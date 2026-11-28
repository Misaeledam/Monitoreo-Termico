"""Controles de seguridad del panel: bloqueo por intentos fallidos y cabeceras."""

import base64

from werkzeug.security import generate_password_hash

from monitoreo.panel import CABECERAS_SEGURIDAD, ControlIntentos, crear_app


def _auth(usuario, clave):
    return {"Authorization": "Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()}


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_bloquea_tras_5_fallos_y_libera_despues(cfg, monkeypatch):
    monkeypatch.setenv("MONITOREO_PANEL_HASH", generate_password_hash("correcta"))
    reloj = Reloj()
    cliente = crear_app(cfg, intentos=ControlIntentos(reloj=reloj)).test_client()
    for _ in range(4):
        assert cliente.get("/configuracion", headers=_auth("admin", "mala")).status_code == 401
    assert cliente.get("/configuracion", headers=_auth("admin", "mala")).status_code == 429
    # Bloqueada: ni siquiera la clave correcta entra.
    assert cliente.get("/configuracion", headers=_auth("admin", "correcta")).status_code == 429
    reloj.t += 901
    assert cliente.get("/configuracion", headers=_auth("admin", "correcta")).status_code == 200


def test_pedido_sin_credenciales_no_cuenta_como_fallo(cfg, monkeypatch):
    monkeypatch.setenv("MONITOREO_PANEL_HASH", generate_password_hash("correcta"))
    cliente = crear_app(cfg).test_client()
    for _ in range(10):
        assert cliente.get("/configuracion").status_code == 401
    assert cliente.get("/configuracion", headers=_auth("admin", "correcta")).status_code == 200


def test_cabeceras_de_seguridad(cfg):
    r = crear_app(cfg).test_client().get("/configuracion")
    for nombre, valor in CABECERAS_SEGURIDAD.items():
        assert r.headers[nombre] == valor


def test_hsts_solo_con_https(cfg):
    cliente = crear_app(cfg).test_client()
    assert "Strict-Transport-Security" not in cliente.get("/configuracion").headers
    r = cliente.get("/configuracion", base_url="https://localhost")
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_fallo_queda_registrado(cfg, monkeypatch, caplog):
    monkeypatch.setenv("MONITOREO_PANEL_HASH", generate_password_hash("correcta"))
    cliente = crear_app(cfg).test_client()
    with caplog.at_level("WARNING", logger="monitoreo.panel"):
        cliente.get("/configuracion", headers=_auth("intruso", "x"))
    assert "Acceso fallido" in caplog.text and "intruso" in caplog.text
