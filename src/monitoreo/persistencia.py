"""Persistencia local en SQLite (RF-10, RF-15, RF-17, RNF-04, RNF-12).

El esquema sigue el diccionario de datos de la tesis (Tabla de diccionario de datos,
Figura D15). Todas las marcas temporales se guardan en UTC, formato ISO 8601.
El modo WAL permite que el panel y el agente SNMP lean mientras el monitor escribe, y
``synchronous=NORMAL`` reduce escrituras sin perder consistencia ante un corte.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from .analisis import Muestra
from .config import Config, Destinatario, UmbralMetrica
from .modelos import Ciclo, Evaluacion, Metricas, Nivel, Ubicacion

ESQUEMA = """
CREATE TABLE IF NOT EXISTS bastidor (
    id_bastidor INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    altura_u INTEGER,
    material TEXT,
    configuracion_puertas TEXT
);
CREATE TABLE IF NOT EXISTS sonda (
    id_sonda INTEGER PRIMARY KEY,
    id_bastidor INTEGER NOT NULL REFERENCES bastidor(id_bastidor),
    tipo TEXT NOT NULL CHECK (tipo IN ('AMBIENTAL', 'AGUA')),
    ubicacion TEXT NOT NULL CHECK (ubicacion IN ('ENTRADA', 'SALIDA', 'BASE')),
    direccion_bus TEXT,
    UNIQUE (id_bastidor, ubicacion)
);
CREATE TABLE IF NOT EXISTS lectura (
    id_lectura INTEGER PRIMARY KEY,
    id_sonda INTEGER NOT NULL REFERENCES sonda(id_sonda),
    marca_temporal TEXT NOT NULL,
    temperatura REAL,
    humedad_relativa REAL CHECK (humedad_relativa IS NULL OR humedad_relativa BETWEEN 0 AND 100),
    agua_detectada INTEGER,
    valida INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_lectura_sonda_marca ON lectura (id_sonda, marca_temporal);
CREATE TABLE IF NOT EXISTS metrica_derivada (
    id_metrica INTEGER PRIMARY KEY,
    marca_temporal TEXT NOT NULL,
    delta_t REAL,
    punto_rocio_entrada REAL,
    punto_rocio_salida REAL,
    margen_condensacion REAL,
    tasa_variacion_t_15min REAL,
    tasa_variacion_t_1h REAL,
    tasa_variacion_hr_1h REAL,
    condicion_flujo TEXT NOT NULL,
    nivel INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrica_marca ON metrica_derivada (marca_temporal);
CREATE TABLE IF NOT EXISTS umbral (
    id_umbral INTEGER PRIMARY KEY,
    metrica TEXT NOT NULL,
    nivel TEXT NOT NULL CHECK (nivel IN ('AVISO', 'ADVERTENCIA', 'CRITICO')),
    sentido TEXT NOT NULL CHECK (sentido IN ('ALTO', 'BAJO')),
    valor_limite REAL NOT NULL,
    histeresis REAL NOT NULL DEFAULT 0 CHECK (histeresis >= 0),
    vigente INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS evento (
    id_evento INTEGER PRIMARY KEY,
    marca_temporal TEXT NOT NULL,
    id_umbral INTEGER REFERENCES umbral(id_umbral),
    id_metrica INTEGER REFERENCES metrica_derivada(id_metrica),
    nivel_anterior TEXT NOT NULL,
    nivel_nuevo TEXT NOT NULL,
    criterio TEXT CHECK (criterio IS NULL OR criterio IN ('UMBRAL', 'TASA', 'AGUA')),
    metrica TEXT,
    valor_disparador REAL,
    descripcion TEXT,
    motivo TEXT
);
CREATE INDEX IF NOT EXISTS idx_evento_marca ON evento (marca_temporal);
CREATE TABLE IF NOT EXISTS destinatario (
    id_destinatario INTEGER PRIMARY KEY,
    nombre_rol TEXT NOT NULL,
    contacto TEXT NOT NULL,
    canal TEXT NOT NULL CHECK (canal IN ('correo', 'telegram')),
    activo INTEGER NOT NULL,
    UNIQUE (canal, contacto)
);
CREATE TABLE IF NOT EXISTS notificacion (
    id_notificacion INTEGER PRIMARY KEY,
    id_evento INTEGER NOT NULL REFERENCES evento(id_evento),
    id_destinatario INTEGER REFERENCES destinatario(id_destinatario),
    canal TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('PENDIENTE', 'ENVIADA', 'DESCARTADA')),
    creada TEXT NOT NULL,
    fecha_envio TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    mensaje TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notificacion_estado ON notificacion (estado);
CREATE TABLE IF NOT EXISTS parametro_configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT,
    unidad TEXT
);
"""


def iso(marca: datetime) -> str:
    if marca.tzinfo is None:
        marca = marca.replace(tzinfo=UTC)
    return marca.astimezone(UTC).isoformat(timespec="seconds")


def desde_iso(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


class BaseDatos:
    def __init__(self, ruta: str | Path, solo_lectura: bool = False):
        self.ruta = str(ruta)
        if solo_lectura:
            uri = f"file:{Path(self.ruta).resolve()}?mode=ro"
            self.cx = sqlite3.connect(uri, uri=True, timeout=10, check_same_thread=False)
        else:
            if self.ruta != ":memory:":
                Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
            self.cx = sqlite3.connect(self.ruta, timeout=10, check_same_thread=False)
            self.cx.execute("PRAGMA journal_mode=WAL")
            self.cx.execute("PRAGMA synchronous=NORMAL")
            self.cx.execute("PRAGMA foreign_keys=ON")
            self.cx.executescript(ESQUEMA)
        self.cx.row_factory = sqlite3.Row
        self._sondas: dict[str, int] = {}

    def cerrar(self) -> None:
        self.cx.close()

    # ------------------------------------------------------------------ inicialización
    def preparar(self, cfg: Config) -> None:
        """Registra bastidor, sondas, umbrales, destinatarios y parámetros vigentes."""
        with self.cx:
            self.cx.execute("INSERT OR IGNORE INTO bastidor (nombre) VALUES (?)", (cfg.bastidor,))
            id_b = self.cx.execute("SELECT id_bastidor FROM bastidor WHERE nombre = ?",
                                   (cfg.bastidor,)).fetchone()[0]
            sondas = [
                ("AMBIENTAL", Ubicacion.ENTRADA,
                 f"i2c-{cfg.sondas.entrada.bus}:0x{cfg.sondas.entrada.direccion:02x}"),
                ("AMBIENTAL", Ubicacion.SALIDA,
                 f"i2c-{cfg.sondas.salida.bus}:0x{cfg.sondas.salida.direccion:02x}"),
                ("AGUA", Ubicacion.BASE, f"GPIO{cfg.sondas.gpio_agua}"),
            ]
            for tipo, ubicacion, direccion in sondas:
                self.cx.execute(
                    "INSERT INTO sonda (id_bastidor, tipo, ubicacion, direccion_bus) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT (id_bastidor, ubicacion) "
                    "DO UPDATE SET direccion_bus = excluded.direccion_bus",
                    (id_b, tipo, ubicacion, direccion))
            for fila in self.cx.execute("SELECT id_sonda, ubicacion FROM sonda WHERE id_bastidor = ?",
                                        (id_b,)):
                self._sondas[fila[1]] = fila[0]
        self.sincronizar_umbrales(cfg.umbrales)
        self.sincronizar_destinatarios(cfg.notificaciones.destinatarios)
        self.guardar_parametros(cfg)

    def sincronizar_umbrales(self, umbrales: dict[str, UmbralMetrica]) -> None:
        nuevos = sorted(
            (m, lim.nivel.name, "ALTO" if lim.alto else "BAJO", lim.valor, u.histeresis)
            for m, u in umbrales.items() for lim in u.limites
        )
        actuales = sorted(tuple(r) for r in self.cx.execute(
            "SELECT metrica, nivel, sentido, valor_limite, histeresis FROM umbral WHERE vigente = 1"))
        if nuevos == actuales:
            return
        with self.cx:
            self.cx.execute("UPDATE umbral SET vigente = 0 WHERE vigente = 1")
            self.cx.executemany(
                "INSERT INTO umbral (metrica, nivel, sentido, valor_limite, histeresis) "
                "VALUES (?, ?, ?, ?, ?)", nuevos)

    def sincronizar_destinatarios(self, destinatarios: Iterable[Destinatario]) -> None:
        with self.cx:
            self.cx.execute("UPDATE destinatario SET activo = 0")
            for d in destinatarios:
                self.cx.execute(
                    "INSERT INTO destinatario (nombre_rol, contacto, canal, activo) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT (canal, contacto) DO UPDATE SET "
                    "nombre_rol = excluded.nombre_rol, activo = excluded.activo",
                    (d.nombre, d.contacto, d.canal, int(d.activo)))

    def guardar_parametros(self, cfg: Config) -> None:
        parametros = [
            ("intervalo_muestreo", str(cfg.intervalo_muestreo_s), "s"),
            ("ventana", str(cfg.ventana_min), "min"),
            ("tiempo_minimo_notificacion", str(cfg.notificaciones.tiempo_minimo_min), "min"),
            ("temperatura_referencia",
             "entrada" if cfg.temperatura_referencia is None else str(cfg.temperatura_referencia),
             "°C"),
            ("retencion", str(cfg.retencion_dias), "días"),
        ]
        with self.cx:
            self.cx.executemany(
                "INSERT INTO parametro_configuracion (clave, valor, unidad) VALUES (?, ?, ?) "
                "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor, unidad = excluded.unidad",
                parametros)

    # ---------------------------------------------------------------------- escritura
    def guardar_ciclo(self, ciclo: Ciclo, met: Metricas, nivel: Nivel) -> int:
        marca = iso(ciclo.marca_temporal)
        with self.cx:
            for lec in (ciclo.entrada, ciclo.salida):
                self.cx.execute(
                    "INSERT INTO lectura (id_sonda, marca_temporal, temperatura, humedad_relativa, "
                    "valida, error) VALUES (?, ?, ?, ?, ?, ?)",
                    (self._sondas[lec.ubicacion], marca, lec.temperatura, lec.humedad_relativa,
                     int(lec.valida), lec.error))
            self.cx.execute(
                "INSERT INTO lectura (id_sonda, marca_temporal, agua_detectada, valida, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (self._sondas[Ubicacion.BASE], marca,
                 None if ciclo.agua.detectada is None else int(ciclo.agua.detectada),
                 int(ciclo.agua.valida), ciclo.agua.error))
            cur = self.cx.execute(
                "INSERT INTO metrica_derivada (marca_temporal, delta_t, punto_rocio_entrada, "
                "punto_rocio_salida, margen_condensacion, tasa_variacion_t_15min, "
                "tasa_variacion_t_1h, tasa_variacion_hr_1h, condicion_flujo, nivel) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (marca, _r(met.delta_t), _r(met.punto_rocio_entrada), _r(met.punto_rocio_salida),
                 _r(met.margen_condensacion), _r(met.tasa_t_15min, 3), _r(met.tasa_t_1h, 3),
                 _r(met.tasa_hr_1h, 3), met.condicion_flujo, int(nivel)))
            return int(cur.lastrowid)

    def _id_umbral(self, metrica: str, nivel: Nivel, limite: float | None) -> int | None:
        if limite is None:
            return None
        fila = self.cx.execute(
            "SELECT id_umbral FROM umbral WHERE vigente = 1 AND metrica = ? AND nivel = ? "
            "AND valor_limite = ?", (metrica, nivel.name, limite)).fetchone()
        return fila[0] if fila else None

    def registrar_evento(self, marca: datetime, ev: Evaluacion, id_metrica: int) -> int:
        principal = ev.disparos[0] if ev.disparos else None
        with self.cx:
            cur = self.cx.execute(
                "INSERT INTO evento (marca_temporal, id_umbral, id_metrica, nivel_anterior, "
                "nivel_nuevo, criterio, metrica, valor_disparador, descripcion, motivo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (iso(marca),
                 self._id_umbral(principal.metrica, principal.nivel, principal.limite)
                 if principal else None,
                 id_metrica, ev.nivel_anterior.name, ev.nivel.name,
                 principal.criterio if principal else None,
                 principal.metrica if principal else None,
                 _r(principal.valor) if principal else None,
                 "; ".join(d.descripcion for d in ev.disparos) or "Condición normal",
                 ev.motivo_notificacion))
            return int(cur.lastrowid)

    def encolar_notificacion(self, id_evento: int, canal: str, mensaje: str, marca: datetime,
                             id_destinatario: int | None = None) -> int:
        with self.cx:
            cur = self.cx.execute(
                "INSERT INTO notificacion (id_evento, id_destinatario, canal, estado, creada, "
                "mensaje) VALUES (?, ?, ?, 'PENDIENTE', ?, ?)",
                (id_evento, id_destinatario, canal, iso(marca), mensaje))
            return int(cur.lastrowid)

    def id_destinatario(self, canal: str, contacto: str) -> int | None:
        fila = self.cx.execute("SELECT id_destinatario FROM destinatario WHERE canal = ? "
                               "AND contacto = ?", (canal, contacto)).fetchone()
        return fila[0] if fila else None

    def pendientes(self) -> list[sqlite3.Row]:
        return self.cx.execute(
            "SELECT n.*, d.contacto, d.nombre_rol FROM notificacion n "
            "LEFT JOIN destinatario d USING (id_destinatario) "
            "WHERE n.estado = 'PENDIENTE' ORDER BY n.id_notificacion").fetchall()

    def marcar_enviada(self, id_notificacion: int, marca: datetime) -> None:
        with self.cx:
            self.cx.execute("UPDATE notificacion SET estado = 'ENVIADA', fecha_envio = ?, "
                            "intentos = intentos + 1, ultimo_error = NULL "
                            "WHERE id_notificacion = ?", (iso(marca), id_notificacion))

    def marcar_fallo(self, id_notificacion: int, error: str) -> None:
        with self.cx:
            self.cx.execute("UPDATE notificacion SET intentos = intentos + 1, ultimo_error = ? "
                            "WHERE id_notificacion = ?", (error[:500], id_notificacion))

    def descartar_vencidas(self, antes_de: datetime) -> int:
        with self.cx:
            cur = self.cx.execute("UPDATE notificacion SET estado = 'DESCARTADA' "
                                  "WHERE estado = 'PENDIENTE' AND creada < ?", (iso(antes_de),))
            return cur.rowcount

    def purgar(self, antes_de: datetime) -> None:
        """Borra el histórico más viejo que la retención (RNF-12). Los eventos se conservan."""
        limite = iso(antes_de)
        with self.cx:
            self.cx.execute("DELETE FROM lectura WHERE marca_temporal < ?", (limite,))
            self.cx.execute(
                "DELETE FROM metrica_derivada WHERE marca_temporal < ? AND id_metrica NOT IN "
                "(SELECT id_metrica FROM evento WHERE id_metrica IS NOT NULL)", (limite,))

    # ------------------------------------------------------------------------ lectura
    def muestras_entrada(self, desde: datetime) -> list[Muestra]:
        filas = self.cx.execute(
            "SELECT l.marca_temporal, l.temperatura, l.humedad_relativa FROM lectura l "
            "JOIN sonda s USING (id_sonda) WHERE s.ubicacion = 'ENTRADA' AND l.valida = 1 "
            "AND l.marca_temporal >= ? ORDER BY l.marca_temporal", (iso(desde),)).fetchall()
        return [Muestra(desde_iso(f[0]), f[1], f[2]) for f in filas]

    def ultimo_nivel(self) -> Nivel:
        fila = self.cx.execute(
            "SELECT nivel FROM metrica_derivada ORDER BY id_metrica DESC LIMIT 1").fetchone()
        return Nivel(fila[0]) if fila else Nivel.NORMAL

    def ultimo_estado(self) -> dict[str, Any] | None:
        met = self.cx.execute(
            "SELECT * FROM metrica_derivada ORDER BY id_metrica DESC LIMIT 1").fetchone()
        if met is None:
            return None
        estado: dict[str, Any] = dict(met)
        for f in self.cx.execute(
            "SELECT s.ubicacion, l.temperatura, l.humedad_relativa, l.agua_detectada, l.valida, "
            "l.error FROM lectura l JOIN sonda s USING (id_sonda) WHERE l.marca_temporal = ?",
            (met["marca_temporal"],),
        ):
            clave = f["ubicacion"].lower()
            estado[clave] = {k: f[k] for k in ("temperatura", "humedad_relativa",
                                               "agua_detectada", "valida", "error")}
        return estado

    def serie(self, desde: datetime) -> list[dict[str, Any]]:
        filas = self.cx.execute(
            "SELECT m.marca_temporal, m.delta_t, m.nivel, m.punto_rocio_entrada, "
            "e.temperatura AS t_entrada, e.humedad_relativa AS hr_entrada, "
            "s.temperatura AS t_salida, s.humedad_relativa AS hr_salida "
            "FROM metrica_derivada m "
            "LEFT JOIN lectura e ON e.marca_temporal = m.marca_temporal "
            "  AND e.id_sonda = (SELECT id_sonda FROM sonda WHERE ubicacion = 'ENTRADA') "
            "LEFT JOIN lectura s ON s.marca_temporal = m.marca_temporal "
            "  AND s.id_sonda = (SELECT id_sonda FROM sonda WHERE ubicacion = 'SALIDA') "
            "WHERE m.marca_temporal >= ? ORDER BY m.marca_temporal", (iso(desde),)).fetchall()
        return [dict(f) for f in filas]

    def eventos(self, limite: int = 50) -> list[dict[str, Any]]:
        return [dict(f) for f in self.cx.execute(
            "SELECT * FROM evento ORDER BY id_evento DESC LIMIT ?", (limite,))]

    def notificaciones(self, limite: int = 50) -> list[dict[str, Any]]:
        return [dict(f) for f in self.cx.execute(
            "SELECT id_notificacion, id_evento, canal, estado, creada, fecha_envio, intentos, "
            "ultimo_error FROM notificacion ORDER BY id_notificacion DESC LIMIT ?", (limite,))]

    def exportar_csv(self, salida: IO[str], desde: datetime, hasta: datetime) -> int:
        """Exporta lecturas y métricas de un período en CSV (RF-17)."""
        escritor = csv.writer(salida)
        escritor.writerow(["marca_temporal_utc", "t_entrada", "hr_entrada", "t_salida",
                           "hr_salida", "agua", "delta_t", "punto_rocio_entrada",
                           "punto_rocio_salida", "margen_condensacion", "tasa_t_15min",
                           "tasa_t_1h", "condicion_flujo", "nivel"])
        n = 0
        for f in self._filas_export(desde, hasta):
            escritor.writerow(f)
            n += 1
        return n

    def _filas_export(self, desde: datetime, hasta: datetime) -> Iterator[tuple]:
        consulta = (
            "SELECT m.marca_temporal, e.temperatura, e.humedad_relativa, s.temperatura, "
            "s.humedad_relativa, a.agua_detectada, m.delta_t, m.punto_rocio_entrada, "
            "m.punto_rocio_salida, m.margen_condensacion, m.tasa_variacion_t_15min, "
            "m.tasa_variacion_t_1h, m.condicion_flujo, m.nivel FROM metrica_derivada m "
            "LEFT JOIN lectura e ON e.marca_temporal = m.marca_temporal "
            "  AND e.id_sonda = (SELECT id_sonda FROM sonda WHERE ubicacion = 'ENTRADA') "
            "LEFT JOIN lectura s ON s.marca_temporal = m.marca_temporal "
            "  AND s.id_sonda = (SELECT id_sonda FROM sonda WHERE ubicacion = 'SALIDA') "
            "LEFT JOIN lectura a ON a.marca_temporal = m.marca_temporal "
            "  AND a.id_sonda = (SELECT id_sonda FROM sonda WHERE ubicacion = 'BASE') "
            "WHERE m.marca_temporal BETWEEN ? AND ? ORDER BY m.marca_temporal")
        for fila in self.cx.execute(consulta, (iso(desde), iso(hasta))):
            yield tuple(fila[:-1]) + (Nivel(fila[-1]).etiqueta,)


def _r(valor: float | None, decimales: int = 2) -> float | None:
    return None if valor is None else round(valor, decimales)

