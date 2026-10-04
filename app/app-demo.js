/* ============================================================
   PatitasFind 🐾 — Motor de interacción y animaciones
   ============================================================ */
'use strict';
const $  = (s, c=document) => c.querySelector(s);
const $$ = (s, c=document) => [...c.querySelectorAll(s)];
const device = $('#device');
const pawLayer = $('#pawLayer');
const fxLayer  = $('#fxLayer');
const rand = (a,b) => a + Math.random()*(b-a);
const pick = arr => arr[Math.floor(Math.random()*arr.length)];

const PAW = '<svg viewBox="0 0 64 64" width="100%" height="100%"><use href="#paw"/></svg>';
const HEART = '<svg viewBox="0 0 24 24" width="100%" height="100%"><use href="#heart"/></svg>';

/* ---------- utilidad: posición relativa al dispositivo ---------- */
function relPos(clientX, clientY){
  const r = device.getBoundingClientRect();
  return { x: clientX - r.left, y: clientY - r.top };
}

/* ============================================================
   1) HUELLITAS NEGRAS: cada toque pinta una huella 2 s y se desvanece 1 s
   ============================================================ */
let pawCount = 0;
device.addEventListener('pointerdown', e => {
  if (pawCount > 40) return;
  const {x, y} = relPos(e.clientX, e.clientY);
  const paw = document.createElement('div');
  paw.className = 'touch-paw';
  paw.innerHTML = PAW;
  paw.style.left = (x - 17) + 'px';
  paw.style.top  = (y - 17) + 'px';
  paw.style.setProperty('--rot', rand(-35, 35).toFixed(0) + 'deg');
  pawLayer.appendChild(paw);
  pawCount++;
  setTimeout(() => { paw.remove(); pawCount--; }, 3000);
});

/* ---------- ráfaga de mini huellitas desde un elemento ---------- */
function pawBurst(el, n=3){
  const r = el.getBoundingClientRect(), d = device.getBoundingClientRect();
  for (let i=0;i<n;i++){
    const m = document.createElement('div');
    m.className = 'mini-paw';
    m.innerHTML = PAW;
    m.style.left = (r.left - d.left + r.width/2 - 8 + rand(-24,24)) + 'px';
    m.style.top  = (r.top - d.top + rand(-4,8)) + 'px';
    m.style.setProperty('--dx', rand(-30,30).toFixed(0)+'px');
    m.style.setProperty('--rot', rand(-40,40).toFixed(0)+'deg');
    pawLayer.appendChild(m);
    setTimeout(()=>m.remove(), 950);
  }
}

/* ============================================================
   2) BOTONES — 5 efectos asignados en rotación
      squish · ripple · magnet · wiggle · shine  (+ float idle)
   ============================================================ */
const FX = ['fx-squish','fx-ripple','fx-magnet','fx-wiggle','fx-shine'];
$$('.btn').forEach((b,i) => b.classList.add(FX[i % FX.length]));
$$('.iconbtn').forEach(b => b.classList.add('fx-squish','fx-wiggle'));

/* ---------- contadores: el número crece, da un "pop" al llegar y regresa ---------- */
function countUp(el, dur=1000){
  const html = el.innerHTML;
  const m = html.match(/^([\s\S]*?)(\d[\d,]*)([\s\S]*)$/);
  if (!m) return;
  const target = parseInt(m[2].replace(/,/g,''),10);
  const fmt = v => m[1] + Math.round(v).toLocaleString('en-US') + m[3];
  const t0 = performance.now();
  (function tick(t){
    const p = Math.min(1, Math.max(0, (t - t0) / dur));
    const e = 1 - Math.pow(1-p,3);              // easeOutCubic
    el.innerHTML = fmt(target*e);
    if (p < 1) requestAnimationFrame(tick);
    else{
      el.innerHTML = fmt(target);
      // aumento al llegar al número y regreso a tamaño normal
      el.style.display = getComputedStyle(el).display === 'inline' ? 'inline-block' : el.style.display;
      el.animate(
        [{transform:'scale(1)'},{transform:'scale(1.45)',offset:.38},{transform:'scale(1)'}],
        {duration:520, easing:'cubic-bezier(.34,1.56,.64,1)'}
      );
    }
  })(performance.now());
}

/* ---------- barras: crecen desde cero con rebote ---------- */
function growBar(el, prop, dur=900, delay=0){
  const target = el.style[prop];
  if (!target || parseFloat(target) === 0) return;
  el.animate(
    [{[prop]:'0'},{[prop]:target}],
    {duration:dur, delay, easing:'cubic-bezier(.34,1.3,.5,1)', fill:'backwards'}
  );
}

/* ---------- sacudida de error ---------- */
function shake(el){
  el && el.animate(
    [{transform:'translateX(0)'},{transform:'translateX(-9px)'},{transform:'translateX(9px)'},{transform:'translateX(-5px)'},{transform:'translateX(0)'}],
    {duration:380}
  );
}

/* ============================================================
   2b) ¡GUAU! / ¡MIAU! — globo cómic que crece letra por letra
   ============================================================ */
