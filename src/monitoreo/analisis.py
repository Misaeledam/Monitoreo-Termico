"""Motor de análisis: ΔT, punto de rocío y tasa de variación (RF-03, RF-04, RF-05)."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .modelos import CondicionFlujo, LecturaAmbiental, Metricas

# Constantes de la aproximación de Magnus (Alduchov y Eskridge, 1996), las mismas que
# recomienda Lawrence (2005): a = 17.625, b = 243.04 °C. Válidas para el rango de un rack.
MAGNUS_A = 17.625
MAGNUS_B = 243.04


def punto_rocio(temperatura: float, humedad_relativa: float) -> float:
    """Punto de rocío en °C por la aproximación de Magnus-Tetens."""
    if not 0 < humedad_relativa <= 100:
        raise ValueError("La humedad relativa debe estar en (0, 100]")
    gamma = math.log(humedad_relativa / 100.0) + (MAGNUS_A * temperatura) / (
        MAGNUS_B + temperatura
    )
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)


def diferencial_termico(entrada: LecturaAmbiental, salida: LecturaAmbiental) -> float | None:
    """ΔT = salida − entrada. ``None`` si alguna sonda no dio lectura válida (RF-03)."""
    if not (entrada.valida and salida.valida):
        return None
    if entrada.temperatura is None or salida.temperatura is None:
        return None
    return salida.temperatura - entrada.temperatura


def condicion_flujo(delta_t: float | None, limite_alto: float, limite_bajo: float) -> str:
    """Clasifica el flujo de aire a partir del ΔT (RN-07)."""
    if delta_t is None:
        return CondicionFlujo.NO_DISPONIBLE
    if delta_t > limite_alto:
        return CondicionFlujo.RESTRINGIDO
    if delta_t < limite_bajo:
        return CondicionFlujo.DERIVACION
    return CondicionFlujo.NORMAL


@dataclass(slots=True)
class Muestra:
    marca_temporal: datetime
    temperatura: float
    humedad_relativa: float


class VentanaDeslizante:
    """Ventana de lecturas recientes de la sonda de entrada (RF-05, RN-06).

    La variación en un período se mide como (máximo − mínimo) dentro del período, que es
    como ASHRAE expresa el límite: "no más de 5 °C en cualquier período de 15 minutos".
    Solo se informa una tasa cuando la ventana cubre al menos la mitad del período y no
    tiene huecos grandes; así un reinicio o un corte no produce alertas espurias.
    """

    def __init__(self, duracion: timedelta, intervalo_s: float):
        self.duracion = duracion
        self.intervalo_s = intervalo_s
        self._muestras: deque[Muestra] = deque()

    def __len__(self) -> int:
        return len(self._muestras)

    def agregar(self, muestra: Muestra) -> None:
        if self._muestras and muestra.marca_temporal <= self._muestras[-1].marca_temporal:
            return  # descarta duplicados o relojes que retroceden
        hueco_max = timedelta(seconds=self.intervalo_s * 5)
        if self._muestras and muestra.marca_temporal - self._muestras[-1].marca_temporal > hueco_max:
            # Discontinuidad (equipo apagado o sonda caída): se reinicia la ventana.
            self._muestras.clear()
        self._muestras.append(muestra)
        limite = muestra.marca_temporal - self.duracion
        while self._muestras and self._muestras[0].marca_temporal < limite:
            self._muestras.popleft()

    def reconstruir(self, muestras: Iterable[Muestra]) -> None:
        """Recarga la ventana desde la base de datos tras un reinicio."""
        self._muestras.clear()
        for m in sorted(muestras, key=lambda x: x.marca_temporal):
            self.agregar(m)

    def _periodo(self, periodo: timedelta) -> list[Muestra]:
        if not self._muestras:
            return []
        desde = self._muestras[-1].marca_temporal - periodo
        return [m for m in self._muestras if m.marca_temporal >= desde]

    def _cubre(self, muestras: list[Muestra], periodo: timedelta) -> bool:
        if len(muestras) < 2:
            return False
        cobertura = muestras[-1].marca_temporal - muestras[0].marca_temporal
        return cobertura >= periodo / 2

    def variacion_temperatura(self, periodo: timedelta) -> float | None:
        m = self._periodo(periodo)
        if not self._cubre(m, periodo):
            return None
        valores = [x.temperatura for x in m]
        return max(valores) - min(valores)

    def variacion_humedad(self, periodo: timedelta) -> float | None:
        m = self._periodo(periodo)
        if not self._cubre(m, periodo):
            return None
        valores = [x.humedad_relativa for x in m]
        return max(valores) - min(valores)


class MotorAnalisis:
    def __init__(self, ventana: VentanaDeslizante, delta_alto: float, delta_bajo: float,
                 temperatura_referencia: float | None = None):
        self.ventana = ventana
        self.delta_alto = delta_alto
        self.delta_bajo = delta_bajo
        self.temperatura_referencia = temperatura_referencia

    def calcular(self, marca: datetime, entrada: LecturaAmbiental,
                 salida: LecturaAmbiental) -> Metricas:
        met = Metricas(marca_temporal=marca)
        met.delta_t = diferencial_termico(entrada, salida)
        met.condicion_flujo = condicion_flujo(met.delta_t, self.delta_alto, self.delta_bajo)

        for lectura, atributo in ((entrada, "punto_rocio_entrada"),
                                  (salida, "punto_rocio_salida")):
            if (lectura.valida and lectura.temperatura is not None
                    and lectura.humedad_relativa and lectura.humedad_relativa > 0):
                setattr(met, atributo, punto_rocio(lectura.temperatura, lectura.humedad_relativa))

        rocios = [r for r in (met.punto_rocio_entrada, met.punto_rocio_salida) if r is not None]
        t_ref = self.temperatura_referencia
        if t_ref is None and entrada.valida:
            t_ref = entrada.temperatura
        if rocios and t_ref is not None:
            met.margen_condensacion = t_ref - max(rocios)

        if entrada.valida and entrada.temperatura is not None and entrada.humedad_relativa is not None:
            self.ventana.agregar(Muestra(marca, entrada.temperatura, entrada.humedad_relativa))
        met.tasa_t_15min = self.ventana.variacion_temperatura(timedelta(minutes=15))
        met.tasa_t_1h = self.ventana.variacion_temperatura(timedelta(hours=1))
        met.tasa_hr_1h = self.ventana.variacion_humedad(timedelta(hours=1))
        return met
