"""Escena 'step-2-alert': el celular lanza la alerta y se propaga por todo el vecindario.

La ilustración tiene fondo transparente y casi todo son figuras sueltas, así que se separa por
componentes conexos del alfa. Donde dos figuras se tocan (chica/beagle, chico/casita, golden/niña) se
parten por color, y cuando una pieza se mueve sobre otra, la de atrás se "extiende" por debajo
(inpainting) para que no aparezcan huecos.
"""
import cv2
import numpy as np

from capas import Escena, rellenar

e = Escena("step-2-alert", 600, "Alerta activada en la app")

# el PNG trae un halo blanco casi invisible (alfa < 12) que inflaría las cajas de las piezas
alfa = e.img[..., 3]
alfa[alfa < 12] = 0
e.base[..., 3] = alfa
A = alfa / 255
R, G, B = (e.img[..., i] for i in range(3))
YY, XX = np.mgrid[0:e.H, 0:e.W]

# ---------- componentes: núcleo opaco + bordes asignados al núcleo más cercano ----------
nucleo = (alfa > 40).astype(np.uint8)
_, etiq = cv2.connectedComponents(nucleo, connectivity=8)
_, idx = cv2.distanceTransformWithLabels(1 - nucleo, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
mapa = np.zeros(idx.max() + 1, np.int32)
mapa[idx[nucleo > 0]] = etiq[nucleo > 0]
ETIQ = np.where(alfa > 0, mapa[idx], 0)


def comp(x, y):
    """Figura (componente) que contiene el punto."""
    return ETIQ == etiq[y, x]


def comps_en(caja):
    """Todas las figuras cuyo centro cae en la caja (para rayitas sueltas)."""
    x0, y0, x1, y1 = caja
    m = np.zeros_like(ETIQ, bool)
    for k in np.unique(ETIQ[y0:y1, x0:x1]):
        if not k:
            continue
        ys, xs = np.nonzero(ETIQ == k)
        if x0 <= xs.mean() < x1 and y0 <= ys.mean() < y1:
            m |= ETIQ == k
    return m


def caja(x0, y0, x1, y1):
    return (XX >= x0) & (XX < x1) & (YY >= y0) & (YY < y1)


def poli(pts):
    return e.poligono(pts) > 0.5


def cc_con(mascara, x, y):
    """Componente conexo de la máscara que contiene (x, y)."""
    _, et = cv2.connectedComponents(mascara.astype(np.uint8), connectivity=8)
    return et == et[y, x]


def piel(m=None):
    p = (R > 195) & (G > 135) & (B < 200) & (R - B > 45) & (G > B + 8)
    return p if m is None else p & m


def extender(capa, relleno, conocido):
    """Rellena `relleno` en la capa con inpainting a partir de los píxeles `conocido` (opacos del padre)."""
    if not relleno.any():
        return
    ys, xs = np.nonzero(relleno)
    x0, y0 = max(0, xs.min() - 40), max(0, ys.min() - 40)
    x1, y1 = min(e.W, xs.max() + 41), min(e.H, ys.max() + 41)
    rgb = np.clip(capa[y0:y1, x0:x1, :3], 0, 255).astype(np.uint8)
    desconocido = (~conocido[y0:y1, x0:x1]).astype(np.uint8)
    lleno = cv2.inpaint(rgb, desconocido, 9, cv2.INPAINT_TELEA).astype(np.float32)
    r = relleno[y0:y1, x0:x1]
    capa[y0:y1, x0:x1, :3][r] = lleno[r]
    capa[y0:y1, x0:x1, 3][r] = 255


def recorte(nombre, region, relleno=None, pivote=None, sin_oscuros=False, fuente=None, **kw):
    """Pieza = alfa original dentro de `region`; con `relleno` se extiende por debajo de lo que la tapa
    (`sin_oscuros`: las sombras oscuras no alimentan el relleno; `fuente`: solo esos píxeles lo alimentan)."""
    region = region & (alfa > 0)
    capa = e.img.copy()
    capa[..., 3] = alfa * region
    if relleno is not None:
        conocido = region & (alfa > 230)
        if sin_oscuros:
            conocido &= np.maximum(np.maximum(R, G), B) > 90
        if fuente is not None:
            conocido &= fuente
        extender(capa, relleno & ~region, conocido)
    e._quitar(region.astype(np.float32))
    return e.pieza_desde(nombre, capa, pivote, **kw)


def caja_de(*mascaras, margen=6):
    m = np.logical_or.reduce(mascaras)
    ys, xs = np.nonzero(m)
    return (max(0, xs.min() - margen), max(0, ys.min() - margen), min(e.W, xs.max() + margen + 1),
            min(e.H, ys.max() + margen + 1))


# ---------- separar figuras que se tocan ----------
# chica / beagle: la cabeza del beagle tapa el borde del suéter lila
duo = comp(300, 350)
lila = (B > G + 5) & (B > 120)
beagle = rellenar(cc_con(duo & ~lila & (YY > 440), 250, 650)).astype(bool) & duo
chica = cc_con(duo & ~beagle, 300, 350) | (duo & ~beagle & (YY < 430))  # sombras azuladas sueltas del pelaje se quedan con el beagle
beagle = duo & ~chica
# chico / casita: el pico del techo toca la sudadera
duo = comp(1000, 300)
sudadera = (R < 130) & (B > R + 30) & (YY < 485)
casa = rellenar(cc_con(duo & ~sudadera & (YY > 440), 1080, 620)).astype(bool) & duo
chico = cc_con(duo & ~casa, 1000, 300) | (duo & ~casa & (YY < 440))
casa = duo & ~chico
# golden / niña: el pelo de la niña tapa la panza del golden
duo = comp(1000, 1150)
pelo = (np.maximum(np.maximum(R, G), B) < 140) & (YY > 890)
golden = rellenar(cc_con(duo & ~pelo & (YY < 1000), 1050, 850)).astype(bool) & duo
nina = cc_con(duo & ~golden, 1000, 1150)
nina = cv2.dilate(nina.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & duo  # borde suavizado del pelo
golden = duo & ~nina

senor = comp(200, 1100)
cachorro = comp(600, 1100)
celular = comp(560, 420)
campana = comp(637, 230)


# ---------- partes que se mueven por su cuenta ----------
def crecer(m, dentro, px=2):
    """Toma el borde suavizado (px) alrededor de una parte, sin salirse de su figura."""
    k = 2 * px + 1
    return cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool) & dentro


oscuro = np.maximum(np.maximum(R, G), B) < 110
huella = rellenar(celular & (R < 150) & (G > R + 40) & poli([(530, 480), (720, 480), (720, 665), (530, 665)]))
huella = crecer(huella.astype(bool), celular, 1)
manos_chica = crecer(rellenar(piel(chica & poli([(330, 284), (372, 278), (392, 296), (410, 330), (425, 385),
                                                 (400, 410), (325, 410), (296, 398), (300, 370), (313, 340),
                                                 (318, 310)]))).astype(bool), chica)
manos_nina = crecer(rellenar(piel(nina & poli([(818, 1098), (868, 1088), (905, 1108), (910, 1200), (860, 1215),
                                               (812, 1205), (806, 1150)]))).astype(bool), nina)
zona = chico & poli([(842, 258), (900, 255), (935, 300), (962, 345), (962, 395), (925, 420), (870, 420), (843, 385)])
gris_cel = (np.ptp(e.img[..., :3], axis=2) < 45) & (YY < 398)
cel_chico = crecer(rellenar((piel(zona) | (gris_cel & zona))).astype(bool), chico)
dedo = crecer(rellenar(piel(chico & poli([(950, 318), (1005, 312), (1075, 345), (1090, 415), (1062, 452),
                                          (1030, 440), (1000, 415), (965, 365)]))).astype(bool), chico)
# cabeza del señor: todo lo que queda arriba del borde inferior de la barba gris, columna por columna
gris = senor & (np.ptp(e.img[..., :3], axis=2) < 45) & (np.maximum(np.maximum(R, G), B) > 70) & (YY < 1070)
fondo_barba = np.where(gris.any(axis=0), e.H - 1 - np.argmax(gris[::-1], axis=0), -1)
cabeza_senor = crecer(rellenar(senor & (YY <= fondo_barba[None, :]) & (YY < 1070)).astype(bool), senor)
pulgar = crecer(rellenar(piel(senor & poli([(335, 985), (412, 985), (415, 1095), (378, 1115), (340, 1105),
                                            (330, 1040)]))).astype(bool), senor & ~cabeza_senor)
cola_beagle = beagle & poli([(15, 630), (105, 630), (97, 680), (88, 700), (78, 722), (72, 745), (69, 768), (70, 800),
                             (15, 800)])
cola_golden = golden & poli([(1118, 800), (1240, 800), (1240, 980), (1168, 980), (1160, 945), (1152, 905),
                             (1140, 878), (1127, 852)])
cola_cachorro = cachorro & poli([(435, 1050), (520, 1050), (510, 1085), (498, 1105), (492, 1130), (490, 1160),
                                 (494, 1190), (435, 1200)])
pata = cachorro & poli([(692, 1020), (780, 1020), (780, 1130), (668, 1130), (676, 1110), (682, 1090), (686, 1060)])
verde = (G > R + 25) & (G > B + 20)


def mayor(m):
    """Solo el componente conexo más grande (quita motitas sueltas)."""
    n, et, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    return et == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA]) if n > 1 else m


