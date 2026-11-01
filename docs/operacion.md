# Operación de GuauWoow en producción

Guía para quien opera el servidor: tamaño, seguridad del sistema, despliegues y reversa, respaldos,
monitoreo, Cloudflare y cuándo crecer. La puesta en marcha paso a paso (dominio, credenciales,
textos legales, primer certificado) está en [`README-despliegue.md`](../README-despliegue.md).

En todos los comandos:

```bash
cd /opt/patitasfind
F="docker compose -f docker-compose.production.yml"
```

---

## 1. Tamaño del servidor

Objetivo: ~5000 usuarios registrados con picos de 300–800 personas usando la app al mismo tiempo.

| | Mínimo | Cómodo para picos de 800 |
|---|---|---|
| CPU | 4 vCPU | 8 vCPU |
| RAM | 8 GB | 16 GB |
| Disco | 160 GB NVMe | 320 GB NVMe |
| Sistema | Ubuntu 24.04 LTS (o Debian 13) | igual |

Cómo se reparte la memoria con el tamaño mínimo (valores por defecto de `docker-compose.production.yml`):

| Servicio | Límite / reserva | Variable |
|---|---|---|
| PostgreSQL | `shared_buffers` 1 GB, `effective_cache_size` 3 GB, hasta 150 conexiones | `PG_SHARED_BUFFERS`, `PG_EFFECTIVE_CACHE_SIZE` |
| Backend (API) | 3 CPUs, 3 GB, 4 workers de uvicorn | `WEB_CONCURRENCY` |
| Celery worker | 2 CPUs, 2 GB, 4 procesos | `CELERY_CONCURRENCY` |
| Redis | 512 MB (`volatile-lru`: nunca desaloja las colas) | `REDIS_MAXMEMORY` |

Para **8 vCPU / 16 GB** pon en `.env`:

```bash
WEB_CONCURRENCY=8
CELERY_CONCURRENCY=8
PG_SHARED_BUFFERS=4GB
PG_EFFECTIVE_CACHE_SIZE=10GB
REDIS_MAXMEMORY=1gb
```

y sube en `docker-compose.production.yml` los límites del backend a `cpus: "6"`, `memory: 6G` (y el
worker a `memory: 3G`). Revisa la cuenta de conexiones de `app/database.py`: con 8 workers el backend
usa hasta 8 × 10 = 80 conexiones por réplica, y durante un despliegue hay dos réplicas a la vez; si
pasas de ~120 en total, baja `DB_MAX_OVERFLOW` o sube `max_connections` en el compose.

