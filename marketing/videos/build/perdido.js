/* Video 2 · Si se pierde tu perrito (60 s, 1080x1920). Los tiempos coinciden con GUION.md. */
(function () {
  const { FX, scene, E, prog, lerp, clamp } = PF;
  const { COL, S } = C;

  // P1 · Gancho: "Se perdió... y cada minuto cuenta"
  scene(0, 4.4, { trans: 'cut' }, ctx => {
    FX.bg(ctx, { colors: [COL.navy, '#2B2350'], angle: 170, blobs: [{ x: 540, y: 1000, r: 720, color: 'rgba(232,87,79,.22)' }] });
    FX.trail(ctx, { from: [120, 1750], to: [960, 260], at: 0, steps: 11, every: 0.12, size: 66, color: 'rgba(255,246,234,.55)', fadeAfter: 1.3, layer: 'behind' });
    FX.node(ctx, { html: C.poster(), at: 0.05, x: 540, y: 1000, enter: 'swing', dur: 0.9, rot: -3, scale: 0.92 });
    FX.glitch(ctx, { text: 'SE PERDIÓ', at: 0.25, x: 540, y: 320, size: 128, settle: 1.8 });
    FX.sfx(ctx, { at: 0.9, kind: 'heartbeat', x: 540 });
    FX.sfx(ctx, { at: 1.75, kind: 'heartbeat', x: 540 });
    FX.clock(ctx, { at: 2.0, x: 150, y: 1610, size: 150, color: COL.cream });
    FX.type(ctx, { text: 'cada minuto cuenta', at: 2.15, cps: 24, x: 250, y: 1610, size: 74, color: COL.cream, font: 'Baloo 2' });
  });

  // P2 · Respira. Sube una foto clara de su carita
  scene(4.4, 11.2, { trans: 'whip', transDur: 0.55 }, ctx => {
    FX.bg(ctx, { colors: [COL.cream, '#D3F3EF'], angle: 170, pattern: 'paws', patternColor: 'rgba(51,199,190,.10)', blobs: [{ x: 250, y: 1300, r: 520, color: 'rgba(185,166,245,.35)' }] });
    FX.giant(ctx, { lines: ['RESPIRA'], at: 0.15, x: 540, y: 600, size: 250, color: COL.teal, font: 'Lilita One', drift: 12 });
    FX.sprite(ctx, { src: S('chica-foto'), w: 600, x: 330, y: 1180, enter: 'left', at: 0.2, dur: 0.8, float: 4 });
    FX.node(ctx, { html: C.phone({ inner: C.camera({ dog: 'beagle-sentado' }) }), at: 1.5, x: 800, y: 1080, enter: 'right', rot: 7, scale: 0.6, float: 6 });
    FX.fill(ctx, { text: 'SUBE UNA FOTO', at: 2.0, fillAt: 2.8, x: 540, y: 320, size: 92, color: COL.orange, stroke: COL.ink, font: 'Bungee', rot: -3 });
    FX.flash(ctx, { at: 3.5 });
    FX.node(ctx, { html: C.polaroid({ dog: 'beagle-sentado', cap: '¡lista!', bg: 'linear-gradient(160deg,#CFEFEA,#E9E1FF)' }), at: 3.7, x: 830, y: 1430, enter: 'pop', rot: 9, scale: 0.9, float: 4, sfx: 'polaroid' });
    FX.hand(ctx, { text: 'clara, de su carita', at: 4.3, dur: 1.2, x: 420, y: 1580, size: 96, color: COL.ink, underline: COL.teal, rot: -3 });
  });

  // P3 · La IA analiza sus rasgos y compara con encontrados cerca
  scene(11.2, 19.2, { trans: 'circle', origin: [830, 1430], transDur: 0.7 }, ctx => {
    FX.bg(ctx, { colors: ['#0F3B47', '#1C6D73'], angle: 170, pattern: 'spark', patternColor: 'rgba(184,237,232,.07)', patternSize: 120, blobs: [{ x: 540, y: 1050, r: 620, color: 'rgba(51,199,190,.35)' }] });
    FX.giant(ctx, { lines: ['IA'], at: 0.3, x: 540, y: 1000, size: 760, color: 'rgba(51,199,190,.16)', stroke: '5px rgba(184,237,232,.55)', font: 'Bungee', shadow: false, drift: 6 });
    FX.subject(ctx, { src: S('step-1-photo-00'), w: 920, x: 540, y: 1060, from: 'pop', at: 0.1, float: 6, zoom: 0.05 });
    FX.scan(ctx, { at: 0.6, dur: 2.2, x: 395, y: 1050, w: 470, h: 790, color: COL.teal, seed: 8 });
    FX.type(ctx, { text: 'Analizando con IA...', at: 0.4, cps: 20, x: 60, y: 300, size: 66, color: '#B8EDE8', bg: 'rgba(0,0,0,.25)' });
    FX.pop(ctx, { items: [
      { text: 'rasgos', at: 3.4, x: 860, y: 520, rot: 6, bg: COL.teal, color: '#fff', size: 66 },
      { text: 'color', at: 3.9, x: 900, y: 650, rot: -5, bg: COL.lilac, color: COL.ink, size: 66 },
      { text: 'tamaño', at: 4.4, x: 850, y: 780, rot: 4, bg: COL.orange, color: COL.ink, size: 66 },
    ] });
    FX.icon(ctx, { kind: 'pin', at: 5.6, x: 150, y: 1520, size: 120, color: COL.coral });
    FX.pop(ctx, { items: [{ text: 'encontrados cerca de ti', at: 5.8, x: 590, y: 1580, rot: -3, bg: COL.cream, color: COL.ink, size: 70 }] });
  });

  // P4 · Tu alerta llega a vecinos, refugios y casas de paso
  scene(19.2, 28.2, { trans: 'paw', origin: [540, 980], transDur: 0.75 }, ctx => {
    FX.bg(ctx, { colors: [COL.orange, COL.coral], angle: 170, blobs: [{ x: 540, y: 980, r: 650, color: 'rgba(255,246,234,.30)' }] });
    FX.radar(ctx, { x: 540, y: 980, at: 0.2, color: 'rgba(255,255,255,.75)', count: 4, period: 1.5, max: 1500, layer: 'behind' });
    FX.giant(ctx, { lines: ['ALERTA'], at: 0.25, x: 540, y: 420, size: 230, color: 'rgba(255,255,255,.28)', font: 'Bungee', shadow: false });
    FX.sprite(ctx, { src: S('celular-huella'), w: 330, x: 540, y: 980, enter: 'pop', at: 0.1, extra: lt => ({ r: Math.sin(lt * 30) * 6 * clamp(1 - Math.abs(Math.sin(lt * 1.2))) }) });
    FX.sprite(ctx, { src: S('campana'), w: 150, x: 720, y: 740, enter: 'pop', at: 0.6, extra: lt => ({ r: Math.sin(lt * 18) * 16 }) });
    FX.sprite(ctx, { src: S('abuelo'), w: 300, x: 210, y: 640, enter: 'pop', at: 1.8 });
    FX.sprite(ctx, { src: S('nino-celular'), w: 280, x: 870, y: 610, enter: 'pop', at: 2.1 });
    FX.sprite(ctx, { src: S('chica-celebra'), w: 280, x: 210, y: 1350, enter: 'pop', at: 2.4 });
    FX.sprite(ctx, { src: S('casita'), w: 330, x: 860, y: 1360, enter: 'pop', at: 5.3 });
    FX.pop(ctx, { items: [
      { text: 'vecinos', at: 2.4, x: 230, y: 880, rot: -6, bg: '#fff', color: COL.coral, size: 64 },
      { text: 'refugios', at: 4.1, x: 860, y: 860, rot: 5, bg: COL.purple, color: '#fff', size: 64 },
      { text: 'casas de paso', at: 5.6, x: 760, y: 1560, rot: -4, bg: COL.teal, color: '#fff', size: 64 },
    ] });
    FX.node(ctx, { html: C.notif({ title: 'Perrito perdido cerca de ti', text: 'Beagle con collar rojo · a 800 m' }), at: 6.3, x: 540, y: 290, enter: 'drop', dur: 0.8, sfx: 'notif' });
    FX.sfx(ctx, { at: 0.65, kind: 'bell', x: 720 });
    FX.pop(ctx, { items: [{ text: 'a quienes activaron sus alertas', at: 7.0, x: 540, y: 1650, rot: 0, cls: 'tag', size: 46, color: '#fff' }] });
  });

  // P5 · Posible coincidencia: te avisamos
  scene(28.2, 36.2, { trans: 'whip', transDur: 0.55 }, ctx => {
    FX.bg(ctx, { colors: [COL.lilac, COL.purple], angle: 200, pattern: 'paws', patternColor: 'rgba(255,255,255,.08)', blobs: [{ x: 540, y: 1000, r: 600, color: 'rgba(255,246,234,.25)' }] });
    const join = dir => lt => ({ x: dir * -60 * E.inOutCubic(clamp((lt - 1.6) / 0.8)) });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-sentado', name: 'Rocky', tags: ['Perdido hoy'], badge: 'PERDIDO', badgeColor: COL.coral }), at: 0.2, x: 280, y: 1010, enter: 'left', rot: -7, scale: 0.74, float: 5, extra: join(-1) });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-ladra', name: '¿Rocky?', tags: ['Visto en el parque'], badge: 'ENCONTRADO', badgeColor: COL.tealD, bg: 'linear-gradient(160deg,#FFE3B8,#F7C6D9)' }), at: 0.7, x: 800, y: 1010, enter: 'right', rot: 7, scale: 0.74, float: 5, extra: join(1) });
    FX.ring(ctx, { at: 2.0, dur: 1.8, to: 92, x: 540, y: 1000, size: 300, color: COL.teal, label: 'posible coincidencia' });
    FX.sfx(ctx, { at: 1.0, kind: 'bark', x: 800 });
    FX.hand(ctx, { text: 'si alguien lo encuentra...', at: 0.3, dur: 1.2, x: 540, y: 330, size: 104, color: '#fff', underline: COL.orange, rot: -3 });
    FX.icon(ctx, { kind: 'bell', at: 4.3, x: 860, y: 1440, size: 130, color: COL.orange, bounce: false, wiggle: 18 });
    FX.pop(ctx, { items: [{ text: '¡te avisamos!', at: 4.4, x: 470, y: 1520, rot: -4, bg: COL.orange, color: COL.ink, size: 104, ease: 'elastic' }] });
  });

  // P6 · Chat en la app y punto de encuentro público
  scene(36.2, 44.2, { trans: 'circle', origin: [470, 1520], transDur: 0.7 }, ctx => {
    FX.bg(ctx, { colors: [COL.teal, '#2AA9C9'], angle: 160, pattern: 'paws', patternColor: 'rgba(255,255,255,.08)', blobs: [{ x: 900, y: 1300, r: 500, color: 'rgba(185,166,245,.45)' }] });
    FX.card(ctx, { src: '../src/map.png', w: 560, x: 760, y: 1180, rot: 6, from: 'up', at: 0.1, layer: 'behind' });
    FX.chat(ctx, { msgs: [
      { side: 'them', text: '¡Hola! Creo que vi a tu perrito: trae collar rojo', at: 0.6 },
      { side: 'me', text: '¡Sí es él! ¿Dónde nos vemos?', at: 2.4 },
      { side: 'them', text: 'En la entrada del parque, a las 6', at: 4.0 },
    ], x: 540, y: 330, gap: 250, width: 820 });
    FX.icon(ctx, { kind: 'pin', at: 4.9, x: 700, y: 1100, size: 120, color: COL.coral });
    FX.stamp(ctx, { text: 'LUGAR PÚBLICO', at: 5.4, x: 470, y: 1530, rot: -6, color: COL.coral, size: 92, bg: 'rgba(255,246,234,.92)' });
    FX.icon(ctx, { kind: 'shield', at: 5.8, x: 930, y: 1440, size: 120, color: COL.cream, bounce: false });
  });

  // P7 · El reencuentro
  scene(44.2, 52.2, { trans: 'zoom', transDur: 0.5 }, ctx => {
    FX.bg(ctx, { colors: ['#FFB36B', COL.pink, COL.lilac], angle: 180, blobs: [{ x: 540, y: 1100, r: 720, color: 'rgba(255,246,234,.55)' }] });
    FX.scatter(ctx, { text: 'REENCUENTRO', at: 0.3, x: 540, y: 560, size: 152, color: COL.cream, font: 'Lilita One', seed: 31, spread: 700 });
    FX.sprite(ctx, { src: S('step-3-reunion-00'), w: 880, x: 540, y: 1160, enter: 'up', at: 0, dur: 0.9, float: 5 });
    FX.sfx(ctx, { at: 0.8, kind: 'howl', x: 600 });
    FX.sfx(ctx, { at: 4.2, kind: 'pant', x: 600 });
    FX.sprite(ctx, { src: S('corazon-coral'), w: 120, x: 170, y: 900, enter: 'pop', at: 1.6, float: 10 });
    FX.sprite(ctx, { src: S('corazon-lila'), w: 110, x: 920, y: 820, enter: 'pop', at: 1.9, float: 12 });
    FX.sprite(ctx, { src: S('corazon-coral2'), w: 90, x: 950, y: 1300, enter: 'pop', at: 2.2, float: 9 });
    FX.floaters(ctx, { kind: 'heart', count: 14, area: [60, 650, 1020, 1550], colors: [COL.coral, COL.pink, '#fff', COL.lilac], seed: 27, at: 1.4, size: [30, 76], rise: 120 });
    FX.hand(ctx, { text: 'que tanto esperabas', at: 2.8, dur: 1.2, x: 540, y: 1580, size: 100, color: '#fff', underline: COL.coral, rot: -3 });
  });

  // P8 · Cierre: el cartel recibe el sello "¡En casa!" + logo y llamada a la acción
  scene(52.2, 60, { trans: 'paw', origin: [540, 1150], transDur: 0.75 }, ctx => {
    FX.bg(ctx, { colors: [COL.cream, '#D3F3EF'], angle: 175, pattern: 'paws', patternColor: 'rgba(124,92,224,.07)', blobs: [{ x: 540, y: 700, r: 520, color: 'rgba(242,169,59,.25)' }] });
    FX.node(ctx, { html: C.poster(), at: 0.1, x: 540, y: 660, enter: 'pop', rot: 3, scale: 0.62 });
    FX.stamp(ctx, { text: '¡EN CASA!', at: 1.0, x: 560, y: 700, rot: -12, color: COL.tealD, size: 120, bg: 'rgba(255,246,234,.85)' });
    FX.sfx(ctx, { at: 1.6, kind: 'bark_double', x: 560 });
    FX.sfx(ctx, { at: 1.4, kind: 'applause', x: 540 });
    FX.rise(ctx, { lines: [{ text: 'Repórtalo', size: 96, color: COL.ink }, { text: 'GRATIS', size: 110, color: '#fff', bg: COL.coral }], at: 1.9, x: 540, y: 1150, gap: 135 });
    FX.logo(ctx, { at: 3.4, x: 540, y: 1430, scale: 0.66, colorA: COL.ink, colorB: COL.teal });
    FX.hand(ctx, { text: 'juntos lo traemos a casa', at: 4.6, dur: 1.2, x: 540, y: 1600, size: 84, color: COL.purple, underline: COL.orange, rot: -2 });
    FX.pop(ctx, { items: [{ text: 'Link en la bio', at: 5.8, x: 540, y: 1720, rot: 0, cls: 'tag', size: 54, color: COL.ink }] });
  });
})();
