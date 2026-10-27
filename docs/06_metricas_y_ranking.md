# 6. Métricas y ranking

El módulo `simulador/metricas.py` lee `snapshots_portafolio` y calcula métricas de la trayectoria de cada agente. La interfaz vuelve a presentar los resultados y agrega conteos de órdenes y decisiones registrados en PostgreSQL.

## Fórmulas

Sea `V0` el capital inicial y `Vt` el valor del snapshot al cierre del día `t`:

- **Retorno diario:** `rt = Vt / V(t-1) - 1`. El primer valor anterior es el capital inicial.
- **Retorno total:** `(Vfinal / V0 - 1) × 100`.
- **Volatilidad anualizada:** desviación estándar muestral de retornos diarios `× √252`.
- **Sharpe simplificado:** media de retornos diarios `/` desviación estándar `× √252`. Se asume tasa libre de riesgo igual a cero.
- **Drawdown:** `Vt / máximo(V0 … Vt) - 1`. El drawdown máximo es el menor valor de esa serie y se muestra como porcentaje negativo o cero.
- **Ganancia/pérdida:** valor final menos capital inicial.
- **Operaciones:** cantidad de filas ejecutadas en `ordenes`.
- **Decisiones inválidas (%):** decisiones con `es_valida = false` divididas entre todas las decisiones del agente.
- **Latencia media:** promedio de `latencia_ms` válidas y mayores que cero.

Con muy pocos snapshots Sharpe y volatilidad son inestables; no deben interpretarse como pronósticos. El Sharpe de esta implementación no descuenta una tasa libre de riesgo.

## Clasificación y fuentes

La vista `vw_metricas_finales` resume el último snapshot, P/L, operaciones, decisiones inválidas y latencia. `simulador/metricas.py` calcula las métricas que requieren una serie ordenada de snapshots. El ranking de la interfaz ordena primero por retorno total descendente y usa Sharpe descendente como desempate.

El punto de partida de las series es el capital inicial. Por eso el gráfico puede mostrar el estado antes del primer snapshot guardado. El benchmark “Comprar y mantener” es un agente adicional y se incluye en la misma comparación.

## Archivos y gráficos

Ejecutar `python -m simulador.metricas` desde la raíz genera:

- `reports/ranking_agentes.csv`
- `reports/evolucion_portafolios.csv`
- `reports/graficos_agentes.html` (gráfico interactivo autocontenido)

La página **Métricas** muestra la tabla, la rentabilidad, la evolución del portafolio frente al benchmark y las operaciones. Permite descargar el ranking y la evolución en CSV. La exportación de gráficos a PNG todavía no está implementada en el código actual.

## Cómo probar y leerlo

1. Ejecuta una simulación o avanza un día desde la interfaz.
2. Abre **Métricas** y compara el retorno con el drawdown y el número de operaciones.
3. Ejecuta `.\.venv\Scripts\python.exe -m simulador.metricas` para crear los archivos de `reports/`.
4. Abre `reports/graficos_agentes.html` en un navegador.

Un retorno de 0 % puede significar que el portafolio terminó con el mismo valor que el capital inicial; consulta órdenes y decisiones antes de concluir por qué no operó un agente.
