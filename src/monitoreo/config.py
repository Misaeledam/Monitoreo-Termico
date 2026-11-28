"""Configuración externa al código (RF-14, RNF-11).

Los parámetros viven en un archivo TOML. Los valores por defecto corresponden a las
reglas de negocio RN-01 a RN-07; los que la tesis deja para calibrar contra la línea
base (RN-07, RN-10) están marcados como provisionales en ``config/config.ejemplo.toml``.
Las contraseñas y claves nunca van en el archivo: se leen de variables de entorno.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .modelos import Nivel

NIVELES_TEXTO = {"aviso": Nivel.AVISO, "advertencia": Nivel.ADVERTENCIA, "critico": Nivel.CRITICO}

# Umbrales por defecto. Clave: "<nivel>_<alto|bajo>".
UMBRALES_POR_DEFECTO: dict[str, dict[str, float]] = {
    # RN-01 (18-27 °C recomendado), RN-02 (32 °C límite permitido A1),
    # RN-03 (aviso en 24 °C; crítico por debajo de 2 °C).
    "temperatura_entrada": {
        "aviso_alto": 24.0,
        "advertencia_alto": 27.0,
        "advertencia_bajo": 18.0,
        "critico_alto": 32.0,
        "critico_bajo": 2.0,
        "histeresis": 1.0,
    },
    # RN-05: recomendado hasta 60 % HR; permitido 8 % a 80 % HR.
    "humedad_relativa": {
        "aviso_alto": 60.0,
        "advertencia_alto": 80.0,
        "advertencia_bajo": 8.0,
        "histeresis": 3.0,
    },
    # RN-04: recomendado hasta 15 °C; máximo permitido A1 17 °C.
    "punto_rocio": {"aviso_alto": 15.0, "advertencia_alto": 17.0, "histeresis": 0.5},
    # RN-04 (margen de condensación). Provisional: calibrar con la línea base.
    "margen_condensacion": {
        "aviso_bajo": 5.0,
        "advertencia_bajo": 3.0,
        "critico_bajo": 1.0,
        "histeresis": 0.5,
    },
    # RN-06: no más de 5 °C en cualquier período de 15 minutos. Crítico: provisional.
    "tasa_t_15min": {"advertencia_alto": 5.0, "critico_alto": 10.0, "histeresis": 0.5},
    # RN-06: 20 °C por hora.
    "tasa_t_1h": {"advertencia_alto": 20.0, "histeresis": 1.0},
    # RN-07: la tesis fija la referencia con la línea base. Valores provisionales.
    "delta_t": {"advertencia_alto": 20.0, "aviso_bajo": 1.0, "histeresis": 0.5},
}


@dataclass(slots=True)
class Limite:
    nivel: Nivel
    alto: bool  # True: se dispara por encima; False: por debajo
    valor: float


@dataclass(slots=True)
class UmbralMetrica:
    metrica: str
    limites: list[Limite]
    histeresis: float = 0.0

    @classmethod
    def desde_dict(cls, metrica: str, datos: dict[str, Any]) -> UmbralMetrica:
        limites: list[Limite] = []
        histeresis = float(datos.get("histeresis", 0.0))
        for clave, valor in datos.items():
            if clave == "histeresis":
                continue
            try:
                nivel_txt, sentido = clave.rsplit("_", 1)
                nivel = NIVELES_TEXTO[nivel_txt]
            except (ValueError, KeyError) as exc:
                raise ValueError(f"Umbral desconocido '{clave}' en '{metrica}'") from exc
            if sentido not in ("alto", "bajo"):
                raise ValueError(f"Sentido inválido en '{metrica}.{clave}'")
            limites.append(Limite(nivel=nivel, alto=sentido == "alto", valor=float(valor)))
        if histeresis < 0:
            raise ValueError(f"La histéresis de '{metrica}' no puede ser negativa")
        return cls(metrica=metrica, limites=limites, histeresis=histeresis)


@dataclass(slots=True)
class SondaI2C:
    bus: int = 1
    direccion: int = 0x44


@dataclass(slots=True)
class ConfigSondas:
    modo: str = "real"  # "real" | "simulado"
    escenario: str = "normal"
    entrada: SondaI2C = field(default_factory=lambda: SondaI2C(bus=1, direccion=0x44))
    salida: SondaI2C = field(default_factory=lambda: SondaI2C(bus=4, direccion=0x44))
    gpio_agua: int = 17


@dataclass(slots=True)
class CanalCorreo:
    habilitado: bool = False
    servidor: str = ""
    puerto: int = 587
    usuario: str = ""
    contrasena_env: str = "MONITOREO_SMTP_PASS"
    remitente: str = ""
    starttls: bool = True


@dataclass(slots=True)
class CanalSnmpTrap:
    habilitado: bool = False
    destino: str = ""
    usuario: str = ""
    engine_id: str = ""  # opcional; el receptor (snmptrapd) debe conocerlo para SNMPv3
    nivel_seguridad: str = "authPriv"
    auth_protocolo: str = "SHA"
    auth_clave_env: str = "MONITOREO_SNMP_AUTH"
    priv_protocolo: str = "AES"
    priv_clave_env: str = "MONITOREO_SNMP_PRIV"


@dataclass(slots=True)
class Destinatario:
    nombre: str
    canal: str  # "correo" | "telegram"
    contacto: str
    activo: bool = True


@dataclass(slots=True)
class ConfigNotificaciones:
    tiempo_minimo_min: float = 10.0
    reintento_s: int = 60
    descartar_tras_h: float = 24.0
    telegram_habilitado: bool = False
    telegram_token_env: str = "MONITOREO_TELEGRAM_TOKEN"
    correo: CanalCorreo = field(default_factory=CanalCorreo)
    snmp_trap: CanalSnmpTrap = field(default_factory=CanalSnmpTrap)
    destinatarios: list[Destinatario] = field(default_factory=list)


@dataclass(slots=True)
class ConfigPanel:
    host: str = "0.0.0.0"
    puerto: int = 8443
    usuario: str = "admin"
    contrasena_hash_env: str = "MONITOREO_PANEL_HASH"
    certificado: str = ""
    clave_privada: str = ""


@dataclass(slots=True)
class ConfigSnmp:
    oid_base: str = ".1.3.6.1.4.1.8072.9999.9999.1"
    max_antiguedad_s: int = 180


@dataclass(slots=True)
class Config:
    bastidor: str = "Bastidor instrumentado"
    intervalo_muestreo_s: float = 60.0
    base_datos: str = "monitoreo.db"
    retencion_dias: int = 365
    temperatura_referencia: float | None = None  # None: usa la temperatura de entrada
    ventana_min: float = 60.0
    sondas: ConfigSondas = field(default_factory=ConfigSondas)
    umbrales: dict[str, UmbralMetrica] = field(default_factory=dict)
    notificaciones: ConfigNotificaciones = field(default_factory=ConfigNotificaciones)
    panel: ConfigPanel = field(default_factory=ConfigPanel)
    snmp: ConfigSnmp = field(default_factory=ConfigSnmp)
    origen: Path | None = None

    @staticmethod
    def secreto(nombre_env: str) -> str:
        """Devuelve un secreto desde el entorno ("" si no está definido)."""
        return os.environ.get(nombre_env, "") if nombre_env else ""


def _umbrales(datos: dict[str, Any]) -> dict[str, UmbralMetrica]:
    combinados = {k: dict(v) for k, v in UMBRALES_POR_DEFECTO.items()}
    for metrica, valores in datos.items():
        if metrica not in combinados:
            raise ValueError(f"Métrica desconocida en [umbrales]: '{metrica}'")
        # Si el usuario define la métrica, su sección reemplaza la de fábrica.
        combinados[metrica] = dict(valores)
    return {m: UmbralMetrica.desde_dict(m, v) for m, v in combinados.items()}


def _sonda(datos: dict[str, Any], defecto: SondaI2C) -> SondaI2C:
    return SondaI2C(
        bus=int(datos.get("bus", defecto.bus)),
        direccion=int(datos.get("direccion", defecto.direccion)),
    )


def desde_dict(datos: dict[str, Any], origen: Path | None = None) -> Config:
    gen = datos.get("general", {})
    s = datos.get("sondas", {})
    base_sondas = ConfigSondas()
    sondas = ConfigSondas(
        modo=s.get("modo", base_sondas.modo),
        escenario=s.get("escenario", base_sondas.escenario),
        entrada=_sonda(s.get("entrada", {}), base_sondas.entrada),
        salida=_sonda(s.get("salida", {}), base_sondas.salida),
        gpio_agua=int(s.get("agua", {}).get("gpio", base_sondas.gpio_agua)),
    )
    if sondas.modo not in ("real", "simulado"):
        raise ValueError("[sondas].modo debe ser 'real' o 'simulado'")

    n = datos.get("notificaciones", {})
    notif = ConfigNotificaciones(
        tiempo_minimo_min=float(n.get("tiempo_minimo_min", 10.0)),
        reintento_s=int(n.get("reintento_s", 60)),
        descartar_tras_h=float(n.get("descartar_tras_h", 24.0)),
        telegram_habilitado=bool(n.get("telegram", {}).get("habilitado", False)),
        telegram_token_env=n.get("telegram", {}).get("token_env", "MONITOREO_TELEGRAM_TOKEN"),
        correo=CanalCorreo(**n.get("correo", {})),
        snmp_trap=CanalSnmpTrap(**n.get("snmp_trap", {})),
        destinatarios=[Destinatario(**d) for d in datos.get("destinatarios", [])],
    )
    for d in notif.destinatarios:
        if d.canal not in ("correo", "telegram"):
            raise ValueError(f"Canal inválido para '{d.nombre}': {d.canal}")

    t_ref = gen.get("temperatura_referencia")
    cfg = Config(
        bastidor=gen.get("bastidor", "Bastidor instrumentado"),
        intervalo_muestreo_s=float(gen.get("intervalo_muestreo_s", 60.0)),
        base_datos=gen.get("base_datos", "monitoreo.db"),
        retencion_dias=int(gen.get("retencion_dias", 365)),
        temperatura_referencia=None if t_ref in (None, "entrada") else float(t_ref),
        ventana_min=float(gen.get("ventana_min", 60.0)),
        sondas=sondas,
        umbrales=_umbrales(datos.get("umbrales", {})),
        notificaciones=notif,
        panel=ConfigPanel(**datos.get("panel", {})),
        snmp=ConfigSnmp(**datos.get("snmp", {})),
        origen=origen,
    )
    if cfg.intervalo_muestreo_s <= 0:
        raise ValueError("El intervalo de muestreo debe ser positivo")
    if cfg.ventana_min < 15:
        raise ValueError("La ventana debe cubrir al menos 15 minutos (RN-06)")
    return cfg


def cargar(ruta: str | Path) -> Config:
    ruta = Path(ruta)
    with ruta.open("rb") as f:
        return desde_dict(tomllib.load(f), origen=ruta)


class ConfigRecargable:
    """Recarga la configuración cuando cambia el archivo, sin reinstalar (RF-14)."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        self._mtime = self.ruta.stat().st_mtime
        self.actual = cargar(self.ruta)
        self.ultimo_error: str | None = None

    def recargar_si_cambio(self) -> bool:
        try:
            mtime = self.ruta.stat().st_mtime
        except FileNotFoundError:
            return False
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        try:
            self.actual = cargar(self.ruta)
        except (ValueError, tomllib.TOMLDecodeError, TypeError) as exc:
            # Un archivo mal editado no debe detener la supervisión: se conserva el anterior.
            self.ultimo_error = str(exc)
            return False
        self.ultimo_error = None
        return True
