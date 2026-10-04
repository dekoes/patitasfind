/* ============================================================
   PatitasFind — Motor de apariencia
   Se carga en <head> (sin defer) para aplicar el tema antes de
   pintar. La pantalla de Apariencia se construye con Theme.mount().
   ============================================================ */
'use strict';

const Theme = (() => {
  const KEY = 'patitas_theme';
  const root = document.documentElement;

  const PALETTES = {
    patitas:  { label: 'PatitasFind', teal: '#33C7BE', orange: '#8E66D9', lila: '#DCC7FA', green: '#86E0D4', blue: '#A9D6F9', pink: '#F6C8A4', yellow: '#C9F0EB', sand: '#EFE3FD', grad: ['#E8F8F6', '#EBDFFC', '#DCC7FA', '#F6D9C4'], solid: '#F3EDFC' },
    oceano:   { label: 'Océano', teal: '#1FA2C9', orange: '#3B5BDB', lila: '#C9DEFA', green: '#9BE7E0', blue: '#B8D8F8', pink: '#CFE9F5', yellow: '#D4F3F7', sand: '#E3EFFB', grad: ['#E6F7FB', '#D9ECFB', '#C9DEFA', '#DFF5F1'], solid: '#EAF4FB' },
    atardecer:{ label: 'Atardecer', teal: '#F2709C', orange: '#FF9F43', lila: '#FFD6C9', green: '#FFE3A3', blue: '#FFC9D9', pink: '#FFD1B3', yellow: '#FFEDC2', sand: '#FFE9DF', grad: ['#FFF1E6', '#FFE0E9', '#FFD6C9', '#FFE9B8'], solid: '#FFF0EA' },
    bosque:   { label: 'Bosque', teal: '#2F9E6E', orange: '#B5763F', lila: '#D8E8C8', green: '#A8DDB5', blue: '#C5E1D2', pink: '#EED9BE', yellow: '#E2F0CB', sand: '#EAF1E1', grad: ['#EEF7EA', '#E2F0DA', '#D8E8C8', '#F1E6D2'], solid: '#EEF4E8' },
    algodon:  { label: 'Algodón de azúcar', teal: '#FF7EB6', orange: '#7C6CF2', lila: '#E6D7FF', green: '#C7F5E8', blue: '#CDE7FF', pink: '#FFD3E8', yellow: '#FFF1C9', sand: '#F7E9FF', grad: ['#FFE9F4', '#F2E6FF', '#E6D7FF', '#DDF4FF'], solid: '#FBEFFA' },
    lavanda:  { label: 'Lavanda', teal: '#8E66D9', orange: '#33C7BE', lila: '#E4D6FB', green: '#C8F1EC', blue: '#D5DEFA', pink: '#F3D9EE', yellow: '#E9E2FB', sand: '#F1EAFD', grad: ['#F4EEFF', '#E9DDFD', '#DCC7FA', '#E8F8F6'], solid: '#F1EAFD' },
    mono:     { label: 'Monocromo', teal: '#3A3F55', orange: '#6B7088', lila: '#E3E4EA', green: '#D9DBE3', blue: '#E6E8EF', pink: '#ECEDF1', yellow: '#EEF0F4', sand: '#F1F2F5', grad: ['#F7F7F9', '#EEEFF3', '#E3E4EA', '#F2F2F4'], solid: '#F2F3F6' },
  };
  const CHART_PALETTES = {
    marca: null,
    pastel: ['#9ADCD6', '#C6B3F2', '#F8CBA6', '#B9DBF7', '#BDECDF', '#FFB4A8'],
    vibrante: ['#00B8A9', '#7B2CBF', '#FF6B35', '#1E88E5', '#FFC300', '#E63946'],
    mono: ['#1D2233', '#3A3F55', '#5A6078', '#7D8399', '#A2A7B8', '#C6C9D4'],
    atardecer: ['#F2709C', '#FF9F43', '#FFC75F', '#F9F871', '#845EC2', '#D65DB1'],
  };
  const FONTS = {
    baloo:    { label: 'Baloo 2', css: "'Baloo 2'", g: 'Baloo+2:wght@500;600;700;800' },
    fredoka:  { label: 'Fredoka', css: "'Fredoka'", g: 'Fredoka:wght@400;500;600;700' },
    nunito:   { label: 'Nunito', css: "'Nunito'", g: 'Nunito:wght@500;600;700;800;900' },
    poppins:  { label: 'Poppins', css: "'Poppins'", g: 'Poppins:wght@400;500;600;700;800' },
    quicksand:{ label: 'Quicksand', css: "'Quicksand'", g: 'Quicksand:wght@500;600;700' },
    inter:    { label: 'Inter', css: "'Inter'", g: 'Inter:wght@400;500;600;700;800' },
    patrick:  { label: 'Patrick Hand', css: "'Patrick Hand'", g: 'Patrick+Hand' },
    comfortaa:{ label: 'Comfortaa', css: "'Comfortaa'", g: 'Comfortaa:wght@500;600;700' },
    system:   { label: 'Del sistema', css: 'system-ui,-apple-system,Segoe UI,Roboto', g: null },
  };
  const MASCOTS = { blanco: ['#FFF6EC', '#B5763F'], caramelo: ['#E0A160', '#7A5238'], dorado: ['#F6C344', '#7A5238'], negro: ['#3A3440', '#1D1A22'], gris: ['#C9CCD6', '#6B7088'], chocolate: ['#8A5A3B', '#4A2E1E'], panda: ['#FFFFFF', '#1D2233'] };
  const MAPS = {
    osm: { label: 'Clásico', url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', attr: '© OpenStreetMap' },
    claro: { label: 'Claro', url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', attr: '© OpenStreetMap © CARTO' },
    voyager: { label: 'Voyager', url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', attr: '© OpenStreetMap © CARTO' },
    oscuro: { label: 'Oscuro', url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', attr: '© OpenStreetMap © CARTO' },
  };

  const o = (pairs) => pairs.map(([v, label, extra]) => ({ v, label, ...(extra || {}) }));
  /* Definición de todas las opciones (grupo, tipo, valores, predeterminado) */
  const SCHEMA = [
    // Tema y colores
    { key: 'palette', group: 'colores', label: 'Paleta de colores', type: 'choice', def: 'patitas', options: Object.entries(PALETTES).map(([v, p]) => ({ v, label: p.label, sw2: [p.teal, p.orange] })) },
    { key: 'mode', group: 'colores', label: 'Modo', type: 'choice', def: 'light', options: o([['light', '☀️ Claro'], ['dark', '🌙 Oscuro'], ['auto', '🌗 Automático']]) },
    { key: 'primary', group: 'colores', label: 'Color principal', type: 'color', def: '', swatches: ['#33C7BE', '#1FA2C9', '#2F9E6E', '#F2709C', '#FF7EB6', '#8E66D9', '#3A3F55', '#E86A5E'] },
    { key: 'accent', group: 'colores', label: 'Color de acento', type: 'color', def: '', swatches: ['#8E66D9', '#3B5BDB', '#FF9F43', '#B5763F', '#7C6CF2', '#33C7BE', '#FF6B5C', '#6B7088'] },
    { key: 'bg', group: 'colores', label: 'Fondo de pantallas', type: 'choice', def: 'gradient', options: o([['gradient', 'Degradado'], ['solid', 'Sólido'], ['paws', 'Huellitas'], ['bones', 'Huesitos'], ['dots', 'Lunares'], ['grid', 'Cuadrícula'], ['waves', 'Ondas']]) },
    { key: 'bgInt', group: 'colores', label: 'Intensidad del patrón', type: 'range', def: 60, min: 10, max: 100, step: 5, unit: '%' },
    { key: 'contrast', group: 'colores', label: 'Alto contraste', type: 'toggle', def: false },

    // Tipografía
    { key: 'fontTitle', group: 'texto', label: 'Fuente de títulos', type: 'choice', def: 'baloo', options: Object.entries(FONTS).map(([v, f]) => ({ v, label: f.label, font: f.css })) },
    { key: 'fontBody', group: 'texto', label: 'Fuente de texto', type: 'choice', def: 'baloo', options: Object.entries(FONTS).map(([v, f]) => ({ v, label: f.label, font: f.css })) },
    { key: 'scale', group: 'texto', label: 'Tamaño de la interfaz', type: 'range', def: 100, min: 85, max: 120, step: 5, unit: '%' },
    { key: 'titleW', group: 'texto', label: 'Grosor de títulos', type: 'choice', def: '800', options: o([['600', 'Ligero'], ['700', 'Medio'], ['800', 'Grueso']]) },
    { key: 'ls', group: 'texto', label: 'Espaciado de letras en títulos', type: 'range', def: 0, min: -1, max: 3, step: .5, unit: 'px' },

    // Superficies y bordes
    { key: 'surface', group: 'superficies', label: 'Estilo de tarjetas y bordes', type: 'choice', def: 'classic', options: o([['classic', '🧸 Clásico'], ['soft', '☁️ Suave'], ['glass', '🫧 Cristal'], ['outline', '✏️ Contorno'], ['dashed', '🎈 Punteado'], ['brutal', '🧱 Neo-brutal'], ['gradient', '🌈 Degradado'], ['sketch', '🖍️ A mano']]) },
    { key: 'radius', group: 'superficies', label: 'Redondeo de esquinas', type: 'range', def: 100, min: 0, max: 150, step: 10, unit: '%' },
    { key: 'border', group: 'superficies', label: 'Grosor de bordes', type: 'range', def: 2, min: 0, max: 4, step: .5, unit: 'px' },
    { key: 'shadow', group: 'superficies', label: 'Profundidad de sombras', type: 'range', def: 4, min: 0, max: 10, step: 1, unit: 'px' },
    { key: 'input', group: 'superficies', label: 'Estilo de campos', type: 'choice', def: 'box', options: o([['box', 'Caja'], ['underline', 'Subrayado'], ['filled', 'Relleno'], ['pill', 'Píldora']]) },
    { key: 'chip', group: 'superficies', label: 'Estilo de etiquetas', type: 'choice', def: 'pill', options: o([['pill', 'Píldora'], ['square', 'Cuadrada'], ['outline', 'Contorno'], ['soft', 'Suave']]) },
    { key: 'density', group: 'superficies', label: 'Densidad', type: 'choice', def: 'normal', options: o([['compact', 'Compacta'], ['normal', 'Normal'], ['cozy', 'Cómoda']]) },

    // Botones
    { key: 'btn', group: 'botones', label: 'Estilo de botones', type: 'choice', def: 'chunky', options: o([['chunky', '🍪 Gordito'], ['flat', 'Plano'], ['outline', 'Contorno'], ['glass', 'Cristal'], ['gradient', 'Degradado'], ['neon', '⚡ Neón'], ['3d', '3D'], ['minimal', 'Minimal'], ['bubble', 'Burbuja']]) },
    { key: 'btnShape', group: 'botones', label: 'Forma de botones', type: 'choice', def: 'pill', options: o([['pill', 'Píldora'], ['rounded', 'Redondeado'], ['square', 'Cuadrado'], ['leaf', 'Hoja'], ['ticket', 'Boleto']]) },
    { key: 'hover', group: 'botones', label: 'Efecto al pasar el cursor', type: 'choice', def: 'ears', options: o([['ears', '🐶 Orejitas y colita'], ['lift', 'Levitar'], ['glow', 'Brillo'], ['magnet', '🧲 Imán'], ['tilt', 'Inclinación 3D'], ['colorshift', 'Cambio de color'], ['wiggle', 'Meneo'], ['none', 'Ninguno']]) },
    { key: 'press', group: 'botones', label: 'Efecto al presionar', type: 'choice', def: 'squish', options: o([['squish', 'Aplastar'], ['jelly', '🍮 Gelatina'], ['ripple', 'Onda de color'], ['bounce', 'Rebote'], ['heartbeat', '💓 Latido'], ['sink', 'Hundir'], ['flash', 'Destello'], ['pawburst', '🐾 Lluvia de huellitas']]) },
    { key: 'shine', group: 'botones', label: 'Destello en botones principales', type: 'toggle', def: true },

    // Cursor e interacción
    { key: 'cursor', group: 'interaccion', label: 'Cursor', type: 'choice', def: 'normal', options: o([['normal', 'Normal'], ['paw', '🐾 Huellita'], ['bone', '🦴 Hueso'], ['dot', 'Punto']]) },
    { key: 'trail', group: 'interaccion', label: 'Estela del cursor', type: 'choice', def: 'none', options: o([['none', 'Ninguna'], ['paws', '🐾 Huellitas'], ['hearts', '💜 Corazones'], ['sparkles', '✨ Destellos'], ['bones', '🦴 Huesitos'], ['rainbow', '🌈 Arcoíris']]) },
    { key: 'tapFx', group: 'interaccion', label: 'Efecto al tocar la pantalla', type: 'choice', def: 'paw', options: o([['paw', 'Huellita'], ['ring', 'Anillo'], ['hearts', 'Corazones'], ['none', 'Nada']]) },
    { key: 'vibrate', group: 'interaccion', label: 'Vibración al presionar (celular)', type: 'toggle', def: true },
    { key: 'sound', group: 'interaccion', label: 'Sonidos divertidos', type: 'toggle', def: false },

    // Animaciones
    { key: 'tx', group: 'animaciones', label: 'Transición entre pantallas', type: 'choice', def: 'slide', options: o([['slide', 'Deslizar'], ['fade', 'Desvanecer'], ['zoom', 'Zoom'], ['flip', 'Voltear'], ['rise', 'Subir'], ['none', 'Sin transición']]) },
    { key: 'speed', group: 'animaciones', label: 'Velocidad de animaciones', type: 'choice', def: '1', options: o([['1.6', '🐢 Lenta'], ['1', 'Normal'], ['.6', '🐇 Rápida']]) },
    { key: 'loader', group: 'animaciones', label: 'Animación de carga', type: 'choice', def: 'run', options: o([['run', 'Perrito corriendo'], ['chase', 'Persiguiendo su cola'], ['sniff', 'Olfateando'], ['trail', 'Rastro de huellitas']]) },
    { key: 'confetti', group: 'animaciones', label: 'Confeti en celebraciones', type: 'choice', def: '1', options: o([['2', '🎉 Mucho'], ['1', 'Normal'], ['.4', 'Poquito'], ['0', 'Apagado']]) },
    { key: 'bgPaws', group: 'animaciones', label: 'Huellitas flotantes de fondo', type: 'toggle', def: true },
    { key: 'motion', group: 'animaciones', label: 'Reducir movimiento', type: 'toggle', def: false },

    // Gráficas
    { key: 'chartType', group: 'graficas', label: 'Tipo de gráfica preferido', type: 'choice', def: 'area', options: o([['line', '📈 Línea'], ['area', 'Área'], ['bar', '📊 Barras'], ['hbar', 'Barras horizontales'], ['donut', '🍩 Dona'], ['radar', '🕸️ Radar']]) },
    { key: 'chartAnim', group: 'graficas', label: 'Cómo se dibujan', type: 'choice', def: 'draw', options: o([['draw', 'Dibujar'], ['grow', 'Crecer'], ['stagger', 'Escalonado'], ['bounce', 'Rebote'], ['wipe', 'Barrido'], ['fade', 'Desvanecer'], ['none', 'Sin animación']]) },
    { key: 'chartCurve', group: 'graficas', label: 'Líneas', type: 'choice', def: 'smooth', options: o([['smooth', '〰️ Curvas'], ['straight', '📐 Rectas'], ['step', '⎍ Escalonadas']]) },
    { key: 'chartPoints', group: 'graficas', label: 'Marcadores de datos', type: 'choice', def: 'paw', options: o([['circle', '● Círculo'], ['paw', '🐾 Huellita'], ['diamond', '◆ Rombo'], ['square', '■ Cuadrado'], ['none', 'Ninguno']]) },
    { key: 'chartPalette', group: 'graficas', label: 'Colores de gráficas', type: 'choice', def: 'marca', options: Object.keys(CHART_PALETTES).map(v => ({ v, label: { marca: 'De la marca', pastel: 'Pastel', vibrante: 'Vibrante', mono: 'Monocromo', atardecer: 'Atardecer' }[v] })) },
    { key: 'chartThick', group: 'graficas', label: 'Grosor de línea', type: 'range', def: 3, min: 1, max: 6, step: .5, unit: 'px' },
    { key: 'chartGrid', group: 'graficas', label: 'Cuadrícula', type: 'toggle', def: true },
    { key: 'chartLabels', group: 'graficas', label: 'Mostrar valores', type: 'toggle', def: false },
    { key: 'chartFill', group: 'graficas', label: 'Relleno degradado', type: 'toggle', def: true },

    // Diseño general
    { key: 'nav', group: 'diseno', label: 'Barra de navegación', type: 'choice', def: 'floating', options: o([['floating', 'Flotante'], ['docked', 'Pegada abajo'], ['labels', 'Con nombres'], ['minimal', 'Transparente'], ['bubble', 'Burbuja activa']]) },
    { key: 'toast', group: 'diseno', label: 'Posición de avisos', type: 'choice', def: 'top', options: o([['top', 'Arriba'], ['bottom', 'Abajo']]) },
    { key: 'photo', group: 'diseno', label: 'Fotos de perritos', type: 'choice', def: 'normal', options: o([['normal', 'Normal'], ['square', 'Cuadradas'], ['wide', 'Panorámicas'], ['tall', 'Altas']]) },
    { key: 'map', group: 'diseno', label: 'Estilo del mapa', type: 'choice', def: 'osm', options: Object.entries(MAPS).map(([v, m]) => ({ v, label: m.label })) },
    { key: 'mascot', group: 'diseno', label: 'Color del perrito mascota', type: 'choice', def: 'blanco', options: Object.entries(MASCOTS).map(([v, c]) => ({ v, label: v[0].toUpperCase() + v.slice(1), sw2: c })) },
  ];
  const GROUPS = [
    ['colores', '🎨 Tema y colores'], ['texto', '🔤 Tipografía'], ['superficies', '🧩 Tarjetas y bordes'], ['botones', '🔘 Botones'],
    ['interaccion', '🖱️ Cursor e interacción'], ['animaciones', '✨ Animaciones'], ['graficas', '📊 Gráficas'], ['diseno', '🧭 Diseño general'],
  ];

  const defaults = Object.fromEntries(SCHEMA.map(s => [s.key, s.def]));
  let cfg = { ...defaults };
  try { cfg = { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { }

  const loadedFonts = new Set(['baloo', 'patrick']);
  function loadFont(id) {
    const f = FONTS[id];
    if (!f || !f.g || loadedFonts.has(id)) return;
    loadedFonts.add(id);
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = `https://fonts.googleapis.com/css2?family=${f.g}&display=swap`;
    document.head.appendChild(l);
  }

  const darkMQ = window.matchMedia('(prefers-color-scheme: dark)');
  function isDark() { return cfg.mode === 'dark' || (cfg.mode === 'auto' && darkMQ.matches); }

  function apply() {
    const p = PALETTES[cfg.palette] || PALETTES.patitas;
    const st = root.style;
    const set = (k, v) => st.setProperty(k, v);
    const primary = cfg.primary || p.teal, accent = cfg.accent || p.orange;
    set('--teal', primary); set('--teal-d', `color-mix(in srgb, ${primary} 78%, #000)`);
    set('--orange', accent); set('--orange-d', `color-mix(in srgb, ${accent} 80%, #000)`); set('--purple', accent);
    const dark = isDark();
    ['lila', 'green', 'blue', 'pink', 'yellow', 'sand'].forEach(k => { if (dark) st.removeProperty('--' + k); else set('--' + k, p[k]); });
    if (dark) { st.removeProperty('--bg-grad'); st.removeProperty('--bg-solid'); }
    else { set('--bg-grad', `linear-gradient(165deg,${p.grad[0]} 0%,${p.grad[1]} 42%,${p.grad[2]} 72%,${p.grad[3]} 100%)`); set('--bg-solid', p.solid); }
    if (dark && cfg.bg === 'solid') set('--bg-solid', '#1F1C33');
    set('--bg-int', cfg.bgInt / 100);
    set('--rs', cfg.radius / 100);
    set('--bw', cfg.border + 'px');
    set('--sh-y', cfg.shadow + 'px');
    set('--title-w', cfg.titleW);
    set('--ls', cfg.ls + 'px');
    set('--spd', cfg.speed);
    set('--ui-scale', cfg.scale / 100);
    const ff = id => `${(FONTS[id] || FONTS.baloo).css},'Arial Rounded MT Bold',system-ui,sans-serif`;
    set('--font-title', ff(cfg.fontTitle)); set('--font-body', ff(cfg.fontBody));
    loadFont(cfg.fontTitle); loadFont(cfg.fontBody);
    const m = MASCOTS[cfg.mascot] || MASCOTS.blanco;
    set('--dog-fur', m[0]); set('--dog-ear', m[1]);
    const attrs = { mode: dark ? 'dark' : 'light', surface: cfg.surface, bg: cfg.bg, input: cfg.input, chip: cfg.chip, density: cfg.density, btn: cfg.btn,
      btnshape: cfg.btnShape, hover: cfg.hover, press: cfg.press === 'pawburst' ? 'squish' : cfg.press, cursor: cfg.cursor === 'normal' ? null : cfg.cursor,
      tx: cfg.tx, nav: cfg.nav, toast: cfg.toast, photo: cfg.photo, contrast: cfg.contrast ? 'high' : null, motion: cfg.motion ? 'reduce' : null,
      shine: cfg.shine ? null : 'off', bgpaws: cfg.bgPaws ? null : 'off', touchpaws: cfg.tapFx === 'paw' ? null : 'off' };
    Object.entries(attrs).forEach(([k, v]) => { if (v == null) root.removeAttribute('data-' + k); else root.setAttribute('data-' + k, v); });
    const meta = document.querySelector('meta[name=theme-color]');
    if (meta) meta.content = dark ? '#1F1838' : p.lila;
    applyScale();
    applyCharts();
    document.dispatchEvent(new CustomEvent('themechange', { detail: cfg }));
  }

  /* Escala: zoom sobre las pantallas y capas, compensando el tamaño */
  function applyScale() {
    const z = cfg.scale / 100;
    let st = document.getElementById('theme-scale');
    if (!st) { st = document.createElement('style'); st.id = 'theme-scale'; document.head.appendChild(st); }
    st.textContent = z === 1 ? '' : `#screens > .screen, #device > .modal, #nav, #cookie-banner{zoom:${z}} #screens > .screen, #device > .modal{width:${100 / z}%;height:${100 / z}%;right:auto;bottom:auto}`;
  }

  function chartDefaults() {
    return { curve: cfg.chartCurve, animation: cfg.motion ? 'none' : cfg.chartAnim, points: cfg.chartPoints, grid: cfg.chartGrid, valueLabels: cfg.chartLabels,
      palette: CHART_PALETTES[cfg.chartPalette] || null, thickness: +cfg.chartThick, gradientFill: cfg.chartFill, speed: 1 / Math.max(.2, +cfg.speed) };
  }
  function applyCharts() {
    if (!window.PFCharts) return;
    try { PFCharts.setDefaults ? PFCharts.setDefaults(chartDefaults()) : Object.assign(PFCharts.defaults, chartDefaults()); } catch { }
  }

  function save() { try { localStorage.setItem(KEY, JSON.stringify(diff())); } catch { } }
  function diff() { return Object.fromEntries(Object.entries(cfg).filter(([k, v]) => v !== defaults[k])); }
  function set(key, value) { cfg[key] = value; save(); apply(); }
  function get(key) { return cfg[key]; }
  function reset() { cfg = { ...defaults }; save(); apply(); }

  darkMQ.addEventListener && darkMQ.addEventListener('change', () => { if (cfg.mode === 'auto') apply(); });
  apply();

  /* ============================================================
     Interacción: estela, imán, inclinación, vibración, sonido, toque
     ============================================================ */
  const TRAIL = { paws: '#paw', hearts: '#heart', bones: null, sparkles: '#sparkle' };
  let lastTrail = 0, audioCtx = null;
  function boop(freq = 520) {
    if (!cfg.sound) return;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const t = audioCtx.currentTime, osc = audioCtx.createOscillator(), g = audioCtx.createGain();
      osc.type = 'sine'; osc.frequency.setValueAtTime(freq, t); osc.frequency.exponentialRampToValueAtTime(freq * 1.8, t + .09);
      g.gain.setValueAtTime(.12, t); g.gain.exponentialRampToValueAtTime(.001, t + .16);
      osc.connect(g); g.connect(audioCtx.destination); osc.start(t); osc.stop(t + .17);
    } catch { }
  }
  function initInteractions(device) {
    device.addEventListener('pointermove', e => {
      // Estela
      if (cfg.trail !== 'none' && e.pointerType === 'mouse' && !cfg.motion) {
        const now = performance.now();
        if (now - lastTrail > 45) {
          lastTrail = now;
          const d = device.getBoundingClientRect();
          const el = document.createElement('div');
          el.className = 'trail' + (cfg.trail === 'rainbow' ? ' dot' : '');
          el.style.left = (e.clientX - d.left) + 'px'; el.style.top = (e.clientY - d.top) + 'px';
          el.style.setProperty('--r', (Math.random() * 60 - 30).toFixed(0) + 'deg');
          if (cfg.trail === 'rainbow') el.style.background = `hsl(${(now / 6) % 360} 85% 62%)`;
          else if (cfg.trail === 'bones') el.innerHTML = window.FX ? FX.bone('#fff', 16) : '';
          else el.innerHTML = `<svg viewBox="${cfg.trail === 'paws' ? '0 0 64 64' : '0 0 24 24'}" style="color:${cfg.trail === 'hearts' ? 'var(--orange)' : cfg.trail === 'sparkles' ? '#F6C344' : 'var(--teal)'}"><use href="${TRAIL[cfg.trail]}"/></svg>`;
          (document.getElementById('pawLayer') || device).appendChild(el);
          setTimeout(() => el.remove(), 820);
        }
      }
      // Imán / inclinación
      if (cfg.hover === 'magnet' || cfg.hover === 'tilt') {
        const b = e.target.closest('.btn');
        device.querySelectorAll('.btn[data-mag]').forEach(x => { if (x !== b) { x.style.transform = ''; x.removeAttribute('data-mag'); } });
        if (b && !b.disabled) {
          const r = b.getBoundingClientRect();
          const dx = (e.clientX - r.left - r.width / 2) / (r.width / 2), dy = (e.clientY - r.top - r.height / 2) / (r.height / 2);
          b.dataset.mag = '1';
          b.style.transform = cfg.hover === 'magnet' ? `translate(${dx * 6}px,${dy * 4}px) scale(1.04)` : `perspective(500px) rotateX(${-dy * 12}deg) rotateY(${dx * 12}deg) scale(1.03)`;
        }
      }
    });
    device.addEventListener('pointerleave', () => device.querySelectorAll('.btn[data-mag]').forEach(x => { x.style.transform = ''; x.removeAttribute('data-mag'); }));
    device.addEventListener('pointerdown', e => {
      const btn = e.target.closest('.btn,.round,.iconbtn,.chip,.ap-opt,.nav-item,.fab');
      if (btn) {
        if (cfg.vibrate && navigator.vibrate) { try { navigator.vibrate(12); } catch { } }
        boop(btn.classList.contains('like-btn') ? 700 : 480 + Math.random() * 120);
        if (cfg.press === 'pawburst' && btn.classList.contains('btn') && window.FX) FX.pawBurst(btn, 7);
      }
      if (cfg.tapFx === 'ring' || cfg.tapFx === 'hearts') {
        if (e.target.closest('input,textarea,select,.tcard,#leaflet-map')) return;
        const d = device.getBoundingClientRect();
        const x = e.clientX - d.left, y = e.clientY - d.top;
        if (cfg.tapFx === 'ring') {
          const r = document.createElement('div');
          r.style.cssText = `position:absolute;left:${x - 20}px;top:${y - 20}px;width:40px;height:40px;border-radius:50%;border:3px solid var(--teal);pointer-events:none;z-index:115;animation:ringOut .55s ease-out forwards`;
          (document.getElementById('pawLayer') || device).appendChild(r); setTimeout(() => r.remove(), 600);
        } else if (window.FX) {
          const tmp = document.createElement('div'); tmp.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:1px;height:1px`;
          device.appendChild(tmp); FX.heartBurst(tmp, 4); tmp.remove();
        }
      }
    });
  }

  /* ============================================================
     Pantalla de Apariencia
     ============================================================ */
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function control(s) {
    const v = cfg[s.key];
    if (s.type === 'choice') {
      return `<div class="ap-opts">${s.options.map(op => `<button type="button" class="ap-opt ${String(v) === String(op.v) ? 'on' : ''}" data-k="${s.key}" data-v="${esc(op.v)}" ${op.font ? `style="font-family:${esc(op.font)}"` : ''}>${op.sw2 ? `<span class="sw2"><i style="background:${op.sw2[0]}"></i><i style="background:${op.sw2[1]}"></i></span>` : ''}${esc(op.label)}</button>`).join('')}</div>`;
    }
    if (s.type === 'toggle') return `<div class="ap-switch ${v ? 'on' : ''}" role="switch" aria-checked="${!!v}" tabindex="0" data-k="${s.key}"></div>`;
    if (s.type === 'range') return `<input type="range" class="ap-range" data-k="${s.key}" min="${s.min}" max="${s.max}" step="${s.step}" value="${v}">`;
    if (s.type === 'color') {
      const p = PALETTES[cfg.palette] || PALETTES.patitas;
      const cur = v || (s.key === 'primary' ? p.teal : p.orange);
      return `<div class="ap-colors">${s.swatches.map(c => `<button type="button" class="ap-color ${cur.toLowerCase() === c.toLowerCase() ? 'on' : ''}" style="background:${c}" data-k="${s.key}" data-v="${c}" aria-label="${c}"></button>`).join('')}<input type="color" data-k="${s.key}" value="${cur}" aria-label="Elegir otro color"><button type="button" class="ap-opt" data-k="${s.key}" data-v="">Paleta</button></div>`;
    }
    return '';
  }
  function rowHtml(s) {
    const val = s.type === 'range' ? `<small>${cfg[s.key]}${s.unit || ''}</small>` : '';
    const inline = s.type === 'toggle';
    return `<div class="ap-row" data-row="${s.key}">${inline ? `<div class="between"><span class="ap-lbl" style="margin:0">${esc(s.label)}</span>${control(s)}</div>` : `<div class="ap-lbl"><span>${esc(s.label)}</span>${val}</div>${control(s)}`}</div>`;
  }
  let mounted = null, previewChart = null;
  function mount(container) {
    mounted = container;
    const count = SCHEMA.length;
    container.innerHTML = `
      <div class="ap-preview">
        <div class="card ap-pv-card">
          <div class="between"><b class="h2" style="font-size:17px">Vista previa</b><span class="badge b-teal">${count} opciones</span></div>
          <p class="small muted">Así se verá PatitasFind con tu estilo.</p>
          <div class="row mt8" style="flex-wrap:wrap;gap:8px"><button class="btn btn-sm shine" type="button">Principal</button><button class="btn btn-sm btn-orange" type="button">Acento</button><button class="btn btn-sm btn-ghost" type="button">Secundario</button></div>
          <div class="row mt8" style="gap:8px"><input class="inp grow" placeholder="Campo de texto" style="padding:9px 14px"><span class="chip on">Etiqueta</span></div>
          <div class="ap-pv-chart" id="ap-chart"></div>
        </div>
      </div>
      <div class="row mt8" style="gap:8px;flex-wrap:wrap">
        <button class="btn btn-sm btn-lila" type="button" id="ap-random">🎲 Sorpréndeme</button>
        <button class="btn btn-sm btn-ghost" type="button" id="ap-replay">▶ Repetir gráfica</button>
        <button class="btn btn-sm btn-ghost" type="button" id="ap-export">Copiar estilo</button>
        <button class="btn btn-sm btn-ghost" type="button" id="ap-import">Pegar estilo</button>
        <button class="btn btn-sm btn-ghost" type="button" id="ap-reset">Restablecer</button>
      </div>
      ${GROUPS.map(([g, label], i) => {
        const items = SCHEMA.filter(s => s.group === g);
        return `<details class="card ap-group" ${i < 2 ? 'open' : ''}><summary>${label}<span class="ap-n">${items.length}</span></summary><div class="ap-body">${items.map(rowHtml).join('')}</div></details>`;
      }).join('')}
      <p class="small muted center mt16">Tu estilo se guarda en este dispositivo.</p>`;
    container.addEventListener('click', onClick);
    container.addEventListener('input', onInput);
    container.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('ap-switch')) { e.preventDefault(); e.target.click(); } });
    renderPreviewChart();
    if (window.FX) FX.decorate(container);
  }
  function refreshRow(key) {
    if (!mounted) return;
    const s = SCHEMA.find(x => x.key === key);
    const row = mounted.querySelector(`[data-row="${key}"]`);
    if (s && row) { row.outerHTML = rowHtml(s); if (window.FX) FX.decorate(mounted); }
  }
  function onClick(e) {
    const t = e.target.closest('[data-k],#ap-random,#ap-reset,#ap-export,#ap-import,#ap-replay');
    if (!t) return;
    if (t.id === 'ap-reset') { reset(); return mount(mounted); }
    if (t.id === 'ap-replay') { if (previewChart && previewChart.replay) previewChart.replay(); return; }
    if (t.id === 'ap-random') {
      SCHEMA.forEach(s => {
        if (['motion', 'contrast', 'sound', 'scale', 'mode'].includes(s.key)) return;
        if (s.type === 'choice') cfg[s.key] = s.options[Math.floor(Math.random() * s.options.length)].v;
        else if (s.type === 'toggle') cfg[s.key] = Math.random() > .4;
        else if (s.type === 'range') cfg[s.key] = +(s.min + Math.round(Math.random() * (s.max - s.min) / s.step) * s.step).toFixed(1);
        else if (s.type === 'color') cfg[s.key] = '';
      });
      save(); apply(); mount(mounted);
      if (window.FX) FX.confetti(20 * (+cfg.confetti || 0));
      return;
    }
    if (t.id === 'ap-export') {
      const txt = JSON.stringify(diff());
      (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(() => notify('Estilo copiado 📋'), () => prompt('Copia tu estilo:', txt));
      return;
    }
    if (t.id === 'ap-import') {
      const txt = prompt('Pega aquí el estilo copiado:');
      if (!txt) return;
      try { const obj = JSON.parse(txt); cfg = { ...defaults, ...Object.fromEntries(Object.entries(obj).filter(([k]) => k in defaults)) }; save(); apply(); mount(mounted); notify('Estilo aplicado ✨'); }
      catch { notify('Ese texto no es un estilo válido'); }
      return;
    }
    const key = t.dataset.k;
    const s = SCHEMA.find(x => x.key === key);
    if (!s) return;
    if (s.type === 'toggle') set(key, !cfg[key]);
    else if (s.type === 'choice' || s.type === 'color') { if (t.tagName === 'INPUT') return; set(key, t.dataset.v); }
    refreshRow(key);
    if (key === 'palette') { refreshRow('primary'); refreshRow('accent'); }
    if (key === 'mode' || key === 'palette') renderPreviewChart();
    if (key.startsWith('chart')) renderPreviewChart();
  }
  function onInput(e) {
    const t = e.target;
    const key = t.dataset && t.dataset.k;
    const s = SCHEMA.find(x => x.key === key);
    if (!s) return;
    if (s.type === 'range') {
      set(key, +t.value);
      const lbl = mounted.querySelector(`[data-row="${key}"] .ap-lbl small`);
      if (lbl) lbl.textContent = t.value + (s.unit || '');
      if (key === 'chartThick') renderPreviewChart();
    } else if (s.type === 'color' && t.type === 'color') {
      set(key, t.value);
      mounted.querySelectorAll(`.ap-color[data-k="${key}"]`).forEach(b => b.classList.remove('on'));
    }
  }
  function renderPreviewChart() {
    const el = mounted && mounted.querySelector('#ap-chart');
    if (!el || !window.PFCharts) return;
    if (previewChart && previewChart.destroy) previewChart.destroy();
    const donutish = cfg.chartType === 'donut';
    previewChart = PFCharts.render(el, {
      type: cfg.chartType, height: 150,
      labels: donutish ? ['Disponibles', 'En proceso', 'Adoptados'] : ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
      series: donutish ? [{ name: 'Perritos', data: [12, 5, 9] }] : [{ name: 'Adopciones', data: [2, 5, 3, 8, 6, 11, 9] }, { name: 'Reportes', data: [4, 3, 6, 4, 7, 5, 8] }],
      ...chartDefaults(),
    });
  }
  function notify(msg) { if (window.toast) window.toast(msg, 'ok'); }

  return {
    SCHEMA, GROUPS, PALETTES, MAPS, apply, set, get, reset, mount, initInteractions, chartDefaults,
    get cfg() { return { ...cfg }; },
    mapTiles() { return MAPS[cfg.map] || MAPS.osm; },
    mascot() { return MASCOTS[cfg.mascot] || MASCOTS.blanco; },
    confettiFactor() { return cfg.motion ? 0 : +cfg.confetti; },
    loader() { return cfg.loader; },
    chartType() { return cfg.chartType; },
  };
})();
