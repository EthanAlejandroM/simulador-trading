# 8. Guía de defensa

## Preguntas probables

### ¿Qué resuelve PostgreSQL en el proyecto?

Guarda precios, portafolios, decisiones, órdenes y snapshots con restricciones relacionales. La base permite consultar y comparar la simulación de manera reproducible.

### ¿Por qué las compras y ventas se hacen con procedimientos almacenados?

El procedimiento obtiene el cierre desde `precios_historicos`, valida saldo o posición, comisión y concentración, y modifica saldo, posición y orden en una operación transaccional. Así Python no decide el precio negociable ni actualiza esas tablas por separado.

### ¿Qué significa ACID aquí?

- **Atomicidad:** la compra o venta completa se confirma o se revierte.
- **Consistencia:** PK, FK, `CHECK` y validaciones mantienen los invariantes.
- **Aislamiento:** `FOR UPDATE` bloquea el portafolio y la posición durante una operación concurrente.
- **Durabilidad:** una vez confirmado el commit, PostgreSQL conserva el cambio.

### ¿Por qué se usa `SELECT ... FOR UPDATE`?

Evita que dos operaciones concurrentes lean el mismo saldo o cantidad y ambas gasten/vendan basándose en el mismo valor anterior.

### ¿Por qué el LLM no calcula los indicadores ni el precio?

Un modelo pequeño puede fallar en aritmética. Python calcula retornos, medias, RSI y volatilidad; PostgreSQL es la fuente del precio de cierre y valida las operaciones. El LLM interpreta la tabla resumida.

### ¿Cómo se evita que el agente vea el futuro?

Los indicadores filtran las cotizaciones para incluir solo fechas menores o iguales a la fecha que se procesa.

### ¿Qué hace el dry-run?

Usa reglas fijas sin Ollama para probar el flujo y revierte los cambios al final. El botón **Avanzar 1 día**, fuera del dry-run, sí persiste el avance en la base demo.

### ¿Qué significa que una decisión sea inválida o rechazada?

Inválida significa que la respuesta del modelo no cumplió el esquema o reglas de validación. Rechazada significa que el procedimiento almacenado impidió ejecutar la operación, por ejemplo por saldo insuficiente. Se conservan para auditoría.

### ¿El agente con más retorno es necesariamente el mejor?

El ranking usa retorno y Sharpe simplificado como desempate. También conviene evaluar drawdown, cantidad de operaciones y calidad de las decisiones; una ventana corta puede distorsionar la clasificación.

## Guion breve para la exposición

1. En **Inicio**, mostrar PostgreSQL, Ollama, el modelo y los datos cargados.
2. En **Mercado**, elegir un ticker y explicar precio, SMA, RSI y volatilidad.
3. En **Simulación**, explicar que el dry-run no usa el modelo y no deja cambios; mostrar un avance de un día en la base demo.
4. En **Agentes**, revisar una justificación y diferenciar decisión inválida de operación rechazada.
5. En **Métricas**, comparar retorno, drawdown, Sharpe y benchmark, mencionando el periodo limitado.
6. Cerrar explicando que es una simulación educativa y que no predice rendimientos reales.

## Preparación

Antes de presentar, carga precios y confirma que la base activa sea `simulador-trading-demo`. No uses la opción de reinicio durante la exposición: elimina el contenido del esquema `public` de la base demo.
