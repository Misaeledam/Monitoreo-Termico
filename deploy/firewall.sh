#!/usr/bin/env bash
# Firewall de la Raspberry Pi con ufw: todo lo entrante se rechaza salvo lo necesario,
# y solo desde la subred de gestión. Lo saliente (correo, Telegram, traps SNMP hacia
# el NMS, NTP) queda permitido.
#
# Uso:  sudo ./deploy/firewall.sh 192.168.10.0/24
# Ejecutarlo conectado desde una PC de esa subred: si la subred es incorrecta, se
# corta el acceso SSH.
set -euo pipefail

SUBRED="${1:?Indicar la subred de gestión, por ejemplo 192.168.10.0/24}"

apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$SUBRED" to any port 22 proto tcp comment 'SSH (administración)'
ufw allow from "$SUBRED" to any port 8443 proto tcp comment 'Panel HTTPS'
ufw allow from "$SUBRED" to any port 161 proto udp comment 'SNMPv3 (consultas del NMS)'
# El puerto 162 no se abre: los traps SALEN de la Pi hacia el NMS.
ufw --force enable
ufw status verbose
