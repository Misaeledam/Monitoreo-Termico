"""Tipos de datos compartidos entre los módulos (modelo de dominio, Figura D11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class Nivel(IntEnum):
    """Niveles de severidad (RF-07). El orden numérico permite tomar el máximo."""

    NORMAL = 0
    AVISO = 1
    ADVERTENCIA = 2
    CRITICO = 3

    @property
    def etiqueta(self) -> str:
        return {0: "Normal", 1: "Aviso", 2: "Advertencia", 3: "Crítico"}[int(self)]


class Ubicacion:
    ENTRADA = "ENTRADA"
    SALIDA = "SALIDA"
    BASE = "BASE"


class Criterio:
    UMBRAL = "UMBRAL"
    TASA = "TASA"
    AGUA = "AGUA"


class CondicionFlujo:
    NORMAL = "NORMAL"
    RESTRINGIDO = "RESTRINGIDO"
    DERIVACION = "DERIVACION"
    NO_DISPONIBLE = "NO_DISPONIBLE"


@dataclass(slots=True)
class LecturaAmbiental:
    """Lectura de una sonda SHT31 (RF-01). ``valida`` refleja la validación de RF-02."""

    ubicacion: str
    temperatura: float | None
    humedad_relativa: float | None
    valida: bool
    error: str | None = None


@dataclass(slots=True)
class LecturaAgua:
    detectada: bool | None
    valida: bool
    error: str | None = None


@dataclass(slots=True)
class Ciclo:
    """Todo lo leído en un ciclo de muestreo."""

    marca_temporal: datetime
    entrada: LecturaAmbiental
    salida: LecturaAmbiental
    agua: LecturaAgua


@dataclass(slots=True)
class Metricas:
    """Métricas derivadas de un ciclo (RF-03 a RF-05)."""

    marca_temporal: datetime
    delta_t: float | None = None
    punto_rocio_entrada: float | None = None
    punto_rocio_salida: float | None = None
    margen_condensacion: float | None = None
    tasa_t_15min: float | None = None
    tasa_t_1h: float | None = None
    tasa_hr_1h: float | None = None
    condicion_flujo: str = CondicionFlujo.NO_DISPONIBLE


@dataclass(slots=True)
class Disparo:
    """Una métrica que llevó a un nivel distinto de Normal."""

    metrica: str
    nivel: Nivel
    criterio: str
    valor: float | None
    limite: float | None
    descripcion: str


@dataclass(slots=True)
class Evaluacion:
    """Resultado del clasificador para un ciclo."""

    nivel: Nivel
    disparos: list[Disparo] = field(default_factory=list)
    cambio: bool = False
    nivel_anterior: Nivel = Nivel.NORMAL
    notificar: bool = False
    motivo_notificacion: str = ""
