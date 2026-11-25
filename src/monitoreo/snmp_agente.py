"""Exposición de métricas por SNMP (RF-11, RNF-06) como extensión ``pass_persist`` de Net-SNMP.

snmpd lanza este programa y le habla por stdin/stdout con el protocolo documentado en
snmpd.conf(5): responde "PONG" a "PING"; para "get"/"getnext" recibe el OID y responde
tres líneas (OID, tipo, valor) o "NONE". La seguridad (SNMPv3, usuarios, vistas) la
maneja snmpd; este programa solo lee la base de datos local.

Los valores con decimales se publican como enteros en centésimas (×100), porque SNMP no
tiene tipo de punto flotante. Ejemplo: 23,47 °C → 2347. Ver deploy/MONITOREO-TERMICO-MIB.txt.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TextIO

from .modelos import Nivel
from .persistencia import BaseDatos, desde_iso

# (sufijo, nombre, tipo, función que extrae el valor del estado)
Extractor = Callable[[dict[str, Any]], Any]


def _cent(valor: float | None) -> int | None:
    return None if valor is None else int(round(valor * 100))


def _sonda(clave: str, campo: str) -> Extractor:
    return lambda e: _cent((e.get(clave) or {}).get(campo))


def _antiguedad(e: dict[str, Any]) -> int:
    return max(0, int((datetime.now(UTC) - desde_iso(e["marca_temporal"])).total_seconds()))


OBJETOS: list[tuple[tuple[int, ...], str, str, Extractor]] = [
    ((1, 0), "temperaturaEntrada", "integer", _sonda("entrada", "temperatura")),
    ((2, 0), "humedadEntrada", "integer", _sonda("entrada", "humedad_relativa")),
    ((3, 0), "temperaturaSalida", "integer", _sonda("salida", "temperatura")),
    ((4, 0), "humedadSalida", "integer", _sonda("salida", "humedad_relativa")),
    ((5, 0), "diferencialTermico", "integer", lambda e: _cent(e.get("delta_t"))),
    ((6, 0), "puntoRocioEntrada", "integer", lambda e: _cent(e.get("punto_rocio_entrada"))),
    ((7, 0), "puntoRocioSalida", "integer", lambda e: _cent(e.get("punto_rocio_salida"))),
    ((8, 0), "margenCondensacion", "integer", lambda e: _cent(e.get("margen_condensacion"))),
    ((9, 0), "variacionTemp15min", "integer", lambda e: _cent(e.get("tasa_variacion_t_15min"))),
    ((10, 0), "variacionTemp1h", "integer", lambda e: _cent(e.get("tasa_variacion_t_1h"))),
    ((11, 0), "aguaDetectada", "integer",
     lambda e: (e.get("base") or {}).get("agua_detectada")),
    ((12, 0), "nivelSeveridad", "integer", lambda e: int(e["nivel"])),
    ((13, 0), "nivelSeveridadTexto", "string", lambda e: Nivel(int(e["nivel"])).etiqueta),
    ((14, 0), "marcaTemporal", "string", lambda e: e["marca_temporal"]),
    ((15, 0), "antiguedadLectura", "gauge", _antiguedad),
]


def oid_a_tupla(oid: str) -> tuple[int, ...]:
    return tuple(int(p) for p in oid.strip().strip(".").split(".") if p)


class AgenteSnmp:
    def __init__(self, oid_base: str, obtener_estado: Callable[[], dict[str, Any] | None]):
        self.base = oid_a_tupla(oid_base)
        self.obtener_estado = obtener_estado

    def _oid(self, sufijo: tuple[int, ...]) -> str:
        return "." + ".".join(str(p) for p in self.base + sufijo)

    def _respuesta(self, estado: dict[str, Any], indice: int) -> list[str] | None:
        sufijo, _, tipo, extraer = OBJETOS[indice]
        try:
            valor = extraer(estado)
        except (KeyError, TypeError, ValueError):
            valor = None
        if valor is None:
            return None
        return [self._oid(sufijo), tipo, str(valor)]

    def get(self, oid: str) -> list[str] | None:
        estado = self.obtener_estado()
        if estado is None:
            return None
        pedido = oid_a_tupla(oid)
        for i, (sufijo, *_rest) in enumerate(OBJETOS):
            if self.base + sufijo == pedido:
                return self._respuesta(estado, i)
        return None

    def getnext(self, oid: str) -> list[str] | None:
        estado = self.obtener_estado()
        if estado is None:
            return None
        pedido = oid_a_tupla(oid)
        for i, (sufijo, *_rest) in enumerate(OBJETOS):  # OBJETOS está ordenado por OID
            if self.base + sufijo > pedido:
                r = self._respuesta(estado, i)
                if r is not None:
                    return r
        return None

    def atender(self, entrada: TextIO, salida: TextIO) -> None:
        """Bucle del protocolo pass_persist."""
        while True:
            linea = entrada.readline()
            if not linea:
                return
            comando = linea.strip()
            if comando == "PING":
                salida.write("PONG\n")
            elif comando in ("get", "getnext"):
                oid = entrada.readline().strip()
                r = self.get(oid) if comando == "get" else self.getnext(oid)
                salida.write("NONE\n" if r is None else "\n".join(r) + "\n")
            elif comando == "set":
                entrada.readline()  # OID
                entrada.readline()  # tipo y valor
                salida.write("not-writable\n")
            elif comando:
                salida.write("NONE\n")
            salida.flush()


def principal(ruta_db: str, oid_base: str) -> None:
    db: BaseDatos | None = None

    def estado() -> dict[str, Any] | None:
        nonlocal db
        try:
            if db is None:
                db = BaseDatos(ruta_db, solo_lectura=True)
            return db.ultimo_estado()
        except Exception:  # noqa: BLE001 - si la base no está lista se responde NONE
            db = None
            return None

    AgenteSnmp(oid_base, estado).atender(sys.stdin, sys.stdout)
