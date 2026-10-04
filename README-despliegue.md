# Guía de despliegue de PatitasFind

## Desarrollo local

```bash
# 1. (Opcional) variables propias
cp .env.example .env

# 2. Levantar PostgreSQL, Redis, backend (8001) y worker de Celery
docker compose up -d --build
#   Si el puerto 5433 ya está ocupado en tu máquina:
#   POSTGRES_HOST_PORT=5437 docker compose up -d --build

# 3. Datos de prueba y administrador
docker exec patitasfind-backend python seed_data.py
docker exec patitasfind-backend python -m app.cli create-admin admin@patitasfind.mx 'TuContraseñaSegura' --name "Admin"

# 4. Frontend + proxy de la API (incluye WebSocket del chat y Google OAuth)
cd app && python3 server.py          # http://localhost:8082  (/, /app/, /admin/)

# 5. Túnel público opcional
cloudflared tunnel --url http://localhost:8082
#   y pon esa URL en PUBLIC_BASE_URL para que los enlaces apunten ahí.

# 6. Pruebas
docker exec patitasfind-backend pytest -q
```

- API y documentación: http://localhost:8001/docs
- Salud: http://localhost:8001/health (revisa base de datos y Redis)
- Usuarios seed: `lucia@patitas.com`, `carlos@patitas.com`, … contraseña `Patitas123!`
  (teléfonos ya verificados; Lucía, Carlos y Ana administran refugios aprobados).
- En `development`, sin llaves externas: el login demo está activo (usuario demo exento de
  verificar teléfono), el código SMS se devuelve como `dev_code`, el enlace de contraseña como
  `dev_link` y los pagos se aprueban de forma simulada (`simulated: true`).

## Cuenta, teléfono y privacidad (resumen de la API)

| Endpoint | Cuerpo | Respuesta |
|----------|--------|-----------|
| `POST /auth/register` | `{email, password, full_name, phone, accepted_terms: true, marketing_opt_in?, city?, country?}` | `201 {access_token, token_type}` · 400 sin teléfono/teléfono inválido/sin aceptar términos · 409 teléfono ya verificado en otra cuenta |
| `POST /users/me/phone/send-code` | opcional `{phone}` (cambia el número antes) | `{sent, phone: "+52…", cooldown: 60, dev_code?}` · 429 espera/límite · 409 · 502 proveedor · 503 sin proveedor |
| `POST /users/me/phone/verify` | `{code}` | `{verified: true}` · 400 incorrecto/vencido · 429 5 intentos · 409 |
| `POST /users/me/password` | `{current_password?, new_password}` | `{ok: true}` (cuentas de Google sin contraseña no envían la actual) |
| `POST /users/me/terms` | `{accepted_terms: true, marketing_opt_in?}` | `User` (para cuentas creadas con Google) |
| `GET /users/me/export` | — | JSON descargable con todos tus datos (acceso/portabilidad) |
| `DELETE /users/me` | `{confirm: "ELIMINAR", password?}` | `{ok: true}` (cancelación) |

Las acciones de escritura (perros, reportes, likes/solicitudes, aprobar/completar, mensajes REST y
WebSocket, pedidos, donaciones, registro de refugio/hogar temporal, productos, análisis con IA)
exigen teléfono verificado y responden:

```json
HTTP 403  {"detail": "Verifica tu teléfono para continuar", "code": "phone_verification_required"}
```

Admins y el usuario demo están exentos. `GET /users/me` incluye `phone_verified`,
`phone_verification_required`, `has_password`, `terms_version`, `privacy_version`,
`terms_accepted_at` y `marketing_opt_in`. `PATCH /users/me {phone}` funciona sin verificar,
normaliza a `+52XXXXXXXXXX` y, si el número cambia, quita la verificación.

**Cancelación de cuenta (LFPDPPP):** se anonimiza el perfil (correo `eliminado-<id>@patitasfind.invalid`,
nombre "Usuario eliminado", sin teléfono, foto, ubicación ni contraseña), se desactiva, se
despublican sus perros, se resuelven sus reportes sin teléfono de contacto, se borran sus
notificaciones y su historial con el bot de WhatsApp. **Se conservan pedidos y donaciones**
(montos, fechas, referencias de pago, sin dirección de envío) porque el Código Fiscal de la
Federación (art. 30) obliga a guardar la contabilidad y su documentación 5 años, y se necesitan
para aclaraciones y contracargos.

