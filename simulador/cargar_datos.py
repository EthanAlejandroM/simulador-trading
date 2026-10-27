"""Valida el CSV de precios y lo carga en PostgreSQL."""

import logging

import pandas as pd
import psycopg

from simulador.configuracion import (
    cargar_configuracion,
    obtener_parametros_bd,
    obtener_ruta_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

COLUMNAS_REQUERIDAS = {
    "ticker",
    "fecha",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


def leer_y_validar_csv(ruta_csv) -> pd.DataFrame:
    """Carga el CSV y valida datos antes de abrir una transacción."""
    if not ruta_csv.exists():
        raise FileNotFoundError(
            f"No existe {ruta_csv}. Ejecuta primero "
            "'python -m simulador.descargar_datos'."
        )

    precios = pd.read_csv(ruta_csv)

    faltantes = COLUMNAS_REQUERIDAS - set(precios.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas en el CSV: {sorted(faltantes)}")

    precios = precios[list(COLUMNAS_REQUERIDAS)].copy()
    precios["ticker"] = precios["ticker"].astype(str).str.strip().str.upper()
    precios["fecha"] = pd.to_datetime(
        precios["fecha"], errors="raise"
    ).dt.date

    for columna in ("open", "high", "low", "close", "volume"):
        precios[columna] = pd.to_numeric(precios[columna], errors="raise")

    if precios.isna().any().any():
        raise ValueError("El CSV contiene valores vacíos.")

    if (precios[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Los precios deben ser mayores que cero.")

    if (precios["volume"] < 0).any():
        raise ValueError("El volumen no puede ser negativo.")

    if (precios["volume"] % 1 != 0).any():
        raise ValueError("El volumen debe estar expresado como número entero.")

    if (precios["high"] < precios[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("Hay filas donde high es menor que open, close o low.")

    if (precios["low"] > precios[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("Hay filas donde low es mayor que open, close o high.")

    if precios.duplicated(["ticker", "fecha"]).any():
        raise ValueError("El CSV tiene filas repetidas por ticker y fecha.")

    precios["volume"] = precios["volume"].astype("int64")
    return precios.sort_values(["ticker", "fecha"]).reset_index(drop=True)


def cargar_en_postgres(precios: pd.DataFrame) -> None:
    """Inserta tickers y cotizaciones; actualiza filas ya existentes."""
    tickers = sorted(precios["ticker"].unique())

    sql_accion = """
        INSERT INTO acciones (ticker, nombre)
        VALUES (%s, %s)
        ON CONFLICT (ticker) DO NOTHING;
    """

    sql_precio = """
        INSERT INTO precios_historicos
            (ticker, fecha, open, high, low, close, volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, fecha) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """

    filas = [
        (
            fila.ticker,
            fila.fecha,
            float(fila.open),
            float(fila.high),
            float(fila.low),
            float(fila.close),
            int(fila.volume),
        )
        for fila in precios.itertuples(index=False)
    ]

    # El bloque de conexión hace commit si todo funciona y rollback si falla.
    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        with conexion.cursor() as cursor:
            cursor.executemany(
                sql_accion,
                [(ticker, ticker) for ticker in tickers],
            )
            cursor.executemany(sql_precio, filas)

    logger.info(
        "Carga completada: %s tickers y %s cotizaciones.",
        len(tickers),
        len(filas),
    )


def main() -> None:
    configuracion = cargar_configuracion()
    ruta_csv = obtener_ruta_csv(configuracion)
    precios = leer_y_validar_csv(ruta_csv)
    cargar_en_postgres(precios)


if __name__ == "__main__":
    main()