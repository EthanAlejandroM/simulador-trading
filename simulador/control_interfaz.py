"""Controla la simulación desde la interfaz, procesando una fecha a la vez."""

import logging
import threading
import time
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
    ejecutar_dry_run,
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
    """Estado compartido para los controles de la interfaz Streamlit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._reanudar = threading.Event()
        self._reanudar.set()
        self._hilo: threading.Thread | None = None

        self._estado = "inactivo"
        self._fecha_actual: str | None = None
        self._completados = 0
        self._total = 0
        self._eta_segundos: float | None = None
        self._error: str | None = None

    def estado(self) -> dict[str, Any]:
        with self._lock:
            return {
                "estado": self._estado,
                "fecha_actual": self._fecha_actual,
                "completados": self._completados,
                "total": self._total,
                "eta_segundos": self._eta_segundos,
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
                "Así se protegen los resultados de la base principal."
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

    def _preparar_dry_run(self):
        """Prepara datos para dry-run sin crear agentes persistentes."""
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

        return configuracion, tickers, historial, fechas

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

    def ejecutar_prueba_dry_run(self) -> str:
        """Ejecuta el dry-run reversible definido en el motor."""
        if self.estado()["hilo_activo"]:
            raise RuntimeError(
                "Pausa o termina la simulación automática antes del dry-run."
            )

        configuracion, tickers, historial, fechas = (
            self._preparar_dry_run()
        )

        with self._lock:
            self._estado = "dry-run"
            self._error = None
            self._fecha_actual = None
            self._completados = 0
            self._total = min(3, len(fechas))
            self._eta_segundos = None

        try:
            ejecutar_dry_run(
                historial,
                tickers,
                fechas,
                configuracion["simulacion"]["capital_inicial"],
            )
            with self._lock:
                self._estado = "inactivo"
                self._completados = self._total
            return (
                "Dry-run terminado. Los cambios se revirtieron "
                "y no se llamó a Ollama."
            )
        except Exception as exc:
            LOGGER.exception("Falló el dry-run desde la interfaz.")
            with self._lock:
                self._estado = "error"
                self._error = str(exc)
            raise

    def avanzar_un_dia(self) -> str:
        """Procesa solo la primera fecha pendiente."""
        if self.estado()["hilo_activo"]:
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
                self._eta_segundos = 0
            return "La simulación ya está completa; no quedan días pendientes."

        fecha = pendientes[0]
        inicio = time.perf_counter()

        with self._lock:
            self._estado = "avanzando"
            self._fecha_actual = fecha.isoformat()
            self._completados = 0
            self._total = 1
            self._eta_segundos = None
            self._error = None

        try:
            self._ejecutar_fecha(contexto, fecha)
            duracion = time.perf_counter() - inicio
            quedan_pendientes = self._fechas_pendientes(contexto)

            with self._lock:
                self._completados = 1
                self._estado = "inactivo" if quedan_pendientes else "completo"
                self._fecha_actual = None
                self._eta_segundos = 0

            return f"Día {fecha} procesado en {duracion:.1f} segundos."
        except Exception as exc:
            LOGGER.exception("Falló el avance de un día.")
            with self._lock:
                self._estado = "error"
                self._error = str(exc)
                self._fecha_actual = None
            raise

    def iniciar(self) -> str:
        """Inicia la simulación automática en segundo plano."""
        if self.estado()["hilo_activo"]:
            return "La simulación ya está ejecutándose."

        contexto = self._preparar()
        pendientes = self._fechas_pendientes(contexto)

        if not pendientes:
            with self._lock:
                self._estado = "completo"
                self._fecha_actual = None
                self._completados = 0
                self._total = 0
                self._eta_segundos = 0
                self._error = None
            return "La simulación ya está completa; no quedan días pendientes."

        self._reanudar.set()
        with self._lock:
            self._estado = "ejecutando"
            self._fecha_actual = None
            self._completados = 0
            self._total = len(pendientes)
            self._eta_segundos = None
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
        duraciones = []

        try:
            for indice, fecha in enumerate(pendientes, start=1):
                if not self._reanudar.is_set():
                    with self._lock:
                        self._estado = "pausada"

                self._reanudar.wait()

                with self._lock:
                    self._estado = "ejecutando"
                    self._fecha_actual = fecha.isoformat()

                inicio = time.perf_counter()
                self._ejecutar_fecha(contexto, fecha)
                duraciones.append(time.perf_counter() - inicio)

                promedio = sum(duraciones) / len(duraciones)
                dias_restantes = len(pendientes) - indice

                with self._lock:
                    self._completados = indice
                    self._fecha_actual = None
                    self._eta_segundos = promedio * dias_restantes

            with self._lock:
                self._estado = "completo"
                self._fecha_actual = None
                self._eta_segundos = 0
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
        """Continúa una simulación pausada."""
        with self._lock:
            if self._estado in ("pausada", "pausando"):
                self._estado = "ejecutando"
                self._reanudar.set()