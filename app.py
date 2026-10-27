"""Interfaz Streamlit del simulador de trading."""

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg
import streamlit as st
from ollama import Client
from plotly.subplots import make_subplots
from psycopg.rows import dict_row

from simulador.configuracion import (
    cargar_configuracion,
    obtener_parametros_bd,
)
from simulador.control_interfaz import ControlSimulacion
from simulador.metricas import calcular_metricas, cargar_snapshots
from simulador.servicios_interfaz import (
    cargar_csv_configurado,
    descargar_csv_configurado,
    guardar_ajustes,
    guardar_comision_porcentaje,
    obtener_comision_porcentaje,
    crear_o_reiniciar_base_demo,
)

from simulador.indicadores import calcular_indicadores

BASE_DEMO = "simulador-trading-demo"

st.set_page_config(
    page_title="Simulador de Trading",
    page_icon="docs/img/icon.jpg",
    layout="wide",
)


def consultar_dataframe(
    consulta: str,
    parametros: tuple = (),
) -> pd.DataFrame:
    """Ejecuta una consulta de lectura y devuelve un DataFrame."""
    with psycopg.connect(
        **obtener_parametros_bd(),
        row_factory=dict_row,
    ) as conexion:
        filas = conexion.execute(consulta, parametros).fetchall()

    return pd.DataFrame(filas)


@st.cache_resource
def obtener_control() -> ControlSimulacion:
    """Conserva el controlador entre las recargas de Streamlit."""
    return ControlSimulacion()


def cargar_resultados():
    """Calcula las métricas a partir de los snapshots disponibles."""
    filas = cargar_snapshots()

    if not filas:
        return [], []

    return calcular_metricas(filas)


