/* ============================================================
   PatitasFind — FX: perritos animados, loaders y efectos
   ============================================================ */
'use strict';

const FX = (() => {
  const rand = (a, b) => a + Math.random() * (b - a);
  const INK = '#1D2233';

  const PAW = '<svg viewBox="0 0 64 64" width="100%" height="100%" aria-hidden="true"><use href="#paw"/></svg>';
  const HEART = '<svg viewBox="0 0 24 24" width="100%" height="100%" aria-hidden="true"><use href="#heart"/></svg>';

  function bone(fill = '#fff', size = 42, cls = '') {
    const shapes = '<rect x="18" y="26" width="28" height="12" rx="6"/><circle cx="15" cy="26" r="7"/><circle cx="15" cy="38" r="7"/><circle cx="49" cy="26" r="7"/><circle cx="49" cy="38" r="7"/>';
    return `<svg class="${cls}" viewBox="0 0 64 64" width="${size}" height="${size}" aria-hidden="true"><g transform="rotate(-35 32 32)"><g fill="${INK}" stroke="${INK}" stroke-width="5">${shapes}</g><g fill="${fill}">${shapes}</g></g></svg>`;
  }

  /* Cara de perrito frontal animada (orejas, parpadeo, lengua) */
  function dogFace(size = 90, o = {}) {
    const fur = o.fur || '#FFF6EC', ear = o.ear || '#B5763F', snout = o.snout || '#F6C8A4';
    return `<svg class="dog-anim" viewBox="0 0 120 120" width="${size}" height="${size}" aria-hidden="true">
      <path class="da-ear" d="M24 28 Q4 32 9 62 Q12 84 31 77 Q24 55 30 37 Z" fill="${ear}" stroke="${INK}" stroke-width="3"/>
      <path class="da-ear r" d="M96 28 Q116 32 111 62 Q108 84 89 77 Q96 55 90 37 Z" fill="${ear}" stroke="${INK}" stroke-width="3"/>
      <circle cx="60" cy="64" r="41" fill="${fur}" stroke="${INK}" stroke-width="3"/>
      <ellipse class="da-eye" cx="45" cy="57" rx="5" ry="6" fill="${INK}"/>
      <ellipse class="da-eye" cx="75" cy="57" rx="5" ry="6" fill="${INK}"/>
      <circle cx="47" cy="55" r="1.6" fill="#fff"/><circle cx="77" cy="55" r="1.6" fill="#fff"/>
      <ellipse cx="60" cy="81" rx="18" ry="14" fill="${snout}" stroke="${INK}" stroke-width="2.5"/>
      ${o.tongue === false ? '' : `<path class="da-tongue" d="M54 88 Q54 100 60 100 Q66 100 66 88 Z" fill="#F49AC1" stroke="${INK}" stroke-width="2.5"/>`}
      <ellipse cx="60" cy="74" rx="7.5" ry="5.5" fill="${INK}"/>
      <path d="M60 79 Q60 86 53 87 M60 79 Q60 86 67 87" stroke="${INK}" stroke-width="3" fill="none" stroke-linecap="round"/>
      <circle cx="33" cy="72" r="5.5" fill="#F49AC1" opacity=".75"/><circle cx="87" cy="72" r="5.5" fill="#F49AC1" opacity=".75"/>
    </svg>`;
  }

  /* Perrito corriendo de perfil */
  function runDog() {
    const fur = '#E0A160', far = '#B5763F';
    const leg = (x, cls, c) => `<rect class="rd-leg ${cls}" x="${x}" y="58" width="10" height="27" rx="5" fill="${c}" stroke="${INK}" stroke-width="2.5"/>`;
    return `<svg class="run-dog" viewBox="0 0 150 100" aria-hidden="true">
      <line class="rd-ground" x1="0" y1="95" x2="150" y2="95" stroke="${INK}" stroke-width="3" stroke-linecap="round" stroke-dasharray="14 14" opacity=".25"/>
      <circle class="rd-dust" cx="26" cy="88" r="5" fill="${INK}" opacity=".2"/>
      <circle class="rd-dust d2" cx="34" cy="90" r="4" fill="${INK}" opacity=".2"/>
      <g class="rd-all">
        <g class="rd-tail"><path d="M38 50 Q24 46 20 30" stroke="${INK}" stroke-width="11" fill="none" stroke-linecap="round"/><path d="M38 50 Q24 46 20 30" stroke="${fur}" stroke-width="5.5" fill="none" stroke-linecap="round"/></g>
        ${leg(44, 'b', far)}${leg(90, 'b', far)}
        <ellipse cx="68" cy="56" rx="34" ry="17" fill="${fur}" stroke="${INK}" stroke-width="2.5"/>
        <ellipse cx="62" cy="61" rx="16" ry="7" fill="#FBE3B0" opacity=".7"/>
        ${leg(50, '', fur)}${leg(96, '', fur)}
        <path d="M94 44 L101 58" stroke="#33C7BE" stroke-width="6" stroke-linecap="round"/>
        <circle cx="108" cy="37" r="17" fill="${fur}" stroke="${INK}" stroke-width="2.5"/>
        <path class="rd-tongue" d="M118 48 Q117 60 122 60 Q127 60 126 48 Z" fill="#F49AC1" stroke="${INK}" stroke-width="2.2"/>
        <ellipse cx="123" cy="44" rx="11" ry="7.5" fill="#FBE3B0" stroke="${INK}" stroke-width="2.5"/>
        <circle cx="132" cy="40.5" r="3.8" fill="${INK}"/>
        <circle cx="111" cy="32" r="3" fill="${INK}"/><circle cx="112" cy="31" r="1" fill="#fff"/>
        <path class="rd-ear" d="M98 23 Q90 27 93 45 Q100 43 102 30 Z" fill="#7A5238" stroke="${INK}" stroke-width="2.5"/>
      </g>
    </svg>`;
  }

  /* Perrito dormido con Zzz */
  function sleepDog() {
    return `<svg class="sleep-dog" viewBox="0 0 150 110" aria-hidden="true">
      <text class="sl-z" x="112" y="44" font-size="18">z</text>
      <text class="sl-z z2" x="120" y="36" font-size="22">z</text>
      <text class="sl-z z3" x="128" y="26" font-size="26">Z</text>
      <ellipse cx="75" cy="102" rx="58" ry="6" fill="${INK}" opacity=".1"/>
      <g class="sl-tail"><path d="M30 92 Q8 92 14 74" stroke="${INK}" stroke-width="11" fill="none" stroke-linecap="round"/><path d="M30 92 Q8 92 14 74" stroke="#E0A160" stroke-width="5.5" fill="none" stroke-linecap="round"/></g>
      <g class="sl-body"><ellipse cx="70" cy="80" rx="46" ry="22" fill="#E0A160" stroke="${INK}" stroke-width="2.8"/>
      <ellipse cx="62" cy="88" rx="22" ry="8" fill="#FBE3B0" opacity=".7"/></g>
      <path d="M86 98 Q90 90 104 96" stroke="${INK}" stroke-width="2.5" fill="#E0A160"/>
      <circle cx="108" cy="78" r="19" fill="#E0A160" stroke="${INK}" stroke-width="2.8"/>
      <path d="M95 64 Q86 68 90 88 Q98 86 100 70 Z" fill="#7A5238" stroke="${INK}" stroke-width="2.5"/>
      <ellipse cx="122" cy="86" rx="10" ry="7" fill="#FBE3B0" stroke="${INK}" stroke-width="2.5"/>
      <circle cx="130" cy="83" r="3.4" fill="${INK}"/>
      <path d="M106 76 Q110 80 114 76" stroke="${INK}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      <circle cx="104" cy="85" r="3.5" fill="#F49AC1" opacity=".7"/>
    </svg>`;
  }

  /* Perrito olfateando con lupa (búsqueda) */
  function sniffDog() {
    return `<svg class="sniff-dog" viewBox="0 0 130 110" aria-hidden="true">
      <ellipse cx="62" cy="102" rx="54" ry="5" fill="${INK}" opacity=".1"/>
      <g class="sd-tail"><path d="M24 56 Q10 50 8 34" stroke="${INK}" stroke-width="11" fill="none" stroke-linecap="round"/><path d="M24 56 Q10 50 8 34" stroke="#fff" stroke-width="5.5" fill="none" stroke-linecap="round"/></g>
      <rect x="28" y="64" width="10" height="34" rx="5" fill="#fff" stroke="${INK}" stroke-width="2.5"/>
      <rect x="62" y="64" width="10" height="34" rx="5" fill="#fff" stroke="${INK}" stroke-width="2.5"/>
      <ellipse cx="50" cy="60" rx="30" ry="16" fill="#fff" stroke="${INK}" stroke-width="2.5"/>
      <circle cx="40" cy="56" r="7" fill="#1D2233" opacity=".85"/>
      <g class="sd-head">
        <circle cx="84" cy="66" r="15" fill="#fff" stroke="${INK}" stroke-width="2.5"/>
        <ellipse cx="96" cy="77" rx="10" ry="7" fill="#fff" stroke="${INK}" stroke-width="2.5"/>
        <circle class="sd-nose" cx="104" cy="79" r="3.6" fill="${INK}"/>
        <circle cx="87" cy="62" r="2.6" fill="${INK}"/>
        <path d="M74 54 Q66 58 70 74 Q77 72 78 60 Z" fill="${INK}"/>
      </g>
      <g class="sd-lens"><circle cx="108" cy="58" r="13" fill="rgba(169,214,249,.55)" stroke="${INK}" stroke-width="3.5"/><path d="M99 68 L90 80" stroke="${INK}" stroke-width="6" stroke-linecap="round"/><path d="M103 52 Q106 49 110 50" stroke="#fff" stroke-width="2.5" fill="none" stroke-linecap="round"/></g>
    </svg>`;
  }

  function pawTrail() {
    return `<div class="paw-trail" aria-hidden="true">${('<i>' + PAW + '</i>').repeat(6)}</div>`;
  }

  function tailChase() {
    return `<div class="tail-chase" aria-hidden="true"><div class="tc-track"></div><div class="tc-spin"><div class="tc-dog">${dogFace(30, { tongue: false })}</div><div class="tc-tail"></div></div></div>`;
  }

  /* Loader en línea para listas */
  function inlineLoader(msg = 'Buscando perritos...') {
    return `<div class="center" style="padding:36px 0">${pawTrail().replace('class="paw-trail"', 'class="paw-trail" style="margin:0 auto"')}<div class="small muted mt12">${msg}</div></div>`;
  }

  function skeletonList(n = 4) {
    return Array.from({ length: n }, (_, i) => `<div class="skel" style="height:78px;padding:14px 14px 14px 84px;animation-delay:${i * 80}ms">
      <div style="position:absolute;left:14px;top:12px;width:54px;height:54px;border-radius:16px;background:rgba(29,34,51,.08)"></div>
      <div class="skel-line" style="width:60%;margin-top:4px"></div><div class="skel-line" style="width:40%"></div>
      <i class="skel-paw">${PAW}</i></div>`).join('');
  }
  function skeletonCards(n = 3) {
    return Array.from({ length: n }, () => `<div class="skel" style="flex-shrink:0;width:176px;height:196px"><i class="skel-paw">${PAW}</i></div>`).join('');
  }

  function empty(title, text = '', btn = null) {
    return `<div class="empty pop-in">${sleepDog()}<h3>${title}</h3>${text ? `<p>${text}</p>` : ''}${btn ? `<button class="btn btn-sm" data-empty-action="${btn.action}">${btn.label}</button>` : ''}</div>`;
  }

  /* ---------- capas ---------- */
  let device, fxLayer, pawLayer;
  function rel(el) {
    const r = el.getBoundingClientRect(), d = device.getBoundingClientRect();
    return { x: r.left - d.left + r.width / 2, y: r.top - d.top + r.height / 2, w: r.width, h: r.height };
  }

  function pawBurst(el, n = 4) {
    const p = rel(el);
    for (let i = 0; i < n; i++) {
      const m = document.createElement('div');
      m.className = 'mini-paw';
      m.innerHTML = PAW;
      m.style.left = (p.x - 8 + rand(-p.w / 3, p.w / 3)) + 'px';
      m.style.top = (p.y - p.h / 2 + rand(-4, 6)) + 'px';
      m.style.setProperty('--dx', rand(-30, 30).toFixed(0) + 'px');
      m.style.setProperty('--rot', rand(-40, 40).toFixed(0) + 'deg');
      pawLayer.appendChild(m);
      setTimeout(() => m.remove(), 950);
    }
  }

  function heartBurst(el, n = 8) {
    const p = rel(el);
    for (let i = 0; i < n; i++) {
      const h = document.createElement('div');
      h.className = 'heart-fly';
      h.innerHTML = HEART;
      h.style.left = (p.x - 10) + 'px';
      h.style.top = (p.y - 10) + 'px';
      h.style.setProperty('--dx', rand(-60, 60).toFixed(0) + 'px');
      h.style.setProperty('--rot', rand(-45, 45).toFixed(0) + 'deg');
      h.style.animationDelay = (i * 40) + 'ms';
      fxLayer.appendChild(h);
      setTimeout(() => h.remove(), 1400);
    }
  }

  function boneBurst(el, n = 6) {
    const p = rel(el);
    for (let i = 0; i < n; i++) {
      const b = document.createElement('div');
      b.className = 'bone-fly';
      b.innerHTML = bone(['#fff', '#B794F4', '#86E0D4', '#DCC7FA'][i % 4], 26);
      b.style.left = (p.x - 13) + 'px';
      b.style.top = (p.y - 13) + 'px';
      const ang = (Math.PI * 2 * i) / n + rand(-.3, .3);
      b.style.setProperty('--dx', (Math.cos(ang) * rand(60, 110)).toFixed(0) + 'px');
      b.style.setProperty('--dy', (Math.sin(ang) * rand(60, 110) - 30).toFixed(0) + 'px');
      b.style.setProperty('--rot', rand(-540, 540).toFixed(0) + 'deg');
      fxLayer.appendChild(b);
      setTimeout(() => b.remove(), 1300);
    }
  }

  function confetti(n = 34) {
    const colors = ['#8E66D9', '#F6C8A4', '#A9D6F9', '#DCC7FA', '#86E0D4', '#33C7BE'];
    const w = device.clientWidth;
    for (let i = 0; i < n; i++) {
      const c = document.createElement('div');
      const isPaw = i % 5 === 0;
      c.className = 'confetti' + (isPaw ? ' paw' : '');
      if (isPaw) { c.innerHTML = PAW; c.style.color = colors[i % colors.length]; }
      else c.style.background = colors[i % colors.length];
      c.style.left = rand(w * .15, w * .85) + 'px';
      c.style.top = rand(-30, 60) + 'px';
      c.style.setProperty('--dx', rand(-90, 90).toFixed(0) + 'px');
      c.style.setProperty('--dy', rand(400, 760).toFixed(0) + 'px');
      c.style.setProperty('--rot', rand(360, 1000).toFixed(0) + 'deg');
      c.style.animationDelay = rand(0, 300).toFixed(0) + 'ms';
      fxLayer.appendChild(c);
      setTimeout(() => c.remove(), 2300);
    }
  }

  /* ---------- botones: orejitas, colita, ripple, cargando ---------- */
  const EAR_COLORS = { 'btn-orange': '#B5763F', 'btn-ghost': '#B794F4', 'btn-white': '#B794F4', 'btn-lila': '#8E66D9', 'btn-green': '#21A39B' };
  function decorate(root = document) {
    root.querySelectorAll('.btn:not([data-fx])').forEach(b => {
      b.dataset.fx = '1';
      const label = document.createElement('span');
      label.className = 'btn-label';
      while (b.firstChild) label.appendChild(b.firstChild);
      b.appendChild(label);
      b.insertAdjacentHTML('afterbegin', '<span class="btn-clip"></span><span class="ears" aria-hidden="true"><i></i><i></i></span>');
      if (!b.classList.contains('btn-sm')) b.insertAdjacentHTML('beforeend', '<span class="tail" aria-hidden="true"></span>');
      b.insertAdjacentHTML('beforeend', `<span class="btn-paws" aria-hidden="true"><i>${PAW}</i><i>${PAW}</i><i>${PAW}</i></span>`);
      const k = Object.keys(EAR_COLORS).find(c => b.classList.contains(c));
      if (k) b.style.setProperty('--ear', EAR_COLORS[k]);
    });
  }

  function setLoading(btn, on) {
    if (!btn) return;
    btn.classList.toggle('loading', !!on);
    btn.disabled = !!on;
  }

  /* ---------- overlay de carga ---------- */
  let loTimer = null;
  function showLoading(msg = 'Cargando...', tips = [], kind = 'run') {
    const o = document.getElementById('loading-overlay');
    o.querySelector('.lo-art').innerHTML = kind === 'sniff' ? sniffDog() : kind === 'chase' ? tailChase() : runDog();
    o.querySelector('.lo-msg').textContent = msg;
    const sub = o.querySelector('.lo-sub');
    sub.textContent = tips[0] || '';
    clearInterval(loTimer);
    if (tips.length > 1) {
      let i = 0;
      loTimer = setInterval(() => { i = (i + 1) % tips.length; sub.textContent = tips[i]; }, 1800);
    }
    o.classList.add('show');
  }
  function hideLoading() {
    clearInterval(loTimer);
    document.getElementById('loading-overlay').classList.remove('show');
  }

  /* ---------- éxito ---------- */
  function success(title, sub = '', ms = 1700) {
    const s = document.getElementById('success-pop');
    s.querySelector('.sp-dog').innerHTML = dogFace(110);
    s.querySelector('.sp-title').textContent = title;
    s.querySelector('.sp-sub').textContent = sub;
    s.classList.add('show');
    confetti(30);
    return new Promise(r => setTimeout(() => { s.classList.remove('show'); r(); }, ms));
  }

  function init(dev) {
    device = dev;
    fxLayer = document.getElementById('fxLayer');
    pawLayer = document.getElementById('pawLayer');

    // ripple + huellitas en cada botón
    device.addEventListener('pointerdown', e => {
      const btn = e.target.closest('.btn');
      if (btn) {
        const clip = btn.querySelector('.btn-clip') || btn;
        const r = btn.getBoundingClientRect();
        const s = document.createElement('span');
        const size = Math.max(r.width, r.height);
        s.className = 'ripple';
        s.style.width = s.style.height = size + 'px';
        s.style.left = (e.clientX - r.left - size / 2) + 'px';
        s.style.top = (e.clientY - r.top - size / 2) + 'px';
        clip.appendChild(s);
        setTimeout(() => s.remove(), 700);
        btn.classList.add('pressed');
        setTimeout(() => btn.classList.remove('pressed'), 450);
      }
      // huellita suave donde se toca (fuera de inputs)
      if (!e.target.closest('input,textarea,select,.tcard,#leaflet-map')) {
        const d = device.getBoundingClientRect();
        const p = document.createElement('div');
        p.className = 'touch-paw';
        p.innerHTML = PAW;
        p.style.left = (e.clientX - d.left - 15) + 'px';
        p.style.top = (e.clientY - d.top - 15) + 'px';
        p.style.setProperty('--rot', rand(-35, 35).toFixed(0) + 'deg');
        pawLayer.appendChild(p);
        setTimeout(() => p.remove(), 2200);
      }
    });
    device.addEventListener('click', e => {
      const btn = e.target.closest('.btn');
      if (btn && !btn.disabled) pawBurst(btn, 3);
    });

    // fondo de huellitas
    const bg = document.getElementById('bg');
    for (let i = 0; i < 14; i++) {
      const p = document.createElement('div');
      p.className = 'bg-paw';
      p.innerHTML = PAW;
      const size = rand(30, 90).toFixed(0);
      p.style.width = p.style.height = size + 'px';
      p.style.left = rand(0, 94).toFixed(1) + 'vw';
      p.style.top = rand(0, 92).toFixed(1) + 'vh';
      p.style.setProperty('--rot', rand(-40, 40).toFixed(0) + 'deg');
      p.style.animationDuration = rand(4, 9).toFixed(1) + 's';
      p.style.animationDelay = (-rand(0, 6)).toFixed(1) + 's';
      bg.appendChild(p);
    }
  }

  return { PAW, HEART, bone, dogFace, runDog, sleepDog, sniffDog, pawTrail, tailChase, inlineLoader, skeletonList, skeletonCards, empty,
    pawBurst, heartBurst, boneBurst, confetti, decorate, setLoading, showLoading, hideLoading, success, init, rand };
})();
