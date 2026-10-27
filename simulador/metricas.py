"""Calcula métricas de los agentes y genera CSV y gráficos HTML."""

import csv
import logging
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from datetime import timedelta

import plotly.graph_objects as go
import psycopg
from dotenv import load_dotenv
from plotly.subplots import make_subplots
from psycopg.rows import dict_row


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger(__name__)


def valor_entorno(*nombres, predeterminado=None):
    """Devuelve el primer valor de entorno configurado."""
    for nombre in nombres:
        valor = os.getenv(nombre)
        if valor:
            return valor
    return predeterminado


def conectar():
    """Abre una conexión usando las variables del archivo .env."""
    load_dotenv()

    return psycopg.connect(
        host=valor_entorno("DB_HOST", "POSTGRES_HOST", predeterminado="localhost"),
        port=valor_entorno("DB_PORT", "POSTGRES_PORT", predeterminado="5432"),
        dbname=valor_entorno(
            "DB_NAME",
            "POSTGRES_DB",
            predeterminado="simulador-trading",
        ),
        user=valor_entorno("DB_USER", "POSTGRES_USER", "PGUSER"),
        password=valor_entorno("DB_PASSWORD", "POSTGRES_PASSWORD", "PGPASSWORD"),
        row_factory=dict_row,
    )


def cargar_snapshots():
    """Lee el capital inicial y el valor diario de cada portafolio."""
    consulta = """
        SELECT
            a.agente_id,
            a.nombre AS agente,
            a.estrategia,
            p.capital_inicial,
            s.fecha,
            s.valor_total
        FROM snapshots_portafolio AS s
        JOIN agentes AS a
          ON a.agente_id = s.agente_id
        JOIN portafolios AS p
          ON p.agente_id = s.agente_id
        ORDER BY a.agente_id, s.fecha;
    """

    with conectar() as conexion:
        return conexion.execute(consulta).fetchall()


def calcular_metricas(filas):
    """Calcula retorno, volatilidad, Sharpe y drawdown por agente."""
    por_agente = defaultdict(list)

    for fila in filas:
        por_agente[fila["agente_id"]].append(fila)

    metricas = []
    evolucion = []

    for agente_id, snapshots in por_agente.items():
        snapshots.sort(key=lambda fila: fila["fecha"])

        primero = snapshots[0]
        capital_inicial = float(primero["capital_inicial"])
        valores = [capital_inicial]
        valores.extend(float(fila["valor_total"]) for fila in snapshots)

        rendimientos = [
            (actual / anterior) - 1
            for anterior, actual in zip(valores, valores[1:])
            if anterior != 0
        ]

        valor_final = valores[-1]
        retorno_total = (
            (valor_final / capital_inicial) - 1
            if capital_inicial
            else 0.0
        )

        desviacion_diaria = (
            statistics.stdev(rendimientos)
            if len(rendimientos) >= 2
            else 0.0
        )
        volatilidad_anual = desviacion_diaria * math.sqrt(252)
        sharpe = (
            statistics.mean(rendimientos) / desviacion_diaria * math.sqrt(252)
            if desviacion_diaria
            else 0.0
        )

        maximo_historico = valores[0]
        drawdown_maximo = 0.0

        for valor in valores:
            maximo_historico = max(maximo_historico, valor)
            if maximo_historico:
                drawdown = (valor / maximo_historico) - 1
                drawdown_maximo = min(drawdown_maximo, drawdown)

        metricas.append({
            "agente_id": agente_id,
            "agente": primero["agente"],
            "estrategia": primero["estrategia"],
            "dias_simulados": len(snapshots),
            "fecha_inicio": primero["fecha"].isoformat(),
            "fecha_final": snapshots[-1]["fecha"].isoformat(),
            "capital_inicial": round(capital_inicial, 2),
            "valor_final": round(valor_final, 2),
            "retorno_total_pct": round(retorno_total * 100, 4),
            "volatilidad_anual_pct": round(volatilidad_anual * 100, 4),
            "sharpe": round(sharpe, 4),
            "drawdown_maximo_pct": round(drawdown_maximo * 100, 4),
        })

        # Incluye el capital inicial para que el gráfico muestre la trayectoria completa.
        evolucion.append({
            "agente": primero["agente"],
            "estrategia": primero["estrategia"],
            "fecha": (primero["fecha"] - timedelta(days=1)).isoformat(),
            "valor_total": round(capital_inicial, 2),
        })

        for snapshot in snapshots:
            evolucion.append({
                "agente": primero["agente"],
                "estrategia": primero["estrategia"],
                "fecha": snapshot["fecha"].isoformat(),
                "valor_total": round(float(snapshot["valor_total"]), 2),
            })

    metricas.sort(
        key=lambda fila: (
            fila["retorno_total_pct"],
            fila["sharpe"],
        ),
        reverse=True,
    )

    for puesto, fila in enumerate(metricas, start=1):
        fila["puesto"] = puesto

    return metricas, evolucion


