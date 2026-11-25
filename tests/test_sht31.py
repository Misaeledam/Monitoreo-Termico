"""Driver SHT31: CRC y conversión según la hoja de datos de Sensirion."""

import pytest

from monitoreo.adquisicion.sht31 import SondaSHT31, convertir, crc8


def test_crc_ejemplo_hoja_de_datos():
    # Ejemplo de la hoja de datos SHT3x-DIS: CRC(0xBEEF) = 0x92
    assert crc8(bytes([0xBE, 0xEF])) == 0x92


def _crudo(s_t: int, s_rh: int) -> bytes:
    t = s_t.to_bytes(2, "big")
    h = s_rh.to_bytes(2, "big")
    return t + bytes([crc8(t)]) + h + bytes([crc8(h)])


def test_conversion_extremos():
    t, hr = convertir(_crudo(0, 0))
    assert t == pytest.approx(-45.0)
    assert hr == pytest.approx(0.0)
    t, hr = convertir(_crudo(65535, 65535))
    assert t == pytest.approx(130.0)
    assert hr == pytest.approx(100.0)


def test_conversion_valor_tipico():
    # 25 °C → S_T = (25 + 45) / 175 × 65535 = 26214
    t, _ = convertir(_crudo(26214, 32768))
    assert t == pytest.approx(25.0, abs=0.01)


def test_crc_invalido_se_rechaza():
    datos = bytearray(_crudo(26214, 32768))
    datos[2] ^= 0xFF
    with pytest.raises(ValueError, match="CRC"):
        convertir(bytes(datos))


class _BusFalso:
    """Simula el bus I²C para probar SondaSHT31 sin hardware."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_sonda_reintenta_y_marca_invalida(monkeypatch):
    sonda = SondaSHT31(1, 0x44, "ENTRADA", reintentos=1)
    llamadas = []

    def falla():
        llamadas.append(1)
        raise OSError("Remote I/O error")

    monkeypatch.setattr(sonda, "_leer_crudo", falla)
    monkeypatch.setattr("monitoreo.adquisicion.sht31.time.sleep", lambda s: None)
    lec = sonda.leer()
    assert not lec.valida
    assert "Remote I/O" in lec.error
    assert len(llamadas) == 2


def test_sonda_lectura_valida(monkeypatch):
    sonda = SondaSHT31(1, 0x44, "SALIDA")
    monkeypatch.setattr(sonda, "_leer_crudo", lambda: _crudo(26214, 32768))
    lec = sonda.leer()
    assert lec.valida and lec.temperatura == pytest.approx(25.0, abs=0.01)
    assert lec.humedad_relativa == pytest.approx(50.0, abs=0.01)
