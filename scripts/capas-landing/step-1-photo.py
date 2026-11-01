"""Escena 'step-1-photo' (Cómo funciona · Sube una foto): el celular toma la foto, una línea de escaneo
recorre la pantalla, los puntos clave del perro aparecen uno a uno y se unen con líneas, salen los
acercamientos de cara y cuerpo y al final aparece la palomita.

La imagen original tiene fondo transparente, pero la pantalla del celular es opaca: lo que se recorta
dentro de ella se reconstruye con inpaint (no basta con borrar el alfa). Todo lo del celular va en
piezas, así que la base queda vacía. Las líneas del esqueleto y los conectores lila se redibujan en
SVG para poder "dibujarlos" con stroke-dashoffset.

Este script también escribe app/img/anim/step-1-photo/escena.css: los tiempos de cada punto y cada
línea se calculan según cuándo pasa la línea de escaneo.
"""
import cv2
import numpy as np

from capas import SALIDA, Escena, pct, rellenar

e = Escena("step-1-photo", 600, "Escaneo facial de un perro en el celular")
H, W = e.H, e.W
yy, xx = np.mgrid[:H, :W].astype(np.float32)
ORIG = e.img.copy()
R, G, B, A = (ORIG[..., i] for i in range(4))


CREMA = np.array([253, 244, 230, 255.0])


def tapar(m, radio=6, crecer=3, solo_pantalla=False):
    """Reconstruye (inpaint) en e.img lo que queda debajo de una pieza ya recortada.
    Con solo_pantalla, el bisel oscuro no alimenta el relleno (se toma como crema)."""
    duro = (m > 0.05).astype(np.uint8)
    if crecer:
        duro = cv2.dilate(duro, np.ones((crecer * 2 + 1,) * 2, np.uint8))
    if solo_pantalla:  # el bisel no se toca
        duro &= cv2.erode((pantalla_m > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8))
    rgb = np.clip(e.img[..., :3], 0, 255)
    if solo_pantalla:
        rgb = np.where(pantalla_m[..., None] > 0.5, rgb, CREMA[:3])
    rgb = rgb.astype(np.uint8)
    e.img[..., :3] = np.where(duro[..., None] > 0, cv2.inpaint(rgb, duro, radio, cv2.INPAINT_TELEA), e.img[..., :3])


def disco(cx, cy, r):
    return e.elipse((cx - r, cy - r, cx + r, cy + r))


# ---------- geometría del celular ----------
# esquinas de la pantalla (donde empieza el crema), medidas sobre el original
ESQ_PANTALLA = [(161, 131.5), (677.8, 88.1), (778.4, 1068.9), (263.5, 1126.9)]
pantalla_m = e.cuadrilatero_redondeado(ESQ_PANTALLA, 36)
# bordes externos del marco (para reconstruir la esquina inferior izquierda que tapa la palomita)
N_IZQ = np.array([1, -0.0968]) / np.hypot(1, 0.0968)        # normal hacia adentro del borde izquierdo
N_ABA = np.array([-0.1075, -1]) / np.hypot(1, 0.1075)       # normal hacia adentro del borde inferior
P_IZQ = np.array([84.35, 0.0])                              # punto del borde izquierdo (x = .0968y + 84.35)
P_ABA = np.array([0.0, 1219.65])                            # punto del borde inferior (y = -.1075x + 1219.65)
R_MARCO = 88


def dist_marco():
    """Distancia (hacia adentro) al contorno exterior del celular cerca de la esquina inferior izquierda."""
    dl = (xx - P_IZQ[0]) * N_IZQ[0] + (yy - P_IZQ[1]) * N_IZQ[1]
    db = (xx - P_ABA[0]) * N_ABA[0] + (yy - P_ABA[1]) * N_ABA[1]
    esquina = (dl < R_MARCO) & (db < R_MARCO)
    d = np.minimum(dl, db)
    d_esq = R_MARCO - np.hypot(R_MARCO - np.minimum(dl, R_MARCO), R_MARCO - np.minimum(db, R_MARCO))
    return np.where(esquina, d_esq, d), dl, db


# ---------- puntos clave del celular (detectados por color) ----------
cian = (G - R > 60) & (B - R > 50) & (A > 200)
dist = cv2.distanceTransform(cian.astype(np.uint8), cv2.DIST_L2, 5)
n, lab, st, cen = cv2.connectedComponentsWithStats((dist > 5).astype(np.uint8), 8)
PUNTOS = []
for i in range(1, n):
    x, y, w, h, area = st[i]
    if 6 <= w <= 20 and 6 <= h <= 20 and pantalla_m[int(cen[i][1]), int(cen[i][0])] > 0.5:
        PUNTOS.append((float(cen[i][0]), float(cen[i][1]), float(dist[lab == i].max())))
PUNTOS.sort(key=lambda p: p[1])
CARA = [p for p in PUNTOS if p[1] < 400]
CUERPO = [p for p in PUNTOS if p[1] >= 400]
BARBILLA = (482.0, 463.0)

# líneas del esqueleto: pares de puntos unidos por píxeles cian
puntos_m = np.zeros((H, W), bool)
for cx, cy, r in PUNTOS:
    puntos_m |= np.hypot(xx - cx, yy - cy) < r + 4.5
