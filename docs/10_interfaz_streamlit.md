# 10. Interfaz Streamlit

La interfaz vive actualmente en `app.py` en la raíz y se inicia con `streamlit run app.py`. El prompt inicial propuso `app/main.py`; esa reorganización aún está pendiente y no se usa en los comandos de este repositorio.

## Páginas

- **Resumen:** estado de PostgreSQL y Ollama, presencia del modelo, conteo de cotizaciones, tickers, agentes y días; cuando hay snapshots presenta el ranking y evolución.
- **Simulación:** restringida a `simulador-trading-demo`; ofrece dry-run reversible, avance de un día, inicio, pausa y reanudación, ETA, progreso y decisiones guardadas recientes.
- **Agentes:** permite consultar portafolios, órdenes y decisiones por agente y fecha; resalta decisiones inválidas y motivos de rechazo.
- **Mercado:** gráficos interactivos por ticker, con precios e indicadores disponibles.
- **Métricas:** clasificación, retorno, drawdown, Sharpe, operaciones, decisiones inválidas, latencia y CSV descargables.
- **Configuración y datos:** guarda tickers, rango temporal, capital, días y modelo en `config.yaml`; permite descargar datos, guardar comisión, cargar el CSV y crear o reiniciar la base demo.

## Creación y reinicio de la base demo

La opción de la página **Configuración y datos** solo se activa cuando `.env` apunta exactamente a `simulador-trading-demo`. Exige marcar una casilla y escribir el nombre completo de la base.

- Si la base no existe, intenta crearla usando los permisos del usuario de PostgreSQL (`CREATEDB`).
- Si ya existe, elimina los objetos y datos del esquema `public`, luego vuelve a aplicar `sql/01_schema.sql` y `sql/02_procedures.sql`.
- Si hay sesiones abiertas a la base demo, cancela el reinicio; cierra antes conexiones externas como pgAdmin.
- Si el esquema se crea correctamente, carga nuevamente el CSV desde la interfaz antes de simular.
- La operación no modifica otras bases. La comprobación también existe dentro del servicio Python, no solo en el botón.

El reset del esquema se ejecuta dentro de una transacción. Si falla la aplicación de los scripts, PostgreSQL revierte el borrado y la creación del esquema. La creación inicial de una base es una operación separada y requiere permiso `CREATEDB`.

## Separación de responsabilidades

`app.py` presenta páginas, filtros y gráficos. `simulador/servicios_interfaz.py` escribe configuración, descarga/carga CSV, modifica comisión y prepara el esquema demo. `simulador/control_interfaz.py` usa las funciones del motor para controlar jornadas. Las operaciones de compra y venta siguen pasando por los procedimientos almacenados; la interfaz no inserta órdenes.

La interfaz usa `st.cache_data` para el estado del sistema y fragmentos que actualizan partes de la página. El control de simulación se mantiene como recurso de Streamlit y ejecuta el lote automático en un hilo. El dry-run llama al motor con reglas fijas y no invoca Ollama.

## Cómo ejecutar

Desde PowerShell en la carpeta raíz:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

La prueba de un día y la simulación normal guardan los cambios en la base demo. El dry-run informa que revirtió cambios al terminar. Para confirmar el resultado de un día, abre **Agentes** y revisa snapshots, órdenes y decisiones.
