"""Escena 'match': la chica y Luna se acercan, chocan con el corazón y ¡es un match!

Los dos círculos (con su aro blanco) salen enteros como piezas: lo que tapa el corazón del centro se
redibuja limpio y la parte de abajo se alarga bajo las tarjetas, que van encima, para que puedan
moverse e inclinarse sin dejar huecos. La franja del teléfono que queda detrás se vuelve a pintar.
Las plantas se alargan por detrás del marco del teléfono, que se repone encima como pieza fija.
"""
import cv2
import numpy as np

from capas import Escena, rellenar


class EscenaCapas(Escena):
    def recorte(self, mascara, no_mezclar=None, umbral_alfa=(6, 70)):
        """Igual que pieza() pero devuelve la capa RGBA (para retocarla antes de guardarla con pieza_desde)."""
        m = np.clip(mascara, 0, 1).astype(np.float32) * (1 - self.tomado)
        self.tomado = np.maximum(self.tomado, (m > 0.5).astype(np.float32))
        self._quitar(m, no_mezclar)
        capa = self.img.copy()
        fondo = self.base[..., :3]
        dif = np.abs(self.img[..., :3] - fondo).max(axis=2)
        t0, t1 = umbral_alfa
        a_color = np.clip((dif - t0) / (t1 - t0), 0, 1)
        nucleo = cv2.erode((m > 0.5).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
        a = np.maximum(a_color, nucleo) * m
        seguro = np.maximum(a, 1e-3)[..., None]
        rgb = fondo + (self.img[..., :3] - fondo) / seguro
        capa[..., :3] = np.clip(np.where(a[..., None] > 0.02, rgb, self.img[..., :3]), 0, 255)
        capa[..., 3] = a * 255
        return capa

    def de_base(self, mascara):
        """Capa con los píxeles actuales de la base (ya sin las piezas de encima) dentro de la máscara."""
        capa = self.base.copy()
        capa[..., 3] = np.clip(mascara, 0, 1) * 255
        return capa


e = EscenaCapas("match", 1000, "Pantalla de match con Luna")
yy, xx = np.mgrid[0:e.H, 0:e.W].astype(np.float32)

CIRC_TU = (411, 595, 143, 154)      # centro x, centro y, radio del disco turquesa, radio con aro blanco
CIRC_LUNA = (707, 600, 146, 157)
CORAZON = (560, 577.5, 60)          # disco blanco del centro
TARJ_TU = (306, 739.5, 551, 987)
TARJ_LUNA = (586, 742.5, 816, 987)
PANTALLA = (251, 250, 248)
TARJETA = (254, 254, 252)


def por_tono(caja, cond, crecer=1):
    """Píxeles de `caja` que cumplen `cond(r, g, b)` (solo la mancha más grande), con borde suave."""
    r, g, b = (e.img[..., i] for i in range(3))
    m = (cond(r, g, b) & (e.rect(caja) > 0.5)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    m = rellenar(lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA]))
    m = cv2.dilate(m, np.ones((2 * crecer + 1,) * 2, np.uint8)).astype(np.float32)
    return cv2.GaussianBlur(m, (0, 0), .7)


def plano(caja, color, radio=0):
    """Pinta un color liso en la base: bajo textos sobre fondo liso el relleno queda perfecto."""
    capa = np.zeros((e.H, e.W, 4), np.float32)
    capa[..., :3] = color
    capa[..., 3] = e.rect(caja, radio) * 255
    e.pintar(capa)


def texto(nombre, caja, **kw):
    """Texto o ícono sobre fondo liso (conserva puntos y acentos pequeños)."""
    return e.pieza(nombre, e.por_color(e.rect(caja), min_area=2), **kw)


def disco(cx, cy, r):
    return np.clip(r - np.hypot(xx - cx, yy - cy) + .5, 0, 1)


# ---------- decoraciones exteriores ----------
e.pieza("corazon-izq", e.por_color(e.rect((122, 414, 220, 532))), pivote=(170, 522),
        clases="a-pop", estilo="--dur:5.4s;--delay:-1.2s")
