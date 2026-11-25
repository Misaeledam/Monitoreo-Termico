"""Punto de entrada WSGI para gunicorn: ``gunicorn monitoreo.panel.wsgi:app``.

La ruta de la configuración se toma de la variable MONITOREO_CONFIG.
"""

import os

from ..config import cargar
from . import crear_app

_ruta = os.environ.get("MONITOREO_CONFIG", "/etc/monitoreo/config.toml")
app = crear_app(cargar(_ruta), _ruta)
