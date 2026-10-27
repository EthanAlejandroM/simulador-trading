-- Esquema base del simulador de trading.
-- Compatible con PostgreSQL 15 o superior.

CREATE TABLE usuarios (
    usuario_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre      text NOT NULL CHECK (length(trim(nombre)) > 0),
    email       text NOT NULL UNIQUE CHECK (position('@' IN email) > 1),
    creado_en   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agentes (
    agente_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id      bigint NOT NULL REFERENCES usuarios(usuario_id),
    nombre          text NOT NULL CHECK (length(trim(nombre)) > 0),
    estrategia      text NOT NULL CHECK (
        estrategia IN (
            'CONSERVADOR',
            'AGRESIVO',
            'ESPECULADOR',
            'GESTOR_RIESGO',
            'BUY_AND_HOLD'
        )
    ),
    descripcion     text NOT NULL,
    activo          boolean NOT NULL DEFAULT true,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (usuario_id, nombre)
);

CREATE TABLE acciones (
    ticker          text PRIMARY KEY CHECK (ticker = upper(ticker)),
    nombre          text NOT NULL CHECK (length(trim(nombre)) > 0),
    mercado         text,
    activa          boolean NOT NULL DEFAULT true
);

CREATE TABLE precios_historicos (
    ticker          text NOT NULL REFERENCES acciones(ticker),
    fecha           date NOT NULL,
    open            numeric(18, 6) NOT NULL CHECK (open > 0),
    high            numeric(18, 6) NOT NULL CHECK (high > 0),
    low             numeric(18, 6) NOT NULL CHECK (low > 0),
    close           numeric(18, 6) NOT NULL CHECK (close > 0),
    volume          bigint NOT NULL CHECK (volume >= 0),
    PRIMARY KEY (ticker, fecha),
    CHECK (high >= low),
    CHECK (high >= greatest(open, close)),
    CHECK (low <= least(open, close))
);

CREATE TABLE portafolios (
    portafolio_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agente_id           bigint NOT NULL UNIQUE REFERENCES agentes(agente_id),
    capital_inicial     numeric(18, 2) NOT NULL CHECK (capital_inicial > 0),
    saldo_efectivo      numeric(18, 2) NOT NULL CHECK (saldo_efectivo >= 0),
    creado_en           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE posiciones (
    posicion_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agente_id           bigint NOT NULL REFERENCES agentes(agente_id),
    ticker              text NOT NULL REFERENCES acciones(ticker),
    cantidad            bigint NOT NULL CHECK (cantidad > 0),
    costo_promedio      numeric(18, 6) NOT NULL CHECK (costo_promedio > 0),
    actualizada_en      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agente_id, ticker)
);

CREATE TABLE decisiones_agentes (
    decision_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agente_id           bigint NOT NULL REFERENCES agentes(agente_id),
    ticker              text NOT NULL REFERENCES acciones(ticker),
    fecha               date NOT NULL,
    accion_decidida     text NOT NULL CHECK (
        accion_decidida IN ('COMPRAR', 'VENDER', 'MANTENER')
    ),
    cantidad            bigint NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
    justificacion       varchar(200) NOT NULL,
    respuesta_json     jsonb NOT NULL,
    modelo              text NOT NULL,
    latencia_ms         integer CHECK (latencia_ms >= 0),
    es_valida           boolean NOT NULL,
    motivo_rechazo      text,
    creada_en           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agente_id, ticker, fecha),
    CHECK (
        (accion_decidida = 'MANTENER' AND cantidad = 0)
        OR accion_decidida IN ('COMPRAR', 'VENDER')
    )
);

CREATE TABLE ordenes (
    orden_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agente_id           bigint NOT NULL REFERENCES agentes(agente_id),
    ticker              text NOT NULL REFERENCES acciones(ticker),
    decision_id         bigint REFERENCES decisiones_agentes(decision_id),
    tipo                text NOT NULL CHECK (tipo IN ('COMPRA', 'VENTA')),
    cantidad            bigint NOT NULL CHECK (cantidad > 0),
    precio              numeric(18, 6) NOT NULL CHECK (precio > 0),
    comision            numeric(18, 2) NOT NULL CHECK (comision >= 0),
    estado              text NOT NULL DEFAULT 'EJECUTADA'
                        CHECK (estado IN ('EJECUTADA')),
    fecha               date NOT NULL,
    creada_en           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE snapshots_portafolio (
    snapshot_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agente_id           bigint NOT NULL REFERENCES agentes(agente_id),
    fecha               date NOT NULL,
    valor_total         numeric(18, 2) NOT NULL CHECK (valor_total >= 0),
    saldo_efectivo      numeric(18, 2) NOT NULL CHECK (saldo_efectivo >= 0),
    creado_en           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agente_id, fecha)
);