**Donaciones:** `POST /payments/donations {refuge_id, amount, share_name?}`; el refugio solo ve el
nombre si `share_name: true`, si no ve "Donante anónimo".

**Bot de WhatsApp:** "BAJA" o "STOP" da de baja el número (no recibe alertas de coincidencias ni
respuestas); "HOLA" lo reactiva.

## Producción

### 1. Preparar `.env`

```bash
cp .env.example .env
# Obligatorio: ENVIRONMENT=production (lo fija el compose), DOMAIN=tu-dominio.mx,
# SECRET_KEY (python3 -c "import secrets; print(secrets.token_urlsafe(64))"),
# POSTGRES_PASSWORD (larga, sin @ : / ?), SMSMASIVOS_API_KEY (o Twilio).
# PUBLIC_BASE_URL y CORS_ORIGINS toman https://$DOMAIN por defecto.
```

El backend **se niega a arrancar** en producción (mensaje claro en `docker compose logs backend`) si:
`SECRET_KEY` es la de desarrollo, `CORS_ORIGINS` está vacío, la contraseña de PostgreSQL es
`patitasfind`, `CORS_ORIGIN_REGEX` permite `trycloudflare`, `SMS_PROVIDER=dev` o el proveedor de SMS
no tiene llaves (con `REQUIRE_PHONE_VERIFICATION=true`), o WhatsApp está
activo sin `WHATSAPP_APP_SECRET` o con el `WHATSAPP_VERIFY_TOKEN` de desarrollo. El login demo
siempre está apagado en producción.

### 2. Primer arranque y certificado (HTTPS)

Nginx usa plantillas (`nginx/templates/<modo>/*.template`) que la imagen `nginx:alpine` procesa con
`envsubst` (solo se sustituye `${DOMAIN}`). Como el modo HTTPS necesita el certificado, la
primera vez se arranca en modo `http-only`:

```bash
# DNS: registros A/AAAA de tu-dominio.mx (y www) apuntando al servidor; puertos 80 y 443 abiertos.
NGINX_MODE=http-only docker compose -f docker-compose.production.yml up -d --build

# Emitir el certificado (webroot servido por Nginx en /.well-known/acme-challenge/)
docker compose -f docker-compose.production.yml run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot -d tu-dominio.mx -d www.tu-dominio.mx \
  --email tu@correo.mx --agree-tos --no-eff-email

# Cambiar a HTTPS (redirección 301, HSTS, CSP, etc.)
docker compose -f docker-compose.production.yml up -d nginx      # NGINX_MODE=https por defecto
curl -I https://tu-dominio.mx/health

docker exec patitasfind-backend python -m app.cli create-admin tu@correo.mx 'ContraseñaSegura'
```

- El servicio `certbot` intenta renovar cada 12 h y Nginx recarga su configuración cada 12 h.
- Nginx: TLS 1.2/1.3, HSTS (2 años), `X-Frame-Options: DENY`, `Referrer-Policy:
  strict-origin-when-cross-origin`, `Permissions-Policy` (geolocalización y cámara solo propias),
  CSP (self + unpkg.com para Leaflet, Google Fonts, teselas y Nominatim de OpenStreetMap,
  PostHog, Sentry, `data:`/`blob:` en imágenes, `wss://` del dominio), `server_tokens off`.
- Nunca sirve archivos de desarrollo de `app/` (`*.py`, `*.mjs`, `*.md`, `package*.json`,
  `node_modules/`, `e2e-shots/`, `test-*`, `_build_index*`, `app-mvp*`, `app-demo*`,
  `index-demo*`, archivos ocultos): responde 404.
- Límites por IP: login/registro/olvidé contraseña 10/min, envío de SMS 6/min (además de los
  límites internos del backend), API 50/s.

### 3. Migraciones

`RUN_MIGRATIONS=true` en producción ejecuta `python -m app.migrate` antes de Uvicorn:
- Base vacía: `alembic upgrade head` crea el esquema desde `alembic/versions/0001_baseline.py`.
- Base existente creada con `create_all` (tiene `users` pero ninguna versión): se hace
  `alembic stamp 0001_baseline` (no recrea tablas) y luego `upgrade head`.