arbusto_izq = crecer(mayor(rellenar(casa & verde & caja(905, 590, 1008, 700))), casa, 1)
arbusto_der = crecer(mayor(rellenar(casa & verde & caja(1105, 610, 1245, 700))), casa, 1)
huella_casa = crecer(rellenar(casa & (R < 150) & (G > R + 40) & (B > R + 30) & caja(1020, 505, 1120, 584)).astype(bool), casa)


# ============================================================
#   Armado (de atrás hacia adelante)
# ============================================================
CENTRO = (629, 585)  # centro del celular: de aquí sale la señal

# anillos de radar que barren todo el vecindario (detrás de todo)
e.html("radar", (CENTRO[0] - 560, CENTRO[1] - 560, CENTRO[0] + 560, CENTRO[1] + 560), "<i></i>" * 3)

# ondas del celular: se encienden de adentro hacia afuera (escalan desde el centro del teléfono)
for nombre, semilla in (("onda-izq-lila", (437, 580)), ("onda-der-lila", (794, 640)),
                        ("onda-izq-naranja", (385, 580)), ("onda-der-lila2", (822, 580)),
                        ("onda-der-naranja", (876, 580))):
    recorte(nombre, comp(*semilla), pivote=CENTRO, clases="onda")

# rayitas de énfasis: destellan cuando su personaje recibe la alerta (pivote del lado del personaje)
RAYITAS = {
    "rayitas-chica": ((425, 125, 495, 235), (428, 215)),
    "rayos-campana-izq": ((505, 212, 572, 300), (575, 262)),
    "rayos-campana-der": ((705, 225, 765, 316), (702, 272)),
    "rayitas-beagle": ((48, 548, 116, 618), (118, 600)),
    "rayitas-casa": ((895, 472, 966, 548), (968, 548)),
    "rayitas-golden": ((1165, 762, 1235, 830), (1162, 832)),
    "rayitas-senor": ((330, 916, 398, 986), (328, 990)),
    "rayitas-cachorro": ((463, 990, 530, 1064), (534, 1066)),
    "rayitas-nina": ((770, 966, 840, 1066), (845, 1030)),
}
for nombre, (bbox, pivote) in RAYITAS.items():
    recorte(nombre, comps_en(bbox), pivote=pivote, clases="rayitas")

