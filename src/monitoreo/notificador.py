"""Notificador con cola persistente (RF-09, RF-12, RF-15).

Cada evento genera una notificación PENDIENTE por destinatario y canal. Un envío que falla
(por ejemplo, sin conectividad) queda pendiente y se reintenta; pasado el plazo
configurado se marca DESCARTADA (diagrama de estados de la notificación, Figura D10).
El sistema notifica, no actúa (RN-11).
"""

from __future__ import annotations

import smtplib
import ssl
import subprocess
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

import requests

from .config import Config, Destinatario
from .modelos import Ciclo, Evaluacion, Metricas, Nivel
from .persistencia import BaseDatos

UNIDADES = {
    "temperatura_entrada": "°C",
    "humedad_relativa": "%",
    "punto_rocio": "°C",
    "margen_condensacion": "°C",
    "tasa_t_15min": "°C en 15 min",
    "tasa_t_1h": "°C en 1 h",
    "delta_t": "°C",
}

URL_TELEGRAM = "https://api.telegram.org/bot{token}/sendMessage"
MAX_TELEGRAM = 4096  # largo máximo de un mensaje según la Bot API


class ErrorEnvio(Exception):
    pass


class Canal(Protocol):
    def enviar(self, contacto: str | None, mensaje: str, destinatario: Destinatario | None) -> None:
        ...


class CanalCorreo:
    def __init__(self, cfg: Config):
        self.c = cfg.notificaciones.correo

    def enviar(self, contacto, mensaje, destinatario) -> None:
        if not contacto:
            raise ErrorEnvio("Destinatario de correo sin dirección")
        msg = EmailMessage()
        msg["Subject"] = mensaje.splitlines()[0]
        msg["From"] = self.c.remitente or self.c.usuario
        msg["To"] = contacto
        msg.set_content(mensaje)
        try:
            with smtplib.SMTP(self.c.servidor, self.c.puerto, timeout=20) as smtp:
                if self.c.starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if self.c.usuario:
                    smtp.login(self.c.usuario, Config.secreto(self.c.contrasena_env))
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise ErrorEnvio(f"correo: {exc}") from exc


class CanalTelegram:
    """Bot API oficial de Telegram (https://core.telegram.org/bots/api), sin costo.

    El bot se crea con @BotFather, que entrega el token. Un bot no puede iniciar una
    conversación: cada destinatario le escribe primero (/start) y su ``chat_id`` es el
    contacto que va en la configuración.
    """

    def __init__(self, cfg: Config, sesion: requests.Session | None = None):
        self.token_env = cfg.notificaciones.telegram_token_env
        self.sesion = sesion or requests.Session()

    def enviar(self, contacto, mensaje, destinatario) -> None:
        token = Config.secreto(self.token_env)
        if not contacto or not token:
            raise ErrorEnvio("Telegram: falta el chat_id o el token del bot")
        try:
            r = self.sesion.post(URL_TELEGRAM.format(token=token),
                                 json={"chat_id": contacto, "text": mensaje[:MAX_TELEGRAM]},
                                 timeout=30)
        except requests.RequestException as exc:
            # El mensaje de error no incluye la URL para no dejar el token en los registros.
            raise ErrorEnvio(f"Telegram: {type(exc).__name__}") from None
        try:
            ok = r.json().get("ok", False)
        except ValueError:
            ok = False
        if r.status_code != 200 or not ok:
            raise ErrorEnvio(f"Telegram: HTTP {r.status_code}")