-- Parámetros comunes de las operaciones. Se inicializa una sola fila.
CREATE TABLE configuracion_simulacion (
    configuracion_id   smallint PRIMARY KEY CHECK (configuracion_id = 1),
    comision_porcentaje numeric(8, 6) NOT NULL
                         CHECK (comision_porcentaje >= 0 AND comision_porcentaje <= 1),
    limite_por_accion   numeric(5, 4) NOT NULL
                         CHECK (limite_por_accion > 0 AND limite_por_accion <= 1),
    actualizada_en      timestamptz NOT NULL DEFAULT now()
);

INSERT INTO configuracion_simulacion (
    configuracion_id, comision_porcentaje, limite_por_accion
)
VALUES (1, 0.001, 0.30)
ON CONFLICT (configuracion_id) DO NOTHING;

CREATE INDEX idx_agentes_usuario ON agentes(usuario_id);
CREATE INDEX idx_precios_fecha ON precios_historicos(fecha);
CREATE INDEX idx_decisiones_agente_fecha
    ON decisiones_agentes(agente_id, fecha);
CREATE INDEX idx_ordenes_agente_fecha
    ON ordenes(agente_id, fecha);
CREATE INDEX idx_snapshots_fecha
    ON snapshots_portafolio(fecha);

-- Métricas resumidas por agente usando su snapshot más reciente.
CREATE VIEW vw_metricas_finales AS
WITH ultimo_snapshot AS (
    SELECT DISTINCT ON (s.agente_id)
        s.agente_id,
        s.fecha,
        s.valor_total
    FROM snapshots_portafolio AS s
    ORDER BY s.agente_id, s.fecha DESC
),
conteo_ordenes AS (
    SELECT agente_id, count(*)::bigint AS numero_operaciones
    FROM ordenes
    WHERE estado = 'EJECUTADA'
    GROUP BY agente_id
),
metricas_decisiones AS (
    SELECT
        agente_id,
        count(*)::bigint AS numero_decisiones,
        count(*) FILTER (WHERE NOT es_valida)::bigint AS decisiones_invalidas,
        avg(latencia_ms) AS latencia_promedio_ms
    FROM decisiones_agentes
    GROUP BY agente_id
)
SELECT
    a.agente_id,
    a.nombre AS agente,
    a.estrategia,
    u.fecha AS fecha_ultimo_snapshot,
    p.capital_inicial,
    u.valor_total AS valor_final_portafolio,
    coalesce(u.valor_total - p.capital_inicial, 0)::numeric(18, 2)
        AS ganancia_perdida,
    CASE
        WHEN p.capital_inicial > 0 AND u.valor_total IS NOT NULL
        THEN round(100 * (u.valor_total - p.capital_inicial) / p.capital_inicial, 4)
        ELSE NULL
    END AS rentabilidad_porcentaje,
    coalesce(o.numero_operaciones, 0) AS numero_operaciones,
    coalesce(d.numero_decisiones, 0) AS numero_decisiones,
    coalesce(d.decisiones_invalidas, 0) AS decisiones_invalidas,
    CASE
        WHEN coalesce(d.numero_decisiones, 0) > 0
        THEN round(100.0 * d.decisiones_invalidas / d.numero_decisiones, 2)
        ELSE 0
    END AS porcentaje_decisiones_invalidas,
    d.latencia_promedio_ms
FROM agentes AS a
JOIN portafolios AS p ON p.agente_id = a.agente_id
LEFT JOIN ultimo_snapshot AS u ON u.agente_id = a.agente_id
LEFT JOIN conteo_ordenes AS o ON o.agente_id = a.agente_id
LEFT JOIN metricas_decisiones AS d ON d.agente_id = a.agente_id;