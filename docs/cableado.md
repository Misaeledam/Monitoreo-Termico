# Cableado

Numeración de pines físicos del conector de 40 pines de la Raspberry Pi 4.

## Sonda de ENTRADA (frente, tercio superior) → bus I²C 1

| SHT31 | Pin de la Pi | Señal |
|---|---|---|
| VIN | 1 | 3V3 |
| GND | 6 | GND |
| SDA | 3 | GPIO2 (SDA1) |
| SCL | 5 | GPIO3 (SCL1) |
| ADDR | a GND | dirección 0x44 |

## Sonda de SALIDA (fondo, misma altura) → bus I²C 4

| SHT31 | Pin de la Pi | Señal |
|---|---|---|
| VIN | 17 | 3V3 |
| GND | 9 | GND |
| SDA | 24 | GPIO8 (SDA4) |
| SCL | 21 | GPIO9 (SCL4) |
| ADDR | a GND | dirección 0x44 |

El bus 4 se habilita en `/boot/firmware/config.txt` (ver `deploy/config.txt.fragmento`):

```
dtparam=i2c_arm=on
dtparam=i2c_arm_baudrate=50000
dtoverlay=i2c4,pins_8_9,baudrate=50000
```

Usar GPIO8/GPIO9 para I²C deja sin SPI0; el proyecto no usa SPI.

## Sonda de AGUA (base del bastidor)

| Sonda | Pin de la Pi |
|---|---|
| Electrodo 1 | 11 (GPIO17) |
| Electrodo 2 | 14 (GND) |

El programa activa la resistencia pull-up interna: con la base seca el pin lee "alto" y
el agua, al unir los electrodos, lo lleva a "bajo". Solo circula corriente cuando hay agua.

## Por qué un bus por sonda y a 50 kHz

I²C está pensado para distancias cortas. La guía de Adafruit da como referencia unos 30 cm
a 100 kHz y aconseja acortar el cable o bajar la velocidad si el bus falla. Las sondas del
frente y del fondo quedan más lejos que eso, así que:

1. Cada sonda va en su propio bus: así un cable largo no suma capacidad sobre el otro, y una
   sonda dañada no deja sin datos a la otra.
2. Los dos buses van a 50 kHz en lugar de 100 kHz.
3. El cable es de par trenzado (un tramo de UTP Cat5e), lo más corto posible.
4. Hay que probar antes de instalar: `i2cdetect -y 1` e `i2cdetect -y 4` deben mostrar `44`,
   y `python -m monitoreo diagnostico -c /etc/monitoreo/config.toml` debe leer sin errores.
   Conviene dejarlo varias horas en banco con el cable definitivo.
5. Si aparecen errores (`Remote I/O error`, CRC inválido): bajar a 20 kHz o 10 kHz
   (`baudrate=20000`) y, si no alcanza, poner un extensor activo LTC4311 en el extremo de
   la sonda.

El sistema tolera fallas puntuales: cada lectura se reintenta, se descarta si el CRC no
coincide y, tras tres ciclos seguidos sin dato, avisa que la sonda no responde.

## Ubicación (sección 4.6 de la tesis)

- Entrada: frente del bastidor, tercio superior, en la corriente de aire que entra a los
  equipos, sin tocar metal.
- Salida: fondo, a la misma altura.
- Agua: en la base, en el punto más bajo.
- La Pi y su gabinete calientan: las sondas no deben quedar pegadas al gabinete 1U.
- Alimentación desde el suministro respaldado del bastidor (RN-14).

## Fuentes

- Raspberry Pi Ltd., *Using I2C on Raspberry Pi SBCs* (buses de la Pi 4, pull-ups de 1,8 kΩ).
- Raspberry Pi firmware, `boot/overlays/README` (overlay `i2c4`, `pins_8_9`, `baudrate`,
  `i2c_arm_baudrate`).
- Zephyr Project, `bcm2711-pinctrl.h` (I2C4: SDA en GPIO8 y SCL en GPIO9).
- Adafruit, *Working with I2C Devices: Cable Length*.
