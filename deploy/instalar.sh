#!/usr/bin/env bash
# Instalación en Raspberry Pi OS (Bookworm). Ejecutar con sudo desde la raíz del repositorio.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ejecutar con sudo" >&2
  exit 1
fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Paquetes del sistema"
apt-get update
apt-get install -y python3-venv python3-gpiozero python3-lgpio i2c-tools sqlite3 openssl \
  snmpd snmp

echo "== Usuario de servicio"
id monitoreo >/dev/null 2>&1 || useradd --system --home-dir /var/lib/monitoreo \
  --shell /usr/sbin/nologin monitoreo
usermod -aG i2c,gpio monitoreo
# El agente SNMP (usuario Debian-snmp) solo necesita leer la base de datos.
id Debian-snmp >/dev/null 2>&1 && usermod -aG monitoreo Debian-snmp

echo "== Programa en /opt/monitoreo"
install -d -m 755 /opt/monitoreo
# --system-site-packages: usa gpiozero y lgpio instalados con apt.
[[ -d /opt/monitoreo/venv ]] || python3 -m venv --system-site-packages /opt/monitoreo/venv
/opt/monitoreo/venv/bin/pip install --upgrade pip
/opt/monitoreo/venv/bin/pip install "$REPO[prod]" smbus2

echo "== Configuración en /etc/monitoreo"
install -d -m 750 -o root -g monitoreo /etc/monitoreo /etc/monitoreo/tls
[[ -f /etc/monitoreo/config.toml ]] || install -m 640 -o root -g monitoreo \
  "$REPO/config/config.ejemplo.toml" /etc/monitoreo/config.toml
[[ -f /etc/monitoreo/secretos.env ]] || install -m 640 -o root -g monitoreo \
  "$REPO/deploy/secretos.env.ejemplo" /etc/monitoreo/secretos.env

if [[ ! -f /etc/monitoreo/tls/panel.crt ]]; then
  echo "== Certificado autofirmado para el panel"
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout /etc/monitoreo/tls/panel.key -out /etc/monitoreo/tls/panel.crt \
    -subj "/CN=$(hostname)"
  chown root:monitoreo /etc/monitoreo/tls/panel.key /etc/monitoreo/tls/panel.crt
  chmod 640 /etc/monitoreo/tls/panel.key
fi

echo "== Servicios"
install -m 755 "$REPO/deploy/monitoreo-snmp" /usr/local/bin/monitoreo-snmp
install -m 644 "$REPO"/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now monitoreo-monitor.service monitoreo-panel.service

echo
echo "Listo. Pendiente:"
echo "  1. Editar /etc/monitoreo/config.toml y /etc/monitoreo/secretos.env"
echo "  2. Configurar SNMP según docs/instalacion.md (sección 4)"
echo "  3. Probar: /opt/monitoreo/venv/bin/python -m monitoreo diagnostico -c /etc/monitoreo/config.toml"