Agrega 2–4 GB de *swap* como colchón (no como memoria de trabajo):

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swappiness.conf && sudo sysctl --system
```

---

## 2. Seguridad del sistema operativo

Hazlo antes de publicar el dominio.

### Usuario y SSH solo con llaves

```bash
# En tu computadora: ssh-keygen -t ed25519 && ssh-copy-id usuario@servidor
sudo adduser deploy && sudo usermod -aG sudo,docker deploy
sudo tee /etc/ssh/sshd_config.d/99-patitasfind.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo systemctl reload ssh
```

Antes de cerrar la sesión, abre **otra** terminal y comprueba que entras con la llave.

### Firewall (ufw): solo 22, 80 y 443

```bash
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable && sudo ufw status verbose
```

PostgreSQL (5432) escucha solo en `127.0.0.1` y el backend no publica puertos: nada más queda
expuesto. Ojo: Docker publica puertos por encima de ufw, así que **no agregues `ports:`** nuevos al
compose sin pensarlo. Para entrar a la base desde tu computadora usa un túnel:
`ssh -L 5432:127.0.0.1:5432 deploy@servidor`.

Con Cloudflare con proxy (§7) puedes además limitar 80/443 a sus rangos (ver
`nginx/snippets/cloudflare-realip.conf`), así nadie llega directo al servidor.

### fail2ban y actualizaciones automáticas

```bash
sudo apt install -y fail2ban unattended-upgrades
sudo tee /etc/fail2ban/jail.d/sshd.local >/dev/null <<'EOF'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
EOF
sudo systemctl enable --now fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades     # "Sí": parches de seguridad automáticos
```

Reinicia el servidor cuando `/var/run/reboot-required` exista (kernel nuevo), en un horario de poco
uso: los contenedores tienen `restart: unless-stopped` y vuelven solos.

### Docker

- Los logs de cada contenedor rotan solos (10 MB × 5 archivos).
- El backend, el worker y beat corren como el usuario `app` (uid 1000), sin privilegios.
  `deploy.sh` deja `backend/uploads` con dueño `1000:1000`.
- `.env` con permisos `600` y fuera de cualquier respaldo sin cifrar.

---

## 3. Desplegar y revertir

### Despliegue normal

```bash
./backend/scripts/deploy.sh --pull
```

Qué hace `deploy.sh`, en orden (se detiene en el primer error y lo dice claro):

1. `--pull`: `git fetch`, cambia a `DEPLOY_BRANCH` (`main`) y `git pull --ff-only`.
2. Revisa `.env`, la configuración de compose y los textos legales (`python3 scripts/render-legal.py
   --check`). Con datos legales pendientes **se niega** a desplegar; `--allow-legal-placeholders` lo
   permite con una advertencia enorme (solo para pruebas, nunca con usuarios reales).
3. Construye `patitasfind-backend:<sha del commit>` (y la etiqueta `latest`). El sha va dentro de la
   imagen: Sentry lo usa como *release*.
4. Asegura PostgreSQL y Redis, hace un **dump cifrado** en `backups/db/` y corre las migraciones
   **una sola vez** (`python -m app.migrate`). Si fallan, no se toca nada de lo que está corriendo.
   Después sincroniza el registro de versiones legales (`python -m app.cli sync-legal-docs`, desde
   `backend/app/data/versiones-legales.json` de la imagen nueva) y cifra los documentos privados y datos
   fiscales que sigan en claro, y pasa a la carpeta privada (cifrados) los documentos antiguos de refugios que
   seguían en `/uploads/` público (`python -m app.cli encrypt-private-files`, idempotente; si falla, el
   despliegue se detiene antes de cambiar los contenedores).
5. **Rolling update**: levanta la(s) réplica(s) nueva(s) junto a la(s) actual(es), espera a que
   `/health` responda, recarga Nginx (reparte entre las dos), apaga la vieja con calma (termina sus
   peticiones; los chats se reconectan solos) y recarga Nginx otra vez. Si la nueva no queda sana en
   4 minutos, se borra y la anterior sigue atendiendo.
6. Recrea Celery worker y beat (el worker termina sus tareas en curso), Nginx/certbot/respaldos si
   cambió su configuración, regenera las plantillas de Nginx y lo recarga sin cortar conexiones.
7. Guarda la versión en `.deploy/` (`current`, `previous`, `history`), conserva las últimas 5 imágenes
   y prueba `https://DOMINIO/health`.

Opciones útiles:

| Opción | Para qué |
|---|---|
| `--replicas 2` | Dejar 2 réplicas del backend (más capacidad y despliegues aún más suaves; revisa memoria y conexiones) |
| `--no-build` | Reiniciar con la imagen actual (p. ej. después de restaurar un respaldo) |
| `--skip-backup` | Saltar el dump previo (no recomendado) |
| `--with-infra` | Aplicar cambios de configuración de PostgreSQL/Redis (los reinicia: unos segundos sin servicio; hazlo de madrugada) |

Variables: `DEPLOY_BRANCH`, `BACKEND_REPLICAS`, `DEPLOY_HEALTH_TIMEOUT` (240 s),
`DEPLOY_KEEP_IMAGES` (5), `DEPLOY_ENV_FILE` (`.env`).

Evita `$F up -d` a secas para el backend: sin `BACKEND_TAG` compose usa la imagen `latest` (que
`deploy.sh` deja apuntando a la versión desplegada, así que el código es el mismo) pero **recrea** los
contenedores en vez de hacer el rolling update, con unos segundos de corte. Para reiniciar sin corte usa
`./backend/scripts/deploy.sh --no-build`. Los comandos puntuales sí van con `$F exec backend ...`
(p. ej. `$F exec backend python -m app.cli create-admin correo 'contraseña'`); con 2 réplicas `exec`
entra a la primera.

### Migraciones

- Todo cambio de esquema va en una revisión de Alembic (`alembic revision --autogenerate` en
  desarrollo, revisada a mano). CI falla si `models.py` cambia sin migración.