e.pieza("corazon-der", e.por_color(e.rect((896, 534, 1024, 672))), pivote=(955, 662),
        clases="a-pop", estilo="--dur:4.8s;--delay:-3.4s")
e.pieza("rayitas-lila", e.por_color(e.rect((902, 180, 986, 270))), pivote=(905, 268),
        clases="a-flash", estilo="--dur:2.3s;--delay:-.4s")
e.pieza("rayitas-teal", e.por_color(e.rect((180, 645, 246, 720))), pivote=(244, 648),
        clases="a-flash", estilo="--dur:2.6s;--delay:-1.3s")
e.pieza("rayitas-teal2", e.por_color(e.rect((896, 860, 962, 935))), pivote=(898, 932),
        clases="a-flash", estilo="--dur:2.1s;--delay:-.8s")


# plantas: dentro de un grupo que recorta en el borde interior del marco; se alargan bajo el marco
def planta(nombre, caja, borde, hasta, pivote, estilo):
    capa = e.recorte(e.por_color(e.rect(caja), umbral=30), no_mezclar=e.oscuro())
    paso = 1 if hasta > borde else -1
    col = borde - 4 * paso  # columna de la planta junto al marco (sin el contorno oscuro de este)
    filas = capa[:, col, 3] > 128
    for x in range(col + paso, hasta, paso):
        capa[filas, x] = capa[filas, col]
    return e.pieza_desde(nombre, capa, pivote=pivote, clases="a-sway", estilo=estilo, diferir=True)


