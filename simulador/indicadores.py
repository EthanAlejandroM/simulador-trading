"""Cálculo de indicadores usando exclusivamente precios hasta la fecha evaluada."""

import pandas as pd


def calcular_indicadores(
    historial: pd.DataFrame,
    fecha: object,
) -> pd.DataFrame:
    """Calcula retornos, SMA, RSI y volatilidad hasta `fecha`, inclusive."""
    datos = historial.copy()
    datos["fecha"] = pd.to_datetime(datos["fecha"]).dt.date
    fecha_corte = pd.to_datetime(fecha).date()

    # Esta condición evita que cualquier fila futura participe en los cálculos.
    datos = datos.loc[datos["fecha"] <= fecha_corte].copy()
    datos = datos.sort_values(["ticker", "fecha"])

    resultados = []

    for ticker, grupo in datos.groupby("ticker", sort=True):
        grupo = grupo.copy()
        cierre = grupo["close"].astype(float)
        retorno_diario = cierre.pct_change(fill_method=None)

        delta = cierre.diff()
        ganancias = delta.clip(lower=0)
        perdidas = -delta.clip(upper=0)
        ganancia_media = ganancias.rolling(14, min_periods=14).mean()
        perdida_media = perdidas.rolling(14, min_periods=14).mean()

        rs = ganancia_media / perdida_media
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.mask((perdida_media == 0) & (ganancia_media > 0), 100)
        rsi = rsi.mask((perdida_media == 0) & (ganancia_media == 0), 50)

        grupo["retorno_1d_pct"] = cierre.pct_change(1, fill_method=None) * 100
        grupo["retorno_5d_pct"] = cierre.pct_change(5, fill_method=None) * 100
        grupo["retorno_20d_pct"] = cierre.pct_change(20, fill_method=None) * 100
        grupo["sma_5"] = cierre.rolling(5, min_periods=5).mean()
        grupo["sma_20"] = cierre.rolling(20, min_periods=20).mean()
        grupo["rsi_14"] = rsi
        grupo["volatilidad_20_pct"] = (
            retorno_diario.rolling(20, min_periods=20).std() * 100
        )

        resultados.append(grupo.loc[grupo["fecha"] == fecha_corte])

    if not resultados:
        return pd.DataFrame()

    return pd.concat(resultados, ignore_index=True)


def formato_numero(valor: object, decimales: int = 2) -> str:
    """Muestra un número o un guion cuando aún no se puede calcular."""
    if pd.isna(valor):
        return "—"
    return f"{float(valor):.{decimales}f}"