linea_cian = cian & ~puntos_m & (pantalla_m > 0.5)
linea_cian_d = cv2.dilate(linea_cian.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0


def unidos(a, b):
    (ax, ay), (bx, by) = a[:2], b[:2]
    ra, rb = (a[2] + 5 if len(a) > 2 else 2), (b[2] + 5 if len(b) > 2 else 2)
    largo = np.hypot(bx - ax, by - ay)
    if largo - ra - rb < 3:
        return False
    ts = np.linspace(ra / largo, 1 - rb / largo, 40)
    return np.mean([linea_cian_d[int(round(ay + t * (by - ay))), int(round(ax + t * (bx - ax)))] for t in ts]) > 0.6


def pares(lista, extra=()):
    todos = list(lista) + list(extra)
    out = []
    for i in range(len(todos)):
        for j in range(i + 1, len(todos)):
            if np.hypot(todos[i][0] - todos[j][0], todos[i][1] - todos[j][1]) < 240 and unidos(todos[i], todos[j]):
                out.append((todos[i], todos[j]))
    return out


PARES_CARA = pares(CARA)
PARES_CUERPO = pares(CUERPO, [BARBILLA])
print("puntos:", len(CARA), "cara,", len(CUERPO), "cuerpo; líneas:", len(PARES_CARA), "cara,", len(PARES_CUERPO), "cuerpo")

# ---------- tiempos de la historia (fracción del ciclo) ----------
Y_INI, Y_FIN = 150, 1060          # recorrido de la línea de escaneo (bajada)
T_BAJA = (0.07, 0.36)             # la línea de escaneo baja
T_SUBE = (0.36, 0.47)             # y regresa rápido hacia arriba (repaso)


def t_paso(y):
    return T_BAJA[0] + (y - Y_INI) / (Y_FIN - Y_INI) * (T_BAJA[1] - T_BAJA[0])


def t_repaso(y):
    return T_SUBE[1] - (y - Y_INI) / (Y_FIN - Y_INI) * (T_SUBE[1] - T_SUBE[0])


# ---------- 1) puntos clave: piezas, y se borran del dibujo ----------
e.grupo("telefono", (60, 40, 830, 1215), pivote=(450, 1200))
xs_p = [p[0] for p in ESQ_PANTALLA]
ys_p = [p[1] for p in ESQ_PANTALLA]
CAJA_PANT = (min(xs_p) - 2, min(ys_p) - 2, max(xs_p) + 2, max(ys_p) + 2)
CAJA_PERRO = (170, 140, 760, 1080)
CAJA_CABEZA = (200, 150, 680, 520)

piezas_cara, piezas_cuerpo = [], []
for k, (cx, cy, r) in enumerate(PUNTOS):
    m = disco(cx, cy, r + 3.6)
    nombre = f"punto-{k + 1:02d}"
    it = e.pieza(nombre, m, pivote=(cx, cy), quitar=False, diferir=True)
    it["t"] = t_paso(cy)
    it["t2"] = t_repaso(cy)
    (piezas_cara if cy < 400 else piezas_cuerpo).append(it)
tapar(np.maximum.reduce([disco(cx, cy, r + 4.5) for cx, cy, r in PUNTOS]) + linea_cian_d, radio=5, crecer=2)

# ---------- 2) conectores lila: puntos como piezas; las líneas se redibujan en SVG ----------
lila = (B > R + 5) & (R > G + 30) & (A > 100)
LILA_PUNTOS = [(602, 331, 18.5), (644, 638, 17.5)]
CIRC_CARA = (999.5, 317.4, 214.5)
CIRC_CUERPO = (1002.0, 790.8, 211.0)
ARO_INT = 189.0
lila_pts = []
for k, (cx, cy, r) in enumerate(LILA_PUNTOS):
    it = e.pieza(f"lila-{k + 1}", disco(cx, cy, r), pivote=(cx, cy), quitar=False, diferir=True)
    lila_pts.append(it)
fuera_aros = (np.hypot(xx - CIRC_CARA[0], yy - CIRC_CARA[1]) > CIRC_CARA[2] + 2) & \
             (np.hypot(xx - CIRC_CUERPO[0], yy - CIRC_CUERPO[1]) > CIRC_CUERPO[2] + 2)
lila_linea = cv2.dilate((lila & fuera_aros & (xx < 830)).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
lila_linea &= fuera_aros
# el borde claro de la línea también se va
lila_linea = cv2.dilate(lila_linea.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
lila_linea &= fuera_aros
# el halo tenue de la línea (lila muy claro) también
cerca = cv2.dilate(lila_linea.astype(np.uint8), np.ones((11, 11), np.uint8)) > 0
lila_linea |= cerca & (B > G + 8) & (R > G + 5) & fuera_aros
lila_linea = cv2.dilate(lila_linea.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
lila_linea &= fuera_aros
# dentro de la pantalla la línea se reconstruye con inpaint; sobre el marco (bandas casi verticales) se
# copia el marco de justo arriba de la línea siguiendo la inclinación del borde (x avanza .108 por cada y),
# alfa incluido, así el contorno exterior del celular queda limpio
cerca_marco = xx > 0.1025 * yy + 668.8 - 8      # borde derecho de la pantalla
en_pantalla = (pantalla_m > 0.5) & lila_linea & ~cerca_marco
sobre_marco = lila_linea & cerca_marco
for y, x in zip(*np.nonzero(sobre_marco)):
    for dy in range(1, 30):
        if not sobre_marco[y - dy, x]:
            break
    dy += 1
    xs = x - 0.108 * dy
    x0 = int(np.floor(xs)); f = xs - x0
    e.img[y, x] = ORIG[y - dy, x0] * (1 - f) + ORIG[y - dy, x0 + 1] * f
e.base[..., 3] = np.where(sobre_marco, 0, e.base[..., 3])
tapar(en_pantalla.astype(np.float32), radio=5, crecer=1, solo_pantalla=True)   # después: ya sin lila al lado
tapar(sum(disco(cx, cy, r + 2) for cx, cy, r in LILA_PUNTOS), radio=14, crecer=1, solo_pantalla=True)

# ---------- 3) partes del perro ----------
oreja_color = (e.img[..., 1] < 118) & (e.img[..., 0] < 200)   # ya sin el punto lila
oreja_izq = e.poligono([(300, 222), (335, 228), (352, 260), (348, 300), (338, 350), (336, 400), (350, 445),
                        (356, 480), (330, 505), (280, 505), (225, 480), (205, 420), (210, 330), (240, 260)])
oreja_izq = rellenar((oreja_izq > 0.5) & cv2.dilate(oreja_color.astype(np.uint8), np.ones((7, 7), np.uint8)))
oreja_izq = cv2.GaussianBlur(cv2.morphologyEx(oreja_izq.astype(np.float32), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)), (0, 0), .7)
oreja_der = e.poligono([(548, 205), (600, 210), (640, 245), (660, 300), (662, 380), (650, 440), (615, 448),
                        (595, 420), (585, 370), (575, 320), (565, 280), (555, 245)])
oreja_der = rellenar(((oreja_der > 0.5) & cv2.dilate(oreja_color.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0) |
                     ((oreja_der > 0.5) & (disco(602, 331, 19) > 0.5)))   # donde estaba el punto lila
oreja_der = cv2.GaussianBlur(cv2.morphologyEx(oreja_der.astype(np.float32), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)), (0, 0), .7)
it_oreja_izq = e.pieza("oreja-izq", oreja_izq, pivote=(318, 250), quitar=False, diferir=True, exclusiva=False)
it_oreja_der = e.pieza("oreja-der", oreja_der, pivote=(575, 235), quitar=False, diferir=True, exclusiva=False)
tapar(oreja_izq + oreja_der, radio=9, crecer=3, solo_pantalla=True)

cola = e.poligono([(298, 592), (322, 598), (326, 640), (333, 690), (340, 740), (342, 764), (318, 778), (300, 792),
                   (296, 830), (297, 884), (240, 888), (232, 840), (222, 780), (218, 720), (222, 660), (242, 622),
                   (272, 600)])
# dentro del polígono, solo la cola (contorno incluido) con un margen corto de fondo
cola_sil = rellenar((np.abs(ORIG[..., :3] - CREMA[:3]).max(axis=2) > 10) & (cola > 0.5))
cola = cola * cv2.GaussianBlur(cv2.dilate(cola_sil.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(np.float32), (0, 0), 1)
it_cola = e.pieza("cola", cola, pivote=(312, 830), quitar=False, diferir=True)
tapar(cola, radio=9, crecer=2, solo_pantalla=True)

# cabeza: el borde de abajo se desvanece en el cuello (la base conserva ese tramo original)
cabeza_pol = e.poligono([(300, 160), (480, 150), (650, 170), (628, 300), (618, 420), (600, 445), (540, 468),
                         (482, 482), (420, 470), (360, 452), (318, 420), (300, 300)])
desv = np.clip((492 - yy - (np.abs(xx - 480) * 0.18)) / 26, 0, 1)   # 1 arriba, 0 en el cuello
sil_cabeza = ((np.abs(ORIG[..., :3] - CREMA[:3]).max(axis=2) > 16) & (pantalla_m > 0.5)).astype(np.uint8)
sil_cabeza = cv2.dilate(rellenar(sil_cabeza), np.ones((7, 7), np.uint8)).astype(np.float32)
sil_cabeza = np.clip(sil_cabeza + cv2.dilate((oreja_izq + oreja_der > 0.05).astype(np.uint8), np.ones((9, 9), np.uint8)), 0, 1)
cabeza = cv2.GaussianBlur(sil_cabeza, (0, 0), 1) * cabeza_pol * np.where(yy > 380, desv, 1)
it_cabeza = e.pieza("cabeza", cabeza, pivote=(482, 470), quitar=False, diferir=True, exclusiva=False)
nucleo_cabeza = cabeza_pol * np.clip((desv - 0.9) * 10, 0, 1)   # arriba del tramo del cuello

# cuerpo: todo lo que se separa del crema de la pantalla (sin cola ni orejas; con el tramo del cuello)
dif = np.abs(ORIG[..., :3] - np.array([253, 244, 230.0])).max(axis=2)
silueta = ((dif > 16) & (pantalla_m > 0.5) & (e.rect((175, 150, 760, 1075)) > 0.5) &
           (np.hypot(xx - 211.5, yy - 1065.5) > 132) & ~lila_linea).astype(np.uint8)
n, lab, st, _ = cv2.connectedComponentsWithStats(silueta, 8)
silueta = rellenar(np.isin(lab, [i for i in range(1, n) if st[i, 4] >= 400]))
silueta = cv2.dilate(silueta.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
silueta = cv2.GaussianBlur(silueta, (0, 0), 1.2) * pantalla_m
orejas_d = cv2.dilate(np.clip(oreja_izq + oreja_der, 0, 1), np.ones((9, 9), np.uint8))
# el cuerpo va encima de la cola y de lo de abajo de las orejas: se mete unos px sobre ellas para que no
# quede una costura clara entre dos bordes suaves
orejas_n = cv2.erode(np.clip(oreja_izq + oreja_der, 0, 1), np.ones((7, 7), np.uint8))
cuerpo = silueta * (1 - np.clip(cola + orejas_n, 0, 1)) * (1 - nucleo_cabeza)
borde = cv2.dilate((cuerpo > 0.5).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(np.float32)
cuerpo = np.maximum(cuerpo, cv2.GaussianBlur(borde, (0, 0), 1.2) * silueta * (1 - nucleo_cabeza))
it_cuerpo = e.pieza("cuerpo", cuerpo, pivote=(490, 1012), quitar=False, diferir=True, exclusiva=False)
# lo que queda detrás del perro: pantalla color crema con la sombrita
tapar(np.clip(silueta + cola + orejas_d + cabeza, 0, 1), radio=12, crecer=4, solo_pantalla=True)

# ---------- 4) palomita, rayitas y acercamientos (fuera del celular) ----------
CX_P, CY_P, R_P = 211.5, 1065.5, 127.0
disco_p = disco(CX_P, CY_P, R_P)   # pieza() ya multiplica por el alfa
palomita = e.por_color(disco(CX_P, CY_P, 110), umbral=40, fondo=(253, 120, 84), min_area=200)
palomita = cv2.GaussianBlur(cv2.dilate(palomita.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32),
                            (0, 0), .8)
it_palomita = e.pieza("palomita", palomita, pivote=(240, 1080), quitar=False, diferir=True)
no_naranja = (np.abs(ORIG[..., :3] - np.array([253, 122, 86.0])).max(axis=2) > 22) & (np.hypot(xx - CX_P, yy - CY_P) < 112)
tapar(no_naranja.astype(np.float32), radio=7, crecer=4)
it_disco = e.pieza("disco", disco_p, pivote=(CX_P, CY_P), diferir=True, exclusiva=False)

it_rayita_1 = e.pieza("rayita-1", e.rect((92, 866, 154, 948)), pivote=(160, 960), diferir=True)
it_rayita_2 = e.pieza("rayita-2", e.rect((40, 922, 116, 982)), pivote=(130, 985), diferir=True)


def anillo(c, r0, r1):
    cx, cy, _ = c
    return np.clip(disco(cx, cy, r1) - disco(cx, cy, r0), 0, 1)


aro_cara = anillo(CIRC_CARA, ARO_INT, CIRC_CARA[2] + 1.5)
aro_cuerpo = anillo(CIRC_CUERPO, ARO_INT, CIRC_CUERPO[2] + 1.5)
it_aro_cara = e.pieza("aro-cara", aro_cara, pivote=CIRC_CARA[:2], diferir=True)
it_aro_cuerpo = e.pieza("aro-cuerpo", aro_cuerpo, pivote=CIRC_CUERPO[:2], diferir=True)
it_zoom_cara = e.pieza("zoom-cara", disco(CIRC_CARA[0], CIRC_CARA[1], ARO_INT + 3), pivote=CIRC_CARA[:2],
                       diferir=True, exclusiva=False)
it_zoom_cuerpo = e.pieza("zoom-cuerpo", disco(CIRC_CUERPO[0], CIRC_CUERPO[1], ARO_INT + 3),
                         pivote=CIRC_CUERPO[:2], diferir=True, exclusiva=False)
# el aro de abajo toca el borde derecho del celular: ahí se rehace el borde copiando el de más arriba
borde_der = 0.108 * yy + 707.5                 # borde exterior derecho del celular
d_aro = np.hypot(xx - CIRC_CUERPO[0], yy - CIRC_CUERPO[1])
zona = (d_aro < CIRC_CUERPO[2] + 4) & (xx < borde_der + 3)
for y, x in zip(*np.nonzero(zona)):
    dy = 1
    while zona[y - dy, x - int(round(0.108 * dy))]:
        dy += 1
    dy += 2
    xs = x - 0.108 * dy
    x0 = int(np.floor(xs)); f = xs - x0
    e.img[y, x] = ORIG[y - dy, x0] * (1 - f) + ORIG[y - dy, x0 + 1] * f

# ---------- 5) el celular completo (con la esquina reconstruida) ----------
d, dl, db = dist_marco()
# perfil de colores del marco según la distancia al borde (de los bordes rectos visibles)
muestra = ((yy > 700) & (yy < 860) & (dl < 90) & (dl > -2) & (xx < 300)) | \
          ((xx > 350) & (xx < 700) & (db < 90) & (db > -2) & (yy > 1000))
perfil = np.zeros((400, 4))
cuenta = np.zeros(400)
idx = np.clip(np.round((d + 2) * 4), 0, 399).astype(int)
np.add.at(perfil, idx[muestra], ORIG[muestra])
np.add.at(cuenta, idx[muestra], 1)
perfil = perfil / np.maximum(cuenta, 1)[:, None]
for i in range(400):  # huecos del perfil: copia el vecino
    if cuenta[i] == 0:
        perfil[i] = perfil[i - 1]
CREMA = np.array([253, 244, 230, 255.0])
esquina_zona = disco(CX_P, CY_P, R_P + 6)
dentro_pant = pantalla_m > 0.5
idx_marco = np.where(dentro_pant, idx, np.minimum(idx, int(64 * 4)))   # fuera de la pantalla: bisel oscuro
pint = perfil[idx_marco]
pint[dentro_pant] = CREMA
pint[..., 3] = np.where(d < -1.5, 0, pint[..., 3])
z = esquina_zona[..., None]
e.img = e.img * (1 - z) + pint * z

marco_m = e.poligono([(70, 120), (120, 40), (720, 20), (760, 60), (835, 1100), (790, 1170), (250, 1235),
                      (150, 1220), (110, 1150)])
fuera = ((aro_cara > 0.02) | (aro_cuerpo > 0.02) | (np.hypot(xx - CIRC_CARA[0], yy - CIRC_CARA[1]) < ARO_INT + 4) |
         (np.hypot(xx - CIRC_CUERPO[0], yy - CIRC_CUERPO[1]) < ARO_INT + 4)) & ~zona
telefono = e.img[..., 3] / 255 * marco_m * (1 - fuera) * (1 - e.rect((30, 860, 160, 990)))
it_telefono = e.pieza_desde("telefono", np.concatenate([e.img[..., :3], (telefono * 255)[..., None]], axis=2),
                            pivote=(450, 1200), diferir=True)
e.base[..., 3] = 0   # todo está en piezas: la base solo da el tamaño

# ---------- 6) armado (orden de apilado) ----------
e.agregar(it_telefono, "telefono")
e.grupo("pantalla", CAJA_PANT, padre="telefono",
        estilo="clip-path:polygon(" + ",".join(
            f"{pct(x - CAJA_PANT[0], CAJA_PANT[2] - CAJA_PANT[0])} {pct(y - CAJA_PANT[1], CAJA_PANT[3] - CAJA_PANT[1])}"
            for x, y in [(161 + 30, 131.5 - 3), (677.8 - 30, 88.1 + 3), (677.8 + 3, 88.1 + 30), (778.4 - 3, 1068.9 - 30),
                         (778.4 - 30, 1068.9 + 3), (263.5 + 30, 1126.9 - 3), (263.5 - 3, 1126.9 - 30),
                         (161 + 3, 131.5 + 30)]) + ")")
e.grupo("perro", CAJA_PERRO, padre="pantalla", pivote=(490, 1012))
e.agregar(it_cola, "perro")
e.agregar(it_cuerpo, "perro")


def svg_lineas(pares_, caja, clase):
    x0, y0, x1, y1 = caja
    trazos = []
    for k, (a, b) in enumerate(pares_):
        ra = a[2] + 1 if len(a) > 2 else 0
        rb = b[2] + 1 if len(b) > 2 else 0
        (ax, ay), (bx, by) = a[:2], b[:2]
        largo = np.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / largo, (by - ay) / largo
        p0 = (ax + ux * ra, ay + uy * ra)
        p1 = (bx - ux * rb, by - uy * rb)
        trazos.append(f'<path class="{clase}-{k + 1}" pathLength="1" d="M{p0[0]:.1f} {p0[1]:.1f}L{p1[0]:.1f} {p1[1]:.1f}"/>')
    return (f'<svg viewBox="{x0} {y0} {x1 - x0} {y1 - y0}" preserveAspectRatio="none">' + "".join(trazos) + "</svg>")


e.html("lineas-cuerpo", CAJA_PERRO, svg_lineas(PARES_CUERPO, CAJA_PERRO, "lc"), grupo="perro")
e.grupo("puntos-cuerpo", CAJA_PERRO, padre="perro")
for it in piezas_cuerpo:
    e.agregar(it, "puntos-cuerpo")
e.grupo("cabeza", CAJA_CABEZA, padre="perro", pivote=(482, 470))
e.agregar(it_cabeza, "cabeza")
e.agregar(it_oreja_izq, "cabeza")
e.agregar(it_oreja_der, "cabeza")
e.html("lineas-cara", CAJA_CABEZA, svg_lineas(PARES_CARA, CAJA_CABEZA, "lf"), grupo="cabeza")
e.grupo("puntos-cara", CAJA_CABEZA, padre="cabeza")
for it in piezas_cara:
    e.agregar(it, "puntos-cara")
# efectos de pantalla: flash de la foto, esquinas de enfoque y línea de escaneo
e.html("flash", CAJA_PANT, grupo="pantalla")
e.html("enfoque", (300, 170, 660, 500), "<i></i><i></i><i></i><i></i>", grupo="pantalla")
e.html("escaneo", (CAJA_PANT[0], Y_INI - 60, CAJA_PANT[2], Y_INI + 60), "<i></i>", grupo="pantalla")
# conectores lila (encima del marco; su punta se mete debajo de los aros)
CAJA_CON = (560, 240, 860, 760)
conectores = [((602, 331), (812, 293)), ((644, 638), (826, 726))]
trazos = "".join(f'<path class="cn-{k + 1}" pathLength="1" d="M{a[0]} {a[1]}L{b[0]} {b[1]}"/>'
                 for k, (a, b) in enumerate(conectores))
e.html("conectores", CAJA_CON, f'<svg viewBox="{CAJA_CON[0]} {CAJA_CON[1]} {CAJA_CON[2] - CAJA_CON[0]} '
                                f'{CAJA_CON[3] - CAJA_CON[1]}" preserveAspectRatio="none">{trazos}</svg>',
       grupo="telefono")
for it in lila_pts:
    e.agregar(it, "telefono")

# acercamientos: contenido que hace zoom dentro de un círculo + aro
for nombre, c, it_zoom, it_aro in (("cara", CIRC_CARA, it_zoom_cara, it_aro_cara),
                                   ("cuerpo", CIRC_CUERPO, it_zoom_cuerpo, it_aro_cuerpo)):
    cx, cy, r = c
    e.grupo(f"circ-{nombre}", (cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), pivote=(cx, cy))
    rz = ARO_INT + 1
    e.grupo(f"ventana-{nombre}", (cx - rz, cy - rz, cx + rz, cy + rz), radio=rz, clase="clip",
            padre=f"circ-{nombre}", pivote=(cx, cy))
    e.agregar(it_zoom, f"ventana-{nombre}")
    e.html(f"brillo-{nombre}", (cx - rz, cy - rz, cx + rz, cy + rz), "<i></i>", grupo=f"ventana-{nombre}")
    e.agregar(it_aro, f"circ-{nombre}")

e.grupo("check", (CX_P - R_P - 4, CY_P - R_P - 4, CX_P + R_P + 4, CY_P + R_P + 4), pivote=(CX_P, CY_P))
e.agregar(it_disco, "check")
e.agregar(it_palomita, "check")
e.html("onda-check", (CX_P - R_P, CY_P - R_P, CX_P + R_P, CY_P + R_P), "<i></i><i></i>")
e.agregar(it_rayita_1)
e.agregar(it_rayita_2)

e.guardar()

# ---------- CSS ----------
T = 9.0


def p(v):
    return f"{v * 100:.2f}".rstrip("0").rstrip(".") + "%"


css = [f"""/* Generado por scripts/capas-landing/step-1-photo.py — no editar a mano */
.scene-step-1-photo{{--T:{T}s}}
/* el celular se balancea y hace "clic" al tomar la foto */
.scene-step-1-photo .g-telefono{{animation:s1Tel var(--T) ease-in-out infinite}}
@keyframes s1Tel{{
  0%{{transform:rotate(0)}}
  3%{{transform:scale(.96) rotate(-1deg)}}
  6%{{transform:scale(1.03) rotate(.6deg)}}
  9%{{transform:scale(1) rotate(0)}}
  25%{{transform:rotate(-1.6deg)}}
  45%{{transform:rotate(1.4deg)}}
  64%{{transform:rotate(-1.2deg)}}
  80%{{transform:translateY(-1.5%) rotate(1.6deg)}}
  100%{{transform:rotate(0)}}
}}
/* el perro respira, menea la cola, mueve la cabeza y las orejas */
.scene-step-1-photo .g-perro{{animation:s1Resp 2.2s ease-in-out infinite}}
@keyframes s1Resp{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.012,1.028)}}}}
.scene-step-1-photo .p-cola{{animation:s1Cola .36s ease-in-out infinite alternate}}
@keyframes s1Cola{{0%{{transform:rotate(-11deg)}}100%{{transform:rotate(9deg)}}}}
.scene-step-1-photo .g-cabeza{{animation:s1Cabeza var(--T) ease-in-out infinite}}
@keyframes s1Cabeza{{
  0%,4%{{transform:rotate(0)}}
  10%{{transform:rotate(-4deg) translateY(-1%)}}
  20%{{transform:rotate(-3deg)}}
  30%{{transform:rotate(3.5deg)}}
  40%{{transform:rotate(2deg)}}
  50%{{transform:rotate(-2deg)}}
  62%{{transform:rotate(4deg) translateY(-1%)}}
  70%{{transform:rotate(-5deg) translateY(-1.5%)}}
  76%{{transform:rotate(4deg)}}
  82%{{transform:rotate(-3deg)}}
  88%,100%{{transform:rotate(0)}}
}}
.scene-step-1-photo .p-oreja-izq{{animation:s1OrejaI 1.6s ease-in-out infinite}}
@keyframes s1OrejaI{{0%,40%,100%{{transform:rotate(0)}}10%{{transform:rotate(7deg)}}20%{{transform:rotate(-3deg)}}30%{{transform:rotate(3deg)}}}}
.scene-step-1-photo .p-oreja-der{{animation:s1OrejaD 1.6s -.25s ease-in-out infinite}}
@keyframes s1OrejaD{{0%,40%,100%{{transform:rotate(0)}}10%{{transform:rotate(-6deg)}}20%{{transform:rotate(3deg)}}30%{{transform:rotate(-3deg)}}}}
/* flash de la foto */
.scene-step-1-photo .f-flash{{background:#fff;opacity:0;animation:s1Flash var(--T) infinite}}
@keyframes s1Flash{{0%,2%{{opacity:0}}3.2%{{opacity:.95}}9%,100%{{opacity:0}}}}
/* esquinas de enfoque sobre la cara */
.scene-step-1-photo .f-enfoque{{opacity:0;animation:s1Enfoque var(--T) infinite}}
.scene-step-1-photo .f-enfoque i{{position:absolute;width:18%;height:16%;border:0 solid #fff;filter:drop-shadow(0 0 .3cqw rgba(0,150,140,.8))}}
.scene-step-1-photo .f-enfoque i:nth-child(1){{left:0;top:0;border-width:.9cqw 0 0 .9cqw;border-radius:2cqw 0 0 0}}
.scene-step-1-photo .f-enfoque i:nth-child(2){{right:0;top:0;border-width:.9cqw .9cqw 0 0;border-radius:0 2cqw 0 0}}
.scene-step-1-photo .f-enfoque i:nth-child(3){{left:0;bottom:0;border-width:0 0 .9cqw .9cqw;border-radius:0 0 0 2cqw}}
.scene-step-1-photo .f-enfoque i:nth-child(4){{right:0;bottom:0;border-width:0 .9cqw .9cqw 0;border-radius:0 0 2cqw 0}}
@keyframes s1Enfoque{{
  0%,1%{{opacity:0;transform:scale(1.5) rotate(-6deg)}}
  4%{{opacity:1;transform:scale(.92) rotate(-6deg)}}
  6%{{transform:scale(1.04) rotate(-6deg)}}
  8%{{opacity:1;transform:scale(1) rotate(-6deg)}}
  11%,100%{{opacity:0;transform:scale(1) rotate(-6deg)}}
}}
/* línea de escaneo: baja por toda la pantalla y regresa */
.scene-step-1-photo .f-escaneo{{opacity:0;animation:s1Scan var(--T) infinite}}
.scene-step-1-photo .f-escaneo i{{position:absolute;left:0;right:0;top:42%;height:16%;transform:rotate(-4.8deg);
  background:linear-gradient(180deg,rgba(51,215,200,0),rgba(51,215,200,.45) 40%,#bff8f2 50%,rgba(51,215,200,.45) 60%,rgba(51,215,200,0));
  box-shadow:0 0 3cqw 1cqw rgba(51,215,200,.35)}}
@keyframes s1Scan{{
  0%,{p(T_BAJA[0] - 0.01)}{{opacity:0;transform:translateY(0)}}
  {p(T_BAJA[0])}{{opacity:1;transform:translateY(0)}}
  {p(T_BAJA[1])}{{opacity:1;transform:translateY({(Y_FIN - Y_INI) / 120 * 100:.1f}%)}}
  {p(T_SUBE[1])}{{opacity:1;transform:translateY(0)}}
  {p(T_SUBE[1] + 0.015)},100%{{opacity:0;transform:translateY(0)}}
}}
/* líneas del esqueleto y conectores: se dibujan */
.scene-step-1-photo .f-lineas-cuerpo svg,.scene-step-1-photo .f-lineas-cara svg,.scene-step-1-photo .f-conectores svg{{
  width:100%;height:100%;display:block;overflow:visible;fill:none;stroke-linecap:butt}}
.scene-step-1-photo .f-lineas-cuerpo path,.scene-step-1-photo .f-lineas-cara path{{stroke:#36E4D3;stroke-width:5.4px;
  stroke-dasharray:1 1;stroke-dashoffset:0}}
.scene-step-1-photo .f-conectores path{{stroke:#DDB4FB;stroke-width:12.5px;stroke-dasharray:1 1;stroke-dashoffset:0}}
"""]

FIN = (0.93, 0.975)   # todo se va al final del ciclo


def kf_aparece(nombre, t, t2=None, escala_max=1.7):
    """Pop al pasar la línea de escaneo, latido en el repaso y salida al final."""
    t = max(t, 0.02)
    pasos = [f"0%,{p(t - 0.004)}{{transform:scale(0);opacity:0}}",
             f"{p(t + 0.012)}{{transform:scale({escala_max});opacity:1}}",
             f"{p(t + 0.024)}{{transform:scale(.8)}}",
             f"{p(t + 0.036)}{{transform:scale(1)}}"]
    if t2 is not None and t2 > t + 0.05:
        pasos += [f"{p(t2 - 0.008)}{{transform:scale(1)}}", f"{p(t2)}{{transform:scale(1.45)}}",
                  f"{p(t2 + 0.014)}{{transform:scale(1)}}"]
    pasos += [f"{p(0.6)}{{transform:scale(1)}}", f"{p(0.63)}{{transform:scale(1.3)}}", f"{p(0.66)}{{transform:scale(1)}}",
              f"{p(FIN[0])}{{transform:scale(1);opacity:1}}", f"{p(FIN[1])},100%{{transform:scale(0);opacity:0}}"]
    return f"@keyframes {nombre}{{{''.join(pasos)}}}"


for it in piezas_cara + piezas_cuerpo:
    k = it["nombre"].split("-")[1]
    css.append(f".scene-step-1-photo .p-{it['nombre']}{{animation:s1P{k} var(--T) infinite}}")
    css.append(kf_aparece(f"s1P{k}", it["t"], it["t2"]))


def kf_dibuja(nombre, t, dur=0.03):
    return (f"@keyframes {nombre}{{0%,{p(t - 0.002)}{{stroke-dashoffset:1;opacity:0}}{p(t)}{{stroke-dashoffset:1;opacity:1}}"
            f"{p(t + dur)}{{stroke-dashoffset:0}}"
            f"{p(FIN[0])}{{stroke-dashoffset:0;opacity:1}}{p(FIN[1])},100%{{stroke-dashoffset:0;opacity:0}}}}")


for clase, pares_ in (("lf", PARES_CARA), ("lc", PARES_CUERPO)):
    for k, (a, b) in enumerate(pares_):
        t = max(t_paso(a[1]), t_paso(b[1])) + 0.03
        css.append(f".scene-step-1-photo .{clase}-{k + 1}{{animation:s1{clase.upper()}{k + 1} var(--T) infinite}}")
        css.append(kf_dibuja(f"s1{clase.upper()}{k + 1}", t))

T_LILA = 0.49
for k in range(2):
    t = T_LILA + k * 0.05
    css.append(f".scene-step-1-photo .p-lila-{k + 1}{{animation:s1Lila{k + 1} var(--T) infinite}}")
    css.append(kf_aparece(f"s1Lila{k + 1}", t))
    css.append(f".scene-step-1-photo .cn-{k + 1}{{animation:s1Cn{k + 1} var(--T) infinite}}")
    css.append(kf_dibuja(f"s1Cn{k + 1}", t + 0.02, 0.04))

css.append(f"""/* acercamientos: aparecen, hacen zoom y flotan */
.scene-step-1-photo .g-circ-cara{{animation:s1Circ var(--T) infinite}}
.scene-step-1-photo .g-circ-cuerpo{{animation:s1Circ2 var(--T) infinite}}
@keyframes s1Circ{{
  0%,{p(T_LILA + 0.045)}{{transform:scale(0) rotate(-25deg);opacity:0}}
  {p(T_LILA + 0.075)}{{transform:scale(1.14) rotate(6deg);opacity:1}}
  {p(T_LILA + 0.095)}{{transform:scale(.95) rotate(-2deg)}}
  {p(T_LILA + 0.115)}{{transform:scale(1) rotate(0)}}
  {p(0.72)}{{transform:translateY(-2.5%) rotate(-2deg)}}
  {p(0.82)}{{transform:translateY(1.5%) rotate(1.5deg)}}
  {p(FIN[0])}{{transform:translateY(0) scale(1);opacity:1}}
  {p(FIN[1])},100%{{transform:scale(0);opacity:0}}
}}
@keyframes s1Circ2{{
  0%,{p(T_LILA + 0.095)}{{transform:scale(0) rotate(25deg);opacity:0}}
  {p(T_LILA + 0.125)}{{transform:scale(1.14) rotate(-6deg);opacity:1}}
  {p(T_LILA + 0.145)}{{transform:scale(.95) rotate(2deg)}}
  {p(T_LILA + 0.165)}{{transform:scale(1) rotate(0)}}
  {p(0.76)}{{transform:translateY(2.5%) rotate(2deg)}}
  {p(0.86)}{{transform:translateY(-1.5%) rotate(-1.5deg)}}
  {p(FIN[0])}{{transform:translateY(0) scale(1);opacity:1}}
  {p(FIN[1])},100%{{transform:scale(0);opacity:0}}
}}
.scene-step-1-photo .p-zoom-cara{{animation:s1Zoom var(--T) infinite}}
.scene-step-1-photo .p-zoom-cuerpo{{animation:s1Zoom2 var(--T) infinite}}
@keyframes s1Zoom{{0%,{p(T_LILA + 0.06)}{{transform:scale(1.7)}}{p(T_LILA + 0.16)}{{transform:scale(1)}}100%{{transform:scale(1)}}}}
@keyframes s1Zoom2{{0%,{p(T_LILA + 0.11)}{{transform:scale(1.7)}}{p(T_LILA + 0.21)}{{transform:scale(1)}}100%{{transform:scale(1)}}}}
.scene-step-1-photo .f-brillo-cara,.scene-step-1-photo .f-brillo-cuerpo{{overflow:hidden;border-radius:50%}}
.scene-step-1-photo .f-brillo-cara i,.scene-step-1-photo .f-brillo-cuerpo i{{position:absolute;top:-10%;left:-60%;width:40%;height:120%;
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.7),rgba(255,255,255,0));transform:translateX(0) rotate(20deg);opacity:0;
  animation:s1Brillo var(--T) infinite}}
.scene-step-1-photo .f-brillo-cuerpo i{{animation-name:s1Brillo2}}
@keyframes s1Brillo{{0%,{p(T_LILA + 0.15)}{{transform:translateX(0) rotate(20deg);opacity:0}}{p(T_LILA + 0.16)}{{opacity:1}}{p(T_LILA + 0.22)}{{transform:translateX(420%) rotate(20deg);opacity:1}}{p(T_LILA + 0.23)},100%{{opacity:0;transform:translateX(420%) rotate(20deg)}}}}
@keyframes s1Brillo2{{0%,{p(T_LILA + 0.2)}{{transform:translateX(0) rotate(20deg);opacity:0}}{p(T_LILA + 0.21)}{{opacity:1}}{p(T_LILA + 0.27)}{{transform:translateX(420%) rotate(20deg);opacity:1}}{p(T_LILA + 0.28)},100%{{opacity:0;transform:translateX(420%) rotate(20deg)}}}}
/* palomita: aparece con rebote cuando termina el análisis */
.scene-step-1-photo .g-check{{animation:s1Check var(--T) infinite}}
@keyframes s1Check{{
  0%,70%{{transform:scale(0) rotate(-90deg);opacity:0}}
  70.5%{{opacity:1}}
  74%{{transform:scale(1.3) rotate(10deg)}}
  77%{{transform:scale(.88) rotate(-4deg)}}
  80%{{transform:scale(1.06) rotate(0)}}
  83%{{transform:scale(1)}}
  {p(FIN[0])}{{transform:scale(1);opacity:1}}
  {p(FIN[1])},100%{{transform:scale(0);opacity:0}}
}}
.scene-step-1-photo .p-palomita{{animation:s1Palomita var(--T) infinite}}
@keyframes s1Palomita{{0%,73%{{transform:scale(0) rotate(-30deg)}}77%{{transform:scale(1.35) rotate(8deg)}}80%{{transform:scale(.9)}}83%,86%{{transform:scale(1)}}88%{{transform:scale(1.15) rotate(-6deg)}}90%,100%{{transform:scale(1) rotate(0)}}}}
.scene-step-1-photo .f-onda-check i{{position:absolute;inset:0;border-radius:50%;border:1.1cqw solid #FF7A55;opacity:0;animation:s1Onda var(--T) infinite}}
.scene-step-1-photo .f-onda-check i+i{{animation-delay:.25s;border-color:#FFB199}}
@keyframes s1Onda{{0%,73%{{transform:scale(.9);opacity:0}}74%{{opacity:.9}}85%,100%{{transform:scale(1.8);opacity:0}}}}
.scene-step-1-photo .p-rayita-1,.scene-step-1-photo .p-rayita-2{{animation:s1Rayita var(--T) infinite}}
.scene-step-1-photo .p-rayita-2{{animation-delay:calc(var(--T) * -1 + .12s)}}
@keyframes s1Rayita{{
  0%,73%{{transform:scale(0);opacity:0}}
  75%{{transform:scale(1.35);opacity:1}}
  77%{{transform:scale(1)}}
  81%{{transform:scale(1)}}
  83%{{transform:scale(1.3)}}
  85%,{p(FIN[0])}{{transform:scale(1);opacity:1}}
  {p(FIN[1])},100%{{transform:scale(0);opacity:0}}
}}
""")
(SALIDA / e.nombre / "escena.css").write_text("\n".join(css) + "\n")
