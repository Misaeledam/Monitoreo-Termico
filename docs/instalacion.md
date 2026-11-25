# Instalación en la Raspberry Pi 4

Los pasos asumen Raspberry Pi OS (Bookworm, 64 bits). El script `deploy/instalar.sh` todavía
no se ejecutó sobre una Raspberry Pi real: se valida cuando llegue el hardware.

## 1. Sistema

1. Grabar Raspberry Pi OS Lite (64 bits) con Raspberry Pi Imager en el SSD. Si la Pi no
   arranca desde USB, grabar primero la microSD, actualizar el bootloader y configurar el
   orden de arranque con `sudo raspi-config` (Advanced Options → Boot Order).
2. En Imager: nombre de equipo, usuario, SSH con clave pública y zona horaria.
3. Agregar al final de `/boot/firmware/config.txt` el contenido de
   `deploy/config.txt.fragmento` y reiniciar.
4. Verificar las sondas:
   ```bash
   sudo apt install -y i2c-tools
   i2cdetect -y 1     # debe aparecer 44
   i2cdetect -y 4     # debe aparecer 44
   ```

## 2. Programa

```bash
git clone https://github.com/Misaeledam/Monitoreo-Termico.git
cd Monitoreo-Termico
sudo ./deploy/instalar.sh
```

El script:
- instala dependencias;
- crea el usuario de servicio `monitoreo`;
- deja el programa en `/opt/monitoreo`;
- copia la configuración a `/etc/monitoreo`;
- genera un certificado autofirmado para el panel;
- activa los servicios.

## 3. Configurar

- `/etc/monitoreo/config.toml`: bastidor, destinatarios, canales y umbrales. El monitor lo
  recarga solo al guardar.
- `/etc/monitoreo/secretos.env`: contraseñas y claves (permisos 640). Después de editarlo:
  `sudo systemctl restart monitoreo-monitor monitoreo-panel`.
- Contraseña del panel:
  `sudo -u monitoreo /opt/monitoreo/venv/bin/python -m monitoreo hash-contrasena`. El
  resultado va en `MONITOREO_PANEL_HASH`.
- Probar los envíos:
  `sudo -u monitoreo bash -c 'set -a; . /etc/monitoreo/secretos.env; /opt/monitoreo/venv/bin/python -m monitoreo probar-notificacion -c /etc/monitoreo/config.toml'`.

### WhatsApp (CallMeBot)

Cada destinatario agrega el número del bot a sus contactos y le manda por WhatsApp el
mensaje `I allow callmebot to send me messages`. El bot responde con la apikey, que va en
`secretos.env`. Según CallMeBot, la API gratuita es solo para uso personal.

## 4. SNMP

```bash
sudo systemctl stop snmpd
sudo net-snmp-create-v3-user -ro -a SHA -A 'CLAVE_AUTH' -x AES -X 'CLAVE_PRIV' monitoreo
# agregar a /etc/snmp/snmpd.conf el contenido de deploy/snmpd.conf.ejemplo
sudo systemctl start snmpd
```

Desde el NMS (copiar `deploy/MONITOREO-TERMICO-MIB.txt` a su carpeta de MIB):

```bash
snmpwalk -v3 -u monitoreo -l authPriv -a SHA -A 'CLAVE_AUTH' -x AES -X 'CLAVE_PRIV' \
  -m +MONITOREO-TERMICO-MIB IP_DE_LA_PI .1.3.6.1.4.1.8072.9999.9999.1
```

Este procedimiento se verificó con Net-SNMP 5.9 (snmpd con `pass_persist` y snmpwalk
SNMPv3 authPriv); también se verificó la recepción de la notificación `cambioNivel` en
snmptrapd.

## 5. Operación

```bash
systemctl status monitoreo-monitor monitoreo-panel
journalctl -u monitoreo-monitor -f          # registro en vivo
```

Panel: `https://IP_DE_LA_PI:8443` (el navegador avisa del certificado autofirmado).
