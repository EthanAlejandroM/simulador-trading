"""Carga la configuración YAML y las variables privadas del archivo .env."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parents[1]
ARCHIVO_CONFIG = RAIZ_PROYECTO / "config.yaml"
ARCHIVO_ENV = RAIZ_PROYECTO / ".env"


def cargar_configuracion() -> dict[str, Any]:
    """Lee config.yaml y comprueba que tenga los ajustes mínimos."""
    if not ARCHIVO_CONFIG.exists():
        raise FileNotFoundError(f"No se encontró {ARCHIVO_CONFIG}")

    with ARCHIVO_CONFIG.open("r", encoding="utf-8") as archivo:
        configuracion = yaml.safe_load(archivo) or {}

    tickers = configuracion.get("tickers", [])
    if not tickers:
        raise ValueError("config.yaml debe incluir al menos un ticker.")

    datos = configuracion.get("datos", {})
    if not datos.get("periodo_descarga"):
        raise ValueError("Falta datos.periodo_descarga en config.yaml.")
    if not datos.get("archivo_csv"):
        raise ValueError("Falta datos.archivo_csv en config.yaml.")

    return configuracion


def obtener_ruta_csv(configuracion: dict[str, Any]) -> Path:
    """Resuelve la ruta del CSV desde la raíz del proyecto."""
    ruta = Path(configuracion["datos"]["archivo_csv"])
    if not ruta.is_absolute():
        ruta = RAIZ_PROYECTO / ruta
    return ruta


def obtener_parametros_bd() -> dict[str, Any]:
    """Lee las credenciales de PostgreSQL desde .env."""
    load_dotenv(ARCHIVO_ENV)

    nombres = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    faltantes = [nombre for nombre in nombres if not os.getenv(nombre)]

    if faltantes:
        raise ValueError(
            "Faltan variables en .env: " + ", ".join(faltantes)
        )

    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ["DB_PORT"]),
        "dbname": os.environ["DB_NAME"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
    }