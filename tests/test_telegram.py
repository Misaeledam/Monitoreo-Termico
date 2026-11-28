"""Canal de notificación por Telegram (RF-09), sin red: la sesión HTTP es simulada."""

import pytest
import requests

from monitoreo.config import desde_dict
from monitoreo.notificador import MAX_TELEGRAM, CanalTelegram, ErrorEnvio, Notificador


class Respuesta:
    def __init__(self, status=200, cuerpo=None):
        self.status_code = status
        self._cuerpo = {"ok": True} if cuerpo is None else cuerpo

    def json(self):
        return self._cuerpo


class SesionFalsa:
    def __init__(self, respuesta=None, error=None):
        self.respuesta = respuesta or Respuesta()
        self.error = error
        self.llamadas = []

    def post(self, url, json, timeout):
        self.llamadas.append((url, json))
        if self.error:
            raise self.error
        return self.respuesta


@pytest.fixture
def cfg_tg(tmp_path):
    return desde_dict({
        "general": {"base_datos": str(tmp_path / "t.db")},
        "notificaciones": {"telegram": {"habilitado": True}},
        "destinatarios": [{"nombre": "Guardia", "canal": "telegram", "contacto": "123456"}],
    })


def test_envia_al_chat_id_con_el_token(cfg_tg, monkeypatch):
    monkeypatch.setenv("MONITOREO_TELEGRAM_TOKEN", "TOKEN-DE-PRUEBA")
    sesion = SesionFalsa()
    CanalTelegram(cfg_tg, sesion).enviar("123456", "x" * (MAX_TELEGRAM + 50), None)
    url, cuerpo = sesion.llamadas[0]
    assert url == "https://api.telegram.org/botTOKEN-DE-PRUEBA/sendMessage"
    assert cuerpo["chat_id"] == "123456"
    assert len(cuerpo["text"]) == MAX_TELEGRAM


def test_sin_token_falla_sin_llamar(cfg_tg, monkeypatch):
    monkeypatch.delenv("MONITOREO_TELEGRAM_TOKEN", raising=False)
    sesion = SesionFalsa()
    with pytest.raises(ErrorEnvio, match="token"):
        CanalTelegram(cfg_tg, sesion).enviar("123456", "hola", None)
    assert not sesion.llamadas


def test_respuesta_no_ok_es_error(cfg_tg, monkeypatch):
    monkeypatch.setenv("MONITOREO_TELEGRAM_TOKEN", "T")
    sesion = SesionFalsa(Respuesta(400, {"ok": False, "description": "chat not found"}))
    with pytest.raises(ErrorEnvio, match="HTTP 400"):
        CanalTelegram(cfg_tg, sesion).enviar("1", "hola", None)


def test_error_de_red_no_expone_el_token(cfg_tg, monkeypatch):
    monkeypatch.setenv("MONITOREO_TELEGRAM_TOKEN", "SECRETO")
    error = requests.ConnectionError("https://api.telegram.org/botSECRETO/sendMessage caído")
    with pytest.raises(ErrorEnvio) as exc:
        CanalTelegram(cfg_tg, SesionFalsa(error=error)).enviar("1", "hola", None)
    assert "SECRETO" not in str(exc.value)


def test_notificador_registra_canal_telegram(cfg_tg):
    from monitoreo.persistencia import BaseDatos

    db = BaseDatos(cfg_tg.base_datos)
    db.preparar(cfg_tg)
    assert set(Notificador(cfg_tg, db).canales) == {"telegram"}


def test_canal_whatsapp_ya_no_es_valido(tmp_path):
    with pytest.raises(ValueError, match="Canal inválido"):
        desde_dict({"destinatarios": [{"nombre": "x", "canal": "whatsapp", "contacto": "1"}]})