# campana: se sacude colgada de su argolla
recorte("campana", campana, pivote=(637, 158))

# pines: caen uno por uno y rebotan sobre su punta; una onda marca dónde aterrizan
PINES = {"pin-1": ((803, 230), (803, 303)), "pin-2": ((114, 420), (114, 494)),
         "pin-3": ((403, 840), (403, 911)), "pin-4": ((838, 870), (838, 947))}
for nombre, (semilla, punta) in PINES.items():
    e.html(f"aterriza-{nombre[-1]}", (punta[0] - 45, punta[1] - 14, punta[0] + 45, punta[1] + 14))
    recorte(nombre, comp(*semilla), pivote=punta, clases="pin")

# ---------- celular ----------
e.grupo("celular", caja_de(celular), pivote=CENTRO)
recorte("celular", celular & ~huella, relleno=huella, grupo="celular")
e.html("pantalla-brillo", (488, 352, 772, 802), grupo="celular")
recorte("huella", huella, pivote=(625, 590), grupo="celular")
e.html("aviso", (735, 322, 805, 392), "!", grupo="celular")

# ---------- chica de suéter lila (atrás del beagle) ----------
fondo_sueter = beagle & poli([(200, 440), (470, 440), (460, 462), (420, 470), (350, 476), (280, 476), (235, 470),
                              (205, 458)])