- Los contenedores **no** migran al arrancar (`RUN_MIGRATIONS=false`): lo hace `deploy.sh`.
  A mano: `$F run --rm backend python -m app.migrate`.
- Regla para poder revertir: **expandir y luego contraer**. Un despliegue agrega columnas/tablas
  (compatibles con el código anterior); borrar o renombrar va en un despliegue posterior, cuando ya
  nadie usa lo viejo.

### Revertir

```bash
./backend/scripts/rollback.sh --list        # historial e imágenes disponibles
./backend/scripts/rollback.sh               # a la versión anterior
./backend/scripts/rollback.sh <tag|commit>  # a una versión concreta
```

`rollback.sh` pone el código en ese commit (`git checkout --detach`, así frontend y Nginx coinciden con
el backend) y hace el mismo rolling update **sin migrar**. Si la imagen ya no existe, la reconstruye.
`--image-only` cambia solo la imagen del backend. Para volver a la rama principal:
`./backend/scripts/deploy.sh --pull`.

No revierte migraciones. Si una migración dañó datos: detén el backend, restaura el dump que hizo
`deploy.sh` justo antes de migrar (§4) y luego revierte el código.

---

## 4. Respaldos

| Qué | Dónde | Cuándo | Retención |
|---|---|---|---|
| Base de datos: `pg_dump -Fc` cifrado (AES-256 + PBKDF2) | `backups/db/db-<fecha>.dump.enc` | diario desde las 3 h (`BACKUP_HOUR`) y antes de cada migración | 14 días (`BACKUP_RETENTION_DAYS`), siempre las 3 más recientes |
| Fotos (incluye documentos privados) | `backups/uploads/<fecha>/` (instantáneas con enlaces duros: cada día solo ocupa lo nuevo) | diario, junto con la base | 14 días |
| Copia externa cifrada (rclone *crypt*) | bucket R2/S3 (`BACKUP_S3_*`) | diario desde las 4 h | 30 días (`BACKUP_OFFSITE_RETENTION_DAYS`) |

- **Contraseña:** `BACKUP_ENCRYPTION_PASSWORD` es obligatoria (sin ella no arranca el stack) y
  `BACKUP_ENCRYPTION_SALT` la complementa para la copia externa. Genéralas con
  `openssl rand -base64 32` y guárdalas en tu gestor de contraseñas **fuera del servidor**: sin ellas
  los respaldos no sirven.
- **Documentos privados cifrados:** las identificaciones, actas, cédulas, constancias fiscales y CFDI de
  `uploads/private/` (y los datos fiscales de la base) se guardan cifrados con `PRIVATE_FILES_KEY`, así que el
  respaldo de fotos los lleva cifrados. Genera la llave con `openssl rand -base64 32` y guárdala junto a las
  contraseñas de respaldo, **fuera del servidor**: un respaldo restaurado sin esa llave no permite leer esos
  documentos. Para rotarla: la anterior va a `PRIVATE_FILES_OLD_KEYS`, la nueva a `PRIVATE_FILES_KEY` y luego
  `$F exec backend python -m app.cli encrypt-private-files --rotate`.
- **Sin copia externa** (`BACKUP_S3_BUCKET` vacío) el servicio de respaldo lo advierte en cada corrida:
  los respaldos locales no te salvan si se pierde el servidor.
- Las instantáneas de fotos están en el mismo disco: protegen contra borrados, no contra perder el
  disco. Por eso la copia externa sincroniza las fotos (solo sube lo nuevo) y guarda lo borrado en
  `uploads/archive/<fecha>/`.

### Configurar Cloudflare R2

1. Cloudflare → R2 → *Create bucket* (`patitasfind-respaldos`).
2. R2 → *Manage API tokens* → token con permiso **Object Read & Write** solo para ese bucket.
3. En `.env`:
   ```bash
   BACKUP_S3_BUCKET=patitasfind-respaldos
   BACKUP_S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
   BACKUP_S3_ACCESS_KEY_ID=...
   BACKUP_S3_SECRET_ACCESS_KEY=...
   BACKUP_ENCRYPTION_SALT=<openssl rand -base64 32>
   ```
4. `./backend/scripts/deploy.sh --no-build` y luego `$F exec backup-offsite sh /scripts/backup-offsite.sh once`.

### Comandos

