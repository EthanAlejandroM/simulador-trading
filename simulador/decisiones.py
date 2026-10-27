"""Validación y consulta a Ollama para obtener hasta tres decisiones."""

import json
import time
from typing import Literal

from ollama import Client
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Decision(BaseModel):
    """Una decisión propuesta para un ticker."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    accion: Literal["COMPRAR", "VENDER", "MANTENER"]
    cantidad: int = Field(ge=0)
    justificacion: str = Field(max_length=200)


class DecisionBatch(BaseModel):
    """Respuesta completa del agente."""

    model_config = ConfigDict(extra="forbid")

    decisiones: list[Decision] = Field(max_length=3)


def consultar_ollama(
    cliente: Client,
    modelo: str,
    prompt_sistema: str,
    mensaje_usuario: str,
    tickers_validos: set[str],
    temperatura: float,
    num_predict: int,
) -> tuple[list[Decision] | None, dict, bool, int, str | None]:
    """Llama al modelo y reintenta una vez si la salida no valida."""
    inicio = time.perf_counter()
    error_anterior = None
    respuesta_cruda = ""
    schema = DecisionBatch.model_json_schema()

    for intento in range(2):
        mensaje = mensaje_usuario
        if intento == 1:
            mensaje += (
                "\n\nTu respuesta anterior no pasó la validación: "
                f"{error_anterior}. Corrige la salida y devuelve solo JSON."
            )

        respuesta = cliente.chat(
            model=modelo,
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": mensaje},
            ],
            format=schema,
            options={
                "temperature": temperatura,
                "num_predict": num_predict,
            },
        )
        respuesta_cruda = respuesta.message.content

        try:
            lote = DecisionBatch.model_validate_json(respuesta_cruda)
            decisiones = lote.decisiones
            vistos = set()

            for decision in decisiones:
                ticker = decision.ticker.upper()
                if ticker not in tickers_validos:
                    raise ValueError(f"Ticker no permitido: {ticker}")
                if ticker in vistos:
                    raise ValueError(f"Ticker repetido: {ticker}")
                vistos.add(ticker)

                if decision.accion == "MANTENER" and decision.cantidad != 0:
                    raise ValueError("MANTENER requiere cantidad 0.")
                if decision.accion in ("COMPRAR", "VENDER") and decision.cantidad <= 0:
                    raise ValueError("COMPRAR y VENDER requieren cantidad positiva.")

            contenido = json.loads(respuesta_cruda)
            latencia_ms = int((time.perf_counter() - inicio) * 1000)
            return decisiones, contenido, True, latencia_ms, None

        except (ValidationError, json.JSONDecodeError, ValueError) as error:
            error_anterior = str(error)

    latencia_ms = int((time.perf_counter() - inicio) * 1000)
    contenido_seguro = {
        "respuesta_cruda": respuesta_cruda,
        "error_validacion": error_anterior,
    }
    return None, contenido_seguro, False, latencia_ms, error_anterior