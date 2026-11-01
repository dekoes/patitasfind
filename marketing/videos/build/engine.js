/* Motor de animación determinista para los videos de GuauWoow.
   Cada efecto registra una función update(t) que calcula su estado solo a partir del tiempo,
   así cada cuadro se puede renderizar en cualquier orden (render cuadro por cuadro con Playwright). */
(function () {
  const W = 1080, H = 1920;

  const E = {
    lin: x => x,
    outCubic: x => 1 - Math.pow(1 - x, 3),
    inCubic: x => x * x * x,
    inOutCubic: x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    outQuint: x => 1 - Math.pow(1 - x, 5),
    outBack: x => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
    outBackBig: x => { const c1 = 3, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
    outElastic: x => (x === 0 ? 0 : x === 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (2 * Math.PI) / 3) + 1),
    outBounce: x => {
      const n1 = 7.5625, d1 = 2.75;
      if (x < 1 / d1) return n1 * x * x;
      if (x < 2 / d1) return n1 * (x -= 1.5 / d1) * x + 0.75;
      if (x < 2.5 / d1) return n1 * (x -= 2.25 / d1) * x + 0.9375;
      return n1 * (x -= 2.625 / d1) * x + 0.984375;
    },
  };
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const prog = (t, a, b) => clamp((t - a) / (b - a));
  const lerp = (a, b, x) => a + (b - a) * x;
  function rng(seed) { let s = (seed >>> 0) || 1; return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296); }

  function el(tag, cls, parent, html) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html !== undefined) n.innerHTML = html;
    if (parent) parent.appendChild(n);
    return n;
  }
  function place(n, x, y, anchor = 'c') {
    n.style.left = x + 'px';
    n.style.top = y + 'px';
    n.dataset.anchor = anchor;
  }
  const ANCHOR = { c: '-50%,-50%', l: '0,-50%', r: '-100%,-50%', tl: '0,0', tr: '-100%,0', bl: '0,-100%', br: '-100%,-100%', t: '-50%,0', b: '-50%,-100%' };
  function tf(n, { x = 0, y = 0, s = 1, sx, sy, r = 0, skx = 0 } = {}) {
    const a = ANCHOR[n.dataset.anchor || 'c'];
    n.style.transform = `translate(${a.split(',')[0]},${a.split(',')[1]}) translate(${x}px,${y}px) rotate(${r}deg) skewX(${skx}deg) scale(${sx ?? s},${sy ?? s})`;
  }

  // ---------------------------------------------------------------- SVG
  const PAW = '<svg viewBox="0 0 64 64"><ellipse cx="32" cy="40" rx="15" ry="12"/><ellipse cx="14" cy="26" rx="7" ry="9" transform="rotate(-18 14 26)"/><ellipse cx="26" cy="17" rx="7" ry="9"/><ellipse cx="40" cy="17" rx="7" ry="9"/><ellipse cx="51" cy="26" rx="7" ry="9" transform="rotate(18 51 26)"/></svg>';
  const HEART = '<svg viewBox="0 0 24 22"><path d="M12 21.5S1 14.6 1 7.4C1 3.6 3.8 1 7 1c2.2 0 3.9 1.2 5 2.9C13.1 2.2 14.8 1 17 1c3.2 0 6 2.6 6 6.4 0 7.2-11 14.1-11 14.1z"/></svg>';
  const SPARK = '<svg viewBox="0 0 24 24"><path d="M12 0l2.6 9.4L24 12l-9.4 2.6L12 24l-2.6-9.4L0 12l9.4-2.6z"/></svg>';
  const PIN = '<svg viewBox="0 0 24 32"><path d="M12 0C5.4 0 0 5.2 0 11.7 0 20.4 12 32 12 32s12-11.6 12-20.3C24 5.2 18.6 0 12 0z"/><circle cx="12" cy="11.5" r="4.6" fill="#fff"/></svg>';
  const SHIELD = '<svg viewBox="0 0 24 28"><path d="M12 0l11 4v8.5C23 20 18.3 25.6 12 28 5.7 25.6 1 20 1 12.5V4z"/><path d="M6.5 14l4 4 7.5-8" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const BELL = '<svg viewBox="0 0 24 26"><path d="M12 0a2 2 0 012 2v1.2a8 8 0 016 7.8v6l3 3.5H1L4 17v-6a8 8 0 016-7.8V2a2 2 0 012-2z"/><circle cx="12" cy="23.3" r="2.7"/></svg>';
  const svgData = (svg, fill) => 'url("data:image/svg+xml;utf8,' + encodeURIComponent(svg.replace('<svg ', `<svg xmlns="http://www.w3.org/2000/svg" fill="${fill}" `)) + '")';

  // ---------------------------------------------------------------- Escenas
  const scenes = [];
  const stage = document.getElementById('stage');

  function scene(start, end, opts, build) {
    const root = el('div', 'scene', stage);
    const ctx = {
      start, end, root,
      bg: el('div', 'layer bg', root),
      behind: el('div', 'layer behind', root),
      subj: el('div', 'layer subj', root),
      front: el('div', 'layer front', root),
      top: el('div', 'layer top', root),
      ups: [],
      add(fn) { this.ups.push(fn); },
    };
    const sc = { start, end, root, ctx, trans: opts.trans || 'cut', transDur: opts.transDur ?? 0.6, origin: opts.origin || [540, 960] };
    build(ctx);
    if (opts.polish !== false) {
      const vig = el('div', 'fill vignette', ctx.top);
      const leak = el('div', 'leak', ctx.top);
      const seed = scenes.length * 1.7;
      ctx.add(t => {
        const lt = t - start;
        leak.style.opacity = 0.18 + 0.1 * Math.sin(lt * 0.7 + seed);
        tf(leak, { x: Math.sin(lt * 0.25 + seed) * 380, y: Math.cos(lt * 0.2 + seed) * 520 });
      });
      place(leak, 540, 700);
    }
    scenes.push(sc);
    return sc;
  }

  function applyTransition(sc, t) {
    const r = sc.root;
    const k = prog(t, sc.start, sc.start + sc.transDur);
    r.style.clipPath = 'none';
    r.style.webkitMaskImage = 'none';
    r.style.transform = 'none';
    r.style.opacity = 1;
    if (k >= 1 || sc.trans === 'cut') return;
    const [ox, oy] = sc.origin;
    if (sc.trans === 'circle') {
      r.style.clipPath = `circle(${E.inOutCubic(k) * 2300}px at ${ox}px ${oy}px)`;
    } else if (sc.trans === 'paw') {
      const size = E.inCubic(k) * 11000 + 1;
      r.style.webkitMaskImage = svgData(PAW, '#000');
      r.style.webkitMaskRepeat = 'no-repeat';
      r.style.webkitMaskSize = `${size}px ${size}px`;
      r.style.webkitMaskPosition = `${ox - size / 2}px ${oy - size * 0.62}px`;
    } else if (sc.trans === 'whip') {
      const e = E.outQuint(k);
      r.style.transform = `translateX(${(1 - e) * W * 1.05}px) skewX(${(1 - e) * -12}deg)`;
    } else if (sc.trans === 'whipUp') {
      const e = E.outQuint(k);
      r.style.transform = `translateY(${(1 - e) * H}px) skewY(${(1 - e) * 6}deg)`;
    } else if (sc.trans === 'zoom') {
      const e = E.outCubic(k);
      r.style.opacity = e;
      r.style.transform = `scale(${lerp(1.35, 1, e)})`;
    }
  }

  function renderFrame(t) {
    for (let i = 0; i < scenes.length; i++) {
      const sc = scenes[i];
      const next = scenes[i + 1];
      const until = next ? next.start + next.transDur : sc.end;
      const vis = t >= sc.start && t < until;
      sc.root.style.display = vis ? 'block' : 'none';
      if (!vis) continue;
      applyTransition(sc, t);
      // salida: la escena saliente se acerca un poco cuando la siguiente entra con zoom
      if (next && next.trans === 'zoom' && t >= next.start) {
        const k = E.inCubic(prog(t, next.start, next.start + next.transDur));
        sc.root.style.transform = `scale(${1 + k * 0.25})`;
      }
      for (const fn of sc.ctx.ups) fn(t);
    }
  }

  // ---------------------------------------------------------------- Efectos
  const FX = {};

  // Fondo: degradado + manchas suaves en movimiento + patrón opcional
  FX.bg = (ctx, { colors = ['#33C7BE', '#7C5CE0'], angle = 160, blobs = [], pattern = null, patternColor = 'rgba(255,255,255,.10)', patternSize = 130, patternSpeed = 30 }) => {
    const g = el('div', 'fill', ctx.bg);
    g.style.background = `linear-gradient(${angle}deg, ${colors.join(',')})`;
    const bl = blobs.map(b => {
      const n = el('div', 'blob', ctx.bg);
      n.style.width = n.style.height = b.r * 2 + 'px';
      n.style.background = `radial-gradient(circle, ${b.color} 0%, rgba(255,255,255,0) 68%)`;
      place(n, b.x, b.y);
      return { n, b };
    });
    let pat = null;
    if (pattern) {
      pat = el('div', 'fill', ctx.bg);
      const svg = pattern === 'paws' ? PAW : pattern === 'hearts' ? HEART : SPARK;
      pat.style.backgroundImage = svgData(svg, patternColor);
      pat.style.backgroundSize = `${patternSize}px ${patternSize}px`;
      pat.style.opacity = 1;
    }
    ctx.add(t => {
      const lt = t - ctx.start;
      for (const { n, b } of bl) tf(n, { x: Math.sin(lt * 0.5 + b.x) * 60, y: Math.cos(lt * 0.4 + b.y) * 70, s: 1 + Math.sin(lt * 0.6 + b.r) * 0.08 });
      if (pat) pat.style.backgroundPosition = `${lt * patternSpeed}px ${-lt * patternSpeed * 0.6}px`;
    });
  };

  // Imagen principal (ilustración recortada): entrada, Ken Burns y flotación
  FX.subject = (ctx, { src, at = 0, x = 540, y = 1100, w = 900, from = 'up', zoom = 0.06, float = 10, rot = 0, layer = 'subj', dur = 0.9 }) => {
    const n = el('img', 'subject', ctx[layer]);
    n.src = src;
    n.style.width = w + 'px';
    place(n, x, y);
    ctx.add(t => {
      const lt = t - ctx.start;
      const k = prog(t, ctx.start + at, ctx.start + at + dur);
      const e = from === 'pop' ? E.outBack(k) : E.outQuint(k);
      let dx = 0, dy = 0, s = 1;
      if (from === 'up') dy = (1 - e) * 900;
      if (from === 'down') dy = -(1 - e) * 900;
      if (from === 'left') dx = -(1 - e) * 1100;
      if (from === 'right') dx = (1 - e) * 1100;
      if (from === 'pop') s = e;
      const kb = 1 + zoom * prog(t, ctx.start, ctx.end);
      n.style.opacity = from === 'fade' ? k : 1;
      tf(n, { x: dx, y: dy + Math.sin(lt * 1.6) * float, s: s * kb, r: rot + Math.sin(lt * 0.9) * 1.2 });
    });
    return n;
  };

  // Tarjeta con imagen (para ilustraciones con fondo claro)
  FX.card = (ctx, { src, at = 0, x = 540, y = 1000, w = 720, rot = -4, sway = 3, from = 'right', layer = 'subj', radius = 54, swipe = null }) => {
    const n = el('div', 'card', ctx[layer]);
    n.style.width = w + 'px';
    n.style.borderRadius = radius + 'px';
    const img = el('img', '', n);
    img.src = src;
    place(n, x, y);
    ctx.add(t => {
      const lt = t - ctx.start;
      const k = E.outBack(prog(t, ctx.start + at, ctx.start + at + 0.8));
      let dx = from === 'right' ? (1 - k) * 1200 : from === 'left' ? -(1 - k) * 1200 : 0;
      let dy = from === 'up' ? (1 - k) * 1400 : 0;
      let r = rot + Math.sin(lt * 1.1) * sway;
      if (swipe) {
        // gesto de deslizar: se inclina y regresa
        const sk = Math.sin(clamp((lt - swipe.at) / swipe.dur) * Math.PI);
        dx += sk * swipe.dx;
        r += sk * swipe.rot;
      }
      tf(n, { x: dx, y: dy + Math.sin(lt * 1.4) * 8, r, s: from === 'pop' ? E.outBack(prog(t, ctx.start + at, ctx.start + at + 0.6)) : 1 });
    });
    return n;
  };

  // Palabra gigante (normalmente detrás del sujeto)
  FX.giant = (ctx, { lines, at = 0.2, x = 540, y = 760, size = 250, color = '#FFF6EA', stroke = null, font = 'Bungee', layer = 'behind', rot = 0, drift = 14, stagger = 0.14, lineGap = 0.92, from = 'scale', shadow = true }) => {
    const box = el('div', 'giant', ctx[layer]);
    place(box, x, y);
    box.style.fontFamily = font;
    box.style.fontSize = size + 'px';
    box.style.lineHeight = lineGap;
    const ls = lines.map(ln => {
      const txt = typeof ln === 'string' ? ln : ln.text;
      const l = el('div', 'gline', box, txt);
      l.style.color = ln.color || color;
      if (ln.size) l.style.fontSize = ln.size + 'px';
      if (stroke) { l.style.webkitTextStroke = stroke; }
      if (shadow) l.style.textShadow = '0 14px 0 rgba(0,0,0,.10)';
      return l;
    });
    ctx.add(t => {
      const lt = t - ctx.start;
      tf(box, { r: rot, x: Math.sin(lt * 0.3) * drift + lt * drift * 0.3 });
      ls.forEach((l, i) => {
        const k = prog(t, ctx.start + at + i * stagger, ctx.start + at + i * stagger + 0.75);
        const e = E.outCubic(k);
        l.style.opacity = k > 0 ? clamp(k * 2) : 0;
        if (from === 'scale') l.style.transform = `scale(${lerp(1.5, 1, e)}) translateY(${(1 - e) * 60}px)`;
        if (from === 'left') l.style.transform = `translateX(${(1 - e) * (i % 2 ? 900 : -900)}px)`;
        if (from === 'drop') l.style.transform = `translateY(${(1 - E.outBounce(k)) * -900}px)`;
      });
    });
    return box;
  };

  // Etiquetas tipo estampa que aparecen con rebote
  FX.pop = (ctx, { items, layer = 'front' }) => {
    const ns = items.map(it => {
      const n = el('div', 'pop ' + (it.cls || 'sticker'), ctx[layer], it.html || it.text);
      if (it.bg) n.style.background = it.bg;
      if (it.color) n.style.color = it.color;
      if (it.size) n.style.fontSize = it.size + 'px';
      if (it.font) n.style.fontFamily = it.font;
      place(n, it.x, it.y, it.anchor || 'c');
      return { n, it };
    });
    ctx.add(t => {
      const lt = t - ctx.start;
      for (const { n, it } of ns) {
        const k = prog(t, ctx.start + it.at, ctx.start + it.at + 0.5);
        const e = (it.ease === 'elastic' ? E.outElastic : E.outBackBig)(k);
        const ko = it.out !== undefined ? clamp((t - ctx.start - it.out) / 0.35) : 0;
        n.style.opacity = k > 0 ? 1 - ko : 0;
        const wig = it.wiggle ? Math.sin(lt * 7) * it.wiggle * clamp(1 - (lt - it.at - 0.5) / 3) : Math.sin(lt * 2 + it.x) * 1.5;
        tf(n, { s: e * (1 - ko * 0.6), r: (it.rot || 0) + (1 - k) * -18 + wig, y: -ko * 60 });
      }
    });
  };

  // Marcatexto que se pinta detrás de una frase
  FX.highlight = (ctx, { text, at, x, y, size = 86, color = '#2B2340', marker = '#F2A93B', font = 'Baloo 2', anchor = 'c', rot = -2, layer = 'front' }) => {
    const box = el('div', 'hl', ctx[layer]);
    place(box, x, y, anchor);
    const m = el('div', 'hl-marker', box);
    m.style.background = marker;
    const tx = el('div', 'hl-text', box, text);
    tx.style.fontSize = size + 'px';
    tx.style.color = color;
    tx.style.fontFamily = font;
    ctx.add(t => {
      const k = prog(t, ctx.start + at, ctx.start + at + 0.55);
      m.style.transform = `scaleX(${E.outCubic(k)}) skewX(-8deg)`;
      tx.style.opacity = clamp(prog(t, ctx.start + at - 0.1, ctx.start + at + 0.25));
      tf(box, { r: rot });
    });
  };

  // Máquina de escribir con cursor
  FX.type = (ctx, { text, at, cps = 20, x, y, size = 64, color = '#fff', font = 'Baloo 2', anchor = 'l', bg = null, layer = 'front', weight = 700 }) => {
    const n = el('div', 'type', ctx[layer]);
    place(n, x, y, anchor);
    n.style.fontSize = size + 'px';
    n.style.color = color;
    n.style.fontFamily = font;
    n.style.fontWeight = weight;
    if (bg) { n.style.background = bg; n.style.padding = '10px 26px 6px'; n.style.borderRadius = '22px'; }
    const span = el('span', '', n);
    const cur = el('span', 'cursor', n, '|');
    ctx.add(t => {
      const lt = t - ctx.start - at;
      const nch = clamp(Math.floor(lt * cps), 0, text.length);
      span.textContent = text.slice(0, nch);
      n.style.opacity = lt >= 0 ? 1 : 0;
      cur.style.opacity = (nch < text.length || Math.floor(lt * 2.2) % 2 === 0) ? 1 : 0;
      tf(n, {});
    });
  };

  // Renglones que caen y rebotan apilados
  FX.stack = (ctx, { lines, x, y, gap = 150, layer = 'front', anchor = 'l' }) => {
    const ns = lines.map((ln, i) => {
      const n = el('div', 'stackline', ctx[layer], ln.text);
      n.style.fontSize = (ln.size || 120) + 'px';
      n.style.color = ln.color || '#fff';
      n.style.fontFamily = ln.font || 'Lilita One';
      if (ln.bg) { n.style.background = ln.bg; n.style.padding = '0 30px'; n.style.borderRadius = '26px'; }
      place(n, x + (ln.dx || 0), y + i * gap, anchor);
      return { n, ln };
    });
    ctx.add(t => {
      for (const { n, ln } of ns) {
        const k = prog(t, ctx.start + ln.at, ctx.start + ln.at + 0.8);
        n.style.opacity = k > 0 ? clamp(k * 4) : 0;
        tf(n, { y: (1 - E.outBounce(k)) * -420, r: (ln.rot || 0) * E.outCubic(k) });
      }
    });
  };

  // Estallido con rayos y confeti
  FX.burst = (ctx, { text, at, x, y, size = 190, color = '#fff', rays = '#F2A93B', font = 'Bungee', layer = 'front', seed = 7, confetti = ['#F2A93B', '#33C7BE', '#F7A8C4', '#B9A6F5', '#fff'] }) => {
    const wrap = el('div', 'burst', ctx[layer]);
    place(wrap, x, y);
    let svg = '<svg viewBox="-100 -100 200 200" class="rays">';
    for (let i = 0; i < 18; i++) {
      const a = (i / 18) * Math.PI * 2;
      svg += `<line x1="${Math.cos(a) * 30}" y1="${Math.sin(a) * 30}" x2="${Math.cos(a) * 95}" y2="${Math.sin(a) * 95}" stroke="${rays}" stroke-width="${i % 2 ? 5 : 9}" stroke-linecap="round"/>`;
    }
    svg += '</svg>';
    const r = el('div', 'rays-wrap', wrap, svg);
    const tx = el('div', 'burst-text', wrap, text);
    tx.style.fontSize = size + 'px';
    tx.style.color = color;
    tx.style.fontFamily = font;
    const rnd = rng(seed);
    const parts = Array.from({ length: 46 }, () => {
      const p = el('div', 'confetti', ctx[layer]);
      p.style.background = confetti[Math.floor(rnd() * confetti.length)];
      const a = rnd() * Math.PI * 2, v = 500 + rnd() * 900;
      return { p, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 500, rot: rnd() * 720, w: 14 + rnd() * 18 };
    });
    parts.forEach(q => { q.p.style.width = q.w + 'px'; q.p.style.height = q.w * 0.45 + 'px'; place(q.p, x, y); });
    ctx.add(t => {
      const lt = t - ctx.start - at;
      const k = prog(lt, 0, 0.8);
      tx.style.opacity = lt >= 0 ? 1 : 0;
      tx.style.transform = `scale(${E.outElastic(k)}) rotate(${-6 + Math.sin(lt * 3) * 2}deg)`;
      r.style.opacity = lt >= 0 ? clamp(1 - prog(lt, 0.6, 2.2)) : 0;
      r.style.transform = `scale(${lerp(0.3, 1.6, E.outCubic(prog(lt, 0, 1.2)))}) rotate(${lt * 30}deg)`;
      for (const q of parts) {
        const tt = clamp(lt, 0, 3);
        q.p.style.opacity = lt >= 0 && lt < 3 ? 1 - lt / 3 : 0;
        tf(q.p, { x: q.vx * tt * 0.6, y: q.vy * tt * 0.6 + 900 * tt * tt * 0.5, r: q.rot * tt });
      }
    });
  };

  // Sello que cae y golpea
  FX.stamp = (ctx, { text, at, x, y, rot = -8, color = '#E8574F', size = 92, layer = 'front', font = 'Bungee', bg = 'transparent' }) => {
    const n = el('div', 'stamp', ctx[layer], text);
    place(n, x, y);
    n.style.color = color;
    n.style.borderColor = color;
    n.style.fontSize = size + 'px';
    n.style.fontFamily = font;
    n.style.background = bg;
    ctx.add(t => {
      const lt = t - ctx.start - at;
      const k = prog(lt, 0, 0.28);
      const shake = lt > 0.28 && lt < 0.55 ? Math.sin(lt * 90) * (0.55 - lt) * 30 : 0;
      n.style.opacity = lt >= 0 ? Math.min(1, k * 1.6) : 0;
      tf(n, { s: lerp(2.6, 1, E.inCubic(k)), r: rot + shake * 0.3, x: shake });
    });
  };

  // Letra manuscrita que se dibuja de izquierda a derecha + subrayado
  FX.hand = (ctx, { text, at, dur = 1.1, x, y, size = 110, color = '#fff', font = 'Caveat', anchor = 'c', underline = '#F2A93B', rot = -3, layer = 'front' }) => {
    const box = el('div', 'hand', ctx[layer]);
    place(box, x, y, anchor);
    const tx = el('div', 'hand-text', box, text);
    tx.style.fontFamily = font;
    tx.style.fontSize = size + 'px';
    tx.style.color = color;
    let path = null;
    if (underline) {
      const u = el('div', 'hand-ul', box, `<svg viewBox="0 0 400 40" preserveAspectRatio="none"><path d="M5 28 C 90 6, 170 36, 250 18 S 360 10, 395 22" fill="none" stroke="${underline}" stroke-width="9" stroke-linecap="round"/></svg>`);
      path = u.querySelector('path');
      path.style.strokeDasharray = 460;
    }
    ctx.add(t => {
      const lt = t - ctx.start - at;
      const k = prog(lt, 0, dur);
      tx.style.clipPath = `inset(-20% ${(1 - k) * 100}% -20% 0)`;
      box.style.opacity = lt >= 0 ? 1 : 0;
      if (path) path.style.strokeDashoffset = 460 * (1 - E.outCubic(prog(lt, dur * 0.8, dur + 0.5)));
      tf(box, { r: rot });
    });
  };

  // Renglones que suben desde una máscara
  FX.rise = (ctx, { lines, at, x, y, gap = 120, stagger = 0.16, layer = 'front', anchor = 'c' }) => {
    const ns = lines.map((ln, i) => {
      const wrap = el('div', 'rise-wrap', ctx[layer]);
      place(wrap, x + (ln.dx || 0), y + i * gap, ln.anchor || anchor);
      const inner = el('div', 'rise-inner', wrap, ln.text);
      inner.style.fontSize = (ln.size || 96) + 'px';
      inner.style.color = ln.color || '#fff';
      inner.style.fontFamily = ln.font || 'Baloo 2';
      inner.style.fontWeight = ln.weight || 800;
      if (ln.bg) { inner.style.background = ln.bg; inner.style.padding = '0 28px'; inner.style.borderRadius = '24px'; }
      return { wrap, inner, i };
    });
    ctx.add(t => {
      for (const { wrap, inner, i } of ns) {
        const k = prog(t, ctx.start + at + i * stagger, ctx.start + at + i * stagger + 0.7);
        inner.style.transform = `translateY(${(1 - E.outQuint(k)) * 115}%)`;
        wrap.style.opacity = k > 0 ? 1 : 0;
        tf(wrap, {});
      }
    });
  };

  // Texto con falla digital (desplazamiento de color y temblor)
  FX.glitch = (ctx, { text, at, x, y, size = 220, color = '#FFF6EA', font = 'Bungee', layer = 'front', settle = 1.6 }) => {
    const box = el('div', 'glitch', ctx[layer]);
    place(box, x, y);
    const mk = (c, cls) => { const n = el('div', 'glitch-copy ' + cls, box, text); n.style.color = c; n.style.fontSize = size + 'px'; n.style.fontFamily = font; return n; };
    const a = mk('#33C7BE', 'g1'), b = mk('#E8574F', 'g2'), c = mk(color, 'g3');
    ctx.add(t => {
      const lt = t - ctx.start - at;
      box.style.opacity = lt >= 0 ? 1 : 0;
      const f = Math.floor(t * 30);
      const r = rng(f * 7919 + 13);
      const amp = 34 * clamp(1 - lt / settle) + 3;
      a.style.transform = `translate(${(r() - 0.5) * amp}px, ${(r() - 0.5) * amp * 0.4}px)`;
      b.style.transform = `translate(${(r() - 0.5) * amp}px, ${(r() - 0.5) * amp * 0.4}px)`;
      const slice = r() < 0.35 * clamp(1 - lt / settle) ? `inset(${Math.floor(r() * 80)}% 0 ${Math.floor(r() * 30)}% 0)` : 'none';
      c.style.clipPath = slice;
      const s = lerp(1.4, 1, E.outCubic(prog(lt, 0, 0.35)));
      tf(box, { s, x: (r() - 0.5) * amp * 0.5, r: -3 });
    });
  };

  // Palabras que orbitan alrededor del sujeto, pasando por detrás y por delante
  FX.orbit = (ctx, { words, at, cx = 540, cy = 1000, rx = 420, ry = 150, speed = 0.55, size = 70, colors = ['#fff'], bgs = ['#7C5CE0'] }) => {
    const items = words.map((w, i) => {
      const mk = layer => { const n = el('div', 'orbit-word', ctx[layer], w); n.style.fontSize = size + 'px'; n.style.color = colors[i % colors.length]; n.style.background = bgs[i % bgs.length]; place(n, cx, cy); return n; };
      return { b: mk('behind'), f: mk('front'), a0: (i / words.length) * Math.PI * 2, i };
    });
    ctx.add(t => {
      const lt = t - ctx.start - at;
      for (const it of items) {
        const k = E.outBack(prog(lt, it.i * 0.35, it.i * 0.35 + 0.6));
        const ang = it.a0 + lt * speed;
        const px = Math.cos(ang) * rx, py = Math.sin(ang) * ry;
        const front = Math.sin(ang) > 0;
        const depth = lerp(0.82, 1.12, (Math.sin(ang) + 1) / 2);
        for (const n of [it.b, it.f]) { n.style.opacity = lt >= 0 ? 1 : 0; tf(n, { x: px, y: py, s: k * depth, r: Math.cos(ang) * -6 }); }
        it.b.style.visibility = front ? 'hidden' : 'visible';
        it.f.style.visibility = front ? 'visible' : 'hidden';
      }
    });
  };

  // Anillo con porcentaje que sube
  FX.ring = (ctx, { at, dur = 2, to = 92, x, y, size = 330, color = '#33C7BE', track = 'rgba(255,255,255,.35)', label = '', layer = 'front' }) => {
    const box = el('div', 'ring', ctx[layer]);
    place(box, x, y);
    box.style.width = box.style.height = size + 'px';
    box.innerHTML = `<svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="52" fill="#fff" stroke="${track}" stroke-width="12"/><circle class="arc" cx="60" cy="60" r="52" fill="none" stroke="${color}" stroke-width="12" stroke-linecap="round" transform="rotate(-90 60 60)" stroke-dasharray="326.7" stroke-dashoffset="326.7"/></svg><div class="ring-num">0%</div><div class="ring-label">${label}</div>`;
    const arc = box.querySelector('.arc'), num = box.querySelector('.ring-num');
    ctx.add(t => {
      const lt = t - ctx.start - at;
      const k = E.outCubic(prog(lt, 0.2, 0.2 + dur));
      arc.setAttribute('stroke-dashoffset', 326.7 * (1 - (k * to) / 100));
      num.textContent = Math.round(k * to) + '%';
      box.style.opacity = lt >= 0 ? 1 : 0;
      tf(box, { s: E.outBack(prog(lt, 0, 0.5)) });
    });
  };

  // Burbujas de chat con "escribiendo..."
  FX.chat = (ctx, { msgs, x = 540, y = 600, gap = 210, width = 760, layer = 'front' }) => {
    const ns = msgs.map((m, i) => {
      const b = el('div', 'bubble ' + m.side, ctx[layer]);
      b.style.maxWidth = width + 'px';
      const dots = el('div', 'dots', b, '<i></i><i></i><i></i>');
      const tx = el('div', 'bubble-text', b, m.text);
      place(b, m.side === 'me' ? x + width / 2 : x - width / 2, y + i * gap, m.side === 'me' ? 'tr' : 'tl');
      return { b, dots, tx, m };
    });
    ctx.add(t => {
      for (const { b, dots, tx, m } of ns) {
        const lt = t - ctx.start - m.at;
        const k = E.outBack(prog(lt, 0, 0.4));
        b.style.opacity = lt >= 0 ? 1 : 0;
        const typing = lt < 0.75;
        dots.style.display = typing ? 'flex' : 'none';
        tx.style.display = typing ? 'none' : 'block';
        if (typing) [...dots.children].forEach((d, j) => (d.style.transform = `translateY(${Math.sin(lt * 14 - j) * 6}px)`));
        tf(b, { s: k, y: (1 - k) * 40 });
      }
    });
  };

  // Línea de escaneo con puntos que se encienden
  FX.scan = (ctx, { at, dur = 3.2, x, y, w, h, color = '#33C7BE', dots = 26, seed = 3, layer = 'front' }) => {
    const box = el('div', 'scanbox', ctx[layer]);
    place(box, x, y);
    box.style.width = w + 'px';
    box.style.height = h + 'px';
    const line = el('div', 'scanline', box);
    line.style.background = `linear-gradient(180deg, rgba(255,255,255,0), ${color}, rgba(255,255,255,0))`;
    const rnd = rng(seed);
    const ds = Array.from({ length: dots }, () => { const d = el('div', 'scandot', box); d.style.left = rnd() * 100 + '%'; d.style.top = (0.08 + rnd() * 0.84) * 100 + '%'; d.style.background = color; return d; });
    const corners = el('div', 'scan-corners', box);
    corners.style.borderColor = color;
    ctx.add(t => {
      const lt = t - ctx.start - at;
      box.style.opacity = lt >= 0 ? 1 : 0;
      const cyc = (lt / dur) % 2;
      const pos = cyc < 1 ? cyc : 2 - cyc;
      line.style.top = pos * 100 + '%';
      ds.forEach(d => { const dy = parseFloat(d.style.top) / 100; d.style.opacity = lt > dy * dur ? 0.9 : 0; d.style.transform = `translate(-50%,-50%) scale(${0.6 + 0.4 * Math.sin(lt * 5 + dy * 20)})`; });
      tf(box, { s: E.outCubic(prog(lt, 0, 0.4)) });
    });
  };

  // Letras dispersas que se arman
  FX.scatter = (ctx, { text, at, dur = 1.1, x, y, size = 200, color = '#fff', font = 'Lilita One', layer = 'behind', seed = 5, stroke = null, spread = 700, shadow = true }) => {
    const box = el('div', 'scatter', ctx[layer]);
    place(box, x, y);
    box.style.fontFamily = font;
    box.style.fontSize = size + 'px';
    const rnd = rng(seed);
    const ls = [...text].map(ch => {
      const s = el('span', 'sl', box, ch === ' ' ? '&nbsp;' : ch);
      s.style.color = color;
      if (stroke) s.style.webkitTextStroke = stroke;
      if (shadow) s.style.textShadow = '0 12px 0 rgba(0,0,0,.12)';
      return { s, dx: (rnd() - 0.5) * spread * 2, dy: (rnd() - 0.5) * spread * 2, r: (rnd() - 0.5) * 360, d: rnd() * 0.35 };
    });
    ctx.add(t => {
      const lt = t - ctx.start - at;
      tf(box, { s: 1 + Math.sin(lt * 0.8) * 0.01 });
      for (const l of ls) {
        const k = E.outBack(prog(lt, l.d, l.d + dur));
        l.s.style.opacity = lt >= l.d ? clamp(prog(lt, l.d, l.d + 0.3)) : 0;
        l.s.style.transform = `translate(${l.dx * (1 - k)}px, ${l.dy * (1 - k)}px) rotate(${l.r * (1 - k)}deg) scale(${lerp(0.3, 1, k)})`;
      }
    });
    return box;
  };

  // Texto con contorno que se llena como líquido
  FX.fill = (ctx, { text, at, fillAt, x, y, size = 200, color = '#F2A93B', stroke = '#fff', font = 'Bungee', layer = 'front', rot = 0 }) => {
    const box = el('div', 'fillbox', ctx[layer]);
    place(box, x, y);
    const o = el('div', 'fill-outline', box, text), f = el('div', 'fill-solid', box, text);
    for (const n of [o, f]) { n.style.fontSize = size + 'px'; n.style.fontFamily = font; }
    o.style.webkitTextStroke = `6px ${stroke}`;
    f.style.color = color;
    f.style.webkitTextStroke = `6px ${stroke}`;
    ctx.add(t => {
      const lt = t - ctx.start - at;
      box.style.opacity = lt >= 0 ? 1 : 0;
      const k = prog(lt, 0, 0.6);
      tf(box, { r: rot, s: lerp(0.7, 1, E.outBack(k)) });
      const fk = E.inOutCubic(prog(t, ctx.start + fillAt, ctx.start + fillAt + 0.9));
      const wave = Math.sin(lt * 6) * 4;
      f.style.clipPath = `inset(${(1 - fk) * 100 + wave * (1 - fk)}% 0 0 0)`;
    });
  };

  // Texto en círculo que gira alrededor del sujeto
  FX.curve = (ctx, { text, at, cx = 540, cy = 1000, r = 470, speed = 9, size = 54, color = '#fff', layer = 'behind', font = 'Baloo 2' }) => {
    const id = 'c' + Math.floor(Math.random() * 1e9);
    const n = el('div', 'curve', ctx[layer], `<svg viewBox="-600 -600 1200 1200"><defs><path id="${id}" d="M0,${-r} a${r},${r} 0 1,1 0,${2 * r} a${r},${r} 0 1,1 0,${-2 * r}"/></defs><text font-size="${size}" fill="${color}" font-family="${font}" font-weight="800" letter-spacing="4"><textPath href="#${id}">${text}</textPath></text></svg>`);
    place(n, cx, cy);
    ctx.add(t => {
      const lt = t - ctx.start - at;
      n.style.opacity = lt >= 0 ? clamp(lt / 0.6) : 0;
      tf(n, { r: lt * speed, s: lerp(0.8, 1, E.outCubic(prog(lt, 0, 0.8))) });
    });
  };

  // Rastro de huellas (aparecen y, si se pide, se desvanecen)
  FX.trail = (ctx, { from, to, at, steps = 9, every = 0.18, size = 70, color = '#FFF6EA', fadeAfter = null, layer = 'behind' }) => {
    const ang = Math.atan2(to[1] - from[1], to[0] - from[0]);
    const ps = Array.from({ length: steps }, (_, i) => {
      const k = i / (steps - 1);
      const side = i % 2 ? 1 : -1;
      const px = lerp(from[0], to[0], k) + Math.cos(ang + Math.PI / 2) * side * 34;
      const py = lerp(from[1], to[1], k) + Math.sin(ang + Math.PI / 2) * side * 34;
      const n = el('div', 'paw', ctx[layer], PAW);
      n.style.width = n.style.height = size + 'px';
      n.style.fill = color;
      place(n, px, py);
      return { n, i };
    });
    ctx.add(t => {
      const lt = t - ctx.start - at;
      for (const { n, i } of ps) {
        const on = prog(lt, i * every, i * every + 0.2);
        const off = fadeAfter == null ? 0 : prog(lt, fadeAfter + i * every, fadeAfter + i * every + 0.5);
        n.style.opacity = on * (1 - off);
        tf(n, { r: (ang * 180) / Math.PI + 90, s: lerp(0.4, 1, E.outBack(on)) });
      }
    });
  };

  // Elementos decorativos flotantes (corazones, huellas, destellos)
  FX.floaters = (ctx, { kind = 'heart', count = 8, area = [80, 300, 1000, 1500], colors = ['#F7A8C4'], seed = 11, at = 0, size = [40, 90], rise = 120, layer = 'front' }) => {
    const svg = kind === 'paw' ? PAW : kind === 'spark' ? SPARK : HEART;
    const rnd = rng(seed);
    const fs = Array.from({ length: count }, () => {
      const n = el('div', 'floater', ctx[layer], svg);
      const s = lerp(size[0], size[1], rnd());
      n.style.width = n.style.height = s + 'px';
      n.style.fill = colors[Math.floor(rnd() * colors.length)];
      place(n, lerp(area[0], area[2], rnd()), lerp(area[1], area[3], rnd()));
      return { n, ph: rnd() * 6, d: rnd() * 0.8, sp: 0.6 + rnd() };
    });
    ctx.add(t => {
      const lt = t - ctx.start - at;
      for (const f of fs) {
        const k = E.outBack(prog(lt, f.d, f.d + 0.5));
        f.n.style.opacity = lt >= f.d ? 1 : 0;
        tf(f.n, { s: k, y: -((lt * rise * f.sp) % 400) * 0 - lt * rise * 0.3 * f.sp + Math.sin(lt * 2 + f.ph) * 14, x: Math.sin(lt * 1.3 + f.ph) * 22, r: Math.sin(lt + f.ph) * 15 });
      }
    });
  };

  // Ondas de radar
  FX.radar = (ctx, { x, y, at = 0, color = 'rgba(255,255,255,.7)', count = 4, period = 1.6, max = 1200, layer = 'behind' }) => {
    const rs = Array.from({ length: count }, (_, i) => { const n = el('div', 'radar', ctx[layer]); n.style.borderColor = color; place(n, x, y); return { n, i }; });
    ctx.add(t => {
      const lt = t - ctx.start - at;
      for (const { n, i } of rs) {
        if (lt < 0) { n.style.opacity = 0; continue; }
        const ph = ((lt + (i * period) / count) % period) / period;
        n.style.width = n.style.height = ph * max + 'px';
        n.style.opacity = (1 - ph) * 0.9;
        tf(n, {});
      }
    });
  };

  // Destello blanco (flash de cámara)
  FX.flash = (ctx, { at }) => {
    const n = el('div', 'fill flash', ctx.top);
    ctx.add(t => { const lt = t - ctx.start - at; n.style.opacity = lt < 0 ? 0 : clamp(1 - lt / 0.45) * (lt < 0.05 ? lt / 0.05 : 1); });
  };

  // Reloj con manecilla que corre
  FX.clock = (ctx, { at, x, y, size = 200, color = '#FFF6EA', layer = 'front' }) => {
    const n = el('div', 'clock', ctx[layer], `<svg viewBox="-50 -50 100 100"><circle r="44" fill="none" stroke="${color}" stroke-width="7"/><line class="hand" x1="0" y1="0" x2="0" y2="-32" stroke="#F2A93B" stroke-width="7" stroke-linecap="round"/><circle r="5" fill="${color}"/></svg>`);
    n.style.width = n.style.height = size + 'px';
    place(n, x, y);
    const hand = n.querySelector('.hand');
    ctx.add(t => {
      const lt = t - ctx.start - at;
      n.style.opacity = lt >= 0 ? 1 : 0;
      hand.setAttribute('transform', `rotate(${Math.floor(lt * 4) * 30})`);
      tf(n, { s: E.outBack(prog(lt, 0, 0.5)) * (1 + (Math.floor(lt * 4) !== Math.floor((lt - 0.06) * 4) ? 0.06 : 0)) });
    });
  };

  // Ícono suelto (pin, escudo, campana, huella)
  FX.icon = (ctx, { kind, at, x, y, size = 120, color = '#E8574F', layer = 'front', bounce = true, wiggle = 0 }) => {
    const svg = { pin: PIN, shield: SHIELD, bell: BELL, paw: PAW, heart: HEART, spark: SPARK }[kind];
    const n = el('div', 'icon', ctx[layer], svg);
    n.style.width = n.style.height = size + 'px';
    n.style.fill = color;
    place(n, x, y);
    ctx.add(t => {
      const lt = t - ctx.start - at;
      n.style.opacity = lt >= 0 ? 1 : 0;
      const k = prog(lt, 0, 0.7);
      tf(n, { y: bounce ? (1 - E.outBounce(k)) * -500 : 0, s: bounce ? 1 : E.outBack(k), r: wiggle ? Math.sin(lt * 12) * wiggle * clamp(1 - (lt - 0.7) / 2) : 0 });
    });
  };

  // Logo de GuauWoow armándose
  FX.logo = (ctx, { at, x = 540, y = 900, scale = 1, layer = 'front', icon = '../src/icon-512.png', colorA = '#fff', colorB = '#2B2340' }) => {
    const box = el('div', 'logo', ctx[layer]);
    place(box, x, y);
    const ic = el('img', 'logo-icon', box);
    ic.src = icon;
    const wd = el('div', 'logo-word', box, `<span class="lp" style="color:${colorA}">Guau</span><span class="lf" style="color:${colorB}">Woow</span>`);
    ctx.add(t => {
      const lt = t - ctx.start - at;
      box.style.opacity = lt >= 0 ? 1 : 0;
      const k = prog(lt, 0, 0.8);
      ic.style.transform = `rotate(${(1 - E.outBack(k)) * -260}deg) scale(${E.outBack(k)})`;
      const k2 = prog(lt, 0.35, 1.0);
      wd.style.clipPath = `inset(-30% ${(1 - E.outCubic(k2)) * 100}% -30% 0)`;
      tf(box, { s: scale * (1 + Math.sin(lt * 2) * 0.01) });
    });
  };

  // Botón de llamada a la acción con pulso
  FX.button = (ctx, { text, at, x, y, bg = '#F2A93B', color = '#2B2340', size = 72, layer = 'front' }) => {
    const n = el('div', 'cta', ctx[layer], text);
    n.style.background = bg;
    n.style.color = color;
    n.style.fontSize = size + 'px';
    place(n, x, y);
    ctx.add(t => {
      const lt = t - ctx.start - at;
      n.style.opacity = lt >= 0 ? 1 : 0;
      tf(n, { s: E.outBackBig(prog(lt, 0, 0.5)) * (1 + Math.max(0, Math.sin(lt * 5)) * 0.05) });
    });
  };

  // Nodo genérico (elementos compuestos: cartel, celular, tarjetas, notificaciones...)
  // extra(lt, k) puede devolver {x, y, r, s, o} adicionales para animaciones propias de la escena.
  FX.node = (ctx, { html, cls = '', at = 0, x = 540, y = 960, anchor = 'c', enter = 'pop', rot = 0, float = 0, scale = 1, layer = 'front', dur = 0.7, extra = null, tag = 'div' }) => {
    const n = el(tag, 'node ' + cls, ctx[layer], html);
    place(n, x, y, anchor);
    ctx.add(t => {
      const lt = t - ctx.start - at;
      const k = prog(lt, 0, dur);
      let dx = 0, dy = 0, s = scale, r = rot, o = lt >= 0 ? 1 : 0;
      if (enter === 'pop') s = scale * E.outBackBig(k);
      if (enter === 'drop') dy = (1 - E.outBounce(k)) * -1500;
      if (enter === 'up') dy = (1 - E.outQuint(k)) * 1500;
      if (enter === 'left') { dx = (1 - E.outQuint(k)) * -1300; r += (1 - k) * -14; }
      if (enter === 'right') { dx = (1 - E.outQuint(k)) * 1300; r += (1 - k) * 14; }
      if (enter === 'fade') o *= k;
      if (enter === 'swing') { dy = (1 - E.outCubic(k)) * -1400; r += Math.exp(-lt * 1.6) * Math.sin(lt * 7) * 14 * (lt > 0 ? 1 : 0); }
      if (float) { dy += Math.sin(lt * 1.5) * float; r += Math.sin(lt * 1.1) * 1.2; }
      if (extra) { const e = extra(lt, k) || {}; dx += e.x || 0; dy += e.y || 0; r += e.r || 0; s *= e.s ?? 1; if (e.o !== undefined) o *= e.o; }
      n.style.opacity = o;
      tf(n, { x: dx, y: dy, s, r });
    });
    return n;
  };

  // Imagen recortada (sprite) con la misma mecánica de entrada que FX.node
  FX.sprite = (ctx, opts) => {
    const n = FX.node(ctx, { ...opts, tag: 'img', cls: 'sprite ' + (opts.cls || ''), html: undefined });
    n.src = opts.src;
    n.style.width = (opts.w || 400) + 'px';
    if (opts.flip) n.style.scale = '-1 1';
    return n;
  };

  // ---------------------------------------------------------------- Marcas de sonido
  // Cada efecto deja una marca (tiempo absoluto, tipo, posición) que tools/sonido.py convierte en efectos de audio.
  const CUES = [];
  const cue = (ctx, at, kind, d = {}) => CUES.push({ t: +(ctx.start + at).toFixed(3), kind, ...d });
  FX.sfx = () => {}; // solo marca de sonido: FX.sfx(ctx, {at, kind, ...})
  const CUE_RULES = {
    sfx: (c, o) => cue(c, o.at, o.kind, o),
    subject: (c, o) => cue(c, (o.at || 0) + 0.15, o.sfx || (o.from === 'pop' ? 'pop_big' : 'whoosh_in'), { x: o.x }),
    sprite: (c, o) => o.sfx !== false && cue(c, (o.at || 0) + 0.12, o.sfx || (o.enter === 'pop' ? 'pop' : 'whoosh_in'), { x: o.x }),
    node: (c, o) => o.tag !== 'img' && o.sfx !== false && cue(c, (o.at || 0) + (o.enter === 'drop' ? 0.33 : 0.12), o.sfx || { pop: 'pop', drop: 'drop', swing: 'paper', left: 'whoosh_in', right: 'whoosh_in', up: 'whoosh_in', fade: 'none' }[o.enter || 'pop'], { x: o.x }),
    card: (c, o) => cue(c, (o.at || 0) + 0.15, o.from === 'pop' ? 'pop_big' : 'whoosh_in', { x: o.x }),
    giant: (c, o) => cue(c, o.at ?? 0.2, 'boom', { x: o.x ?? 540 }),
    pop: (c, o) => o.items.forEach(it => cue(c, it.at + 0.05, it.ease === 'elastic' ? 'boing' : (it.cls === 'tag' ? 'pop_soft' : 'pop'), { x: it.x })),
    highlight: (c, o) => cue(c, o.at, 'marker', { x: o.x }),
    type: (c, o) => cue(c, o.at, 'typing', { n: o.text.length, cps: o.cps || 20, x: o.x }),
    stack: (c, o) => o.lines.forEach(ln => cue(c, ln.at + 0.28, 'drop', { x: (o.x || 0) + 300 })),
    burst: (c, o) => cue(c, o.at, 'burst', { x: o.x }),
    stamp: (c, o) => cue(c, o.at + 0.27, 'stamp', { x: o.x }),
    hand: (c, o) => cue(c, o.at, 'pencil', { dur: o.dur || 1.1, x: o.x }),
    rise: (c, o) => cue(c, o.at, 'swoosh_up', { x: o.x }),
    glitch: (c, o) => cue(c, o.at, 'glitch', { dur: o.settle || 1.6, x: o.x }),
    orbit: (c, o) => o.words.forEach((w, i) => cue(c, o.at + i * 0.35, 'pop_soft', { x: (o.cx || 540) + (i % 2 ? 300 : -300) })),
    ring: (c, o) => cue(c, o.at + 0.2, 'ring', { dur: o.dur || 2, to: o.to || 92, x: o.x }),
    chat: (c, o) => o.msgs.forEach(m => { cue(c, m.at, 'typing_dots', { x: m.side === 'me' ? 800 : 280 }); cue(c, m.at + 0.75, m.side === 'me' ? 'msg_out' : 'msg_in', { x: m.side === 'me' ? 800 : 280 }); }),
    scan: (c, o) => cue(c, o.at, 'scan', { dur: o.dur || 3.2, x: o.x }),
    scatter: (c, o) => cue(c, o.at, 'magic', { x: o.x }),
    fill: (c, o) => { cue(c, o.at, 'pop', { x: o.x }); cue(c, o.fillAt, 'fill', { x: o.x }); },
    curve: (c, o) => cue(c, o.at, 'shimmer', { x: o.cx }),
    trail: (c, o) => cue(c, o.at, 'steps', { steps: o.steps || 9, every: o.every || 0.18 }),
    floaters: (c, o) => cue(c, (o.at || 0) + 0.2, o.kind === 'heart' ? 'twinkle' : 'sparkle', { count: o.count || 8 }),
    radar: (c, o) => cue(c, o.at || 0, 'sonar', { period: o.period || 1.6, until: c.end - c.start, x: o.x }),
    flash: (c, o) => cue(c, o.at, 'camera', {}),
    clock: (c, o) => cue(c, o.at, 'clock', { until: c.end - c.start, x: o.x }),
    icon: (c, o) => cue(c, o.at + (o.bounce === false ? 0.05 : 0.33), { pin: 'pin', bell: 'bell', shield: 'shield', heart: 'kiss', paw: 'pop', spark: 'sparkle' }[o.kind] || 'pop', { x: o.x }),
    logo: (c, o) => cue(c, o.at, 'logo', { x: o.x }),
    button: (c, o) => cue(c, o.at, 'button', { x: o.x }),
  };
  for (const name of Object.keys(FX)) {
    const fn = FX[name];
    FX[name] = (ctx, o = {}) => { if (CUE_RULES[name]) CUE_RULES[name](ctx, o); return fn(ctx, o); };
  }
  const sceneBase = scene;
  const sceneConCue = (start, end, opts, build) => {
    const sc = sceneBase(start, end, opts, build);
    if (opts.trans && opts.trans !== 'cut') CUES.push({ t: +start.toFixed(3), kind: 'trans_' + opts.trans, dur: sc.transDur, x: (opts.origin || [540])[0] });
    return sc;
  };

  window.PF = { FX, scene: sceneConCue, renderFrame, E, prog, lerp, clamp, W, H, PAW, HEART, SHIELD, BELL, PIN, cues: CUES };
  window.renderFrame = renderFrame;
})();