```bash
$F exec backup sh /scripts/backup.sh                         # respaldo completo inmediato
$F exec backup sh /scripts/backup.sh health                  # ¿el servicio está sano?
$F exec backup-offsite sh /scripts/backup-offsite.sh once    # copia externa inmediata
ls -lt backups/db | head; ls backups/uploads
```

### Simulacro de restauración (cada mes)

Un respaldo que nunca se probó no es un respaldo. Una vez al mes:

```bash
$F run --rm -e PGDATABASE=patitasfind_restore_test -e RESTORE_CREATE_DB=1 -e RESTORE_YES=1 \
  --entrypoint sh backup /scripts/restore.sh /backups/db/$(ls -t backups/db | head -1)
$F exec postgres psql -U patitasfind -d patitasfind_restore_test -c "select count(*) from users"
$F exec postgres dropdb -U patitasfind patitasfind_restore_test
```

Anota la fecha y cuánto tardó. Cada 3 meses prueba también bajar algo de la copia externa (abajo).

### Restauración real

```bash
$F stop backend celery-worker celery-beat
# Base + fotos (la carpeta de fotos se monta con escritura en /uploads-rw)
$F run --rm -v "$PWD/backend/uploads:/uploads-rw" -e UPLOADS_DIR=/uploads-rw --entrypoint sh backup \
  /scripts/restore.sh /backups/db/db-AAAAMMDD-HHMMSS.dump.enc /backups/uploads/AAAAMMDD-HHMMSS
./backend/scripts/deploy.sh --no-build
```

`restore.sh` primero comprueba la contraseña y el archivo (si no cuadran, no cambia nada), restaura con
`pg_restore --clean --if-exists` en **una sola transacción** (si algo falla, la base queda como estaba)
y aparta las fotos actuales en `backend/uploads/.pre-restore-<fecha>/`. Bórrala cuando confirmes que
todo está bien.

### Restaurar desde la copia externa

Si perdiste el servidor: instala uno nuevo (§2), clona el repo, pon el mismo `.env` (con la misma
contraseña y sal) y baja los respaldos:

```bash
mkdir -p backups/restore
$F run --rm -v "$PWD/backups/restore:/restore" --entrypoint sh backup-offsite \
  /scripts/backup-offsite.sh rclone copy offsitecrypt:db /restore/db --max-age 3d
$F run --rm -v "$PWD/backend/uploads:/restore-uploads" --entrypoint sh backup-offsite \
  /scripts/backup-offsite.sh rclone copy offsitecrypt:uploads/current /restore-uploads
mkdir -p backups/db && mv backups/restore/db/* backups/db/
```

Después sigue "Restauración real" solo con la base (las fotos ya quedaron en su lugar).

---

## 5. Monitoreo y alertas

| Qué | Herramienta | Configuración |
|---|---|---|
| ¿La app responde? | UptimeRobot o Better Stack (gratis) | Monitor HTTP(S) a `https://DOMINIO/health` cada 1–5 min; alerta por correo y app/SMS. `/health` devuelve 503 si fallan PostgreSQL o Redis. |
| ¿Corrió el respaldo? | healthchecks.io | Un check "diario, gracia 2 h" → su URL en `BACKUP_HEARTBEAT_URL`. El servicio avisa `/start`, éxito y `/fail` con el error. |
| ¿Corrió la copia externa? | healthchecks.io | Otro check diario → `BACKUP_OFFSITE_HEARTBEAT_URL`. |
| ¿Hay disco? | healthchecks.io | Check "cada hora, gracia 2 h" → `DISK_ALERT_URL`. `disk-check.sh` corre cada hora y avisa `/fail` si algún disco pasa de `DISK_ALERT_THRESHOLD` (85 %). |
| Errores de la app | Sentry | Reglas abajo. |
| Estado de los contenedores | `$F ps` | Todos con healthcheck: backend (`/health`), worker (`celery inspect ping`), beat (el horario se escribe al menos cada hora), backup y backup-offsite (última corrida), Nginx. |

### Reglas de alerta en Sentry

En *Alerts → Create Alert* (proyecto backend; filtra `environment:production`):

1. **Error nuevo**: "A new issue is created" → correo inmediato.
2. **Ráfaga de errores**: "Number of events in an issue > 50 en 5 min" → correo/Slack.
3. **Regresión**: "An issue changes state from resolved to unresolved".
4. (Rendimiento) Transacciones `p95 > 2 s` durante 10 min en `/dogs`, `/lost-reports`, `/search/by-photo`.

