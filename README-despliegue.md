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

# 4. Frontend + proxy de la API (incluye WebSocket del chat)
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
  (Lucía, Carlos y Ana administran refugios aprobados).
- En `development`, sin llaves externas: el login demo está activo, el código OTP se
  devuelve como `dev_code`, el enlace de contraseña como `dev_link` y los pagos se
  aprueban de forma simulada (`simulated: true`).

## Producción

```bash
cp .env.example .env
# Edita .env: ENVIRONMENT=production, SECRET_KEY nueva, PUBLIC_BASE_URL=https://tu-dominio
# y las llaves de las integraciones que vayas a usar.

docker compose -f docker-compose.production.yml up -d --build
docker exec patitasfind-backend python -m app.cli create-admin tu@correo.mx 'ContraseñaSegura'
curl https://tu-dominio/health
```

El backend aplica sus migraciones al arrancar (`run_startup_migrations`, idempotentes y
protegidas con un advisory lock para varios workers). Si `ENVIRONMENT=production` y
`SECRET_KEY` es la de desarrollo, el backend se niega a arrancar.

### Componentes

| Servicio | Rol |
|----------|-----|
| PostgreSQL 16 | Datos |
| Redis 7 | Broker de Celery, pub/sub del chat entre workers, caché y rate limit |
| FastAPI + Uvicorn (4 workers) | API REST y WebSocket `/ws/chat/{id}` |
| Celery worker (colas `whatsapp`, `facebook`, `default`) | Bot de WhatsApp, coincidencias por foto, IA, webhooks de pago |
| Celery beat | Recordatorios diarios (8:00 CDMX), Páginas de Facebook cada hora (si hay token), firmas de fotos cada hora |
| Nginx | Estáticos (landing `/`, app `/app/`, panel `/admin/`), `/uploads/`, proxy al backend, límite 12 MB, rate limit en login |

### Integraciones (todas opcionales, configuradas por variables)

| Función | Variables | Sin configurar |
|---------|-----------|----------------|
| Análisis de fotos con Claude | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Búsqueda por foto solo visual (hash + color); `/ai/analyze-photo` → 503 |
| Pagos (tienda y donaciones) | `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_WEBHOOK_SECRET` | dev: simulado · prod: 503 |
| Verificación de teléfono | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID` | dev: `dev_code` · prod: 503 |
| Correo de contraseña | `SMTP_*` | Enlace en logs (y `dev_link` en dev) |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Botón oculto (`google_enabled: false`) |
| Bot de WhatsApp | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` | Solo simulador del panel |
| Páginas de Facebook | `FACEBOOK_PAGE_ACCESS_TOKEN` | Solo importación manual |

`GET /auth/config` indica al frontend qué está activo.

### Webhooks a registrar

- **WhatsApp (Meta):** `https://tu-dominio/whatsapp/webhook`, token de verificación =
  `WHATSAPP_VERIFY_TOKEN`, campo `messages`.
- **Mercado Pago:** `https://tu-dominio/payments/mercadopago/webhook`, evento *Pagos*.

### Facebook

Meta retiró la API de Grupos en 2024 y hacer scraping de grupos viola sus términos, por lo
que PatitasFind **no** lee grupos. Opciones soportadas: Páginas de Facebook vía Graph API
(panel admin → Facebook → agregar fuente tipo "Página") e importación manual de
publicaciones que voluntarios encuentren en grupos.

## SSL / dominio propio

1. Apunta tu dominio al servidor y define `PUBLIC_BASE_URL=https://tu-dominio`.
2. Obtén certificados (con Nginx ya corriendo en el puerto 80):
   ```bash
   docker run --rm -v ./certbot/conf:/etc/letsencrypt -v ./certbot/www:/var/www/certbot \
     certbot/certbot certonly --webroot -w /var/www/certbot -d tu-dominio.com
   ```
3. En `nginx/nginx.conf` descomenta el bloque HTTPS (reemplaza el dominio) y deja el
   servidor del puerto 80 solo con `acme-challenge` y la redirección 301.
4. `docker compose -f docker-compose.production.yml restart nginx`

## Escalabilidad y operación

- El chat funciona con varios workers/réplicas gracias al pub/sub de Redis.
- Uploads: carpeta `backend/uploads` (montada en backend, worker y Nginx). Las fotos se
  re-codifican sin EXIF (sin GPS), máx. 1600 px, con miniatura `<nombre>_thumb.jpg`.
- Logs: `docker compose -f docker-compose.production.yml logs -f backend celery-worker`
- Respaldos: `docker exec patitasfind-postgres pg_dump -U patitasfind patitasfind > backups/$(date +%F).sql`
