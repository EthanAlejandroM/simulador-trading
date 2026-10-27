-- Los procedimientos consultan el precio de cierre en la BD.
-- Una excepción cancela los cambios de la llamada actual.

CREATE OR REPLACE FUNCTION fn_valor_portafolio(
    p_agente_id bigint,
    p_fecha date
)
RETURNS numeric(18, 2)
LANGUAGE plpgsql
AS $$
DECLARE
    v_efectivo numeric(18, 2);
    v_posiciones numeric(24, 6);
BEGIN
    SELECT saldo_efectivo
    INTO v_efectivo
    FROM portafolios
    WHERE agente_id = p_agente_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe portafolio para el agente %', p_agente_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM posiciones AS po
        LEFT JOIN precios_historicos AS ph
            ON ph.ticker = po.ticker
           AND ph.fecha = p_fecha
        WHERE po.agente_id = p_agente_id
          AND ph.ticker IS NULL
    ) THEN
        RAISE EXCEPTION
            'Falta precio de cierre de una posición del agente % para %',
            p_agente_id, p_fecha;
    END IF;

    SELECT coalesce(sum(po.cantidad * ph.close), 0)
    INTO v_posiciones
    FROM posiciones AS po
    JOIN precios_historicos AS ph
      ON ph.ticker = po.ticker
     AND ph.fecha = p_fecha
    WHERE po.agente_id = p_agente_id;

    RETURN (v_efectivo + v_posiciones)::numeric(18, 2);
END;
$$;

