"""Interfaz Streamlit del simulador de trading."""

import pandas as pd
import plotly.express as px
import psycopg
import streamlit as st
from psycopg.rows import dict_row

from simulador.configuracion import obtener_parametros_bd
from simulador.control_interfaz import ControlSimulacion
from simulador.metricas import calcular_metricas, cargar_snapshots
import plotly.graph_objects as go
from plotly.subplots import make_subplots

BASE_DEMO = "simulador-trading-demo"

st.set_page_config(
    page_title="Simulador de Trading",
    page_icon="docs/img/icon.jpg",
    layout="wide",
)


def consultar_dataframe(consulta: str, parametros: tuple = ()) -> pd.DataFrame:
    """Ejecuta una consulta de lectura y devuelve un DataFrame."""
    with psycopg.connect(
        **obtener_parametros_bd(),
        row_factory=dict_row,
    ) as conexion:
        filas = conexion.execute(consulta, parametros).fetchall()
    return pd.DataFrame(filas)


@st.cache_resource
def obtener_control() -> ControlSimulacion:
    return ControlSimulacion()


def cargar_resultados():
    filas = cargar_snapshots()
    if not filas:
        return [], []

    return calcular_metricas(filas)


def mostrar_resumen():
    st.title("Resumen del simulador")
    metricas, evolucion = cargar_resultados()

    if not metricas:
        st.info(
            "Todavía no hay resultados en esta base. "
            "Inicia la simulación desde la sección Simulación."
        )
        return

    mejor = metricas[0]
    columnas = st.columns(4)
    columnas[0].metric("Agentes", len(metricas))
    columnas[1].metric(
        "Días procesados",
        max(fila["dias_simulados"] for fila in metricas),
    )
    columnas[2].metric("Mejor agente", mejor["agente"])
    columnas[3].metric(
        "Mejor retorno",
        f'{mejor["retorno_total_pct"]:.2f}%',
    )

    st.subheader("Ranking actual")
    st.dataframe(
        pd.DataFrame(metricas),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Evolución de los portafolios")
    datos = pd.DataFrame(evolucion)
    if not datos.empty:
        datos["fecha"] = pd.to_datetime(datos["fecha"])
        figura = px.line(
            datos,
            x="fecha",
            y="valor_total",
            color="agente",
            markers=False,
            labels={
                "fecha": "Fecha",
                "valor_total": "Valor del portafolio",
                "agente": "Agente",
            },
        )
        st.plotly_chart(figura, use_container_width=True)


def mostrar_controles():
    parametros = obtener_parametros_bd()
    nombre_bd = parametros["dbname"]
    es_demo = nombre_bd == BASE_DEMO

    st.title("Control de la simulación")
    st.caption(f"Base de datos conectada: {nombre_bd}")

    if not es_demo:
        st.warning(
            f"Los controles están protegidos y solo se activan en "
            f"{BASE_DEMO}. La base actual no se modificará."
        )
        return

    control = obtener_control()
    estado = control.estado()
    nombre_estado = {
        "inactivo": "Lista para continuar",
        "avanzando": "Procesando un día",
        "ejecutando": "En ejecución",
        "pausando": "Pausando al terminar el día actual",
        "pausada": "En pausa",
        "completo": "Simulación completada",
        "error": "Error",
    }.get(estado["estado"], estado["estado"])

    st.subheader(nombre_estado)

    if estado["fecha_actual"]:
        st.write(f"Día actual: **{estado['fecha_actual']}**")

    if estado["total"]:
        avance = estado["completados"] / estado["total"]
        st.progress(min(avance, 1.0))
        st.caption(
            f'{estado["completados"]} de {estado["total"]} días '
            "pendientes procesados en esta ejecución."
        )

    if estado["error"]:
        st.error(estado["error"])

    hilo_activo = estado["hilo_activo"]
    columnas = st.columns(3)

    with columnas[0]:
        if st.button(
            "Avanzar 1 día",
            disabled=hilo_activo or estado["estado"] == "completo",
            use_container_width=True,
        ):
            try:
                with st.spinner(
                    "Procesando un día para todos los agentes..."
                ):
                    mensaje = control.avanzar_un_dia()
                st.success(mensaje)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with columnas[1]:
        if st.button(
            "Iniciar simulación",
            disabled=hilo_activo or estado["estado"] == "completo",
            use_container_width=True,
        ):
            try:
                mensaje = control.iniciar()
                st.success(mensaje)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with columnas[2]:
        if estado["estado"] in ("ejecutando", "pausando"):
            if st.button(
                "Pausar",
                disabled=estado["estado"] == "pausando",
                use_container_width=True,
            ):
                control.pausar()
                st.rerun()
        elif estado["estado"] == "pausada":
            if st.button("Continuar", use_container_width=True):
                control.continuar()
                st.rerun()

    if hilo_activo:
        st.caption(
            "La pausa se aplica al terminar el día que se está procesando."
        )


@st.fragment(run_every=2)
def panel_estado_simulacion():
    control = obtener_control()
    estado = control.estado()

    if estado["hilo_activo"]:
        st.info(
            f'Estado: {estado["estado"]}. '
            f'Día actual: {estado["fecha_actual"] or "preparando"}'
        )
        if estado["total"]:
            st.progress(
                min(estado["completados"] / estado["total"], 1.0)
            )


def mostrar_agentes():
    st.title("Agentes")

    agentes = consultar_dataframe(
        """
        SELECT agente_id, nombre, estrategia, descripcion, activo
        FROM agentes
        ORDER BY agente_id;
        """
    )
    st.subheader("Agentes registrados")
    if agentes.empty:
        st.info("Aún no hay agentes. Se crean al iniciar la simulación.")
    else:
        st.dataframe(agentes, use_container_width=True, hide_index=True)

    decisiones = consultar_dataframe(
        """
        SELECT
            d.fecha,
            a.nombre AS agente,
            d.ticker,
            d.accion_decidida AS accion,
            d.cantidad,
            d.justificacion,
            d.modelo,
            d.latencia_ms,
            d.es_valida
        FROM decisiones_agentes AS d
        JOIN agentes AS a ON a.agente_id = d.agente_id
        ORDER BY d.fecha DESC, d.decision_id DESC
        LIMIT 100;
        """
    )
    st.subheader("Decisiones recientes")
    if decisiones.empty:
        st.info("Todavía no hay decisiones guardadas.")
    else:
        st.dataframe(
            decisiones,
            use_container_width=True,
            hide_index=True,
        )

def mostrar_mercado():
    st.title("Mercado")

    tickers = consultar_dataframe(
        """
        SELECT DISTINCT ticker
        FROM precios_historicos
        ORDER BY ticker;
        """
    )

    if tickers.empty:
        st.warning("No hay precios históricos en esta base.")
        return

    ticker = st.selectbox("Selecciona un ticker", tickers["ticker"].tolist())

    precios = consultar_dataframe(
        """
        SELECT fecha, open, high, low, close, volume
        FROM precios_historicos
        WHERE ticker = %s
        ORDER BY fecha;
        """,
        (ticker,),
    )

    if precios.empty:
        st.info("No hay datos para ese ticker.")
        return

    precios["fecha"] = pd.to_datetime(precios["fecha"])
    precios["variacion_pct"] = precios["close"].pct_change() * 100

    colores = [
        "#64748b" if pd.isna(valor)
        else "#00C853" if valor >= 0
        else "#FF4D6D"
        for valor in precios["variacion_pct"]
    ]

    figura = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.72, 0.28],
        subplot_titles=(
            f"Precio diario de {ticker}",
            "Variación del cierre frente al día anterior",
        ),
    )

    figura.add_trace(
        go.Candlestick(
            x=precios["fecha"],
            open=precios["open"],
            high=precios["high"],
            low=precios["low"],
            close=precios["close"],
            name=ticker,
            increasing={
                "line": {"color": "#00C853"},
                "fillcolor": "#00C853",
            },
            decreasing={
                "line": {"color": "#FF4D6D"},
                "fillcolor": "#FF4D6D",
            },
        ),
        row=1,
        col=1,
    )

    figura.add_trace(
        go.Bar(
            x=precios["fecha"],
            y=precios["variacion_pct"],
            marker_color=colores,
            name="Variación diaria",
        ),
        row=2,
        col=1,
    )

    figura.update_layout(
        template="plotly_dark",
        height=700,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        showlegend=False,
    )
    figura.update_yaxes(title_text="Precio", row=1, col=1)
    figura.update_yaxes(
        title_text="Variación (%)",
        ticksuffix="%",
        row=2,
        col=1,
    )
    figura.update_xaxes(title_text="Fecha", row=2, col=1)

    st.caption(
        "Las velas comparan apertura y cierre del día. "
        "Las barras inferiores comparan el cierre con el del día anterior."
    )
    st.plotly_chart(figura, use_container_width=True)
    st.dataframe(precios, use_container_width=True, hide_index=True)