class CanalSnmpTrap:
    """Notificación asíncrona SNMPv3 hacia el NMS (RF-12), con la herramienta snmptrap."""

    def __init__(self, cfg: Config, ejecutar=subprocess.run):
        self.t = cfg.notificaciones.snmp_trap
        self.base = cfg.snmp.oid_base
        self.ejecutar = ejecutar

    def comando(self, nivel: int, texto: str) -> list[str]:
        t = self.t
        cmd = ["snmptrap", "-v", "3", "-u", t.usuario, "-l", t.nivel_seguridad]
        if t.engine_id:
            cmd += ["-e", t.engine_id]
        if t.nivel_seguridad in ("authNoPriv", "authPriv"):
            cmd += ["-a", t.auth_protocolo, "-A", Config.secreto(t.auth_clave_env)]
        if t.nivel_seguridad == "authPriv":
            cmd += ["-x", t.priv_protocolo, "-X", Config.secreto(t.priv_clave_env)]
        cmd += [t.destino, "", f"{self.base}.0.1",
                f"{self.base}.12.0", "i", str(nivel),
                f"{self.base}.13.0", "s", texto[:255]]
        return cmd

    def enviar(self, contacto, mensaje, destinatario) -> None:
        nivel_txt = mensaje.split("|", 1)
        try:
            nivel = int(nivel_txt[0])
        except ValueError:
            nivel = 0
        texto = nivel_txt[1] if len(nivel_txt) > 1 else mensaje
        try:
            self.ejecutar(self.comando(nivel, texto), check=True, timeout=20,
                          capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ErrorEnvio(f"snmptrap: {exc}") from exc


def _fmt(valor: float | None, unidad: str) -> str:
    return "sin dato" if valor is None else f"{valor:.2f} {unidad}"


def redactar(cfg: Config, ev: Evaluacion, ciclo: Ciclo, met: Metricas) -> str:
    local = ciclo.marca_temporal.astimezone()
    lineas = [
        f"[Monitoreo térmico] {ev.nivel.etiqueta.upper()} (antes: {ev.nivel_anterior.etiqueta})",
        f"Bastidor: {cfg.bastidor}",
        f"Fecha: {local:%d/%m/%Y %H:%M}",
        f"Motivo: {ev.motivo_notificacion}",
    ]
    if ev.disparos:
        lineas.append("Origen:")
        for d in ev.disparos:
            if d.metrica == "agua":
                lineas.append("- Presencia de agua en la base del bastidor")
                continue
            unidad = UNIDADES.get(d.metrica, "")
            limite = "" if d.limite is None else f" (límite {d.limite:g} {unidad})"
            valor = "" if d.valor is None else f": {_fmt(d.valor, unidad)}"
            lineas.append(f"- {d.descripcion}{valor}{limite} [{d.nivel.etiqueta}, {d.criterio}]")
    else:
        lineas.append("Todas las métricas volvieron a valores normales.")
    e, s = ciclo.entrada, ciclo.salida
    lineas.append(f"Entrada: {_fmt(e.temperatura, '°C')} / {_fmt(e.humedad_relativa, '%')}")
    lineas.append(f"Salida: {_fmt(s.temperatura, '°C')} / {_fmt(s.humedad_relativa, '%')}")
    lineas.append(f"ΔT: {_fmt(met.delta_t, '°C')}")
    return "\n".join(lineas)


class Notificador:
    def __init__(self, cfg: Config, db: BaseDatos, canales: dict[str, Canal] | None = None):
        self.cfg = cfg
        self.db = db
        self.canales = canales if canales is not None else self._canales_por_defecto(cfg)
        self._proximo_intento: dict[int, datetime] = {}

    @staticmethod
    def _canales_por_defecto(cfg: Config) -> dict[str, Canal]:
        canales: dict[str, Canal] = {}
        if cfg.notificaciones.correo.habilitado:
            canales["correo"] = CanalCorreo(cfg)
        if cfg.notificaciones.telegram_habilitado:
            canales["telegram"] = CanalTelegram(cfg)
        if cfg.notificaciones.snmp_trap.habilitado:
            canales["snmp"] = CanalSnmpTrap(cfg)
        return canales

    def actualizar_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self.canales = self._canales_por_defecto(cfg)

    def encolar(self, id_evento: int, ev: Evaluacion, ciclo: Ciclo, met: Metricas) -> int:
        mensaje = redactar(self.cfg, ev, ciclo, met)
        n = 0
        for d in self.cfg.notificaciones.destinatarios:
            if d.activo and d.canal in self.canales:
                self.db.encolar_notificacion(id_evento, d.canal, mensaje, ciclo.marca_temporal,
                                             self.db.id_destinatario(d.canal, d.contacto))
                n += 1
        if "snmp" in self.canales:
            resumen = "; ".join(x.descripcion for x in ev.disparos) or "Normal"
            self.db.encolar_notificacion(id_evento, "snmp",
                                         f"{int(ev.nivel)}|{ev.nivel.etiqueta}: {resumen}",
                                         ciclo.marca_temporal)
            n += 1
        return n

    def procesar(self, ahora: datetime) -> tuple[int, int]:
        """Intenta enviar lo pendiente. Devuelve (enviadas, fallidas)."""
        plazo = timedelta(hours=self.cfg.notificaciones.descartar_tras_h)
        self.db.descartar_vencidas(ahora - plazo)
        enviadas = fallidas = 0
        por_contacto = {(d.canal, d.contacto): d for d in self.cfg.notificaciones.destinatarios}
        for fila in self.db.pendientes():
            idn = fila["id_notificacion"]
            if self._proximo_intento.get(idn, ahora) > ahora:
                continue
            canal = self.canales.get(fila["canal"])
            if canal is None:
                continue  # canal deshabilitado: queda pendiente hasta vencer
            destinatario = por_contacto.get((fila["canal"], fila["contacto"]))
            try:
                canal.enviar(fila["contacto"], fila["mensaje"], destinatario)
            except ErrorEnvio as exc:
                self.db.marcar_fallo(idn, str(exc))
                self._proximo_intento[idn] = ahora + timedelta(
                    seconds=self.cfg.notificaciones.reintento_s)
                fallidas += 1
                continue
            self.db.marcar_enviada(idn, ahora)
            self._proximo_intento.pop(idn, None)
            enviadas += 1
        return enviadas, fallidas


__all__ = ["Notificador", "CanalCorreo", "CanalTelegram", "CanalSnmpTrap", "ErrorEnvio",
           "redactar", "Nivel"]
