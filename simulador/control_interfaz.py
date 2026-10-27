"""Controla la simulación desde la interfaz, procesando una fecha a la vez."""

import logging
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

from ollama import Client

from simulador.configuracion import (
    cargar_configuracion,
    obtener_parametros_bd,
)
from simulador.motor import (
    agente_ya_procesado,
    asegurar_agentes,
    cargar_historial,
    ejecutar_simulacion,
    fechas_comunes,
)

LOGGER = logging.getLogger(__name__)
BASE_DEMO = "simulador-trading-demo"


@dataclass
class ContextoSimulacion:
    configuracion: dict[str, Any]
    tickers: list[str]
    historial: Any
    fechas: list[date]
    agentes: list[tuple[int, str, str]]
    cliente: Client


class ControlSimulacion:
    """Estado compartido para los botones de la interfaz Streamlit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._reanudar = threading.Event()
        self._reanudar.set()
        self._hilo: threading.Thread | None = None

        self._estado = "inactivo"
        self._fecha_actual: str | None = None
        self._completados = 0
        self._total = 0
        self._error: str | None = None

    def estado(self) -> dict[str, Any]:
        with self._lock:
            return {
                "estado": self._estado,
                "fecha_actual": self._fecha_actual,
                "completados": self._completados,
                "total": self._total,
                "error": self._error,
                "hilo_activo": (
                    self._hilo is not None and self._hilo.is_alive()
                ),
            }

    @staticmethod
    def _comprobar_base_demo() -> None:
        parametros = obtener_parametros_bd()
        if parametros["dbname"] != BASE_DEMO:
            raise RuntimeError(
                f"Los controles solo funcionan en la base {BASE_DEMO!r}. "
                "Así se protegen los resultados de la simulación original."
            )

    def _preparar(self) -> ContextoSimulacion:
        self._comprobar_base_demo()

        configuracion = cargar_configuracion()
        tickers = [
            str(ticker).upper()
            for ticker in configuracion["tickers"]
        ]
        historial = cargar_historial()
        fechas = fechas_comunes(
            historial,
            tickers,
            cantidad=configuracion["simulacion"]["dias_habiles"],
        )
        agentes = asegurar_agentes(
            configuracion["simulacion"]["capital_inicial"]
        )
        cliente = Client(host=configuracion["ollama"]["host"])

        return ContextoSimulacion(
            configuracion=configuracion,
            tickers=tickers,
            historial=historial,
            fechas=fechas,
            agentes=agentes,
            cliente=cliente,
        )

    @staticmethod
    def _fechas_pendientes(contexto: ContextoSimulacion) -> list[date]:
        pendientes = []

        for fecha in contexto.fechas:
            falta_algun_agente = any(
                not agente_ya_procesado(
                    agente_id,
                    fecha,
                    contexto.tickers,
                )
                for agente_id, _, _ in contexto.agentes
            )
            if falta_algun_agente:
                pendientes.append(fecha)

        return pendientes

    @staticmethod
    def _ejecutar_fecha(
        contexto: ContextoSimulacion,
        fecha: date,
    ) -> None:
        ejecutar_simulacion(
            contexto.historial,
            contexto.tickers,
            contexto.agentes,
            [fecha],
            contexto.cliente,
            contexto.configuracion,
        )

    def avanzar_un_dia(self) -> str:
        """Procesa solo la primera fecha pendiente."""
        estado = self.estado()
        if estado["hilo_activo"]:
            raise RuntimeError(
                "La simulación automática está activa. Paúsala antes de avanzar."
            )

        contexto = self._preparar()
        pendientes = self._fechas_pendientes(contexto)

        if not pendientes:
            with self._lock:
                self._estado = "completo"
                self._fecha_actual = None
                self._completados = 0
                self._total = 0
            return "La simulación ya está completa; no quedan días pendientes."

        fecha = pendientes[0]
        with self._lock:
            self._estado = "avanzando"
            self._fecha_actual = fecha.isoformat()
            self._completados = 0
            self._total = 1
            self._error = None

        try:
            self._ejecutar_fecha(contexto, fecha)
            quedan_pendientes = self._fechas_pendientes(contexto)

            with self._lock:
                self._completados = 1
                self._estado = "inactivo" if quedan_pendientes else "completo"
                self._fecha_actual = None

            return f"Día {fecha} procesado."
        except Exception as exc:
            LOGGER.exception("Falló el avance de un día.")
            with self._lock:
                self._estado = "error"
                self._error = str(exc)
                self._fecha_actual = None
            raise

    def iniciar(self) -> str:
        """Inicia la simulación automática en segundo plano."""
        estado = self.estado()
        if estado["hilo_activo"]:
            return "La simulación ya está ejecutándose."

        contexto = self._preparar()
        pendientes = self._fechas_pendientes(contexto)

        if not pendientes:
            with self._lock:
                self._estado = "completo"
                self._fecha_actual = None
                self._completados = 0
                self._total = 0
                self._error = None
            return "La simulación ya está completa; no quedan días pendientes."

        self._reanudar.set()
        with self._lock:
            self._estado = "ejecutando"
            self._fecha_actual = None
            self._completados = 0
            self._total = len(pendientes)
            self._error = None

        self._hilo = threading.Thread(
            target=self._ejecutar_lote,
            args=(contexto, pendientes),
            daemon=True,
            name="simulacion-trading",
        )
        self._hilo.start()
        return "Simulación iniciada."

    def _ejecutar_lote(
        self,
        contexto: ContextoSimulacion,
        pendientes: list[date],
    ) -> None:
        try:
            for indice, fecha in enumerate(pendientes, start=1):
                if not self._reanudar.is_set():
                    with self._lock:
                        self._estado = "pausada"

                self._reanudar.wait()

                with self._lock:
                    self._estado = "ejecutando"
                    self._fecha_actual = fecha.isoformat()

                self._ejecutar_fecha(contexto, fecha)

                with self._lock:
                    self._completados = indice
                    self._fecha_actual = None

            with self._lock:
                self._estado = "completo"
                self._fecha_actual = None
        except Exception as exc:
            LOGGER.exception("Falló la simulación automática.")
            with self._lock:
                self._estado = "error"
                self._error = str(exc)
                self._fecha_actual = None

    def pausar(self) -> None:
        """Pide pausar cuando termine el día que está procesando."""
        with self._lock:
            if self._estado == "ejecutando":
                self._estado = "pausando"
                self._reanudar.clear()

    def continuar(self) -> None:
        """Continúa una simulación que está pausada."""
        with self._lock:
            if self._estado in ("pausada", "pausando"):
                self._estado = "ejecutando"
                self._reanudar.set()