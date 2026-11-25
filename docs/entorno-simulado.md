# Entorno virtual simulado

Es el entorno donde se emulan los puntos críticos que no se provocan sobre el bastidor real
(T-03, sección 4.5 de la tesis): una máquina virtual o la PC de desarrollo, con las sondas
reemplazadas por funciones que inyectan valores conocidos. El resto del sistema (análisis,
severidad, base de datos, notificaciones, panel y SNMP) es exactamente el mismo código.

## Uso

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows   (en Linux: source .venv/bin/activate)
pip install -e ".[dev]"

python -m monitoreo escenarios   # lista los escenarios

# 60 minutos simulados en 2 minutos reales (factor 30)
python -m monitoreo monitor -c config/config.simulado.toml --simulado calentamiento --acelerar 30 --ciclos 60

# en otra terminal: panel en http://127.0.0.1:8080
python -m monitoreo panel -c config/config.simulado.toml
```

## Escenarios

| Escenario | Qué emula | Nivel esperado | Caso de prueba |
|---|---|---|---|
| `normal` | 21,5 °C con la oscilación del aire acondicionado | Normal | Línea de base |
| `calentamiento` | Falla de refrigeración: +0,5 °C por minuto | Aviso → Advertencia (tasa) → Crítico | CP-05, CP-07 |
| `subida_brusca` | +8 °C en 5 minutos | Advertencia por tasa y por umbral | CP-05 |
| `sobre_limite` | Entrada a 33,5 °C (> 32 °C) | Crítico | CP-07 |
| `bajo_2` | Entrada a 1,5 °C (< 2 °C) | Crítico | CP-07 |
| `condensacion` | La humedad sube hasta acercar el rocío a la temperatura | Crítico | CP-04 |
| `agua` | Agua desde el minuto 3 | Crítico inmediato | CP-06 |
| `falla_sonda` | La sonda de salida deja de responder | Aviso | CP-02 |

Al calentarse el aire, los escenarios mantienen constante el punto de rocío, así que la
humedad relativa baja, como pasa físicamente.

Las pruebas automáticas (`pytest`) corren estos mismos escenarios y verifican el nivel
alcanzado. Por ejemplo, comprueban que en `calentamiento` la alerta por tasa de variación
llega antes que el nivel crítico por umbral.
