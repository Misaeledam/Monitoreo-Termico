"""CP-06 (agua), CP-07 (severidad), CP-08 (histéresis y repetición)."""

from datetime import timedelta

from conftest import ciclo
from monitoreo.analisis import MotorAnalisis, VentanaDeslizante
from monitoreo.modelos import Criterio, Nivel
from monitoreo.severidad import Clasificador


def _evaluador(cfg):
    motor = MotorAnalisis(VentanaDeslizante(timedelta(minutes=60), 60), 20, 1)
    clasif = Clasificador(cfg.umbrales, timedelta(minutes=10))

    def evaluar(c):
        return clasif.evaluar(c, motor.calcular(c.marca_temporal, c.entrada, c.salida))

    return evaluar


def test_niveles_de_temperatura_de_entrada(cfg, t0):
    casos = [(22.0, Nivel.NORMAL), (24.5, Nivel.AVISO), (28.0, Nivel.ADVERTENCIA),
             (33.0, Nivel.CRITICO), (16.0, Nivel.ADVERTENCIA), (1.5, Nivel.CRITICO)]
    for t, esperado in casos:
        evaluar = _evaluador(cfg)
        assert evaluar(ciclo(t0, t_in=t, t_out=t + 9)).nivel == esperado, t


def test_agua_es_critico_inmediato_y_se_notifica(cfg, t0):
    evaluar = _evaluador(cfg)
    assert evaluar(ciclo(t0)).nivel == Nivel.NORMAL
    ev = evaluar(ciclo(t0 + timedelta(minutes=1), agua=True))
    assert ev.nivel == Nivel.CRITICO
    assert ev.notificar
    assert ev.disparos[0].criterio == Criterio.AGUA


def test_agua_se_notifica_aunque_ya_este_en_critico(cfg, t0):
    evaluar = _evaluador(cfg)
    evaluar(ciclo(t0, t_in=33, t_out=42))
    ev = evaluar(ciclo(t0 + timedelta(minutes=1), t_in=33, t_out=42, agua=True))
    assert ev.notificar and ev.motivo_notificacion == "detección de agua"


def test_histeresis_evita_oscilacion(cfg, t0):
    evaluar = _evaluador(cfg)
    assert evaluar(ciclo(t0, t_in=24.3)).nivel == Nivel.AVISO
    # Baja a 23,6 °C: debajo del umbral (24) pero no del margen (24 − 1 = 23): sigue en Aviso.
    ev = evaluar(ciclo(t0 + timedelta(minutes=1), t_in=23.6))
    assert ev.nivel == Nivel.AVISO and not ev.cambio
    # Atraviesa el margen: vuelve a Normal y se notifica la normalización.
    ev = evaluar(ciclo(t0 + timedelta(minutes=2), t_in=22.9))
    assert ev.nivel == Nivel.NORMAL and ev.notificar
    assert ev.motivo_notificacion == "normalización"


def test_notifica_por_cambio_y_repite_tras_tiempo_minimo(cfg, t0):
    evaluar = _evaluador(cfg)
    ev = evaluar(ciclo(t0, t_in=28))
    assert ev.notificar and ev.motivo_notificacion == "cambio de nivel"
    for minuto in range(1, 10):
        assert not evaluar(ciclo(t0 + timedelta(minutes=minuto), t_in=28)).notificar
    ev = evaluar(ciclo(t0 + timedelta(minutes=10), t_in=28))
    assert ev.notificar and ev.motivo_notificacion == "condición persistente"


def test_toma_el_nivel_mas_alto_entre_metricas(cfg, t0):
    evaluar = _evaluador(cfg)
    # Temperatura en aviso (24,5) y humedad en advertencia (85 %).
    ev = evaluar(ciclo(t0, t_in=24.5, hr_in=85))
    assert ev.nivel == Nivel.ADVERTENCIA
    metricas = {d.metrica for d in ev.disparos}
    assert {"temperatura_entrada", "humedad_relativa"} <= metricas


def test_tasa_de_variacion_se_registra_como_criterio_tasa(cfg, t0):
    evaluar = _evaluador(cfg)
    ev = None
    for i in range(16):  # +0,4 °C/min: 6 °C en 15 min, siempre por debajo de 27 °C
        ev = evaluar(ciclo(t0 + timedelta(minutes=i), t_in=18.5 + 0.4 * i, t_out=27 + 0.4 * i))
    tasas = [d for d in ev.disparos if d.criterio == Criterio.TASA]
    assert tasas and tasas[0].nivel == Nivel.ADVERTENCIA


def test_sonda_sin_lectura_genera_aviso(cfg, t0):
    evaluar = _evaluador(cfg)
    ev = None
    for i in range(3):
        ev = evaluar(ciclo(t0 + timedelta(minutes=i), salida_valida=False))
    assert ev.nivel == Nivel.AVISO
    assert any(d.metrica == "sonda" for d in ev.disparos)
