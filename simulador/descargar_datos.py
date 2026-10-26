"""Descarga cotizaciones diarias y las guarda en un CSV reproducible."""

import logging

import pandas as pd
import yfinance as yf

from simulador.configuracion import cargar_configuracion, obtener_ruta_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

COLUMNAS_YAHOO = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}


def descargar_ticker(ticker: str, periodo: str, intervalo: str) -> pd.DataFrame:
    """Descarga un ticker y devuelve columnas normalizadas."""
    historial = yf.Ticker(ticker).history(
        period=periodo,
        interval=intervalo,
        auto_adjust=False,
        actions=False,
    )

    if historial.empty:
        raise RuntimeError(
            f"yfinance no devolvió precios para {ticker}. "
            "Comprueba el ticker y la conexión a internet."
        )

    faltantes = set(COLUMNAS_YAHOO) - set(historial.columns)
    if faltantes:
        raise RuntimeError(
            f"Faltan columnas de precios para {ticker}: {sorted(faltantes)}"
        )

    # El CSV usa fechas sin zona horaria, porque la columna SQL es DATE.
    indice = pd.DatetimeIndex(historial.index)
    if indice.tz is not None:
        indice = indice.tz_localize(None)

    datos = historial.rename(columns=COLUMNAS_YAHOO)[
        list(COLUMNAS_YAHOO.values())
    ].copy()

    datos.insert(0, "fecha", indice.date)
    datos.insert(0, "ticker", ticker.upper())
    datos = datos.dropna(subset=["open", "high", "low", "close", "volume"])

    return datos.reset_index(drop=True)


def main() -> None:
    configuracion = cargar_configuracion()
    periodo = configuracion["datos"]["periodo_descarga"]
    intervalo = configuracion["datos"].get("intervalo", "1d")
    tickers = [str(ticker).upper() for ticker in configuracion["tickers"]]

    partes = []
    for ticker in tickers:
        logger.info("Descargando %s (%s, intervalo %s)", ticker, periodo, intervalo)
        partes.append(descargar_ticker(ticker, periodo, intervalo))

    precios = pd.concat(partes, ignore_index=True)
    precios = precios.sort_values(["fecha", "ticker"]).reset_index(drop=True)

    ruta_csv = obtener_ruta_csv(configuracion)
    ruta_csv.parent.mkdir(parents=True, exist_ok=True)
    precios.to_csv(ruta_csv, index=False, date_format="%Y-%m-%d")

    logger.info(
        "CSV guardado: %s; %s filas; fechas %s a %s",
        ruta_csv,
        len(precios),
        precios["fecha"].min(),
        precios["fecha"].max(),
    )


if __name__ == "__main__":
    main()