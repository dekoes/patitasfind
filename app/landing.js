/* ============================================================
   PatitasFind — Efectos de landing (huellitas y botones)
   ============================================================ */
'use strict';
const $$ = (s, c=document) => [...c.querySelectorAll(s)];
const rand = (a,b) => a + Math.random()*(b-a);

const PAW = '<svg viewBox="0 0 64 64" width="100%" height="100%"><ellipse cx="32" cy="40" rx="15" ry="12" fill="currentColor"/><ellipse cx="14" cy="26" rx="7" ry="9" fill="currentColor" transform="rotate(-18 14 26)"/><ellipse cx="26" cy="17" rx="7" ry="9" fill="currentColor"/><ellipse cx="40" cy="17" rx="7" ry="9" fill="currentColor"/><ellipse cx="51" cy="26" rx="7" ry="9" fill="currentColor" transform="rotate(18 51 26)"/></svg>';

/* ---------- Capa de huellas ---------- */
let pawLayer = document.getElementById('pawLayer');
if (!pawLayer){
  pawLayer = document.createElement('div');
  pawLayer.id = 'pawLayer';
  pawLayer.setAttribute('aria-hidden', 'true');
  document.body.appendChild(pawLayer);
}

/* ---------- Huellitas negras en cada toque ---------- */
let pawCount = 0;
document.addEventListener('pointerdown', e => {
  if (pawCount > 40) return;
  const paw = document.createElement('div');
  paw.className = 'touch-paw';
  paw.innerHTML = PAW;
  paw.style.left = (e.clientX - 17) + 'px';
  paw.style.top  = (e.clientY - 17) + 'px';
  paw.style.setProperty('--rot', rand(-35, 35).toFixed(0) + 'deg');
  pawLayer.appendChild(paw);
  pawCount++;
  setTimeout(() => { paw.remove(); pawCount--; }, 3000);
});

/* ---------- Ráfaga de mini huellitas desde un elemento ---------- */
function pawBurst(el, n=3){
  const r = el.getBoundingClientRect();
  for (let i=0;i<n;i++){
    const m = document.createElement('div');
    m.className = 'mini-paw';
    m.innerHTML = PAW;
    m.style.left = (r.left + r.width/2 - 8 + rand(-24,24)) + 'px';
    m.style.top  = (r.top + rand(-4,8)) + 'px';
    m.style.setProperty('--dx', rand(-30,30).toFixed(0)+'px');
    m.style.setProperty('--rot', rand(-40,40).toFixed(0)+'deg');
    pawLayer.appendChild(m);
    setTimeout(()=>m.remove(), 950);
  }
}

/* ---------- Botones: 5 efectos asignados en rotación ---------- */
const BTN_FX = ['fx-squish','fx-ripple','fx-magnet','fx-wiggle','fx-shine'];
$$('.btn').forEach((b,i) => b.classList.add(BTN_FX[i % BTN_FX.length]));

/* ---------- Ripple: onda en el punto exacto del click ---------- */
document.addEventListener('pointerdown', e => {
  const btn = e.target.closest('.fx-ripple');
  if (!btn) return;
  const r = btn.getBoundingClientRect();
  const s = document.createElement('span');
  s.className = 'ripple';
  const size = Math.max(r.width, r.height) * .6;
  s.style.width = s.style.height = size + 'px';
  s.style.left = (e.clientX - r.left - size/2) + 'px';
  s.style.top  = (e.clientY - r.top  - size/2) + 'px';
  (btn.querySelector(".btn-clip") || btn).appendChild(s);
  setTimeout(()=>s.remove(), 700);
});

