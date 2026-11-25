"""Clasificador de severidad con histéresis (RF-07, RF-08, RN-08, RN-09)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import UmbralMetrica
from .modelos import Ciclo, Criterio, Disparo, Evaluacion, Metricas, Nivel

# Métricas cuyo criterio es la velocidad de cambio y no el valor absoluto (HU-04).
METRICAS_TASA = {"tasa_t_15min", "tasa_t_1h"}

# Ciclos seguidos sin lectura válida antes de avisar que una sonda no responde.
CICLOS_FALLA_SONDA = 3

DESCRIPCIONES = {
    "temperatura_entrada": "Temperatura de entrada",
    "humedad_relativa": "Humedad relativa",
    "punto_rocio": "Punto de rocío",
    "margen_condensacion": "Margen de condensación",
    "tasa_t_15min": "Variación de temperatura en 15 min",
    "tasa_t_1h": "Variación de temperatura en 1 h",
    "delta_t": "Diferencial térmico (ΔT)",
    "agua": "Presencia de agua",
    "sonda": "Sonda sin lectura",
}


def nivel_bruto(umbral: UmbralMetrica, valor: float, corrimiento: float = 0.0) -> tuple[Nivel, float | None]:
    """Nivel más alto cuyo límite se supera. ``corrimiento`` desplaza los límites hacia el
    lado seguro (se usa para la histéresis)."""
    mejor, limite_usado = Nivel.NORMAL, None
    for lim in umbral.limites:
        superado = valor > lim.valor - corrimiento if lim.alto else valor < lim.valor + corrimiento
        if superado and lim.nivel > mejor:
            mejor, limite_usado = lim.nivel, lim.valor
    return mejor, limite_usado


@dataclass(slots=True)
class _EstadoMetrica:
    nivel: Nivel = Nivel.NORMAL


class Clasificador:
    def __init__(self, umbrales: dict[str, UmbralMetrica], tiempo_minimo: timedelta,
                 nivel_inicial: Nivel = Nivel.NORMAL):
        self.umbrales = umbrales
        self.tiempo_minimo = tiempo_minimo
        self.nivel_actual = nivel_inicial
        self._por_metrica: dict[str, _EstadoMetrica] = {}
        self._ultima_notificacion: datetime | None = None
        self._agua_previa = False
        self._fallas_sonda = {"ENTRADA": 0, "SALIDA": 0}

    def actualizar_umbrales(self, umbrales: dict[str, UmbralMetrica], tiempo_minimo: timedelta) -> None:
        self.umbrales = umbrales
        self.tiempo_minimo = tiempo_minimo

    @staticmethod
    def valores(ciclo: Ciclo, met: Metricas) -> dict[str, float | None]:
        entrada = ciclo.entrada
        rocios = [r for r in (met.punto_rocio_entrada, met.punto_rocio_salida) if r is not None]
        humedades = [lec.humedad_relativa for lec in (ciclo.entrada, ciclo.salida)
                     if lec.valida and lec.humedad_relativa is not None]
        return {
            "temperatura_entrada": entrada.temperatura if entrada.valida else None,
            "humedad_relativa": max(humedades) if humedades else None,
            "punto_rocio": max(rocios) if rocios else None,
            "margen_condensacion": met.margen_condensacion,
            "tasa_t_15min": met.tasa_t_15min,
            "tasa_t_1h": met.tasa_t_1h,
            "delta_t": met.delta_t,
        }

    def _evaluar_metrica(self, metrica: str, valor: float | None) -> Disparo | None:
        umbral = self.umbrales.get(metrica)
        estado = self._por_metrica.setdefault(metrica, _EstadoMetrica())
        if umbral is None:
            return None
        if valor is None:
            # Sin dato no se baja ni se sube el nivel de esa métrica.
            nivel, limite = estado.nivel, None
        else:
            bruto, limite = nivel_bruto(umbral, valor)
            if bruto >= estado.nivel:
                nivel = bruto
            else:
                # Para bajar, el valor debe atravesar el margen de histéresis (RN-09).
                con_h, lim_h = nivel_bruto(umbral, valor, corrimiento=umbral.histeresis)
                nivel = min(estado.nivel, con_h)
                if nivel > bruto:
                    limite = lim_h
            estado.nivel = nivel
        if nivel == Nivel.NORMAL:
            return None
        criterio = Criterio.TASA if metrica in METRICAS_TASA else Criterio.UMBRAL
        return Disparo(metrica=metrica, nivel=nivel, criterio=criterio, valor=valor,
                       limite=limite, descripcion=DESCRIPCIONES.get(metrica, metrica))

    def evaluar(self, ciclo: Ciclo, met: Metricas) -> Evaluacion:
        disparos: list[Disparo] = []
        for metrica, valor in self.valores(ciclo, met).items():
            d = self._evaluar_metrica(metrica, valor)
            if d:
                disparos.append(d)

        for lectura in (ciclo.entrada, ciclo.salida):
            cuenta = 0 if lectura.valida else self._fallas_sonda[lectura.ubicacion] + 1
            self._fallas_sonda[lectura.ubicacion] = cuenta
            if cuenta >= CICLOS_FALLA_SONDA:
                disparos.append(Disparo(
                    metrica="sonda", nivel=Nivel.AVISO, criterio=Criterio.UMBRAL, valor=None,
                    limite=None, descripcion=f"Sonda de {lectura.ubicacion.lower()} sin lectura "
                    f"válida ({lectura.error or 'sin detalle'})"))

        agua = bool(ciclo.agua.valida and ciclo.agua.detectada)
        if agua:
            # RN-08: crítico inmediato, sin histéresis ni tiempo mínimo.
            disparos.append(Disparo(metrica="agua", nivel=Nivel.CRITICO, criterio=Criterio.AGUA,
                                    valor=1.0, limite=None, descripcion="Presencia de agua"))

        nivel = max((d.nivel for d in disparos), default=Nivel.NORMAL)
        ev = Evaluacion(nivel=nivel, disparos=sorted(disparos, key=lambda d: -d.nivel),
                        nivel_anterior=self.nivel_actual, cambio=nivel != self.nivel_actual)
        ahora = ciclo.marca_temporal
        if ev.cambio:
            ev.notificar = True
            ev.motivo_notificacion = "normalización" if nivel == Nivel.NORMAL else "cambio de nivel"
        elif agua and not self._agua_previa:
            ev.notificar, ev.motivo_notificacion = True, "detección de agua"
        elif nivel > Nivel.NORMAL and (
            self._ultima_notificacion is None
            or ahora - self._ultima_notificacion >= self.tiempo_minimo
        ):
            ev.notificar, ev.motivo_notificacion = True, "condición persistente"

        if ev.notificar:
            self._ultima_notificacion = ahora
        self._agua_previa = agua
        self.nivel_actual = nivel
        return ev
