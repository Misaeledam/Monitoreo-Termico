"""Panel web propio (RF-13, RNF-09), servido por la propia Raspberry Pi con Flask.

Pensado para la red de gestión: no carga nada de internet (gráficos dibujados con canvas).
Si se define la variable de entorno con el hash de la contraseña, pide usuario y clave.

Controles de seguridad (ver docs/seguridad.md):
- bloqueo temporal de la IP tras varios intentos de acceso fallidos (OWASP A07:2025);
- registro de los intentos fallidos y de los bloqueos (A09:2025);
- cabeceras de seguridad en todas las respuestas (A02:2025).
"""

from __future__ import annotations

import io
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.security import check_password_hash

from ..config import Config, ConfigRecargable
from ..modelos import Nivel
from ..persistencia import BaseDatos, desde_iso

MAX_PUNTOS = 1500
log = logging.getLogger("monitoreo.panel")

CABECERAS_SEGURIDAD = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class ControlIntentos:
    """Bloquea una IP durante ``bloqueo_s`` segundos después de ``max_fallos`` intentos
    fallidos dentro de ``ventana_s`` segundos. El estado vive en memoria del proceso: por
    eso el panel se sirve con un solo proceso de gunicorn (con varios hilos)."""

    def __init__(self, max_fallos: int = 5, ventana_s: float = 900, bloqueo_s: float = 900,
                 reloj=time.monotonic):
        self.max_fallos, self.ventana_s, self.bloqueo_s = max_fallos, ventana_s, bloqueo_s
        self.reloj = reloj
        self._fallos: dict[str, list[float]] = {}
        self._bloqueadas: dict[str, float] = {}
        self._lock = threading.Lock()

    def bloqueada(self, ip: str) -> bool:
        with self._lock:
            hasta = self._bloqueadas.get(ip)
            if hasta is None:
                return False
            if self.reloj() >= hasta:
                del self._bloqueadas[ip]
                return False
            return True

    def registrar_fallo(self, ip: str) -> bool:
        """Devuelve True si este fallo provoca el bloqueo."""
        with self._lock:
            ahora = self.reloj()
            recientes = [t for t in self._fallos.get(ip, []) if ahora - t < self.ventana_s]
            recientes.append(ahora)
            if len(recientes) >= self.max_fallos:
                self._fallos.pop(ip, None)
                self._bloqueadas[ip] = ahora + self.bloqueo_s
                return True
            self._fallos[ip] = recientes
            return False

    def registrar_exito(self, ip: str) -> None:
        with self._lock:
            self._fallos.pop(ip, None)


def crear_app(cfg: Config, ruta_config: str | Path | None = None,
              intentos: ControlIntentos | None = None) -> Flask:
    app = Flask(__name__)
    control = intentos or ControlIntentos()
    recargable = ConfigRecargable(ruta_config) if ruta_config else None

    def config_actual() -> Config:
        if recargable:
            recargable.recargar_si_cambio()
            return recargable.actual
        return cfg

    def db() -> BaseDatos:
        return BaseDatos(config_actual().base_datos, solo_lectura=True)

    def requiere_login(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            c = config_actual()
            hash_clave = Config.secreto(c.panel.contrasena_hash_env)
            if hash_clave:
                ip = request.remote_addr or "desconocida"
                if control.bloqueada(ip):
                    return Response("Demasiados intentos fallidos. Probá más tarde.", 429)
                auth = request.authorization
                if not (auth and auth.username == c.panel.usuario
                        and check_password_hash(hash_clave, auth.password or "")):
                    if auth is not None:  # el primer pedido del navegador llega sin credenciales
                        log.warning("Acceso fallido al panel desde %s (usuario %r)", ip,
                                    auth.username)
                        if control.registrar_fallo(ip):
                            log.warning("IP %s bloqueada por intentos fallidos", ip)
                            return Response("Demasiados intentos fallidos. Probá más tarde.", 429)
                    return Response("Acceso restringido", 401,
                                    {"WWW-Authenticate": 'Basic realm="Monitoreo termico"'})
                control.registrar_exito(ip)
            return vista(*args, **kwargs)

        return envoltura

    @app.after_request
    def cabeceras(respuesta):
        for nombre, valor in CABECERAS_SEGURIDAD.items():
            respuesta.headers.setdefault(nombre, valor)
        if request.is_secure:
            respuesta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return respuesta

    @app.get("/")
    @requiere_login
    def inicio():
        return render_template("index.html", bastidor=config_actual().bastidor)

    @app.get("/configuracion")
    @requiere_login
    def configuracion():
        c = config_actual()
        filas = []
        for metrica, u in sorted(c.umbrales.items()):
            for lim in sorted(u.limites, key=lambda x: x.nivel):
                filas.append({"metrica": metrica, "nivel": lim.nivel.etiqueta,
                              "sentido": "mayor que" if lim.alto else "menor que",
                              "valor": lim.valor, "histeresis": u.histeresis})
        return render_template("configuracion.html", filas=filas, cfg=c,
                               origen=str(c.origen or "valores por defecto"))

    @app.get("/api/estado")
    @requiere_login
    def api_estado():
        base = db()
        try:
            estado = base.ultimo_estado()
        finally:
            base.cerrar()
        if estado is None:
            return jsonify({"disponible": False})
        estado["disponible"] = True
        estado["nivel_texto"] = Nivel(estado["nivel"]).etiqueta
        estado["antiguedad_s"] = int(
            (datetime.now(UTC) - desde_iso(estado["marca_temporal"])).total_seconds())
        return jsonify(estado)

    @app.get("/api/serie")
    @requiere_login
    def api_serie():
        horas = min(max(float(request.args.get("horas", 24)), 0.25), 24 * 31)
        base = db()
        try:
            serie = base.serie(datetime.now(UTC) - timedelta(hours=horas))
        finally:
            base.cerrar()
        paso = max(1, len(serie) // MAX_PUNTOS)
        c = config_actual().umbrales.get("temperatura_entrada")
        lineas = [] if c is None else [
            {"valor": lim.valor, "nivel": lim.nivel.etiqueta} for lim in c.limites]
        return jsonify({"puntos": serie[::paso], "umbrales_temperatura": lineas})

    @app.get("/api/eventos")
    @requiere_login
    def api_eventos():
        base = db()
        try:
            return jsonify({"eventos": base.eventos(100),
                            "notificaciones": base.notificaciones(100)})
        finally:
            base.cerrar()

    @app.get("/exportar.csv")
    @requiere_login
    def exportar():
        dias = min(max(float(request.args.get("dias", 7)), 0.04), 400)
        hasta = datetime.now(UTC)
        buffer = io.StringIO()
        base = db()
        try:
            base.exportar_csv(buffer, hasta - timedelta(days=dias), hasta)
        finally:
            base.cerrar()
        nombre = f"monitoreo_{hasta:%Y%m%d_%H%M}.csv"
        return Response(buffer.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={nombre}"})

    return app
