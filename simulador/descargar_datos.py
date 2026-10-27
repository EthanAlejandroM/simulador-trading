"""Descarga cotizaciones diarias y las guarda en un CSV reproducible."""

import logging
from datetime import date, timedelta

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


def descargar_ticker(
    ticker: str,
    periodo: str,
    intervalo: str,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
) -> pd.DataFrame:
    """Descarga un ticker por periodo o por un rango de fechas inclusivo."""
    parametros = {
        "interval": intervalo,
        "auto_adjust": False,
        "actions": False,
    }

    if fecha_inicio and fecha_fin:
        fecha_fin_exclusiva = fecha_fin + timedelta(days=1)
        parametros["start"] = fecha_inicio.isoformat()
        parametros["end"] = fecha_fin_exclusiva.isoformat()
    else:
        parametros["period"] = periodo

    historial = yf.Ticker(ticker).history(**parametros)

    if historial.empty:
        raise RuntimeError(
            f"yfinance no devolvió precios para {ticker}. "
            "Comprueba el ticker, el rango y la conexión a internet."
        )

    faltantes = set(COLUMNAS_YAHOO) - set(historial.columns)
    if faltantes:
        raise RuntimeError(
            f"Faltan columnas de precios para {ticker}: {sorted(faltantes)}"
        )

    indice = pd.DatetimeIndex(historial.index)
    if indice.tz is not None:
        indice = indice.tz_localize(None)

    datos = historial.rename(columns=COLUMNAS_YAHOO)[
        list(COLUMNAS_YAHOO.values())
    ].copy()

    datos.insert(0, "fecha", indice.date)
    datos.insert(0, "ticker", ticker.upper())
    datos = datos.dropna(
        subset=["open", "high", "low", "close", "volume"]
    )

    return datos.reset_index(drop=True)


def descargar_tickers(
    tickers: list[str],
    periodo: str,
    intervalo: str,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
) -> pd.DataFrame:
    """Descarga y combina las cotizaciones de varios tickers."""
    partes = []

    for ticker in tickers:
        ticker = str(ticker).upper()
        logger.info("Descargando %s", ticker)
        partes.append(
            descargar_ticker(
                ticker,
                periodo,
                intervalo,
                fecha_inicio,
                fecha_fin,
            )
        )

    if not partes:
        raise ValueError("Selecciona al menos un ticker.")

    precios = pd.concat(partes, ignore_index=True)
    return precios.sort_values(
        ["fecha", "ticker"]
    ).reset_index(drop=True)


def guardar_csv(precios: pd.DataFrame) -> str:
    """Guarda las cotizaciones en la ruta configurada."""
    configuracion = cargar_configuracion()
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
    return str(ruta_csv)


def main() -> None:
    configuracion = cargar_configuracion()
    datos_config = configuracion["datos"]
    tickers = [
        str(ticker).upper()
        for ticker in configuracion["tickers"]
    ]

    fecha_inicio = datos_config.get("fecha_inicio")
    fecha_fin = datos_config.get("fecha_fin")

    if fecha_inicio:
        fecha_inicio = date.fromisoformat(str(fecha_inicio))
    if fecha_fin:
        fecha_fin = date.fromisoformat(str(fecha_fin))

    precios = descargar_tickers(
        tickers=tickers,
        periodo=datos_config["periodo_descarga"],
        intervalo=datos_config.get("intervalo", "1d"),
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )
    guardar_csv(precios)


if __name__ == "__main__":
    main()