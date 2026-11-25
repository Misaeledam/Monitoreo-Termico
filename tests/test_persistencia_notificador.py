"""CP-09 (notificación), CP-10 (persistencia), CP-15 (sin conectividad), CP-17 (exportación)."""

import io
from datetime import timedelta

from conftest import ciclo
from monitoreo.modelos import Evaluacion, Metricas, Nivel
from monitoreo.notificador import ErrorEnvio, Notificador, redactar
from monitoreo.persistencia import BaseDatos


class CanalFalso:
    def __init__(self, fallar=False):
        self.fallar = fallar
        self.enviados = []

    def enviar(self, contacto, mensaje, destinatario):
        if self.fallar:
            raise ErrorEnvio("sin red")
        self.enviados.append((contacto, mensaje))


def _evento(db, t0):
    c = ciclo(t0, t_in=33, t_out=42)
    met = Metricas(t0, delta_t=9.0)
    ev = Evaluacion(nivel=Nivel.CRITICO, nivel_anterior=Nivel.NORMAL, cambio=True,
                    notificar=True, motivo_notificacion="cambio de nivel")
    id_met = db.guardar_ciclo(c, met, ev.nivel)
    return db.registrar_evento(t0, ev, id_met), ev, c, met


def test_guarda_y_recupera_estado(cfg, t0):
    db = BaseDatos(cfg.base_datos)
    db.preparar(cfg)
    db.guardar_ciclo(ciclo(t0, agua=True), Metricas(t0, delta_t=9.0), Nivel.CRITICO)
    estado = db.ultimo_estado()
    assert estado["entrada"]["temperatura"] == 22.0
    assert estado["base"]["agua_detectada"] == 1
    assert estado["nivel"] == Nivel.CRITICO
    assert db.ultimo_nivel() == Nivel.CRITICO


def test_umbrales_se_versionan_al_cambiar(cfg):
    db = BaseDatos(cfg.base_datos)
    db.preparar(cfg)
    n = db.cx.execute("SELECT COUNT(*) FROM umbral WHERE vigente = 1").fetchone()[0]
    db.sincronizar_umbrales(cfg.umbrales)  # sin cambios: no duplica
    assert db.cx.execute("SELECT COUNT(*) FROM umbral").fetchone()[0] == n


def test_notificacion_offline_queda_pendiente_y_se_envia_al_volver(cfg, t0):
    db = BaseDatos(cfg.base_datos)
    db.preparar(cfg)
    canal = CanalFalso(fallar=True)
    notif = Notificador(cfg, db, canales={"correo": canal})
    id_evento, ev, c, met = _evento(db, t0)
    assert notif.encolar(id_evento, ev, c, met) == 1
    assert notif.procesar(t0) == (0, 1)
    assert db.pendientes()[0]["intentos"] == 1
    # Antes del plazo de reintento no se vuelve a intentar.
    assert notif.procesar(t0 + timedelta(seconds=30)) == (0, 0)
    canal.fallar = False
    assert notif.procesar(t0 + timedelta(seconds=61)) == (1, 0)
    assert not db.pendientes()
    assert canal.enviados[0][0] == "g@ejemplo.com"


def test_notificacion_vencida_se_descarta(cfg, t0):
    db = BaseDatos(cfg.base_datos)
    db.preparar(cfg)
    notif = Notificador(cfg, db, canales={"correo": CanalFalso(fallar=True)})
    id_evento, ev, c, met = _evento(db, t0)
    notif.encolar(id_evento, ev, c, met)
    notif.procesar(t0 + timedelta(hours=25))
    assert db.notificaciones()[0]["estado"] == "DESCARTADA"


def test_mensaje_incluye_nivel_valores_y_fecha(cfg, t0):
    c = ciclo(t0, t_in=33, t_out=42)
    ev = Evaluacion(nivel=Nivel.CRITICO, nivel_anterior=Nivel.AVISO, cambio=True,
                    notificar=True, motivo_notificacion="cambio de nivel")
    texto = redactar(cfg, ev, c, Metricas(t0, delta_t=9.0))
    assert "CRÍTICO" in texto and "Aviso" in texto
    assert "33.00 °C" in texto and "9.00 °C" in texto


def test_exportar_csv(cfg, t0):
    db = BaseDatos(cfg.base_datos)
    db.preparar(cfg)
    for i in range(3):
        db.guardar_ciclo(ciclo(t0 + timedelta(minutes=i)), Metricas(t0 + timedelta(minutes=i)),
                         Nivel.NORMAL)
    salida = io.StringIO()
    assert db.exportar_csv(salida, t0 - timedelta(hours=1), t0 + timedelta(hours=1)) == 3
    lineas = salida.getvalue().strip().splitlines()
    assert lineas[0].startswith("marca_temporal_utc")
    assert lineas[1].endswith("Normal")


def test_purga_conserva_metricas_con_evento(cfg, t0):
    db = BaseDatos(cfg.base_datos)
    db.preparar(cfg)
    _evento(db, t0)
    db.guardar_ciclo(ciclo(t0 + timedelta(minutes=1)), Metricas(t0 + timedelta(minutes=1)),
                     Nivel.NORMAL)
    db.purgar(t0 + timedelta(days=1))
    assert db.cx.execute("SELECT COUNT(*) FROM metrica_derivada").fetchone()[0] == 1
    assert db.cx.execute("SELECT COUNT(*) FROM lectura").fetchone()[0] == 0