@st.cache_data(ttl=30, show_spinner=False)
def consultar_estado_sistema():
    """Comprueba PostgreSQL, Ollama, el modelo y los datos cargados."""
    estado = {
        "postgres_ok": False,
        "postgres_error": None,
        "cotizaciones": 0,
        "tickers": 0,
        "agentes": 0,
        "dias": 0,
        "ollama_ok": False,
        "ollama_error": None,
        "modelo": "No configurado",
        "modelo_descargado": False,
        "modelos_disponibles": [],
    }

    try:
        with psycopg.connect(**obtener_parametros_bd()) as conexion:
            fila = conexion.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM precios_historicos)
                        AS cotizaciones,
                    (SELECT COUNT(DISTINCT ticker)
                     FROM precios_historicos)
                        AS tickers,
                    (SELECT COUNT(*) FROM agentes)
                        AS agentes,
                    (SELECT COUNT(DISTINCT fecha)
                     FROM snapshots_portafolio)
                        AS dias;
                """
            ).fetchone()

        estado.update({
            "postgres_ok": True,
            "cotizaciones": fila[0],
            "tickers": fila[1],
            "agentes": fila[2],
            "dias": fila[3],
        })
    except Exception as exc:
        estado["postgres_error"] = str(exc)

    try:
        configuracion = cargar_configuracion()
        modelo_configurado = configuracion["ollama"]["modelo"]
        cliente = Client(host=configuracion["ollama"]["host"])
        respuesta = cliente.list()

        modelos = sorted({
            modelo.model
            for modelo in respuesta.models
            if modelo.model
        })

        estado.update({
            "ollama_ok": True,
            "modelo": modelo_configurado,
            "modelo_descargado": modelo_configurado in modelos,
            "modelos_disponibles": modelos,
        })
    except Exception as exc:
        estado["ollama_error"] = str(exc)

    return estado


@st.fragment(run_every=30)
def mostrar_estado_sistema():
    """Muestra el estado de servicios y datos; se actualiza cada 30 s."""
    estado = consultar_estado_sistema()

    columnas = st.columns(4)
    columnas[0].metric(
        "PostgreSQL",
        "Conectado" if estado["postgres_ok"] else "No disponible",
    )
    columnas[1].metric(
        "Ollama",
        "Disponible" if estado["ollama_ok"] else "No disponible",
    )
    columnas[2].metric(
        "Modelo",
        "Descargado"
        if estado["modelo_descargado"]
        else "Pendiente",
    )
    columnas[3].metric(
        "Cotizaciones",
        f'{estado["cotizaciones"]:,}',
    )

    columnas_datos = st.columns(3)
    columnas_datos[0].metric("Tickers cargados", estado["tickers"])
    columnas_datos[1].metric("Agentes registrados", estado["agentes"])
    columnas_datos[2].metric("Días simulados", estado["dias"])

    if estado["postgres_error"]:
        st.error(
            "No pude leer PostgreSQL. Revisa que el servicio esté iniciado, "
            "que las variables del archivo `.env` sean correctas y que el "
            "esquema SQL esté creado."
        )
        st.caption(estado["postgres_error"])

    if estado["ollama_error"]:
        st.error(
            "No pude consultar Ollama. Revisa que esté ejecutándose y que "
            "la dirección configurada en `config.yaml` sea correcta."
        )
        st.caption(estado["ollama_error"])
    elif not estado["modelo_descargado"]:
        st.warning(
            f'El modelo `{estado["modelo"]}` no aparece descargado. '
            f'En PowerShell ejecuta: `ollama pull {estado["modelo"]}`.'
        )


def mostrar_resumen():
    st.title("Inicio y estado del sistema")
    st.info(
        "Aquí puedes revisar la conexión, el modelo, los datos cargados "
        "y el resumen de resultados. El estado se actualiza cada 30 segundos."
    )
    mostrar_estado_sistema()

    try:
        metricas, evolucion = cargar_resultados()
    except Exception as exc:
        st.warning(
            "No pude cargar las métricas. Comprueba la base conectada y, "
            "si hace falta, crea o reinicia la base demo en "
            "Configuración y datos."
        )
        st.caption(f"Detalle: {exc}")
        return

    if not metricas:
        st.info(
            "Todavía no hay snapshots para mostrar resultados. "
            "Avanza un día o inicia la simulación."
        )
        return

    mejor = metricas[0]
    columnas = st.columns(4)
    columnas[0].metric(
        "Mejor agente",
        mejor["agente"],
    )
    columnas[1].metric(
        "Rentabilidad líder",
        f'{mejor["retorno_total_pct"]:+.2f}%',
    )
    columnas[2].metric(
        "Valor final del líder",
        f'${mejor["valor_final"]:,.2f}',
    )
    columnas[3].metric(
        "Días procesados",
        max(fila["dias_simulados"] for fila in metricas),
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
            labels={
                "fecha": "Fecha",
                "valor_total": "Valor del portafolio ($)",
                "agente": "Agente",
            },
        )
        st.plotly_chart(figura, use_container_width=True)


def mostrar_controles():
    parametros = obtener_parametros_bd()
    nombre_bd = parametros["dbname"]

    st.title("Control de la simulación")
    st.caption(f"Base de datos conectada: {nombre_bd}")

    if nombre_bd != BASE_DEMO:
        st.warning(
            f"Los controles solo se activan en `{BASE_DEMO}` para proteger "
            "los resultados de la base principal."
        )
        return

    control = obtener_control()
    estado = control.estado()

    st.info(
        "El dry-run prueba tres días con reglas fijas, revierte sus cambios "
        "y no llama a Ollama. La simulación normal sí utiliza el modelo."
    )

    usar_dry_run = st.checkbox(
        "Modo dry-run (prueba rápida sin Ollama)",
        disabled=estado["hilo_activo"],
        help="La prueba no conserva sus cambios en la base.",
    )

    if usar_dry_run:
        if st.button(
            "Ejecutar dry-run",
            type="primary",
            disabled=estado["hilo_activo"],
            use_container_width=True,
        ):
            try:
                with st.spinner("Ejecutando la prueba reversible..."):
                    mensaje = control.ejecutar_prueba_dry_run()
                st.success(mensaje)
            except Exception as exc:
                st.error(f"No se pudo completar el dry-run: {exc}")
    else:
        nombres_estado = {
            "inactivo": "Lista para continuar",
            "avanzando": "Procesando un día",
            "ejecutando": "En ejecución",
            "pausando": "Pausando al terminar el día actual",
            "pausada": "En pausa",
            "completo": "Simulación completada",
            "error": "Error",
        }
        st.subheader(
            nombres_estado.get(estado["estado"], estado["estado"])
        )

        if estado["fecha_actual"]:
            st.write(f'Día actual: **{estado["fecha_actual"]}**')

        if estado["total"]:
            avance = estado["completados"] / estado["total"]
            st.progress(min(avance, 1.0))
            st.caption(
                f'{estado["completados"]} de {estado["total"]} días '
                "pendientes procesados."
            )

        if (
            estado.get("eta_segundos") is not None
            and estado["estado"] == "ejecutando"
        ):
            st.caption(
                "Tiempo restante aproximado: "
                f'{estado.get("eta_segundos") / 60:.1f} minutos.'
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
                    with st.spinner("Procesando un día..."):
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
                    st.success(control.iniciar())
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
                if st.button(
                    "Continuar",
                    use_container_width=True,
                ):
                    control.continuar()
                    st.rerun()

        if hilo_activo:
            st.caption(
                "La pausa se aplica al terminar el día que está en curso."
            )

    mostrar_decisiones_en_vivo()

@st.fragment(run_every=2)
def panel_estado_simulacion():
    """Actualiza parcialmente el estado de la ejecución en segundo plano."""
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
        if estado.get("eta_segundos") is not None:
            st.caption(
                f'Tiempo estimado restante: '
                f'{estado.get("eta_segundos"):.0f} segundos'
            )

@st.fragment(run_every=5)
def mostrar_decisiones_en_vivo():
    """Muestra las decisiones más recientes mientras corre la simulación."""
    st.subheader("Decisiones recientes")
    st.caption(
        "La lista se actualiza cada cinco segundos y muestra hasta "
        "20 decisiones guardadas."
    )

    try:
        decisiones = consultar_dataframe(
            """
            SELECT
                d.fecha,
                a.nombre AS agente,
                d.ticker,
                d.accion_decidida AS accion,
                d.cantidad,
                d.justificacion,
                d.es_valida,
                d.motivo_rechazo
            FROM decisiones_agentes AS d
            JOIN agentes AS a
              ON a.agente_id = d.agente_id
            ORDER BY d.creada_en DESC
            LIMIT 20;
            """
        )
    except Exception as exc:
        st.warning(f"No pude leer las decisiones recientes: {exc}")
        return

    if decisiones.empty:
        st.info("Todavía no hay decisiones guardadas.")
        return

    def colorear_decision(fila):
        invalida = (
            not bool(fila["es_valida"])
            or pd.notna(fila["motivo_rechazo"])
        )
        color = (
            "background-color: #5A1F2A; color: #FFE3E6"
            if invalida
            else ""
        )
        return [color] * len(fila)

    st.dataframe(
        decisiones.style.apply(colorear_decision, axis=1),
        use_container_width=True,
        hide_index=True,
    )

def mostrar_agentes():
    st.title("Agentes")
    st.info(
        "Selecciona un agente y un rango de fechas para revisar su "
        "portafolio, las operaciones ejecutadas y las decisiones del modelo."
    )

    agentes = consultar_dataframe(
        """
        SELECT agente_id, nombre, estrategia, descripcion, activo
        FROM agentes
        ORDER BY agente_id;
        """
    )

    if agentes.empty:
        st.info("Aún no hay agentes. Se crean al iniciar la simulación.")
        return

    agentes_por_id = {
        int(fila["agente_id"]): fila
        for _, fila in agentes.iterrows()
    }

    agente_id = st.selectbox(
        "Agente",
        options=list(agentes_por_id),
        format_func=lambda ident: (
            f'{agentes_por_id[ident]["nombre"]} '
            f'({agentes_por_id[ident]["estrategia"]})'
        ),
    )

    fechas_registros = consultar_dataframe(
        """
        SELECT MIN(fecha) AS fecha_inicio, MAX(fecha) AS fecha_fin
        FROM (
            SELECT fecha
            FROM decisiones_agentes
            WHERE agente_id = %s

            UNION ALL

            SELECT fecha
            FROM ordenes
            WHERE agente_id = %s
        ) AS registros;
        """,
        (agente_id, agente_id),
    )

    hoy = date.today()
    inicio_predeterminado = hoy - timedelta(days=365)
    fin_predeterminado = hoy

    if (
        not fechas_registros.empty
        and pd.notna(fechas_registros.iloc[0]["fecha_inicio"])
    ):
        inicio_predeterminado = fechas_registros.iloc[0]["fecha_inicio"]
        fin_predeterminado = fechas_registros.iloc[0]["fecha_fin"]

    col_inicio, col_fin = st.columns(2)
    fecha_inicio = col_inicio.date_input(
        "Desde",
        value=inicio_predeterminado,
    )
    fecha_fin = col_fin.date_input(
        "Hasta",
        value=fin_predeterminado,
    )

    if fecha_inicio > fecha_fin:
        st.error("La fecha inicial no puede ser posterior a la fecha final.")
        return

    portafolio = consultar_dataframe(
        """
        SELECT capital_inicial, saldo_efectivo
        FROM portafolios
        WHERE agente_id = %s;
        """,
        (agente_id,),
    )

    if portafolio.empty:
        st.warning("Este agente todavía no tiene un portafolio.")
        return

    capital_inicial = float(portafolio.iloc[0]["capital_inicial"])
    efectivo = float(portafolio.iloc[0]["saldo_efectivo"])

    snapshot = consultar_dataframe(
        """
        SELECT fecha, valor_total
        FROM snapshots_portafolio
        WHERE agente_id = %s
        ORDER BY fecha DESC
        LIMIT 1;
        """,
        (agente_id,),
    )

    fecha_valoracion = (
        snapshot.iloc[0]["fecha"]
        if not snapshot.empty
        else hoy
    )

    posiciones = consultar_dataframe(
        """
        SELECT
            po.ticker,
            po.cantidad,
            po.costo_promedio,
            ph.close AS precio_actual,
            ph.fecha AS fecha_precio
        FROM posiciones AS po
        LEFT JOIN LATERAL (
            SELECT close, fecha
            FROM precios_historicos
            WHERE ticker = po.ticker
              AND fecha <= %s
            ORDER BY fecha DESC
            LIMIT 1
        ) AS ph ON TRUE
        WHERE po.agente_id = %s
        ORDER BY po.ticker;
        """,
        (fecha_valoracion, agente_id),
    )

    if posiciones.empty:
        valor_posiciones = 0.0
        ganancia_no_realizada = 0.0
    else:
        # PostgreSQL devuelve las columnas NUMERIC como Decimal. Convierte
        # las tres columnas antes de combinarlas con valores float de pandas.
        for columna in ("cantidad", "costo_promedio", "precio_actual"):
            posiciones[columna] = pd.to_numeric(
                posiciones[columna],
                errors="coerce",
            ).fillna(0.0)

        posiciones["valor_mercado"] = (
            posiciones["cantidad"] * posiciones["precio_actual"]
        )
        posiciones["ganancia_no_realizada"] = (
            posiciones["cantidad"]
            * (
                posiciones["precio_actual"]
                - posiciones["costo_promedio"]
            )
        )

        valor_posiciones = float(posiciones["valor_mercado"].sum())
        ganancia_no_realizada = float(
            posiciones["ganancia_no_realizada"].sum()
        )

    valor_total = (
        float(snapshot.iloc[0]["valor_total"])
        if not snapshot.empty
        else efectivo + valor_posiciones
    )
    rentabilidad = (
        (valor_total / capital_inicial - 1) * 100
        if capital_inicial
        else 0.0
    )

    kpis = st.columns(4)
    kpis[0].metric("Efectivo", f"${efectivo:,.2f}")
    kpis[1].metric("Valor de posiciones", f"${valor_posiciones:,.2f}")
    kpis[2].metric("Valor total", f"${valor_total:,.2f}")
    kpis[3].metric("Rentabilidad", f"{rentabilidad:+.2f}%")

    st.caption(
        f"Capital inicial: ${capital_inicial:,.2f} · "
        f"Valoración al: {fecha_valoracion}"
    )

    pestaña_portafolio, pestaña_ordenes, pestaña_decisiones = st.tabs(
        ["Portafolio y posiciones", "Órdenes", "Decisiones"]
    )

    with pestaña_portafolio:
        st.subheader("Posiciones actuales")

        if posiciones.empty:
            st.info("El agente no tiene posiciones abiertas.")
        else:
            st.metric(
                "Ganancia/pérdida no realizada",
                f"${ganancia_no_realizada:+,.2f}",
            )
            tabla_posiciones = posiciones.rename(columns={
                "ticker": "Ticker",
                "cantidad": "Cantidad",
                "costo_promedio": "Costo promedio",
                "precio_actual": "Precio actual",
                "valor_mercado": "Valor de mercado",
                "ganancia_no_realizada": "Ganancia/pérdida",
                "fecha_precio": "Fecha del precio",
            })
            st.dataframe(
                tabla_posiciones[
                    [
                        "Ticker",
                        "Cantidad",
                        "Costo promedio",
                        "Precio actual",
                        "Valor de mercado",
                        "Ganancia/pérdida",
                        "Fecha del precio",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    with pestaña_ordenes:
        st.subheader("Órdenes ejecutadas")

        ordenes = consultar_dataframe(
            """
            SELECT
                fecha,
                ticker,
                tipo,
                cantidad,
                precio,
                comision,
                estado
            FROM ordenes
            WHERE agente_id = %s
              AND fecha BETWEEN %s AND %s
            ORDER BY fecha DESC, orden_id DESC;
            """,
            (agente_id, fecha_inicio, fecha_fin),
        )

        if ordenes.empty:
            st.info("No hay órdenes para este agente en ese rango.")
        else:
            ordenes = ordenes.rename(columns={
                "fecha": "Fecha",
                "ticker": "Ticker",
                "tipo": "Tipo",
                "cantidad": "Cantidad",
                "precio": "Precio",
                "comision": "Comisión",
                "estado": "Estado",
            })
            st.dataframe(
                ordenes,
                use_container_width=True,
                hide_index=True,
            )

    with pestaña_decisiones:
        st.subheader("Decisiones del agente")

        decisiones = consultar_dataframe(
            """
            SELECT
                fecha,
                ticker,
                accion_decidida AS accion,
                cantidad,
                justificacion,
                modelo,
                latencia_ms,
                es_valida,
                motivo_rechazo
            FROM decisiones_agentes
            WHERE agente_id = %s
              AND fecha BETWEEN %s AND %s
            ORDER BY fecha DESC, decision_id DESC;
            """,
            (agente_id, fecha_inicio, fecha_fin),
        )

        if decisiones.empty:
            st.info("No hay decisiones para este agente en ese rango.")
        else:
            decisiones = decisiones.rename(columns={
                "fecha": "Fecha",
                "ticker": "Ticker",
                "accion": "Acción",
                "cantidad": "Cantidad",
                "justificacion": "Justificación",
                "modelo": "Modelo",
                "latencia_ms": "Latencia (ms)",
                "es_valida": "Válida",
                "motivo_rechazo": "Motivo de rechazo",
            })

            def colorear_decision(fila):
                invalida = (
                    not bool(fila["Válida"])
                    or pd.notna(fila["Motivo de rechazo"])
                )
                color = (
                    "background-color: #5A1F2A; color: #FFE3E6"
                    if invalida
                    else ""
                )
                return [color] * len(fila)

            tabla_decisiones = decisiones.style.apply(
                colorear_decision,
                axis=1,
            )

            st.caption(
                "Las filas rojas corresponden a decisiones inválidas "
                "o rechazadas."
            )
            st.dataframe(
                tabla_decisiones,
                use_container_width=True,
                hide_index=True,
            )


def mostrar_mercado():
    st.title("Mercado")
    st.info(
        "El precio y las medias móviles aparecen arriba. Abajo se muestran "
        "la variación diaria, el RSI y la volatilidad. Las barras verdes "
        "indican subidas frente al cierre anterior; las rojas, bajadas."
    )

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

    ticker = st.selectbox(
        "Selecciona un ticker",
        tickers["ticker"].tolist(),
    )

    precios = consultar_dataframe(
        """
        SELECT ticker, fecha, open, high, low, close, volume
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

    # Reutiliza el cálculo del motor para no duplicar las fórmulas.
    fechas = precios["fecha"].drop_duplicates().tolist()
    partes_indicadores = [
        calcular_indicadores(precios, fecha)
        for fecha in fechas
    ]
    indicadores = pd.concat(partes_indicadores, ignore_index=True)
    indicadores["fecha"] = pd.to_datetime(indicadores["fecha"])

    if indicadores.empty:
        st.warning(
            "No hay suficientes datos para calcular los indicadores. "
            "Carga más precios históricos."
        )
        return

    ultimo = indicadores.iloc[-1]
    columnas = st.columns(4)

    columnas[0].metric(
        "Cierre más reciente",
        f'${float(ultimo["close"]):,.2f}',
    )
    columnas[1].metric(
        "SMA 5",
        "—" if pd.isna(ultimo["sma_5"])
        else f'${float(ultimo["sma_5"]):,.2f}',
    )
    columnas[2].metric(
        "SMA 20",
        "—" if pd.isna(ultimo["sma_20"])
        else f'${float(ultimo["sma_20"]):,.2f}',
    )
    columnas[3].metric(
        "RSI 14",
        "—" if pd.isna(ultimo["rsi_14"])
        else f'{float(ultimo["rsi_14"]):.2f}',
    )

    colores_variacion = [
        "#64748b" if pd.isna(valor)
        else "#00C853" if valor >= 0
        else "#FF4D6D"
        for valor in precios["variacion_pct"]
    ]

    figura = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=[0.50, 0.16, 0.17, 0.17],
        subplot_titles=(
            f"Precio y medias móviles de {ticker}",
            "Variación del cierre frente al día anterior",
            "RSI de 14 días",
            "Volatilidad de 20 días",
        ),
    )

    figura.add_trace(
        go.Candlestick(
            x=precios["fecha"],
            open=precios["open"],
            high=precios["high"],
            low=precios["low"],
            close=precios["close"],
            name="Precio OHLC",
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
        go.Scatter(
            x=indicadores["fecha"],
            y=indicadores["sma_5"],
            mode="lines",
            name="SMA 5",
            line={"color": "#F5C542", "width": 1.5},
        ),
        row=1,
        col=1,
    )

    figura.add_trace(
        go.Scatter(
            x=indicadores["fecha"],
            y=indicadores["sma_20"],
            mode="lines",
            name="SMA 20",
            line={"color": "#A78BFA", "width": 1.5},
        ),
        row=1,
        col=1,
    )

    figura.add_trace(
        go.Bar(
            x=precios["fecha"],
            y=precios["variacion_pct"],
            marker_color=colores_variacion,
            name="Variación diaria",
        ),
        row=2,
        col=1,
    )

    figura.add_trace(
        go.Scatter(
            x=indicadores["fecha"],
            y=indicadores["rsi_14"],
            mode="lines",
            name="RSI 14",
            line={"color": "#38BDF8", "width": 1.5},
        ),
        row=3,
        col=1,
    )

    figura.add_trace(
        go.Scatter(
            x=indicadores["fecha"],
            y=indicadores["volatilidad_20_pct"],
            mode="lines",
            name="Volatilidad 20",
            line={"color": "#FB923C", "width": 1.5},
        ),
        row=4,
        col=1,
    )

    figura.add_hline(
        y=70,
        line_dash="dash",
        line_color="#FF4D6D",
        row=3,
        col=1,
    )
    figura.add_hline(
        y=30,
        line_dash="dash",
        line_color="#00C853",
        row=3,
        col=1,
    )

    figura.update_layout(
        template="plotly_dark",
        height=1000,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
    )
    figura.update_yaxes(title_text="Precio ($)", row=1, col=1)
    figura.update_yaxes(title_text="Variación (%)", row=2, col=1)
    figura.update_yaxes(
        title_text="RSI",
        range=[0, 100],
        row=3,
        col=1,
    )
    figura.update_yaxes(
        title_text="Volatilidad (%)",
        row=4,
        col=1,
    )
    figura.update_xaxes(title_text="Fecha", row=4, col=1)

    st.plotly_chart(figura, use_container_width=True)

    st.caption(
        "SMA es la media móvil simple. El RSI ayuda a observar el impulso "
        "reciente; las líneas 30 y 70 son referencias visuales, no señales "
        "automáticas de compra o venta. La volatilidad resume la variación "
        "reciente de los retornos."
    )

    tabla = indicadores[
        [
            "fecha",
            "close",
            "sma_5",
            "sma_20",
            "rsi_14",
            "volatilidad_20_pct",
        ]
    ].tail(30).rename(columns={
        "fecha": "Fecha",
        "close": "Cierre",
        "sma_5": "SMA 5",
        "sma_20": "SMA 20",
        "rsi_14": "RSI 14",
        "volatilidad_20_pct": "Volatilidad 20 días (%)",
    })

    st.subheader("Últimos 30 días")
    st.dataframe(
        tabla,
        use_container_width=True,
        hide_index=True,
    )

def mostrar_metricas():
    st.title("Ranking y métricas")
    st.markdown(
        "Compara el desempeño de cada agente durante los días procesados. "
        "El ranking prioriza la rentabilidad y usa Sharpe como desempate."
    )

    metricas, evolucion = cargar_resultados()

    if not metricas:
        st.info(
            "Todavía no hay snapshots para calcular métricas. "
            "Avanza un día o ejecuta la simulación."
        )
        return

    operaciones_df = consultar_dataframe(
        """
        SELECT agente_id, COUNT(*) AS operaciones
        FROM ordenes
        GROUP BY agente_id;
        """
    )
    decisiones_df = consultar_dataframe(
        """
        SELECT
            agente_id,
            COUNT(*) AS decisiones_totales,
            COUNT(*) FILTER (
                WHERE es_valida IS FALSE OR motivo_rechazo IS NOT NULL
            ) AS decisiones_invalidas,
            AVG(latencia_ms) FILTER (WHERE latencia_ms > 0)
                AS latencia_promedio_ms
        FROM decisiones_agentes
        GROUP BY agente_id;
        """
    )

    operaciones_por_agente = {}
    if not operaciones_df.empty:
        operaciones_por_agente = dict(
            zip(
                operaciones_df["agente_id"],
                operaciones_df["operaciones"],
            )
        )

    decisiones_por_agente = {}
    if not decisiones_df.empty:
        decisiones_por_agente = {
            fila["agente_id"]: fila
            for _, fila in decisiones_df.iterrows()
        }

    ranking = []

    for fila in metricas:
        agente_id = fila["agente_id"]
        decisiones = decisiones_por_agente.get(agente_id)

        total_decisiones = (
            int(decisiones["decisiones_totales"])
            if decisiones is not None
            else 0
        )
        invalidas = (
            int(decisiones["decisiones_invalidas"])
            if decisiones is not None
            else 0
        )
        latencia = (
            float(decisiones["latencia_promedio_ms"])
            if decisiones is not None
            and pd.notna(decisiones["latencia_promedio_ms"])
            else 0.0
        )

        ranking.append({
            **fila,
            "ganancia_perdida": round(
                fila["valor_final"] - fila["capital_inicial"],
                2,
            ),
            "operaciones": int(
                operaciones_por_agente.get(agente_id, 0)
            ),
            "decisiones_invalidas_pct": round(
                invalidas / total_decisiones * 100
                if total_decisiones
                else 0.0,
                2,
            ),
            "latencia_promedio_ms": round(latencia, 2),
        })

    ranking.sort(
        key=lambda fila: (
            fila["retorno_total_pct"],
            fila["sharpe"],
        ),
        reverse=True,
    )

    mejor = ranking[0]
    columnas = st.columns(4)
    columnas[0].metric("Mejor agente", mejor["agente"])
    columnas[1].metric(
        "Rentabilidad líder",
        f'{mejor["retorno_total_pct"]:+.2f}%',
    )
    columnas[2].metric(
        "Valor final del líder",
        f'${mejor["valor_final"]:,.2f}',
    )
    columnas[3].metric(
        "Días procesados",
        max(fila["dias_simulados"] for fila in ranking),
    )

    st.info(
        "**Cómo leerlas:** la rentabilidad compara el valor final con el "
        "capital inicial. Drawdown máximo muestra la mayor caída desde un "
        "máximo previo. Sharpe resume retorno frente a variación; con pocos "
        "días debe interpretarse con cautela. La latencia media excluye "
        "decisiones sin llamada al modelo, como el benchmark."
    )

    tabla = pd.DataFrame(ranking)
    tabla_visible = tabla.rename(columns={
        "puesto": "Puesto",
        "agente": "Agente",
        "estrategia": "Estrategia",
        "dias_simulados": "Días",
        "capital_inicial": "Capital inicial ($)",
        "valor_final": "Valor final ($)",
        "ganancia_perdida": "Ganancia / pérdida ($)",
        "retorno_total_pct": "Rentabilidad (%)",
        "volatilidad_anual_pct": "Volatilidad anual (%)",
        "drawdown_maximo_pct": "Drawdown máximo (%)",
        "sharpe": "Sharpe",
        "operaciones": "Operaciones",
        "decisiones_invalidas_pct": "Decisiones inválidas (%)",
        "latencia_promedio_ms": "Latencia media (ms)",
    })

    columnas_visibles = [
        "Puesto",
        "Agente",
        "Estrategia",
        "Días",
        "Capital inicial ($)",
        "Valor final ($)",
        "Ganancia / pérdida ($)",
        "Rentabilidad (%)",
        "Volatilidad anual (%)",
        "Drawdown máximo (%)",
        "Sharpe",
        "Operaciones",
        "Decisiones inválidas (%)",
        "Latencia media (ms)",
    ]

    st.subheader("Clasificación")
    st.dataframe(
        tabla_visible[columnas_visibles],
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "Descargar ranking CSV",
        data=tabla_visible[columnas_visibles].to_csv(
            index=False,
            encoding="utf-8-sig",
        ),
        file_name="ranking_agentes.csv",
        mime="text/csv",
    )

    st.subheader("Rentabilidad por agente")
    st.caption(
        "Verde indica ganancia, rojo indica pérdida y gris indica "
        "rentabilidad de 0 %."
    )

    nombres = [fila["agente"] for fila in ranking]
    retornos = [
        float(fila["retorno_total_pct"])
        for fila in ranking
    ]
    colores = [
        "#00C853" if valor > 0
        else "#FF4D6D" if valor < 0
        else "#64748B"
        for valor in retornos
    ]
    etiquetas = [
        f"{valor:+.2f}%" if abs(valor) >= 0.005 else ""
        for valor in retornos
    ]

    figura_rentabilidad = go.Figure(
        go.Bar(
            x=retornos,
            y=nombres,
            orientation="h",
            marker_color=colores,
            text=etiquetas,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "%{y}<br>Rentabilidad: %{x:.2f}%<extra></extra>"
            ),
        )
    )

    for nombre, valor in zip(nombres, retornos):
        if abs(valor) < 0.005:
            figura_rentabilidad.add_annotation(
                x=0,
                y=nombre,
                text="0.00%",
                showarrow=False,
                xshift=35,
            )

    valor_minimo = min(min(retornos), 0)
    valor_maximo = max(max(retornos), 0)
    margen = max(
        (valor_maximo - valor_minimo) * 0.15,
        0.25,
    )

    figura_rentabilidad.add_vline(
        x=0,
        line_dash="dash",
        line_color="#94A3B8",
    )
    figura_rentabilidad.update_layout(
        template="plotly_dark",
        showlegend=False,
        xaxis_title="Rentabilidad (%)",
        yaxis_title="Agente",
        height=380,
    )
    figura_rentabilidad.update_xaxes(
        range=[
            valor_minimo - margen,
            valor_maximo + margen,
        ],
    )
    st.plotly_chart(
        figura_rentabilidad,
        use_container_width=True,
    )

    st.subheader("Evolución del valor de los portafolios")
    datos_evolucion = pd.DataFrame(evolucion)

    if not datos_evolucion.empty:
        datos_evolucion["fecha"] = pd.to_datetime(
            datos_evolucion["fecha"]
        )
        figura_evolucion = px.line(
            datos_evolucion,
            x="fecha",
            y="valor_total",
            color="agente",
            labels={
                "fecha": "Fecha",
                "valor_total": "Valor del portafolio ($)",
                "agente": "Agente",
            },
        )
        st.plotly_chart(
            figura_evolucion,
            use_container_width=True,
        )

    st.subheader("Operaciones ejecutadas")
    operaciones = [
        int(fila["operaciones"])
        for fila in ranking
    ]
    colores_operaciones = [
        "#00C853" if cantidad > 0 else "#64748B"
        for cantidad in operaciones
    ]

    figura_operaciones = go.Figure(
        go.Bar(
            x=operaciones,
            y=nombres,
            orientation="h",
            marker_color=colores_operaciones,
            text=[
                str(cantidad) if cantidad else ""
                for cantidad in operaciones
            ],
            textposition="outside",
            cliponaxis=False,
        )
    )

    for nombre, cantidad in zip(nombres, operaciones):
        if cantidad == 0:
            figura_operaciones.add_annotation(
                x=0,
                y=nombre,
                text="0",
                showarrow=False,
                xshift=20,
            )

    figura_operaciones.update_layout(
        template="plotly_dark",
        showlegend=False,
        xaxis_title="Cantidad de operaciones",
        yaxis_title="Agente",
        height=320,
    )
    st.plotly_chart(
        figura_operaciones,
        use_container_width=True,
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


def mostrar_configuracion_datos():
    st.title("Configuración y datos")
    st.info(
        "Aquí puedes elegir los tickers y el periodo de precios, guardar "
        "los ajustes, descargar el CSV y cargarlo en la base conectada."
    )

    configuracion = cargar_configuracion()
    datos_config = configuracion["datos"]
    simulacion_config = configuracion["simulacion"]
    ollama_config = configuracion["ollama"]

    catalogo_tickers = sorted(set(
        configuracion["tickers"]
        + ["AAPL", "MSFT", "NVDA", "KO", "JPM", "TSLA"]
    ))

    fecha_fin_default = date.today()
    fecha_inicio_default = fecha_fin_default - timedelta(days=365)

    if datos_config.get("fecha_inicio"):
        fecha_inicio_default = date.fromisoformat(
            str(datos_config["fecha_inicio"])
        )
    if datos_config.get("fecha_fin"):
        fecha_fin_default = date.fromisoformat(
            str(datos_config["fecha_fin"])
        )

    modelos = sorted(set([
        ollama_config["modelo"],
        "llama3.2:3b",
        "qwen2.5:3b",
    ]))

    with st.form("form_configuracion_datos"):
        st.subheader("Parámetros de simulación")

        tickers = st.multiselect(
            "Tickers",
            options=catalogo_tickers,
            default=configuracion["tickers"],
            help="Selecciona los instrumentos que analizarán los agentes.",
        )

        col_fecha_inicio, col_fecha_fin = st.columns(2)
        fecha_inicio = col_fecha_inicio.date_input(
            "Fecha inicial de los precios",
            value=fecha_inicio_default,
        )
        fecha_fin = col_fecha_fin.date_input(
            "Fecha final de los precios",
            value=fecha_fin_default,
        )

        col_capital, col_dias = st.columns(2)
        capital_inicial = col_capital.number_input(
            "Capital inicial (USD)",
            min_value=1000.0,
            step=1000.0,
            value=float(simulacion_config["capital_inicial"]),
        )
        dias_habiles = col_dias.number_input(
            "Días hábiles a simular",
            min_value=1,
            max_value=252,
            step=1,
            value=int(simulacion_config["dias_habiles"]),
        )

        modelo = st.selectbox(
            "Modelo de Ollama",
            options=modelos,
            index=modelos.index(ollama_config["modelo"]),
            help="Los cuatro agentes usarán el mismo modelo.",
        )

        guardar = st.form_submit_button(
            "Guardar configuración",
            width="stretch",
        )
        guardar_y_descargar = st.form_submit_button(
            "Guardar y descargar precios",
            type="primary",
            width="stretch",
        )

    if guardar or guardar_y_descargar:
        try:
            guardar_ajustes(
                tickers=tickers,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                capital_inicial=capital_inicial,
                dias_habiles=dias_habiles,
                modelo=modelo,
            )
            st.success("Configuración guardada en `config.yaml`.")

            if guardar_y_descargar:
                with st.spinner(
                    "Descargando precios; esto requiere internet..."
                ):
                    ruta_csv, filas = descargar_csv_configurado(
                        tickers,
                        fecha_inicio,
                        fecha_fin,
                    )
                st.success(
                    f"Descarga completada: {filas:,} cotizaciones en "
                    f"`{ruta_csv}`."
                )
        except Exception as exc:
            st.error(f"No se pudo guardar o descargar: {exc}")

    st.divider()
    st.subheader("Comisión por operación")
    st.caption(
        "La comisión se guarda en la base de datos conectada. "
        "El valor inicial del proyecto es 0,1 %."
    )

    try:
        comision_actual = obtener_comision_porcentaje()

        with st.form("form_comision"):
            comision_pct = st.number_input(
                "Comisión (%)",
                min_value=0.0,
                max_value=100.0,
                step=0.05,
                value=comision_actual,
                format="%.3f",
            )
            guardar_comision = st.form_submit_button(
                "Guardar comisión",
                width="stretch",
            )

        if guardar_comision:
            guardar_comision_porcentaje(comision_pct)
            st.success("Comisión actualizada en la base de datos.")
    except Exception as exc:
        st.warning(
            "No pude leer o actualizar la comisión. Comprueba la conexión "
            f"y el esquema de PostgreSQL. Detalle: {exc}"
        )

    st.divider()
    st.subheader("Crear o reiniciar la base de datos demo")
    st.warning(
        "Si la base demo no existe, intenta crearla. Si ya existe, elimina "
        "todos los objetos y datos del esquema `public` y vuelve a crear las "
        "tablas, vistas y procedimientos. Después tendrás que cargar de nuevo "
        "el CSV. Solo funciona en la base demo."
    )

    if obtener_parametros_bd()["dbname"] != BASE_DEMO:
        st.info(
                f"Para proteger otras bases, esta opción solo funciona cuando "
            f"`.env` apunta a `{BASE_DEMO}`."
        )
    else:
        estado_control = obtener_control().estado()
        simulacion_activa = estado_control.get("hilo_activo", False)
        if simulacion_activa:
            st.error(
                "No se puede reiniciar mientras la simulación está activa. "
                "Páusala o espera a que termine."
            )

        with st.form("form_reinicio_bd_demo"):
            nombre_confirmacion = st.text_input(
                f"Escribe `{BASE_DEMO}` para confirmar",
                disabled=simulacion_activa,
            )
            confirmar_borrado = st.checkbox(
                "Entiendo que, si ya existe, se borrará el contenido de su "
                "esquema public.",
                disabled=simulacion_activa,
            )
            reiniciar = st.form_submit_button(
                "Crear o reiniciar base demo",
                type="primary",
                disabled=simulacion_activa,
                width="stretch",
            )

        if reiniciar:
            if not confirmar_borrado:
                st.error("Marca la casilla para confirmar el reinicio.")
            elif nombre_confirmacion != BASE_DEMO:
                st.error(f"El nombre debe coincidir exactamente: {BASE_DEMO}.")
            else:
                try:
                    with st.spinner("Creando la base y su esquema..."):
                        base_creada = crear_o_reiniciar_base_demo(
                            nombre_confirmacion
                        )
                    obtener_control.clear()
                    consultar_estado_sistema.clear()
                    st.cache_data.clear()
                    mensaje = (
                        "Base demo creada desde cero."
                        if base_creada
                        else "Esquema de la base demo reiniciado."
                    )
                    st.success(
                        f"{mensaje} Carga nuevamente el CSV antes de "
                        "iniciar una simulación."
                    )
                except Exception as exc:
                    st.error(f"No se pudo reiniciar la base demo: {exc}")

    st.divider()
    st.subheader("Cargar precios a PostgreSQL")
    st.write(
        "Este botón valida `data/precios_historicos.csv` y carga sus precios "
        "en la base conectada. Las cotizaciones existentes se actualizan."
    )

    if st.button(
        "Cargar CSV en la base de datos",
        type="primary",
    ):
        try:
            with st.spinner("Validando y cargando las cotizaciones..."):
                filas = cargar_csv_configurado()
            st.success(
                f"Carga completada: {filas:,} cotizaciones procesadas."
            )
        except Exception as exc:
            st.error(f"No se pudo cargar el CSV: {exc}")


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
    "Resumen",
    "Simulación",
    "Agentes",
    "Mercado",
    "Métricas",
    "Configuración y datos",
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

st.sidebar.caption(f"Base: {parametros_bd['dbname']}")

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
elif pagina == "Configuración y datos":
    mostrar_configuracion_datos()

