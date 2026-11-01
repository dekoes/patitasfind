/* ============================================================
   GuauWoow — Presentación de la landing
   Parte títulos y párrafos en palabras, los hace aparecer al entrar en pantalla,
   escribe el progreso de scroll (--e/--p) que usan las transiciones de landing-motion.css,
   mueve las bandas según la velocidad del scroll e inclina tarjetas con el cursor.
   Si el visitante pidió "reducir movimiento" no hace nada y todo queda quieto y visible.
   ============================================================ */
(function landingMotion(){
  'use strict';
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const root = document.documentElement;
  root.classList.add('motion');

  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => [...c.querySelectorAll(s)];
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const fino = matchMedia('(pointer:fine)').matches;

  /* ---------- Partir texto en palabras (y letras) sin perder los elementos internos ---------- */
  function partir(el, { exterior = 'w', interior = 'wi', letras = false } = {}) {
    let i = 0, ci = 0;
    const recorrer = nodo => {
      [...nodo.childNodes].forEach(n => {
        if (n.nodeType === 3) {
          const frag = document.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach(parte => {
            if (!parte) return;
            if (/^\s+$/.test(parte)) { frag.appendChild(document.createTextNode(' ')); return; }
            const w = document.createElement('span');
            w.className = exterior;
            const wi = document.createElement('span');
            wi.className = interior;
            wi.style.setProperty('--d', i++);
            if (letras) {
              [...parte].forEach(ch => {
                const c = document.createElement('span');
                c.className = 'c';
                c.textContent = ch;
                c.style.setProperty('--ci', ci++);
                wi.appendChild(c);
              });
            } else wi.textContent = parte;
            w.appendChild(wi);
            frag.appendChild(w);
          });
          n.replaceWith(frag);
        } else if (n.nodeType === 1 && n.tagName !== 'svg') recorrer(n);
      });
    };
    recorrer(el);
  }

  /* ---------- Hero ---------- */
  const hero = $('.hero');
  const h1 = $('.hero-title');
  h1.setAttribute('aria-label', h1.textContent.replace(/\s+/g, ' ').trim());
  partir(h1, { letras: true });
  $$('.w', h1).forEach(w => w.setAttribute('aria-hidden', 'true'));
  h1.classList.add('split');
  const resaltado = $('.accent', h1);
  if (resaltado) resaltado.insertAdjacentHTML('beforeend',
    '<svg class="scribble" viewBox="0 0 300 30" preserveAspectRatio="none" aria-hidden="true">' +
    '<path pathLength="1" d="M4 20 C 60 6, 120 26, 170 14 S 260 6, 296 18 M 40 26 C 110 18, 190 24, 270 22"/></svg>');
  if (fino) h1.addEventListener('pointerover', e => {
    const c = e.target.closest('.c');
    if (c && h1.classList.contains('in')) { c.classList.remove('jelly'); void c.offsetWidth; c.classList.add('jelly'); }
  });
  $$('.c', h1).forEach(c => {
    c.addEventListener('animationend', () => c.classList.remove('jelly'));
    // rumbo de cada letra cuando el hero explota al hacer scroll
    c.style.setProperty('--sx', ((Math.random() * 2 - 1) * 620).toFixed(0));
    c.style.setProperty('--sy', ((Math.random() * 1.3 - 1) * 480 - 80).toFixed(0));
    c.style.setProperty('--sr', ((Math.random() * 2 - 1) * 560).toFixed(0));
  });

  const leadHero = $('.hero-lead');
  partir(leadHero, { exterior: 'bwo', interior: 'bw' });
  leadHero.classList.add('blur-in');
  leadHero.style.setProperty('--d0', '700ms');
  $$('.hero-btns .btn').forEach((b, i) => { b.classList.add('pop-in'); b.style.setProperty('--d0', 1100 + i * 140 + 'ms'); });
  const badgeHero = $('.hero .badge');
  badgeHero.classList.add('m');

  /* ---------- Títulos, párrafos, badges y listas del resto de la página ---------- */
  const observados = [];
  $$('.section-title').forEach(t => { partir(t); t.classList.add('split'); observados.push(t); });
  $$('.section-lead').forEach(p => { partir(p, { exterior: 'bwo', interior: 'bw' }); p.classList.add('blur-in'); observados.push(p); });
  $$('.badge').forEach(b => { if (b !== badgeHero) { b.classList.add('m'); observados.push(b); } });
  $$('.feature-list').forEach(l => { $$('li', l).forEach((li, i) => li.style.setProperty('--d', i)); observados.push(l); });
  $$('.source-card').forEach(c => observados.push(c));
  $$('#donde-buscamos .source-card').forEach((c, i) => c.style.setProperty('--i0', i));
  $$('.bands').forEach(b => observados.push(b));
  const ctaImg = $('.cta-img');
  if (ctaImg) { ctaImg.classList.add('m'); observados.push(ctaImg); }
  const ctaBtn = $('.cta .btn');
  if (ctaBtn) ctaBtn.classList.add('pulse');

  /* letras que se revuelven antes de quedar fijas (badges) */
  const RUIDO = 'ABCDEFGHIJKLMNÑOPQRSTUVWXYZ#%&*+?!';
  function revolver(el) {
    const nodo = [...el.childNodes].reverse().find(n => n.nodeType === 3 && n.textContent.trim());
    if (!nodo) return;
    const final = nodo.textContent;
    const t0 = performance.now(), dur = 650;
    const paso = ahora => {
      const k = clamp((ahora - t0) / dur);
      const fijas = Math.floor(k * final.length);
      nodo.textContent = final.slice(0, fijas) + [...final.slice(fijas)]
        .map(ch => /\s/.test(ch) ? ch : RUIDO[(Math.random() * RUIDO.length) | 0]).join('');
      if (k < 1) requestAnimationFrame(paso); else nodo.textContent = final;
    };
    requestAnimationFrame(paso);
  }

  const entrar = el => {
    el.classList.add('in');
    if (el.classList.contains('badge')) revolver(el);
  };
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { entrar(e.target); io.unobserve(e.target); }
  }), { rootMargin: '0px 0px -10% 0px', threshold: 0.01 });

  /* ---------- Arranque: el hero entra cuando se va el loader ---------- */
  let listo = false;
  const arrancar = () => {
    if (listo) return;
    listo = true;
    [hero, h1, leadHero, badgeHero, $('.hero-btns')].forEach(entrar);
    setTimeout(() => $('.hero-tilt') && $('.hero-tilt').classList.add('live'), 1500);
    observados.forEach(el => io.observe(el));
  };
  document.addEventListener('landing:ready', arrancar);
  if ($('#page-loader.done')) arrancar();
  setTimeout(arrancar, 4500);

  /* ---------- Secciones que se expanden y progreso de scroll ---------- */
  // la sección que sale del portal ya llena la pantalla de menta: esa no se expande
  const features = $$('.feature, .cta').filter(s => !(s.previousElementSibling || {}).classList?.contains('portal'));
  features.forEach(s => s.classList.add('sheet'));
  $$('.feature').forEach(s => {
    const img = $('.feature-img', s);
    if (!img) return;
    const r = img.getBoundingClientRect(), rs = s.getBoundingClientRect();
    img.style.setProperty('--dir', r.left + r.width / 2 > rs.left + rs.width / 2 ? -1 : 1);
  });
  const cta = $('.cta');
  const header = $('.header');

  /* Cómo funciona: la sección se queda fija mientras las tarjetas pasan de lado */
  const hpin = $('.hpin');
  const pista = hpin && $('.hpin-track .cards', hpin);
  const cartas = pista ? $$('.source-card', pista) : [];
  let recorrido = 0;
  if (hpin) root.classList.add('hpin-on');
  function medirPasos() {
    if (!hpin) return;
    recorrido = Math.max(0, pista.scrollWidth - innerWidth);
    hpin.style.setProperty('--hpin-h', recorrido + innerHeight + 'px');
  }
  medirPasos();

  /* Portal: las letras de ADOPTA caen y luego la huella te traga */
  const portal = $('.portal');
  const portalFijo = portal && $('.portal-sticky', portal);
  const palabra = portal && $('.portal-word', portal);
  const letrasPortal = palabra ? $$('.pl', palabra) : [];
  if (portal && typeof FX !== 'undefined') {
    // perritos que se asoman detrás de la D, la T y la última A
    [[1, '#FFF6EC', '#B5763F', '-8deg', '0s'], [4, '#F2C27B', '#C98A3D', '6deg', '-.6s'], [5, '#5A463F', '#2E2420', '-4deg', '-1.1s']]
      .forEach(([i, fur, ear, hr, hd]) => {
        const ph = document.createElement('span');
        ph.className = 'ph';
        ph.style.cssText = `--hr:${hr};--hd:${hd}`;
        ph.innerHTML = '<i>' + FX.dogFace(100, { fur, ear }) + '</i>';
        letrasPortal[i].prepend(ph);
      });
    // huesos, huellas y corazones alrededor (x, y en %, tamaño, tipo, rumbo al salir)
    const HUELLA = '<svg viewBox="0 0 64 64"><use href="#paw"/></svg>';
    const CORAZON = '<svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.6 4.5c2.1 0 3.6 1.2 4.4 2.6.8-1.4 2.3-2.6 4.4-2.6 3.6 0 5.7 3.9 4.2 7.3C19.5 16.4 12 21 12 21z"/></svg>';
    const adornos = [
      [12, 20, 64, 'bone', -70, -60, '#fff'], [86, 16, 52, 'heart', 70, -70], [7, 58, 56, 'paw', -90, 10, 'var(--teal)'],
      [92, 56, 70, 'bone', 90, 10, 'var(--pink)'], [20, 84, 48, 'heart', -60, 70], [80, 84, 58, 'paw', 60, 80, 'var(--orange)'],
      [50, 10, 44, 'paw', 0, -90, 'var(--purple)'], [32, 14, 40, 'heart', -30, -90], [66, 88, 50, 'bone', 30, 90, 'var(--lila)'],
      [95, 32, 40, 'paw', 95, -30, 'var(--teal)'], [4, 36, 42, 'heart', -95, -20], [62, 18, 54, 'bone', 40, -90, 'var(--mint)'],
    ];
    const deco = $('.portal-deco', portal);
    adornos.forEach(([x, y, s, tipo, fx, fy, color], k) => {
      const f = document.createElement('span');
      f.className = 'pf ' + tipo;
      f.style.cssText = `--x:${x}%;--y:${y}%;--s:clamp(${Math.round(s * .55)}px, ${(s / 12).toFixed(1)}vw, ${s}px);--fx:${fx};--fy:${fy};` +
        `--t:${(.04 + k * .025).toFixed(3)};--r:${(k % 2 ? 1 : -1) * (10 + k * 7)}deg;--f:${(2.8 + (k % 4) * .5).toFixed(1)}s;--fd:${(-k * .4).toFixed(1)}s` +
        (tipo === 'paw' ? `;--pc:${color}` : '');
      f.innerHTML = '<i>' + (tipo === 'bone' ? FX.bone(color, 64) : tipo === 'paw' ? HUELLA : CORAZON) + '</i>';
      deco.appendChild(f);
    });
    // huellitas que cruzan de izquierda a derecha
    const rastro = $('.portal-trail', portal);
    for (let k = 0; k < 12; k++) {
      const h = document.createElement('i');
      h.style.cssText = `--x:${(4 + k * 8).toFixed(1)}%;--y:${k % 2 ? 4 : 30}px;--t:${(.2 + k * .022).toFixed(3)}`;
      h.innerHTML = HUELLA;
      rastro.appendChild(h);
    }
  }
  let escalaPortal = 30;
  function medirPortal() {
    if (!palabra) return;
    const o = $('.portal-o', palabra);  // centro del cojinete grande de la huella (cy 40 de 64)
    const ox = o.offsetLeft + o.offsetWidth * .5, oy = o.offsetTop + o.offsetHeight * (40 / 64);
    palabra.style.setProperty('--pox', ox + 'px');
    palabra.style.setProperty('--poy', oy + 'px');
    portalFijo.style.setProperty('--rcx', palabra.offsetLeft + ox + 'px');
    portalFijo.style.setProperty('--rcy', palabra.offsetTop + oy + 'px');
    // escala a la que el cojinete (24 de 64 de alto) ya cubre toda la pantalla
    escalaPortal = Math.hypot(innerWidth, innerHeight) / (o.offsetHeight * 24 / 64) * 1.05;
  }
  medirPortal();
  const easeOutBack = t => { const c = 1.9; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); };

  let confetiLanzado = false;
  function actualizarScroll() {
    const vh = innerHeight;
    const rh = hero.getBoundingClientRect();
    hero.style.setProperty('--e', easeOut(clamp(-rh.top / (rh.height * .9))).toFixed(4));
    // entre que la sección asoma abajo y su borde llega al 25 % de la pantalla
    const entrada = (el, fin = .25) => clamp((vh - el.getBoundingClientRect().top) / (vh * (1 - fin)));
    features.forEach(s => s.style.setProperty('--e', easeOut(entrada(s)).toFixed(4)));

    if (hpin) {
      const r = hpin.getBoundingClientRect();
      const p = clamp(-r.top / Math.max(1, r.height - vh));
      pista.style.setProperty('--tx', (-p * recorrido).toFixed(1) + 'px');
      hpin.style.setProperty('--hp', p.toFixed(4));
      cartas.forEach(c => {
        const rc = c.getBoundingClientRect();
        const k = clamp((rc.left + rc.width / 2 - innerWidth / 2) / (innerWidth * .55), -1, 1);
        c.style.setProperty('--cf-ry', (-k * 42).toFixed(2) + 'deg');
        c.style.setProperty('--cf-s', (1 - Math.abs(k) * .2).toFixed(3));
        c.style.setProperty('--cf-on', (1 - Math.abs(k)).toFixed(3));
      });
    }

    if (portal) {
      const r = portal.getBoundingClientRect();
      // el zoom termina justo cuando la sección siguiente (que sube encima) asoma por abajo
      const finZoom = r.height - 2 * vh, inicioZoom = finZoom - 1.1 * vh;
      // las letras empiezan a caer desde que el portal asoma, antes de quedar fijo
      const pl = clamp((vh * .75 - r.top) / (inicioZoom + vh * .75));
      letrasPortal.forEach((l, i) => {
        // caen con rebote (se pasan del piso y regresan) y se aplastan al aterrizar
        const t = clamp((pl - i * .035) / .2);
        l.style.setProperty('--l', easeOutBack(t).toFixed(4));
        l.style.setProperty('--sq', (t > .55 && t < 1 ? Math.sin((t - .55) / .45 * Math.PI) : 0).toFixed(3));
      });
      const z = clamp((-r.top - inicioZoom) / (finZoom - inicioZoom));
      const fijo = portalFijo.style;
      fijo.setProperty('--pl', pl.toFixed(4));
      fijo.setProperty('--hp', easeOutBack(clamp((pl - .3) / .1)).toFixed(3));
      fijo.setProperty('--sub', clamp((pl - .34) / .12).toFixed(3));
      fijo.setProperty('--z', z.toFixed(4));
      fijo.setProperty('--zp', Math.pow(clamp(z * 1.7), 2).toFixed(4));  // las letras se abren como cortina
      portalFijo.classList.toggle('zoom', z > 0);
      palabra.style.setProperty('--ps', (1 + Math.pow(z, 2.6) * (escalaPortal - 1)).toFixed(3));
    }

    if (cta) {
      const r = cta.getBoundingClientRect();
      const p = clamp((vh - r.top) / (vh + r.height));
      cta.style.setProperty('--p', p.toFixed(4));
      if (!confetiLanzado && p > .45) { confetiLanzado = true; confeti(); }
    }
    header.classList.toggle('pill', scrollY > 60);
  }

  /* lluvia de huellitas y papelitos con los colores de la marca */
  function confeti() {
    const colores = ['#33C7BE', '#FF8A5C', '#DCC7FA', '#86E0D4', '#FF5A5A', '#B794F4', '#F6C8A4'];
    for (let i = 0; i < 46; i++) {
      const c = document.createElement('div');
      c.className = 'mconf';
      c.setAttribute('aria-hidden', 'true');
      const color = colores[i % colores.length];
      if (i % 4 === 0) { c.innerHTML = '<svg viewBox="0 0 64 64"><use href="#paw"/></svg>'; c.style.color = color; c.style.setProperty('--w', '22px'); }
      else c.style.background = color;
      c.style.left = (Math.random() * 100).toFixed(1) + 'vw';
      c.style.setProperty('--dx', ((Math.random() * 2 - 1) * 160).toFixed(0) + 'px');
      c.style.setProperty('--rt', ((Math.random() * 2 - 1) * 900).toFixed(0) + 'deg');
      c.style.setProperty('--t', (1.8 + Math.random() * 1.6).toFixed(2) + 's');
      c.style.setProperty('--dl', (Math.random() * .5).toFixed(2) + 's');
      document.body.appendChild(c);
      setTimeout(() => c.remove(), 4500);
    }
  }

  /* ---------- Bandas: avanzan solas y aceleran (o se voltean) con el scroll ---------- */
  const bandas = $$('.band').map((b, i) => {
    const pista = $('.band-track', b);
    const unidad = pista.innerHTML;
    let veces = 1;
    pista.innerHTML = unidad;
    while (pista.scrollWidth < b.clientWidth * 1.2 && veces < 12) pista.innerHTML = unidad.repeat(++veces);
    pista.innerHTML = unidad.repeat(veces) + unidad.repeat(veces);
    return { b, pista, x: 0, sentido: i % 2 ? -1 : 1, ancho: pista.scrollWidth / 2, visible: false };
  });
  const bio = new IntersectionObserver(es => es.forEach(e => {
    const bd = bandas.find(x => x.b === e.target);
    if (bd) bd.visible = e.isIntersecting;
  }));
  bandas.forEach(bd => bio.observe(bd.b));

  let ultimoY = scrollY, vel = 0, dir = 1, sucio = true;
  addEventListener('scroll', () => { sucio = true; }, { passive: true });
  addEventListener('resize', () => {
    sucio = true;
    bandas.forEach(bd => { bd.ancho = bd.pista.scrollWidth / 2; });
    medirPasos();
    medirPortal();
  });
  addEventListener('load', () => { medirPasos(); medirPortal(); sucio = true; });

  let inclinacion = 0;
  function cuadro() {
    const dy = scrollY - ultimoY;
    ultimoY = scrollY;
    if (dy) dir = Math.sign(dy);
    vel += (Math.abs(dy) - vel) * .12;
    // gelatina: los títulos se ladean con la velocidad y regresan solos
    const meta = clamp(dy * .18, -7, 7);
    inclinacion += (meta - inclinacion) * .15;
    if (Math.abs(inclinacion) > .02 || inclinacion !== 0) {
      if (Math.abs(inclinacion) < .02) inclinacion = 0;
      root.style.setProperty('--skew', inclinacion.toFixed(2));
    }
    bandas.forEach(bd => {
      if (!bd.visible) return;
      bd.x += (1.1 + vel * .6) * bd.sentido * dir;
      bd.x = ((bd.x % bd.ancho) + bd.ancho) % bd.ancho;
      bd.pista.style.transform = `translate3d(${-bd.x}px,0,0)`;
    });
    if (sucio) { sucio = false; actualizarScroll(); }
    requestAnimationFrame(cuadro);
  }
  requestAnimationFrame(cuadro);

  /* ---------- Cursor: inclinación 3D, brillo y anillo (solo con mouse) ---------- */
  if (!fino) return;

  const escenario = $('.hero-stage');
  hero.addEventListener('pointermove', e => {
    const r = hero.getBoundingClientRect();
    const nx = (e.clientX - r.left) / r.width - .5, ny = (e.clientY - r.top) / r.height - .5;
    escenario.style.setProperty('--ry', (nx * 22).toFixed(2) + 'deg');
    escenario.style.setProperty('--rx', (-ny * 16).toFixed(2) + 'deg');
  });
  hero.addEventListener('pointerleave', () => {
    escenario.style.setProperty('--ry', '0deg');
    escenario.style.setProperty('--rx', '0deg');
  });

  const brillo = (el, e) => {
    const r = el.getBoundingClientRect();
    el.style.setProperty('--gx', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%');
    el.style.setProperty('--gy', ((e.clientY - r.top) / r.height * 100).toFixed(1) + '%');
    el.classList.add('lit');
    return [(e.clientX - r.left) / r.width - .5, (e.clientY - r.top) / r.height - .5];
  };
  $$('.hero-img, .source-card, .feature-img').forEach(el => el.classList.add('glare'));
  $('.hero-img').addEventListener('pointermove', e => brillo(e.currentTarget, e));
  $('.hero-img').addEventListener('pointerleave', e => e.currentTarget.classList.remove('lit'));

  $$('.source-card').forEach(c => {
    c.classList.add('tilt');
    c.addEventListener('pointermove', e => {
      const [nx, ny] = brillo(c, e);
      c.style.rotate = `${-ny} ${nx} 0 ${(Math.hypot(nx, ny) * 16).toFixed(2)}deg`;
    });
    c.addEventListener('pointerleave', () => { c.style.rotate = ''; c.classList.remove('lit'); });
  });
  $$('.feature-img').forEach(f => {
    f.addEventListener('pointermove', e => {
      const [nx, ny] = brillo(f, e);
      f.style.setProperty('--ry', (nx * 14).toFixed(2) + 'deg');
      f.style.setProperty('--rx', (-ny * 10).toFixed(2) + 'deg');
    });
    f.addEventListener('pointerleave', () => {
      f.style.setProperty('--ry', '0deg');
      f.style.setProperty('--rx', '0deg');
      f.classList.remove('lit');
    });
  });

  const anillo = document.createElement('div');
  anillo.className = 'cursor-ring';
  anillo.setAttribute('aria-hidden', 'true');
  document.body.appendChild(anillo);
  let mx = -100, my = -100, ax = -100, ay = -100;
  addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse') return;
    mx = e.clientX; my = e.clientY;
    anillo.classList.add('on');
    anillo.classList.toggle('big', !!e.target.closest('a, button, .btn'));
  }, { passive: true });
  document.addEventListener('pointerleave', () => anillo.classList.remove('on'));
  (function seguir() {
    ax += (mx - ax) * .2; ay += (my - ay) * .2;
    anillo.style.transform = `translate3d(${ax}px,${ay}px,0)`;
    requestAnimationFrame(seguir);
  })();
})();
