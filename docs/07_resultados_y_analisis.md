# 7. Resultados y análisis

## Ejecución observada

El 26 de octubre de 2026 se compartió en la conversación una salida de `simulador.metricas`. Se documenta como resultado de esa ejecución, no como medición de la base demo que se está probando ahora:

| Agente | Retorno | Sharpe | Drawdown máximo |
|---|---:|---:|---:|
| Comprar y mantener | 3,49 % | 2,5780 | -2,09 % |
| Agente agresivo | 0,00 % | 0,0000 | 0,00 % |
| Agente especulador | 0,00 % | 0,0000 | 0,00 % |
| Gestor de riesgo | 0,00 % | 0,0000 | 0,00 % |
| Agente conservador | -0,17 % | -2,4758 | -0,23 % |

La salida también informó que los archivos se escribieron en `reports/`. No se atribuye una causa a las rentabilidades de 0 % sin revisar las órdenes y decisiones de esa misma base y periodo. El resultado debe regenerarse al finalizar la prueba actual para que el informe de entrega use la corrida definitiva.

## Cómo regenerar el análisis

Desde PowerShell, en la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m simulador.metricas
```

La tabla y los gráficos de la aplicación consultan los snapshots existentes. Exporta los CSV desde la página **Métricas** o usa los archivos creados en `reports/`. No copies números antiguos a una nueva corrida.

## Límites de interpretación

- La simulación de referencia usa una ventana corta de 30 días hábiles; el rendimiento no predice resultados futuros.
- `llama3.2:3b` corre en CPU y puede proponer decisiones inconsistentes. Python valida el JSON y PostgreSQL valida la operación.
- Comisiones, el límite de concentración, los tickers y el rango temporal afectan el resultado.
- El benchmark tiene una regla distinta (comprar y mantener) y sirve como comparación, no como otro agente LLM.
- El Sharpe simplificado supone tasa libre de riesgo cero y se vuelve poco estable con pocas observaciones.

## Pendiente antes del informe final

**[PENDIENTE: finalizar la simulación de demostración y regenerar métricas desde la base definitiva].** Después se deben reemplazar o confirmar las cifras de esta tabla y explicar cada estrategia consultando tanto órdenes como decisiones.
