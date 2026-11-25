"""Panel web propio (RF-13, RNF-09), servido por la propia Raspberry Pi con Flask.

Pensado para la red de gestión: no carga nada de internet (gráficos dibujados con canvas).
Si se define la variable de entorno con el hash de la contraseña, pide usuario y clave.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.security import check_password_hash

from ..config import Config, ConfigRecargable
from ..modelos import Nivel
from ..persistencia import BaseDatos, desde_iso

MAX_PUNTOS = 1500


def crear_app(cfg: Config, ruta_config: str | Path | None = None) -> Flask:
    app = Flask(__name__)
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
                auth = request.authorization
                if not (auth and auth.username == c.panel.usuario
                        and check_password_hash(hash_clave, auth.password or "")):
                    return Response("Acceso restringido", 401,
                                    {"WWW-Authenticate": 'Basic realm="Monitoreo termico"'})
            return vista(*args, **kwargs)

        return envoltura

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