def guardar_csv(ruta, filas, columnas):
    """Guarda un CSV que se puede abrir en Excel."""
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)


def generar_grafico(metricas, evolucion, ruta):
    """Genera un HTML con la evolución y el ranking por retorno."""
    figura = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=(
            "Evolución del valor de los portafolios",
            "Retorno total por agente",
        ),
        vertical_spacing=0.18,
    )

    agentes = list(dict.fromkeys(fila["agente"] for fila in evolucion))

    for agente in agentes:
        puntos = [fila for fila in evolucion if fila["agente"] == agente]
        figura.add_trace(
            go.Scatter(
                x=[fila["fecha"] for fila in puntos],
                y=[fila["valor_total"] for fila in puntos],
                mode="lines",
                name=agente,
            ),
            row=1,
            col=1,
        )

    ordenadas = list(reversed(metricas))
    figura.add_trace(
        go.Bar(
            x=[fila["retorno_total_pct"] for fila in ordenadas],
            y=[fila["agente"] for fila in ordenadas],
            orientation="h",
            text=[f'{fila["retorno_total_pct"]:.2f}%' for fila in ordenadas],
            textposition="outside",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    figura.update_layout(
        title="Resultados de la simulación",
        height=850,
        template="plotly_white",
    )
    figura.update_xaxes(title_text="Fecha", row=1, col=1)
    figura.update_yaxes(title_text="Valor del portafolio", row=1, col=1)
    figura.update_xaxes(title_text="Retorno total (%)", row=2, col=1)

    # El HTML incluye Plotly para poder abrirlo sin conexión a internet.
    figura.write_html(ruta, include_plotlyjs=True)


def main():
    filas = cargar_snapshots()

    if not filas:
        raise SystemExit(
            "No hay snapshots para calcular. Revisa que la simulación haya "
            "guardado datos en snapshots_portafolio."
        )

    metricas, evolucion = calcular_metricas(filas)
    carpeta_reportes = Path("reports")
    carpeta_reportes.mkdir(exist_ok=True)

    columnas_ranking = [
        "puesto",
        "agente_id",
        "agente",
        "estrategia",
        "dias_simulados",
        "fecha_inicio",
        "fecha_final",
        "capital_inicial",
        "valor_final",
        "retorno_total_pct",
        "volatilidad_anual_pct",
        "sharpe",
        "drawdown_maximo_pct",
    ]

    guardar_csv(
        carpeta_reportes / "ranking_agentes.csv",
        metricas,
        columnas_ranking,
    )
    guardar_csv(
        carpeta_reportes / "evolucion_portafolios.csv",
        evolucion,
        ["agente", "estrategia", "fecha", "valor_total"],
    )
    generar_grafico(
        metricas,
        evolucion,
        carpeta_reportes / "graficos_agentes.html",
    )

    LOGGER.info("Ranking de agentes:")
    for fila in metricas:
        LOGGER.info(
            "%s. %s | retorno: %.2f%% | Sharpe: %.4f | drawdown máximo: %.2f%%",
            fila["puesto"],
            fila["agente"],
            fila["retorno_total_pct"],
            fila["sharpe"],
            fila["drawdown_maximo_pct"],
        )

    LOGGER.info("Archivos generados en: %s", carpeta_reportes.resolve())


if __name__ == "__main__":
    main()