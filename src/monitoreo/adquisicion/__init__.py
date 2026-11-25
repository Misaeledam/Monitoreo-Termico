"""Módulo de adquisición (RF-01, RF-02, RF-06)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..config import Config
from ..modelos import Ciclo


class Adquisidor(Protocol):
    def leer_ciclo(self, marca: datetime) -> Ciclo: ...

    def cerrar(self) -> None: ...


def crear_adquisidor(cfg: Config, inicio: datetime | None = None) -> Adquisidor:
    """Devuelve el adquisidor real (Raspberry Pi) o el simulado (entorno virtual)."""
    if cfg.sondas.modo == "simulado":
        from .simulado import AdquisidorSimulado

        return AdquisidorSimulado(cfg.sondas.escenario, inicio=inicio)
    from .real import AdquisidorReal

    return AdquisidorReal(cfg.sondas)
