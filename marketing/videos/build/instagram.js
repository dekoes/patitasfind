/* Video 3 · Instagram Reels/Historias (30 s, 1080x1920). Perdido -> reencuentro y adopción con compatibilidad.
   Los tiempos coinciden con GUION.md. Cortes sobre la rejilla de 0.6 s (100 BPM) de tools/musica.py.
   Zonas seguras de Reels: lo importante queda entre y=250 y y=1500 y lejos del borde derecho (x < 920). */
(function () {
  const { FX, scene, E, lerp, clamp } = PF;
  const { COL, S } = C;
  const CX = 520; // eje un poco a la izquierda: los botones de Reels van a la derecha

  // I1 · Gancho (0-2.4): "¿SE PERDIÓ?" con falla + cartel "¿Me has visto?"
  scene(0, 2.4, { trans: 'cut' }, ctx => {
    FX.bg(ctx, { colors: [COL.navy, '#2B2350'], angle: 170, blobs: [{ x: 540, y: 1000, r: 720, color: 'rgba(232,87,79,.26)' }] });
    FX.trail(ctx, { from: [110, 1760], to: [990, 250], at: 0, steps: 11, every: 0.08, size: 62, color: 'rgba(255,246,234,.45)', fadeAfter: 0.9, layer: 'behind' });
    FX.glitch(ctx, { text: '¿SE PERDIÓ?', at: 0, x: CX, y: 370, size: 96, settle: 1.3 });
    // el cartel ya viene cayendo en el primer cuadro (gancho inmediato)
    FX.node(ctx, { html: C.poster(), at: -0.18, x: CX, y: 900, enter: 'up', dur: 0.65, rot: -3, scale: 0.95, sfx: false, layer: 'subj', extra: lt => ({ r: Math.exp(-lt * 2.2) * Math.sin(lt * 9) * 7 }) });
    FX.sfx(ctx, { at: 0.0, kind: 'whoosh_in', x: CX });
    FX.sfx(ctx, { at: 0.55, kind: 'heartbeat', x: CX });
    FX.sfx(ctx, { at: 1.45, kind: 'heartbeat', x: CX });
    FX.hand(ctx, { text: 'cada minuto cuenta', at: 1.15, dur: 0.85, x: CX, y: 1430, size: 92, color: COL.cream, underline: COL.coral, rot: -3 });
  });

  // I2 · Sube su foto (2.4-5.4)
  scene(2.4, 5.4, { trans: 'whip', transDur: 0.45 }, ctx => {
    FX.bg(ctx, { colors: [COL.cream, '#D3F3EF'], angle: 170, pattern: 'paws', patternColor: 'rgba(51,199,190,.10)', blobs: [{ x: 250, y: 1250, r: 520, color: 'rgba(185,166,245,.35)' }] });
    FX.fill(ctx, { text: 'SUBE SU FOTO', at: 0.15, fillAt: 0.6, x: CX, y: 370, size: 84, color: COL.orange, stroke: COL.ink, font: 'Bungee', rot: -3 });
    FX.sprite(ctx, { src: S('chica-foto'), w: 520, x: 290, y: 1060, enter: 'left', at: 0.05, dur: 0.6, float: 4 });
    FX.node(ctx, { html: C.phone({ inner: C.camera({ dog: 'beagle-sentado' }) }), at: 0.35, x: 720, y: 980, enter: 'right', rot: 7, scale: 0.54, float: 6 });
    FX.flash(ctx, { at: 1.5 });
    FX.node(ctx, { html: C.polaroid({ dog: 'beagle-sentado', cap: '¡lista!', bg: 'linear-gradient(160deg,#CFEFEA,#E9E1FF)' }), at: 1.62, x: 740, y: 1330, enter: 'pop', rot: 9, scale: 0.78, float: 4, sfx: 'polaroid' });
    FX.pop(ctx, { items: [{ text: 'de su carita', at: 2.0, x: 300, y: 1420, rot: -5, bg: COL.teal, color: '#fff', size: 66 }] });
  });

  // I3 · La IA compara con perritos encontrados cerca (5.4-8.4)
  scene(5.4, 8.4, { trans: 'circle', origin: [740, 1330], transDur: 0.5 }, ctx => {
    FX.bg(ctx, { colors: ['#0F3B47', '#1C6D73'], angle: 170, pattern: 'spark', patternColor: 'rgba(184,237,232,.07)', patternSize: 120, blobs: [{ x: 520, y: 950, r: 600, color: 'rgba(51,199,190,.35)' }] });
    FX.giant(ctx, { lines: ['IA'], at: 0.15, x: CX, y: 900, size: 640, color: 'rgba(51,199,190,.16)', stroke: '5px rgba(184,237,232,.55)', font: 'Bungee', shadow: false, drift: 6 });
    FX.subject(ctx, { src: S('step-1-photo-00'), w: 760, x: CX, y: 850, from: 'pop', at: 0.05, float: 5, zoom: 0.05, dur: 0.6 });
    FX.scan(ctx, { at: 0.35, dur: 1.4, x: 400, y: 842, w: 388, h: 652, color: COL.teal, seed: 8 });
    FX.type(ctx, { text: 'La IA compara su foto...', at: 0.15, cps: 30, x: 70, y: 330, size: 62, color: '#B8EDE8', bg: 'rgba(0,0,0,.28)' });
    FX.pop(ctx, { items: [
      { text: 'rasgos', at: 1.1, x: 220, y: 1300, rot: -6, bg: COL.teal, color: '#fff', size: 64 },
      { text: 'color', at: 1.3, x: 480, y: 1290, rot: 4, bg: COL.lilac, color: COL.ink, size: 64 },
      { text: 'tamaño', at: 1.5, x: 740, y: 1300, rot: -3, bg: COL.orange, color: COL.ink, size: 64 },
    ] });
    FX.pop(ctx, { items: [{ text: 'con perritos encontrados cerca', at: 1.95, x: CX, y: 1440, rot: -2, bg: COL.cream, color: COL.ink, size: 58 }] });
  });

  // I4 · Alerta a vecinos que activaron sus avisos, refugios y casas de paso (8.4-11.4)
  scene(8.4, 11.4, { trans: 'paw', origin: [CX, 950], transDur: 0.55 }, ctx => {
    FX.bg(ctx, { colors: [COL.orange, COL.coral], angle: 170, blobs: [{ x: CX, y: 950, r: 650, color: 'rgba(255,246,234,.30)' }] });
    FX.radar(ctx, { x: CX, y: 950, at: 0.1, color: 'rgba(255,255,255,.75)', count: 4, period: 1.2, max: 1400, layer: 'behind' });
    FX.sprite(ctx, { src: S('celular-huella'), w: 290, x: CX, y: 950, enter: 'pop', at: 0.05, extra: lt => ({ r: Math.sin(lt * 30) * 6 * clamp(1 - Math.abs(Math.sin(lt * 1.6))) }) });
    FX.sprite(ctx, { src: S('campana'), w: 130, x: 690, y: 750, enter: 'pop', at: 0.3, extra: lt => ({ r: Math.sin(lt * 18) * 16 }) });
    FX.sfx(ctx, { at: 0.35, kind: 'bell', x: 665 });
    FX.sprite(ctx, { src: S('abuelo'), w: 260, x: 200, y: 760, enter: 'pop', at: 0.55, sfx: 'pop_soft' });
    FX.sprite(ctx, { src: S('nino-celular'), w: 250, x: 820, y: 1130, enter: 'pop', at: 0.8, sfx: 'pop_soft' });
    FX.sprite(ctx, { src: S('casita'), w: 280, x: 210, y: 1170, enter: 'pop', at: 1.05, sfx: 'pop_soft' });
    FX.pop(ctx, { items: [
      { text: 'vecinos', at: 0.75, x: 210, y: 960, rot: -6, bg: '#fff', color: COL.coral, size: 62 },
      { text: 'refugios', at: 1.0, x: 790, y: 1310, rot: 5, bg: COL.purple, color: '#fff', size: 62 },
      { text: 'casas de paso', at: 1.25, x: 270, y: 1320, rot: -4, bg: COL.teal, color: '#fff', size: 62 },
    ] });
    FX.node(ctx, { html: C.notif({ title: 'Perrito perdido cerca de ti', text: 'Beagle con collar rojo · a 800 m' }).replace('class="notif"', 'class="notif" style="width:720px"'), at: 0.4, x: CX, y: 400, enter: 'drop', dur: 0.7, scale: 1.12, sfx: 'notif' });
    FX.pop(ctx, { items: [{ text: 'a quienes activaron sus alertas', at: 1.7, x: CX, y: 1450, rot: 0, cls: 'tag', size: 62, color: '#fff' }] });
  });

  // I5 · Posible coincidencia: te avisamos (11.4-14.4)
  scene(11.4, 14.4, { trans: 'whip', transDur: 0.45 }, ctx => {
    FX.bg(ctx, { colors: [COL.lilac, COL.purple], angle: 200, pattern: 'paws', patternColor: 'rgba(255,255,255,.08)', blobs: [{ x: CX, y: 950, r: 600, color: 'rgba(255,246,234,.25)' }] });
    const join = dir => lt => ({ x: dir * -50 * E.inOutCubic(clamp((lt - 0.7) / 0.6)) });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-sentado', name: 'Rocky', tags: ['Perdido hoy'], badge: 'PERDIDO', badgeColor: COL.coral }), at: 0.05, x: 290, y: 900, enter: 'left', rot: -7, scale: 0.68, float: 5, extra: join(-1) });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-ladra', name: '¿Rocky?', tags: ['Visto en el parque'], badge: 'ENCONTRADO', badgeColor: COL.tealD, bg: 'linear-gradient(160deg,#FFE3B8,#F7C6D9)' }), at: 0.25, x: 750, y: 900, enter: 'right', rot: 7, scale: 0.68, float: 5, extra: join(1) });
    FX.sfx(ctx, { at: 0.5, kind: 'bark', x: 750 });
    FX.ring(ctx, { at: 0.95, dur: 1.0, to: 92, x: CX, y: 870, size: 270, color: COL.teal, label: 'posible coincidencia' });
    FX.hand(ctx, { text: 'si alguien lo encuentra...', at: 0.05, dur: 0.8, x: CX, y: 360, size: 92, color: '#fff', underline: COL.orange, rot: -3 });
    FX.icon(ctx, { kind: 'bell', at: 2.15, x: 800, y: 1310, size: 110, color: COL.orange, bounce: false, wiggle: 18 });
    FX.pop(ctx, { items: [{ text: '¡te avisamos!', at: 2.2, x: 440, y: 1380, rot: -4, bg: COL.orange, color: COL.ink, size: 96, ease: 'elastic' }] });
  });

  // I6 · El reencuentro (14.4-17.4)
  scene(14.4, 17.4, { trans: 'zoom', transDur: 0.45 }, ctx => {
    FX.bg(ctx, { colors: ['#FFB36B', COL.pink, COL.lilac], angle: 180, blobs: [{ x: CX, y: 1050, r: 700, color: 'rgba(255,246,234,.55)' }] });
    FX.scatter(ctx, { text: 'REENCUENTRO', at: 0.1, dur: 0.8, x: CX, y: 440, size: 132, color: COL.cream, font: 'Lilita One', seed: 31, spread: 700 });
    FX.sprite(ctx, { src: S('step-3-reunion-00'), w: 760, x: CX, y: 970, enter: 'up', at: 0, dur: 0.7, float: 5 });
    FX.sfx(ctx, { at: 0.6, kind: 'howl', x: 600 });
    FX.sfx(ctx, { at: 2.0, kind: 'pant', x: 600 });
    FX.sprite(ctx, { src: S('corazon-coral'), w: 110, x: 150, y: 820, enter: 'pop', at: 0.9, float: 10 });
    FX.sprite(ctx, { src: S('corazon-lila'), w: 100, x: 860, y: 760, enter: 'pop', at: 1.1, float: 12 });
    FX.floaters(ctx, { kind: 'heart', count: 12, area: [60, 600, 900, 1450], colors: [COL.coral, COL.pink, '#fff', COL.lilac], seed: 27, at: 0.8, size: [30, 72], rise: 120 });
    FX.hand(ctx, { text: '¡de vuelta a casa!', at: 1.25, dur: 0.9, x: CX, y: 1430, size: 112, color: '#fff', underline: COL.coral, rot: -3 });
  });

  // I7 · Puente a adopción (17.4-19.8): "¿Buscas un nuevo amigo?" + ADOPTA detrás del beagle
  scene(17.4, 19.8, { trans: 'whipUp', transDur: 0.45 }, ctx => {
    FX.bg(ctx, { colors: [COL.teal, '#29A7C4'], angle: 165, pattern: 'paws', patternColor: 'rgba(255,255,255,.09)', blobs: [{ x: 160, y: 420, r: 420, color: 'rgba(247,168,196,.55)' }, { x: 900, y: 1450, r: 520, color: 'rgba(185,166,245,.6)' }] });
    FX.hand(ctx, { text: '¿Buscas un nuevo amigo?', at: 0.1, dur: 0.8, x: CX, y: 350, size: 90, color: '#fff', underline: COL.orange, rot: -2 });
    FX.giant(ctx, { lines: [{ text: 'ADOPTA', size: 220, color: COL.cream }], at: 0.3, x: CX, y: 700, font: 'Lilita One', color: COL.cream, drift: 8 });
    FX.sprite(ctx, { src: S('beagle-sentado'), w: 700, x: 540, y: 1130, enter: 'up', at: 0, dur: 0.6, float: 6 });
    FX.sfx(ctx, { at: 0.7, kind: 'bark_double', x: 540 });
    FX.floaters(ctx, { kind: 'heart', count: 7, area: [90, 560, 900, 1300], colors: [COL.pink, '#fff', COL.lilac], seed: 4, at: 0.9, size: [34, 66], rise: 60 });
  });

  // I8 · Desliza, descubre, enamórate (19.8-22.8)
  scene(19.8, 22.8, { trans: 'whip', transDur: 0.45 }, ctx => {
    FX.bg(ctx, { colors: [COL.purple, '#A68BF0'], angle: 200, blobs: [{ x: 120, y: 1450, r: 480, color: 'rgba(51,199,190,.45)' }, { x: 960, y: 420, r: 420, color: 'rgba(247,168,196,.5)' }], pattern: 'hearts', patternColor: 'rgba(255,255,255,.06)', patternSize: 110 });
    const swipeOut = (t0, dir) => lt => { const k = E.inCubic(clamp((lt - t0) / 0.45)); return { x: dir * k * 1400, r: dir * k * 26, y: -k * 120 }; };
    const cy = 900, sc = 0.9;
    FX.node(ctx, { html: C.dogcard({ dog: 'cachorro-beagle', name: 'Canela', tags: ['Cachorra', 'Juguetona'], bg: 'linear-gradient(160deg,#FFE3B8,#F7C6D9)' }), at: 0.05, x: CX, y: cy, enter: 'up', rot: 4, scale: sc * 0.94, float: 5 });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-sentado', name: 'Luna', tags: ['2 años', 'Cariñosa'] }) + '<div class="swipe-mark" style="left:40px;color:#33C7BE;border-color:#33C7BE;rotate:-14deg">¡SÍ!</div>', at: 0.08, x: CX, y: cy, enter: 'up', rot: -2, scale: sc, float: 5, sfx: false, extra: swipeOut(1.75, 1) });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-ladra', name: 'Toby', tags: ['1 año', 'Activo'], bg: 'linear-gradient(160deg,#E4DBFF,#FFD9E6)' }) + '<div class="swipe-mark" style="right:40px;color:#E8574F;border-color:#E8574F;rotate:14deg">PASO</div>', at: 0.11, x: CX, y: cy, enter: 'up', rot: 3, scale: sc, float: 5, sfx: false, extra: swipeOut(0.8, -1) });
    FX.sfx(ctx, { at: 0.85, kind: 'swipe', x: 200 });
    FX.sfx(ctx, { at: 1.8, kind: 'swipe', x: 840 });
    FX.sfx(ctx, { at: 2.0, kind: 'yip', x: 700 });
    FX.pop(ctx, { items: [
      { text: 'DESLIZA →', at: 0.25, x: 330, y: 360, rot: -6, bg: '#fff', color: COL.purple, size: 88, out: 1.9 },
      { text: 'DESCUBRE', at: 1.05, x: 640, y: 1400, rot: 5, bg: COL.teal, color: '#fff', size: 84, wiggle: 6 },
    ] });
    FX.burst(ctx, { text: '¡ENAMÓRATE!', at: 2.05, x: CX, y: 370, size: 112, color: COL.pink, rays: '#fff', font: 'Lilita One', seed: 21 });
  });

  // I9 · Compatibilidad: tu ritmo, tu casa, tu familia (22.8-26.4)
  scene(22.8, 26.4, { trans: 'circle', origin: [CX, 370], transDur: 0.5 }, ctx => {
    FX.bg(ctx, { colors: [COL.orange, '#F8CB73'], angle: 165, pattern: 'spark', patternColor: 'rgba(255,255,255,.12)', patternSize: 150, blobs: [{ x: 900, y: 1400, r: 500, color: 'rgba(232,87,79,.35)' }] });
    FX.subject(ctx, { src: '../masks/compatibility.png', w: 860, x: 800, y: 1130, from: 'right', rot: 5, float: 8, zoom: 0.04, dur: 0.7 });
    FX.type(ctx, { text: 'Cuéntanos cómo vives', at: 0.15, cps: 30, x: 70, y: 340, size: 66, color: COL.ink, bg: '#fff' });
    FX.pop(ctx, { items: [{ text: '¡encajan contigo!', at: 1.0, x: 330, y: 520, rot: -7, bg: COL.purple, color: '#fff', size: 74 }] });
    FX.stack(ctx, { lines: [
      { text: 'TU RITMO', at: 1.5, size: 104, color: '#fff', bg: COL.teal, rot: -4 },
      { text: 'TU CASA', at: 1.9, size: 104, color: '#fff', bg: COL.coral, rot: 3, dx: 40 },
      { text: 'TU FAMILIA', at: 2.3, size: 104, color: '#fff', bg: COL.purple, rot: -2, dx: 10 },
    ], x: 60, y: 900, gap: 175 });
  });

  // I10 · Cierre (26.4-30): logo, beagle, "repórtalo gratis" / "adopta gratis", "Link en la bio"
  scene(26.4, 30, { trans: 'paw', origin: [CX, 1000], transDur: 0.55 }, ctx => {
    FX.bg(ctx, { colors: [COL.cream, '#FFE7C2'], angle: 175, pattern: 'paws', patternColor: 'rgba(124,92,224,.07)', blobs: [{ x: CX, y: 860, r: 520, color: 'rgba(51,199,190,.25)' }] });
    FX.radar(ctx, { x: CX, y: 900, at: 0.3, color: 'rgba(124,92,224,.30)', count: 3, period: 1.6, max: 1000, layer: 'behind' });
    FX.logo(ctx, { at: 0.1, x: CX, y: 430, scale: 0.74, colorA: COL.ink, colorB: COL.teal });
    FX.sprite(ctx, { src: S('beagle-sentado'), w: 580, x: CX, y: 850, enter: 'pop', at: 0.35, float: 5 });
    FX.sfx(ctx, { at: 0.6, kind: 'bark', x: CX });
    FX.pop(ctx, { items: [
      { text: 'Repórtalo gratis', at: 0.95, x: 340, y: 1170, rot: -5, bg: COL.coral, color: '#fff', size: 76 },
      { text: 'Adopta gratis', at: 1.25, x: 690, y: 1270, rot: 4, bg: COL.teal, color: '#fff', size: 76 },
    ] });
    FX.button(ctx, { text: 'Link en la bio', at: 1.75, x: CX, y: 1420, bg: COL.purple, color: '#fff', size: 84 });
  });
})();
