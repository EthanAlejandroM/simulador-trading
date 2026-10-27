# 5. Motor de simulación

`simulador/motor.py` orquesta el procesamiento de fechas. Primero se asegura de
que existan los cuatro agentes y el benchmark, cada uno con el mismo capital
inicial. Luego obtiene los días con precios para todos los tickers y procesa
hasta los últimos 30 días hábiles configurados.

Para cada agente y fecha, el motor:

1. Calcula indicadores con cotizaciones hasta esa fecha inclusive.
2. Lee efectivo y posiciones del portafolio.
3. Construye el contexto de mercado y llama a Ollama una vez.
4. Valida y registra las decisiones.
5. Llama a `sp_registrar_compra` o `sp_registrar_venta`.
6. Registra el snapshot de todos los portafolios al terminar el día.

El benchmark compra una cesta con presupuesto aproximadamente igual por ticker
el primer día y luego mantiene las posiciones. Se procesa con el mismo orden de
precios y las mismas reglas de ejecución.

## Reanudación

Una jornada de un agente se considera completa cuando hay una decisión guardada
para cada ticker configurado. Si se reinicia el programa, esas jornadas se
omiten y se continúa con las pendientes. Las operaciones de cada agente y fecha
se guardan en una transacción; si falla una operación, su procedimiento se
revierte mediante un savepoint y el motivo queda en `decisiones_agentes`.

## Modo `--dry-run`

El comando `python -m simulador.motor --dry-run` usa un agente temporal con reglas
fijas durante los últimos tres días disponibles. Prueba decisiones,
procedimientos y snapshots sin llamar a Ollama. Al terminar revierte todos los
cambios de prueba.

## Tiempo de ejecución

El motor informa progreso por día y una estimación de tiempo restante. La
simulación completa puede tardar, porque corre en CPU y necesita una llamada de
Ollama por agente y día. Las jornadas con JSON inválido pueden requerir un
segundo intento.