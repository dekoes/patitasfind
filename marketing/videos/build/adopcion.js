/* Video 1 · Adopción (60 s, 1080x1920). Los tiempos coinciden con GUION.md. */
(function () {
  const { FX, scene, E, prog, lerp, clamp } = PF;
  const { COL, S } = C;

  // A1 · Gancho: "¿Y si tu mejor amigo ya te está esperando?"
  scene(0, 4.2, { trans: 'cut' }, ctx => {
    FX.bg(ctx, { colors: [COL.teal, '#29A7C4'], angle: 165, pattern: 'paws', patternColor: 'rgba(255,255,255,.09)', blobs: [{ x: 160, y: 380, r: 420, color: 'rgba(247,168,196,.55)' }, { x: 960, y: 1500, r: 520, color: 'rgba(185,166,245,.6)' }] });
    FX.giant(ctx, { lines: [{ text: 'TE ESTÁ', size: 230 }, { text: 'ESPERANDO', size: 168, color: COL.orange }], at: 0.25, y: 700, font: 'Lilita One', color: COL.cream, drift: 10 });
    FX.sprite(ctx, { src: S('beagle-sentado'), w: 820, x: 560, y: 1330, enter: 'up', at: 0, dur: 0.8, float: 6 });
    FX.sfx(ctx, { at: 0.75, kind: 'bark', x: 560 });
    FX.sfx(ctx, { at: 3.2, kind: 'bark_double', x: 560 });
    FX.hand(ctx, { text: '¿Y si tu mejor amigo...', at: 0.3, dur: 1.2, x: 540, y: 330, size: 100, color: '#fff', underline: COL.orange });
    FX.floaters(ctx, { kind: 'heart', count: 7, area: [90, 520, 990, 1250], colors: [COL.pink, '#fff', COL.lilac], seed: 4, at: 1.2, size: [36, 70], rise: 60 });
  });

  // A2 · Problema: "Miles de perritos buscan una familia... y tú, ¿a quién buscas?"
  scene(4.2, 11.2, { trans: 'paw', origin: [560, 1250], transDur: 0.7 }, ctx => {
    FX.bg(ctx, { colors: [COL.cream, '#FFE5CC'], angle: 170, pattern: 'paws', patternColor: 'rgba(124,92,224,.07)', blobs: [{ x: 900, y: 300, r: 380, color: 'rgba(242,169,59,.35)' }] });
    const dogs = ['beagle-sentado', 'beagle-ladra', 'cachorro-beagle'];
    const caps = ['Luna', 'Toby', 'Canela', 'Max', 'Nala', 'Coco', 'Bruno', 'Kira', 'Rocky'];
    const bgs = ['linear-gradient(160deg,#B8EDE8,#E4DBFF)', 'linear-gradient(160deg,#FFE3B8,#F7C6D9)', 'linear-gradient(160deg,#E4DBFF,#FFD9E6)'];
    const fade = lt => ({ o: lt + 0 > 4.0 ? lerp(1, 0.28, E.inOutCubic(clamp((lt - 4.0) / 0.6))) : 1 });
    for (let i = 0; i < 9; i++) {
      const col = i % 3, row = Math.floor(i / 3);
      const at = 0.35 + i * 0.12;
      FX.node(ctx, {
        html: C.polaroid({ dog: dogs[(i + row) % 3], cap: caps[i], bg: bgs[(i + col) % 3], flip: i % 2 === 1 }),
        at, x: 210 + col * 330 + (row % 2 ? 20 : -10), y: 700 + row * 400, enter: 'drop', dur: 0.9, sfx: 'polaroid', rot: [-7, 4, -3, 6, -5, 3, -4, 7, -2][i], float: 4,
        extra: lt => fade(lt + at),
      });
    }
    FX.stack(ctx, { lines: [{ text: 'MILES', at: 0.25, size: 230, color: COL.orange, font: 'Bungee', rot: -4 }], x: 60, y: 300, anchor: 'l' });
    FX.pop(ctx, { items: [{ text: 'de perritos', at: 1.0, x: 800, y: 470, rot: 6, bg: COL.purple, color: '#fff', size: 66 }] });
    FX.highlight(ctx, { text: 'buscan una familia', at: 2.7, x: 540, y: 1560, size: 96, marker: COL.pink, color: COL.ink, rot: -2 });
    FX.hand(ctx, { text: 'y tú, ¿a quién buscas?', at: 4.3, dur: 1.2, x: 540, y: 1110, size: 118, color: COL.purple, underline: COL.orange, rot: -4 });
    FX.icon(ctx, { kind: 'heart', at: 5.5, x: 900, y: 960, size: 120, color: COL.coral, bounce: false, wiggle: 12 });
  });

  // A3 · Desliza, descubre, enamórate
  scene(11.2, 18.2, { trans: 'whip', transDur: 0.55 }, ctx => {
    FX.bg(ctx, { colors: [COL.purple, '#A68BF0'], angle: 200, blobs: [{ x: 120, y: 1500, r: 480, color: 'rgba(51,199,190,.45)' }, { x: 980, y: 400, r: 420, color: 'rgba(247,168,196,.5)' }], pattern: 'hearts', patternColor: 'rgba(255,255,255,.06)', patternSize: 110 });
    const swipeOut = (t0, dir) => lt => {
      const k = E.inCubic(clamp((lt - t0) / 0.55));
      return { x: dir * k * 1400, r: dir * k * 26, y: -k * 120 };
    };
    // de atrás hacia adelante: Canela (se queda), Luna (desliza a la derecha), Toby (desliza a la izquierda)
    FX.node(ctx, { html: C.dogcard({ dog: 'cachorro-beagle', name: 'Canela', tags: ['Cachorra', 'Juguetona'], bg: 'linear-gradient(160deg,#FFE3B8,#F7C6D9)' }), at: 0.1, x: 540, y: 1000, enter: 'up', rot: 4, scale: 0.92, float: 5 });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-sentado', name: 'Luna', tags: ['2 años', 'Cariñosa', 'Mediana'] }) + '<div class="swipe-mark" style="left:40px;color:#33C7BE;border-color:#33C7BE;rotate:-14deg">¡SÍ!</div>', at: 0.15, x: 540, y: 1000, enter: 'up', rot: -2, float: 5, extra: swipeOut(3.6, 1) });
    FX.node(ctx, { html: C.dogcard({ dog: 'beagle-ladra', name: 'Toby', tags: ['1 año', 'Activo'], bg: 'linear-gradient(160deg,#E4DBFF,#FFD9E6)' }) + '<div class="swipe-mark" style="right:40px;color:#E8574F;border-color:#E8574F;rotate:14deg">PASO</div>', at: 0.2, x: 540, y: 1000, enter: 'up', rot: 3, float: 5, extra: swipeOut(1.4, -1) });
    FX.sfx(ctx, { at: 1.45, kind: 'swipe', x: 200 });
    FX.sfx(ctx, { at: 3.65, kind: 'swipe', x: 880 });
    FX.sfx(ctx, { at: 3.9, kind: 'yip', x: 700 });
    FX.pop(ctx, { items: [
      { text: 'DESLIZA →', at: 0.55, x: 330, y: 330, rot: -6, bg: '#fff', color: COL.purple, size: 96, out: 4.0 },
      { text: 'DESCUBRE', at: 2.1, x: 760, y: 1560, rot: 5, bg: COL.teal, color: '#fff', size: 92, wiggle: 6 },
    ] });
    FX.burst(ctx, { text: '¡ENAMÓRATE!', at: 4.3, x: 540, y: 340, size: 140, color: COL.pink, rays: '#fff', font: 'Lilita One', seed: 21 });
    FX.floaters(ctx, { kind: 'heart', count: 10, area: [80, 520, 1000, 1500], colors: [COL.pink, COL.coral, '#fff'], seed: 9, at: 4.5, size: [40, 90], rise: 90 });
  });

  // A4 · Compatibilidad: tu ritmo, tu casa, tu familia
  scene(18.2, 26.2, { trans: 'circle', origin: [540, 340], transDur: 0.7 }, ctx => {
    FX.bg(ctx, { colors: [COL.orange, '#F8CB73'], angle: 165, pattern: 'spark', patternColor: 'rgba(255,255,255,.12)', patternSize: 150, blobs: [{ x: 900, y: 1500, r: 500, color: 'rgba(232,87,79,.35)' }] });
    FX.subject(ctx, { src: '../masks/compatibility.png', w: 1000, x: 770, y: 1150, from: 'right', rot: 5, float: 8, zoom: 0.04 });
    FX.type(ctx, { text: 'Cuéntanos cómo vives', at: 0.3, cps: 22, x: 60, y: 300, size: 70, color: COL.ink, bg: '#fff' });
    FX.pop(ctx, { items: [{ text: '¡encajan contigo!', at: 2.6, x: 330, y: 560, rot: -8, bg: COL.purple, color: '#fff', size: 80 }] });
    FX.stack(ctx, { lines: [
      { text: 'TU RITMO', at: 4.2, size: 112, color: '#fff', bg: COL.teal, rot: -4 },
      { text: 'TU CASA', at: 5.0, size: 112, color: '#fff', bg: COL.coral, rot: 3, dx: 40 },
      { text: 'TU FAMILIA', at: 5.8, size: 112, color: '#fff', bg: COL.purple, rot: -2, dx: 10 },
    ], x: 60, y: 900, gap: 190 });
  });

  // A5 · ¡Match! y chat en la app
  scene(26.2, 33.2, { trans: 'zoom', transDur: 0.5 }, ctx => {
    FX.bg(ctx, { colors: [COL.pink, COL.lilac], angle: 170, pattern: 'hearts', patternColor: 'rgba(255,255,255,.12)', patternSize: 120, blobs: [{ x: 200, y: 1600, r: 480, color: 'rgba(255,255,255,.35)' }] });
    FX.card(ctx, { src: '../src/match.png', w: 640, x: 540, y: 1000, rot: -3, from: 'pop', at: 0.1 });
    FX.burst(ctx, { text: '¡MATCH!', at: 0.3, x: 540, y: 380, size: 190, color: '#fff', rays: COL.orange, font: 'Bungee', seed: 33 });
    FX.chat(ctx, { msgs: [
      { side: 'me', text: '¡Hola! ¿Luna se lleva bien con niños?', at: 2.8 },
      { side: 'them', text: '¡Sí! Es súper cariñosa', at: 4.4 },
    ], x: 540, y: 1230, gap: 210, width: 820 });
    FX.icon(ctx, { kind: 'shield', at: 5.5, x: 860, y: 640, size: 120, color: COL.teal, bounce: false });
    FX.pop(ctx, { items: [{ text: 'chat en la app', at: 5.6, x: 640, y: 760, rot: 6, cls: 'chip', size: 56 }] });
  });

  // A6 · Confianza: refugios verificados, adopción gratis
  scene(33.2, 40.2, { trans: 'whipUp', transDur: 0.55 }, ctx => {
    FX.bg(ctx, { colors: [COL.navy, '#2E2558'], angle: 160, pattern: 'paws', patternColor: 'rgba(255,255,255,.04)', patternSize: 160, blobs: [{ x: 540, y: 960, r: 650, color: 'rgba(124,92,224,.35)' }] });
    FX.trail(ctx, { from: [80, 1700], to: [1000, 220], at: 0.1, steps: 12, every: 0.22, size: 64, color: 'rgba(255,246,234,.35)', layer: 'behind' });
    FX.stamp(ctx, { text: 'REFUGIOS<br>VERIFICADOS', at: 0.6, x: 540, y: 560, rot: -7, color: COL.teal, size: 92 });
    FX.icon(ctx, { kind: 'shield', at: 1.0, x: 910, y: 400, size: 130, color: COL.teal, bounce: false });
    FX.stamp(ctx, { text: 'ADOPTAR<br>ES GRATIS', at: 2.4, x: 540, y: 1000, rot: 6, color: COL.orange, size: 108 });
    FX.hand(ctx, { text: 'porque adoptar no es comprar', at: 4.1, dur: 1.5, x: 540, y: 1400, size: 104, color: COL.cream, underline: COL.pink, rot: -3 });
  });

  // A7 · Emoción: una familia completa
  scene(40.2, 50.2, { trans: 'circle', origin: [540, 1400], transDur: 0.75 }, ctx => {
    FX.bg(ctx, { colors: ['#FFB36B', COL.pink, COL.lilac], angle: 180, blobs: [{ x: 540, y: 1100, r: 700, color: 'rgba(255,246,234,.55)' }] });
    FX.scatter(ctx, { text: 'FAMILIA', at: 0.4, x: 540, y: 640, size: 240, color: COL.cream, font: 'Lilita One', seed: 12, spread: 800 });
    FX.curve(ctx, { text: 'primer paseo · travesuras · siestas juntos · mil besos · primer paseo · travesuras · ', at: 1.2, cx: 540, cy: 1160, r: 520, speed: 7, size: 46, color: 'rgba(255,255,255,.9)' });
    FX.sprite(ctx, { src: S('family-hug-00'), w: 1060, x: 540, y: 1180, enter: 'up', dur: 0.9, float: 5 });
    FX.sfx(ctx, { at: 1.1, kind: 'howl', x: 540 });
    FX.sfx(ctx, { at: 6.0, kind: 'pant', x: 600 });
    FX.pop(ctx, { items: [
      { text: 'primer paseo', at: 3.4, x: 290, y: 1560, rot: -6, bg: COL.teal, color: '#fff', size: 72 },
      { text: 'travesuras', at: 5.0, x: 800, y: 1450, rot: 7, bg: COL.orange, color: COL.ink, size: 72, wiggle: 9 },
    ] });
    FX.hand(ctx, { text: 'una familia completa', at: 6.8, dur: 1.2, x: 540, y: 330, size: 112, color: '#fff', underline: COL.coral, rot: -3 });
    FX.floaters(ctx, { kind: 'heart', count: 12, area: [60, 700, 1020, 1500], colors: [COL.coral, COL.pink, '#fff', COL.lilac], seed: 17, at: 2.0, size: [34, 80], rise: 110 });
  });

  // A8 · Cerca de ti
  scene(50.2, 54.4, { trans: 'zoom', transDur: 0.5 }, ctx => {
    FX.bg(ctx, { colors: [COL.teal, COL.purple], angle: 165, pattern: 'paws', patternColor: 'rgba(255,255,255,.07)', blobs: [{ x: 900, y: 1200, r: 520, color: 'rgba(247,168,196,.4)' }] });
    FX.card(ctx, { src: '../src/map.png', w: 600, x: 740, y: 1150, rot: 6, from: 'right', at: 0.1 });
    FX.radar(ctx, { x: 700, y: 1100, at: 0.6, color: 'rgba(255,255,255,.6)', count: 3, period: 1.4, max: 900, layer: 'behind' });
    FX.rise(ctx, { lines: [{ text: 'Encuentra a tu', size: 104, anchor: 'l' }, { text: 'compañero ideal', size: 104, color: COL.ink, bg: COL.orange, anchor: 'l' }], at: 0.3, x: 60, y: 330, gap: 140 });
    FX.icon(ctx, { kind: 'pin', at: 1.9, x: 600, y: 980, size: 110, color: COL.coral });
    FX.icon(ctx, { kind: 'pin', at: 2.2, x: 900, y: 1080, size: 90, color: COL.orange });
    FX.pop(ctx, { items: [{ text: 'cerca de ti', at: 2.1, x: 260, y: 700, rot: -5, cls: 'chip', size: 64 }] });
  });

  // A9 · Cierre: logo + llamada a la acción
  scene(54.4, 60, { trans: 'paw', origin: [540, 1000], transDur: 0.75 }, ctx => {
    FX.bg(ctx, { colors: [COL.cream, '#FFE7C2'], angle: 175, pattern: 'paws', patternColor: 'rgba(124,92,224,.07)', blobs: [{ x: 540, y: 760, r: 520, color: 'rgba(51,199,190,.25)' }] });
    FX.radar(ctx, { x: 540, y: 1250, at: 0.3, color: 'rgba(124,92,224,.35)', count: 3, period: 1.8, max: 1100, layer: 'behind' });
    FX.logo(ctx, { at: 0.2, x: 540, y: 470, scale: 0.8, colorA: COL.ink, colorB: COL.teal });
    FX.sprite(ctx, { src: S('beagle-sentado'), w: 600, x: 540, y: 1180, enter: 'pop', at: 0.6, float: 5 });
    FX.sfx(ctx, { at: 0.95, kind: 'bark', x: 540 });
    FX.sfx(ctx, { at: 4.4, kind: 'yip', x: 560 });
    FX.hand(ctx, { text: 'él ya te está esperando', at: 1.9, dur: 1.2, x: 540, y: 760, size: 96, color: COL.purple, underline: COL.orange, rot: -3 });
    FX.button(ctx, { text: 'Adopta hoy', at: 2.8, x: 540, y: 1560, bg: COL.purple, color: '#fff', size: 84 });
    FX.pop(ctx, { items: [{ text: 'Link en la bio', at: 3.6, x: 540, y: 1690, rot: 0, cls: 'tag', size: 60, color: COL.ink }] });
  });
})();
