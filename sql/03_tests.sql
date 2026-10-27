-- Prueba aislada: crea datos temporales, ejecuta casos y revierte todo.
-- No ejecutar en paralelo con otra copia de este mismo archivo.

BEGIN;

INSERT INTO usuarios (nombre, email)
VALUES ('Usuario de pruebas', 'pruebas-fase1@local.invalid');

INSERT INTO agentes (usuario_id, nombre, estrategia, descripcion)
SELECT usuario_id, 'Agente prueba', 'CONSERVADOR', 'Pruebas de procedimientos'
FROM usuarios
WHERE email = 'pruebas-fase1@local.invalid';

INSERT INTO agentes (usuario_id, nombre, estrategia, descripcion)
SELECT usuario_id, 'Agente saldo bajo', 'CONSERVADOR', 'Prueba de saldo insuficiente'
FROM usuarios
WHERE email = 'pruebas-fase1@local.invalid';

INSERT INTO acciones (ticker, nombre)
VALUES ('TST1', 'Acción de prueba'), ('TST2', 'Acción costosa');

INSERT INTO precios_historicos (ticker, fecha, open, high, low, close, volume)
VALUES
    ('TST1', DATE '2026-01-05', 100, 110, 95, 100, 1000),
    ('TST1', DATE '2026-01-06', 100, 120, 99, 110, 1200),
    ('TST2', DATE '2026-01-05', 1000, 1000, 1000, 1000, 500);

INSERT INTO portafolios (agente_id, capital_inicial, saldo_efectivo)
SELECT agente_id, 100000, 100000
FROM agentes
WHERE nombre = 'Agente prueba';

INSERT INTO portafolios (agente_id, capital_inicial, saldo_efectivo)
SELECT agente_id, 100, 100
FROM agentes
WHERE nombre = 'Agente saldo bajo';

-- Los SELECT asignan los ID a variables antes de llamar a los procedimientos.
DO $$
DECLARE
    v_agente_prueba bigint;
    v_agente_saldo_bajo bigint;
BEGIN
    SELECT agente_id INTO v_agente_prueba
    FROM agentes
    WHERE nombre = 'Agente prueba';

    SELECT agente_id INTO v_agente_saldo_bajo
    FROM agentes
    WHERE nombre = 'Agente saldo bajo';

    -- Compra y venta válidas.
    CALL sp_registrar_compra(
        v_agente_prueba, 'TST1', 10, DATE '2026-01-05'
    );

    CALL sp_registrar_venta(
        v_agente_prueba, 'TST1', 10, DATE '2026-01-06'
    );

    -- Se espera rechazo por saldo insuficiente.
    BEGIN
        CALL sp_registrar_compra(
            v_agente_saldo_bajo, 'TST2', 1, DATE '2026-01-05'
        );

        RAISE EXCEPTION USING
            ERRCODE = 'Z0001',
            MESSAGE = 'La compra debía fallar por saldo insuficiente';
    EXCEPTION
        WHEN SQLSTATE 'P0001' THEN
            RAISE NOTICE 'Correcto: se rechazó la compra por saldo insuficiente';
    END;

    -- Se espera rechazo porque el agente no tiene TST1.
    BEGIN
        CALL sp_registrar_venta(
            v_agente_saldo_bajo, 'TST1', 1, DATE '2026-01-05'
        );

        RAISE EXCEPTION USING
            ERRCODE = 'Z0001',
            MESSAGE = 'La venta debía fallar por falta de posición';
    EXCEPTION
        WHEN SQLSTATE 'P0001' THEN
            RAISE NOTICE 'Correcto: se rechazó la venta sin posición';
    END;
END;
$$;

-- Deben aparecer las dos operaciones válidas: compra y venta.
SELECT tipo, ticker, cantidad, precio, comision, fecha
FROM ordenes
ORDER BY orden_id;

ROLLBACK;