// Prueba de carga de GuauWoow (k6). Ver loadtest/README.md.
//
//   k6 run -e BASE_URL=https://staging.guauwoow.com \
//          -e LOADTEST_EMAIL=carga@guauwoow.com -e LOADTEST_PASSWORD='...' \
//          -e PHOTO=./perro.jpg loadtest/k6-patitasfind.js
//
// Escenarios:
//   browse        portada: /dogs/featured + /lost-reports con lat/lon de CDMX y detalle de un perro
//   chat          sesión iniciada: /conversations y WebSocket del chat con ping/pong
//   photo_search  búsqueda por foto a ritmo bajo (opcional, requiere PHOTO)
import http from 'k6/http';
import ws from 'k6/ws';
import { check, group, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8001').replace(/\/$/, '');
const WS_URL = BASE_URL.replace(/^http/, 'ws');
const SMOKE = Boolean(__ENV.SMOKE); // prueba corta (≈1 min, pocos VUs) para validar el script
const TARGET_VUS = parseInt(__ENV.TARGET_VUS || (SMOKE ? '10' : '800'), 10);
const CHAT_VUS = parseInt(__ENV.CHAT_VUS || String(Math.max(1, Math.round(TARGET_VUS / 10))), 10);
const HOLD_MIN = parseInt(__ENV.HOLD_MINUTES || '5', 10); // minutos sosteniendo el pico
// Etapas: subida suave, subida al pico, sostener, bajada
const STAGES = SMOKE
  ? ['10s', '10s', '30s', '10s']
  : ['2m', '3m', `${HOLD_MIN}m`, '1m'];
const PHOTO = __ENV.PHOTO ? open(__ENV.PHOTO, 'b') : null;
const HAS_LOGIN = Boolean(__ENV.LOADTEST_EMAIL && __ENV.LOADTEST_PASSWORD);

// Errores "de verdad": 5xx, timeouts y respuestas inesperadas (un 429 esperado no cuenta)
const errors = new Rate('errors');
const pongOk = new Rate('ws_pong_ok');
const pongLatency = new Trend('ws_pong_ms', true);

const scenarios = {
  browse: {
    executor: 'ramping-vus',
    exec: 'browse',
    startVUs: 0,
    stages: [
      { duration: STAGES[0], target: Math.max(1, Math.round(TARGET_VUS / 4)) },
      { duration: STAGES[1], target: TARGET_VUS },
      { duration: STAGES[2], target: TARGET_VUS },
      { duration: STAGES[3], target: 0 },
    ],
    gracefulRampDown: '30s',
  },
};
if (HAS_LOGIN) {
  scenarios.chat = {
    executor: 'ramping-vus',
    exec: 'chat',
    startVUs: 0,
    stages: [
      { duration: STAGES[0], target: CHAT_VUS },
      { duration: SMOKE ? '40s' : `${HOLD_MIN + 3}m`, target: CHAT_VUS },
      { duration: STAGES[3], target: 0 },
    ],
  };
}
if (PHOTO) {
  scenarios.photo_search = {
    executor: 'constant-arrival-rate',
    exec: 'photoSearch',
    rate: parseInt(__ENV.PHOTO_RATE_PER_MIN || '30', 10),
    timeUnit: '1m',
    duration: SMOKE ? '1m' : `${HOLD_MIN + 5}m`,
    preAllocatedVUs: 5,
    maxVUs: 20,
  };
}

export const options = {
  scenarios,
  thresholds: {
    'http_req_duration{scenario:browse}': ['p(95)<500'],
    'http_req_duration{scenario:chat}': ['p(95)<500'],
    'http_req_duration{scenario:photo_search}': ['p(95)<8000'], // incluye la llamada a la IA
    http_req_failed: ['rate<0.01'],
    errors: ['rate<0.01'],
    ws_pong_ok: ['rate>0.99'],
    ws_pong_ms: ['p(95)<500'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

// Punto aleatorio en la CDMX (~±15 km del Zócalo)
function cdmx() {
  return {
    lat: (19.4326 + (Math.random() - 0.5) * 0.3).toFixed(4),
    lon: (-99.1332 + (Math.random() - 0.5) * 0.3).toFixed(4),
  };
}

function ok(res, name, expected = [200]) {
  const good = check(res, { [`${name}: ${expected.join('/')}`]: (r) => expected.includes(r.status) });
  errors.add(!good);
  return good;
}

export function setup() {
  if (!HAS_LOGIN) return {};
  const res = http.post(`${BASE_URL}/auth/login`, {
    username: __ENV.LOADTEST_EMAIL,
    password: __ENV.LOADTEST_PASSWORD,
  });
  if (res.status !== 200) {
    throw new Error(`No se pudo iniciar sesión con LOADTEST_EMAIL (${res.status}): ${res.body}`);
  }
  const token = res.json('access_token');
  const convs = http.get(`${BASE_URL}/conversations?limit=20`, { headers: { Authorization: `Bearer ${token}` } });
  const ids = convs.status === 200 ? convs.json().map((c) => c.id) : [];
  if (!ids.length) console.warn('La cuenta de carga no tiene conversaciones: el WebSocket no se probará.');
  return { token, conversationIds: ids };
}

export function browse() {
  const p = cdmx();
  let dogs = [];
  group('portada', () => {
    const res = http.batch([
      ['GET', `${BASE_URL}/dogs/featured?lat=${p.lat}&lon=${p.lon}&limit=10`, null, { tags: { name: 'featured' } }],
      ['GET', `${BASE_URL}/lost-reports?lat=${p.lat}&lon=${p.lon}&radius_km=30`, null, { tags: { name: 'lost-reports' } }],
    ]);
    if (ok(res[0], 'featured')) dogs = res[0].json();
    ok(res[1], 'lost-reports');
  });
  sleep(1 + Math.random() * 2);
  if (dogs.length) {
    const dog = dogs[Math.floor(Math.random() * dogs.length)];
    ok(http.get(`${BASE_URL}/dogs/${dog.id}?lat=${p.lat}&lon=${p.lon}`, { tags: { name: 'dog-detail' } }), 'dog-detail');
  }
  sleep(2 + Math.random() * 3);
}

export function chat(data) {
  const headers = { Authorization: `Bearer ${data.token}` };
  ok(http.get(`${BASE_URL}/conversations`, { headers, tags: { name: 'conversations' } }), 'conversations');
  const ids = data.conversationIds || [];
  if (!ids.length) {
    sleep(5);
    return;
  }
  const convId = ids[Math.floor(Math.random() * ids.length)];
  const url = `${WS_URL}/ws/chat/${convId}?token=${data.token}`;
  const res = ws.connect(url, { tags: { name: 'ws-chat' } }, (socket) => {
    let sentAt = 0;
    let waiting = false;
    socket.on('open', () => {
      // El cliente real hace ping cada 25 s; aquí cada 5 s para medir más
      socket.setInterval(() => {
        if (waiting) pongOk.add(false); // el anterior nunca llegó
        sentAt = Date.now();
        waiting = true;
        socket.send(JSON.stringify({ type: 'ping' }));
      }, 5000);
      socket.setTimeout(() => socket.close(), SMOKE ? 12000 : 30000 + Math.random() * 30000);
    });
    socket.on('message', (msg) => {
      let evt = {};
      try { evt = JSON.parse(msg); } catch (e) { return; }
      if (evt.type === 'pong' && waiting) {
        waiting = false;
        pongOk.add(true);
        pongLatency.add(Date.now() - sentAt);
      }
    });
    socket.on('error', () => errors.add(true));
  });
  errors.add(!check(res, { 'ws: 101': (r) => r && r.status === 101 }));
  sleep(1);
}

export function photoSearch() {
  const p = cdmx();
  const res = http.post(
    `${BASE_URL}/search/by-photo`,
    { file: http.file(PHOTO, 'perro.jpg', 'image/jpeg'), lat: p.lat, lon: p.lon },
    // 429 = el límite por IP funciona (esperado si todo sale de una sola IP)
    { tags: { name: 'search-by-photo' }, responseCallback: http.expectedStatuses(200, 429) },
  );
  ok(res, 'search-by-photo', [200, 429]);
}