CREATE OR REPLACE PROCEDURE sp_registrar_compra(
    p_agente_id bigint,
    p_ticker text,
    p_cantidad bigint,
    p_fecha date
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_precio numeric(18, 6);
    v_saldo numeric(18, 2);
    v_comision_pct numeric(8, 6);
    v_limite numeric(5, 4);
    v_comision numeric(18, 2);
    v_costo numeric(24, 6);
    v_valor_actual numeric(18, 2);
    v_cantidad_actual bigint;
    v_valor_posicion numeric(24, 6);
BEGIN
    IF p_cantidad IS NULL OR p_cantidad <= 0 THEN
        RAISE EXCEPTION 'La cantidad de compra debe ser mayor que cero';
    END IF;

    SELECT close INTO v_precio
    FROM precios_historicos
    WHERE ticker = upper(p_ticker) AND fecha = p_fecha;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe precio de cierre para % en %',
            upper(p_ticker), p_fecha;
    END IF;

    -- El portafolio serializa las operaciones del agente.
    SELECT saldo_efectivo INTO v_saldo
    FROM portafolios
    WHERE agente_id = p_agente_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe portafolio para el agente %', p_agente_id;
    END IF;

    SELECT comision_porcentaje, limite_por_accion
    INTO v_comision_pct, v_limite
    FROM configuracion_simulacion
    WHERE configuracion_id = 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Falta la configuración de la simulación';
    END IF;

    v_comision := round(p_cantidad * v_precio * v_comision_pct, 2);
    v_costo := p_cantidad * v_precio + v_comision;

    IF v_saldo < v_costo THEN
        RAISE EXCEPTION
            'Saldo insuficiente: disponible %, costo total %',
            v_saldo, v_costo;
    END IF;

    PERFORM 1
    FROM posiciones
    WHERE agente_id = p_agente_id AND ticker = upper(p_ticker)
    FOR UPDATE;

    SELECT coalesce(cantidad, 0)
    INTO v_cantidad_actual
    FROM posiciones
    WHERE agente_id = p_agente_id AND ticker = upper(p_ticker);

    v_cantidad_actual := coalesce(v_cantidad_actual, 0);
    v_valor_actual := fn_valor_portafolio(p_agente_id, p_fecha);
    v_valor_posicion := (v_cantidad_actual + p_cantidad) * v_precio;

    -- La comisión reduce el valor total del portafolio.
    IF v_valor_actual - v_comision <= 0
       OR v_valor_posicion > (v_valor_actual - v_comision) * v_limite
    THEN
        RAISE EXCEPTION
            'La compra excede el límite de concentración de %%% para %',
            round(v_limite * 100, 2), upper(p_ticker);
    END IF;

    UPDATE portafolios
    SET saldo_efectivo = saldo_efectivo - v_costo
    WHERE agente_id = p_agente_id;

    INSERT INTO posiciones (agente_id, ticker, cantidad, costo_promedio)
    VALUES (p_agente_id, upper(p_ticker), p_cantidad, v_precio)
    ON CONFLICT (agente_id, ticker) DO UPDATE
    SET cantidad = posiciones.cantidad + EXCLUDED.cantidad,
        costo_promedio = (
            posiciones.cantidad * posiciones.costo_promedio
            + EXCLUDED.cantidad * EXCLUDED.costo_promedio
        ) / (posiciones.cantidad + EXCLUDED.cantidad),
        actualizada_en = now();

    INSERT INTO ordenes (
        agente_id, ticker, tipo, cantidad, precio, comision, fecha
    )
    VALUES (
        p_agente_id, upper(p_ticker), 'COMPRA', p_cantidad,
        v_precio, v_comision, p_fecha
    );
END;
$$;

CREATE OR REPLACE PROCEDURE sp_registrar_venta(
    p_agente_id bigint,
    p_ticker text,
    p_cantidad bigint,
    p_fecha date
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_precio numeric(18, 6);
    v_saldo numeric(18, 2);
    v_cantidad_actual bigint;
    v_comision_pct numeric(8, 6);
    v_comision numeric(18, 2);
    v_ingreso numeric(24, 6);
BEGIN
    IF p_cantidad IS NULL OR p_cantidad <= 0 THEN
        RAISE EXCEPTION 'La cantidad de venta debe ser mayor que cero';
    END IF;

    SELECT close INTO v_precio
    FROM precios_historicos
    WHERE ticker = upper(p_ticker) AND fecha = p_fecha;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe precio de cierre para % en %',
            upper(p_ticker), p_fecha;
    END IF;

    SELECT saldo_efectivo INTO v_saldo
    FROM portafolios
    WHERE agente_id = p_agente_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe portafolio para el agente %', p_agente_id;
    END IF;

    SELECT cantidad INTO v_cantidad_actual
    FROM posiciones
    WHERE agente_id = p_agente_id
      AND ticker = upper(p_ticker)
    FOR UPDATE;

    IF NOT FOUND OR v_cantidad_actual < p_cantidad THEN
        RAISE EXCEPTION
            'Posición insuficiente para vender % de %; disponible %',
            p_cantidad, upper(p_ticker), coalesce(v_cantidad_actual, 0);
    END IF;

    SELECT comision_porcentaje INTO v_comision_pct
    FROM configuracion_simulacion
    WHERE configuracion_id = 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Falta la configuración de la simulación';
    END IF;

    v_comision := round(p_cantidad * v_precio * v_comision_pct, 2);
    v_ingreso := p_cantidad * v_precio - v_comision;

    UPDATE portafolios
    SET saldo_efectivo = saldo_efectivo + v_ingreso
    WHERE agente_id = p_agente_id;

    IF v_cantidad_actual = p_cantidad THEN
        DELETE FROM posiciones
        WHERE agente_id = p_agente_id AND ticker = upper(p_ticker);
    ELSE
        UPDATE posiciones
        SET cantidad = cantidad - p_cantidad,
            actualizada_en = now()
        WHERE agente_id = p_agente_id AND ticker = upper(p_ticker);
    END IF;

    INSERT INTO ordenes (
        agente_id, ticker, tipo, cantidad, precio, comision, fecha
    )
    VALUES (
        p_agente_id, upper(p_ticker), 'VENTA', p_cantidad,
        v_precio, v_comision, p_fecha
    );
END;
$$;

CREATE OR REPLACE PROCEDURE sp_tomar_snapshot(p_fecha date)
LANGUAGE plpgsql
AS $$
DECLARE
    v_agente record;
    v_valor numeric(18, 2);
    v_efectivo numeric(18, 2);
BEGIN
    FOR v_agente IN
        SELECT a.agente_id
        FROM agentes AS a
        JOIN portafolios AS p ON p.agente_id = a.agente_id
        WHERE a.activo
        ORDER BY a.agente_id
    LOOP
        v_valor := fn_valor_portafolio(v_agente.agente_id, p_fecha);

        SELECT saldo_efectivo INTO v_efectivo
        FROM portafolios
        WHERE agente_id = v_agente.agente_id;

        INSERT INTO snapshots_portafolio (
            agente_id, fecha, valor_total, saldo_efectivo
        )
        VALUES (v_agente.agente_id, p_fecha, v_valor, v_efectivo)
        ON CONFLICT (agente_id, fecha) DO UPDATE
        SET valor_total = EXCLUDED.valor_total,
            saldo_efectivo = EXCLUDED.saldo_efectivo,
            creado_en = now();
    END LOOP;
END;
$$;