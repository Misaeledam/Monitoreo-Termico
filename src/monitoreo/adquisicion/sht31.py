"""Lectura de la sonda Sensirion SHT31 por I²C, sin dependencias externas salvo smbus2.

Datos tomados de la hoja de datos SHT3x-DIS de Sensirion:
- Dirección 0x44 (pin ADDR a GND) o 0x45 (ADDR a VDD).
- Medición única, repetibilidad alta, sin clock stretching: comando 0x2400.
- Duración máxima de la medición en repetibilidad alta: 15 ms.
- Respuesta: T MSB, T LSB, CRC, HR MSB, HR LSB, CRC.
- CRC-8: polinomio 0x31, valor inicial 0xFF, sin reflexión, XOR final 0x00
  (ejemplo de la hoja de datos: CRC(0xBEEF) = 0x92).
- T [°C] = −45 + 175 · S_T / (2^16 − 1);  HR [%] = 100 · S_RH / (2^16 − 1).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..modelos import LecturaAmbiental

CMD_MEDICION_ALTA = (0x24, 0x00)
CMD_RESET_SUAVE = (0x30, 0xA2)
ESPERA_MEDICION_S = 0.020  # 15 ms de la hoja de datos + margen

# Rango de medición de la sonda: lecturas fuera de él se consideran inválidas (RF-02).
T_MIN, T_MAX = -40.0, 125.0


def crc8(datos: bytes) -> int:
    crc = 0xFF
    for byte in datos:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def convertir(datos: bytes) -> tuple[float, float]:
    """Convierte los 6 bytes crudos en (temperatura °C, humedad %). Verifica el CRC."""
    if len(datos) != 6:
        raise ValueError(f"Se esperaban 6 bytes y llegaron {len(datos)}")
    if crc8(datos[0:2]) != datos[2]:
        raise ValueError("CRC de temperatura inválido")
    if crc8(datos[3:5]) != datos[5]:
        raise ValueError("CRC de humedad inválido")
    s_t = (datos[0] << 8) | datos[1]
    s_rh = (datos[3] << 8) | datos[4]
    temperatura = -45.0 + 175.0 * s_t / 65535.0
    humedad = 100.0 * s_rh / 65535.0
    return temperatura, humedad


def validar(temperatura: float, humedad: float) -> str | None:
    if not T_MIN <= temperatura <= T_MAX:
        return f"temperatura fuera de rango ({temperatura:.2f} °C)"
    if not 0.0 <= humedad <= 100.0:
        return f"humedad fuera de rango ({humedad:.2f} %)"
    return None


class SondaSHT31:
    def __init__(self, bus: int, direccion: int, ubicacion: str,
                 abrir_bus: Callable[[int], Any] | None = None, reintentos: int = 2):
        self.bus = bus
        self.direccion = direccion
        self.ubicacion = ubicacion
        self.reintentos = reintentos
        self._abrir_bus = abrir_bus

    def _bus(self):
        if self._abrir_bus is not None:
            return self._abrir_bus(self.bus)
        from smbus2 import SMBus  # import diferido: solo existe en la Raspberry Pi

        return SMBus(self.bus)

    def _leer_crudo(self) -> bytes:
        from smbus2 import i2c_msg

        with self._bus() as b:
            b.i2c_rdwr(i2c_msg.write(self.direccion, list(CMD_MEDICION_ALTA)))
            time.sleep(ESPERA_MEDICION_S)
            lectura = i2c_msg.read(self.direccion, 6)
            b.i2c_rdwr(lectura)
            return bytes(lectura)

    def leer(self) -> LecturaAmbiental:
        ultimo_error = "sin intentos"
        for _ in range(self.reintentos + 1):
            try:
                temperatura, humedad = convertir(self._leer_crudo())
                problema = validar(temperatura, humedad)
                if problema:
                    ultimo_error = problema
                    continue
                return LecturaAmbiental(self.ubicacion, round(temperatura, 2),
                                        round(humedad, 2), valida=True)
            except (OSError, ValueError) as exc:
                ultimo_error = str(exc)
                time.sleep(0.05)
        return LecturaAmbiental(self.ubicacion, None, None, valida=False, error=ultimo_error)
