"""Adquisidor con el hardware real: 2 × SHT31 por I²C y sonda de agua por GPIO."""

from __future__ import annotations

from datetime import datetime

from ..config import ConfigSondas
from ..modelos import Ciclo, LecturaAgua, Ubicacion
from .sht31 import SondaSHT31


class SondaAgua:
    """Sonda de conductividad de dos electrodos entre el GPIO y GND.

    Con la resistencia de pull-up interna activada, el pin queda en alto con la base seca;
    el agua une los electrodos y lleva el pin a bajo. Para ``gpiozero``, un dispositivo con
    ``pull_up=True`` está "activo" en bajo, así que ``is_active`` significa "hay agua".
    Se toman tres lecturas seguidas y se exige mayoría para filtrar ruido.
    """

    def __init__(self, gpio: int):
        from gpiozero import DigitalInputDevice  # solo en la Raspberry Pi

        self._dispositivo = DigitalInputDevice(gpio, pull_up=True)

    def leer(self) -> LecturaAgua:
        try:
            votos = sum(1 for _ in range(3) if self._dispositivo.is_active)
            return LecturaAgua(detectada=votos >= 2, valida=True)
        except Exception as exc:  # noqa: BLE001 - cualquier falla del GPIO invalida la lectura
            return LecturaAgua(detectada=None, valida=False, error=str(exc))

    def cerrar(self) -> None:
        self._dispositivo.close()


class AdquisidorReal:
    def __init__(self, cfg: ConfigSondas):
        self.entrada = SondaSHT31(cfg.entrada.bus, cfg.entrada.direccion, Ubicacion.ENTRADA)
        self.salida = SondaSHT31(cfg.salida.bus, cfg.salida.direccion, Ubicacion.SALIDA)
        self.agua = SondaAgua(cfg.gpio_agua)

    def leer_ciclo(self, marca: datetime) -> Ciclo:
        return Ciclo(marca_temporal=marca, entrada=self.entrada.leer(),
                     salida=self.salida.leer(), agua=self.agua.leer())

    def cerrar(self) -> None:
        self.agua.cerrar()
