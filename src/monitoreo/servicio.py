"""Ciclo principal de supervisión (CU-01 "Supervisar condiciones", Figura D5).

leer sondas → validar → calcular métricas → clasificar → persistir → notificar.
La evaluación no depende de la red (RNF-02): si no hay conectividad, las notificaciones
quedan pendientes y se envían al volver el enlace (Figura D6).
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime, timedelta

from .adquisicion import Adquisidor, crear_adquisidor
from .analisis import MotorAnalisis, VentanaDeslizante
from .config import Config, ConfigRecargable
from .modelos import Evaluacion
from .notificador import Notificador
from .persistencia import BaseDatos
from .severidad import Clasificador

log = logging.getLogger("monitoreo")


class Reloj:
    """Reloj real o acelerado (para recorrer escenarios simulados más rápido)."""

    def __init__(self, factor: float = 1.0):
        self.factor = factor
        self._t0_real = time.monotonic()
        self._t0 = datetime.now(UTC)

    def ahora(self) -> datetime:
        return self._t0 + timedelta(seconds=(time.monotonic() - self._t0_real) * self.factor)

    def dormir(self, segundos: float) -> None:
        time.sleep(max(0.0, segundos / self.factor))


def _limites_delta(cfg: Config) -> tuple[float, float]:
    alto, bajo = float("inf"), float("-inf")
    umbral = cfg.umbrales.get("delta_t")
    if umbral:
        altos = [lim.valor for lim in umbral.limites if lim.alto]
        bajos = [lim.valor for lim in umbral.limites if not lim.alto]
        alto = min(altos) if altos else alto
        bajo = max(bajos) if bajos else bajo
    return alto, bajo


class Monitor:
    def __init__(self, cfg: Config, db: BaseDatos | None = None,
                 adquisidor: Adquisidor | None = None, notificador: Notificador | None = None,
                 recargable: ConfigRecargable | None = None, inicio: datetime | None = None):
        self.cfg = cfg
        self.recargable = recargable
        self.db = db or BaseDatos(cfg.base_datos)
        self.db.preparar(cfg)
        self.adquisidor = adquisidor or crear_adquisidor(cfg, inicio=inicio)
        ventana = VentanaDeslizante(timedelta(minutes=cfg.ventana_min), cfg.intervalo_muestreo_s)
        ahora = inicio or datetime.now(UTC)
        ventana.reconstruir(self.db.muestras_entrada(ahora - timedelta(minutes=cfg.ventana_min)))
        alto, bajo = _limites_delta(cfg)
        self.analisis = MotorAnalisis(ventana, alto, bajo, cfg.temperatura_referencia)
        self.clasificador = Clasificador(
            cfg.umbrales, timedelta(minutes=cfg.notificaciones.tiempo_minimo_min),
            nivel_inicial=self.db.ultimo_nivel())
        self.notificador = notificador or Notificador(cfg, self.db)
        self._ultima_purga: datetime | None = None
        self._detener = False

    def _aplicar_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self.db.sincronizar_umbrales(cfg.umbrales)
        self.db.sincronizar_destinatarios(cfg.notificaciones.destinatarios)
        self.db.guardar_parametros(cfg)
        self.analisis.delta_alto, self.analisis.delta_bajo = _limites_delta(cfg)
        self.analisis.temperatura_referencia = cfg.temperatura_referencia
        self.clasificador.actualizar_umbrales(
            cfg.umbrales, timedelta(minutes=cfg.notificaciones.tiempo_minimo_min))
        self.notificador.actualizar_config(cfg)

    def ciclo(self, marca: datetime) -> Evaluacion:
        if self.recargable and self.recargable.recargar_si_cambio():
            log.info("Configuración recargada desde %s", self.recargable.ruta)
            self._aplicar_config(self.recargable.actual)
        lectura = self.adquisidor.leer_ciclo(marca)
        met = self.analisis.calcular(marca, lectura.entrada, lectura.salida)
        ev = self.clasificador.evaluar(lectura, met)
        id_metrica = self.db.guardar_ciclo(lectura, met, ev.nivel)
        if ev.notificar:
            id_evento = self.db.registrar_evento(marca, ev, id_metrica)
            self.notificador.encolar(id_evento, ev, lectura, met)
            log.warning("%s -> %s (%s): %s", ev.nivel_anterior.etiqueta, ev.nivel.etiqueta,
                        ev.motivo_notificacion,
                        "; ".join(d.descripcion for d in ev.disparos) or "normal")
        enviadas, fallidas = self.notificador.procesar(marca)
        if fallidas:
            log.info("Notificaciones: %d enviadas, %d pendientes con error", enviadas, fallidas)
        if self._ultima_purga is None or marca - self._ultima_purga > timedelta(days=1):
            self.db.purgar(marca - timedelta(days=self.cfg.retencion_dias))
            self._ultima_purga = marca
        return ev

    def detener(self, *_: object) -> None:
        self._detener = True

    def ejecutar(self, reloj: Reloj, ciclos: int | None = None) -> None:
        signal.signal(signal.SIGTERM, self.detener)
        signal.signal(signal.SIGINT, self.detener)
        n = 0
        try:
            while not self._detener and (ciclos is None or n < ciclos):
                inicio = reloj.ahora()
                try:
                    self.ciclo(inicio)
                except Exception:  # noqa: BLE001 - un ciclo fallido no debe detener el servicio
                    log.exception("Error en el ciclo de supervisión")
                n += 1
                transcurrido = (reloj.ahora() - inicio).total_seconds()
                reloj.dormir(self.cfg.intervalo_muestreo_s - transcurrido)
        finally:
            self.adquisidor.cerrar()
