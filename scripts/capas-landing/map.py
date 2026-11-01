"""Escena 'map': mapa de tu zona con pines que caen, tarjetas de perritos que hacen pop y el punto azul que pulsa."""
import cv2
import numpy as np

from capas import Escena, capa_vacia, componer, rellenar

e = Escena("map", 720, "Mapa con perritos cerca de ti")
ORIG = e.img.copy()
CORAZON = ('<svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.6 4.5c2.1 0 3.6 1.2 4.4 2.6.8-1.4 '
           '2.3-2.6 4.4-2.6 3.6 0 5.7 3.9 4.2 7.3C19.5 16.4 12 21 12 21z"/></svg>')


def color(x, y):
    return tuple(ORIG[y, x, :3])


def silueta(pts, fondo, umbral=18):
    """Lo que se separa del fondo liso dentro de un polígono (cabezas, colitas)."""
    zona = e.poligono(pts)
    return zona * e.por_color(zona, umbral=umbral, fondo=fondo, min_area=4)


def por_componentes(caja, asignar, umbral=40, dilatar=2):
    """Separa texto/trazos de una caja en grupos (letras, renglones) según el centro de cada componente."""
    x0, y0, x1, y1 = caja
    rgb = ORIG[y0:y1, x0:x1, :3]
    tinta = ((rgb.max(2) - rgb.min(2) > umbral) | (rgb.max(2) < 200)) & (rgb[..., 1] - rgb[..., 0] < 60)  # sin verdes
    tinta = tinta.astype(np.uint8)
    n, etiquetas, stats, centros = cv2.connectedComponentsWithStats(tinta, 8)
    grupos = {}
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 6:
            continue
        cx, cy = centros[i][0] + x0, centros[i][1] + y0
        k = asignar(cx, cy)
        if k is None:
            continue
        m = grupos.setdefault(k, np.zeros((e.H, e.W), np.uint8))
        m[y0:y1, x0:x1] |= (etiquetas == i).astype(np.uint8)
    nucleo = np.ones((2 * dilatar + 1, 2 * dilatar + 1), np.uint8)
    return {k: cv2.dilate(m, nucleo).astype(np.float32) for k, m in grupos.items()}


# ======================================================================
# 1) Título "Perritos cercanos": cada letra brinca en ola
# ======================================================================
LETRAS = [257, 301, 337, 372, 403, 418, 454, 492, 545, 580, 617, 647, 684, 729, 774, 812, 848]  # bordes izq.
letras = por_componentes((250, 85, 852, 170),
                         lambda cx, cy: next((i for i in range(len(LETRAS) - 1) if LETRAS[i] <= cx < LETRAS[i + 1]),
                                             None))
# se quita todo el título de una vez para que el relleno de una letra no arrastre tinta de la vecina
e._quitar(cv2.dilate(sum(letras.values()), np.ones((5, 5), np.uint8)))
for i in sorted(letras):
    m = letras[i]
    ys, xs = np.nonzero(m)
    piv = ((xs.min() + xs.max()) / 2, ys.max())
    e.pieza(f"letra-{i:02d}", m, pivote=piv, clases="mp-letra", estilo=f"--i:{i}")

e.pieza("corazon-titulo", e.por_color(e.rect((850, 42, 932, 122))), pivote=(890, 118),
        clases="a-pop", estilo="--dur:5.4s;--delay:-.6s")
e.pieza("rayitas-titulo", e.por_color(e.rect((882, 118, 940, 184))), pivote=(880, 150),
        clases="a-flash", estilo="--dur:2.2s;--delay:-.4s")

# ======================================================================
# 2) Decoraciones de los lados
# ======================================================================
e.pieza("rayitas-lila", e.por_color(e.rect((76, 408, 150, 490))), pivote=(150, 490),
        clases="a-flash", estilo="--dur:2.6s;--delay:-1.2s")
e.pieza("rayitas-teal", e.por_color(e.rect((966, 406, 1046, 516))), pivote=(966, 516),
        clases="a-flash", estilo="--dur:2.4s;--delay:-.2s")
e.pieza("rayitas-teal-abajo", e.por_color(e.rect((966, 1060, 1040, 1140))), pivote=(966, 1140),
        clases="a-flash", estilo="--dur:2.8s;--delay:-1.9s")
e.pieza("rayitas-naranja", e.por_color(e.rect((132, 826, 192, 888))), pivote=(130, 888),
        clases="a-flash", estilo="--dur:2.1s;--delay:-.7s")
