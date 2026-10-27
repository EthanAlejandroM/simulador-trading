"""Motor diario: dry-run reversible y simulación completa con Ollama."""

import argparse
import logging
import math
import time
import uuid
from datetime import date

import pandas as pd
import psycopg
from ollama import Client
from psycopg.types.json import Jsonb

from agents.prompts import PROMPTS
from simulador.configuracion import (
    cargar_configuracion,
    obtener_parametros_bd,
)
from simulador.decisiones import consultar_ollama
from simulador.indicadores import calcular_indicadores, formato_numero

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

ESTRATEGIAS = {
    "CONSERVADOR": ("Agente conservador", "CONSERVADOR"),
    "AGRESIVO": ("Agente agresivo", "AGRESIVO"),
    "ESPECULADOR": ("Agente especulador", "ESPECULADOR"),
    "GESTOR_RIESGO": ("Gestor de riesgo", "GESTOR_RIESGO"),
    "BENCHMARK": ("Comprar y mantener", "BUY_AND_HOLD"),
}


class RevertirDryRun(Exception):
    """Fuerza el rollback de todos los cambios del modo dry-run."""


def cargar_historial() -> pd.DataFrame:
    """Lee todos los precios de PostgreSQL para calcular indicadores históricos."""
    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        filas = conexion.execute(
            """
            SELECT ticker, fecha, open, high, low, close, volume
            FROM precios_historicos
            ORDER BY ticker, fecha
            """
        ).fetchall()

    if not filas:
        raise RuntimeError("No hay precios cargados en precios_historicos.")

    return pd.DataFrame(
        filas,
        columns=["ticker", "fecha", "open", "high", "low", "close", "volume"],
    )


def fechas_comunes(
    historial: pd.DataFrame,
    tickers: list[str],
    cantidad: int,
) -> list[date]:
    """Devuelve las últimas fechas que tienen precio para todos los tickers."""
    filas = historial.loc[historial["ticker"].isin(tickers)]
    conteos = filas.groupby("fecha")["ticker"].nunique()
    fechas = sorted(conteos[conteos == len(tickers)].index)

    if not fechas:
        raise RuntimeError("No hay una fecha con precios para todos los tickers.")

    return fechas[-cantidad:]


