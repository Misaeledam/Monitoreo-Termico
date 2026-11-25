"""CP-03 (ΔT), CP-04 (punto de rocío), CP-05 (tasa de variación)."""

from datetime import timedelta

import pytest

from monitoreo.analisis import (
    MotorAnalisis,
    Muestra,
    VentanaDeslizante,
    condicion_flujo,
    diferencial_termico,
    punto_rocio,
)
from monitoreo.modelos import CondicionFlujo, LecturaAmbiental


def _rocio_referencia(t, hr):
    # Misma aproximación de Magnus (a = 17.625, b = 243.04 °C) escrita como en la planilla
    # de B. McNoldy (Univ. de Miami), para contrastar la implementación.
    import math

    a, b = 17.625, 243.04
    return b * (math.log(hr / 100) + a * t / (b + t)) / (a - math.log(hr / 100) - a * t / (b + t))


@pytest.mark.parametrize("t,hr", [(22.0, 45.0), (25.0, 50.0), (30.0, 80.0), (5.0, 90.0)])
def test_punto_rocio_coincide_con_referencia(t, hr):
    assert punto_rocio(t, hr) == pytest.approx(_rocio_referencia(t, hr), abs=1e-9)


def test_punto_rocio_saturado_es_la_temperatura():
    assert punto_rocio(20.0, 100.0) == pytest.approx(20.0, abs=1e-9)


def test_punto_rocio_crece_con_la_humedad():
    assert punto_rocio(22, 40) < punto_rocio(22, 60) < punto_rocio(22, 80)


def test_punto_rocio_humedad_invalida():
    with pytest.raises(ValueError):
        punto_rocio(22, 0)


def test_delta_t_y_condicion_flujo():
    ent = LecturaAmbiental("ENTRADA", 22.0, 45.0, True)
    sal = LecturaAmbiental("SALIDA", 33.5, 30.0, True)
    assert diferencial_termico(ent, sal) == pytest.approx(11.5)
    assert condicion_flujo(11.5, 20, 1) == CondicionFlujo.NORMAL
    assert condicion_flujo(21, 20, 1) == CondicionFlujo.RESTRINGIDO
    assert condicion_flujo(0.5, 20, 1) == CondicionFlujo.DERIVACION


def test_delta_t_no_disponible_si_falta_una_sonda():
    ent = LecturaAmbiental("ENTRADA", 22.0, 45.0, True)
    sal = LecturaAmbiental("SALIDA", None, None, False, "sin respuesta")
    assert diferencial_termico(ent, sal) is None
    assert condicion_flujo(None, 20, 1) == CondicionFlujo.NO_DISPONIBLE


def test_ventana_detecta_5_grados_en_15_minutos(t0):
    v = VentanaDeslizante(timedelta(minutes=60), 60)
    for i in range(16):  # sube 0,4 °C por minuto: 6 °C en 15 min
        v.agregar(Muestra(t0 + timedelta(minutes=i), 22.0 + 0.4 * i, 45))
    assert v.variacion_temperatura(timedelta(minutes=15)) == pytest.approx(6.0)


def test_ventana_no_informa_con_poca_cobertura(t0):
    v = VentanaDeslizante(timedelta(minutes=60), 60)
    for i in range(5):
        v.agregar(Muestra(t0 + timedelta(minutes=i), 22.0 + i, 45))
    assert v.variacion_temperatura(timedelta(minutes=15)) is None  # 4 min < 7,5 min


def test_ventana_se_reinicia_tras_un_hueco(t0):
    v = VentanaDeslizante(timedelta(minutes=60), 60)
    for i in range(20):
        v.agregar(Muestra(t0 + timedelta(minutes=i), 22.0, 45))
    # Corte de 30 minutos: al volver no debe compararse con datos viejos.
    v.agregar(Muestra(t0 + timedelta(minutes=50), 30.0, 45))
    assert len(v) == 1
    assert v.variacion_temperatura(timedelta(minutes=15)) is None


def test_ventana_reconstruir_tras_reinicio(t0):
    v = VentanaDeslizante(timedelta(minutes=60), 60)
    v.reconstruir([Muestra(t0 + timedelta(minutes=i), 22.0 + 0.1 * i, 45) for i in range(30)])
    assert v.variacion_temperatura(timedelta(minutes=15)) == pytest.approx(1.5)


def test_motor_calcula_margen_con_temperatura_de_entrada(t0):
    motor = MotorAnalisis(VentanaDeslizante(timedelta(minutes=60), 60), 20, 1)
    ent = LecturaAmbiental("ENTRADA", 22.0, 50.0, True)
    sal = LecturaAmbiental("SALIDA", 31.0, 30.0, True)
    met = motor.calcular(t0, ent, sal)
    # Se usa el punto de rocío más alto de las dos sondas (criterio conservador).
    peor = max(punto_rocio(22.0, 50.0), punto_rocio(31.0, 30.0))
    assert met.margen_condensacion == pytest.approx(22.0 - peor)
    assert met.delta_t == pytest.approx(9.0)
