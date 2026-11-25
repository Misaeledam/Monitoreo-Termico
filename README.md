# Charmeleon-SYS

**Sistema de monitoreo térmico preventivo para racks de servidores.**
Proyecto de Grado, Licenciatura en Análisis de Sistemas Informáticos (UNAE, FACAT).
Autor: Misael Amarilla.

Una Raspberry Pi 4 con dos sondas SHT31 (entrada y salida de aire) y una sonda de agua
mide el ambiente dentro del bastidor y calcula:
- el diferencial térmico (ΔT);
- el punto de rocío;
- la tasa de variación de la temperatura.

Con esos datos clasifica el riesgo en cuatro niveles (Normal, Aviso, Advertencia, Crítico),
con histéresis. Avisa por correo y WhatsApp y publica todo por SNMPv3 para el sistema de
monitoreo de red. Toda la evaluación ocurre en el propio equipo, así que sigue
funcionando sin internet.

## Módulos (Figuras D12 y D13 de la tesis)

| Módulo | Archivo | Requisitos |
|---|---|---|
| Adquisición (SHT31 por I²C, agua por GPIO) | `src/monitoreo/adquisicion/` | RF-01, RF-02, RF-06 |
| Motor de análisis (ΔT, rocío, ventana deslizante) | `src/monitoreo/analisis.py` | RF-03, RF-04, RF-05 |
| Clasificador de severidad con histéresis | `src/monitoreo/severidad.py` | RF-07, RF-08, RN-08, RN-09 |
| Persistencia SQLite | `src/monitoreo/persistencia.py` | RF-10, RF-15, RF-17, RNF-04 |
| Notificador con cola y reintentos | `src/monitoreo/notificador.py` | RF-09, RF-12, RF-15 |
| Agente SNMP (`pass_persist` de Net-SNMP) | `src/monitoreo/snmp_agente.py` + `deploy/MONITOREO-TERMICO-MIB.txt` | RF-11, RNF-06 |
| Panel web (Flask, sin dependencias externas) | `src/monitoreo/panel/` | RF-13, RNF-09 |
| Configuración externa con recarga en caliente | `src/monitoreo/config.py`, `config/` | RF-14, RNF-11 |
| Entorno virtual simulado | `src/monitoreo/adquisicion/simulado.py` | T-03, CP-05/07/08/22 |

## Probar sin hardware

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest                                       # 49 pruebas
python -m monitoreo monitor -c config/config.simulado.toml --simulado calentamiento --acelerar 30 --ciclos 60
python -m monitoreo panel -c config/config.simulado.toml   # http://127.0.0.1:8080
```

## Documentación

- [Hardware: qué comprar](docs/hardware.md)
- [Cableado](docs/cableado.md)
- [Instalación en la Raspberry Pi](docs/instalacion.md)
- [Entorno virtual simulado](docs/entorno-simulado.md)

## Estado

- [x] Código base de las diez historias de usuario (HU-01 a HU-10), probado con sondas simuladas.
- [x] SNMPv3 verificado con Net-SNMP 5.9: lectura de las 15 métricas y notificación `cambioNivel`.
- [ ] Prueba con las sondas reales en banco (cuando llegue el hardware).
- [ ] Instalación en el bastidor y campaña de medición de una semana (H-07).
- [ ] Calibrar los umbrales provisionales con la línea base (RN-07, RN-10).
- [ ] Edición de umbrales desde el panel (hoy se editan en el archivo de configuración).
