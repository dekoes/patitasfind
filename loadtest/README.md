# Pruebas de carga de GuauWoow

Script: `loadtest/k6-patitasfind.js` ([k6](https://k6.io)). Simula el pico esperado de **800 usuarios
simultáneos** (de ~5000 registrados) contra **staging**, nunca contra producción con usuarios reales.

## Escenarios

| Escenario | Qué hace | Carga por defecto |
|---|---|---|
| `browse` | Portada: `GET /dogs/featured` y `GET /lost-reports` con lat/lon aleatorios de la CDMX, luego el detalle de un perro (`GET /dogs/{id}`), con pausas de 1–5 s como una persona real | sube a 200 VUs en 2 min, a 800 en 3 min, sostiene 5 min y baja |
| `chat` | Con sesión: `GET /conversations` y WebSocket `/ws/chat/{id}` mandando `{"type":"ping"}` cada 5 s (espera `{"type":"pong"}`) | 10 % de `TARGET_VUS` (80) |
| `photo_search` | `POST /search/by-photo` con una foto | 30 por minuto (opcional) |

Umbrales (la prueba falla si no se cumplen): p95 < 500 ms en `browse` y `chat`, p95 < 8 s en la búsqueda
por foto (incluye la IA), errores < 1 %, `pong` recibido > 99 % y su p95 < 500 ms.

## Antes de correrla

1. **Staging con la misma configuración que producción** (`docker-compose.production.yml`, 4 workers,
   Postgres con `max_connections=150`) y datos parecidos a los reales. Para llenar staging con datos
   sintéticos (5000 perros y 3000 reportes alrededor de la CDMX de un usuario `loadtest-owner@patitasfind.test`)
   puedes usar el SQL de la sección *Datos sintéticos*; bórralos al terminar.
2. **Una cuenta de carga** con el teléfono verificado y al menos una conversación (para el WebSocket):
   `LOADTEST_EMAIL` / `LOADTEST_PASSWORD`. Se inicia sesión una sola vez (en `setup`) y todos los VUs
   comparten el token, así que el límite de inicio de sesión no estorba.
3. **Límites por IP.** Nginx limita a 50 peticiones/s por IP (`zone=api`) y el backend limita la búsqueda
   por foto sin sesión a 5 por minuto por IP. Si toda la carga sale de una sola máquina, verás 429 en vez
   de medir el servidor. Opciones:
   - repartir la carga entre varias máquinas (k6 Cloud o varias instancias con `--execution-segment`), o
   - en **staging**, exentar temporalmente la IP del generador en Nginx (p. ej. `geo $limit_key` que deje
     la clave vacía para esa IP) y volver a dejarlo como estaba al terminar.
   En la búsqueda por foto un 429 cuenta como respuesta esperada (prueba que el límite funciona).
4. Avisa al equipo: la prueba genera alertas de monitoreo y llena los logs.

## Cómo correrla

Con k6 instalado (`brew install k6`):

```bash
k6 run \
  -e BASE_URL=https://staging.guauwoow.com \
  -e LOADTEST_EMAIL=carga@guauwoow.com -e LOADTEST_PASSWORD='...' \
  -e PHOTO=./perro.jpg \
  loadtest/k6-patitasfind.js
```

O con Docker (sin instalar nada):

```bash
docker run --rm -v "$PWD/loadtest:/scripts:ro" -v "$PWD/perro.jpg:/data/perro.jpg:ro" \
  -e BASE_URL=https://staging.guauwoow.com -e PHOTO=/data/perro.jpg \
  -e LOADTEST_EMAIL=carga@guauwoow.com -e LOADTEST_PASSWORD='...' \
  grafana/k6:0.54.0 run /scripts/k6-patitasfind.js
```

Variables:

| Variable | Default | Para qué |
|---|---|---|
| `BASE_URL` | `http://localhost:8001` | URL de la API (el WebSocket usa la misma con `ws://`/`wss://`) |
| `TARGET_VUS` | `800` | usuarios simultáneos en el pico de `browse` |
| `CHAT_VUS` | 10 % de `TARGET_VUS` | usuarios con chat abierto |
| `HOLD_MINUTES` | `5` | minutos sosteniendo el pico |
| `LOADTEST_EMAIL` / `LOADTEST_PASSWORD` | — | sin ellas no corre el escenario `chat` |
| `PHOTO` | — | ruta a un JPG; sin ella no corre `photo_search` |
| `PHOTO_RATE_PER_MIN` | `30` | búsquedas por foto por minuto |
| `SMOKE` | — | `SMOKE=1`: ~1 minuto con 10 VUs para validar el script antes de la prueba grande |

Empieza siempre con `SMOKE=1`, luego `TARGET_VUS=200` y al final 800.

## Qué mirar mientras corre

- `docker stats`: CPU y memoria del backend (límite de 1.5 CPU / 3 GB con `WEB_CONCURRENCY=4`, según
  `deploy.resources.limits` del servicio `backend` en `docker-compose.production.yml`) y de Postgres.
- Conexiones de Postgres: `SELECT count(*), state FROM pg_stat_activity GROUP BY state;` debe quedarse muy por
  debajo de 150 (cada worker de uvicorn usa como máximo `DB_POOL_SIZE + DB_MAX_OVERFLOW` = 10).
- Errores `QueuePool limit ... timed out` en los logs del backend: el pool se quedó corto para la carga
  (sube workers o `DB_POOL_SIZE` con cuidado de no rebasar `max_connections`).
- Redis: `redis-cli info stats | grep keyspace` (aciertos de la caché de la portada).
- Sentry: errores nuevos durante la prueba.

## Resultados de referencia (desarrollo local, 1 worker con `--reload`)

Medido con `ab -n 2000 -c 50` contra el backend de desarrollo con 5000 perros y 3000 reportes sintéticos:

| Endpoint | Antes | Después |
|---|---|---|
| `/dogs/featured?lat=19.43&lon=-99.13&limit=10` | 4.6 req/s, p50 10.9 s, p95 14.6 s (62 respuestas 500) | 637 req/s, p50 76 ms, p95 102 ms |
| `/lost-reports?lat=19.43&lon=-99.13` | 7.9 req/s, p50 6.0 s, p95 9.5 s | 480 req/s, p50 101 ms, p95 136 ms |
| `/dogs/nearby?...&radius_km=30&limit=10` (sin caché, distancia en SQL) | — | 324 req/s, p50 145 ms, p95 311 ms |

Antes se traían hasta 5000 filas a Python para calcular la distancia; ahora el filtro, el orden y la
paginación los hace Postgres, y la portada sin sesión se responde desde Redis (60 s).

## Datos sintéticos

```sql
-- Crear (staging): un usuario y 5000 perros + 3000 reportes alrededor de la CDMX
INSERT INTO users (email, full_name, role, is_active, created_at, phone_verified, phone_otp_attempts, marketing_opt_in)
VALUES ('loadtest-owner@patitasfind.test', 'LOADTEST-owner', 'user', TRUE, now(), FALSE, 0, FALSE);
INSERT INTO dogs (owner_id, name, status, photos, city, country, latitude, longitude, created_at)
SELECT (SELECT id FROM users WHERE email = 'loadtest-owner@patitasfind.test'), 'LOADTEST-perro-' || g, 'available',
       '[]', 'Ciudad de México', 'México', 19.43 + (random() - 0.5) * 0.5, -99.13 + (random() - 0.5) * 0.5,
       now() - random() * interval '60 days'
FROM generate_series(1, 5000) g;
INSERT INTO lost_reports (reporter_id, dog_name, report_type, photos, city, country, latitude, longitude, status, source, created_at)
SELECT (SELECT id FROM users WHERE email = 'loadtest-owner@patitasfind.test'), 'LOADTEST-reporte-' || g,
       CASE WHEN g % 2 = 0 THEN 'lost' ELSE 'found' END, '[]', 'Ciudad de México', 'México',
       19.43 + (random() - 0.5) * 0.5, -99.13 + (random() - 0.5) * 0.5, 'active', 'app', now() - random() * interval '60 days'
FROM generate_series(1, 3000) g;

-- Borrar al terminar
DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE lost_report_id IN (SELECT id FROM lost_reports WHERE dog_name LIKE 'LOADTEST-%'));
DELETE FROM conversations WHERE lost_report_id IN (SELECT id FROM lost_reports WHERE dog_name LIKE 'LOADTEST-%');
DELETE FROM lost_reports WHERE dog_name LIKE 'LOADTEST-%';
DELETE FROM dog_passes WHERE dog_id IN (SELECT id FROM dogs WHERE name LIKE 'LOADTEST-%');
DELETE FROM matches WHERE dog_id IN (SELECT id FROM dogs WHERE name LIKE 'LOADTEST-%');
DELETE FROM dogs WHERE name LIKE 'LOADTEST-%';
DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email = 'loadtest-owner@patitasfind.test');
DELETE FROM users WHERE email = 'loadtest-owner@patitasfind.test';
```
