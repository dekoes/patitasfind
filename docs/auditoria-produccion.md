# Auditoría de producción: GuauWoow (2026-11-02)

Rama: `claude/auditoria-produccion`. Todo lo que dice «probado» tiene una prueba automática que se puede repetir. Las
correcciones de dinero también tienen una **contraprueba**: con el código anterior, la prueba falla.

## Veredicto

**El código ya se puede publicar; el negocio todavía no.**

- **Código:** el CI de GitHub está en verde por primera vez (los 5 runs anteriores fallaban). Se corrigieron 3 errores
  que duplicaban dinero o facturas.
- **Lo que falta para publicar:**
  - **77 datos legales sin llenar** en `app/legal/datos-legales.json`: razón social, domicilio fiscal, RFC, fecha de
    entrada en vigor, contacto de datos personales, etc.
  - **Más de 50 notas `VERIFICAR`** para tu abogado y tu contador.
  - `backend/scripts/deploy.sh` se niega a desplegar mientras falten, y es correcto que lo haga.
  - Esos datos no se pueden inventar. Mientras falten, publicar es una decisión tuya y queda registrada:
    `ALLOW_LEGAL_PLACEHOLDERS=1 ./desplegar-vps.sh`.

## Evidencia independiente

| Evidencia | Resultado |
|---|---|
| CI de GitHub (`.github/workflows/ci.yml`), run #6 | ✅ verde. Antes: lint ❌, backend-tests ❌, centro legal ❌ |
| Backend: `pytest` (Python 3.11, PostgreSQL 16, Redis 7) | 697/697 |
| `alembic check` y migración idempotente | sin cambios pendientes |
| `pip-audit` | 0 vulnerabilidades (antes 39, todas de Pillow) |
| E2E existente (`app/test-e2e.mjs`, Playwright) | 31/31 pasos |
| Recorrido de botones nuevo (`app/test-botones.mjs`) | 49 pantallas/secciones, 309 controles pulsados, **0 excepciones JS, 0 errores 5xx** |
| Pruebas de caos (`loadtest/caos.py`) | 18/18 escenarios con el comportamiento esperado (ver abajo) |

Lo que **no** se pudo comprobar desde aquí:
- **El servidor real (2.24.30.179 / guauwoow.com):** la red de este entorno está bloqueada y no hay llave SSH.
- **Mercado Pago, Facturama, Twilio y Google reales:** se usaron simuladores que se comportan como su documentación.

## Errores corregidos

### Altos: dinero y facturas

1. **Reembolso doble.**
   - **Qué pasaba:** cada intento de reembolso mandaba a Mercado Pago una `X-Idempotency-Key` aleatoria. Si Mercado
     Pago aplicaba el reembolso pero la respuesta no llegaba (timeout de 20 s) o el admin pulsaba dos veces, el
     comprador recibía el dinero dos veces.
   - **Arreglo:** clave estable por reembolso lógico (pedido + lo ya reembolsado + monto). Además, no se registra dos
     veces el mismo reembolso de Mercado Pago.
   - **Prueba:** `test_admin_refund_is_idempotent_after_timeout_and_double_click`. Con el código viejo, Mercado Pago
     devolvía **$200 por un reembolso de $100**.
2. **Cancelación y webhook registraban el reembolso dos veces.**
   - **Qué pasaba:** si el aviso «refunded» de Mercado Pago llegaba mientras la cancelación esperaba la respuesta,
     el pedido quedaba con el doble reembolsado. Eso afecta estados de cuenta y CFDI.
   - **Prueba:** `test_cancel_refund_racing_with_webhook_is_recorded_once`. Con el código viejo, un pedido de $300
     quedaba con **$600**.
3. **CFDI timbrado dos veces ante el SAT.**
   - **Qué pasaba:** si fallaba la descarga del XML o PDF después de timbrar, el registro quedaba en `error` **sin el
     UUID**, y el reintento (admin o tarea mensual) timbraba otro.
   - **Arreglo:**
     - Se conserva el UUID aunque falle la descarga.
     - Bloqueo de fila y estado `stamping` antes de llamar al PAC.
     - El panel no permite reintentar un CFDI que se quedó a mitad: hay que revisarlo primero en Facturama.
   - **Prueba:** ampliación de `test_cfdi_pending_without_pac_and_facturama_payload`.
4. **`desplegar-vps.sh`.**
   - **Qué pasaba:**
     - **Subía el `.env` de tu computadora encima del de producción.**
     - Desplegaba con `--skip-backup` (migraciones sin respaldo).
     - Extraía directo sobre la carpeta en línea: un corte de internet dejaba el sitio a medias.
     - Si se caía el SSH, el despliegue moría a la mitad.
     - Sin `.git` en el servidor, rollback no tenía versiones.
   - **Arreglo:**
     - Excluye `.env`, respaldos, certificados, fotos y `.deploy`.
     - Sube a una carpeta de espera.
     - Corre `deploy.sh` con `setsid nohup`.
     - Usa `DEPLOY_GIT_SHA`.
     - Hace respaldo previo.
   - **Probado:** con un servidor simulado.
     - El `.env` del servidor queda intacto.
     - Un corte a la mitad de la subida no cambia ni un byte de la versión en línea.
     - Un despliegue rechazado devuelve código 1 con el log completo.