it_planta_izq = planta("planta-izq", (56, 940, 253, 1222), 253, 281, (190, 1216), "--dur:4.4s")
it_planta_der = planta("planta-der", (869, 940, 1056, 1222), 869, 841, (930, 1216), "--dur:5s;--delay:-1.8s")
e.grupo("maceta-izq", (20, 900, 280, 1226), clase="clip")
e.agregar(it_planta_izq, grupo="maceta-izq")
e.grupo("maceta-der", (842, 900, 1100, 1226), clase="clip")
e.agregar(it_planta_der, grupo="maceta-der")
# el marco del teléfono vuelve a quedar encima de las plantas
marco = cv2.dilate(e.oscuro(110).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
marco *= np.clip((235 - e.img[..., :3].max(axis=2)) / (235 - 50), 0, 1)
for nombre, caja in (("marco-izq", (250, 930, 296, 1226)), ("marco-der", (826, 930, 872, 1226))):
    capa = e.img.copy()
    capa[..., :3] = np.median(e.img[e.oscuro(60)][:, :3], axis=0)
    capa[..., 3] = marco * e.rect(caja) * 255
    e.pieza_desde(nombre, capa)

# ---------- encabezado del teléfono ----------
plano((306, 178, 822, 410), PANTALLA)
plano((330, 1116, 790, 1222), PANTALLA)
for caja in (TARJ_TU, TARJ_LUNA):
    plano((caja[0] + 14, caja[1] + 16, caja[2] - 14, caja[3] - 12), TARJETA)
e.pieza("huella-header", e.por_color(e.rect((518, 186, 596, 260))), pivote=(557, 255))
e.pieza("avatar", e.por_color(e.rect((740, 184, 812, 256))), pivote=(776, 220))
for i, y in enumerate((206, 220, 234)):
    e.pieza(f"menu-{i + 1}", e.por_color(e.rect((314, y - 8, 364, y + 8))), pivote=(320, y))

# ---------- "¡Es un match!" letra por letra ----------
cortes = [360, 381, 419, 458, 504, 553, 612, 647, 676, 707, 744, 765]
for i, (x0, x1) in enumerate(zip(cortes, cortes[1:])):
    texto(f"letra-{i + 1}", (x0, 282, x1, 362), pivote=((x0 + x1) / 2, 350))
texto("subtitulo", (340, 362, 740, 402), pivote=(540, 382))
e.pieza("corazon-sub", e.por_color(e.rect((740, 358, 785, 404))), pivote=(761, 392))

# ---------- contenido de las tarjetas (se recorta antes de tomar las tarjetas) ----------
filas_tu = [("casa", (328, 810, 376, 855), (384, 818, 504, 851)),
            ("corazon-tu", (328, 860, 376, 903), (384, 865, 506, 898)),
            ("pesas", (327, 906, 378, 946), (384, 908, 528, 970))]
filas_luna = [("huellas", (609, 812, 655, 856), (662, 818, 744, 853)),
              ("corazon-luna", (609, 860, 655, 902), (662, 865, 766, 898)),
              ("pelota", (609, 905, 655, 950), (662, 908, 790, 971))]
contenido = {}
for lado, titulo, filas in (("tu", (328, 760, 378, 802), filas_tu), ("luna", (609, 760, 696, 802), filas_luna)):
    lista = [texto(f"titulo-{lado}", titulo, diferir=True, pivote=(titulo[0], titulo[3]))]
    for nombre, c_icono, c_texto in filas:
        lista.append(e.pieza(f"icono-{nombre}", e.por_color(e.rect(c_icono)), diferir=True,
                             pivote=((c_icono[0] + c_icono[2]) / 2, c_icono[3] - 4)))
        lista.append(texto(f"texto-{nombre}", c_texto, diferir=True,
                           pivote=(c_texto[0], (c_texto[1] + c_texto[3]) / 2)))
    contenido[lado] = lista
tarjetas = {lado: e.pieza_desde(f"tarjeta-{lado}", e.de_base(e.rect(caja, radio=22)), diferir=True)
            for lado, caja in (("tu", TARJ_TU), ("luna", TARJ_LUNA))}

# ---------- corazón del centro ----------
it_rayos = e.pieza("rayos-corazon", e.por_color(e.rect((514, 438, 606, 490)), fondo=(251, 250, 248)),
                   pivote=(560, 500), diferir=True)
it_corazon = e.pieza("corazon", e.por_color(e.rect((515, 540, 605, 620)) * disco(*CORAZON[:2], CORAZON[2] - 4),
                                             fondo=(255, 255, 255)),
                     pivote=(560, 583), diferir=True)
cx, cy, r = CORAZON
m_disco = disco(cx, cy, r)
it_disco = e.pieza_desde("disco-corazon", e.de_base(m_disco), pivote=(cx, cy), diferir=True)
e.tomado = np.maximum(e.tomado, (m_disco > .5).astype(np.float32))

# ---------- dentro de los círculos ----------
def tono(cond, crecer=2):
    """Máscara (algo crecida) de los píxeles de un color: evita que una pieza se lleve trozos de su vecina."""
    r, g, b = (e.img[..., i] for i in range(3))
    m = cv2.dilate(cond(r, g, b).astype(np.uint8), np.ones((2 * crecer + 1,) * 2, np.uint8)).astype(np.float32)
    return cv2.GaussianBlur(m, (0, 0), .7)


naranja = tono(lambda r, g, b: (r > 215) & (g < 170) & (b < 140) & (r - g > 70))
gris = tono(lambda r, g, b: (np.abs(r - g) < 22) & (np.abs(g - b) < 22) & (r < 200))
it_rayitas_tu = e.pieza("rayitas-tu", e.por_color(e.rect((280, 540, 338, 608))) * naranja, pivote=(340, 590),
                        diferir=True, clases="a-flash", estilo="--dur:1.9s;--delay:-.7s")
it_rayitas_luna = e.pieza("rayitas-luna", e.por_color(e.rect((778, 538, 834, 614))) * naranja, pivote=(776, 590),
                          diferir=True, clases="a-flash", estilo="--dur:1.7s")
it_ondas = e.pieza("ondas-cola", e.por_color(e.rect((804, 646, 842, 694))) * gris, pivote=(806, 692), diferir=True,
                   clases="a-flash", estilo="--dur:.9s")
cola = e.poligono([(770, 653), (790, 650), (806, 658), (820, 670), (830, 688), (832, 706), (824, 714),
                   (806, 714), (796, 706), (790, 692), (781, 676), (771, 664)])
cola *= ~((e.img[..., 0] > 245) & (e.img[..., 1] > 245) & (e.img[..., 2] > 245))
cola *= e.por_color(e.rect((766, 646, 836, 716)), umbral=16)
it_cola = e.pieza("cola", cola, pivote=(814, 712), diferir=True, no_mezclar=e.img[..., :3].min(axis=2) > 232)
oreja = lambda r, g, b: (r < 185) & (g < 118) & (b < 85) & (r > 70)  # noqa: E731
it_oreja_izq = e.pieza("oreja-izq", por_tono((612, 516, 698, 598), oreja), pivote=(684, 532), diferir=True)
it_oreja_der = e.pieza("oreja-der", por_tono((728, 545, 806, 662), oreja), pivote=(750, 560), diferir=True)


# ---------- los círculos ----------
def circulo(nombre, circ, tope, otro, fuente):
    """Disco con aro blanco + todo lo que tiene dentro; lo que tapaba el corazón del centro se redibuja
    y lo que corta la tarjeta se alarga hacia abajo (queda escondido debajo de ella)."""
    ccx, ccy, ri, re = circ
    lente = disco(CORAZON[0], CORAZON[1], CORAZON[2] + 3) * disco(ccx, ccy, re)
    # el aro no es un círculo perfecto: se toma de sobra y, sobre el marco del teléfono, se separa por brillo
    m = disco(ccx, ccy, re + 8) * (1 - disco(otro[0], otro[1], otro[3] + 2) * (1 - lente))
    m *= (xx > 256.5) & (xx < 865.5)
    banda = ((xx > 249) & (xx < 286)) | ((xx > 834) & (xx < 872))
    brillo = e.img[..., :3].max(axis=2)
    a_marco = np.clip((brillo - 45) / (235 - 45), 0, 1)
    m = np.where(banda, m * a_marco, m)
    # lo que sobresale del aro por abajo (pelo, playera, cuerpo) hasta el borde de la tarjeta
    zona = e.rect((max(283, ccx - re), ccy + 60, min(840, ccx + re), tope)) * (1 - disco(otro[0], otro[1], otro[3]))
    m = np.maximum(m, e.por_color(zona, fondo=(251, 250, 248), umbral=18, min_area=40))
    m *= (yy < tope)
    capa = e.de_base(m)
    # sobre el marco: quitar el color oscuro del borde para que no arrastre halo
    marco = np.array([29, 37, 48], np.float32)
    seguro = np.maximum(a_marco, .05)[..., None]
    limpio = np.clip((capa[..., :3] - (1 - seguro) * marco) / seguro, 0, 255)
    capa[..., :3] = np.where(banda[..., None], limpio, capa[..., :3])
    # lo que tapaba el disco del corazón: turquesa + aro blanco
    d = np.hypot(xx - ccx, yy - ccy)
    anillo = (d > ri - 14) & (d < ri - 4) & (lente < .01) & (disco(ccx, ccy, re) > .5)
    r, g = e.base[..., 0], e.base[..., 1]
    teal = np.median(e.base[anillo & (xx > CORAZON[0] - 90) & (xx < CORAZON[0] + 90) & (g > r + 15) & (r > 170)
                            & (np.abs(yy - CORAZON[1]) < 70)][:, :3], axis=0)
    dentro = np.clip(ri - d + .5, 0, 1)[..., None]
    sint = dentro * teal + (1 - dentro) * np.array([254, 254, 254], np.float32)
    capa[..., :3] = capa[..., :3] * (1 - lente[..., None]) + sint * lente[..., None]
    # se alarga bajo la tarjeta repitiendo una fila lisa (sin las rayas de la playera)
    fila = int(tope) - 2
    cols = capa[fila, :, 3] > 128
    for y in range(fila + 1, fila + 48):
        capa[y, cols] = capa[fuente, cols]
    return e.pieza_desde(nombre, capa, pivote=(ccx, ccy), diferir=True)


it_circ_tu = circulo("circulo-tu", CIRC_TU, TARJ_TU[1] + .5, CIRC_LUNA, 727)
it_circ_luna = circulo("circulo-luna", CIRC_LUNA, TARJ_LUNA[1] + .5, CIRC_TU, 739)

# detrás de los círculos: pantalla vacía y marco del teléfono (copiando la fila de arriba, que está limpia)
franja = np.zeros((e.H, e.W, 4), np.float32)
franja[434:750, 250:872, :3] = e.img[428, 250:872, :3]
franja[434:750, 250:872, 3] = 255
franja[..., 3] *= 1 - np.maximum(e.rect(TARJ_TU, radio=22), e.rect(TARJ_LUNA, radio=22)) * (yy > 741)
e.pintar(franja)

# ---------- botón ----------
it_flecha = e.pieza("flecha", e.por_color(e.rect((648, 1042, 698, 1084))), pivote=(655, 1063), diferir=True)
BOTON = (336.5, 1020.5, 785.5, 1103.5)
it_boton = e.pieza_desde("boton", e.de_base(e.rect(BOTON, radio=41.5)), diferir=True)
fondo_boton = np.zeros((e.H, e.W, 4), np.float32)
fondo_boton[..., :3] = e.img[1112, 560, :3]
fondo_boton[..., 3] = e.rect((BOTON[0] - 4, BOTON[1] - 4, BOTON[2] + 4, BOTON[3] + 4), radio=45) * 255
e.pintar(fondo_boton)
texto("juntos", (346, 1122, 774, 1160), pivote=(560, 1141))
for i, caja in enumerate(((512, 1162, 548, 1206), (550, 1167, 572, 1216), (575, 1162, 611, 1206))):
    e.pieza(f"rayita-abajo-{i + 1}", e.por_color(e.rect(caja)), pivote=((caja[0] + caja[2]) / 2, 1160),
            clases="a-flash", estilo=f"--dur:1.8s;--delay:-{i * .25:.2f}s")

# ---------- apilado ----------
e.grupo("tu", (CIRC_TU[0] - 160, CIRC_TU[1] - 160, CIRC_TU[0] + 160, 800), pivote=CIRC_TU[:2])
for it in (it_circ_tu, it_rayitas_tu):
    e.agregar(it, grupo="tu")
e.grupo("luna", (CIRC_LUNA[0] - 160, CIRC_LUNA[1] - 160, CIRC_LUNA[0] + 160, 800), pivote=CIRC_LUNA[:2])
for it in (it_circ_luna, it_cola, it_ondas, it_oreja_izq, it_oreja_der, it_rayitas_luna):
    e.agregar(it, grupo="luna")
for lado in ("tu", "luna"):
    e.agregar(tarjetas[lado])
    for it in contenido[lado]:
        e.agregar(it)
e.html("onda", (CORAZON[0] - 70, CORAZON[1] - 70, CORAZON[0] + 70, CORAZON[1] + 70), "<i></i><i></i>")
e.grupo("corazon", (cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), pivote=(cx, cy))
for it in (it_disco, it_corazon):
    e.agregar(it, grupo="corazon")
e.agregar(it_rayos)
e.html("confeti", (cx - 150, cy - 150, cx + 150, cy + 150), "<i></i>" * 14)
e.grupo("boton", (BOTON[0] - 1.5, BOTON[1] - 1.5, BOTON[2] + 1.5, BOTON[3] + 1.5), radio=43, clase="clip", pivote=((BOTON[0] + BOTON[2]) / 2, (BOTON[1] + BOTON[3]) / 2))
e.agregar(it_boton, grupo="boton")
e.agregar(it_flecha, grupo="boton")
e.html("brillo", BOTON, "<i></i>", grupo="boton")

e.guardar()