e.pieza("pin-lila", e.por_color(e.rect((64, 782, 134, 870))), pivote=(99, 864),
        clases="a-hop", estilo="--dur:2.8s;--delay:-.3s;--alto:-22%")
e.pieza("corazon-durazno", e.por_color(e.rect((100, 982, 176, 1060))), pivote=(137, 1056),
        clases="a-pop", estilo="--dur:4.8s;--delay:-2.4s")

# textos manuscritos: cada renglón se balancea por su cuenta
renglones_izq = por_componentes((48, 874, 192, 992),
                                lambda cx, cy: 0 if cy + .22 * (cx - 100) < 910 else (1 if cy + .22 * (cx - 100) < 950 else 2))
e._quitar(cv2.dilate(sum(renglones_izq.values()), np.ones((5, 5), np.uint8)))
for i, m in sorted(renglones_izq.items()):
    ys, xs = np.nonzero(m)
    e.pieza(f"texto-izq-{i}", m, pivote=(xs.min(), ys.max()), clases="mp-renglon", estilo=f"--i:{i}")
renglones_der = por_componentes((910, 798, 1076, 932),
                                lambda cx, cy: 0 if cy + .2 * (cx - 990) < 845 else (1 if cy + .2 * (cx - 990) < 888 else 2))
e._quitar(cv2.dilate(sum(renglones_der.values()), np.ones((5, 5), np.uint8)) * (1 - e.tomado))
for i, m in sorted(renglones_der.items()):
    ys, xs = np.nonzero(m)
    e.pieza(f"texto-der-{i}", m, pivote=(xs.min(), ys.max()), clases="mp-renglon", estilo=f"--i:{i + 3}")
r, g, b = (ORIG[..., i] for i in range(3))
VERDE = ((g - r) > 60).astype(np.float32)
e.pieza("subrayado", cv2.dilate(VERDE * e.rect((950, 910, 1074, 972)), np.ones((5, 5), np.uint8)),
        pivote=(962, 962), clases="mp-subrayado")

# ======================================================================
# 3) Celular: íconos de la cabecera, buscador y barra de navegación
# ======================================================================
e.pieza("menu", e.por_color(e.rect((330, 346, 380, 392))), pivote=(337, 369), clases="mp-menu")
e.pieza("huella-app", e.por_color(e.rect((522, 338, 598, 402))), pivote=(560, 396), clases="a-beat",
        estilo="--dur:1.8s")
e.pieza("avatar", e.por_color(e.rect((728, 337, 792, 400))), pivote=(760, 396), clases="a-wiggle",
        estilo="--dur:3.6s;--delay:-1.2s")
e.pieza("ubicacion", e.por_color(e.rect((358, 422, 400, 471))), pivote=(379, 466), clases="a-hop",
        estilo="--dur:2.2s;--delay:-.8s;--alto:-26%")
e.pieza("filtros", e.por_color(e.rect((730, 424, 779, 471))), pivote=(755, 448), clases="mp-filtros")
e.pieza("nav-casa", e.por_color(e.rect((349, 1187, 407, 1242))), pivote=(378, 1237), clases="a-hop",
        estilo="--dur:3s;--delay:-.2s;--alto:-20%")
e.pieza("nav-lupa", e.por_color(e.rect((472, 1191, 525, 1244))), pivote=(498, 1217), clases="mp-lupa")
e.pieza("nav-corazon", e.por_color(e.rect((591, 1192, 648, 1244))), pivote=(619, 1218), clases="a-beat",
        estilo="--dur:1.5s;--delay:-.4s")
e.html("nav-relleno", (597, 1198, 642, 1238), CORAZON)
e.pieza("nav-huella", e.por_color(e.rect((712, 1192, 770, 1244))), pivote=(741, 1238), clases="a-wiggle",
        estilo="--dur:2.8s;--delay:-1.6s")


