# 4. Agentes y prompts

Los cuatro agentes usan el mismo modelo de Ollama; sus estrategias se diferencian
solo por el prompt de sistema. Los prompts completos están en
`agents/prompts.py`.

- **Conservador:** prioriza estabilidad, baja volatilidad y efectivo.
- **Agresivo:** busca momentum y crecimiento.
- **Especulador:** observa retornos cortos y RSI extremo.
- **Gestor de riesgo:** prioriza diversificación y reducción de riesgo.
- **Comprar y mantener:** benchmark fijo sin LLM.

## Datos de entrada

Cada agente recibe efectivo, posiciones e indicadores para todos los tickers:
retornos de 1, 5 y 20 días, SMA 5 y 20, RSI 14 y volatilidad de 20 días.
`simulador/indicadores.py` filtra los precios con `fecha <= fecha_evaluada`
antes de calcularlos. Así, ninguna fila posterior entra en los indicadores.

## Respuesta y validación

Ollama recibe un esquema JSON estructurado con `decisiones`, ticker, acción,
cantidad y justificación. La respuesta admite hasta tres decisiones. Pydantic
valida el esquema y el motor verifica que no haya tickers desconocidos,
duplicados ni cantidades incompatibles con la acción.

Si la respuesta no valida, el motor repite la llamada una vez. Si vuelve a
fallar, guarda decisiones MANTENER inválidas para los tickers de esa jornada.
Los errores de conexión con Ollama detienen la ejecución para poder corregir el
servicio; no se registran como JSON inválido.

Python calcula los indicadores porque un modelo pequeño puede equivocarse en
aritmética. Ollama interpreta la tabla y propone decisiones; PostgreSQL valida
y ejecuta las operaciones.