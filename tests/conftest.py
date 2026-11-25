from datetime import UTC, datetime

import pytest

from monitoreo.config import desde_dict
from monitoreo.modelos import Ciclo, LecturaAgua, LecturaAmbiental


@pytest.fixture
def cfg(tmp_path):
    return desde_dict({
        "general": {"base_datos": str(tmp_path / "prueba.db"), "intervalo_muestreo_s": 60},
        "sondas": {"modo": "simulado", "escenario": "normal"},
        "notificaciones": {"tiempo_minimo_min": 10},
        "destinatarios": [{"nombre": "Guardia", "canal": "correo", "contacto": "g@ejemplo.com"}],
    })


@pytest.fixture
def t0():
    return datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def ciclo(marca, t_in=22.0, hr_in=45.0, t_out=31.0, hr_out=30.0, agua=False,
          salida_valida=True):
    salida = (LecturaAmbiental("SALIDA", t_out, hr_out, True) if salida_valida
              else LecturaAmbiental("SALIDA", None, None, False, "sin respuesta"))
    return Ciclo(marca, LecturaAmbiental("ENTRADA", t_in, hr_in, True), salida,
                 LecturaAgua(agua, True))
