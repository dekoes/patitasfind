"""Extras de `Escena` para ilustraciones con fondo transparente donde los personajes se mueven mucho
(hero, family-hug).

En una imagen transparente, quitar una pieza deja un hueco vacío. Si la pieza solo se asoma un poco
(cabeza que se inclina, mano que sube, hoja que se mece) ese hueco se ve. Aquí se agregan:

- `rellenar_bajo`: rellena en la base lo que queda debajo de la pieza, pero solo cerca del contenido que
  se queda (hasta `alcance` px), propagando sus colores. Lo que estaba contra el fondo transparente se
  queda transparente.
- `colchon`: lo mismo pero dentro de otra pieza (p. ej. el cuerpo del perro se extiende debajo de la
  cabeza y de la cola), para que los rellenos se muevan con su grupo.
- `tapa`: copia fija de una zona que se dibuja encima de una pieza (lo que la tapaba en el original).
- `parpadeo`: capa con el ojo cerrado (piel/pelo reconstruido + trazo) que se muestra con opacidad.
- `islas`: elementos sueltos (rayitas, corazones) que caben completos en una región.
"""
import cv2
import numpy as np

from capas import Escena, dibujar, componer


def disco(r):
    r = max(1, int(round(r)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def dilatar(m, r):
    return cv2.dilate(np.asarray(m, np.uint8), disco(r)) > 0


def propagar(rgb, conocido, zona, radio=5, margen=50):
    """Rellena `zona` con los colores de `conocido` (inpaint TELEA) trabajando solo en el recuadro de la zona."""
    ys, xs = np.nonzero(zona)
    if not len(xs):
        return rgb
    h, w = zona.shape
    y0, y1 = max(0, ys.min() - margen), min(h, ys.max() + margen + 1)
    x0, x1 = max(0, xs.min() - margen), min(w, xs.max() + margen + 1)
    sub = np.clip(rgb[y0:y1, x0:x1], 0, 255).astype(np.uint8)
    desconocido = (~conocido[y0:y1, x0:x1]).astype(np.uint8)
    hecho = cv2.inpaint(sub, desconocido, radio, cv2.INPAINT_TELEA).astype(np.float32)
    out = rgb.copy()
    z = zona[y0:y1, x0:x1]
    out[y0:y1, x0:x1][z] = hecho[z]
    return out


class EscenaCapas(Escena):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.alfa0 = self.img[..., 3] / 255
        self.solido0 = self.alfa0 > 0.97

    # ---------- máscaras ----------
    def islas(self, region, min_area=30):
        """Manchas del original (por alfa) que caben completas dentro de la región."""
        duro = (self.alfa0 > 0.3).astype(np.uint8)
        n, et, st, _ = cv2.connectedComponentsWithStats(duro, 8)
        dentro = region > 0.5
        out = np.zeros(region.shape, bool)
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] < min_area:
                continue
            comp = et == i
            if dentro[comp].all():
                out |= comp
        return dilatar(out, 2).astype(np.float32)

    def color(self, fn):
        """Máscara booleana a partir de una función f(r, g, b) sobre el original."""
        r, g, b = (self.img[..., i] for i in range(3))
        return fn(r, g, b)

    # ---------- piezas ----------
    def capa(self, nombre, mascara, pivote=None, grupo=None, clases="", estilo="", extra="", diferir=True,
             alcance=0, donde=None, colchon=None, quitar=True, exclusiva=True):
        """Como `pieza` pero para fondo transparente con rellenos. `alcance`: px de base que se reconstruyen
        debajo (cerca de lo que se queda). `colchon=(zona, px)`: extiende la propia pieza dentro de `zona`
        (lo que otra pieza le tapa) hasta `px`. Por defecto se difiere para apilarla después con `agregar`."""
        m = np.clip(np.asarray(mascara, np.float32), 0, 1)
        if exclusiva:
            m *= 1 - self.tomado
            self.tomado = np.maximum(self.tomado, (m > 0.5).astype(np.float32))
        capa = self.img.copy()
        capa[..., 3] = self.img[..., 3] * m
        if colchon is not None:
            capa = self.extender(capa, *colchon)
        if quitar:
            self._quitar(m)
            self.rellenar_bajo(m, alcance, donde)
        return self.pieza_desde(nombre, capa, pivote, grupo, clases, estilo, extra, diferir)

    def rellenar_bajo(self, m, alcance=0, donde=None):
        # en la costura (borde suave de la máscara sobre contenido opaco) la base conserva el píxel original:
        # en reposo pieza + base dan exactamente el original y no queda una línea semitransparente
        costura = (m > 0.02) & (m < 0.98) & self.solido0
        self.base[costura] = self.img[costura]
        if not alcance:
            return
        conocido = self.base[..., 3] > 0.97 * 255
        cerca = dilatar(conocido, alcance)
        silueta = dilatar(~self.solido0, 2)  # no tocar el contorno exterior (dejaría halo en reposo)
        zona = (m >= 0.98) & cerca & self.solido0 & ~silueta & ~conocido
        if donde is not None:
            zona &= donde > 0.5
        self.base[..., :3] = propagar(self.base[..., :3], conocido, zona)
        self.base[..., 3] = np.where(zona, 255, self.base[..., 3])

    def extender(self, capa, zona, px):
        """Extiende los colores de la pieza dentro de `zona` (hasta `px` desde su parte sólida)."""
        solido = capa[..., 3] > 0.9 * 255
        # solo donde el original era opaco (lo que tapaba otra pieza), nunca hacia el fondo transparente
        dentro = self.solido0 & ~dilatar(~self.solido0, 1)
        nueva = dilatar(solido, px) & (np.asarray(zona) > 0.5) & dentro & ~solido
        capa = capa.copy()
        capa[..., :3] = propagar(capa[..., :3], solido, nueva)
        # borde suavizado para que el colchón no se vea dentado cuando queda a la vista
        suave = cv2.GaussianBlur(nueva.astype(np.float32), (0, 0), 1.1) * 255
        capa[..., 3] = np.where(nueva, 255, np.maximum(capa[..., 3], np.where(solido, 0, suave)))
        return capa

    def tapa(self, nombre, mascara, pivote=None, grupo=None, clases="", estilo="", diferir=True):
        """Copia fija (no se quita de la base ni reserva píxeles) para tapar el borde de otra pieza."""
        capa = self.img.copy()
        capa[..., 3] = self.img[..., 3] * np.clip(np.asarray(mascara, np.float32), 0, 1)
        return self.pieza_desde(nombre, capa, pivote, grupo, clases, estilo, diferir=diferir)

    def parpadeo(self, nombre, ojo, trazo, pivote=None, grupo=None, clases="", estilo="", fuente=None,
                 borde=3):
        """Ojo cerrado: rellena el ojo (máscara bool) con lo que lo rodea y dibuja `trazo(draw, s)` encima.
        `fuente` permite partir de otra capa (p. ej. la pieza con colchón) en vez del original."""
        src = self.img if fuente is None else fuente
        ojo = dilatar(ojo, 3)
        capa = src.copy()
        conocido = (src[..., 3] > 0.97 * 255) & ~ojo
        capa[..., :3] = propagar(capa[..., :3], conocido, ojo, radio=4)
        cubre = cv2.GaussianBlur(dilatar(ojo, borde).astype(np.float32), (0, 0), 1.2)
        capa[..., 3] = np.minimum(cubre, src[..., 3] / 255) * 255
        capa = componer(capa, dibujar(self, trazo))
        return self.pieza_desde(nombre, capa, pivote, grupo, clases, estilo, diferir=True)