def mostrar_metricas():
    st.title("Métricas y ranking")
    metricas, evolucion = cargar_resultados()

    if not metricas:
        st.info("No hay snapshots para calcular métricas todavía.")
        return

    tabla_metricas = pd.DataFrame(metricas)
    st.dataframe(
        tabla_metricas,
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "Descargar ranking CSV",
        data=tabla_metricas.to_csv(
            index=False,
            encoding="utf-8-sig",
        ),
        file_name="ranking_agentes.csv",
        mime="text/csv",
    )

    tabla_evolucion = pd.DataFrame(evolucion)
    st.download_button(
        "Descargar evolución CSV",
        data=tabla_evolucion.to_csv(
            index=False,
            encoding="utf-8-sig",
        ),
        file_name="evolucion_portafolios.csv",
        mime="text/csv",
    )

    ordenadas = tabla_metricas.sort_values("retorno_total_pct")
    figura = px.bar(
        ordenadas,
        x="retorno_total_pct",
        y="agente",
        orientation="h",
        color="retorno_total_pct",
        title="Retorno total por agente",
        labels={
            "retorno_total_pct": "Retorno total (%)",
            "agente": "Agente",
        },
    )
    st.plotly_chart(figura, use_container_width=True)


try:
    parametros_bd = obtener_parametros_bd()
