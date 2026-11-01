"""Escena 'compatibility': la app revisa rasgo por rasgo, palomita por palomita, y sale ¡95%!

Los dos perfiles (disco + personaje) salen enteros como piezas para inclinarse sin dejar huecos (un
disco que gira sobre su centro no cambia de silueta); lo que tapaban los corazones del borde se redibuja.
Las palomitas, los íconos de cada fila y los dígitos del porcentaje son piezas sueltas; los dígitos van
dentro de un grupo que recorta para girar como tragamonedas. Las plantas se alargan por detrás del
marco del teléfono, que se repone encima como pieza fija.
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


e = EscenaCapas("compatibility", 1000, "Compatibilidad entre dueño y perro")
yy, xx = np.mgrid[0:e.H, 0:e.W].astype(np.float32)

PANTALLA = (251, 251, 249)
DISCO_TU = (430.5, 580, 112)
DISCO_SU = (692.5, 580, 112)
PILDORA_TU = (368.5, 670, 500.5, 707.5)
PILDORA_SU = (622.5, 670, 754.5, 707.5)
FILAS_Y = (755, 825, 896, 966, 1037)


def disco(cx, cy, r):
    return np.clip(r - np.hypot(xx - cx, yy - cy) + .5, 0, 1)


def plano(caja, color, radio=0, mascara=None):
    """Pinta un color liso en la base: bajo textos sobre fondo liso el relleno queda perfecto."""
    capa = np.zeros((e.H, e.W, 4), np.float32)
    capa[..., :3] = color
    capa[..., 3] = (e.rect(caja, radio) if mascara is None else mascara) * 255
    e.pintar(capa)


def liso(caja, crecer=6, excluir=None):
    """Bajo los textos/íconos de `caja` pinta el color liso del fondo (mediana de lo que no es dibujo):
    así al recortar piezas vecinas no se manchan unas a otras."""
    region = e.rect(caja)
    dibujo = e.por_color(region, min_area=2)
    if excluir is not None:
        dibujo *= 1 - excluir
    zona = cv2.dilate(dibujo.astype(np.uint8), np.ones((2 * crecer + 1,) * 2, np.uint8)).astype(np.float32) * region
    if excluir is not None:
        zona *= 1 - excluir
    color = np.median(e.img[(region > .5) & (zona < .5)][:, :3], axis=0)
    plano(None, color, mascara=cv2.GaussianBlur(zona, (0, 0), 1.2) * region)


def texto(nombre, caja, **kw):
    """Texto o ícono sobre fondo liso (conserva puntos y acentos pequeños)."""
    return e.pieza(nombre, e.por_color(e.rect(caja), min_area=2), **kw)


def tono(cond, crecer=2):
    """Máscara (algo crecida) de los píxeles de un color: evita que una pieza se lleve trozos de su vecina."""
    r, g, b = (e.img[..., i] for i in range(3))
    m = cv2.dilate(cond(r, g, b).astype(np.uint8), np.ones((2 * crecer + 1,) * 2, np.uint8)).astype(np.float32)
    return cv2.GaussianBlur(m, (0, 0), .7)


def por_tono(caja, cond, crecer=1):
    """Píxeles de `caja` que cumplen `cond(r, g, b)` (solo la mancha más grande), con borde suave."""
    r, g, b = (e.img[..., i] for i in range(3))
    m = (cond(r, g, b) & (e.rect(caja) > 0.5)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    m = rellenar(lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA]))
    m = cv2.dilate(m, np.ones((2 * crecer + 1,) * 2, np.uint8)).astype(np.float32)
    return cv2.GaussianBlur(m, (0, 0), .7)


naranja = tono(lambda r, g, b: (r > 215) & (g < 175) & (b < 150) & (r - g > 60))

# ---------- decoraciones exteriores ----------
e.pieza("corazon-titulo", e.por_color(e.rect((838, 32, 928, 126))) * naranja, pivote=(880, 115))
e.pieza("rayitas-cafe", e.por_color(e.rect((892, 100, 950, 170))), pivote=(892, 136),
        clases="a-flash", estilo="--dur:2.2s;--delay:-.5s")
e.pieza("corazon-izq", e.por_color(e.rect((102, 731, 199, 836))), pivote=(150, 826),
        clases="a-pop", estilo="--dur:5.2s;--delay:-2.2s")
e.pieza("rayitas-lila", e.por_color(e.rect((70, 512, 152, 604))), pivote=(150, 600),
        clases="a-flash", estilo="--dur:2.5s;--delay:-1.1s")
e.pieza("rayitas-naranja", e.por_color(e.rect((100, 954, 173, 1042))), pivote=(172, 960),
        clases="a-flash", estilo="--dur:2.1s;--delay:-.2s")
e.pieza("rayitas-teal", e.por_color(e.rect((997, 607, 1070, 687))), pivote=(1000, 684),
        clases="a-flash", estilo="--dur:2.7s;--delay:-1.6s")
e.pieza("rayitas-teal2", e.por_color(e.rect((958, 1076, 1027, 1150))), pivote=(960, 1148),
        clases="a-flash", estilo="--dur:2.3s;--delay:-.9s")

# título de arriba palabra por palabra + subtítulo
liso((250, 100, 856, 186), excluir=e.rect((838, 32, 928, 126)))
liso((328, 186, 792, 262))
for nombre, x0, x1 in (("tu", 252, 336), ("perfil", 348, 518), ("mas", 528, 580), ("su", 590, 668), ("perfil2", 680, 852)):
    texto(f"titulo-{nombre}", (x0, 102, x1, 186), pivote=((x0 + x1) / 2, 146 if nombre == "mas" else 170))
texto("subtitulo", (328, 186, 792, 262), pivote=(560, 224))


# ---------- plantas: dentro de un grupo que recorta en el borde interior del marco ----------
def planta(nombre, caja, borde, hasta, pivote, estilo):
    capa = e.recorte(e.por_color(e.rect(caja), umbral=30), no_mezclar=e.oscuro())
    paso = 1 if hasta > borde else -1
    col = borde - 4 * paso  # columna de la planta junto al marco (sin el contorno oscuro de este)
    filas = capa[:, col, 3] > 128
    for x in range(col + paso, hasta, paso):
        capa[filas, x] = capa[filas, col]
    return e.pieza_desde(nombre, capa, pivote=pivote, clases="a-sway", estilo=estilo, diferir=True)


it_planta_izq = planta("planta-izq", (92, 1012, 276, 1292), 276, 301, (200, 1286), "--dur:4.6s")
it_planta_der = planta("planta-der", (847, 1060, 1030, 1292), 847, 822, (930, 1286), "--dur:5.2s;--delay:-2s")
e.grupo("maceta-izq", (50, 980, 301, 1296), clase="clip")
e.agregar(it_planta_izq, grupo="maceta-izq")
e.grupo("maceta-der", (822, 980, 1080, 1296), clase="clip")
e.agregar(it_planta_der, grupo="maceta-der")
marco = cv2.dilate(e.oscuro(110).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
marco *= np.clip((235 - e.img[..., :3].max(axis=2)) / (235 - 50), 0, 1)
for nombre, caja in (("marco-izq", (272, 1000, 330, 1300)), ("marco-der", (794, 1000, 852, 1300))):
    capa = e.img.copy()
    capa[..., :3] = np.median(e.img[e.oscuro(60)][:, :3], axis=0)
    capa[..., 3] = marco * e.rect(caja) * 255
    e.pieza_desde(nombre, capa)

# ---------- encabezado del teléfono ----------
liso((328, 332, 800, 400))
liso((364, 400, 770, 462))
e.pieza("huella-header", e.por_color(e.rect((526, 332, 594, 394))), pivote=(560, 390))
e.pieza("avatar", e.por_color(e.rect((725, 327, 789, 392))), pivote=(757, 360))
for i, y in enumerate((345, 359, 373)):
    e.pieza(f"menu-{i + 1}", e.por_color(e.rect((334, y - 7, 380, y + 7))), pivote=(339, y))
texto("compatibilidad", (426, 402, 710, 462), pivote=(566, 440))
e.pieza("rayitas-tit-izq", e.por_color(e.rect((368, 402, 414, 455))), pivote=(412, 432),
        clases="a-flash", estilo="--dur:1.9s;--delay:-.3s")
e.pieza("rayitas-tit-der", e.por_color(e.rect((718, 402, 762, 455))), pivote=(720, 432),
        clases="a-flash", estilo="--dur:1.9s;--delay:-1.2s")

# ---------- lista de rasgos ----------
FILA = (254, 254, 253)
filas = []
for i, y in enumerate(FILAS_Y):
    n = i + 1
    liso((430, y - 30, 585, y + 30))
    it_txt = texto(f"rasgo-{n}", (432, y - 28, 585, y + 28), pivote=(440, y), diferir=True)
    it_pal = e.pieza(f"palomita-{n}", e.por_color(e.rect((598, y - 24, 646, y + 24))), pivote=(622, y),
                     diferir=True)
    iconos = []
    for lado, cx in (("a", 380), ("b", 736)):
        it = e.pieza(f"icono-{n}{lado}", e.por_color(e.rect((cx - 25, y - 23, cx + 25, y + 23)) * disco(cx, y, 30)),
                     pivote=(cx, y + 18),
                     diferir=True)
        iconos.append(it)
    filas.append((it_txt, it_pal, iconos))

# ---------- porcentaje ----------
liso((440, 1090, 712, 1154))
it_huella = e.pieza("huella-95", e.por_color(e.rect((446, 1088, 520, 1156))), pivote=(483, 1150), diferir=True)
it_raya95 = e.pieza("raya-95", e.por_color(e.rect((668, 1094, 708, 1148))), pivote=(670, 1140), diferir=True,
                    clases="a-flash", estilo="--dur:1.3s;--delay:-.4s")
digitos = [e.pieza(f"digito-{i + 1}", e.por_color(e.rect((x0, 1092, x1, 1152))), diferir=True)
           for i, (x0, x1) in enumerate(((530, 569), (569, 603), (603, 654)))]
liso((440, 1164, 684, 1204))
it_equipo = texto("equipo", (440, 1164, 684, 1204), pivote=(562, 1184), diferir=True)

# ---------- barra de navegación ----------
nav = []
for i, (x0, x1) in enumerate(((348, 404), (472, 524), (592, 648), (712, 766))):
    nav.append(e.pieza(f"nav-{i + 1}", e.por_color(e.rect((x0, 1228, x1, 1284))), pivote=((x0 + x1) / 2, 1280),
                       diferir=True))

# ---------- perfiles ----------
it_pild_tu = e.pieza("pildora-tu", e.rect(PILDORA_TU, radio=18.7), suave=False, diferir=True,
                     pivote=((PILDORA_TU[0] + PILDORA_TU[2]) / 2, PILDORA_TU[3]))
it_pild_su = e.pieza("pildora-su", e.rect(PILDORA_SU, radio=18.7), suave=False, diferir=True,
                     pivote=((PILDORA_SU[0] + PILDORA_SU[2]) / 2, PILDORA_SU[3]))
durazno = tono(lambda r, g, b: (r > 235) & (g > 120) & (g < 205) & (b < 185) & (r - b > 60))
m_cor_mid = e.por_color(e.rect((534, 562, 591, 614)), fondo=PANTALLA, umbral=40)
m_cor_tu = e.por_color(e.rect((492, 484, 538, 532)), fondo=PANTALLA, umbral=40) * durazno
it_corazon_tu = e.pieza("corazon-tu", m_cor_tu,
                        pivote=(514, 524), diferir=True)
it_corazon_mid = e.pieza("corazon-medio", m_cor_mid,
                         pivote=(562, 600), diferir=True)
it_rayitas_su = e.pieza("rayitas-su", e.por_color(e.rect((756, 522, 808, 602))) * naranja, pivote=(756, 565),
                        diferir=True, clases="a-flash", estilo="--dur:1.7s;--delay:-.6s")
cola = e.poligono([(753, 612), (764, 605), (779, 608), (791, 620), (796, 640), (794, 656), (787, 670), (774, 675),
                   (768, 662), (775, 648), (776, 636), (768, 624), (756, 619)])
cola *= e.por_color(e.rect((748, 600, 800, 680)), umbral=16)
it_cola = e.pieza("cola", cola, pivote=(780, 670), diferir=True, no_mezclar=e.img[..., :3].min(axis=2) > 240)
oreja = lambda r, g, b: (r < 185) & (g < 118) & (b < 85) & (r > 70)  # noqa: E731
it_oreja_izq = e.pieza("oreja-izq", por_tono((618, 496, 694, 560), oreja), pivote=(680, 506), diferir=True)
it_oreja_der = e.pieza("oreja-der", por_tono((716, 526, 764, 614), oreja), pivote=(734, 536), diferir=True)


def perfil(nombre, d, colores_cerca):
    """Disco con su personaje. Lo que tapaban los corazones del borde se redibuja (color del disco adentro,
    pantalla afuera) y lo que sobresale por abajo (playera, cuerpo) se incluye."""
    cx, cy, r = d
    # color del disco junto a los corazones
    anillo = (np.abs(np.hypot(xx - cx, yy - cy) - (r - 8)) < 4)
    color = np.median(e.base[anillo & colores_cerca][:, :3], axis=0)
    dentro = disco(cx, cy, r)[..., None]
    zona = cv2.dilate((np.maximum(m_cor_tu, m_cor_mid) > .05).astype(np.uint8),
                      np.ones((9, 9), np.uint8)).astype(np.float32) * disco(cx, cy, r + 4)
    capa = np.zeros((e.H, e.W, 4), np.float32)
    capa[..., :3] = dentro * color + (1 - dentro) * np.array(PANTALLA, np.float32)
    capa[..., 3] = zona * 255
    e.pintar(capa)
    desborde = e.por_color(e.rect((cx - r, cy + 50, cx + r, 676)), fondo=PANTALLA, umbral=10, min_area=40)
    m = np.maximum(disco(cx, cy, r + .5), desborde * (yy < 676))
    return e.pieza_desde(nombre, e.de_base(m), pivote=(cx, cy), diferir=True)


r_, g_, b_ = (e.img[..., i] for i in range(3))
it_perfil_tu = perfil("perfil-tu", DISCO_TU, (b_ > g_ + 12) & (r_ > 225))
it_perfil_su = perfil("perfil-su", DISCO_SU, (g_ > r_ + 10) & (r_ > 210))
# detrás de los perfiles: pantalla lisa
fondo = np.maximum(disco(DISCO_TU[0], DISCO_TU[1], DISCO_TU[2] + 3), disco(DISCO_SU[0], DISCO_SU[1], DISCO_SU[2] + 3))
fondo = np.maximum(fondo, np.maximum(e.rect((330, 620, 820, 712)), e.rect((530, 470, 594, 640))))
plano(None, PANTALLA, mascara=fondo)

# ---------- apilado ----------
e.grupo("tu", (DISCO_TU[0] - 130, DISCO_TU[1] - 130, DISCO_TU[0] + 130, DISCO_TU[1] + 130), pivote=DISCO_TU[:2])
e.agregar(it_perfil_tu, grupo="tu")
e.grupo("su", (DISCO_SU[0] - 130, DISCO_SU[1] - 130, DISCO_SU[0] + 130, DISCO_SU[1] + 130), pivote=DISCO_SU[:2])
for it in (it_perfil_su, it_cola, it_oreja_izq, it_oreja_der, it_rayitas_su):
    e.agregar(it, grupo="su")
e.agregar(it_corazon_tu)
e.agregar(it_pild_tu)
e.agregar(it_pild_su)
e.html("onda", (502, 530, 622, 650), "<i></i><i></i>")
e.agregar(it_corazon_mid)
e.html("corazones", (440, 470, 680, 640), "<i></i>" * 7)
for it_txt, it_pal, iconos in filas:
    e.agregar(it_txt)
    for it in iconos:
        e.agregar(it)
    e.agregar(it_pal)
e.html("relleno", (352, 1086, 770, 1160), "<i></i>")
e.agregar(it_huella)
e.grupo("cifra", (526, 1090, 658, 1154), clase="clip")
for it in digitos:
    e.agregar(it, grupo="cifra")
e.agregar(it_raya95)
e.html("chispas", (420, 1060, 720, 1190), "<i></i>" * 8)
e.agregar(it_equipo)
for it in nav:
    e.agregar(it)

e.guardar()