- Un advisory lock evita migraciones simultáneas.

Además, el backend conserva las migraciones de arranque idempotentes (`ADD COLUMN IF NOT
EXISTS`, índices, normalización de teléfonos) como **red de seguridad**: cubren bases antiguas
marcadas con la baseline y despliegues de desarrollo sin Alembic. Los cambios nuevos que no sean
aditivos (renombrar/borrar columnas, cambiar tipos) deben ir en revisiones de Alembic:

```bash
docker exec patitasfind-backend alembic revision --autogenerate -m "describe el cambio"
```

### Componentes

| Servicio | Rol |
|----------|-----|
| PostgreSQL 16 | Datos |
| Redis 7 | Broker de Celery, pub/sub del chat, caché, límites de SMS y de búsquedas |
| backend (FastAPI + Uvicorn ×4) | API REST y WebSocket `/ws/chat/{id}`; healthcheck `/health` |
| celery-worker | Bot de WhatsApp, coincidencias por foto, IA, webhooks de pago; healthcheck `celery inspect ping` |
| celery-beat | Recordatorios diarios, Páginas de Facebook, firmas de fotos |
| nginx | HTTPS, estáticos, `/uploads/`, proxy; healthcheck `/nginx-health` |
| certbot | Renovación de certificados |
| backup / backup-offsite | Respaldos diarios y copia externa opcional |

Todos los servicios rotan logs (`json-file`, 10 MB × 5). Cada petición lleva `X-Request-ID`
(Nginx lo genera y el backend lo registra en un log JSON por petición y en Sentry).

### Integraciones (todas opcionales, configuradas por variables)

| Función | Variables | Sin configurar |
|---------|-----------|----------------|
| Análisis de fotos (Qwen3-VL / GLM-4.6V) | `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, `AI_EXTRA_BODY` | Búsqueda por foto solo visual; `/ai/analyze-photo` → 503 |
| SMS de verificación | `SMS_PROVIDER`, `SMSMASIVOS_API_KEY` (`SMSMASIVOS_SANDBOX`) o `TWILIO_*` | dev: `dev_code` · prod: el backend no arranca con `dev`; sin llaves → 503 |
| Pagos (tienda y donaciones) | `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_WEBHOOK_SECRET` | dev: simulado · prod: 503 |
| Correo de contraseña | `SMTP_*` | Enlace en logs (y `dev_link` en dev) |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Botón oculto (`google_enabled: false`) |
| Bot de WhatsApp | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Solo simulador del panel |
| Páginas de Facebook | `FACEBOOK_PAGE_ACCESS_TOKEN` | Solo importación manual |
| Errores | `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_DSN_FRONTEND` | Sin reporte |
| Analítica | `POSTHOG_KEY`, `POSTHOG_HOST` | Sin analítica |

`GET /auth/config` indica al frontend qué está activo: `google_enabled`, `demo_enabled`,
`otp_enabled`, `require_phone_verification`, `sms_provider`, `otp_cooldown`, `payments_enabled`,
`ai_enabled`, `whatsapp_enabled`, `environment`, `sentry_dsn_frontend`, `posthog_key`,
`posthog_host`, `legal_versions: {terms, privacy}`.

### Webhooks a registrar

- **WhatsApp (Meta):** `https://tu-dominio/whatsapp/webhook`, token de verificación =
  `WHATSAPP_VERIFY_TOKEN`, campo `messages`.
- **Mercado Pago:** `https://tu-dominio/payments/mercadopago/webhook`, evento *Pagos*.

## Google OAuth ("Continuar con Google")

1. https://console.cloud.google.com → crea (o elige) un proyecto.
2. **APIs y servicios → Pantalla de consentimiento de OAuth** (Google Auth Platform → Branding):
   tipo *Externo*; nombre "PatitasFind", correo de soporte, logo opcional; dominio autorizado
   `tu-dominio.mx`; enlaces a `https://tu-dominio.mx/app/legal/privacidad.html` y términos.
   Alcances: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (no requieren
   verificación de Google). Mientras esté en modo *Prueba*, agrega tus correos como usuarios de
   prueba; luego pulsa *Publicar app*.
3. **Credenciales → Crear credenciales → ID de cliente de OAuth → Aplicación web**:
   - Orígenes de JavaScript autorizados: `http://localhost:8082` y `https://tu-dominio.mx`
   - URI de redireccionamiento autorizados: `http://localhost:8082/auth/google/callback` y
     `https://tu-dominio.mx/auth/google/callback`