except Exception as exc:
    st.error(f"No se pudo leer la configuración de PostgreSQL: {exc}")
    st.stop()

st.sidebar.title("Simulador")
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] button {
        min-height: 46px;
        border-radius: 10px;
    }

    [data-testid="stSidebar"] button[kind="secondary"] {
        border: 1px solid #303744;
    }

    [data-testid="stSidebar"] button[kind="primary"] {
        border: 1px solid #00D4AA;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

secciones = [
    ("Resumen"),
    ("Simulación"),
    ("Agentes"),
    ("Mercado"),
    ("Métricas"),
]
if "pagina" not in st.session_state:
    st.session_state["pagina"] = "Resumen"

for indice, nombre in enumerate(secciones):
    tipo = (
        "primary"
        if st.session_state["pagina"] == nombre
        else "secondary"
    )

    if st.sidebar.button(
        nombre,
        key=f"nav_{indice}",
        type=tipo,
        width="stretch",
    ):
        st.session_state["pagina"] = nombre
        st.rerun()

    pagina = st.session_state["pagina"]

if pagina == "Resumen":
    mostrar_resumen()
elif pagina == "Simulación":
    mostrar_controles()
    if parametros_bd["dbname"] == BASE_DEMO:
        panel_estado_simulacion()
elif pagina == "Agentes":
    mostrar_agentes()
elif pagina == "Mercado":
    mostrar_mercado()
elif pagina == "Métricas":
    mostrar_metricas()