function guau(x, y, flip=false){
  const d = device.getBoundingClientRect();
  const pop = document.createElement('div');
  pop.className = 'guau-pop' + (flip ? ' flip' : '');
  'GUAU!'.split('').forEach((ch, i) => {
    const s = document.createElement('span');
    s.className = 'guau-letter' + (i === 3 ? ' yellow' : i === 4 ? ' red' : '');
    s.textContent = ch;
    pop.appendChild(s);
  });
  pop.style.left = Math.min(Math.max(x - 62, 6), d.width - 140) + 'px';
  pop.style.top  = (y - 64) + 'px';
  pawLayer.appendChild(pop);
  /* entrada: cada letra crece con rebote, una tras otra */
  [...pop.children].forEach((s, i) => {
    s.animate(
      [{transform:'scale(0) rotate(-14deg)',opacity:0},
       {transform:'scale(1.45) rotate(5deg)',opacity:1,offset:.6},
       {transform:'scale(1) rotate(0deg)'}],
      {duration:420, delay:i*95, easing:'cubic-bezier(.34,1.56,.64,1)', fill:'backwards'}
    );
  });
  /* el globo entero hace un pequeño bote al terminar las letras */
  pop.animate(
    [{transform:pop.classList.contains('flip')?'rotate(5deg)':'rotate(-6deg)'},
     {transform:'rotate(-6deg) scale(1.12)',offset:.5},
     {transform:pop.classList.contains('flip')?'rotate(5deg)':'rotate(-6deg)'}],
    {duration:380, delay:560, easing:'ease-in-out'}
  );
  setTimeout(() => {
    pop.animate([{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(-18px)'}],
      {duration:350, easing:'ease-in'});
    setTimeout(() => pop.remove(), 360);
  }, 1500);
}

/* ¡MIAU! — variante gatuna: globo lila, letra a letra más rápida y saltarina */
function miau(x, y, flip=false){
  const d = device.getBoundingClientRect();
  const pop = document.createElement('div');
  pop.className = 'guau-pop miau-pop' + (flip ? ' flip' : '');
  'MIAU!'.split('').forEach((ch, i) => {
    const s = document.createElement('span');
    s.className = 'guau-letter' + (i === 3 ? ' pink' : i === 4 ? ' red' : '');
    s.textContent = ch;
    pop.appendChild(s);
  });
  pop.style.left = Math.min(Math.max(x - 58, 6), d.width - 140) + 'px';
  pop.style.top  = (y - 64) + 'px';
  pawLayer.appendChild(pop);
  /* las letras de gato crecen más rápido y con un brinco extra */
  [...pop.children].forEach((s, i) => {
    s.animate(
      [{transform:'scale(0) rotate(12deg) translateY(6px)',opacity:0},
       {transform:'scale(1.5) rotate(-6deg) translateY(-4px)',opacity:1,offset:.55},
       {transform:'scale(1) rotate(0deg) translateY(0)'}],
      {duration:360, delay:i*80, easing:'cubic-bezier(.34,1.56,.64,1)', fill:'backwards'}
    );
  });
  pop.animate(
    [{transform:pop.classList.contains('flip')?'rotate(6deg)':'rotate(-5deg)'},
     {transform:'rotate(-6deg) scale(1.14) translateY(-4px)',offset:.5},
     {transform:pop.classList.contains('flip')?'rotate(6deg)':'rotate(-5deg)'}],
    {duration:400, delay:500, easing:'ease-in-out'}
  );
  setTimeout(() => {
    pop.animate([{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(-20px) rotate(4deg)'}],
      {duration:340, easing:'ease-in'});
    setTimeout(() => pop.remove(), 350);
  }, 1400);
}

/* ¿el elemento tocado contiene un perrito? (svg dogface o emojis 🐕🐶) */
function hasDog(el){
  return !!(el.querySelector && el.querySelector('use[href="#dogface"]'))
      || /🐕|🐶/.test(el.textContent || '');
}

/* ¿el elemento tocado contiene un gatito? (svg catface o emojis 🐈🐱) */
function hasCat(el){
  return !!(el.querySelector && el.querySelector('use[href="#catface"]'))
      || /🐈|🐱/.test(el.textContent || '');
}

/* click cerca de un perrito o gatito → ¡GUAU! / ¡MIAU! */
device.addEventListener('click', e => {
  let t = e.target;
  for (let i = 0; i < 4 && t && t !== device; i++, t = t.parentElement){
    if (t.classList && t.classList.contains('screen')) break;
    const r = t.getBoundingClientRect(), d = device.getBoundingClientRect();
    if (r.width > d.width * .85 || r.height > d.height * .85) break;   // no pantallas enteras
    if (hasCat(t)){
      miau(r.left - d.left + r.width/2, r.top - d.top, Math.random() > .5);
      pawBurst(t, 2);
      break;
    }
    if (hasDog(t)){
      guau(r.left - d.left + r.width/2, r.top - d.top, Math.random() > .5);
      pawBurst(t, 2);
      break;
    }
  }
});

/* ripple: onda en el punto exacto del click */
device.addEventListener('pointerdown', e => {
  const btn = e.target.closest('.fx-ripple');
  if (!btn) return;
  const r = btn.getBoundingClientRect();
  const s = document.createElement('span');
  s.className = 'ripple';
  const size = Math.max(r.width, r.height) * .6;
  s.style.width = s.style.height = size + 'px';
  s.style.left = (e.clientX - r.left - size/2) + 'px';
  s.style.top  = (e.clientY - r.top  - size/2) + 'px';
  btn.appendChild(s);
  setTimeout(()=>s.remove(), 700);
});

/* magnet: el botón sigue al cursor dentro de su zona */
if (matchMedia('(pointer:fine)').matches){
  device.addEventListener('pointermove', e => {
    $$('.screen.active .fx-magnet').forEach(btn => {
      const r = btn.getBoundingClientRect();
      const cx = r.left + r.width/2, cy = r.top + r.height/2;
      const dx = e.clientX - cx, dy = e.clientY - cy;
      const dist = Math.hypot(dx, dy);
      const range = 110;
      if (dist < range){
        const f = (1 - dist/range) * .28;
        btn.style.transform = `translate(${dx*f}px, ${dy*f}px) scale(${1 + f*.5})`;
      } else {
        btn.style.transform = '';
      }
    });
  });
}

/* cada click en botón lanza su ráfaga de huellitas */
device.addEventListener('click', e => {
  const b = e.target.closest('.btn');
  if (b) pawBurst(b, 3);
});

/* ============================================================
   3) NAVEGACIÓN ENTRE PANTALLAS — 5 transiciones rotando
   ============================================================ */
const TX = ['tx-fade','tx-left','tx-up','tx-zoom','tx-flip'];
const screens = {};
$$('.screen').forEach(s => {
  screens[s.dataset.s] = s;
  s.classList.add(TX[+s.dataset.s % TX.length]);
});

let current = null, historyStack = [];

function blocksOf(screen){
  const out = [];
  for (const child of screen.children){
    if (child.classList.contains('sb')) continue;
    if (child.classList.contains('pad')) out.push(...child.children);
    else if (child.classList.contains('nav') || child.tagName === 'svg') out.push(child);
    else if (child.querySelector && child.querySelector(':scope > .btn')) out.push(child);
  }
  return out.filter(el => !el.style.position.includes('absolute') || el.classList.contains('nav'));
}

const ENT_KF = [
  [{opacity:0,transform:'scale(.3) rotate(-6deg)'},{opacity:1,transform:'scale(1) rotate(0)'}],                    // pop
  [{opacity:0,transform:'translateY(70px)'},{opacity:1,transform:'translateY(0)'}],                                // up
  [{opacity:0,transform:'translateY(-90px) rotate(-10deg)'},{opacity:1,transform:'translateY(0) rotate(0)'}],      // drop
  [{opacity:0,transform:'translateX(120px) rotate(4deg)'},{opacity:1,transform:'translateX(0) rotate(0)'}],        // side
  [{opacity:0,filter:'blur(14px)',transform:'scale(1.25)'},{opacity:1,filter:'blur(0px)',transform:'scale(1)'}],  // blur
];
function playEntrance(screen){
  if (new URLSearchParams(location.search).has('noanim')) return;
  const blocks = blocksOf(screen);
  blocks.forEach((el,i) => {
    // WAAPI compone con las animaciones CSS (float, beat, shine…) sin pisarlas
    el.animate(ENT_KF[i % ENT_KF.length], {
      duration: 560,
      delay: i * 85,
      easing: 'cubic-bezier(.34,1.56,.64,1)',
      fill: 'backwards',
    });
  });
  if (new URLSearchParams(location.search).has('debug')){
    setTimeout(() => {
      const info = blocks.map(el => ({
        cls: (el.className||'').toString().slice(0,20),
        op: getComputedStyle(el).opacity,
        n: el.getAnimations().length,
      }));
      document.body.setAttribute('data-debug', JSON.stringify(info));
    }, 1500);
  }
}

function show(id, push=true){
  if (!screens[id] || current === id) return;
  if (push && current) historyStack.push(current);
  Object.values(screens).forEach(s => s.classList.remove('active'));
  const s = screens[id];
  s.classList.add('active');
  requestAnimationFrame(() => playEntrance(s));
  current = id;
  if (location.hash !== '#s' + id) history.replaceState(null,'','#s'+id);
  onEnter(id);
}

function goBack(){
  const prev = historyStack.pop();
  show(prev || '3', false);
}

/* ---------- Tabla de navegación por texto visible ---------- */
const NAV = {
  1:[['Comenzar',24],['Entrar',24]],
  2:[['Siguiente',3],['Saltar',3]],
  24:[],                                 // Google/correo → verificación SMS
  25:[],                                 // flujo SMS interactivo
  3:[['Buscar ahora',5]],
  4:[['Solicitar adopción',13]],
  5:[],                                  // el obturador se maneja aparte
  6:[],                                  // avanza sola al terminar el escaneo
  7:[['Confirmar match',11],['Activar alerta',9]],
  8:[['Reportar aquí',9]],
  9:[['Siguiente: revisar',3,'🎉 ¡Alerta activada! 143 vecinos avisados']],
  10:[['Publicar reporte',3,'🎉 Reporte publicado. ¡Gracias por ayudar!']],
  11:[['Abrir chat seguro',12]],
  12:[],
  13:[['Enviar solicitud',26,'💌 Solicitud enviada · completa el cuestionario de hogar']],
  14:[['Agendar',null,'📅 Cita agendada con Vet. Patitas']],
  15:[],
  16:[],
  17:[],
  18:[],                                 // filas de ranking → 16
  19:[['Siguiente: dónde y cuándo',9]],
  20:[['Donar',null,'💛 ¡Gracias! Tu donación va directo al refugio']],
  21:[],
  22:[['Publicar',3,'🐾 Publicación enviada · se activa en menos de 24 h']],
  23:[],
};

device.addEventListener('click', e => {
  const navSvg = e.target.closest('.nav svg, .nav .fab, .nav div:last-child');
  const el = e.target.closest('.btn,.iconbtn,.chip,.badge,.rank-row') || navSvg;
  if (!el) return;

  /* corazones: estallido de amor */
  if (el.querySelector('use')?.getAttribute('href') === '#heart' || e.target.closest('use')?.getAttribute('href') === '#heart'){
    heartBurst(el);
  }

  /* chips: selección única por grupo [data-q] o multi (estado de ánimo) */
  if (el.classList.contains('chip')){
    const group = el.parentElement && el.parentElement.dataset ? el.parentElement.dataset.q : null;
    if (group){
      const multi = el.parentElement.hasAttribute('data-multi');
      if (!multi) [...el.parentElement.children].forEach(c => c.classList.toggle('on', c === el ? !el.classList.contains('on') : false));
      else el.classList.toggle('on');
      if (current === '26') updateQProgress();
    } else {
      el.classList.toggle('on');
    }
    el.style.transform = 'scale(.88)';
    setTimeout(()=> el.style.transform = '', 180);
    return;
  }

  /* flechas de regreso */
  if (el.classList.contains('iconbtn') && (el.textContent.trim() === '←' || el.textContent.trim() === '✕')){
    goBack(); return;
  }

  /* barra de navegación inferior */
  if (navSvg && (current === '3' || current === '17' || current === '21')){
    const nav = navSvg.closest('.nav');
    const icons = [...nav.children];
    const i = icons.indexOf(navSvg.tagName === 'svg' || navSvg.classList.contains('fab') ? navSvg : navSvg.parentElement) ;
    const targets = ['3','12','9','18','16'];
    const idx = icons.indexOf(navSvg);
    show(targets[[...nav.children].indexOf(navSvg)] ?? '3');
    return;
  }

  /* filas del ranking → perfil de refugio */
  if (el.classList.contains('rank-row')){ show('16'); return; }

  /* búsqueda en la tabla NAV */
  const txt = el.textContent.trim();
  for (const [match, target, msg] of (NAV[current] || [])){
    if (txt.startsWith(match.slice(0, Math.min(match.length, 12))) || txt.includes(match)){
      if (msg) toast(msg);
      if (target) show(String(target));
      return;
    }
  }
});

/* ============================================================
   4) TOAST
   ============================================================ */
let toastTimer;
function toast(msg){
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=> t.classList.remove('show'), 2400);
}

/* ============================================================
   5) EFECTOS ESPECIALES
   ============================================================ */
function heartBurst(el){
  const r = el.getBoundingClientRect(), d = device.getBoundingClientRect();
  for (let i=0;i<6;i++){
    const h = document.createElement('div');
    h.className = 'heart-fly';
    h.innerHTML = HEART;
    h.style.left = (r.left - d.left + r.width/2 - 9) + 'px';
    h.style.top  = (r.top - d.top) + 'px';
    h.style.setProperty('--dx', rand(-46,46).toFixed(0)+'px');
    h.style.setProperty('--rot', rand(-45,45).toFixed(0)+'deg');
    fxLayer.appendChild(h);
    setTimeout(()=>h.remove(), 1000);
  }
  el.style.transform = 'scale(1.35)';
  setTimeout(()=> el.style.transform = '', 250);
}

function confetti(x, y, n=26){
  const colors = ['var(--orange)','var(--pink)','var(--blue)','var(--lila)','var(--green)'];
  for (let i=0;i<n;i++){
    const c = document.createElement('div');
    c.className = 'confetti';
    c.style.left = x + 'px'; c.style.top = y + 'px';
    c.style.background = pick(colors);
    c.style.setProperty('--dx', rand(-140,140).toFixed(0)+'px');
    c.style.setProperty('--dy', rand(160,340).toFixed(0)+'px');
    c.style.setProperty('--rot', rand(360,900).toFixed(0)+'deg');
    fxLayer.appendChild(c);
    setTimeout(()=>c.remove(), 1900);
  }
}

/* ============================================================
   6) LÓGICA POR PANTALLA
   ============================================================ */
let scanTimer = null;

function onEnter(id){
  clearInterval(scanTimer);

  /* Lámina 1: logo con latido */
  if (id === '1'){
    const logo = screens['1'].querySelector('.pad > div:first-child');
    logo && logo.classList.add('beat');
  }

  /* Lámina 3: carrusel animado + tarjetas deslizables */
  if (id === '3'){
    const row = $$('.screen[data-s="3"] > div').find(d => d.style.paddingLeft === '22px');
    if (row && !row.id) row.id = 'carousel';
    $$('.screen[data-s="3"] .card').forEach(c => {
      if (!c.classList.contains('swipe-card')){
        c.classList.add('swipe-card');
        c.addEventListener('click', () => show('4'));
      }
    });
    /* categoría "Refugios" → mapa de refugios (31) */
    $$('.screen[data-s="3"] .pad div').forEach(d => {
      if (d.textContent.trim() === 'Refugios' && !d.dataset.wired){
        d.dataset.wired = '1';
        d.style.cursor = 'pointer';
        d.addEventListener('click', () => show('31'));
      }
    });
  }

  /* Lámina 5: el obturador dispara el escaneo */
  if (id === '5'){
    const shutter = $('.screen[data-s="5"] .shutter-btn');
    shutter && shutter.addEventListener('click', () => show('6'));
  }

  /* Lámina 6: láser + progreso que avanza solo */
  if (id === '6'){
    const photoBox = $('.screen[data-s="6"] .pad > div');
    if (photoBox && !$('.scan-laser', photoBox)){
      const laser = document.createElement('div');
      laser.className = 'scan-laser';
      photoBox.appendChild(laser);
    }
    const bar  = $$('.screen[data-s="6"] .pad > div')[1];
    const fill = bar && bar.firstElementChild;
    const pct  = $('.screen[data-s="6"] .pad p:last-child');
    let p = 0;
    scanTimer = setInterval(() => {
      p = Math.min(100, p + rand(4,9));
      if (fill) fill.style.width = p + '%';
      if (pct)  pct.textContent = Math.round(p) + '%';
      if (p >= 100){ clearInterval(scanTimer); setTimeout(()=> show('7'), 450); }
    }, 160);
    screens['6'].addEventListener('click', e => {
      if (e.target.closest('.iconbtn')) return;   // la flecha de regreso no avanza
      show('7');
    }, { once:true });
  }

  /* Lámina 8: pines con latido */
  if (id === '8'){
    $$('.screen[data-s="8"] [style*="border-radius:50% 50%"]').forEach(p => p.classList.add('map-pin'));
  }

  /* Lámina 16: estadísticas del refugio cuentan con pop */
  if (id === '16'){
    $$('.screen[data-s="16"] div[style*="font-size:20px"]').forEach((el,i) =>
      setTimeout(() => countUp(el, 900), 250 + i*180));
  }

  /* Lámina 18: podio — barras que crecen + números que cuentan */
  if (id === '18'){
    // barras del podio crecen desde cero
    $$('.screen[data-s="18"] [style*="border-radius:14px 14px 0 0"]').forEach((bar,i) =>
      growBar(bar, 'height', 850, 200 + i*160));
    // cifras del podio (96 🏠, 128 🏠, 84 🏠)
    $$('.screen[data-s="18"] div[style*="color:var(--orange-d)"]').forEach((el,i) =>
      setTimeout(() => countUp(el, 900), 300 + i*160));
    // cifras de la lista (71 🏠, 63 🏠, 12 🏠)
    $$('.screen[data-s="18"] span[style*="font-size:13px"]').forEach((el,i) =>
      setTimeout(() => countUp(el, 800), 600 + i*140));
  }

  /* Lámina 23: recompensas — barras de origen + montos que cuentan */
  if (id === '23'){
    $$('.screen[data-s="23"] div[style*="height:100%"]').forEach((el,i) =>
      growBar(el, 'width', 950, 350 + i*280));
    $$('.screen[data-s="23"] span').filter(s => /^\$[\d,]+$/.test(s.textContent.trim()))
      .forEach((el,i) => setTimeout(() => countUp(el, 1000), 400 + i*250));
    const big = $('.screen[data-s="23"] div[style*="font-size:38px"]');
    if (big) setTimeout(() => countUp(big, 1300), 200);
  }

  /* Lámina 24: registro — Google o correo llevan a verificación SMS */
  if (id === '24'){
    const gBtn = $('.screen[data-s="24"] .g-btn');
    const mailBtn = $('.screen[data-s="24"] .mail-btn');
    const mail = $('.screen[data-s="24"] .reg-mail');
    const goVerify = (name) => {
      toast(`✅ Cuenta ${name} creada · ahora verifica tu celular`);
      pawBurst(gBtn || mailBtn, 4);
      setTimeout(() => show('25'), 700);
    };
    if (gBtn && !gBtn.dataset.wired){
      gBtn.dataset.wired = '1';
      gBtn.addEventListener('click', () => {
        gBtn.textContent = 'Conectando con Google…';
        setTimeout(() => goVerify('de Google'), 900);
      });
    }
    if (mailBtn && !mailBtn.dataset.wired){
      mailBtn.dataset.wired = '1';
      mailBtn.addEventListener('click', () => {
        // MODO PRUEBAS: acepta cualquier correo
        goVerify('de correo');
      });
    }
  }

  /* Lámina 25: verificación SMS — envía código, valida y entra */
  if (id === '25'){
    const phone = $('.screen[data-s="25"] .sms-phone');
    const send  = $('.screen[data-s="25"] .sms-send');
    const codeBox = $('.screen[data-s="25"] .sms-code');
    const verify  = $('.screen[data-s="25"] .sms-verify');
    const resend  = $('.screen[data-s="25"] .sms-resend');
    const boxes   = $$('.screen[data-s="25"] .code-box');

    /* auto-avance entre casillas del código */
    boxes.forEach((b,i) => {
      if (b.dataset.wired) return;
      b.dataset.wired = '1';
      b.addEventListener('input', () => {
        b.value = b.value.replace(/\D/g,'').slice(0,1);
        if (b.value && boxes[i+1]) boxes[i+1].focus();
      });
      b.addEventListener('keydown', e => {
        if (e.key === 'Backspace' && !b.value && boxes[i-1]) boxes[i-1].focus();
      });
      b.addEventListener('paste', e => {
        e.preventDefault();
        const digits = (e.clipboardData.getData('text') || '').replace(/\D/g,'').slice(0,4);
        digits.split('').forEach((d,j) => { if (boxes[j]) boxes[j].value = d; });
        if (digits.length === 4) verify && verify.focus();
      });
    });

    /* temporizador de reenvío */
    let resendTimer = null;
    const startResend = () => {
      let s = 30;
      resend.textContent = `¿No llegó? Reenviar en ${s} s`;
      resend.style.pointerEvents = 'none';
      clearInterval(resendTimer);
      resendTimer = setInterval(() => {
        s--;
        if (s <= 0){
          clearInterval(resendTimer);
          resend.textContent = 'Reenviar código';
          resend.style.pointerEvents = '';
        } else resend.textContent = `¿No llegó? Reenviar en ${s} s`;
      }, 1000);
    };

    if (send && !send.dataset.wired){
      send.dataset.wired = '1';
      send.addEventListener('click', () => {
        // MODO PRUEBAS: acepta cualquier número
        codeBox.style.display = 'block';
        pawBurst(send, 4);
        toast('📩 SMS de prueba enviado · escribe cualquier código');
        startResend();
        setTimeout(() => boxes[0] && boxes[0].focus(), 400);
        codeBox.animate([{opacity:0,transform:'translateY(18px)'},{opacity:1,transform:'translateY(0)'}],{duration:420,easing:'cubic-bezier(.34,1.56,.64,1)'});
      });
    }

    if (resend && !resend.dataset.wired){
      resend.dataset.wired = '1';
      resend.style.cursor = 'pointer';
      resend.addEventListener('click', () => {
        if (resend.style.pointerEvents === 'none') return;
        toast(`📩 Nuevo SMS enviado · demo: ${CODE}`);
        startResend();
      });
    }

    if (verify && !verify.dataset.wired){
      verify.dataset.wired = '1';
      verify.addEventListener('click', () => {
        // MODO PRUEBAS: acepta cualquier código de 1 a 4 dígitos
        confetti(rand(100,280), rand(140,340), 26);
        heartBurst(verify);
        toast('🎉 ¡Número verificado! Bienvenido a PatitasFind');
        setTimeout(() => show('2'), 1100);   // al onboarding
      });
    }
  }

  /* Lámina 26: cuestionario de hogar — progreso + pregunta dependiente + envío */
  if (id === '26'){ wireQuestionnaire(); }
  if (id === '27'){ wireFollowUp(); }
  if (id === '28'){ wireWalkers(); }
  if (id === '29'){ wireKit(); }
  if (id === '30'){ wireEvents(); }

  /* Lámina 31: mapa de refugios — filtros + pin → perfil */
  if (id === '31'){
    const scr = $(S(31));
    if (scr && !scr.dataset.wired){
      scr.dataset.wired = '1';
      /* filtros por tipo */
      $$('.f-chip', scr).forEach(f => f.addEventListener('click', () => {
        $$('.f-chip', scr).forEach(x => x.classList.toggle('on', x === f));
        const t = f.dataset.f;
        $$('.r-item', scr).forEach(it => {
          it.style.display = (t === 'all' || it.dataset.t === t) ? '' : 'none';
        });
        $$('.map-pin', scr).forEach((p,i) => {
          const items = $$('.r-item', scr).filter(x => x.style.display !== 'none');
          p.style.opacity = (t === 'all' || i < items.length) ? '1' : '.25';
        });
        const vis = $$('.r-item', scr).filter(x => x.style.display !== 'none').length + 2;
        const c = scr.querySelector('.r-count');
        if (c) c.textContent = t === 'all' ? 5 : vis;
      }));
      /* item → perfil de refugio (16) */
      $$('.r-item', scr).forEach(it => it.addEventListener('click', () => show('16')));
      /* registrar → paso 1 */
      const reg = scr.querySelector('.r-register');
      reg && reg.addEventListener('click', () => show('32'));
    }
  }

  /* Lámina 32: registro refugio paso 1 — capacidad + validación */
  if (id === '32'){
    const scr = $(S(32));
    if (scr && !scr.dataset.wired){
      scr.dataset.wired = '1';
      let cap = 4;
      const num = scr.querySelector('.cap-num');
      const paint = () => num.textContent = cap;
      scr.querySelector('.cap-plus').addEventListener('click', () => { cap = Math.min(50, cap+1); paint(); });
      scr.querySelector('.cap-minus').addEventListener('click', () => { cap = Math.max(1, cap-1); paint(); });
      scr.querySelector('.reg-next1').addEventListener('click', () => {
        const tipo = scr.querySelector('[data-q="tipo"] .chip.on');
        const nombre = scr.querySelector('.reg-nombre').value.trim();
        const dir = scr.querySelector('.reg-dir').value.trim();
        if (!tipo){ toast('Elige: ¿refugio u hogar de paso?'); return; }
        if (nombre.length < 3){ toast('Escribe el nombre de tu espacio'); shake(scr.querySelector('.reg-nombre')); return; }
        if (dir.length < 10){ toast('La dirección exacta es obligatoria 📍'); shake(scr.querySelector('.reg-dir')); return; }
        scr.dataset.nombre = nombre;
        scr.dataset.cap = cap;
        toast('✅ Paso 1 guardado');
        show('33');
      });
    }
  }

  /* Lámina 33: fotos obligatorias */
  if (id === '33'){
    const scr = $(S(33));
    if (scr && !scr.dataset.wired){
      scr.dataset.wired = '1';
      const TOTAL = 4;
      const refresh = () => {
        const done = $$('.photo-up', scr).filter(p => p.dataset.done === '1').length;
        scr.querySelector('.p-progress').style.width = (done/TOTAL*100) + '%';
        scr.querySelector('.p-count').textContent = done + '/' + TOTAL;
      };
      $$('.photo-up', scr).forEach(p => p.addEventListener('click', () => {
        if (p.dataset.done) return;
        p.dataset.done = '1';
        p.style.borderStyle = 'solid';
        p.style.background = 'var(--green)';
        p.innerHTML = '<div style="font-size:26px">✅</div><div style="font-weight:800;font-size:12px;margin-top:4px">¡Foto lista!</div><div style="font-size:10px;font-weight:600;opacity:.5">Toca para cambiarla</div>';
        pawBurst(p, 3);
        refresh();
      }));
      scr.querySelector('.reg-next2').addEventListener('click', () => {
        const done = $$('.photo-up', scr).filter(p => p.dataset.done === '1').length;
        if (done < TOTAL){
          toast(`📸 Faltan ${TOTAL-done} fotos obligatorias`);
          shake(scr.querySelector('.reg-next2'));
          return;
        }
        toast('✅ Fotos recibidas');
        show('34');
      });
    }
  }

  /* Lámina 34: cuestionario del refugio */
  if (id === '34'){
    const scr = $(S(34));
    if (scr && !scr.dataset.wired){
      scr.dataset.wired = '1';
      scr.querySelector('.reg-send').addEventListener('click', () => {
        const missing = ['r1','r2','r3','r4','r5','r6'].filter(g => !scr.querySelector(`[data-q="${g}"] .chip.on`));
        if (missing.length){
          toast(`Faltan ${missing.length} preguntas del cuestionario`);
          shake(scr.querySelector('.reg-send'));
          return;
        }
        confetti(rand(110,290), rand(140,330), 24);
        toast('🐾 ¡Solicitud enviada! Revisión en menos de 24 h');
        setTimeout(() => show('35'), 900);
      });
    }
  }

  /* Lámina 35: revisión → aprobación simulada → mapa */
  if (id === '35'){
    const scr = $(S(35));
    if (scr && !scr.dataset.wired){
      scr.dataset.wired = '1';
      const nombre = ($(S(32)) || {}).dataset ? $(S(32)).dataset.nombre : '';
      const sim = scr.querySelector('.a-sim');
      sim && sim.addEventListener('click', () => {
        sim.textContent = '⏳ Revisando fotos y dirección…';
        sim.disabled = true;
        setTimeout(() => {
          scr.querySelector('.a-pending').style.display = 'none';
          const ap = scr.querySelector('.a-approved');
          ap.style.display = 'block';
          ap.animate([{opacity:0,transform:'translateY(20px)'},{opacity:1,transform:'translateY(0)'}],{duration:500,easing:'cubic-bezier(.34,1.56,.64,1)'});
          const nm = ap.querySelector('.a-name');
          if (nm && nombre) nm.textContent = nombre + ' · ¡Nuevo en el mapa!';
          confetti(rand(90,300), rand(130,340), 30);
          toast('🎉 ¡Aprobado! Ya estás en el mapa y en el ranking');
        }, 1600);
      });
      scr.querySelector('.a-gomap').addEventListener('click', () => show('31'));
      const rank = [...scr.querySelectorAll('.btn')].find(b => b.textContent.includes('ranking'));
      rank && rank.addEventListener('click', () => show('18'));
    }
  }

  /* Lámina 11: ¡confeti de celebración! */
  if (id === '11'){
    [300, 500, 750].forEach((t,i) =>
      setTimeout(() => confetti(rand(80,310), rand(140,320), 22), t));
  }

  /* Lámina 12: burbujas con pop + enviar mensajes */
  if (id === '12'){
    const col = $$('.screen[data-s="12"] .pad')[2];
    col && [...col.children].forEach(b => b.classList.add('bubble'));
    const input = $('.screen[data-s="12"] .inp');
    const send  = $$('.screen[data-s="12"] .fab').pop();
    if (send && !send.dataset.wired){
      send.dataset.wired = '1';
      send.addEventListener('click', () => {
        const txt = input.textContent.trim();
        if (!txt) { toast('✏️ Escribe un mensaje primero'); return; }
        const b = document.createElement('div');
        b.className = 'bubble';
        b.style.cssText = 'align-self:flex-end;max-width:70%;background:var(--orange);border:2px solid var(--ink);border-radius:20px 20px 6px 20px;padding:11px 14px;font-size:13.5px;font-weight:600;box-shadow:0 3px 0 rgba(59,47,47,.12)';
        b.textContent = txt;
        col.appendChild(b);
        input.textContent = '';
        pawBurst(send, 2);
      });
    }
  }

  /* Lámina 18: filas de ranking navegables */
  if (id === '18'){
    $$('.screen[data-s="18"] .card div[style*="padding:11px"]').forEach(r => {
      if (!r.classList.contains('rank-row')){
        r.classList.add('rank-row');
        r.addEventListener('click', () => show('16'));
      }
    });
  }

  /* Lámina 20: montos exclusivos + confeti al donar */
  if (id === '20'){
    const cards = $$('.screen[data-s="20"] .pad')[1].querySelectorAll('.card');
    const montos = [...cards].filter(c => /^\$\d|Otro/.test(c.textContent.trim()));
    montos.forEach(m => m.addEventListener('click', () => {
      montos.forEach(x => x.style.background = '');
      m.style.background = 'var(--orange)';
      m.style.transform = 'scale(.92)'; setTimeout(()=> m.style.transform = '', 200);
    }));
    const donate = $$('.screen[data-s="20"] .btn').find(b => b.textContent.includes('Donar'));
    donate && donate.addEventListener('click', () =>
      confetti(rand(100,290), rand(500,640), 30));
  }

  /* Lámina 21: carrito con contador */
  if (id === '21'){
    $$('.screen[data-s="21"] .btn-sm').forEach(b => {
      if (b.dataset.wired) return;
      b.dataset.wired = '1';
      b.addEventListener('click', () => {
        cart = (cart||0) + 1;
        toast(`🛒 Agregado al carrito solidario · ${cart} producto${cart>1?'s':''}`);
      });
    });
  }
}
let cart = 0;

/* ============================================================
   6b) NUEVAS FUNCIONALIDADES — cuestionario, seguimiento,
       paseadores, kit y jornadas
   ============================================================ */
const S = n => `.screen[data-s="${n}"]`;

/* Lámina 26: progreso del cuestionario (6 grupos) */
function updateQProgress(){
  const scr = $(S(26));
  if (!scr) return;
  const groups = ['1','2','3','4','5','6'];
  let answered = 0;
  groups.forEach(g => {
    if (scr.querySelector(`[data-q="${g}"] .chip.on`)) answered++;
  });
  const bar = scr.querySelector('.q-progress');
  const cnt = scr.querySelector('.q-count');
  if (bar) bar.style.width = (answered / 6 * 100) + '%';
  if (cnt) cnt.textContent = answered + '/6';
  /* pregunta dependiente: vivienda rentada */
  const rent = [...scr.querySelectorAll('[data-q="2"] .chip')].find(c => c.classList.contains('on') && c.textContent.includes('Rentada'));
  const dep = scr.querySelector('.q-depend');
  if (dep){
    const show = !!rent;
    if (show && dep.style.display === 'none'){
      dep.style.display = 'block';
      dep.animate([{opacity:0,transform:'translateY(-8px)'},{opacity:1,transform:'translateY(0)'}],{duration:350,easing:'cubic-bezier(.34,1.56,.64,1)'});
    } else if (!show) dep.style.display = 'none';
  }
}
function wireQuestionnaire(){
  const scr = $(S(26));
  if (!scr || scr.dataset.wired) return;
  scr.dataset.wired = '1';
  updateQProgress();
  const send = scr.querySelector('.q-send');
  send && send.addEventListener('click', () => {
    const missing = ['1','2','3','4','5','6'].filter(g => !scr.querySelector(`[data-q="${g}"] .chip.on`));
    if (missing.length){
      toast(`Faltan ${missing.length} preguntas por responder 🐾`);
      send.animate([{transform:'translateX(0)'},{transform:'translateX(-9px)'},{transform:'translateX(9px)'},{transform:'translateX(0)'}],{duration:340});
      return;
    }
    confetti(rand(110,290), rand(150,330), 26);
    toast('🎉 ¡Cuestionario enviado! El refugio te responderá en menos de 1 día');
    setTimeout(() => show('27'), 1200);
  });
}

/* Lámina 27: seguimiento post-adopción */
function wireFollowUp(){
  const scr = $(S(27));
  if (!scr || scr.dataset.wired) return;
  scr.dataset.wired = '1';
  const slot = scr.querySelector('.photo-slot');
  const send = scr.querySelector('.f-send');
  let photo = false;
  slot && slot.addEventListener('click', () => {
    photo = true;
    slot.style.borderStyle = 'solid';
    slot.style.background = 'var(--green)';
    slot.innerHTML = '<div style="font-size:24px">✅</div><div style="font-weight:800;font-size:12.5px">¡Foto del día lista!</div><div style="font-size:11px;font-weight:600;opacity:.55">Rocky se ve feliz 🐶</div>';
    pawBurst(slot, 3);
  });
  send && send.addEventListener('click', () => {
    const mood = scr.querySelector('[data-q="mood"] .chip.on');
    if (!mood && !photo){
      toast('Elige cómo está Rocky o sube una foto 📸');
      return;
    }
    confetti(rand(120,260), rand(150,300), 20);
    toast('💚 Check-in del día 30 enviado al refugio');
  });
  const walk = [...scr.querySelectorAll('.btn')].find(b => b.textContent.includes('paseador'));
  walk && walk.addEventListener('click', () => show('28'));
  const kit = scr.querySelector('.f-kit');
  kit && kit.addEventListener('click', () => show('29'));
}

/* Lámina 28: paseadores — pedir con estado */
function wireWalkers(){
  const scr = $(S(28));
  if (!scr || scr.dataset.wired) return;
  scr.dataset.wired = '1';
  $$('.w-request', scr).forEach(btn => btn.addEventListener('click', () => {
    if (btn.dataset.done) return;
    btn.dataset.done = '1';
    btn.textContent = '✓ Pedido';
    btn.style.background = 'var(--green)';
    pawBurst(btn, 3);
    toast('🦮 Solicitud enviada · te confirman en menos de 15 min');
  }));
}

/* Lámina 29: kit de bienvenida — check de artículos */
function wireKit(){
  const scr = $(S(29));
  if (!scr || scr.dataset.wired) return;
  scr.dataset.wired = '1';
  const TOTAL = 6;
  const refresh = () => {
    const done = $$('.k-item', scr).filter(i => i.dataset.done === '1').length;
    const bar = scr.querySelector('.k-progress');
    const cnt = scr.querySelector('.k-count');
    if (bar) bar.style.width = (done / TOTAL * 100) + '%';
    if (cnt) cnt.textContent = done + '/' + TOTAL;
    if (done === TOTAL){
      confetti(rand(110,290), rand(150,330), 26);
      toast('🎒 ¡Kit completo! Rocky está listo para llegar a casa');
    }
  };
  $$('.k-item', scr).forEach(item => {
    if (item.querySelector('.k-check').textContent.trim() === '✓') item.dataset.done = '1';
    item.addEventListener('click', () => {
      const check = item.querySelector('.k-check');
      const on = item.dataset.done === '1';
      item.dataset.done = on ? '' : '1';
      item.style.background = on ? '' : 'var(--green)';
      check.textContent = on ? '' : '✓';
      check.style.opacity = on ? '.35' : '1';
      item.animate([{transform:'scale(.96)'},{transform:'scale(1)'}],{duration:200,easing:'cubic-bezier(.34,1.56,.64,1)'});
      pawBurst(item, 2);
      refresh();
    });
  });
  refresh();
  const store = [...scr.querySelectorAll('.btn')].find(b => b.textContent.includes('tienda'));
  store && store.addEventListener('click', () => show('21'));
  const jor = scr.querySelector('.k-jornadas');
  jor && jor.addEventListener('click', () => show('30'));
}

/* Lámina 30: jornadas — recordatorios */
function wireEvents(){
  const scr = $(S(30));
  if (!scr || scr.dataset.wired) return;
  scr.dataset.wired = '1';
  $$('.e-remind', scr).forEach(btn => btn.addEventListener('click', () => {
    if (btn.dataset.done) return;
    btn.dataset.done = '1';
    btn.textContent = '🔔 ¡Te recordaremos!';
    btn.style.background = 'var(--green)';
    pawBurst(btn, 3);
    toast('📅 Recordatorio activado · te avisamos 1 hora antes');
  }));
}

/* ============================================================
   7) FONDO: huellitas flotantes
   ============================================================ */
(function bgPaws(){
  const bg = $('#bg');
  for (let i=0;i<14;i++){
    const p = document.createElement('div');
    p.className = 'bg-paw';
    p.innerHTML = PAW;
    const size = rand(30, 90).toFixed(0);
    p.style.width = p.style.height = size + 'px';
    p.style.left = rand(0,94).toFixed(1) + 'vw';
    p.style.top  = rand(0,92).toFixed(1) + 'vh';
    p.style.setProperty('--rot', rand(-40,40).toFixed(0)+'deg');
    p.style.animationDuration = rand(4,9).toFixed(1) + 's';
    p.style.animationDelay = (-rand(0,6)).toFixed(1) + 's';
    bg.appendChild(p);
  }
})();

/* ============================================================
   8) ARRANQUE — soporta #sN para abrir una pantalla directa
   ============================================================ */
const start = new URLSearchParams(location.search).get('s')
  || (location.hash.match(/#s(\d+)/) || [])[1] || '1';
show(start, false);
