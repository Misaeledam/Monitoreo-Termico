# Seguridad

## Superficie expuesta

| Puerto | Protocolo | Desde | Para qué |
|---|---|---|---|
| 22/TCP | SSH (solo clave pública) | Subred de gestión | Administración |
| 8443/TCP | HTTPS (TLS, certificado autofirmado) | Subred de gestión | Panel web |
| 161/UDP | SNMPv3 authPriv (SHA + AES) | Subred de gestión | Consultas del NMS |

Conexiones salientes:
- 587/TCP SMTP con STARTTLS (correo).
- 443/TCP HTTPS hacia api.telegram.org.
- 162/UDP traps SNMPv3 hacia el NMS.
- 123/UDP NTP, para que las marcas de tiempo sean válidas.

El firewall (`deploy/firewall.sh`) rechaza todo lo demás. El equipo no se publica en
internet: el acceso remoto, si alguna vez hace falta, debe hacerse por VPN.

Wi-Fi y Bluetooth quedan apagados (`dtoverlay=disable-wifi` y `dtoverlay=disable-bt`); el
equipo se conecta por cable UTP.

**Certificado autofirmado:** no hay dominio público para pedir uno a una autoridad
certificadora. El navegador muestra un aviso la primera vez; se verifica la huella del
certificado y se acepta. Alternativa en producción: certificado emitido por la CA interna
de la empresa.

## OWASP Top 10:2025

| Categoría | Cómo se trata en el sistema |
|---|---|
| A01 Broken Access Control | El panel pide usuario y contraseña y es de solo lectura: no hay ninguna ruta que modifique datos. El usuario SNMPv3 es de solo lectura y el agente responde `not-writable` a cualquier `set`. La configuración y los secretos tienen permisos 640 (root:monitoreo). |
| A02 Security Misconfiguration | Cabeceras de seguridad (CSP, X-Frame-Options, nosniff, Referrer-Policy, HSTS). Servicios systemd con `NoNewPrivileges` y `ProtectSystem=strict`. El servidor de desarrollo de Flask no se usa en producción (gunicorn). Firewall, Wi-Fi y Bluetooth apagados. En snmpd se eliminan las comunidades v1/v2c (`rocommunity`) y se usa solo SNMPv3. |
| A03 Software Supply Chain Failures | Pocas dependencias (Flask, requests, smbus2, gpiozero, gunicorn). El check automático del repositorio revisa vulnerabilidades conocidas con `pip-audit` en cada cambio. |
| A04 Cryptographic Failures | TLS en el panel, SNMPv3 con autenticación y cifrado, STARTTLS en el correo y HTTPS hacia Telegram. La contraseña del panel se guarda como hash con sal (werkzeug), nunca en texto plano. |
| A05 Injection | Todas las consultas SQL son parametrizadas. `snmptrap` se ejecuta con lista de argumentos, sin shell. Las plantillas escapan el contenido y el JavaScript del panel usa `textContent`, no `innerHTML`. |
| A06 Insecure Design | El sistema notifica y no actúa sobre los equipos (RN-11). Los procesos están separados: el monitor escribe; el panel y el agente SNMP solo leen la base. |
| A07 Authentication Failures | Tras 5 intentos fallidos en 15 minutos, la IP queda bloqueada 15 minutos (respuesta 429). SSH solo con clave. |
| A08 Software or Data Integrity Failures | Cada lectura de la SHT31 se verifica con CRC-8. La base tiene restricciones (`CHECK`) y claves foráneas. Un archivo de configuración inválido se rechaza y se conserva el anterior. La instalación se hace desde una versión etiquetada del repositorio. |
| A09 Security Logging and Alerting Failures | Los intentos de acceso fallidos y los bloqueos se registran en journald. Los eventos y notificaciones quedan en la base. El OID `antiguedadLectura` permite al NMS detectar que el monitor dejó de medir. |
| A10 Mishandling of Exceptional Conditions | Una sonda que falla produce una lectura inválida y un aviso, sin detener el ciclo. Una notificación que no se puede enviar queda en cola. Un error inesperado se registra y el ciclo sigue; systemd reinicia el servicio si se cae. |

## Secretos

- Nunca en el repositorio: `.gitignore` excluye `secretos.env`, claves, certificados y bases de datos.
- Se cargan como variables de entorno desde `/etc/monitoreo/secretos.env` (permisos 640).
- Los mensajes de error del canal de Telegram no incluyen la URL, para que el token no quede en los registros.
