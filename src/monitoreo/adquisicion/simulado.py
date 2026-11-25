"""Sondas simuladas por software para el entorno virtual simulado (T-03, sección 4.5).

Los puntos críticos (temperatura por encima del límite permitido o por debajo de 2 °C,
condensación, subidas bruscas, agua) no se provocan sobre el bastidor real: se inyectan
acá con valores conocidos. Cada escenario es una función del tiempo transcurrido.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime

from ..analisis import MAGNUS_A, MAGNUS_B, punto_rocio
from ..modelos import Ciclo, LecturaAgua, LecturaAmbiental, Ubicacion

# Cada escenario devuelve (t_entrada, hr_entrada, t_salida, hr_salida, agua, salida_valida)
Escenario = Callable[[float], tuple[float, float, float, float, bool, bool]]


def _hr_con_rocio(temperatura: float, rocio: float) -> float:
    """Humedad relativa que corresponde a un punto de rocío fijo (Magnus, mismas constantes
    que analisis.py). Al calentarse el aire sin agregar agua, el rocío no cambia y la HR baja."""
    a, b = MAGNUS_A, MAGNUS_B
    return 100.0 * math.exp(a * rocio / (b + rocio) - a * temperatura / (b + temperatura))


def _base(minutos: float) -> tuple[float, float]:
    """Ambiente normal: 21,5 °C con una oscilación suave del aire acondicionado."""
    return 21.5 + 0.3 * math.sin(minutos / 7.0), 45.0 + 2.0 * math.sin(minutos / 11.0)


def _con_salida(t: float, hr: float, agua: bool = False, salida_ok: bool = True):
    """Completa la sonda de salida: 9 °C más caliente y con el mismo punto de rocío."""
    t_out = t + 9.0
    return t, hr, t_out, _hr_con_rocio(t_out, punto_rocio(t, hr)), agua, salida_ok


def normal(m: float):
    t, hr = _base(m)
    return _con_salida(t, hr)


def calentamiento(m: float):
    """Falla de refrigeración: la entrada sube 0,5 °C por minuto desde el minuto 5."""
    t0, hr0 = _base(m)
    rocio = punto_rocio(t0, hr0)
    t = t0 + (0.5 * (m - 5) if m > 5 else 0.0)
    return _con_salida(t, _hr_con_rocio(t, rocio))


def subida_brusca(m: float):
    """Escalón de +8 °C repartido en 5 minutos a partir del minuto 20 (RN-06)."""
    t0, hr0 = _base(m)
    rocio = punto_rocio(t0, hr0)
    t = t0 + (min(8.0, 8.0 * (m - 20) / 5.0) if m > 20 else 0.0)
    return _con_salida(t, _hr_con_rocio(t, rocio))


def sobre_limite(m: float):
    """Temperatura de entrada por encima del límite permitido (32 °C)."""
    _, hr = _base(m)
    return _con_salida(33.5, hr)


def bajo_2(m: float):
    """Temperatura de entrada por debajo de 2 °C (punto crítico inferior, RN-03)."""
    _, hr = _base(m)
    return _con_salida(1.5, hr)


def condensacion(m: float):
    """La humedad sube hasta acercar el punto de rocío a la temperatura de entrada."""
    t = 22.0
    hr = min(96.0, 45.0 + 2.0 * m)
    return _con_salida(t, hr)


def agua(m: float):
    """Ambiente normal y detección de agua a partir del minuto 3."""
    t, hr = _base(m)
    return _con_salida(t, hr, agua=m >= 3)


def falla_sonda(m: float):
    """La sonda de salida deja de responder a partir del minuto 2."""
    t, hr = _base(m)
    return _con_salida(t, hr, salida_ok=m < 2)


ESCENARIOS: dict[str, Escenario] = {
    "normal": normal,
    "calentamiento": calentamiento,
    "subida_brusca": subida_brusca,
    "sobre_limite": sobre_limite,
    "bajo_2": bajo_2,
    "condensacion": condensacion,
    "agua": agua,
    "falla_sonda": falla_sonda,
}


class AdquisidorSimulado:
    def __init__(self, escenario: str, inicio: datetime | None = None):
        if escenario not in ESCENARIOS:
            raise ValueError(f"Escenario desconocido '{escenario}'. Opciones: {', '.join(ESCENARIOS)}")
        self.nombre = escenario
        self._funcion = ESCENARIOS[escenario]
        self._inicio = inicio

    def leer_ciclo(self, marca: datetime) -> Ciclo:
        if self._inicio is None:
            self._inicio = marca
        minutos = (marca - self._inicio).total_seconds() / 60.0
        t_in, hr_in, t_out, hr_out, hay_agua, salida_ok = self._funcion(minutos)
        entrada = LecturaAmbiental(Ubicacion.ENTRADA, round(t_in, 2), round(hr_in, 2), True)
        if salida_ok:
            salida = LecturaAmbiental(Ubicacion.SALIDA, round(t_out, 2), round(hr_out, 2), True)
        else:
            salida = LecturaAmbiental(Ubicacion.SALIDA, None, None, False,
                                      error="sin respuesta (simulado)")
        return Ciclo(marca_temporal=marca, entrada=entrada, salida=salida,
                     agua=LecturaAgua(detectada=hay_agua, valida=True))

    def cerrar(self) -> None:
        pass
