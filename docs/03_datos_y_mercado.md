# 3. Datos y mercado

Esta fase descarga precios diarios con yfinance y los guarda en
`data/precios_historicos.csv`. La carga a PostgreSQL lee ese CSV, lo valida y
actualiza las tablas `acciones` y `precios_historicos`.

## Origen y periodo

Los tickers predeterminados son AAPL, MSFT, NVDA, KO, JPM y TSLA. La
configuración usa un año de datos diarios (`1y`). El CSV conserva las columnas
Open, High, Low, Close y Volume como `open`, `high`, `low`, `close` y `volume`.

El descargador desactiva el ajuste automático de precios para obtener las
columnas de precios diarias de forma explícita. La consulta histórica se hace
por ticker y se normalizan las fechas a `DATE`, sin hora ni zona horaria.

La descarga requiere conexión a internet. Una vez creado el CSV, la carga a
PostgreSQL puede repetirse sin volver a descargar datos. El archivo es una
captura de los precios recibidos en ese momento; una descarga futura podría
contener revisiones del proveedor.

## Archivos

- `config.yaml`: tickers, periodo, intervalo y ruta del CSV.
- `.env`: conexión privada de PostgreSQL; no debe subirse a GitHub.
- `.env.example`: nombres de variables de conexión sin credenciales reales.
- `simulador/descargar_datos.py`: descarga y escribe el CSV.
- `simulador/cargar_datos.py`: valida el CSV y hace inserciones o actualizaciones.
- `simulador/configuracion.py`: lee YAML y variables de entorno.

## Validaciones de carga

Antes de conectarse a la base, el cargador comprueba que estén las columnas
requeridas, que no haya valores vacíos ni duplicados por ticker y fecha, que los
precios sean positivos, que el volumen sea entero y que los valores OHLC tengan
un orden coherente.

La carga usa `ON CONFLICT` para permitir volver a ejecutarla. Las acciones y los
precios existentes se conservan; si una cotización ya está registrada, sus
campos OHLCV se actualizan con los valores del CSV.

## Cómo ejecutar

Desde la raíz del proyecto, crea el entorno, copia `.env.example` como `.env`,
edita las credenciales y ejecuta los módulos de descarga y carga. Los comandos
están en el README, que se completará al final del proyecto.

## Limitaciones

yfinance obtiene datos de Yahoo Finance y requiere internet durante la
descarga. La disponibilidad de tickers y datos puede cambiar. El CSV permite
conservar la misma entrada para ejecuciones posteriores, aunque no garantiza que
una nueva descarga del proveedor sea idéntica.