# ======================================================================
# Relleno de huecos dentro del mapa: el relleno suave se "posteriza" a los colores
# del mapa (calle, manzana, parque, río) para que no quede una mancha borrosa
# ======================================================================
MAPA = (298, 498, 824, 1168)
EN_MAPA = e.rect(MAPA) > .5
EN_MAPA &= e.elipse((560.5 - 80, 831.5 - 80, 560.5 + 80, 831.5 + 80)) < .5  # el halo azul se rellena normal
ESQ = {"luna": [(161.1, 502.8), (390.3, 483.6), (411.8, 739.4), (182.6, 758.7)],
       "max": [(759.1, 493.1), (955.7, 511.5), (933.8, 745.4), (737.2, 727.0)],
       "toby": [(228.9, 895.3), (434.0, 885.6), (445.7, 1131.5), (240.6, 1141.3)],
       "nala": [(725.5, 917.5), (921.6, 934.9), (900.7, 1169.4), (704.6, 1151.9)]}  # esquinas de las tarjetas
_solo_mapa = EN_MAPA & (cv2.dilate(((r > 190) & (g < 175) & (b < 150)).astype(np.uint8), np.ones((15, 15), np.uint8)) == 0)
for _esq in ESQ.values():
    _solo_mapa &= e.cuadrilatero_redondeado(_esq, 22) < .02
_muestra = ORIG[..., :3][_solo_mapa][::5].astype(np.float32)
_crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, .5)
_, _, PALETA = cv2.kmeans(_muestra, 7, None, _crit, 3, cv2.KMEANS_PP_CENTERS)
_quitar_original = e._quitar


POSTERIZAR = [True]  # se apaga mientras se recorta lo de adentro de las tarjetas


