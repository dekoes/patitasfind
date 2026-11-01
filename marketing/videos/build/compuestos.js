/* Piezas gráficas creadas para los videos con el estilo de la marca (se arman con los recortes de las ilustraciones). */
window.C = {
  COL: {
    teal: '#33C7BE', tealD: '#1FA39B', purple: '#7C5CE0', lilac: '#B9A6F5', lilacL: '#EDE6FF', orange: '#F2A93B',
    coral: '#E8574F', pink: '#F7A8C4', cream: '#FFF6EA', ink: '#2B2340', navy: '#1E1B3A',
  },
  S: n => `../sprites/${n}.png`,

  poster({ dog = 'beagle-sentado', title = '¿ME HAS<br>VISTO?', text = 'Se busca a Rocky.<br>Responde a su nombre.' } = {}) {
    return `<div class="poster"><i class="tape l"></i><i class="tape r"></i><h3>${title}</h3>` +
      `<div class="ph"><img src="${C.S(dog)}"></div><p>${text}</p></div>`;
  },

  phone({ inner = '' } = {}) {
    return `<div class="phone"><div class="screen"><i class="notch"></i>${inner}</div></div>`;
  },

  camera({ dog = 'beagle-sentado' } = {}) {
    return `<div style="position:absolute;inset:0;background:linear-gradient(170deg,#CFEFEA,#E9E1FF)">` +
      `<img src="${C.S(dog)}" style="position:absolute;left:50%;bottom:150px;width:560px;translate:-50% 0">` +
      `<div style="position:absolute;left:60px;right:60px;top:170px;bottom:300px;border-radius:40px;border:8px dashed rgba(255,255,255,.95)"></div>` +
      `<div style="position:absolute;left:50%;top:110px;translate:-50% 0;background:rgba(43,35,64,.78);color:#fff;font:800 34px 'Baloo 2';padding:6px 26px 2px;border-radius:999px;white-space:nowrap">Encuadra su carita</div>` +
      `<div style="position:absolute;left:50%;bottom:70px;translate:-50% 0;width:130px;height:130px;border-radius:50%;background:#fff;box-shadow:0 0 0 12px rgba(255,255,255,.45)"></div></div>`;
  },

  dogcard({ dog, name, tags = [], badge = null, badgeColor = '#E8574F', bg = 'linear-gradient(160deg,#B8EDE8,#E4DBFF)', flip = false }) {
    return `<div class="dogcard"><div class="ph" style="background:${bg}"><img src="${C.S(dog)}" style="${flip ? 'scale:-1 1' : ''}"></div>` +
      `${badge ? `<div class="badge" style="background:${badgeColor}">${badge}</div>` : ''}` +
      `<div class="info"><div class="name">${name}</div><div class="meta">${tags.map(t => `<span>${t}</span>`).join('')}</div></div></div>`;
  },

  notif({ title, text, icon = 'beagle-sentado', color = '#E8574F' }) {
    return `<div class="notif"><div class="ico" style="background:${color}"><img src="${C.S(icon)}"></div><div><b>${title}</b><span>${text}</span></div></div>`;
  },

  polaroid({ dog, cap = '', bg = 'linear-gradient(160deg,#FFE3B8,#F7C6D9)', flip = false }) {
    return `<div class="polaroid"><div class="ph" style="background:${bg}"><img src="${C.S(dog)}" style="${flip ? 'scale:-1 1' : ''}"></div><div class="cap">${cap}</div></div>`;
  },
};
