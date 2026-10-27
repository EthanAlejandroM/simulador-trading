"""Operaciones de configuración y carga solicitadas desde Streamlit."""

from datetime import date
from pathlib import Path

import psycopg
from psycopg import sql
import yaml

from simulador.cargar_datos import cargar_en_postgres, leer_y_validar_csv
from simulador.configuracion import (
    ARCHIVO_CONFIG,
    RAIZ_PROYECTO,
    cargar_configuracion,
    obtener_parametros_bd,
    obtener_ruta_csv,
)
from simulador.descargar_datos import (
    descargar_tickers,
    guardar_csv,
)

NOMBRE_BD_DEMO = "simulador-trading-demo"


def crear_o_reiniciar_base_demo(nombre_confirmado: str) -> bool:
    """Crea la base demo si falta o recrea su esquema public.

    El cambio es transaccional: si falla la creación del esquema o de los
    objetos SQL, PostgreSQL revierte el reinicio del esquema completo.
    Devuelve True si la base se creó en esta llamada.
    """
    parametros = obtener_parametros_bd()
    if parametros["dbname"] != NOMBRE_BD_DEMO:
        raise ValueError(
            f"Operación bloqueada: solo se permite en {NOMBRE_BD_DEMO}."
        )
    if nombre_confirmado != NOMBRE_BD_DEMO:
        raise ValueError(
            f"Escribe exactamente {NOMBRE_BD_DEMO} para confirmar."
        )

    carpeta_sql = RAIZ_PROYECTO / "sql"
    archivos_sql = (
        carpeta_sql / "01_schema.sql",
        carpeta_sql / "02_procedures.sql",
    )
    faltantes = [str(ruta) for ruta in archivos_sql if not ruta.is_file()]
    if faltantes:
        raise FileNotFoundError(
            "No se encontraron los scripts requeridos: " + ", ".join(faltantes)
        )

    parametros_admin = {**parametros, "dbname": "postgres"}
    base_creada = False
    with psycopg.connect(**parametros_admin, autocommit=True) as conexion_admin:
        existe = conexion_admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (NOMBRE_BD_DEMO,),
        ).fetchone()

        if existe is None:
            conexion_admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(NOMBRE_BD_DEMO)
                )
            )
            base_creada = True
        else:
            sesiones = conexion_admin.execute(
                """
                SELECT count(*)
                FROM pg_stat_activity
                WHERE datname = %s
                """,
                (NOMBRE_BD_DEMO,),
            ).fetchone()[0]
            if sesiones:
                raise RuntimeError(
                    "Cierra las conexiones abiertas a la base demo "
                    "(por ejemplo, en pgAdmin) y vuelve a intentarlo."
                )

    esquema_sql, procedimientos_sql = (
        ruta.read_text(encoding="utf-8") for ruta in archivos_sql
    )

    # Un solo contexto transaccional: cualquier error restaura el esquema previo.
    with psycopg.connect(**parametros) as conexion:
        conexion.execute("DROP SCHEMA public CASCADE")
        conexion.execute("CREATE SCHEMA public")
        conexion.execute(esquema_sql)
        conexion.execute(procedimientos_sql)

    return base_creada


def guardar_ajustes(
    tickers: list[str],
    fecha_inicio: date,
    fecha_fin: date,
    capital_inicial: float,
    dias_habiles: int,
    modelo: str,
) -> None:
    """Actualiza config.yaml con los valores elegidos en la interfaz."""
    if not tickers:
        raise ValueError("Selecciona al menos un ticker.")
    if fecha_inicio > fecha_fin:
        raise ValueError("La fecha inicial no puede superar la fecha final.")
    if capital_inicial <= 0:
        raise ValueError("El capital inicial debe ser mayor que cero.")
    if dias_habiles <= 0:
        raise ValueError("Los días hábiles deben ser mayores que cero.")

    configuracion = cargar_configuracion()
    configuracion["tickers"] = sorted({
        ticker.upper() for ticker in tickers
    })
    configuracion["datos"]["fecha_inicio"] = fecha_inicio.isoformat()
    configuracion["datos"]["fecha_fin"] = fecha_fin.isoformat()
    configuracion["simulacion"]["capital_inicial"] = float(capital_inicial)
    configuracion["simulacion"]["dias_habiles"] = int(dias_habiles)
    configuracion["ollama"]["modelo"] = modelo

    with ARCHIVO_CONFIG.open("w", encoding="utf-8") as archivo:
        yaml.safe_dump(
            configuracion,
            archivo,
            sort_keys=False,
            allow_unicode=True,
        )


def descargar_csv_configurado(
    tickers: list[str],
    fecha_inicio: date,
    fecha_fin: date,
) -> tuple[str, int]:
    """Descarga el rango indicado y lo guarda en el CSV configurado."""
    if fecha_inicio > fecha_fin:
        raise ValueError("La fecha inicial no puede superar la fecha final.")

    configuracion = cargar_configuracion()
    precios = descargar_tickers(
        tickers=tickers,
        periodo=configuracion["datos"]["periodo_descarga"],
        intervalo=configuracion["datos"].get("intervalo", "1d"),
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )
    ruta_csv = guardar_csv(precios)
    return ruta_csv, len(precios)


def cargar_csv_configurado() -> int:
    """Valida el CSV configurado y carga sus filas en PostgreSQL."""
    configuracion = cargar_configuracion()
    ruta_csv = obtener_ruta_csv(configuracion)
    precios = leer_y_validar_csv(ruta_csv)
    cargar_en_postgres(precios)
    return len(precios)


def obtener_comision_porcentaje() -> float:
    """Lee de la BD la comisión expresada como porcentaje."""
    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        fila = conexion.execute(
            """
            SELECT comision_porcentaje
            FROM configuracion_simulacion
            WHERE configuracion_id = 1;
            """
        ).fetchone()

    if fila is None:
        raise RuntimeError(
            "No se encontró la configuración inicial de la simulación."
        )

    return float(fila[0]) * 100


def guardar_comision_porcentaje(comision_pct: float) -> None:
    """Guarda la comisión de la base; por ejemplo, 0.1 representa 0,1 %."""
    if not 0 <= comision_pct <= 100:
        raise ValueError("La comisión debe estar entre 0 % y 100 %.")

    with psycopg.connect(**obtener_parametros_bd()) as conexion:
        cursor = conexion.execute(
            """
            UPDATE configuracion_simulacion
            SET comision_porcentaje = %s,
                actualizada_en = now()
            WHERE configuracion_id = 1;
            """,
            (comision_pct / 100,),
        )

        if cursor.rowcount == 0:
            raise RuntimeError(
                "No se encontró la configuración que se debía actualizar."
            )