def _quitar_mapa(m, no_mezclar=None):
    _quitar_original(m, no_mezclar)
    if not POSTERIZAR[0]:
        return
    hueco = (cv2.dilate((m > .02).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0) & EN_MAPA
    if no_mezclar is not None:
        hueco &= ~no_mezclar.astype(bool)
    if not hueco.any():
        return
    rgb = e.base[..., :3]
    d = ((rgb[hueco][:, None, :] - PALETA[None]) ** 2).sum(-1)
    plano = rgb.copy()
    plano[hueco] = PALETA[d.argmin(1)]
    suave = cv2.GaussianBlur(plano, (0, 0), .9)
    e.base[..., :3] = np.where(hueco[..., None], suave, rgb)


e._quitar = _quitar_mapa

# ======================================================================
# 4) Elementos del mapa (se recortan antes que las tarjetas para que el relleno no los arrastre)
# ======================================================================
NARANJA = ((r > 190) & (g < 175) & (b < 150)).astype(np.float32)
PINES = [((441, 556, 505, 644), (404, 526, 447, 579), (446, 579)),
         ((656, 682, 718, 765), (701, 638, 744, 690), (701, 690)),
         ((382, 802, 437, 877), (350, 841, 382, 870), (382, 841)),
         ((671, 862, 731, 944), (726, 833, 771, 886), (726, 886))]
mapa_items = []
for i, (caja, caja_r, piv_r) in enumerate(PINES):
    x0, y0, x1, y1 = caja
    pin = rellenar(NARANJA * e.rect((x0 - 3, y0 - 3, x1 + 3, y1 + 3))).astype(np.uint8)
    pin = cv2.dilate(pin, np.ones((7, 7), np.uint8)).astype(np.float32)
    mapa_items.append(e.pieza(f"pin-{i}", pin, pivote=((x0 + x1) / 2, y1 + 2), diferir=True,
                              clases="mp-pin", estilo=f"--i:{i}"))
    mapa_items.append(e.pieza(f"pin-{i}-rayitas", cv2.dilate(NARANJA * e.rect(caja_r), np.ones((5, 5), np.uint8)),
                              pivote=piv_r, diferir=True, clases="mp-pin-rayitas", estilo=f"--i:{i}"))
CELESTE = ((b > 200) & (r < 120) & (g < 170)).astype(np.float32)
LILA = ((b > 190) & (r < 200) & (g < 170) & (b - g > 50)).astype(np.float32)
burbuja = cv2.dilate(rellenar(LILA * e.rect((480, 728, 644, 796))).astype(np.uint8), np.ones((3, 3), np.uint8))
mapa_items.append(e.pieza("burbuja", burbuja.astype(np.float32), pivote=(562, 792), diferir=True,
                          clases="mp-burbuja"))
mapa_items.append(e.pieza("punto", e.elipse((540.5, 811.5, 580.5, 851.5)), pivote=(560.5, 831.5), suave=False,
                          diferir=True, clases="mp-punto"))

# ======================================================================
# 5) Tarjetas de perritos: se separan cabeza, colita, rayitas y corazón;
#    la tarjeta lleva su propia sombra y debajo se limpia (marco y mapa)
# ======================================================================
SOMBRA = np.array((30, 40, 45), np.float32)
MARCO = np.zeros((e.H, e.W), bool)
MARCO[:, 271:300] = True
MARCO[:, 823:852] = True
MARCO &= ORIG[..., :3].max(axis=2) < 120


def sombra_alfa(m):
    """Sombra suave ajustada a la original (medida en los bordes exteriores de Luna y Max)."""
    desplazada = np.roll(np.roll(m, 3, axis=0), 2, axis=1)
    return cv2.GaussianBlur(desplazada, (0, 0), 14) * .135


def sin_sombra(capa, alfa, fuera):
    """Quita la sombra original (modelo: capa = fondo·(1-a) + SOMBRA·a) fuera de la tarjeta."""
    a = (alfa * fuera)[..., None]
    capa[..., :3] = np.clip((capa[..., :3] - SOMBRA * a) / (1 - a), 0, 255)


def marco_de_vuelta(zona):
    """Redibuja el marco recto del teléfono bajo una tarjeta copiando el perfil de una fila limpia."""
    filas = np.nonzero(zona.max(axis=1) > 0)[0]
    for x0, x1 in ((273, 298), (825, 850)):
        franja = zona[:, x0:x1].max(axis=1) > 0
        for y in filas:
            if franja[y]:
                e.base[y, x0:x1, :3] = ORIG[800, x0:x1, :3]


def expandir(esq, d=1.2):
    c = np.mean(esq, axis=0)
    return [tuple(np.array(p) + (np.array(p) - c) / np.linalg.norm(np.array(p) - c) * d) for p in esq]


TARJETAS = {
    "luna": dict(esq=ESQ["luna"], fondo=(252, 243, 233),
                 cabeza=[(200, 548), (215, 523), (250, 512), (290, 510), (328, 513), (356, 528), (372, 556),
                         (366, 588), (350, 598), (332, 602), (322, 617), (300, 624), (272, 622), (248, 614),
                         (238, 603), (222, 606), (204, 592), (196, 568)],
                 piv=(285, 622), cuello=(236, 598, 334, 628), cola=None, rayitas=(186, 598, 220, 642), corazon=(344, 674, 389, 719)),
    "max": dict(esq=ESQ["max"], fondo=(221, 238, 244),
                cabeza=[(788, 575), (798, 548), (826, 524), (850, 518), (878, 535), (912, 553), (925, 585),
                        (910, 610), (888, 622), (860, 630), (832, 640), (822, 652), (802, 650), (790, 625)],
                piv=(848, 640), cuello=(786, 612, 892, 656),
                cola=[(906, 624), (922, 614), (940, 628), (940, 652), (934, 672), (912, 672), (904, 652)],
                piv_cola=(914, 668), rayitas=None, corazon=(883, 678, 923, 717)),
    "toby": dict(esq=ESQ["toby"], fondo=(222, 242, 246),
                 cabeza=[(248, 948), (262, 918), (290, 902), (330, 897), (370, 905), (382, 930), (384, 975),
                         (376, 996), (364, 1026), (340, 1030), (316, 1016), (296, 1008), (282, 996), (262, 972)],
                 piv=(330, 1010), cuello=(278, 984, 386, 1032),
                 cola=[(246, 1000), (262, 996), (280, 1000), (282, 1022), (272, 1044), (246, 1046)],
                 piv_cola=(268, 1040), rayitas=(383, 972, 418, 1020), corazon=(384, 1066, 426, 1108)),
    "nala": dict(esq=ESQ["nala"], fondo=(253, 240, 224),
                 cabeza=[(748, 978), (772, 954), (810, 948), (856, 962), (886, 996), (894, 1030), (878, 1054),
                         (860, 1052), (846, 1042), (818, 1050), (798, 1047), (778, 1036), (762, 1012)],
                 piv=(812, 1042), cuello=(768, 1022, 882, 1058),
                 cola=[(856, 1064), (884, 1056), (894, 1078), (884, 1098), (858, 1098)],
                 piv_cola=(864, 1094), rayitas=None, corazon=(846, 1101, 889, 1144)),
}
ANGULOS = {n: np.degrees(np.arctan2(t["esq"][1][1] - t["esq"][0][1], t["esq"][1][0] - t["esq"][0][0]))
           for n, t in TARJETAS.items()}

tarjetas = {}
for n, t in TARJETAS.items():
    hijos = []
    POSTERIZAR[0] = False
    hijos.append(e.pieza(f"{n}-cabeza", silueta(t["cabeza"], t["fondo"]), pivote=t["piv"], diferir=True,
                         clases="mp-cabeza"))
    # cerca del cuello queda el dibujo original debajo: al girar la cabeza no se ve costura
    x0, y0, x1, y1 = t["cuello"]
    peso = np.zeros((e.H, e.W), np.float32)
    peso[y0:y1, x0:x1] = np.clip((np.arange(y0, y1) - y0) / 12, 0, 1)[:, None]
    e.base[..., :3] = e.base[..., :3] * (1 - peso[..., None]) + ORIG[..., :3] * peso[..., None]
    if t["cola"]:
        hijos.append(e.pieza(f"{n}-cola", silueta(t["cola"], t["fondo"]), pivote=t["piv_cola"], diferir=True,
                             clases="mp-cola"))
    if t["rayitas"]:
        hijos.append(e.pieza(f"{n}-rayitas", cv2.dilate(NARANJA * e.rect(t["rayitas"]), np.ones((9, 9), np.uint8)),
                             pivote=(t["rayitas"][2], (t["rayitas"][1] + t["rayitas"][3]) / 2), diferir=True,
                             clases="a-flash", estilo="--dur:1.4s"))
    hijos.append(e.pieza(f"{n}-corazon", e.por_color(e.rect(t["corazon"]), fondo=(255, 255, 255)), diferir=True,
                         clases="mp-corazon"))
    # tarjeta con sombra propia, tomada de la base ya sin cabeza/cola
    m = e.cuadrilatero_redondeado(expandir(t["esq"]), 22)
    capa = e.base.copy()
    capa[..., :3] = np.where((m < .98)[..., None], 254, capa[..., :3])
    capa[..., 3] = m * 255
    alfa = sombra_alfa(m)
    sombra = capa_vacia(e)
    sombra[..., :3] = SOMBRA
    sombra[..., 3] = alfa * 255
    tarjetas[n] = dict(capa=componer(sombra, capa), hijos=hijos, m=m)
    POSTERIZAR[0] = True
    # debajo: sin sombra, relleno y marco redibujado
    sin_sombra(e.base, alfa, 1 - m)
    sin_sombra(e.img, alfa, 1 - m)
    e.tomado = np.maximum(e.tomado, (m > .5).astype(np.float32))
    e._quitar(m, no_mezclar=MARCO & (m < .02))
    marco_de_vuelta(cv2.dilate((m > .02).astype(np.uint8), np.ones((9, 9), np.uint8)))

# ======================================================================
# 6) Plantas (se extienden por detrás del marco y de las tarjetas) y el marco encima
# ======================================================================
marco_abajo = ((ORIG[..., :3].max(axis=2) < 110) * e.rect((262, 1150, 862, 1315))).astype(np.uint8)
n_, etq, st, _ = cv2.connectedComponentsWithStats(marco_abajo, 8)
marco_abajo = cv2.dilate((etq == 1 + np.argmax(st[1:, 4])).astype(np.uint8), np.ones((3, 3), np.uint8))
oculto_tarjetas = sum(t["m"] for t in tarjetas.values())


def planta(nombre, caja, pivote, estilo):
    m = e.por_color(e.rect(caja), umbral=30) * (1 - marco_abajo)
    m *= 1 - e.tomado
    e.tomado = np.maximum(e.tomado, (m > .5).astype(np.float32))
    e._quitar(m, no_mezclar=marco_abajo.astype(bool))
    fondo = e.base[..., :3]
    dif = np.abs(e.img[..., :3] - fondo).max(axis=2)
    nucleo = cv2.erode((m > .5).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
    a = np.maximum(np.clip((dif - 6) / 64, 0, 1), nucleo) * m
    capa = e.img.copy()
    capa[..., :3] = np.clip(np.where(a[..., None] > .02, fondo + (e.img[..., :3] - fondo) / np.maximum(a, 1e-3)[..., None],
                                     e.img[..., :3]), 0, 255)
    # lo que queda tapado por el marco o por una tarjeta se rellena con la misma planta
    fuera = np.ones((e.H, e.W), np.uint8)
    fuera[:, 271:852] = 0  # nunca encima del marco ni de la pantalla
    oculto = np.maximum(marco_abajo, (oculto_tarjetas > .5) & fuera).astype(np.uint8)
    solido = (a > .9).astype(np.uint8)
    ext = cv2.dilate(solido, np.ones((1, 41), np.uint8)) & cv2.dilate(solido, np.ones((25, 25), np.uint8)) & oculto
    ext &= 1 - solido
    if ext.any():
        conocido = np.clip(capa[..., :3], 0, 255).astype(np.uint8)
        relleno = cv2.inpaint(conocido, (1 - solido) & cv2.dilate(ext, np.ones((5, 5), np.uint8)), 5,
                              cv2.INPAINT_TELEA).astype(np.float32)
        capa[..., :3] = np.where(ext[..., None] > 0, relleno, capa[..., :3])
        a = np.maximum(a, ext)
    capa[..., 3] = a * 255
    e.pieza_desde(nombre, capa, pivote=pivote, clases="a-sway", estilo=estilo)


planta("planta-izq", (86, 1092, 290, 1300), (190, 1290), "--dur:4.2s")
planta("planta-der", (838, 1098, 1056, 1300), (950, 1290), "--dur:4.8s;--delay:-1.7s")
e.pieza("marco", marco_abajo.astype(np.float32), quitar=False, suave=False, exclusiva=False)

# ======================================================================
# 7) Mapa: un grupo recortado a la pantalla que se pasea despacio, con todo lo de encima
# ======================================================================
e.grupo("mapa", MAPA, clase="clip")
e.grupo("mapa-mov", MAPA, padre="mapa")
capa = e.base.copy()
capa[..., 3] = e.rect(MAPA) * 255
e.pieza_desde("mapa", capa, grupo="mapa-mov")
e.html("radar", (480, 751, 641, 912), "<i></i><i></i><i></i>", grupo="mapa-mov")
for it in mapa_items:
    e.agregar(it, grupo="mapa-mov")
HUELLAS = [(568, 862, 160), (577, 885, 165), (590, 907, 140), (614, 902, 105), (638, 895, 105), (660, 899, 140),
           (673, 920, 150), (690, 937, 135)]
HUELLA = ('<svg viewBox="0 0 24 24"><ellipse cx="12" cy="16" rx="6" ry="5"/><circle cx="5" cy="9" r="2.6"/>'
          '<circle cx="9.5" cy="5" r="2.6"/><circle cx="14.5" cy="5" r="2.6"/><circle cx="19" cy="9" r="2.6"/></svg>')
caja_h = (550, 845, 710, 955)
huellas = "".join(
    f'<i style="left:{(x - 10 - caja_h[0]) / (caja_h[2] - caja_h[0]) * 100:.2f}%;'
    f'top:{(y - 10 - caja_h[1]) / (caja_h[3] - caja_h[1]) * 100:.2f}%;--r:{rot}deg;--k:{k}">{HUELLA}</i>'
    for k, (x, y, rot) in enumerate(HUELLAS))
e.html("huellas", caja_h, huellas, grupo="mapa-mov")

# ======================================================================
# 8) Tarjetas encima de todo
# ======================================================================
for k, (n, t) in enumerate(tarjetas.items()):
    a = t["capa"][..., 3]
    ys, xs = np.nonzero(a > 2)
    caja = (xs.min() - 2, ys.min() - 2, xs.max() + 3, ys.max() + 3)
    esq = TARJETAS[n]["esq"]
    piv = ((esq[2][0] + esq[3][0]) / 2, (esq[2][1] + esq[3][1]) / 2)
    # grupo de afuera: flota; grupo de adentro: pop de la historia
    e.grupo(f"t-{n}", caja, pivote=piv, clase="mp-tarjeta", estilo=f"--i:{k};--rot:{ANGULOS[n]:.2f}deg")
    e.grupo(f"t-{n}-pop", caja, pivote=piv, padre=f"t-{n}")
    e.pieza_desde(f"tarjeta-{n}", t["capa"], grupo=f"t-{n}-pop")
    for it in t["hijos"]:
        it["estilo"] = (it["estilo"] + ";" if it["estilo"] else "") + f"--i:{k}"
        e.agregar(it, grupo=f"t-{n}-pop")
    e.html(f"{n}-relleno", TARJETAS[n]["corazon"], CORAZON, grupo=f"t-{n}-pop", clases="mp-relleno",
           estilo=f"--i:{k};--rot:{ANGULOS[n]:.2f}deg")

e.guardar()