/* ---------- Magnet: el botón sigue al cursor dentro de su zona ---------- */
if (matchMedia('(pointer:fine)').matches){
  document.addEventListener('pointermove', e => {
    $$('.fx-magnet').forEach(btn => {
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

/* ---------- Cada click en botón lanza su ráfaga de huellitas ---------- */
document.addEventListener('click', e => {
  const b = e.target.closest('.btn');
  if (b) pawBurst(b, 3);
});

/* ============================================================
   Globos cómicos ¡GUAU! / ¡MIAU! en la landing
   ============================================================ */
function makeComicPop(text, x, y, variant){
  const pop = document.createElement('div');
  pop.className = 'guau-pop' + (variant === 'miau' ? ' miau-pop' : '') + (Math.random() > .5 ? ' flip' : '');
  text.split('').forEach((ch, i) => {
    const s = document.createElement('span');
    const cls = variant === 'miau'
      ? (i === 3 ? ' pink' : i === 4 ? ' red' : '')
      : (i === 3 ? ' yellow' : i === 4 ? ' red' : '');
    s.className = 'guau-letter' + cls;
    s.textContent = ch;
    pop.appendChild(s);
  });

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const pad = 12;
  const approxW = text.length * 22 + 36;
  const approxH = 64;
  pop.style.left = Math.min(Math.max(x - approxW/2, pad), vw - approxW - pad) + 'px';
  pop.style.top  = Math.min(Math.max(y - approxH/2, pad), vh - approxH - pad) + 'px';
  document.body.appendChild(pop);

  const isMiau = variant === 'miau';
  const letterDur = isMiau ? 360 : 420;
  const letterDelay = isMiau ? 80 : 95;
  const keyframes = isMiau
    ? [{transform:'scale(0) rotate(12deg) translateY(6px)',opacity:0},
       {transform:'scale(1.5) rotate(-6deg) translateY(-4px)',opacity:1,offset:.55},
       {transform:'scale(1) rotate(0deg) translateY(0)'}]
    : [{transform:'scale(0) rotate(-14deg)',opacity:0},
       {transform:'scale(1.45) rotate(5deg)',opacity:1,offset:.6},
       {transform:'scale(1) rotate(0deg)'}];

  [...pop.children].forEach((s, i) => {
    s.animate(keyframes, {
      duration: letterDur, delay: i * letterDelay,
      easing: 'cubic-bezier(.34,1.56,.64,1)', fill: 'backwards'
    });
  });

  const startRot = pop.classList.contains('flip') ? (isMiau ? 6 : 5) : (isMiau ? -5 : -6);
  pop.animate(
    [{transform:`rotate(${startRot}deg)`},
     {transform:`rotate(${isMiau?-6:-6}deg) scale(1.12)`,offset:.5},
     {transform:`rotate(${startRot}deg)`}],
    {duration: isMiau ? 400 : 380, delay: isMiau ? 500 : 560, easing:'ease-in-out'}
  );

  setTimeout(() => {
    pop.animate([{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(-18px)'}],
      {duration:350, easing:'ease-in'});
    setTimeout(() => pop.remove(), 360);
  }, isMiau ? 1400 : 1500);
}

function spawnComicBalloon(){
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const margin = 80;

  /* 70 % izquierda, 30 % derecha; nunca en la tercia central */
  const side = Math.random() < .7 ? 'left' : 'right';
  const x = side === 'left'
    ? rand(margin, vw * .33 - margin)
    : rand(vw * .66 + margin, vw - margin);
  const y = rand(90, vh - 90);

  if (Math.random() < .5) makeComicPop('¡GUAU!', x, y, 'guau');
  else makeComicPop('¡MIAU!', x, y, 'miau');
}

/* Primer globo tras un breve instante y luego uno cada 5 s */
setTimeout(spawnComicBalloon, 800);
setInterval(spawnComicBalloon, 5000);

/* ============================================================
   Loader, perrito que corre con el scroll y aparición al hacer scroll
   ============================================================ */
(function landingFx(){
  if (typeof FX === 'undefined') return;
  const loader = document.getElementById('page-loader');
  document.getElementById('pl-dog').innerHTML = FX.runDog();
  const hide = () => loader.classList.add('done');
  window.addEventListener('load', () => setTimeout(hide, 500));
  setTimeout(hide, 4000);

  FX.decorate(document);

  const dog = document.getElementById('scroll-dog');
  dog.innerHTML = '<div>' + FX.runDog() + '</div>';
  dog.classList.add('idle');
  let lastY = scrollY, idleT;
  const place = () => {
    const max = document.documentElement.scrollHeight - innerHeight || 1;
    const x = (scrollY / max) * (innerWidth - dog.offsetWidth);
    dog.style.transform = `translateX(${x}px)`;
    dog.classList.toggle('rev', scrollY < lastY);
    lastY = scrollY;
    dog.classList.remove('idle');
    clearTimeout(idleT);
    idleT = setTimeout(() => dog.classList.add('idle'), 180);
  };
  addEventListener('scroll', place, { passive: true });
  place();

  const els = document.querySelectorAll('.source-card, .feature .wrap > div, .section-title, .cta-img');
  els.forEach(el => el.classList.add('reveal'));
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: .15 });
  els.forEach(el => io.observe(el));
})();
