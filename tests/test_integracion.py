"""Ciclo completo con sondas simuladas (entorno virtual simulado), SNMP, panel y config."""

import io
from dataclasses import replace
from datetime import timedelta

import pytest

from monitoreo.config import ConfigRecargable, cargar
from monitoreo.modelos import Nivel
from monitoreo.panel import crear_app
from monitoreo.persistencia import BaseDatos
from monitoreo.servicio import Monitor
from monitoreo.snmp_agente import AgenteSnmp


class CanalMemoria:
    def __init__(self):
        self.mensajes = []

    def enviar(self, contacto, mensaje, destinatario):
        self.mensajes.append(mensaje)


def _correr(cfg, escenario, t0, minutos):
    from monitoreo.notificador import Notificador

    cfg = replace(cfg, sondas=replace(cfg.sondas, modo="simulado", escenario=escenario))
    db = BaseDatos(cfg.base_datos)
    canal = CanalMemoria()
    monitor = Monitor(cfg, db=db, notificador=Notificador(cfg, db, {"correo": canal}), inicio=t0)
    evaluaciones = [monitor.ciclo(t0 + timedelta(minutes=i)) for i in range(minutos)]
    return monitor, evaluaciones, canal


@pytest.mark.parametrize("escenario,esperado", [
    ("normal", Nivel.NORMAL),
    ("sobre_limite", Nivel.CRITICO),
    ("subida_brusca", Nivel.ADVERTENCIA),
    ("bajo_2", Nivel.CRITICO),
    ("condensacion", Nivel.CRITICO),
    ("agua", Nivel.CRITICO),
    ("falla_sonda", Nivel.AVISO),
])
def test_escenarios_simulados(cfg, t0, escenario, esperado):
    _, evs, _ = _correr(cfg, escenario, t0, 30)
    assert max(e.nivel for e in evs) == esperado


def test_calentamiento_avisa_por_tasa_antes_que_por_umbral_critico(cfg, t0):
    _, evs, canal = _correr(cfg, "calentamiento", t0, 40)
    primer_tasa = next(i for i, e in enumerate(evs)
                       if any(d.criterio == "TASA" for d in e.disparos))
    primer_critico = next(i for i, e in enumerate(evs) if e.nivel == Nivel.CRITICO)
    assert primer_tasa < primer_critico
    assert canal.mensajes  # se encolaron y "enviaron" notificaciones


def test_reinicio_reconstruye_ventana_sin_alertas_espurias(cfg, t0):
    monitor, _, _ = _correr(cfg, "normal", t0, 30)
    monitor2 = Monitor(cfg, db=monitor.db, inicio=t0 + timedelta(minutes=30))
    assert len(monitor2.analisis.ventana) >= 29
    ev = monitor2.ciclo(t0 + timedelta(minutes=30))
    assert ev.nivel == Nivel.NORMAL and not ev.notificar


def test_agente_snmp_pass_persist(cfg, t0):
    monitor, _, _ = _correr(cfg, "sobre_limite", t0, 3)
    base = cfg.snmp.oid_base
    agente = AgenteSnmp(base, monitor.db.ultimo_estado)
    entrada = io.StringIO(f"PING\nget\n{base}.1.0\nget\n{base}.12.0\ngetnext\n{base}\n"
                          f"get\n{base}.99.0\nset\n{base}.1.0\ninteger 5\n")
    salida = io.StringIO()
    agente.atender(entrada, salida)
    lineas = salida.getvalue().splitlines()
    assert lineas[0] == "PONG"
    assert lineas[1:4] == [f"{base}.1.0", "integer", "3350"]
    assert lineas[4:7] == [f"{base}.12.0", "integer", "3"]
    assert lineas[7:10] == [f"{base}.1.0", "integer", "3350"]
    assert lineas[10] == "NONE"
    assert lineas[11] == "not-writable"


def test_agente_snmp_getnext_recorre_todo(cfg, t0):
    # 35 minutos: la variación en 1 h exige cubrir al menos media hora de datos.
    monitor, _, _ = _correr(cfg, "normal", t0, 35)
    agente = AgenteSnmp(cfg.snmp.oid_base, monitor.db.ultimo_estado)
    oid, vistos = cfg.snmp.oid_base, []
    while (r := agente.getnext(oid)) is not None:
        vistos.append(r[0])
        oid = r[0]
    assert len(vistos) == 15
    assert vistos == sorted(vistos, key=lambda o: tuple(int(x) for x in o.strip(".").split(".")))


def test_panel_responde(cfg, t0):
    _correr(cfg, "normal", t0, 5)
    cliente = crear_app(cfg).test_client()
    assert cliente.get("/").status_code == 200
    estado = cliente.get("/api/estado").get_json()
    assert estado["disponible"] and estado["nivel_texto"] == "Normal"
    assert cliente.get("/api/serie?horas=24").status_code == 200
    assert cliente.get("/configuracion").status_code == 200
    csv = cliente.get("/exportar.csv?dias=1")
    assert csv.status_code == 200 and b"marca_temporal_utc" in csv.data


def test_panel_pide_contrasena_si_hay_hash(cfg, t0, monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setenv("MONITOREO_PANEL_HASH", generate_password_hash("secreta"))
    _correr(cfg, "normal", t0, 2)
    cliente = crear_app(cfg).test_client()
    assert cliente.get("/").status_code == 401
    import base64

    cred = base64.b64encode(b"admin:secreta").decode()
    assert cliente.get("/", headers={"Authorization": f"Basic {cred}"}).status_code == 200


def test_config_ejemplo_carga_y_recarga(tmp_path):
    import pathlib
    import shutil

    origen = pathlib.Path(__file__).parents[1] / "config" / "config.ejemplo.toml"
    copia = tmp_path / "config.toml"
    shutil.copy(origen, copia)
    rec = ConfigRecargable(copia)
    assert rec.actual.umbrales["temperatura_entrada"].histeresis == 1.0
    texto = copia.read_text(encoding="utf-8").replace("aviso_alto = 24.0", "aviso_alto = 25.0")
    copia.write_text(texto, encoding="utf-8")
    import os

    os.utime(copia, (rec._mtime + 5, rec._mtime + 5))
    assert rec.recargar_si_cambio()
    limites = rec.actual.umbrales["temperatura_entrada"].limites
    assert any(lim.valor == 25.0 for lim in limites)
    # Un archivo roto no tumba el servicio: se conserva la configuración anterior.
    copia.write_text("esto no es toml [", encoding="utf-8")
    os.utime(copia, (rec._mtime + 10, rec._mtime + 10))
    assert not rec.recargar_si_cambio() and rec.ultimo_error
    assert cargar(origen).sondas.salida.bus == 4