def asegurar_agentes(capital_inicial: float) -> list[tuple[int, str, str]]:
    """Crea, si faltan, los cuatro agentes y el benchmark con capital igual."""
    resultado = []

    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        with conexion.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO usuarios (nombre, email)
                VALUES ('Simulador de trading', 'simulador@local.invalid')
                ON CONFLICT (email) DO NOTHING
                """
            )
            usuario_id = cursor.execute(
                """
                SELECT usuario_id FROM usuarios
                WHERE email = 'simulador@local.invalid'
                """
            ).fetchone()[0]

            for clave, (nombre, estrategia) in ESTRATEGIAS.items():
                cursor.execute(
                    """
                    INSERT INTO agentes (usuario_id, nombre, estrategia, descripcion)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (usuario_id, nombre) DO NOTHING
                    """,
                    (
                        usuario_id,
                        nombre,
                        estrategia,
                        f"Agente de estrategia {estrategia.lower()}",
                    ),
                )
                agente_id = cursor.execute(
                    """
                    SELECT agente_id FROM agentes
                    WHERE usuario_id = %s AND nombre = %s
                    """,
                    (usuario_id, nombre),
                ).fetchone()[0]

                cursor.execute(
                    """
                    INSERT INTO portafolios
                        (agente_id, capital_inicial, saldo_efectivo)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (agente_id) DO NOTHING
                    """,
                    (agente_id, capital_inicial, capital_inicial),
                )
                resultado.append((agente_id, nombre, estrategia))

    return resultado


def agente_ya_procesado(agente_id: int, fecha: date, tickers: list[str]) -> bool:
    """Usa una decisión por ticker como marca de día completado para reanudar."""
    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        cantidad = conexion.execute(
            """
            SELECT count(DISTINCT ticker)
            FROM decisiones_agentes
            WHERE agente_id = %s AND fecha = %s AND ticker = ANY(%s)
            """,
            (agente_id, fecha, tickers),
        ).fetchone()[0]

    return cantidad == len(tickers)


def obtener_estado(agente_id: int) -> tuple[float, dict[str, int]]:
    """Lee efectivo y cantidades actuales del agente."""
    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        efectivo = conexion.execute(
            "SELECT saldo_efectivo FROM portafolios WHERE agente_id = %s",
            (agente_id,),
        ).fetchone()[0]
        filas = conexion.execute(
            """
            SELECT ticker, cantidad
            FROM posiciones
            WHERE agente_id = %s
            """,
            (agente_id,),
        ).fetchall()

    return float(efectivo), {ticker: int(cantidad) for ticker, cantidad in filas}

def obtener_estado_en_conexion(
    conexion: psycopg.Connection,
    agente_id: int,
) -> tuple[float, dict[str, int]]:
    """Lee el estado dentro de la misma conexión y transacción actual."""
    fila_efectivo = conexion.execute(
        "SELECT saldo_efectivo FROM portafolios WHERE agente_id = %s",
        (agente_id,),
    ).fetchone()

    if fila_efectivo is None:
        raise RuntimeError(
            f"No existe portafolio para el agente temporal {agente_id}."
        )

    filas = conexion.execute(
        """
        SELECT ticker, cantidad
        FROM posiciones
        WHERE agente_id = %s
        """,
        (agente_id,),
    ).fetchall()

    return float(fila_efectivo[0]), {
        ticker: int(cantidad) for ticker, cantidad in filas
    }

def construir_mensaje(
    fecha: date,
    efectivo: float,
    posiciones: dict[str, int],
    indicadores: pd.DataFrame,
) -> str:
    """Prepara la tabla de mercado compacta que recibe el LLM."""
    if posiciones:
        texto_posiciones = ", ".join(
            f"{ticker}: {cantidad} acciones"
            for ticker, cantidad in sorted(posiciones.items())
        )
    else:
        texto_posiciones = "Sin posiciones."

    lineas = [
        f"Fecha de decisión: {fecha}",
        f"Efectivo disponible: USD {efectivo:,.2f}",
        f"Posiciones: {texto_posiciones}",
        "",
        "Indicadores al cierre del día (retornos y volatilidad en %):",
        "ticker | close | retorno_1d | retorno_5d | retorno_20d | "
        "SMA_5 | SMA_20 | RSI_14 | volatilidad_20d",
    ]

    for fila in indicadores.itertuples(index=False):
        lineas.append(
            f"{fila.ticker} | {formato_numero(fila.close)} | "
            f"{formato_numero(fila.retorno_1d_pct)} | "
            f"{formato_numero(fila.retorno_5d_pct)} | "
            f"{formato_numero(fila.retorno_20d_pct)} | "
            f"{formato_numero(fila.sma_5)} | "
            f"{formato_numero(fila.sma_20)} | "
            f"{formato_numero(fila.rsi_14)} | "
            f"{formato_numero(fila.volatilidad_20_pct)}"
        )

    lineas.append(
        "\nDevuelve JSON con hasta 3 decisiones. No uses información posterior "
        "a la fecha indicada."
    )
    return "\n".join(lineas)


def decisiones_benchmark(
    fecha: date,
    indicadores: pd.DataFrame,
    primera_fecha: date,
    capital_inicial: float,
) -> tuple[list[dict], dict]:
    """Compra una cesta de igual presupuesto el primer día y luego mantiene."""
    decisiones = []

    for fila in indicadores.itertuples(index=False):
        cantidad = 0
        accion = "MANTENER"
        justificacion = "Benchmark comprar y mantener."

        if fecha == primera_fecha:
            presupuesto = capital_inicial / max(1, len(indicadores))
            cantidad = math.floor(presupuesto / float(fila.close))
            if cantidad > 0:
                accion = "COMPRAR"
                justificacion = "Compra inicial de la cesta benchmark."

        decisiones.append({
            "ticker": fila.ticker,
            "accion": accion,
            "cantidad": cantidad,
            "justificacion": justificacion,
        })

    return decisiones, {"decisiones": decisiones}


def ejecutar_y_guardar(
    agente_id: int,
    fecha: date,
    tickers: list[str],
    decisiones: list[dict],
    respuesta_json: dict,
    modelo: str,
    latencia_ms: int | None,
    es_valida: bool,
    motivo_invalidez: str | None = None,
) -> None:
    """Guarda decisiones y ejecuta operaciones en la misma transacción del día."""
    por_ticker = {item["ticker"].upper(): item for item in decisiones}

    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        with conexion.cursor() as cursor:
            for ticker in tickers:
                item = por_ticker.get(ticker, {
                    "ticker": ticker,
                    "accion": "MANTENER",
                    "cantidad": 0,
                    "justificacion": "Sin decisión explícita para este ticker.",
                })

                justificacion = str(item["justificacion"])[:200]
                cursor.execute(
                    """
                    INSERT INTO decisiones_agentes (
                        agente_id, ticker, fecha, accion_decidida, cantidad,
                        justificacion, respuesta_json, modelo, latencia_ms,
                        es_valida, motivo_rechazo
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING decision_id
                    """,
                    (
                        agente_id,
                        ticker,
                        fecha,
                        item["accion"],
                        item["cantidad"],
                        justificacion,
                        Jsonb(respuesta_json),
                        modelo,
                        latencia_ms,
                        es_valida,
                        motivo_invalidez,
                    ),
                )
                decision_id = cursor.fetchone()[0]

                if item["accion"] not in ("COMPRAR", "VENDER"):
                    continue

                procedimiento = (
                    "sp_registrar_compra"
                    if item["accion"] == "COMPRAR"
                    else "sp_registrar_venta"
                )

                try:
                    # La transacción anidada crea un SAVEPOINT para esta orden.
                    with conexion.transaction():
                        cursor.execute(
                            f"CALL {procedimiento}(%s, %s, %s, %s)",
                            (agente_id, ticker, item["cantidad"], fecha),
                        )
                except psycopg.Error as error:
                    cursor.execute(
                        """
                        UPDATE decisiones_agentes
                        SET motivo_rechazo = %s
                        WHERE decision_id = %s
                        """,
                        (str(error)[:1000], decision_id),
                    )


def insertar_snapshot_un_agente(
    conexion: psycopg.Connection,
    agente_id: int,
    fecha: date,
) -> None:
    """Inserta snapshot del agente actual para usarlo dentro del dry-run."""
    valor = conexion.execute(
        "SELECT fn_valor_portafolio(%s, %s)",
        (agente_id, fecha),
    ).fetchone()[0]
    efectivo = conexion.execute(
        "SELECT saldo_efectivo FROM portafolios WHERE agente_id = %s",
        (agente_id,),
    ).fetchone()[0]

    conexion.execute(
        """
        INSERT INTO snapshots_portafolio
            (agente_id, fecha, valor_total, saldo_efectivo)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (agente_id, fecha) DO UPDATE
        SET valor_total = EXCLUDED.valor_total,
            saldo_efectivo = EXCLUDED.saldo_efectivo
        """,
        (agente_id, fecha, valor, efectivo),
    )


def reglas_dry_run(
    indicadores: pd.DataFrame,
    efectivo: float,
    posiciones: dict[str, int],
) -> list[dict]:
    """Regla determinista sencilla: compra momentum positivo o vende caída."""
    tabla = indicadores.sort_values("retorno_5d_pct", ascending=False)
    filas = tabla.to_dict("records")
    decisiones = []

    compra = next(
        (
            fila for fila in filas
            if pd.notna(fila["retorno_5d_pct"])
            and fila["retorno_5d_pct"] > 0
            and fila["ticker"] not in posiciones
        ),
        None,
    )

    if compra and efectivo > float(compra["close"]):
        cantidad = max(
            1,
            math.floor(min(efectivo * 0.05, 5000) / float(compra["close"])),
        )
        decisiones.append({
            "ticker": compra["ticker"],
            "accion": "COMPRAR",
            "cantidad": cantidad,
            "justificacion": "Dry-run: compra fija por retorno positivo a 5 días.",
        })
        return decisiones

    venta = next(
        (
            fila for fila in filas
            if fila["ticker"] in posiciones
            and pd.notna(fila["retorno_5d_pct"])
            and fila["retorno_5d_pct"] < -2
        ),
        None,
    )

    if venta:
        decisiones.append({
            "ticker": venta["ticker"],
            "accion": "VENDER",
            "cantidad": min(1, posiciones[venta["ticker"]]),
            "justificacion": "Dry-run: reduce una acción tras una caída a 5 días.",
        })

    return decisiones


def ejecutar_dry_run(
    historial: pd.DataFrame,
    tickers: list[str],
    fechas: list[date],
    capital_inicial: float,
) -> None:
    """Prueba decisiones, procedimientos y snapshots; revierte todo al salir."""
    email_temporal = f"dry-run-{uuid.uuid4().hex}@local.invalid"

    try:
        with psycopg.connect(**obtener_parametros_bd()) as conexion:
            try:
                with conexion.transaction():
                    conexion.execute(
                        """
                        INSERT INTO usuarios (nombre, email)
                        VALUES ('Usuario temporal dry-run', %s)
                        RETURNING usuario_id
                        """,
                        (email_temporal,),
                    )
                    usuario_id = conexion.execute(
                        "SELECT usuario_id FROM usuarios WHERE email = %s",
                        (email_temporal,),
                    ).fetchone()[0]

                    conexion.execute(
                        """
                        INSERT INTO agentes (usuario_id, nombre, estrategia, descripcion)
                        VALUES (%s, 'Agente simulado dry-run', 'CONSERVADOR',
                                'Agente temporal para prueba sin Ollama')
                        RETURNING agente_id
                        """,
                        (usuario_id,),
                    )
                    agente_id = conexion.execute(
                        """
                        SELECT agente_id FROM agentes
                        WHERE usuario_id = %s AND nombre = 'Agente simulado dry-run'
                        """,
                        (usuario_id,),
                    ).fetchone()[0]

                    conexion.execute(
                        """
                        INSERT INTO portafolios
                            (agente_id, capital_inicial, saldo_efectivo)
                        VALUES (%s, %s, %s)
                        """,
                        (agente_id, capital_inicial, capital_inicial),
                    )

                    for fecha in fechas[-3:]:
                        indicadores = calcular_indicadores(historial, fecha)
                        efectivo, posiciones = obtener_estado_en_conexion(conexion, agente_id)
                        decisiones = reglas_dry_run(
                            indicadores, efectivo, posiciones
                        )
                        respuesta = {"decisiones": decisiones}

                        # Usamos la misma conexión/transacción temporal.
                        por_ticker = {item["ticker"]: item for item in decisiones}
                        for ticker in tickers:
                            item = por_ticker.get(ticker, {
                                "ticker": ticker,
                                "accion": "MANTENER",
                                "cantidad": 0,
                                "justificacion": "Dry-run: mantener.",
                            })
                            cursor = conexion.execute(
                                """
                                INSERT INTO decisiones_agentes (
                                    agente_id, ticker, fecha, accion_decidida,
                                    cantidad, justificacion, respuesta_json,
                                    modelo, latencia_ms, es_valida, motivo_rechazo
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s,
                                        'dry-run-reglas', 0, true, NULL)
                                RETURNING decision_id
                                """,
                                (
                                    agente_id, ticker, fecha, item["accion"],
                                    item["cantidad"], item["justificacion"][:200],
                                    Jsonb(respuesta),
                                ),
                            )
                            decision_id = cursor.fetchone()[0]

                            if item["accion"] in ("COMPRAR", "VENDER"):
                                procedimiento = (
                                    "sp_registrar_compra"
                                    if item["accion"] == "COMPRAR"
                                    else "sp_registrar_venta"
                                )
                                try:
                                    with conexion.transaction():
                                        conexion.execute(
                                            f"CALL {procedimiento}(%s, %s, %s, %s)",
                                            (
                                                agente_id, ticker,
                                                item["cantidad"], fecha,
                                            ),
                                        )
                                except psycopg.Error as error:
                                    conexion.execute(
                                        """
                                        UPDATE decisiones_agentes
                                        SET motivo_rechazo = %s
                                        WHERE decision_id = %s
                                        """,
                                        (str(error)[:1000], decision_id),
                                    )

                        insertar_snapshot_un_agente(conexion, agente_id, fecha)
                        logger.info("Dry-run: día %s completado.", fecha)

                    # La excepción provoca rollback de usuario, agente y operaciones.
                    raise RevertirDryRun()

            except RevertirDryRun:
                logger.info(
                    "Dry-run terminado: cambios revertidos; no llamó a Ollama."
                )

    except psycopg.Error:
        logger.exception("Falló el dry-run de base de datos.")
        raise


def ejecutar_simulacion(
    historial: pd.DataFrame,
    tickers: list[str],
    agentes: list[tuple[int, str, str]],
    fechas: list[date],
    cliente: Client,
    config: dict,
) -> None:
    """Ejecuta o reanuda la simulación completa por agente y fecha."""
    modelo = config["ollama"]["modelo"]
    temperatura = config["ollama"]["temperatura"]
    num_predict = config["ollama"]["num_predict"]
    inicio = time.perf_counter()
    total = len(fechas)

    for numero_dia, fecha in enumerate(fechas, start=1):
        indicadores = calcular_indicadores(historial, fecha)
        tickers_presentes = set(indicadores["ticker"])
        if tickers_presentes != set(tickers):
            raise RuntimeError(
                f"Faltan indicadores para todos los tickers el {fecha}."
            )

        for agente_id, nombre, estrategia in agentes:
            if agente_ya_procesado(agente_id, fecha, tickers):
                logger.info("%s %s ya estaba completo; se omite.", fecha, nombre)
                continue

            if estrategia == "BUY_AND_HOLD":
                decisiones, respuesta = decisiones_benchmark(
                    fecha,
                    indicadores,
                    fechas[0],
                    config["simulacion"]["capital_inicial"],
                )
                valido = True
                latencia = 0
                error = None
                modelo_usado = "benchmark-comprar-y-mantener"
            else:
                efectivo, posiciones = obtener_estado(agente_id)
                mensaje = construir_mensaje(
                    fecha, efectivo, posiciones, indicadores
                )
                decisiones_modelo, respuesta, valido, latencia, error = (
                    consultar_ollama(
                        cliente=cliente,
                        modelo=modelo,
                        prompt_sistema=PROMPTS[estrategia],
                        mensaje_usuario=mensaje,
                        tickers_validos=set(tickers),
                        temperatura=temperatura,
                        num_predict=num_predict,
                    )
                )
                modelo_usado = modelo

                if valido:
                    decisiones = [
                        {
                            "ticker": item.ticker.upper(),
                            "accion": item.accion,
                            "cantidad": item.cantidad,
                            "justificacion": item.justificacion,
                        }
                        for item in decisiones_modelo or []
                    ]
                else:
                    decisiones = [
                        {
                            "ticker": ticker,
                            "accion": "MANTENER",
                            "cantidad": 0,
                            "justificacion": "JSON inválido; se mantiene.",
                        }
                        for ticker in tickers
                    ]

            ejecutar_y_guardar(
                agente_id=agente_id,
                fecha=fecha,
                tickers=tickers,
                decisiones=decisiones,
                respuesta_json=respuesta,
                modelo=modelo_usado,
                latencia_ms=latencia,
                es_valida=valido,
                motivo_invalidez=error,
            )

        # Se llama después de procesar todos los agentes de este día.
        with psycopg.connect(**obtener_parametros_bd()) as conexion:
            conexion.execute("CALL sp_tomar_snapshot(%s)", (fecha,))

        transcurrido = time.perf_counter() - inicio
        segundos_por_dia = transcurrido / numero_dia
        eta = segundos_por_dia * (total - numero_dia)
        logger.info(
            "Día %s/%s (%s) completo; ETA aproximado %.1f minutos.",
            numero_dia, total, fecha, eta / 60,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Motor de simulación de trading")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prueba 3 días con reglas fijas y revierte todos los cambios.",
    )
    argumentos = parser.parse_args()

    config = cargar_configuracion()
    tickers = [str(ticker).upper() for ticker in config["tickers"]]
    historial = cargar_historial()
    fechas = fechas_comunes(
        historial,
        tickers,
        cantidad=config["simulacion"]["dias_habiles"],
    )

    if argumentos.dry_run:
        ejecutar_dry_run(
            historial,
            tickers,
            fechas,
            config["simulacion"]["capital_inicial"],
        )
        return

    agentes = asegurar_agentes(config["simulacion"]["capital_inicial"])
    cliente = Client(host=config["ollama"]["host"])
    ejecutar_simulacion(
        historial, tickers, agentes, fechas, cliente, config
    )


if __name__ == "__main__":
    main()