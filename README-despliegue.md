# Guía de despliegue de GuauWoow

Esta guía lleva GuauWoow de cero a producción (objetivo: ~5000 personas usuarias, picos de 300 a
800 simultáneas). La operación diaria (firewall, monitoreo, escalar, desplegar y revertir, restaurar
respaldos) está en [`docs/operacion.md`](docs/operacion.md).

Contenido:

1. [Lista de lanzamiento](#1-lista-de-lanzamiento)
2. [Servidor](#2-servidor)
3. [Dominio y DNS](#3-dominio-y-dns)
4. [Credenciales y dónde obtenerlas](#4-credenciales-y-dónde-obtenerlas)
5. [Correo: SPF, DKIM y DMARC](#5-correo-spf-dkim-y-dmarc)
6. [Mercado Pago y su webhook](#6-mercado-pago-y-su-webhook)
7. [WhatsApp: webhook y plantillas](#7-whatsapp-webhook-y-plantillas)
8. [Google OAuth](#8-google-oauth-continuar-con-google)
9. [Textos legales](#9-textos-legales-llenar-generar-y-verificar)
10. [Primer despliegue](#10-primer-despliegue)
11. [Crear el administrador](#11-crear-el-administrador)
12. [Revisiones después del lanzamiento](#12-revisiones-después-del-lanzamiento)
13. [Despliegues siguientes y reversa](#13-despliegues-siguientes-y-reversa)
14. [Respaldos y restauración](#14-respaldos-y-restauración)
15. [CI](#15-ci)
16. [Desarrollo local](#16-desarrollo-local)
17. [Referencia rápida de la API de cuenta](#17-referencia-rápida-de-la-api-de-cuenta)
18. [Veterinarias: llave de Google Maps](#18-veterinarias-llave-de-google-maps-places-api-new)
19. [Grupos públicos de Facebook y voluntarios](#19-grupos-públicos-de-facebook-apify-y-voluntarios)
20. [Variables de tienda, veterinarias y Facebook](#20-variables-de-tienda-veterinarias-y-facebook)

> Todos los comandos de producción se corren en el servidor, desde la carpeta del repositorio
> (p. ej. `/opt/patitasfind`). El backend no tiene `container_name` (se puede escalar), así que los
> comandos van con `docker compose -f docker-compose.production.yml exec backend ...`.

---

## 1. Lista de lanzamiento

Marca cada punto antes de abrir GuauWoow al público.

**Infraestructura**
- [ ] Servidor de 4 vCPU / 8 GB / 80 GB SSD o más, Ubuntu 24.04 LTS, Docker Engine y Compose v2 ([§2](#2-servidor)).
- [ ] Firewall: solo 22 (SSH con llave), 80 y 443 abiertos ([`docs/operacion.md`](docs/operacion.md)).
- [ ] DNS de `DOMAIN` y `www.DOMAIN` apuntando al servidor ([§3](#3-dominio-y-dns)).

**Credenciales en `.env`** ([§4](#4-credenciales-y-dónde-obtenerlas))
- [ ] `DOMAIN`, `SECRET_KEY` (≥ 32 caracteres), `POSTGRES_PASSWORD`.
- [ ] `BACKUP_ENCRYPTION_PASSWORD` y `BACKUP_ENCRYPTION_SALT`, guardadas también en un gestor de contraseñas.
- [ ] `PRIVATE_FILES_KEY` (`openssl rand -base64 32`), guardada también fuera del servidor: cifra INE, actas,
  cédulas, constancias fiscales y datos fiscales. **Sin ella el backend no arranca en producción.**
- [ ] Reglas de negocio decididas con tu contador y abogado: comisiones en 0 y `PLATFORM_TAX_REGIME_READY=false`
  hasta confirmar el régimen de plataformas; `FB_GROUPS_ENABLED=false` hasta tener opinión legal escrita
  (`FB_GROUPS_LEGAL_OPINION_REF`); topes `DONATION_MAX_MXN` / `DONATION_DAILY_MAX_MXN`; `FOUND_DOG_HOLD_DAYS`.
- [ ] Contacto 24/7 para autoridades (`AUTHORITY_CONTACT_EMAIL`, `AUTHORITY_CONTACT_PHONE`) y datos del operador
  en el comprobante de compra (`OPERATOR_ADDRESS`, `OPERATOR_PHONE`, `EMISOR_NOMBRE`, `EMISOR_RFC`).
- [ ] SMS: `SMSMASIVOS_API_KEY` (o `TWILIO_*`). **Sin SMS el backend no arranca en producción.**
- [ ] SMTP: `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, con SPF, DKIM y DMARC ([§5](#5-correo-spf-dkim-y-dmarc)).
- [ ] Mercado Pago: `MERCADOPAGO_ACCESS_TOKEN` + `MERCADOPAGO_WEBHOOK_SECRET` y webhook registrado ([§6](#6-mercado-pago-y-su-webhook)).
- [ ] Decidir la tienda: `SHOP_ENABLED` vacío = apagada en producción (los donativos funcionan igual).
  Con `SHOP_ENABLED=true`: aplicación *Marketplace* de Mercado Pago (`MERCADOPAGO_APP_ID`,
  `MERCADOPAGO_CLIENT_SECRET`, URL de redireccionamiento registrada), comisión decidida y PAC para los CFDI
  de la plataforma ([§6.1](#61-tienda-mercado-pago-marketplace-split-sin-custodia-de-fondos), [§6.2](#62-facturación-cfdi-y-pac)).
- [ ] Opcional: `GOOGLE_MAPS_API_KEY` para las reseñas de Google en veterinarias ([§18](#18-veterinarias-llave-de-google-maps-places-api-new))
  y `APIFY_TOKEN` para leer grupos públicos de Facebook, solo con visto bueno legal ([§19](#19-grupos-públicos-de-facebook-apify-y-voluntarios)).
- [ ] `SUPPORT_EMAIL` y `SUPPORT_WHATSAPP` (se muestran en *Perfil → Ayuda*).
- [ ] Opcionales: Google OAuth ([§8](#8-google-oauth-continuar-con-google)), `AI_API_KEY`, WhatsApp con plantillas aprobadas ([§7](#7-whatsapp-webhook-y-plantillas)), Sentry, PostHog.
- [ ] Copia externa de respaldos en Cloudflare R2 (`BACKUP_S3_*`) y avisos en healthchecks.io (`BACKUP_HEARTBEAT_URL`, `BACKUP_OFFSITE_HEARTBEAT_URL`, `DISK_ALERT_URL`).

**Legal** ([§9](#9-textos-legales-llenar-generar-y-verificar))
- [ ] Datos legales en `app/legal/datos-legales.json` siguiendo [`docs/legal/LLENAR-DATOS.md`](docs/legal/LLENAR-DATOS.md)
  (razón social, RFC, domicilio, correos, plazos, comisiones, `FECHA_DE_ENTRADA_EN_VIGOR`...).
- [ ] Notas `[VERIFICAR: ...]` revisadas con tu abogado y contador.
- [ ] `python3 scripts/render-legal.py --check` termina sin errores (también compara comisiones, topes de
  donativos, plazos y `DOMAIN` con el `.env`).

**Despliegue y pruebas**
- [ ] Certificado HTTPS emitido y `backend/scripts/deploy.sh` corrido sin errores ([§10](#10-primer-despliegue)).
- [ ] Administrador creado y con verificación en dos pasos activada; un segundo superadmin de respaldo
  ([§11](#11-crear-el-administrador)). Al menos dos personas con rol de moderación (una apelación la resuelve
  alguien distinto a quien decidió).
- [ ] Todas las [revisiones de §12](#12-revisiones-después-del-lanzamiento) en verde, incluido un simulacro de restauración.

---

## 2. Servidor

| Tamaño | Para qué alcanza | Ajustes en `.env` |
|--------|------------------|-------------------|
| **4 vCPU / 8 GB RAM / 80 GB SSD** (referencia) | ~5000 usuarios, picos de 300–800 simultáneos | Valores por defecto: `WEB_CONCURRENCY=4`, `CELERY_CONCURRENCY=4`, `PG_SHARED_BUFFERS=1GB`, `PG_EFFECTIVE_CACHE_SIZE=3GB`, `REDIS_MAXMEMORY=512mb` |
| 8 vCPU / 16 GB RAM / 160 GB SSD | Crecimiento o picos mayores | `WEB_CONCURRENCY=8`, `CELERY_CONCURRENCY=8`, `PG_SHARED_BUFFERS=4GB`, `PG_EFFECTIVE_CACHE_SIZE=10GB` y los límites de CPU/memoria comentados "8/16" en `docker-compose.production.yml` |

- Ubuntu 24.04 LTS (o Debian 12/13), con actualizaciones automáticas de seguridad (`unattended-upgrades`).
- Docker Engine y el plugin de Compose v2 desde el repositorio oficial de Docker (`docker compose version`).
- Disco: las fotos crecen con el uso (cada foto se guarda en máx. 1600 px más su miniatura) y los
  respaldos locales ocupan ~14 días de base más instantáneas incrementales de fotos. El servicio
  `backup` revisa el disco cada hora y avisa al pasar el 85 % (`DISK_ALERT_URL`).
- Zona horaria: los respaldos corren a las 3 h hora del centro de México (`TZ` del contenedor).
- **Firewall, SSH y endurecimiento del servidor:** sigue [`docs/operacion.md`](docs/operacion.md).
  Mínimo: abre solo 22/tcp (SSH con llave, sin contraseña ni root), 80/tcp y 443/tcp. PostgreSQL ya
  escucha solo en `127.0.0.1` y Redis no se expone. Ojo: Docker publica puertos por encima de `ufw`;
  no agregues `ports:` nuevos al compose sin revisarlo.

## 3. Dominio y DNS

1. Compra el dominio (p. ej. en Cloudflare Registrar, Namecheap o un registrador `.mx` como Akky).
2. Crea los registros (TTL 300 mientras pruebas):

   | Tipo | Nombre | Valor |
   |------|--------|-------|
   | A | `@` | IPv4 del servidor |
   | A | `www` | IPv4 del servidor |
   | AAAA | `@` y `www` | IPv6 del servidor (si tiene) |
   | CAA (opcional) | `@` | `0 issue "letsencrypt.org"` |

3. Más los registros de correo de la [§5](#5-correo-spf-dkim-y-dmarc).
4. **Con Cloudflare y el proxy activado (nube naranja):** en *SSL/TLS* elige *Full (strict)* y pon
   `NGINX_REAL_IP=cloudflare` en `.env` para que los límites por IP usen la IP real del cliente.
   Para emitir el primer certificado deja la nube **gris** (solo DNS) y actívala después.
5. Comprueba: `dig +short tu-dominio.mx` y `dig +short www.tu-dominio.mx` devuelven la IP del servidor.

## 4. Credenciales y dónde obtenerlas

Todo va en `.env` (copia de `.env.example`, que explica cada variable). Nunca subas `.env` al repositorio
(`.gitignore` ya lo excluye) y deja sus permisos en `600`.

| Qué | Variables | Dónde se obtiene | ¿Obligatoria? |
|-----|-----------|------------------|---------------|
| Dominio | `DOMAIN` (`PUBLIC_BASE_URL` y `CORS_ORIGINS` quedan vacías: salen de `https://$DOMAIN`) | Tu registrador | Sí |
| Clave de sesiones | `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` | Sí (≥ 32 caracteres) |
| Base de datos | `POSTGRES_PASSWORD` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` (sin `@ : / ?`) | Sí |
| Cifrado de respaldos | `BACKUP_ENCRYPTION_PASSWORD`, `BACKUP_ENCRYPTION_SALT` | Igual que arriba; **guárdalas fuera del servidor** | Sí (la sal, muy recomendada) |
| Cifrado de documentos privados | `PRIVATE_FILES_KEY` (al rotar: `PRIVATE_FILES_OLD_KEYS`) | `openssl rand -base64 32` (o `python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"`); **guárdala fuera del servidor** ([§11](#11-crear-el-administrador)) | Sí |
| Verificación en dos pasos | `MFA_REQUIRED_FOR_ADMINS` (vacía = obligatoria; en producción no acepta `false`), `MFA_ISSUER` | — | Ya activa |
| Reglas de negocio | `PLATFORM_TAX_REGIME_READY`, `DONATION_MAX_MXN`, `DONATION_DAILY_MAX_MXN`, `UMA_DAILY_MXN` (cada febrero), `DONATION_IDENTIFICATION_UMA`, `DONATION_NOTICE_UMA`, `FOUND_DOG_HOLD_DAYS`, `FB_GROUPS_ENABLED`, `FB_GROUPS_LEGAL_OPINION_REF` | Tu contador y tu abogado (deben coincidir con `datos-legales.json`; `render-legal.py --check` lo compara) | Valores por defecto seguros |
| Cumplimiento | `AUTHORITY_CONTACT_EMAIL`, `AUTHORITY_CONTACT_PHONE`, `OPERATOR_ADDRESS`, `OPERATOR_PHONE`, plazos `MODERATION_*`, `APPEAL_*`, `COPYRIGHT_*`, `COMPLAINT_*`, `EVIDENCE_*`, `LEGAL_*` | Tus canales y tu abogado (`.env.example` explica cada una) | Contacto de autoridades: sí |
| SMS de verificación | `SMS_PROVIDER=smsmasivos` + `SMSMASIVOS_API_KEY` | [app.smsmasivos.com.mx](https://app.smsmasivos.com.mx) → API (compra créditos) | Sí (o Twilio) |
| SMS alterno | `SMS_PROVIDER=twilio` + `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` o `TWILIO_MESSAGING_SERVICE_SID` | [console.twilio.com](https://console.twilio.com) (número con SMS a México) | — |
| Correo | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Tu proveedor SMTP: Amazon SES, Brevo, Mailgun, SendGrid, Zoho o Google Workspace ([§5](#5-correo-spf-dkim-y-dmarc)) | Sí |
| Pagos | `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_WEBHOOK_SECRET` | [Mercado Pago Developers](https://www.mercadopago.com.mx/developers/panel/app) ([§6](#6-mercado-pago-y-su-webhook)) | Para donativos y tienda |
| Tienda | `SHOP_ENABLED` | Decisión de negocio (vacío = apagada en producción; `true` exige Mercado Pago) | — |
| Tienda: cobro de cada refugio | `MERCADOPAGO_APP_ID`, `MERCADOPAGO_CLIENT_SECRET` (+ `MERCADOPAGO_MARKETPLACE_FEE_PERCENT`, `MERCADOPAGO_DONATION_FEE_PERCENT`) | La misma aplicación de [Mercado Pago Developers](https://www.mercadopago.com.mx/developers/panel/app), modelo *Marketplace*: *Client ID* y *Client Secret*, y la URL de redireccionamiento `https://tu-dominio.mx/payments/mercadopago/oauth/callback` ([§6.1](#61-tienda-mercado-pago-marketplace-split-sin-custodia-de-fondos)) | Sí, si `SHOP_ENABLED=true` |
| CFDI de la plataforma | `PAC_PROVIDER=facturama`, `PAC_USER`, `PAC_PASSWORD`, `PAC_SANDBOX`, `EMISOR_RFC`, `EMISOR_NOMBRE`, `EMISOR_REGIMEN`, `EMISOR_CP` | Cuenta de API de [Facturama](https://facturama.mx) (sandbox: `apisandbox.facturama.mx`), CSD del emisor cargado ahí y tu Constancia de Situación Fiscal ([§6.2](#62-facturación-cfdi-y-pac)) | No (sin PAC los CFDI quedan pendientes) |
| Veterinarias: reseñas de Google | `GOOGLE_MAPS_API_KEY` (+ `GOOGLE_PLACES_DAILY_LIMIT`) | [Google Cloud Console](https://console.cloud.google.com/google/maps-apis/credentials) con *Places API (New)* habilitada ([§18](#18-veterinarias-llave-de-google-maps-places-api-new)) | No |
| Grupos públicos de Facebook | `APIFY_TOKEN` (+ `FB_GROUPS_*`) | [console.apify.com](https://console.apify.com/settings/integrations) → *Personal API tokens* ([§19](#19-grupos-públicos-de-facebook-apify-y-voluntarios)) | No (requiere visto bueno legal) |
| Soporte | `SUPPORT_EMAIL`, `SUPPORT_WHATSAPP` | Tus canales de atención | Recomendada |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) ([§8](#8-google-oauth-continuar-con-google)) | No |
| IA de fotos | `AI_API_KEY` (+ `AI_BASE_URL`, `AI_MODEL`) | [Alibaba Model Studio](https://modelstudio.console.alibabacloud.com) (región internacional) o [Z.ai](https://z.ai/manage-apikey/apikey-list) | No |
| WhatsApp | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_TEMPLATE_MATCH`, `WHATSAPP_TEMPLATE_NEARBY` | [developers.facebook.com/apps](https://developers.facebook.com/apps) + WhatsApp Manager ([§7](#7-whatsapp-webhook-y-plantillas)) | No |
| Facebook Pages | `FACEBOOK_PAGE_ACCESS_TOKEN` | [Graph API Explorer](https://developers.facebook.com/tools/explorer) | No |
| Errores | `SENTRY_DSN`, `SENTRY_DSN_FRONTEND` | [sentry.io](https://sentry.io) → proyecto Python (FastAPI) y proyecto Browser JavaScript → *Client Keys (DSN)* | Recomendada |
| Analítica | `POSTHOG_KEY` (`POSTHOG_HOST`) | [posthog.com](https://posthog.com) → *Project settings*; activa "Discard client IP data" | No |
| Copia externa | `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | Cloudflare → R2 → crear bucket → *Manage API tokens* (Object Read & Write, solo ese bucket); endpoint `https://<account_id>.r2.cloudflarestorage.com` | Muy recomendada |
| Avisos de respaldo y disco | `BACKUP_HEARTBEAT_URL`, `BACKUP_OFFSITE_HEARTBEAT_URL`, `DISK_ALERT_URL` | [healthchecks.io](https://healthchecks.io): un check por URL (respaldo: periodo 1 día, gracia 2 h; disco: 1 h / 1 h) | Muy recomendada |
| Datos legales | `app/legal/datos-legales.json` | Tu constancia de situación fiscal (SAT), tu abogado y tu contador ([§9](#9-textos-legales-llenar-generar-y-verificar)) | Sí |

Si falta algo obligatorio, el backend **no arranca** y `docker compose -f docker-compose.production.yml logs backend`
muestra en un solo mensaje la lista completa de problemas (la lista de validaciones está al inicio de `.env.example`).

## 5. Correo: SPF, DKIM y DMARC

GuauWoow envía correos de verificación de cuenta, de "olvidé mi contraseña" y alertas. Sin estos
registros los correos llegan a spam o se rechazan (Gmail y Outlook los exigen).

1. En tu proveedor SMTP **verifica el dominio** de `SMTP_FROM` (p. ej. `no-reply@guauwoow.com`).
2. **SPF** (un solo registro TXT en `@`; junta todos los proveedores que envían por tu dominio):

   ```
   v=spf1 include:<el que indique tu proveedor> ~all
   ```
   Ejemplos: Amazon SES `include:amazonses.com`, Google Workspace `include:_spf.google.com`,
   Brevo `include:spf.brevo.com`, Mailgun `include:mailgun.org`.
3. **DKIM**: copia los registros (CNAME o TXT, p. ej. `xxxx._domainkey`) que te da el proveedor y espera
   a que aparezca como verificado.
4. **DMARC** (TXT en `_dmarc`): empieza en modo observación y endurécelo cuando los reportes salgan limpios
   (2 a 4 semanas):

   ```
   v=DMARC1; p=none; rua=mailto:dmarc@tu-dominio.mx; adkim=s; aspf=s
   # después: p=quarantine  y finalmente  p=reject
   ```
5. Opcional: dominio de rebote propio ("custom MAIL FROM" / "Return-Path") para alinear SPF.
6. Prueba: manda un correo de "olvidé mi contraseña" a la dirección que te da
   [mail-tester.com](https://www.mail-tester.com) y busca 9/10 o más.

Variables: `SMTP_PORT=587` + `SMTP_USE_TLS=true` (STARTTLS) o `SMTP_PORT=465` (SSL).

## 6. Mercado Pago y su webhook

1. En [Mercado Pago Developers](https://www.mercadopago.com.mx/developers/panel/app) crea una aplicación
   (*Pagos online → Checkout Pro*).
2. Copia el **Access Token de producción** en `MERCADOPAGO_ACCESS_TOKEN` (para probar antes, usa el de
   prueba con usuarios de prueba).
3. En la aplicación → **Webhooks → Configurar notificaciones**, modo productivo:
   - URL: `https://tu-dominio.mx/payments/mercadopago/webhook`
   - Evento: **Pagos** (`payment`)
   - Guarda y copia la **clave secreta** en `MERCADOPAGO_WEBHOOK_SECRET` (con ella se valida la firma
     `x-signature` de cada aviso; en producción el backend no arranca con token y sin secreto).
4. Usa *Simular notificación* y revisa `docker compose -f docker-compose.production.yml logs backend celery-worker`
   (debe responder 200; una firma inválida se rechaza).
5. Prueba real: un donativo de $10 MXN a un refugio aprobado; debe quedar *approved* en el panel admin.
   Reembólsalo desde Mercado Pago y verifica que el donativo cambie de estado.

La tienda solidaria arranca **apagada** en producción. Para abrirla: `SHOP_ENABLED=true` (exige Mercado
Pago y la aplicación Marketplace de [§6.1](#61-tienda-mercado-pago-marketplace-split-sin-custodia-de-fondos)),
decide comisiones, envío y facturación en los textos legales ([§9](#9-textos-legales-llenar-generar-y-verificar))
y vuelve a desplegar.

### 6.1 Tienda: Mercado Pago Marketplace (split, sin custodia de fondos)

GuauWoow opera como **comisionista**: cada refugio cobra con **su propia cuenta** de Mercado Pago y la
plataforma solo recibe su comisión. El dinero de las ventas nunca pasa por la cuenta de GuauWoow, así que
**no hay dispersiones ni pagos a refugios** (recomendación de `docs/legal/secciones/fiscal-tienda.json` y
`gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.json`).

1. En la misma aplicación de Mercado Pago Developers elige el modelo **Marketplace** y copia el *Client ID*
   en `MERCADOPAGO_APP_ID` y el *Client Secret* en `MERCADOPAGO_CLIENT_SECRET`.
2. Registra la URL de redireccionamiento **exacta**: `https://tu-dominio.mx/payments/mercadopago/oauth/callback`.
3. Decide `MERCADOPAGO_MARKETPLACE_FEE_PERCENT` (por defecto 10; la investigación recomienda 0 hasta tener el
   régimen fiscal de plataformas en orden) y `MERCADOPAGO_DONATION_FEE_PERCENT` (por defecto 0).
4. Cada refugio entra a *Mi tienda → Cobros → Conectar Mercado Pago*, autoriza en Mercado Pago y vuelve a
   la app (`/app/#mp=connected`). En producción también debe llenar *Mi tienda → Datos fiscales* (RFC,
   régimen, código postal y Constancia de Situación Fiscal).

Cómo funciona:
- Cada pago se crea con el token del refugio y `marketplace_fee` = comisión (+ retenciones de ISR/IVA si el
  vendedor es persona física, ver §6.2). Mercado Pago separa la comisión sola; el aviso llega al webhook de la
  plataforma, que consulta el pago con el token de la plataforma y, si no lo encuentra, con el del refugio.
- Los reembolsos (cancelación, devolución aprobada o *Admin → Pedidos → Reembolsar*) se hacen con el token del
  refugio; Mercado Pago devuelve también la parte proporcional de la comisión.
- Los tokens se guardan **cifrados con una llave derivada de `SECRET_KEY`** y se renuevan solos cada semana
  (duran 180 días). **Si cambias `SECRET_KEY`, todos los refugios deben volver a conectar Mercado Pago.**
- Refugio sin cuenta conectada: sus productos se ven pero no se pueden comprar ("Este refugio aún no activa
  cobros"), y lo mismo con sus donativos, salvo `DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT=true` (los cobra la
  cuenta de la plataforma, flujo anterior; en producción solo si lo defines y lo valida tu abogado).
- Pedidos: `pending_payment → paid → preparing → shipped → delivered → completed` (se completa solo 10 días
  después de entregado), cancelación antes del envío y devoluciones con los plazos de la LFPC (5 días hábiles
  por arrepentimiento, 60 días por defecto o no entrega). Cada cambio avisa al comprador en la app y por correo.
- Estados de cuenta mensuales: el refugio en *Mi tienda → Estado de cuenta* (con CSV) y los admins en
  *Admin → Estados de cuenta*.

### 6.2 Facturación: CFDI y PAC

- **Factura de la compra (Modelo B):** la emite el **refugio vendedor**. El comprador la pide desde su pedido
  ("¿Necesitas factura?"); el refugio la timbra con su propio PAC o el portal del SAT y sube el XML (y el PDF)
  en *Mi tienda → Facturas*. El backend valida el UUID, los RFC y el total.
- **CFDI de la plataforma:** el día 3 de cada mes (tarea `cfdi-monthly`) GuauWoow genera, por refugio con
  ventas del mes anterior, el CFDI de ingreso por su comisión (IVA 16 %) y, si el refugio es persona física, el
  CFDI de retenciones (`RETENCION_ISR_PERCENT`, `RETENCION_IVA_PERCENT`). Se timbran con Facturama
  (`PAC_PROVIDER=facturama`, `PAC_USER`, `PAC_PASSWORD`, `PAC_SANDBOX=true` para pruebas) y los datos del
  emisor `EMISOR_RFC`, `EMISOR_NOMBRE`, `EMISOR_REGIMEN`, `EMISOR_CP`. Antes sube el CSD del emisor a Facturama.
- Sin PAC configurado los CFDI quedan **"pendiente de PAC"** y no se envía nada. En *Admin → CFDI* se
  generan los de un periodo, se reintentan los fallidos y se descargan XML y PDF.
- Pendiente de tu contador: tasas de retención vigentes, si aplican a personas morales
  (`RETENCION_PERSONAS_MORALES`) y las claves SAT de `backend/app/services/invoicing.py` (marcadas "confirmar"),
  probadas primero en el sandbox.

## 7. WhatsApp: webhook y plantillas

1. En [developers.facebook.com/apps](https://developers.facebook.com/apps) crea una app de tipo *Business*
   y agrega el producto **WhatsApp**; registra y verifica tu número.
2. Copia a `.env`:
   - `WHATSAPP_PHONE_NUMBER_ID`: *WhatsApp → Configuración de la API → Identificador del número de teléfono*.
   - `WHATSAPP_ACCESS_TOKEN`: token **permanente** de un usuario del sistema (*Business Settings →
     Usuarios del sistema → Generar token* con `whatsapp_business_messaging` y `whatsapp_business_management`).
   - `WHATSAPP_APP_SECRET`: *Configuración de la app → Básica → Clave secreta de la app*.
   - `WHATSAPP_VERIFY_TOKEN`: invéntalo largo (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).
3. **Webhook**: *WhatsApp → Configuración* → URL `https://tu-dominio.mx/whatsapp/webhook`, token de
   verificación = `WHATSAPP_VERIFY_TOKEN`, suscríbete al campo `messages`.
4. **Plantillas** (WhatsApp Manager → *Plantillas de mensajes* → *Crear*): fuera de la ventana de 24 h
   desde el último mensaje de la persona, Meta solo permite plantillas aprobadas. Crea estas dos, categoría
   **Utilidad (UTILITY)**, idioma **Español (MEX)** (`WHATSAPP_TEMPLATE_LANGUAGE=es_MX`), y pon su nombre
   exacto en `.env`. El backend manda las variables en este orden:

   **`WHATSAPP_TEMPLATE_MATCH`** — nombre sugerido `posible_coincidencia`
   (`{{1}}` = nombre del perrito y número de reporte, p. ej. "Firulais (reporte #12)"; `{{2}}` = enlace)

   ```
   GuauWoow encontró una posible coincidencia para {{1}}: alguien reportó un perrito que se parece.
   Revisa las fotos aquí: {{2}}
   Confirma señas particulares antes de reunirte y nunca pagues por adelantado.
   ```

   **`WHATSAPP_TEMPLATE_NEARBY`** — nombre sugerido `alerta_perrito_cerca`
   (`{{1}}` = resumen, p. ej. "se perdió Luna a 1.2 km de ti (Coyoacán)" o "encontraron un perrito a 0.8 km
   de ti (Roma Norte)"; `{{2}}` = enlace al reporte)

   ```
   Aviso de GuauWoow: {{1}}. Mira las fotos y ayuda a que vuelva a casa: {{2}}
   Recibes esta alerta porque la tienes activada; puedes apagarla en tu perfil de GuauWoow o responder BAJA.
   ```

   Al registrarlas, Meta pide un ejemplo de cada variable: usa los de arriba. Mientras no estén aprobadas,
   deja las variables vacías: esos avisos se envían solo en la app y por correo.
5. Prueba: escribe "hola" al número desde tu celular; debe llegar el menú del bot. "BAJA" o "STOP" da de
   baja el número y "HOLA" lo reactiva.

## 8. Google OAuth ("Continuar con Google")

1. https://console.cloud.google.com → crea (o elige) un proyecto.
2. **APIs y servicios → Pantalla de consentimiento de OAuth** (Google Auth Platform → Branding):
   tipo *Externo*; nombre "GuauWoow", correo de soporte, logo opcional; dominio autorizado
   `tu-dominio.mx`; enlaces a `https://tu-dominio.mx/app/legal/privacidad.html` y términos.
   Alcances: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (no requieren
   verificación de Google). Mientras esté en modo *Prueba*, agrega tus correos como usuarios de
   prueba; luego pulsa *Publicar app*.
3. **Credenciales → Crear credenciales → ID de cliente de OAuth → Aplicación web**:
   - Orígenes de JavaScript autorizados: `http://localhost:8082` y `https://tu-dominio.mx`
   - URI de redireccionamiento autorizados: `http://localhost:8082/auth/google/callback` y
     `https://tu-dominio.mx/auth/google/callback`
4. Copia el ID y el secreto a `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` y vuelve a desplegar.

Flujo: `/auth/google/login` firma un `state` (10 min) y deja una cookie HttpOnly con su nonce;
`/auth/google/callback` valida firma, vigencia y cookie (protección CSRF), exige `email_verified` y entra a
la cuenta con el mismo correo (la vincula) o crea una nueva, con el correo ya verificado. El éxito redirige
a `/app/#token=<jwt>` (en el fragmento, que no llega a los logs del servidor); los errores a
`/app/?auth_error=<mensaje>`. Las cuentas de Google nuevas deben agregar y verificar su teléfono antes de publicar.

## 9. Textos legales: llenar, generar y verificar

El centro legal (`/app/legal/`, atajos `/legal` y `/legal/<página>`) son **55 páginas que se generan** desde
plantillas: Términos, Aviso de Privacidad, cookies, moderación, derechos ARCO, transparencia, conservación,
estado del servicio, anexos para Refugios, vendedores, clínicas y casas de paso, etc. No edites a mano
`app/legal/*.html`, `aviso-simplificado.txt`, `versiones.json` ni `app/.well-known/security.txt`.

**La guía completa, paso a paso y con cada clave explicada, está en
[`docs/legal/LLENAR-DATOS.md`](docs/legal/LLENAR-DATOS.md).** Resumen:

| Archivo | Para qué |
|---------|----------|
| `app/legal/plantillas/*.html` (+ `_parciales/`, `security.txt`, `aviso-simplificado.txt`) | Textos fuente (lo que revisa tu abogado). Marcadores `<span class="ph">[RAZÓN SOCIAL]</span>` |
| `app/legal/datos-legales.example.json` | Documenta **cada clave** (287): grupo, qué es y un ejemplo |
| `app/legal/datos-legales.json` | Tus valores reales. Se sube al repo: todo es información pública de las páginas legales |
| `scripts/render-legal.py` | Genera las páginas (solo Python 3, sin dependencias) |
| `app/legal/versiones.json` → `backend/app/data/versiones-legales.json` | Registro de versiones con su SHA-256; el backend lo copia a la tabla `legal_documents` |

```bash
python3 scripts/render-legal.py --init      # crea/completa datos-legales.json con todas las claves
# llena app/legal/datos-legales.json siguiendo docs/legal/LLENAR-DATOS.md
python3 scripts/render-legal.py             # genera las 55 páginas, security.txt, versiones.json, sitemap e index.html
python3 scripts/render-legal.py --check     # exit 1 y lista lo que falta mientras quede algún marcador o nota
git add app/legal app/.well-known app/sitemap.xml app/index.html backend/app/data/versiones-legales.json \
        docs/legal/LLENAR-DATOS.md && git commit -m "Datos legales"
```

- Lo que no llenes se queda **resaltado** en la página (borde punteado), nunca en blanco.
- Las claves `VERIFICAR_*` son notas para tu abogado, contador o equipo técnico. Pon `true` cuando confirmen la
  cláusula tal cual (la nota desaparece) o escribe el texto que la sustituye.
- **Versiones y aceptación.** La versión vigente de Términos y Privacidad (`2026-10-17`) debe coincidir con
  `LEGAL_TERMS_VERSION` / `LEGAL_PRIVACY_VERSION` de `backend/app/config.py`; `--check` lo verifica. Cada aceptación
  (registro, reaceptación, compra, donativo, anexos de aliados) queda en una bitácora de solo inserción con la
  versión y el SHA-256 de la página. Si publicas una versión nueva de un documento que pide reaceptación, pon
  `FECHA_DE_ENTRADA_EN_VIGOR` (`AAAA-MM-DD`) **al menos 30 días después** (`LEGAL_NOTICE_DAYS`): el aviso previo
  sale por correo y en la app, y al entrar en vigor la app pide aceptar. La versión anterior queda archivada en
  `/app/legal/<página>-<versión>.html` y en `historial.html`.
- **Registro en el backend.** `python -m app.cli sync-legal-docs` copia `versiones.json` a la base (idempotente);
  `deploy.sh` lo corre después de las migraciones y el backend también lo hace al arrancar si el archivo cambió.
- `--check` también compara con el `.env` del servidor: `COMISION_TIENDA` / `COMISION_DONATIVOS` con
  `MERCADOPAGO_*_FEE_PERCENT`, los topes de donativos con `DONATION_*_MAX_MXN`, `PLAZO_DE_RESGUARDO_...` con
  `FOUND_DOG_HOLD_DAYS`, los plazos de respaldo con `BACKUP_*_RETENTION_DAYS` y `DOMINIO` con `DOMAIN`, y falla
  30 días antes de que caduque `Expires` de `security.txt` (renuévalo en `app/legal/plantillas/security.txt`).
- Mantén iguales `CORREO_DE_CONTACTO` y `SUPPORT_EMAIL`, `CONTACTO_24_7_PARA_AUTORIDADES` y
  `AUTHORITY_CONTACT_EMAIL`/`AUTHORITY_CONTACT_PHONE`, y los plazos de quejas (`PLAZO_DE_PRIMERA_RESPUESTA`,
  `PLAZO_DE_RESPUESTA_A_QUEJAS`) con `COMPLAINT_FIRST_RESPONSE_BUSINESS_DAYS` / `COMPLAINT_RESPONSE_BUSINESS_DAYS`.
- `backend/scripts/deploy.sh` corre `--check` y **se niega a desplegar a producción** si falla. Solo para
  una emergencia existe `--allow-legal-placeholders`, que despliega mostrando una advertencia grande:
  no lo uses para abrir al público. En CI, `legal-generated` exige que las páginas estén al día con sus
  plantillas; `legal-check` avisa sin bloquear en ramas y **bloquea al publicar una etiqueta `v*`**.

## 10. Primer despliegue

```bash
# 0. Código y configuración
sudo mkdir -p /opt/patitasfind && sudo chown "$USER" /opt/patitasfind
git clone <url-del-repositorio> /opt/patitasfind && cd /opt/patitasfind
cp .env.example .env && chmod 600 .env       # y llénalo (§4)

# 1. Textos legales completos (§9)
python3 scripts/render-legal.py --check

# 2. Primer arranque en http-only (Nginx sirve /.well-known/acme-challenge/ para Let's Encrypt)
NGINX_MODE=http-only docker compose -f docker-compose.production.yml up -d --build

# 3. Certificado (webroot servido por Nginx)
docker compose -f docker-compose.production.yml run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot -d tu-dominio.mx -d www.tu-dominio.mx \
  --email tu@correo.mx --agree-tos --no-eff-email

# 4. Despliegue completo en HTTPS: construye la imagen con el sha del commit, migra la base,
#    cambia los contenedores sin cortar el servicio y verifica /health
./backend/scripts/deploy.sh
curl -fsS https://tu-dominio.mx/health
```

- `deploy.sh` revisa los textos legales (§9), construye `patitasfind-backend:<sha>` (con `GIT_SHA`
  adentro: Sentry lo usa como *release* `patitasfind@<sha>`), aplica las migraciones de Alembic, sincroniza el
  registro de versiones legales (`sync-legal-docs`), cifra los documentos privados que sigan en claro
  (`encrypt-private-files`, idempotente) y actualiza los servicios. Detalles, opciones y cómo revertir: [`docs/operacion.md`](docs/operacion.md).
- `certbot` intenta renovar cada 12 h y Nginx recarga su configuración cada 12 h.
- Nginx: TLS 1.2/1.3, HSTS, CSP, `X-Frame-Options: DENY`, límites por IP (login/registro, SMS, API) y
  nunca sirve archivos de desarrollo (`*.py`, `*.mjs`, `node_modules/`, `test-*`...) ni `/uploads/private/`.
- Si actualizas una instalación anterior con documentos de refugios en `/uploads/`, muévelos a la
  carpeta privada una sola vez:
  `docker compose -f docker-compose.production.yml exec backend python -m app.cli move-private-docs`.

## 11. Crear el administrador

```bash
docker compose -f docker-compose.production.yml exec backend \
  python -m app.cli create-admin tu@correo.mx 'UnaContraseñaLargaYÚnica' --name "Tu Nombre"
```

Entra a `https://tu-dominio.mx/admin/`. Las sesiones de administración duran 8 horas
(`ADMIN_TOKEN_EXPIRE_MINUTES`) y cada acción de moderación queda en la bitácora. Usa un correo
propio (no compartido) y crea un segundo superadmin de respaldo.

**Verificación en dos pasos (obligatoria en producción).** En el primer inicio de sesión el panel muestra un
código QR: escanéalo con tu app de autenticación (Google Authenticator, Microsoft Authenticator, 1Password…),
escribe el primer código y guarda los 10 códigos de recuperación. Si alguien pierde su teléfono, otro superadmin
la restablece en *Seguridad*; si no hay otro, desde el servidor:
`docker compose -f docker-compose.production.yml exec backend python -m app.cli reset-mfa tu@correo.mx`.

**Cifrado de documentos privados.** `PRIVATE_FILES_KEY` es obligatoria (genérala en el servidor con
`openssl rand -base64 32`, o con `python -m app.cli generate-private-key` en un contenedor de desarrollo);
guárdala también fuera del servidor: sin ella no se pueden leer las
identificaciones, actas, cédulas, constancias fiscales y CFDI ni los datos fiscales de la base. Si migras desde una
versión anterior, cifra lo que ya existía con `python -m app.cli encrypt-private-files`. La purga diaria de la tabla
de conservación (`/cumplimiento/conservacion`) se revisa en *Seguridad* del panel; un incidente abierto con
«congelar purgas» la pausa.

**Nunca** corras `seed_data.py` en el servidor: se niega con `ENVIRONMENT=production`, pero tampoco tiene
nada que hacer ahí.

## 12. Revisiones después del lanzamiento

```bash
D=https://tu-dominio.mx
F="docker compose -f docker-compose.production.yml"

curl -fsS $D/health                                    # base de datos y Redis OK
curl -s $D/auth/config | python3 -m json.tool          # environment=production, demo_enabled=false,
                                                       # otp_enabled, payments_enabled, shop_enabled...
curl -sI $D/ | grep -iE 'strict-transport|content-security'   # HSTS y CSP presentes
curl -s -o /dev/null -w '%{http_code}\n' $D/uploads/private/x.pdf   # 403/404: documentos privados
curl -s -o /dev/null -w '%{http_code}\n' $D/app/server.py           # 404: archivos de desarrollo
curl -s $D/robots.txt | head -3                        # sin %%SITE_URL%% (Nginx lo reemplaza)
curl -s $D/app/legal/terminos.html | grep -c 'class="ph"'          # 0: sin marcadores legales
$F ps                                                  # todos healthy
```

En la app, con tu celular:
- [ ] Registro con tu teléfono real: llega el SMS y llega el correo de verificación (no en spam).
- [ ] "Olvidé mi contraseña" funciona; al cambiarla, las sesiones anteriores se cierran.
- [ ] Publicar un perrito con foto (se ven miniaturas en las listas) y un reporte de perdido: con una
  segunda cuenta cercana y alertas activadas llega la alerta.
- [ ] Botón "Reportar" en una publicación; el reporte aparece en *Admin → Reportes*.
- [ ] Donativo real de prueba con Mercado Pago (y reembolso) ([§6](#6-mercado-pago-y-su-webhook)).
- [ ] Si abriste la tienda: un refugio de prueba conecta Mercado Pago (*Mi tienda → Cobros*), compras un
  producto barato, el refugio lo marca como enviado con guía y lo reembolsas desde *Admin → Pedidos*
  ([§6.1](#61-tienda-mercado-pago-marketplace-split-sin-custodia-de-fondos)).
- [ ] Veterinarias: registra una clínica de prueba, verifícala en *Admin → Veterinarias* y, con
  `GOOGLE_MAPS_API_KEY`, vincula su ficha de Google y revisa el bloque "Reseñas en Google Maps" ([§18](#18-veterinarias-llave-de-google-maps-places-api-new)).
- [ ] WhatsApp: "hola" al bot responde el menú ([§7](#7-whatsapp-webhook-y-plantillas)).
- [ ] Sentry recibe un evento de prueba:
  `$F exec backend python -c "import sentry_sdk; from app.observability import init_sentry; init_sentry(); sentry_sdk.capture_message('Prueba de GuauWoow'); sentry_sdk.flush()"`
- [ ] Respaldo manual, copia externa y simulacro de restauración en una base aparte ([§14](#14-respaldos-y-restauración));
  los checks de healthchecks.io quedan en verde.
- [ ] Monitor de disponibilidad externo sobre `https://tu-dominio.mx/health` (cada 1–5 min) con aviso
  a tu correo o celular ([`docs/operacion.md`](docs/operacion.md)).
- [ ] Google Search Console: verifica el dominio y envía `https://tu-dominio.mx/sitemap.xml`.

## 13. Despliegues siguientes y reversa

```bash
cd /opt/patitasfind && ./backend/scripts/deploy.sh --pull     # git pull + revisión legal + build + dump
                                                              # cifrado + migrar + rolling update
./backend/scripts/rollback.sh --list                          # versiones desplegadas e imágenes
./backend/scripts/rollback.sh                                 # volver a la versión anterior
./backend/scripts/rollback.sh <tag|commit>                    # volver a una versión concreta
```

`rollback.sh` **no revierte migraciones**: las migraciones deben ser compatibles hacia atrás (agregar
columnas, no borrarlas en el mismo despliegue). Si una migración dañó datos, restaura antes el dump que
`deploy.sh` hace justo antes de migrar (`backups/db/`, [§14](#14-respaldos-y-restauración)). El detalle
(réplicas, `--with-infra`, ventanas de mantenimiento) está en [`docs/operacion.md`](docs/operacion.md).
Los cambios de esquema van siempre en revisiones de Alembic:

```bash
docker compose exec backend alembic revision --autogenerate -m "describe el cambio"   # en desarrollo
```

CI ejecuta `alembic check` y falla si `models.py` tiene cambios sin migración.

## 14. Respaldos y restauración

- **Diario** (servicio `backup`, 3 h): `pg_dump -Fc` **cifrado** (AES-256, PBKDF2) con
  `BACKUP_ENCRYPTION_PASSWORD` en `./backups/db/` (14 días) e instantáneas incrementales de las fotos
  en `./backups/uploads/<fecha>/`. Avisa a `BACKUP_HEARTBEAT_URL` y revisa el disco cada hora.
- **Copia externa** (servicio `backup-offsite`, 4 h): rclone *crypt* a Cloudflare R2/S3; contenido y
  nombres cifrados con `BACKUP_ENCRYPTION_PASSWORD` + `BACKUP_ENCRYPTION_SALT`; borrados conservados
  `BACKUP_OFFSITE_RETENTION_DAYS` (30). Sin `BACKUP_S3_BUCKET` queda inactiva y el respaldo lo advierte.
- **Sin la contraseña (y la sal) no hay restauración posible**: guárdalas en un gestor de contraseñas
  fuera del servidor.

```bash
F="docker compose -f docker-compose.production.yml"
$F exec backup sh /scripts/backup.sh                       # respaldo manual inmediato
$F exec backup-offsite sh /scripts/backup-offsite.sh once  # copia externa inmediata
ls -lt backups/db | head                                   # últimos dumps (.dump.enc)

# Simulacro mensual sin tocar producción (restaura en otra base y la borra)
$F run --rm -e PGDATABASE=patitasfind_restore_test -e RESTORE_CREATE_DB=1 -e RESTORE_YES=1 \
  --entrypoint sh backup /scripts/restore.sh /backups/db/db-AAAAMMDD-HHMMSS.dump.enc
$F exec postgres dropdb -U patitasfind patitasfind_restore_test

# Restauración real (base + fotos)
$F stop backend celery-worker celery-beat
$F run --rm -v "$PWD/backend/uploads:/uploads-rw" -e UPLOADS_DIR=/uploads-rw --entrypoint sh backup \
  /scripts/restore.sh /backups/db/db-AAAAMMDD-HHMMSS.dump.enc /backups/uploads/AAAAMMDD-HHMMSS
./backend/scripts/deploy.sh --no-build
```

`restore.sh` usa `pg_restore --clean --if-exists` en una sola transacción y mueve las fotos actuales a
`backend/uploads/.pre-restore-<fecha>/` antes de copiar las del respaldo. Restaurar desde la copia
externa: [`docs/operacion.md`](docs/operacion.md).

## 15. CI

`.github/workflows/ci.yml` (cada push y pull request):

| Job | Qué hace | ¿Bloquea? |
|-----|----------|-----------|
| `lint` | `ruff` solo con reglas críticas (`E9,F63,F7,F82`) y `pip-audit` sobre `backend/requirements.txt` (excepciones revisadas y comentadas en el workflow) | Sí |
| `backend-tests` | PostgreSQL + Redis, `python -m app.migrate`, `alembic upgrade head && alembic check`, `pytest -q`, migración idempotente | Sí |
| `frontend-syntax` | `node --check` de `app/*.js` y `app/legal/js/*.js` | Sí |
| `legal-generated` | `render-legal.py --check-generated` (las 55 páginas, `versiones.json`, `security.txt` y el sitemap al día con sus plantillas; enlaces, anclas y `js/*.js`) y `tests/test_render_legal.py` | Sí |
| `legal-check` | `render-legal.py --check` (datos legales y notas `VERIFICAR` pendientes) | Solo en etiquetas `v*` |
| `e2e` | Backend con uvicorn + `app/server.py` + datos de prueba, Playwright con Chromium (`node app/test-e2e.mjs`); sube capturas si falla | Sí |
| `docker-build` | Imagen del backend con `GIT_SHA`, `docker compose config` de ambos compose y `nginx -t` (modos `none` y `cloudflare`) | Sí |

## 16. Desarrollo local

```bash
# 1. (Opcional) variables propias
cp .env.example .env

# 2. PostgreSQL, Redis, backend (8001) y worker de Celery
docker compose up -d --build
#   Si el puerto 5433 ya está ocupado:  POSTGRES_HOST_PORT=5437 docker compose up -d --build
#   El backend aplica las migraciones de Alembic al arrancar (RUN_MIGRATIONS=true), igual que deploy.sh
#   en producción; la app ya no crea tablas por sí misma. A mano: docker compose exec backend python -m app.migrate

# 3. Datos de prueba (solo desarrollo) y administrador
docker compose exec -e SEED_PASSWORD='Patitas123!' backend python seed_data.py
#   --reset  borra los datos de prueba anteriores (perros, reportes, chats, pedidos...) y vuelve a sembrar
#   sin SEED_PASSWORD se genera una contraseña al azar y se imprime al final
docker compose exec backend python -m app.cli create-admin admin@guauwoow.com 'TuContraseñaSegura' --name "Admin"

# 4. Frontend + proxy de la API (incluye WebSocket del chat y Google OAuth)
cd app && python3 server.py          # http://localhost:8082  (/, /app/, /admin/)

# 5. Túnel público opcional
cloudflared tunnel --url http://localhost:8082
#   y pon esa URL en PUBLIC_BASE_URL para que los enlaces apunten ahí.

# 6. Pruebas
docker compose exec backend pytest -q
cd app && npm install && npx playwright install chromium && node test-e2e.mjs
#   con E2E_ADMIN_EMAIL y E2E_ADMIN_PASSWORD también corren los pasos del panel (veterinarias, Mi tienda)
```

- El worker de Celery (`patitasfind-celery-dev`, con Beat) **no se recarga solo**: después de cambiar tareas
  o servicios que usa, reinícialo con `docker compose restart celery-worker`. `app/server.py` tampoco se
  recarga: reinícialo si cambias su lista de rutas de la API.

- `seed_data.py` se niega a correr con `ENVIRONMENT=production`, se niega si `DATABASE_URL` no apunta a
  `localhost`/`postgres` (salvo `--force`, que nunca permite producción) y **no borra nada** sin `--reset`.
- API y documentación: http://localhost:8001/docs · Salud: http://localhost:8001/health
- Usuarios de prueba: `lucia@patitas.com`, `carlos@patitas.com`, … con la contraseña de `SEED_PASSWORD`
  (teléfonos ya verificados; Lucía, Carlos y Ana administran refugios aprobados).
- En `development`, sin llaves externas: login demo activo, el código SMS se devuelve como `dev_code`,
  los enlaces de correo como `dev_link`, los pagos se aprueban de forma simulada y la tienda está activa.

## 17. Referencia rápida de la API de cuenta

La referencia completa está en `/docs` (OpenAPI). Lo esencial de cuenta y privacidad:

| Endpoint | Cuerpo | Respuesta |
|----------|--------|-----------|
| `POST /auth/register` | `{email, password, full_name, phone, accepted_terms: true, marketing_opt_in?, city?, country?}` | `201 {access_token, token_type}`; envía el correo de verificación |
| `POST /auth/verify-email` | `{token}` | Marca el correo como verificado |
| `POST /auth/resend-verification` | — (con sesión) | Reenvía el correo (con límite) |
| `POST /auth/logout-all` | — (con sesión) | Invalida todas las sesiones (las anteriores reciben 401) |
| `POST /users/me/phone/send-code` | opcional `{phone}` | `{sent, phone, cooldown, dev_code?}` · 429 espera/límite · 503 sin proveedor |
| `POST /users/me/phone/verify` | `{code}` | `{verified: true}` · 400 incorrecto/vencido · 429 intentos |
| `POST /users/me/password` | `{current_password?, new_password}` | `{ok: true}`; cierra las demás sesiones |
| `PATCH /users/me` | `{full_name?, phone?, city?, notify_nearby?, marketing_opt_in?, ...}` | `User` |
| `GET /users/me/export` | — | JSON descargable con tus datos (acceso/portabilidad) |
| `DELETE /users/me` | `{confirm: "ELIMINAR", password?}` | `{ok: true}` (cancelación) |
| `POST /reports` | `{target_type, target_id, reason, details?}` | `201 {id, status: "open"}` (máx. 10 por hora) |

Las acciones de escritura exigen teléfono verificado (`403 {"code": "phone_verification_required"}`);
admins y el usuario demo están exentos. Los límites responden `429` con un `detail` en español.

**Cancelación de cuenta (LFPDPPP):** se anonimiza el perfil (correo `eliminado-<id>@patitasfind.invalid`,
nombre "Usuario eliminado", sin teléfono, foto, ubicación ni contraseña) y se desactiva; se ocultan sus
perros y reportes y se borran sus fotos; se borran sus respuestas de cuestionarios, recordatorios,
notificaciones e historial con el bot; si administra un refugio, se cierra y se borran sus documentos; si
registró una veterinaria, se oculta sin fotos ni datos de contacto y se borra su cédula; sus reseñas de
veterinarias se borran.
**Se conservan pedidos y donativos** sin datos que identifiquen a la persona (y sin domicilio de envío),
porque el Código Fiscal de la Federación (art. 30) obliga a guardar la contabilidad 5 años. Los mensajes
de chat se conservan para la otra persona, firmados como "Usuario eliminado".

## 18. Veterinarias: llave de Google Maps (Places API New)

El directorio de veterinarias funciona sin llaves externas: registro con cédula (privada, la revisan los
admins contra el Registro Nacional de Profesionistas en *Admin → Veterinarias*), mapa, horarios, "Abierto
ahora" y reseñas propias de GuauWoow. La llave de Google solo agrega el bloque "Reseñas en Google Maps".

1. En [Google Cloud Console](https://console.cloud.google.com/google/maps-apis/credentials) crea un proyecto
   con cuenta de facturación y habilita **Places API (New)** (no la "Places API" heredada).
2. Crea una llave de API con dos restricciones: de aplicación **Direcciones IP** (la IP pública del servidor;
   las consultas salen del backend, nunca del navegador) y de API **solo Places API (New)**.
3. Ponla en `GOOGLE_MAPS_API_KEY`, fija `GOOGLE_PLACES_DAILY_LIMIT` (vistas de perfil al día que consultan
   reseñas; cada una es una llamada de pago del SKU *Enterprise + Atmosphere*) y crea una alerta de presupuesto.
4. Cada clínica vincula su ficha desde *Mi veterinaria → Reseñas de Google Maps en tu perfil* (búsqueda y "Es mi clínica").

Políticas de Google que el código ya respeta: solo se guarda el `place_id` (las reseñas y la calificación se
piden en cada vista y nunca se guardan), se muestran hasta 5 reseñas sin cambios y en el orden de Google, con
el logo de Google Maps, el autor con enlace, "Reportar a Google" y "Ver todas las reseñas en Google Maps"; nada
de Google aparece sobre el mapa de OpenStreetMap. Una tarea semanal (`veterinaries-google-weekly`) revisa que
los `place_id` sigan existiendo y otra diaria (`veterinaries-verification-expiry-daily`) devuelve a revisión
las verificaciones de cédula con más de un año. La CSP ya permite las fotos de autor (`*.googleusercontent.com`).
Sin llave, el perfil se muestra sin el bloque de Google y la búsqueda de fichas responde 503 con un mensaje claro.

## 19. Grupos públicos de Facebook (Apify) y voluntarios

**Antes de activarlo, decide con tu abogado** si leer grupos públicos con un servicio externo es aceptable
(términos de Meta, LFPDPPP, derechos de autor de las fotos y contrato con Apify). Mientras tanto deja
`APIFY_TOKEN` vacío: el panel muestra "Proveedor no configurado (APIFY_TOKEN)" y las tareas no hacen nada.

1. Crea una cuenta en [Apify](https://console.apify.com) y un token en *Settings → Integrations → Personal API
   tokens*; ponlo en `APIFY_TOKEN`. El actor es `APIFY_FB_GROUPS_ACTOR` (por defecto `apify/facebook-groups-scraper`).
2. Ajusta `FB_GROUPS_COST_PER_1000_POSTS_USD` al precio real de tu plan (en el plan gratuito ronda 7 USD por
   1000 publicaciones; el valor por defecto, 3.0, lo subestima) y `FB_GROUPS_DAILY_BUDGET_USD` a lo que quieres
   gastar al día. El presupuesto se lleva en Redis y cada corrida le pide a Apify un tope de cobro.
3. Da de alta los grupos en *Admin → Facebook* (uno por uno o *Importar CSV* con columnas
   `name,state,city,group_url`). Solo grupos públicos que alguien del equipo revisó; la guía para encontrarlos
   por estado está en [`docs/facebook-grupos.md`](docs/facebook-grupos.md).

Cómo funciona: cuando alguien crea un reporte de perdido/encontrado en la app o por WhatsApp se encarga la
lectura de los grupos de su estado (como máximo cada `FB_GROUPS_FETCH_INTERVAL_HOURS`). De cada publicación se
quitan teléfonos, correos, @usuarios y enlaces antes de guardarla; las que hablan de un perrito se vuelven
reportes con fuente "facebook" y se buscan coincidencias. Los importados caducan a los `FB_GROUPS_POST_TTL_DAYS`
(tarea `facebook-groups-expire-daily`). Las solicitudes de retiro se atienden en menos de 72 horas
([`docs/facebook-grupos.md`](docs/facebook-grupos.md) §6).

**Voluntarios** (no necesita Apify): cualquier persona con teléfono verificado puede enviar una publicación
que vio en Facebook (máximo 10 al día; no se duplican enlaces). En computadora, con el botón que se arrastra
a la barra de marcadores desde *Perfil → Ayuda → Botón para voluntarios*; en Android, con la app instalada,
desde *Compartir → GuauWoow* (`share_target` de `manifest.webmanifest`); en iPhone, copiando el enlace en
*Ayuda → Enviar una publicación ahora*. Todo abre `/app/?share=1&url=...&text=...` con el formulario lleno.

## 20. Variables de tienda, veterinarias y Facebook

Todas están documentadas en `.env.example` y se pasan al backend y a Celery en ambos compose (`x-backend-env`).

| Variable | Por defecto | Para qué |
|----------|-------------|----------|
| `MERCADOPAGO_APP_ID`, `MERCADOPAGO_CLIENT_SECRET` | vacías | Aplicación Marketplace (OAuth de cada refugio). Obligatorias en producción con `SHOP_ENABLED=true` |
| `MERCADOPAGO_MARKETPLACE_FEE_PERCENT` | `10` | Comisión de GuauWoow por venta (% del total con IVA) |
| `MERCADOPAGO_DONATION_FEE_PERCENT` | `0` | Comisión sobre donativos |
| `DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT` | vacía (= `true` solo en development) | Cobrar donativos de refugios sin Mercado Pago con la cuenta de la plataforma |
| `RETURN_WINDOW_DAYS` | `5` | Días hábiles para devolver por arrepentimiento (LFPC art. 56) |
| `RETURN_CLAIM_WINDOW_DAYS` | `60` | Días para reclamar producto defectuoso, distinto o no entregado |
| `ORDER_AUTO_COMPLETE_DAYS` | `10` | Días tras la entrega para marcar el pedido como completado |
| `RETENCION_ISR_PERCENT`, `RETENCION_IVA_PERCENT` | `2.5`, `50` | Retenciones a vendedores personas físicas (confirmar con tu contador) |
| `RETENCION_PERSONAS_MORALES` | `false` | Retener también a personas morales |
| `PAC_PROVIDER`, `PAC_USER`, `PAC_PASSWORD`, `PAC_SANDBOX` | vacío, vacías, `true` | Timbrado de los CFDI de la plataforma (`facturama`) |
| `EMISOR_RFC`, `EMISOR_NOMBRE`, `EMISOR_REGIMEN`, `EMISOR_CP`, `CFDI_SERIE` | vacías, `PF` | Datos fiscales de quien opera GuauWoow |
| `GOOGLE_MAPS_API_KEY` | vacía | Reseñas de Google en veterinarias |
| `GOOGLE_PLACES_DAILY_LIMIT` | `200` | Vistas de perfil al día que consultan reseñas de Google |
| `VETERINARY_REVIEW_MIN_ACCOUNT_DAYS` | `0` | Antigüedad mínima de la cuenta para reseñar (la política propone 7) |
| `APIFY_TOKEN`, `APIFY_FB_GROUPS_ACTOR` | vacía, `apify/facebook-groups-scraper` | Lectura de grupos públicos de Facebook |
| `FB_GROUPS_FETCH_INTERVAL_HOURS`, `FB_GROUPS_LOOKBACK_DAYS`, `FB_GROUPS_MAX_POSTS_PER_RUN` | `12`, `14`, `100` | Frecuencia, ventana y tope por corrida |
| `FB_GROUPS_DAILY_BUDGET_USD`, `FB_GROUPS_COST_PER_1000_POSTS_USD` | `2.0`, `3.0` | Presupuesto diario y precio estimado del proveedor |
| `FB_GROUPS_POST_TTL_DAYS` | `30` | Días que un reporte importado sigue visible |

Tareas programadas nuevas (Celery Beat): `orders-auto-complete-daily`, `mercadopago-seller-tokens-weekly`,
`cfdi-monthly`, `veterinaries-google-weekly`, `veterinaries-verification-expiry-daily` y
`facebook-groups-expire-daily`. Las lecturas de grupos van a la cola `facebook` del worker.