Haz lo mismo en el proyecto del frontend (`SENTRY_DSN_FRONTEND`) con la regla 1 y 2. Cada despliegue
lleva el *release* `patitasfind@<sha>`, así Sentry dice qué versión introdujo un error.

### Revisión rápida

```bash
$F ps                                           # todo "healthy"
$F logs --since 1h backend | grep -c '"status": 5'   # errores 5xx de la última hora
$F logs --since 24h backup | tail -20           # último respaldo
$F exec postgres psql -U patitasfind -c "select count(*), state from pg_stat_activity group by state"
docker stats --no-stream                        # CPU y memoria por contenedor
```

### Consultas lentas

PostgreSQL registra en su log toda consulta de más de 500 ms y carga `pg_stat_statements`. Actívala una
vez y consulta las más costosas:

```bash
$F exec postgres psql -U patitasfind -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"
$F exec postgres psql -U patitasfind -c "select round(total_exec_time) ms, calls, left(query, 90)
  from pg_stat_statements order by total_exec_time desc limit 10"
$F logs postgres | grep duration | tail
```

---

## 6. Disco

`disk-check.sh` mide cada hora el disco de Docker (volúmenes de PostgreSQL y Redis), `backups/` y
`backend/uploads/`. Cuando pasa de 85 %:

```bash
df -h; sudo du -sh /var/lib/docker backups backend/uploads
docker system df                              # imágenes, contenedores y caché de build
docker image prune -f && docker builder prune -f --filter until=168h
ls backups/uploads; ls -lt backups/db | tail  # respaldos locales (la retención es de 14 días)
```

- Si `backups/` crece demasiado: baja `BACKUP_RETENTION_DAYS` (la copia externa guarda 30 días).
- Si son las fotos: es hora de moverlas a almacenamiento de objetos (§8).
- Nunca borres a mano `backups/.state/` ni el volumen `postgres_data`.

---

## 7. Cloudflare delante (CDN y protección)

Recomendado: absorbe tráfico de fotos y estáticos, oculta la IP del servidor y frena ataques.