### Medios

5. **Doble clic en botones de dinero del panel.** Reembolsar, Cancelar y Aceptar pago se desactivan mientras la
   petición está en curso.
6. **Doble clic en «Donar»** mientras el navegador va a Mercado Pago creaba otro donativo pendiente.
   - **Arreglo:** `withBtn` ignora el segundo clic en los 57 formularios de la app.
7. **PostgreSQL caído:**
   - **Antes:** la app recibía `Internal Server Error` en texto plano.
   - **Ahora:** 503 JSON con `Retry-After` y un mensaje legible.
   - **Prueba:** `test_caos.py`.
   - Además, `connect_timeout=5`: sin él, un servidor de base congelado colgaba cada hilo durante minutos.
8. **Webhook de Mercado Pago:** con Redis caído, el encolado bloqueaba el event loop, y con él todas las peticiones del
   worker. Ahora corre en un hilo.

### Bajos

9. Login del panel con 429 o 502 de Nginx: antes mostraba «Unexpected token '<'».
10. Solicitud de veterinarias sin red: antes mostraba «Failed to fetch» en inglés.
11. «Buscar» con una sola letra no hacía nada y no explicaba por qué.
12. La tarjeta «Pedidos pagados» del panel dejaba de contar los pedidos en preparación o enviados.

### CI

13. **Huellas de las versiones legales archivadas.** Ninguna versión había entrado en vigor
    (`effective_at: null`); el cambio de marca a GuauWoow las modificó.
14. **Pillow 12.3.0 → 13.0.0** (39 CVE).
15. Límite de 1.5 CPU documentado.
16. Dos pruebas desactualizadas:
    - el plazo de respaldos ya calculado;
    - la ruta de Celery con `USE_CELERY=false`.

## Pruebas de caos (`loadtest/caos.py`)

| Escenario | Resultado |
|---|---|
| Redis apagado: lectura, login, alta de reporte | ✅ funcionan degradados; `/health` = 503 y se recupera solo |
| PostgreSQL apagado | ✅ 503 JSON en ~10 ms, sin colgarse; reconecta solo al volver; la sesión sigue válida |
| `kill -9` al backend a mitad de una subida de foto | ✅ el cliente recibe error en <1 s; sin archivos a medias ni filas huérfanas; el reintento funciona |
| SIGTERM (despliegue) con una subida en curso | ✅ la subida termina (200 en 4 s) antes de apagarse |
| Corte de internet a mitad de `desplegar-vps.sh` | ✅ la versión en línea no cambia |
| Dos POST simultáneos de un reporte directo a la API | ⚠️ crea 2 reportes. La app ya lo impide con el bloqueo del botón; la API no deduplica |

## Riesgos que quedan (no se tocaron, con motivo)

- **Requieren a tu abogado o contador:** los 77 datos legales y las notas `VERIFICAR` (lista completa con
  `python3 scripts/render-legal.py --check`).
- **Avisos de Mercado Pago perdidos si Mercado Pago está caído más de unos 2.5 minutos.**
  - Pasa porque el webhook responde 200 y la tarea reintenta solo 5 veces.
  - Un contracargo hecho fuera de la app no llegaría a la base.
  - Requiere una tabla de entrada y una conciliación periódica: es un cambio de diseño.
- **Timeout en el POST de timbrado de Facturama.** Si la respuesta se pierde, no se sabe si se timbró. Facturama no
  ofrece idempotencia; se debe revisar manualmente en Facturama.
- **`deploy.sh` no tiene `trap`.** Si se interrumpe mientras las réplicas nuevas arrancan, pueden quedar en rotación.
  Con `setsid nohup` ya no lo interrumpe un corte de SSH, pero sí un `kill` manual.
- **Celery sin `REDIS_URL`:** el inventario apartado nunca expira. El compose lo define, así que solo pasa si se
  sobrescribe.
- **Aviso de cookies encima del modal de Términos** en un celular nuevo. No bloquea: al elegir una opción, el modal queda
  libre.

## Cómo repetirlo

```bash
cd backend && pytest -q                                   # 697 pruebas
python3 scripts/render-legal.py --check-generated         # centro legal
BASE=http://localhost:8082 node app/test-e2e.mjs          # E2E
E2E_PASSWORD=... E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... node app/test-botones.mjs
python loadtest/caos.py                                   # SOLO en un entorno local desechable
```
