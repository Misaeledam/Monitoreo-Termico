# Hardware: qué comprar y para qué

Los precios de referencia son los de la Tabla 28 de la tesis (recursos, USD 217 en total).
Lo marcado **fuera del presupuesto** no está en esa tabla y conviene agregarlo.

## Para empezar a programar en banco (ya)

| Componente | Para qué | Ref. tesis |
|---|---|---|
| Raspberry Pi 4 Model B (4 GB) | Unidad central: corre el monitor, SQLite, el panel y SNMP | USD 100 |
| Fuente USB-C 5 V / 3 A (oficial o equivalente) | La documentación de Raspberry Pi recomienda 3 A para la Pi 4 | **fuera del presupuesto** |
| microSD de 16 a 32 GB | Primer arranque y, si hace falta, actualizar el bootloader para arrancar desde el SSD | **fuera del presupuesto** |
| 2 × módulo SHT31 (ej. GY-SHT31-D o Adafruit SHT31-D) | Sondas de temperatura y humedad (entrada y salida) | USD 22 |
| Sonda de agua de dos electrodos | Detección de agua en la base | USD 5 |
| Protoboard, cables dupont y 2 resistencias de 4,7 kΩ | Pruebas en banco; las resistencias son pull-ups por si el módulo no las trae | **fuera del presupuesto** |
| Cable de red (patch cord) | Conexión a la red de gestión | **fuera del presupuesto** |

## Para la instalación en el bastidor (antes de la semana 9, 14/12)

| Componente | Para qué | Ref. tesis |
|---|---|---|
| SSD USB de 128 GB (o SSD 2,5" + adaptador USB 3.0–SATA) | Sistema y base de datos; resiste mejor los cortes que la microSD (RNF-04) | USD 25 |
| Gabinete rackeable 1U + fuente | Aloja la Pi en el bastidor (RNF-08) | USD 50 |
| Cable UTP Cat5e (unos 3 m) | Alargar las sondas hasta el frente y el fondo | **fuera del presupuesto** |
| Disipadores o ventilador para la Pi 4 | Dentro de un 1U cerrado la placa calienta | **fuera del presupuesto** |
| Termohigrómetro digital de mano | Instrumento de referencia (±0,5 °C, ±3 % HR) | USD 15 |
| *(Opcional)* Extensor I²C activo LTC4311 | Solo si el bus falla con el cable largo (ver cableado) | **fuera del presupuesto** |

## Cosas a tener en cuenta al comprar

- **Todo a 3,3 V.** Los GPIO de la Raspberry Pi trabajan a 3,3 V y no toleran 5 V; aplicar
  5 V a un GPIO puede dañar el SoC (documentación oficial de Raspberry Pi). Por eso:
  - el SHT31 se alimenta desde el pin de 3V3 (la sonda admite de 2,15 V a 5,5 V);
  - **no** usar sensores de agua que exigen 5 V, como el *Grove Water Sensor* (trabaja de
    4,75 a 5,25 V): su salida llegaría a 5 V al GPIO. La sonda de dos electrodos se lee
    directamente con la resistencia pull-up interna de la Pi.
- **Dirección I²C.** El SHT31 responde en 0x44 (pin ADDR a GND) o 0x45 (ADDR a VDD). Como
  cada sonda va en su propio bus, las dos pueden quedar en 0x44.
- **Pull-ups.** El bus 1 (GPIO2/GPIO3) ya tiene resistencias de 1,8 kΩ en la placa. El bus 4
  no tiene: la mayoría de los módulos SHT31 las traen; si el tuyo no, se agregan 4,7 kΩ de
  SDA y SCL a 3V3.
- **Consumo USB.** La Pi 4 entrega hasta 1,2 A en total por sus puertos USB; un SSD de
  2,5" suele entrar en ese margen.
- **Arranque desde SSD.** La Pi 4 arranca desde USB si el `BOOT_ORDER` lo incluye. El valor
  por defecto (`0xf41`) prueba la SD y después el USB. Las primeras Pi 4 pueden necesitar
  actualizar el bootloader, y para eso sirve la microSD.

## Fuentes

- Sensirion, *Datasheet SHT3x-DIS* (direcciones, comandos, CRC, tensión de alimentación).
- Raspberry Pi Ltd., *Raspberry Pi hardware documentation*: GPIO a 3,3 V, fuente de 3 A,
  1,2 A para USB, arranque USB y `BOOT_ORDER`.
- Raspberry Pi Ltd., *Using I2C on Raspberry Pi SBCs* (buses extra de la Pi 4, pull-ups).
- Seeed Studio, *Grove - Water Sensor* (tensión de trabajo).