1. Agrega el dominio a Cloudflare y cambia los *nameservers* en tu registrador.
2. DNS: registros `A` de `@` y `www` hacia el servidor con el **proxy activado** (nube naranja).
3. *SSL/TLS* → modo **Full (strict)** (el servidor ya tiene certificado de Let's Encrypt). Nunca
   "Flexible". Activa *Always Use HTTPS*.
4. **IP real del cliente** (obligatorio con el proxy): en `.env` pon `NGINX_REAL_IP=cloudflare` y
   `./backend/scripts/deploy.sh --no-build`. Sin esto todos los usuarios parecen venir de pocas IPs de
   Cloudflare y los límites de peticiones bloquean a gente legítima. Los rangos están en
   `nginx/snippets/cloudflare-realip.conf` (revísalos cada pocos meses contra
   https://www.cloudflare.com/ips/).
5. *Caching → Cache Rules*:
   - `/uploads/*` → *Eligible for cache*, **Edge TTL: respetar el origen** (Nginx manda
     `public, max-age=31536000, immutable`; los nombres son únicos y nunca cambian).
   - `/img/*`, `/app/vendor/*` y archivos `.css`/`.js` → *Eligible for cache*, respetar el origen.
   - **No** caches la API (`/auth/*`, `/users/*`, `/dogs*`, `/ws/*`, etc.): por defecto Cloudflare no
     cachea JSON, déjalo así.
6. *Network* → **WebSockets activado** (chat). *Speed* → Brotli activado.
7. Opcional: *Security → WAF* con la regla administrada gratuita y *Bot Fight Mode*.
8. Opcional: limita el firewall a Cloudflare (nadie entra directo):
   ```bash
   for ip in $(curl -s https://www.cloudflare.com/ips-v4) $(curl -s https://www.cloudflare.com/ips-v6); do
     sudo ufw allow from "$ip" to any port 80,443 proto tcp; done
   sudo ufw delete allow 80/tcp && sudo ufw delete allow 443/tcp
   ```
   La renovación de Let's Encrypt sigue funcionando porque pasa por Cloudflare.

---

## 8. Capacidad: cuándo crecer

Señales de que el servidor se queda corto (revísalas cada semana los primeros meses):

- CPU del backend > 70 % sostenido en horas pico (`docker stats`) o p95 de la API > 1 s en Sentry.
- Memoria disponible < 15 % o el servidor usa *swap* de forma constante.
- `pg_stat_activity` cerca de 120 conexiones, o muchas consultas en el log de "duration".
- Colas de Celery creciendo: `$F exec redis redis-cli llen default` > 100 por más de unos minutos.
- Disco > 70 % (antes de la alerta del 85 %).

Pasos en orden (cada uno compra mucho margen):

1. **Subir el servidor a 8 vCPU / 16 GB** (§1) y `--replicas 2`. Cambio de horas, sin tocar código.
2. **Fotos a almacenamiento de objetos** (Cloudflare R2 + CDN): las fotos dejan de ocupar el disco del
   servidor y de pasar por Nginx. Requiere cambiar `app/services/images.py` para subir a R2 y servir
   desde un dominio de CDN (p. ej. `fotos.DOMINIO`).
3. **PostgreSQL en otro servidor** (o administrado: DigitalOcean, Neon, Supabase, RDS) con respaldos
   automáticos y réplica de lectura. Solo cambia `DATABASE_URL`; el backend y Celery escalan aparte.
4. Varios servidores de backend detrás de un balanceador (Redis ya coordina chat, caché y límites
   entre réplicas).

Antes de cada paso, mide: una prueba de carga con k6 contra un servidor de pruebas con datos
parecidos a los reales te dice cuántos usuarios simultáneos aguanta cada configuración.

---

## 9. Variables de operación (`.env`)

| Variable | Por defecto | Para qué |
|---|---|---|
| `WEB_CONCURRENCY` | 4 | Workers de uvicorn por réplica del backend |
| `CELERY_CONCURRENCY` | 4 | Procesos del worker de Celery |
| `BACKEND_REPLICAS` | 1 | Réplicas del backend que deja `deploy.sh` |
| `PG_SHARED_BUFFERS` / `PG_EFFECTIVE_CACHE_SIZE` | 1GB / 3GB | Memoria de PostgreSQL (25 % / 75 % de la RAM disponible para la base) |
| `REDIS_MAXMEMORY` | 512mb | Tope de memoria de Redis |
| `NGINX_REAL_IP` | none | `cloudflare` cuando el DNS pasa por el proxy de Cloudflare |
| `SENTRY_ENVIRONMENT` | production | Entorno en Sentry |
| `BACKUP_ENCRYPTION_PASSWORD` | (obligatoria) | Cifra dumps y copia externa |
| `PRIVATE_FILES_KEY` | (obligatoria) | Cifra `uploads/private/*` y los datos fiscales (`openssl rand -base64 32`; guárdala fuera del servidor) |
| `PRIVATE_FILES_OLD_KEYS` | vacío | Llaves anteriores, solo para descifrar al rotar (`encrypt-private-files --rotate`) |
| `MFA_REQUIRED_FOR_ADMINS` | vacío (= obligatoria) | Verificación en dos pasos del personal; en producción no acepta `false` |
| `RETENTION_PURGE_ENABLED` | true | `false` pausa la purga diaria de la tabla de conservación |
| `BACKUP_ENCRYPTION_SALT` | vacío | Segunda clave de la copia externa (rclone crypt) |
| `BACKUP_RETENTION_DAYS` | 14 | Días de respaldos locales |
| `BACKUP_HOUR` | 3 | Hora (México) del respaldo diario; vacío = cada `BACKUP_INTERVAL_SECONDS` |
| `BACKUP_HEARTBEAT_URL` | vacío | Check de healthchecks.io del respaldo |
| `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | vacío | Copia externa (R2/S3) |
| `BACKUP_OFFSITE_HOUR` | 4 | Hora de la copia externa |
| `BACKUP_OFFSITE_RETENTION_DAYS` | 30 | Días que se guardan dumps y fotos borradas en el bucket |
| `BACKUP_OFFSITE_HEARTBEAT_URL` | vacío | Check de healthchecks.io de la copia externa |
| `DISK_ALERT_URL` | vacío | Check de healthchecks.io del disco |
| `DISK_ALERT_THRESHOLD` | 85 | % de uso que dispara la alerta |