4. Copia el ID y el secreto a `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` y reinicia el backend.

Flujo: `/auth/google/login` firma un `state` (itsdangerous, 10 min) y deja una cookie HttpOnly con
su nonce; `/auth/google/callback` valida firma, vigencia y cookie (protección CSRF), cambia el código
por el perfil, exige `email_verified` y entra a la cuenta existente con el mismo correo (la
vincula guardando `google_sub`) o crea una nueva. Cualquier error redirige a
`/app/?auth_error=<mensaje>`; el éxito a `/app/?token=<jwt>`. La URI de retorno es
`{PUBLIC_BASE_URL}/auth/google/callback` (local: `http://localhost:8082`, que `app/server.py` reenvía
al backend incluyendo redirecciones y cookies). El frontend puede llamar
`/auth/google/login?accepted_terms=1&marketing_opt_in=0` para registrar el consentimiento de
cuentas nuevas; si no, la cuenta nueva acepta después con `POST /users/me/terms`. Las cuentas de
Google nuevas no tienen teléfono: deben hacer `PATCH /users/me {phone}` (o mandar `{phone}` a
`send-code`) y verificarlo antes de publicar.

## Respaldos y restauración

El servicio `backup` corre `backend/scripts/backup.sh` al arrancar y luego cada 24 h:
`pg_dump -Fc` → `./backups/db-AAAAMMDD-HHMMSS.dump` y las fotos → `./backups/uploads-….tar.gz`.
Se borran los de más de `BACKUP_RETENTION_DAYS` (14). Respaldo manual inmediato:

```bash
docker compose -f docker-compose.production.yml exec backup sh /scripts/backup.sh
```

**Copia externa (S3 / Cloudflare R2):** define `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`,
`BACKUP_S3_SECRET_ACCESS_KEY`, `BACKUP_S3_ENDPOINT` (R2: `https://<account_id>.r2.cloudflarestorage.com`)
y `BACKUP_S3_PROVIDER` (`Cloudflare`, `AWS`, …). El servicio `backup-offsite` (rclone) copia cada
24 h los archivos nuevos a `<bucket>/<BACKUP_S3_PREFIX>/`. Configura en el bucket una regla de
ciclo de vida (p. ej. borrar a los 30 días). Sin bucket, el servicio queda inactivo.

**Restaurar:**

```bash
ls -lt backups/ | head                      # elige el par db-/uploads- de la misma fecha
docker compose -f docker-compose.production.yml stop backend celery-worker celery-beat
docker compose -f docker-compose.production.yml run --rm --entrypoint sh backup \
  /scripts/restore.sh /backups/db-20261004-030000.dump /backups/uploads-20261004-030000.tar.gz
#   escribe RESTAURAR para confirmar (o pasa -e RESTORE_YES=1)
docker compose -f docker-compose.production.yml up -d
curl https://tu-dominio.mx/health
```

`restore.sh` usa `pg_restore --clean --if-exists` y mueve las fotos actuales a
`backend/uploads/.pre-restore-<fecha>/` antes de extraer las del respaldo. Para restaurar desde
la copia externa, descarga los archivos a `./backups/` (p. ej. `rclone copy offsite:bucket/patitasfind ./backups`)
y sigue los mismos pasos. Prueba una restauración al menos una vez al mes en un servidor aparte.

## CI

`.github/workflows/ci.yml` (push y pull request): PostgreSQL + Redis como servicios, instala
dependencias, `python -m app.migrate` sobre base vacía, `pytest -q`, `node --check app/*.js`,
`docker build` del backend, validación de ambos `docker-compose` y `nginx -t` de la plantilla HTTPS.

## Operación

- El chat funciona con varios workers/réplicas gracias al pub/sub de Redis.
- Uploads: carpeta `backend/uploads` (montada en backend, worker, Nginx y backup). Las fotos se
  re-codifican sin EXIF (sin GPS), máx. 1600 px, con miniatura `<nombre>_thumb.jpg`.
- Logs: `docker compose -f docker-compose.production.yml logs -f backend celery-worker`
- Estado: `docker compose -f docker-compose.production.yml ps` (columna *health*).