e.grupo("chica", caja_de(chica), pivote=(300, 472))
recorte("chica", chica & ~manos_chica, relleno=manos_chica | fondo_sueter, grupo="chica")
recorte("manos-chica", manos_chica, pivote=(362, 405), grupo="chica")

# ---------- beagle ----------
cuerpo_beagle = beagle & ~cola_beagle
e.grupo("beagle", caja_de(beagle), pivote=(200, 805))
recorte("cola-beagle", cola_beagle, relleno=cuerpo_beagle & poli([(66, 705), (104, 705), (104, 790), (60, 790)]),
        pivote=(82, 748), grupo="beagle")
recorte("beagle", cuerpo_beagle, grupo="beagle")

# ---------- chico de gorra ----------
pico_techo = casa & poli([(1025, 452), (1095, 452), (1080, 478), (1040, 478)])
e.grupo("chico", caja_de(chico), pivote=(1010, 470))
recorte("chico", chico & ~cel_chico & ~dedo, relleno=cel_chico | dedo | pico_techo, sin_oscuros=True, grupo="chico")
recorte("cel-chico", cel_chico, pivote=(885, 405), grupo="chico")
recorte("dedo", dedo, pivote=(1062, 440), grupo="chico")

# ---------- casita del refugio ----------
muros = poli([(971, 555), (1214, 555), (1214, 682), (971, 682)])
arbustos = arbusto_izq | arbusto_der
e.grupo("casa", caja_de(casa), pivote=(1080, 688))
recorte("casa", casa & ~arbustos & ~huella_casa, relleno=(arbustos & muros) | huella_casa, fuente=R > 150, grupo="casa")
recorte("huella-casa", huella_casa, grupo="casa")
recorte("arbusto-izq", arbusto_izq, pivote=(962, 690), grupo="casa")
recorte("arbusto-der", arbusto_der, pivote=(1175, 692), grupo="casa")

# ---------- golden (atrás de la niña) ----------
cuerpo_golden = golden & ~cola_golden
panza = nina & poli([(962, 898), (1110, 898), (1125, 975), (1040, 988), (966, 985), (958, 940)])
e.grupo("golden", caja_de(golden), pivote=(1075, 975))
recorte("cola-golden", cola_golden, relleno=cuerpo_golden & poli([(1108, 845), (1150, 850), (1166, 985),
                                                                    (1125, 985)]),
        pivote=(1158, 948), grupo="golden")
recorte("golden", cuerpo_golden, relleno=panza, grupo="golden")

# ---------- niña de chongo ----------
e.grupo("nina", caja_de(nina), pivote=(960, 1250))
recorte("nina", nina & ~manos_nina, relleno=manos_nina, grupo="nina")
recorte("manos-nina", manos_nina, pivote=(862, 1205), grupo="nina")

# ---------- señor de barba ----------
cuerpo_senor = senor & ~cabeza_senor & ~pulgar
e.grupo("senor", caja_de(senor), pivote=(245, 1236))
recorte("senor", cuerpo_senor, relleno=(cabeza_senor & caja(140, 960, 335, 1070)) | (pulgar & caja(325, 1075, 398, 1125)),
        grupo="senor")
recorte("pulgar", pulgar, pivote=(372, 1100), grupo="senor")
recorte("cabeza-senor", cabeza_senor, pivote=(238, 1035), grupo="senor")

# ---------- cachorro con collar ----------
cuerpo_cachorro = cachorro & ~cola_cachorro & ~pata
e.grupo("cachorro", caja_de(cachorro), pivote=(600, 1210))
recorte("cola-cachorro", cola_cachorro, relleno=cuerpo_cachorro & poli([(486, 1080), (528, 1080), (528, 1200),
                                                                        (486, 1200)]),
        pivote=(497, 1165), grupo="cachorro")
recorte("pata", pata, relleno=cuerpo_cachorro & poli([(650, 1028), (700, 1028), (690, 1125), (645, 1125)]),
        pivote=(684, 1080), grupo="cachorro")
recorte("cachorro", cuerpo_cachorro, grupo="cachorro")

resto = (e.base[..., 3] > 12).sum()
if resto:
    print(f"aviso: quedaron {resto} px opacos en la base")
e.guardar()
