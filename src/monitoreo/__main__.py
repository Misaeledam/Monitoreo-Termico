"""Línea de comandos: ``python -m monitoreo <comando> --config archivo.toml``."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Config, ConfigRecargable, cargar


def _cfg(args: argparse.Namespace) -> Config:
    return cargar(args.config) if args.config else Config(base_datos="monitoreo.db")


def cmd_monitor(args: argparse.Namespace) -> int:
    from .servicio import Monitor, Reloj

    recargable = ConfigRecargable(args.config) if args.config else None
    cfg = recargable.actual if recargable else Config(base_datos="monitoreo.db")
    if args.simulado:
        cfg = replace(cfg, sondas=replace(cfg.sondas, modo="simulado", escenario=args.simulado))
        recargable = None  # en simulación se ignoran cambios del archivo
    if args.base_datos:
        cfg = replace(cfg, base_datos=args.base_datos)
    reloj = Reloj(args.acelerar)
    monitor = Monitor(cfg, recargable=recargable, inicio=reloj.ahora())
    logging.getLogger("monitoreo").info(
        "Monitor iniciado (%s%s), base %s, cada %.0f s",
        cfg.sondas.modo, f": {cfg.sondas.escenario}" if cfg.sondas.modo == "simulado" else "",
        cfg.base_datos, cfg.intervalo_muestreo_s)
    monitor.ejecutar(reloj, ciclos=args.ciclos)
    return 0


def cmd_panel(args: argparse.Namespace) -> int:
    from .panel import crear_app

    cfg = _cfg(args)
    app = crear_app(cfg, args.config)
    ssl = None
    if cfg.panel.certificado and cfg.panel.clave_privada:
        ssl = (cfg.panel.certificado, cfg.panel.clave_privada)
    app.run(host=args.host or cfg.panel.host, port=args.puerto or cfg.panel.puerto,
            ssl_context=ssl)
    return 0


def cmd_snmp(args: argparse.Namespace) -> int:
    from .snmp_agente import principal

    cfg = _cfg(args)
    principal(cfg.base_datos, cfg.snmp.oid_base)
    return 0


def cmd_diagnostico(args: argparse.Namespace) -> int:
    """Lee una vez cada sonda real y muestra el resultado (para probar el cableado)."""
    cfg = _cfg(args)
    for bus in sorted({cfg.sondas.entrada.bus, cfg.sondas.salida.bus}):
        existe = Path(f"/dev/i2c-{bus}").exists()
        print(f"/dev/i2c-{bus}: {'presente' if existe else 'NO EXISTE (revisar config.txt)'}")
    from .adquisicion.sht31 import SondaSHT31

    for nombre, s in (("ENTRADA", cfg.sondas.entrada), ("SALIDA", cfg.sondas.salida)):
        lec = SondaSHT31(s.bus, s.direccion, nombre).leer()
        detalle = (f"{lec.temperatura:.2f} °C, {lec.humedad_relativa:.2f} % HR"
                   if lec.valida else f"ERROR: {lec.error}")
        print(f"Sonda {nombre} (i2c-{s.bus}, 0x{s.direccion:02x}): {detalle}")
    try:
        from .adquisicion.real import SondaAgua

        sonda = SondaAgua(cfg.sondas.gpio_agua)
        agua = sonda.leer()
        sonda.cerrar()
        estado = ("AGUA DETECTADA" if agua.detectada else "seca") if agua.valida else agua.error
        print(f"Sonda de agua (GPIO{cfg.sondas.gpio_agua}): {estado}")
    except Exception as exc:  # noqa: BLE001
        print(f"Sonda de agua: ERROR {exc}")
    return 0


def cmd_exportar(args: argparse.Namespace) -> int:
    from .persistencia import BaseDatos

    cfg = _cfg(args)
    db = BaseDatos(cfg.base_datos, solo_lectura=True)
    hasta = datetime.now(UTC)
    with open(args.salida, "w", newline="", encoding="utf-8") as f:
        n = db.exportar_csv(f, hasta - timedelta(days=args.dias), hasta)
    print(f"{n} filas exportadas a {args.salida}")
    return 0


def cmd_probar_notificacion(args: argparse.Namespace) -> int:
    from .modelos import Ciclo, Evaluacion, LecturaAgua, LecturaAmbiental, Metricas, Nivel
    from .notificador import Notificador
    from .persistencia import BaseDatos

    cfg = _cfg(args)
    db = BaseDatos(cfg.base_datos)
    db.preparar(cfg)
    ahora = datetime.now(UTC)
    ciclo = Ciclo(ahora, LecturaAmbiental("ENTRADA", None, None, False, "prueba"),
                  LecturaAmbiental("SALIDA", None, None, False, "prueba"),
                  LecturaAgua(False, True))
    ev = Evaluacion(nivel=Nivel.AVISO, nivel_anterior=Nivel.NORMAL, cambio=True, notificar=True,
                    motivo_notificacion="mensaje de prueba")
    met = Metricas(marca_temporal=ahora)
    id_metrica = db.guardar_ciclo(ciclo, met, Nivel.NORMAL)
    notif = Notificador(cfg, db)
    n = notif.encolar(db.registrar_evento(ahora, ev, id_metrica), ev, ciclo, met)
    enviadas, fallidas = notif.procesar(ahora)
    print(f"Encoladas: {n} · enviadas: {enviadas} · con error: {fallidas}")
    for fila in db.notificaciones(n):
        print(f"  {fila['canal']}: {fila['estado']} {fila['ultimo_error'] or ''}")
    return 0 if fallidas == 0 else 1


def cmd_hash(_: argparse.Namespace) -> int:
    from werkzeug.security import generate_password_hash

    clave = getpass.getpass("Contraseña del panel: ")
    if clave != getpass.getpass("Repetir: "):
        print("No coinciden", file=sys.stderr)
        return 1
    print(generate_password_hash(clave))
    return 0


def cmd_escenarios(_: argparse.Namespace) -> int:
    from .adquisicion.simulado import ESCENARIOS

    for nombre, funcion in ESCENARIOS.items():
        print(f"{nombre:15} {(funcion.__doc__ or '').strip()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="monitoreo", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="comando", required=True)

    def nuevo(nombre: str, funcion, ayuda: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(nombre, help=ayuda)
        sp.add_argument("-c", "--config", help="archivo TOML de configuración")
        sp.set_defaults(funcion=funcion)
        return sp

    m = nuevo("monitor", cmd_monitor, "ciclo de supervisión")
    m.add_argument("--simulado", metavar="ESCENARIO", help="usar sondas simuladas")
    m.add_argument("--acelerar", type=float, default=1.0, help="factor de tiempo (simulación)")
    m.add_argument("--ciclos", type=int, help="cantidad de ciclos y salir")
    m.add_argument("--base-datos", help="ruta alternativa de la base SQLite")
    pn = nuevo("panel", cmd_panel, "panel web (servidor de desarrollo)")
    pn.add_argument("--host")
    pn.add_argument("--puerto", type=int)
    nuevo("snmp-agente", cmd_snmp, "extensión pass_persist para snmpd")
    nuevo("diagnostico", cmd_diagnostico, "leer una vez las sondas reales")
    e = nuevo("exportar", cmd_exportar, "exportar lecturas a CSV")
    e.add_argument("--dias", type=float, default=7)
    e.add_argument("--salida", default="lecturas.csv")
    nuevo("probar-notificacion", cmd_probar_notificacion, "enviar un mensaje de prueba")
    nuevo("hash-contrasena", cmd_hash, "generar el hash de la contraseña del panel")
    nuevo("escenarios", cmd_escenarios, "listar escenarios simulados")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    return args.funcion(args)


if __name__ == "__main__":
    sys.exit(main())
