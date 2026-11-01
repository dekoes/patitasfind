"""Escena 'database': la base de datos manda datos a las tarjetas de perritos y hace match.

El cilindro se separa en discos (el de abajo queda fijo en la base y cada disco lleva debajo
una copia de la cara superior, oculta en reposo, para que al levantarse se vea el disco
de abajo). Las tarjetas cuelgan de su nodo lila y se mecen; cada perro mueve la cabeza,
el corazón late y las barras se vuelven a llenar cuando llega un puntito de datos.
"""
import os

import cv2
import numpy as np
from PIL import Image

from capas import SALIDA, Escena, componer

e = Escena("database", 720, "Base de datos propia")
H, W = e.H, e.W
img = e.img
rgb, alfa = img[..., :3], img[..., 3]
r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
lum = rgb.mean(axis=2)
yy, xx = np.mgrid[:H, :W].astype(np.float32)
DEPURA = os.environ.get("DEPURA")
CREMA = np.array([253, 240, 225.5], np.float32)  # fondo de las tarjetas
LILA = np.array([207, 190, 238], np.float32)  # relleno de las barras


def caja_m(x0, y0, x1, y1):
    return ((xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)).astype(np.float32)


def u8(m):
    return (m > .5).astype(np.uint8)


def dilatar(m, n):
    return cv2.dilate(u8(m), np.ones((n, n), np.uint8)).astype(np.float32)


def erosionar(m, n):
    return cv2.erode(u8(m), np.ones((n, n), np.uint8)).astype(np.float32)


def despegar(rgb_fuente, fondo, region, nucleo, t0=6, t1=60):
    """Capa RGBA separada de un fondo opaco conocido; con el alfa mínimo para que la mezcla sea exacta."""
    dif = np.abs(rgb_fuente - fondo).max(axis=2)
    sube = np.where(rgb_fuente > fondo, (rgb_fuente - fondo) / np.maximum(255 - fondo, 1),
                    (fondo - rgb_fuente) / np.maximum(fondo, 1)).max(axis=2)
    a = np.maximum(np.maximum(np.clip((dif - t0) / (t1 - t0), 0, 1), sube), nucleo) * region
    seguro = np.maximum(a, 1e-3)[..., None]
    capa = np.zeros((H, W, 4), np.float32)
    capa[..., :3] = np.clip(np.where(a[..., None] > .02, fondo + (rgb_fuente - fondo) / seguro, rgb_fuente), 0, 255)
    capa[..., 3] = a * 255
    return capa


def transformar(capa, matriz):
    """Transforma una capa RGBA premultiplicada (sin halos oscuros en los bordes)."""
    pre = capa.copy()
    pre[..., :3] *= pre[..., 3:4] / 255
    out = np.clip(cv2.warpAffine(pre, matriz, (W, H), flags=cv2.INTER_CUBIC), 0, None)
    out[..., 3] = np.clip(out[..., 3], 0, 255)
    out[..., :3] = np.clip(out[..., :3] / np.maximum(out[..., 3:4] / 255, 1e-3), 0, 255)
    return out


def con_alfa(rgb_capa, a):
    capa = np.zeros((H, W, 4), np.float32)
    capa[..., :3] = rgb_capa
    capa[..., 3] = np.clip(a, 0, 1) * 255
    return capa


# =====================================================================
# Conectores lila, nodos y separación de las tarjetas
# =====================================================================
es_lila = (b_ > r_ + 5) & (b_ > g_ + 15) & (r_ > 90) & (alfa > 40)
ZONAS_CONECTOR = np.maximum.reduce([caja_m(360, 380, 480, 530), caja_m(775, 380, 890, 530), caja_m(590, 640, 665, 775)])
conector = es_lila * ZONAS_CONECTOR
NODOS = {"izq": (390, 427, 21), "der": (857, 423, 21), "aba": (626, 682, 30)}

sin_lila = u8((alfa > 40) & (conector < .5))
n_c, lab_c, st_c, _ = cv2.connectedComponentsWithStats(cv2.erode(sin_lila, np.ones((3, 3), np.uint8)), 8)


def componente(x, y):
    return dilatar(lab_c == lab_c[y, x], 5) * (alfa > 0) * (conector < .5)


CARTAS = {  # pivote = nodo (o punto de la varilla) del que cuelga cada tarjeta
    "izq": dict(punto=(60, 300), pivote=(390, 427)),
    "der": dict(punto=(1190, 300), pivote=(857, 423)),
    "aba": dict(punto=(480, 1150), pivote=(626, 760)),
}
for nombre, c in CARTAS.items():
    c["m"] = componente(*c["punto"])
cilindro_m = componente(627, 480)

# muesca de cada tarjeta bajo su nodo y junto a su línea: el borde se copia de 150 px más arriba,
# alineando fila por fila el borde exterior; lo que queda bajo el nodo hacia adentro es crema
def borde_medido(y, x_ini, x_fin, paso):
    """x del borde exterior (alfa 50 %) buscando desde el interior de la tarjeta hacia afuera."""
    x = x_ini
    while x != x_fin:
        if alfa[y, x] < 128:
            a0, a1 = alfa[y, x - paso], alfa[y, x]
            return x - paso + paso * (a0 - 128) / max(a0 - a1, 1)
        x += paso
    return None


def borde_oscuro(y, x_ini, x_fin, paso):
    """Donde la línea lila toca el borde no hay alfa que medir: se busca el final del contorno oscuro."""
    x, visto = x_ini, False
    while x != x_fin:
        if es_lila[y, x] and not visto:
            return None
        if lum[y, x] < 100:
            visto = True
        elif visto:
            return x - paso * .5
        x += paso
    return None


FILAS_MUESCA = (396, 537)
for nombre, (x_ini, x_fin, paso) in (("izq", (370, 420, 1)), ("der", (880, 830, -1))):
    c = CARTAS[nombre]
    medido = {y: borde_medido(y, x_ini, x_fin, paso) for y in list(range(240, 392)) + list(range(537, 548))}
    # en las filas tapadas, curva suave (cuadrática) por los bordes medidos arriba/abajo y el contorno visible
    ys_aj, xs_aj = [], []
    for y in range(350, 548):
        if FILAS_MUESCA[0] <= y < FILAS_MUESCA[1]:
            v = borde_oscuro(y, x_ini, x_fin, paso)
        else:
            v = medido.get(y)
        if v is not None:
            ys_aj.append(y)
            xs_aj.append(v)
    ys_aj, xs_aj = np.array(ys_aj, float), np.array(xs_aj, float)
    coef = np.polyfit(ys_aj, xs_aj, 2)
    coef = np.polyfit(ys_aj, xs_aj, 2, w=1 / (1 + np.abs(np.polyval(coef, ys_aj) - xs_aj)))  # sin atípicos
    borde = np.zeros(H, np.float32)
    for y in range(240, 548):
        borde[y] = medido[y] if (medido.get(y) is not None and not (FILAS_MUESCA[0] <= y < FILAS_MUESCA[1])) \
            else np.polyval(coef, y)
    filas = (yy >= FILAS_MUESCA[0]) & (yy < FILAS_MUESCA[1])
    bx = borde[yy.astype(int).clip(0, H - 1)]
    if paso > 0:  # tarjeta izquierda: el borde mira a la derecha
        dentro = xx <= bx + 1.5
        banda = filas & dentro & (xx > bx - 18)
    else:
        dentro = xx >= bx - 1.5
        banda = filas & dentro & (xx < bx + 18)
    nx, ny, nr = NODOS[nombre]
    crema = (np.hypot(xx - nx, yy - ny) < nr + 5) & dentro & ~banda
    fuente_y = np.clip(yy - 150, 0, H - 1)
    corr = bx - borde[fuente_y.astype(int)]  # cuánto se corre el borde entre la fila destino y la fuente
    copia = cv2.remap(img, (xx - corr).astype(np.float32), fuente_y.astype(np.float32), cv2.INTER_LINEAR)
    copia[crema, :3] = CREMA
    copia[crema, 3] = 255
    c["parche"] = (banda | crema).astype(np.float32)
    c["copia"] = copia
    c["m"] = c["m"] * ~(filas & ~dentro)  # nada de la línea ni del nodo por fuera del borde

# =====================================================================
# Tarjetas: cabeza, corazón, barras y rayitas se separan; debajo queda la tarjeta rellena
# =====================================================================
CABEZAS = {
    "izq": dict(pts=[(140, 409), (176, 413), (186, 388), (202, 375), (232, 383), (262, 385), (292, 378), (306, 366),
                     (320, 354), (346, 349), (372, 322), (374, 250), (350, 198), (302, 176), (240, 180), (188, 210),
                     (148, 236), (98, 286), (82, 340), (92, 382), (118, 402)], pivote=(246, 384), corte=345),
    "der": dict(pts=[(932, 374), (952, 384), (1000, 397), (1062, 389), (1100, 375), (1140, 368), (1170, 352),
                     (1178, 300), (1154, 238), (1112, 192), (1050, 176), (980, 182), (928, 198), (896, 228),
                     (876, 252), (872, 302), (882, 348), (902, 372)], pivote=(1005, 396), corte=352),
    "aba": dict(pts=[(556, 958), (580, 982), (610, 993), (642, 988), (680, 973), (702, 966), (736, 963), (768, 952),
                     (778, 900), (772, 838), (742, 806), (690, 790), (630, 786), (568, 792), (518, 812), (486, 840),
                     (476, 882), (494, 906), (530, 910), (548, 924)], pivote=(616, 990), corte=930),
}
CORAZONES = {"izq": (98, 472, 173, 539), "der": (886, 463, 961, 531), "aba": (497, 1061, 571, 1126)}
RAYITAS = {"izq": [(78, 204, 135, 270)], "der": [(1121, 202, 1173, 264)],
           "aba": [(732, 798, 783, 858), (491, 927, 537, 981)]}
BARRAS = {"izq": [(180, 458, 363, 510), (184, 507, 312, 545)], "der": [(968, 472, 1150, 520), (966, 517, 1086, 553)],
          "aba": [(579, 1063, 762, 1103), (579, 1107, 698, 1139)]}

capas_carta = {}
for nombre, c in CARTAS.items():
    m = c["m"]
    tarjeta = img.copy()
    if "parche" in c:
        p = c["parche"][..., None]
        tarjeta = tarjeta * (1 - p) + c["copia"] * p
        m = np.where(c["parche"] > 0, 1, m)
    t_rgb = tarjeta[..., :3].copy()
    piezas = {}
    # corazón y rayitas: sobre crema liso
    cor_m = (((r_ > 200) & (g_ < 175)) * caja_m(*CORAZONES[nombre]))
    cor_m = dilatar(cor_m, 3) * caja_m(*CORAZONES[nombre])
    ray_m = np.zeros((H, W), np.float32)
    for caja in RAYITAS[nombre]:
        ray_m = np.maximum(ray_m, dilatar(((r_ > 200) & (g_ < 175)) * caja_m(*caja), 3) * caja_m(*caja))
    bar_ms = []
    for caja in BARRAS[nombre]:
        bm = dilatar(es_lila * caja_m(*caja), 3) * caja_m(*caja)
        bar_ms.append(bm)
    lisos = np.maximum.reduce([cor_m, ray_m] + bar_ms)
    t_rgb = np.where(dilatar(lisos, 3)[..., None] > 0, CREMA, t_rgb)
    # cabeza: el hueco se rellena por difusión (solo asoma en los bordes al girar)
    cab = CABEZAS[nombre]
    cab_m = e.poligono(cab["pts"])
    hueco = dilatar(cab_m, 5)
    arriba = (hueco > 0) & (yy < cab["corte"])
    t_rgb[arriba] = CREMA
    t_rgb = cv2.inpaint(np.clip(t_rgb, 0, 255).astype(np.uint8), u8(hueco * ~arriba), 15,
                        cv2.INPAINT_NS).astype(np.float32)
    # rastro tenue de cada barra (se ve cuando la barra se vacía)
    for bm in bar_ms:
        suave = cv2.GaussianBlur(erosionar(bm, 3), (0, 0), .8)
        t_rgb = t_rgb * (1 - .28 * suave[..., None]) + LILA * .28 * suave[..., None]
    piezas["cabeza"] = despegar(rgb, t_rgb, dilatar(cab_m, 3), erosionar(cab_m, 5))
    piezas["corazon"] = despegar(rgb, t_rgb, dilatar(cor_m, 3), erosionar(cor_m, 3))
    piezas["rayitas"] = despegar(rgb, t_rgb, dilatar(ray_m, 3), erosionar(ray_m, 3))
    piezas["barras"] = [despegar(rgb, t_rgb, dilatar(bm, 3), erosionar(bm, 3)) for bm in bar_ms]
    a_t = (tarjeta[..., 3] / 255) * m
    piezas["tarjeta"] = con_alfa(t_rgb, a_t)
    capas_carta[nombre] = piezas

# =====================================================================
# Cilindro: tres discos; el de abajo queda en la base
# =====================================================================
CX = 627
# borde inferior de cada costura (contorno oscuro incluido): elipse ajustada a las mediciones
COSTURA1 = [(490, 455), (510, 463), (530, 468), (550, 472), (570, 474), (590, 476), (610, 477), (630, 477),
            (650, 476), (670, 474), (690, 472), (710, 469), (730, 464), (750, 458), (770, 448)]


def ajustar_arco(pts):
    """y = yc + b * sqrt(1 - ((x - CX) / a)^2) con a fijo (radio del cilindro)."""
    a = 167.0
    xs = np.array([p[0] for p in pts], float)
    ys = np.array([p[1] for p in pts], float)
    s = np.sqrt(np.clip(1 - ((xs - CX) / a) ** 2, 0, 1))
    A = np.c_[np.ones_like(s), s]
    yc, b = np.linalg.lstsq(A, ys, rcond=None)[0]
    return yc, b, a


YC1, B_ARCO, A_ARCO = ajustar_arco(COSTURA1)
ESP = 106.0  # distancia entre costuras
ESP_CARA = 111.5  # cuánto hay que bajar la cara superior para que su borde claro coincida con el del disco


def bajo_arco(yc):
    s = np.sqrt(np.clip(1 - ((xx - CX) / A_ARCO) ** 2, 0, 1))
    y_arco = yc + B_ARCO * s
    return np.clip(y_arco + .5 - yy, 0, 1)  # 1 por encima del arco (antialias de 1 px)


sobre1 = bajo_arco(YC1)
sobre2 = bajo_arco(YC1 + ESP)
cil = cilindro_m * (alfa / 255)
disco1_m = cil * sobre1
disco2_m = cil * sobre2 * (1 - sobre1)
# cara superior del disco 1 (contorno de atrás + cara clara + labio), para copiarla bajo los otros discos
cara_m = cil * bajo_arco(YC1 - (ESP_CARA - 2)) * caja_m(440, 250, 815, 420)
cara = img.copy()
cara[..., 3] = 255 * cara_m


def bajar(capa, dy):
    return transformar(capa, np.float32([[1, 0, 0], [0, 1, dy]]))


cara2 = bajar(cara, ESP_CARA)
cara3 = bajar(cara, ESP_CARA + ESP + 1.5)

# brillos ovalados de cada disco: se deslizan para simular que el disco gira
claro = ((r_ > 95) & (g_ > 215) & (alfa > 200)).astype(np.uint8)
OVALOS = []
for (x0, y0, x1, y1) in ((488, 380, 545, 440), (488, 488, 545, 545), (488, 594, 545, 652)):
    om = dilatar(claro * caja_m(x0, y0, x1, y1), 5) * caja_m(x0, y0, x1, y1)
    OVALOS.append(om)

capa_d1 = img.copy()
capa_d1[..., 3] = 255 * disco1_m
capa_d2 = componer(cara2, con_alfa(rgb, disco2_m))
# la base conserva el disco de abajo y su cara (oculta) por encima
disco3_m = cil * (1 - sobre2)


def sin_ovalo(capa, om):
    """Rellena el óvalo con el color de la banda y devuelve (capa sin óvalo, pieza del óvalo)."""
    c_rgb = cv2.inpaint(np.clip(capa[..., :3], 0, 255).astype(np.uint8), u8(dilatar(om, 3)), 7,
                        cv2.INPAINT_TELEA).astype(np.float32)
    pieza = despegar(rgb, c_rgb, dilatar(om, 3), erosionar(om, 3))
    nueva = capa.copy()
    nueva[..., :3] = np.where(dilatar(om, 5)[..., None] > 0, c_rgb, capa[..., :3])
    return nueva, pieza


capa_d1, ovalo1 = sin_ovalo(capa_d1, OVALOS[0])
capa_d2, ovalo2 = sin_ovalo(capa_d2, OVALOS[1])

# =====================================================================
# Base: conectores (prolongados bajo el cilindro), disco de abajo y nodos
# =====================================================================
base = img.copy()
quitar = np.maximum.reduce([CARTAS[n]["m"] for n in CARTAS] + [cilindro_m * sobre2])
base[..., 3] *= 1 - np.clip(quitar, 0, 1)
base[..., 3] = np.where(quitar > .9, 0, base[..., 3])


def prolongar(x_fuente, x_ini, x_fin, y0, y1):
    """Prolonga horizontalmente una línea lila copiando la columna x_fuente."""
    capa = np.zeros((H, W, 4), np.float32)
    col = img[y0:y1, x_fuente]
    for x in range(min(x_ini, x_fin), max(x_ini, x_fin)):
        capa[y0:y1, x] = col
    return capa


ext = componer(prolongar(452, 452, 500, 488, 524), prolongar(800, 760, 801, 488, 524))
base = componer(ext, cara3, base)  # prolongación y cara oculta quedan debajo de lo que ya había
capa_base3, ovalo3 = sin_ovalo(base, OVALOS[2])
base = capa_base3
e.base = base

if DEPURA:
    for n, c in (("base", base), ("d1", capa_d1), ("d2", capa_d2), ("ov1", ovalo1)):
        Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(f"{DEPURA}/{n}.png")
    for nombre, pz in capas_carta.items():
        Image.fromarray(np.clip(pz["tarjeta"], 0, 255).astype(np.uint8)).save(f"{DEPURA}/t-{nombre}.png")
        Image.fromarray(np.clip(pz["cabeza"], 0, 255).astype(np.uint8)).save(f"{DEPURA}/c-{nombre}.png")
    print("arco", YC1, B_ARCO)


# =====================================================================
# Salida
# =====================================================================
def angulo_principal(capa):
    ys, xs = np.nonzero(capa[..., 3] > 128)
    pts = np.c_[xs, ys].astype(np.float64)
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    v = vt[0] if vt[0][0] > 0 else -vt[0]
    return (float(c[0]), float(c[1])), float(np.degrees(np.arctan2(v[1], v[0])))


def caja_alfa(capa, margen=1):
    ys, xs = np.nonzero(capa[..., 3] > 2)
    return (xs.min() - margen, ys.min() - margen, xs.max() + 1 + margen, ys.max() + 1 + margen)


e.pieza_desde("ovalo-3", ovalo3, grupo=None)
CABEZA_PIV = {n: CABEZAS[n]["pivote"] for n in CABEZAS}
RAYITAS_PIV = {"izq": (150, 270), "der": (1110, 270), "aba": None}
for nombre, c in CARTAS.items():
    pz = capas_carta[nombre]
    caja_t = caja_alfa(pz["tarjeta"], 2)
    g = f"carta-{nombre}"
    e.grupo(g, caja_t, pivote=c["pivote"])
    e.pieza_desde(f"tarjeta-{nombre}", pz["tarjeta"], grupo=g)
    for i, barra in enumerate(pz["barras"]):
        centro, ang = angulo_principal(barra)
        recta = transformar(barra, cv2.getRotationMatrix2D(centro, ang, 1.0))
        x0, y0, x1, y1 = caja_alfa(recta, 0)
        gb = f"barra-{nombre}-{i + 1}"
        e.grupo(gb, (x0, y0, x1, y1), radio=(y1 - y0) / 2, clase="clip", padre=g, pivote=centro,
                estilo=f"transform:rotate({ang:.2f}deg)")
        e.pieza_desde(gb, recta, grupo=gb, pivote=(x0, (y0 + y1) / 2))
    cx0, cy0, cx1, cy1 = CORAZONES[nombre]
    e.pieza_desde(f"corazon-{nombre}", pz["corazon"], grupo=g, pivote=((cx0 + cx1) / 2, (cy0 + cy1) / 2 + 4))
    e.html(f"latido-{nombre}", (cx0 - 20, cy0 - 22, cx1 + 20, cy1 + 18), "<i></i>", grupo=g)
    if nombre == "aba":
        for j, caja in enumerate(RAYITAS["aba"]):
            sub = pz["rayitas"] * caja_m(*caja)[..., None]
            piv = (caja[0], caja[3]) if j == 0 else (caja[2], caja[1])
            e.pieza_desde(f"rayitas-aba-{j + 1}", sub, grupo=g, pivote=piv, clases="a-flash",
                          estilo=f"--dur:1.7s;--delay:-{.5 + j * .6:.1f}s")
    else:
        rc = RAYITAS[nombre][0]
        piv = (rc[2], rc[3]) if nombre == "izq" else (rc[0], rc[3])
        e.pieza_desde(f"rayitas-{nombre}", pz["rayitas"], grupo=g, pivote=piv, clases="a-flash",
                      estilo=f"--dur:1.9s;--delay:-{.3 if nombre == 'izq' else 1.1}s")
    e.pieza_desde(f"cabeza-{nombre}", pz["cabeza"], grupo=g, pivote=CABEZA_PIV[nombre])
    e.html(f"chispas-{nombre}", (caja_t[0] - 30, caja_t[1] - 30, caja_t[2] + 30, caja_t[3] + 30), "<b></b>" * 5,
           grupo=g)

# puntitos de datos: nacen bajo el cilindro, recorren la línea y entran al nodo (y de regreso)
RUTAS = {
    "izq": [(476, 506), (462, 506), (440, 506), (423, 503), (413, 492), (409, 472), (407, 452), (398, 434),
            (390, 427)],
    "der": [(778, 507), (790, 507), (808, 507), (826, 503), (836, 491), (840, 471), (842, 451), (850, 433),
            (857, 423)],
    "aba": [(626, 682), (626, 700), (626, 728), (626, 754)],
}
TAM_DATO = 22
for nombre, ruta in RUTAS.items():
    x, y = ruta[0]
    e.html(f"dato-{nombre}", (x - TAM_DATO / 2, y - TAM_DATO / 2, x + TAM_DATO / 2, y + TAM_DATO / 2), "<i></i><i></i>")

e.html("bits", (530, 150, 730, 300), "<i></i>" * 6)  # detrás del cilindro: salen por arriba
# discos del cilindro: cada uno con su brillo (que se desliza como si girara)
e.grupo("disco-2", caja_alfa(capa_d2, 2), pivote=(CX, YC1 + ESP + B_ARCO))
e.pieza_desde("disco-2", capa_d2, grupo="disco-2")
e.pieza_desde("ovalo-2", ovalo2, grupo="disco-2")
e.grupo("disco-1", caja_alfa(capa_d1, 2), pivote=(CX, YC1 + B_ARCO))
e.pieza_desde("disco-1", capa_d1, grupo="disco-1")
e.pieza_desde("ovalo-1", ovalo1, grupo="disco-1")
e.html("senal", (462, 282, 792, 380), "<i></i><i></i><i></i>")  # ondas que suben desde la tapa

# nodos lila encima de todo (la base conserva el original debajo)
for nombre, (nx, ny, nr) in NODOS.items():
    zona = e.elipse((nx - nr - 2, ny - nr - 2, nx + nr + 2, ny + nr + 2))
    e.pieza(f"nodo-{nombre}", zona * np.maximum(dilatar(es_lila, 3), 0) * (alfa / 255), pivote=(nx, ny),
            quitar=False, exclusiva=False)
e.guardar()

if DEPURA:
    fondo = np.zeros_like(img)
    fondo[..., :3] = (243, 239, 232)
    fondo[..., 3] = 255
    capas = [e.base, ovalo3]
    for nombre in CARTAS:
        pz = capas_carta[nombre]
        capas += [pz["tarjeta"]] + pz["barras"] + [pz["corazon"], pz["rayitas"], pz["cabeza"]]
    capas += [capa_d2, ovalo2, capa_d1, ovalo1]
    for nombre, (nx, ny, nr) in NODOS.items():
        zona = e.elipse((nx - nr - 2, ny - nr - 2, nx + nr + 2, ny + nr + 2))
        capas.append(con_alfa(rgb, zona * dilatar(es_lila, 3) * (alfa / 255)))
    reposo = componer(fondo, *capas)
    orig = img.copy()
    orig[..., 3] = np.where(orig[..., 3] > 240, 255, orig[..., 3])
    dif = np.abs(reposo[..., :3] - componer(fondo, orig)[..., :3]).max(axis=2)
    print("dif reposo: media %.2f, p99 %.1f, max %.0f" % (dif.mean(), np.percentile(dif, 99), dif.max()))
    Image.fromarray(np.clip(dif * 4, 0, 255).astype(np.uint8)).save(f"{DEPURA}/dif.png")
    Image.fromarray(np.clip(reposo, 0, 255).astype(np.uint8)).save(f"{DEPURA}/reposo.png")

# =====================================================================
# CSS (los recorridos de los puntitos se calculan aquí a partir de RUTAS)
# =====================================================================
T = 9  # segundos del ciclo
CW = W / 100


def num(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) > 5e-4 else "0"


def recorrido(ruta, ini, fin):
    """Fotogramas (porcentaje, dx, dy) a velocidad constante a lo largo de la ruta, de ini% a fin%."""
    segs = [np.hypot(ruta[i + 1][0] - ruta[i][0], ruta[i + 1][1] - ruta[i][1]) for i in range(len(ruta) - 1)]
    total = sum(segs)
    out, acum = [], 0
    for i, p in enumerate(ruta):
        if i:
            acum += segs[i - 1]
        out.append((ini + (fin - ini) * acum / total, (p[0] - ruta[0][0]) / CW, (p[1] - ruta[0][1]) / CW))
    return out


# salida (base -> tarjeta) y regreso (tarjeta -> base) de cada puntito
VIAJES = {"izq": (5, 14.5), "der": (29, 38.5), "aba": (53, 59)}
REGRESO = (71, 79)
kf_datos = []
for nombre, ruta in RUTAS.items():
    ida = recorrido(ruta, *VIAJES[nombre])
    vuelta = recorrido(ruta[::-1], *REGRESO)
    fin_x, fin_y = ida[-1][1], ida[-1][2]
    lineas = [f"  0%,{num(ida[0][0] - .01)}%{{transform:translate(0,0) scale(.3);opacity:0}}"]
    for k, (pc, dx, dy) in enumerate(ida):
        op = 0 if k == 0 or k == len(ida) - 1 else 1
        esc = 1.25 if 0 < k < len(ida) - 1 else .5
        lineas.append(f"  {num(pc)}%{{transform:translate({num(dx)}cqw,{num(dy)}cqw) scale({esc});opacity:{op}}}")
    lineas.append(f"  {num(vuelta[0][0] - .01)}%{{transform:translate({num(fin_x)}cqw,{num(fin_y)}cqw) scale(.3);opacity:0}}")
    for k, (pc, dx, dy) in enumerate(vuelta):
        op = 0 if k == 0 or k == len(vuelta) - 1 else 1
        esc = 1.25 if 0 < k < len(vuelta) - 1 else .5
        lineas.append(f"  {num(pc)}%{{transform:translate({num(fin_x + dx)}cqw,{num(fin_y + dy)}cqw) "
                      f"scale({esc});opacity:{op}}}")
    lineas.append(f"  {num(REGRESO[1] + .01)}%,100%{{transform:translate(0,0) scale(.3);opacity:0}}")
    kf_datos.append(f".scene-database .f-dato-{nombre} i{{animation-name:dbDato{nombre.capitalize()}}}\n"
                    f"@keyframes dbDato{nombre.capitalize()}{{\n" + "\n".join(lineas) + "\n}")

# momento del "match" de cada tarjeta (cuando llega su puntito)
MATCH = {n: VIAJES[n][1] for n in VIAJES}


def tarjeta_kf(nombre, m, signo):
    """Vaivén suave colgando del nodo + sacudida al hacer match + brinco en la fiesta final."""
    s = signo
    return f"""@keyframes dbCarta{nombre.capitalize()}{{
  0%,100%{{transform:rotate({num(1.2 * s)}deg)}}
  {num(m - 6)}%{{transform:rotate({num(-1.2 * s)}deg)}}
  {num(m)}%{{transform:rotate(0deg)}}
  {num(m + 1.5)}%{{transform:rotate({num(-5 * s)}deg) scale(1.03)}}
  {num(m + 3.5)}%{{transform:rotate({num(3.5 * s)}deg) scale(1)}}
  {num(m + 5.5)}%{{transform:rotate({num(-2 * s)}deg)}}
  {num(m + 7.5)}%{{transform:rotate({num(1 * s)}deg)}}
  {num(m + 10)}%{{transform:rotate({num(-.6 * s)}deg)}}
  80%{{transform:rotate({num(1.4 * s)}deg)}}
  83%{{transform:translateY(-2.5%) rotate({num(-3 * s)}deg)}}
  86%{{transform:translateY(0) rotate({num(2.4 * s)}deg) scale(1.02,.98)}}
  89%{{transform:translateY(-1.2%) rotate({num(-1.2 * s)}deg)}}
  92%{{transform:rotate({num(1.2 * s)}deg)}}
}}"""


def cabeza_kf(nombre, m):
    return f"""@keyframes dbCabeza{nombre.capitalize()}{{
  0%,100%{{transform:rotate(0)}}
  {num(m - 9)}%{{transform:rotate(-3deg)}}
  {num(m - 3)}%{{transform:rotate(2.5deg)}}
  {num(m)}%{{transform:rotate(0)}}
  {num(m + 1.5)}%{{transform:rotate(5.5deg) translateY(-1.5%)}}
  {num(m + 3)}%{{transform:rotate(-5deg) translateY(-1.5%)}}
  {num(m + 4.5)}%{{transform:rotate(4deg)}}
  {num(m + 6)}%{{transform:rotate(-3deg)}}
  {num(m + 8)}%{{transform:rotate(1.5deg)}}
  {num(m + 18)}%{{transform:rotate(-2.5deg)}}
  {num(min(m + 28, 78))}%{{transform:rotate(2.5deg)}}
  82%{{transform:rotate(0)}}
  84%{{transform:rotate(5deg) translateY(-2%)}}
  86%{{transform:rotate(-5deg) translateY(-2%)}}
  88%{{transform:rotate(3.5deg)}}
  90%{{transform:rotate(-2deg)}}
  93%{{transform:rotate(0)}}
}}"""


def corazon_kf(nombre, m):
    return f"""@keyframes dbCorazon{nombre.capitalize()}{{
  0%,{num(m)}%,{num(m + 8)}%,80%,92%,100%{{transform:scale(1)}}
  {num(m + 1.2)}%{{transform:scale(1.45) rotate(-8deg)}}
  {num(m + 2.6)}%{{transform:scale(.9)}}
  {num(m + 4)}%{{transform:scale(1.25) rotate(5deg)}}
  {num(m + 5.6)}%{{transform:scale(.97)}}
  82%,86%{{transform:scale(1.3)}}84%,88%{{transform:scale(.95)}}
}}
@keyframes dbLatido{nombre.capitalize()}{{
  0%,{num(m + .8)}%{{transform:scale(.4);opacity:0}}
  {num(m + 1.6)}%{{opacity:1}}
  {num(m + 7)}%,100%{{transform:scale(1.5);opacity:0}}
}}
@keyframes dbBarra{nombre.capitalize()}1{{
  0%,{num(m + .3)}%{{transform:translateX(0)}}
  {num(m + 1.3)}%{{transform:translateX(-101%)}}
  {num(m + 6)}%,100%{{transform:translateX(0)}}
}}
@keyframes dbBarra{nombre.capitalize()}2{{
  0%,{num(m + .3)}%{{transform:translateX(0)}}
  {num(m + 1.3)}%,{num(m + 3)}%{{transform:translateX(-101%)}}
  {num(m + 8)}%,100%{{transform:translateX(0)}}
}}
@keyframes dbChispas{nombre.capitalize()}{{
  0%,{num(m + .5)}%{{transform:scale(0) rotate(0);opacity:0}}
  {num(m + 2.5)}%{{transform:scale(1.2) rotate(50deg);opacity:1}}
  {num(m + 7)}%,100%{{transform:scale(.3) rotate(110deg);opacity:0}}
}}
@keyframes dbNodo{nombre.capitalize()}{{
  0%,{num(VIAJES[nombre][0] - 1)}%,{num(VIAJES[nombre][0] + 2)}%,{num(m - .8)}%,{num(m + 5)}%,{num(REGRESO[0] - .5)}%,{num(REGRESO[0] + 3)}%,100%{{transform:scale(1)}}
  {num(VIAJES[nombre][0] + .5)}%,{num(REGRESO[0] + 1)}%{{transform:scale(1.25)}}
  {num(m + .4)}%{{transform:scale(1.5)}}
  {num(m + 2)}%{{transform:scale(.92)}}
  {num(m + 3.4)}%{{transform:scale(1.12)}}
}}"""


def estrellas(nombre):
    out = []
    pos = [(8, 18), (82, 6), (90, 52), (4, 64), (70, 88)]
    for i, (lx, ty) in enumerate(pos):
        out.append(f".scene-database .f-chispas-{nombre} b:nth-child({i + 1}){{left:{lx}%;top:{ty}%;"
                   f"animation-delay:{i * .05:.2f}s}}")
    return "\n".join(out)


SIGNO = {"izq": 1, "der": -1, "aba": 1}
bloques = []
for n in CARTAS:
    N = n.capitalize()
    m = MATCH[n]
    bloques.append(f""".scene-database .g-carta-{n}{{animation:dbCarta{N} var(--T) ease-in-out infinite}}
.scene-database .p-cabeza-{n}{{animation:dbCabeza{N} var(--T) ease-in-out infinite}}
.scene-database .p-corazon-{n}{{animation:dbCorazon{N} var(--T) infinite}}
.scene-database .f-latido-{n} i{{animation-name:dbLatido{N}}}
.scene-database .g-barra-{n}-1>.pt{{animation:dbBarra{N}1 var(--T) cubic-bezier(.3,.7,.4,1) infinite}}
.scene-database .g-barra-{n}-2>.pt{{animation:dbBarra{N}2 var(--T) cubic-bezier(.3,.7,.4,1) infinite}}
.scene-database .f-chispas-{n} b{{animation-name:dbChispas{N}}}
.scene-database .p-nodo-{n}{{animation:dbNodo{N} var(--T) infinite}}
{estrellas(n)}
{tarjeta_kf(n, m, SIGNO[n])}
{cabeza_kf(n, m)}
{corazon_kf(n, m)}""")

# los discos: el de arriba siempre va igual o más alto que el de en medio (va montado en él)
SALTOS = [0, 24, 48]  # cada envío empieza con un brinco del cilindro
d1, d2 = ["  0%,100%{transform:none}"], ["  0%,100%{transform:none}"]
for t0 in SALTOS:
    d2 += [f"  {t0}%{{transform:none}}", f"  {t0 + 1}%{{transform:translateY(-1.1cqw)}}",
           f"  {t0 + 2.5}%{{transform:translateY(-1.5cqw)}}", f"  {t0 + 4}%{{transform:translateY(-.6cqw)}}",
           f"  {t0 + 5}%{{transform:translateY(0) scale(1.03,.95)}}", f"  {t0 + 6}%{{transform:scale(.99,1.02)}}",
           f"  {t0 + 7}%{{transform:none}}"]
    d1 += [f"  {t0}%{{transform:none}}", f"  {t0 + 1}%{{transform:translateY(-2.2cqw) rotate(-2deg)}}",
           f"  {t0 + 2.5}%{{transform:translateY(-3.6cqw) rotate(3deg)}}",
           f"  {t0 + 4}%{{transform:translateY(-3cqw) rotate(-1deg)}}",
           f"  {t0 + 5}%{{transform:translateY(-.8cqw) rotate(0)}}", f"  {t0 + 6}%{{transform:translateY(0) scale(1.04,.93)}}",
           f"  {t0 + 7}%{{transform:none}}"]
# fiesta final: los datos regresan y el cilindro brinca alto dos veces
d2 += ["  79%{transform:none}", "  80.5%{transform:translateY(-2cqw)}", "  82%{transform:translateY(-2.6cqw)}",
       "  83.5%{transform:translateY(0) scale(1.04,.94)}", "  85%{transform:translateY(-1.4cqw)}",
       "  86.5%{transform:translateY(0) scale(1.03,.96)}", "  88%{transform:none}"]
d1 += ["  79%{transform:none}", "  80.5%{transform:translateY(-4cqw) rotate(-4deg)}",
       "  82%{transform:translateY(-5.4cqw) rotate(3deg)}", "  83.5%{transform:translateY(-2.6cqw) rotate(-1deg)}",
       "  84.2%{transform:translateY(0) scale(1.05,.92)}", "  85%{transform:translateY(-2.6cqw) rotate(2deg)}",
       "  86.5%{transform:translateY(-.4cqw)}", "  87.2%{transform:translateY(0) scale(1.03,.95)}",
       "  88%{transform:none}"]


def ordenar(lineas):
    def clave(l):
        pc = l.strip().split("%")[0].split(",")[0]
        return float(pc)
    return sorted(lineas, key=clave)


css = f"""/* ============================================================
   database: la base de datos manda datos a cada tarjeta y hacen match
   (generado por scripts/capas-landing/database.py: no editar a mano)
   ============================================================ */
.scene-database{{--T:{T}s}}
.scene-database .g-disco-1{{animation:dbDisco1 var(--T) ease-in-out infinite}}
.scene-database .g-disco-2{{animation:dbDisco2 var(--T) ease-in-out infinite}}
@keyframes dbDisco1{{
{chr(10).join(ordenar(d1))}
}}
@keyframes dbDisco2{{
{chr(10).join(ordenar(d2))}
}}
/* brillos: se deslizan por la banda como si los discos giraran */
.scene-database .p-ovalo-1,.scene-database .p-ovalo-2,.scene-database .p-ovalo-3{{animation:dbGiro 2.6s linear infinite}}
.scene-database .p-ovalo-2{{animation-delay:-.9s}}
.scene-database .p-ovalo-3{{animation-delay:-1.7s}}
@keyframes dbGiro{{
  0%{{transform:translateX(-1.2cqw) scaleX(.35);opacity:0}}
  12%{{transform:translateX(0) scaleX(1);opacity:1}}
  55%{{transform:translateX(11cqw) scaleX(1.1);opacity:.85}}
  82%{{transform:translateX(18.5cqw) scaleX(.45);opacity:0}}
  100%{{transform:translateX(18.5cqw) scaleX(.35);opacity:0}}
}}
/* bits que salen volando del cilindro en cada envío */
.scene-database .f-bits i{{position:absolute;bottom:0;width:11%;aspect-ratio:1;border-radius:28%;opacity:0;
  background:#33C7BE;box-shadow:0 0 0 .3cqw #fff;animation:dbBit var(--T) infinite}}
.scene-database .f-bits i:nth-child(1){{left:8%;--x:-18%}}
.scene-database .f-bits i:nth-child(2){{left:28%;background:#B794F4;--x:-6%;animation-delay:.08s}}
.scene-database .f-bits i:nth-child(3){{left:46%;background:#FFC857;--x:4%;animation-delay:.16s;border-radius:50%}}
.scene-database .f-bits i:nth-child(4){{left:62%;--x:10%;animation-delay:.04s;border-radius:50%}}
.scene-database .f-bits i:nth-child(5){{left:78%;background:#FF8A5C;--x:20%;animation-delay:.12s}}
.scene-database .f-bits i:nth-child(6){{left:90%;background:#B794F4;--x:30%;animation-delay:.2s;border-radius:50%}}
@keyframes dbBit{{
  0%,0.9%,10%,24.9%,34%,48.9%,58%,80.4%,92%,100%{{transform:translate(0,60%) scale(.3);opacity:0}}
  2%,26%,50%,81.5%{{transform:translate(0,0) scale(1);opacity:1}}
  8%,32%,56%{{transform:translate(var(--x),-260%) scale(.7) rotate(160deg);opacity:0}}
  89%{{transform:translate(calc(var(--x) * 2),-360%) scale(.8) rotate(260deg);opacity:0}}
}}
/* ondas de señal que suben desde la tapa del cilindro en la fiesta final */
.scene-database .f-senal i{{position:absolute;inset:0;border-radius:50%;border:.55cqw solid #B794F4;opacity:0;
  animation:dbSenal var(--T) ease-out infinite}}
.scene-database .f-senal i:nth-child(2){{border-color:#33C7BE;animation-delay:.3s}}
.scene-database .f-senal i:nth-child(3){{animation-delay:.6s}}
@keyframes dbSenal{{
  0%,80%{{transform:translateY(-10%) scale(.7);opacity:0}}
  81%{{opacity:.95}}
  89%,100%{{transform:translateY(-150%) scale(1.25);opacity:0}}
}}
/* puntitos de datos */
.scene-database [class*="f-dato-"] i{{position:absolute;inset:0;border-radius:50%;opacity:0;
  background:radial-gradient(circle,#fff 0 38%,#33C7BE 42% 62%,rgba(51,199,190,0) 72%);
  animation-duration:var(--T);animation-iteration-count:infinite;animation-timing-function:linear}}
.scene-database [class*="f-dato-"] i+i{{inset:22%;animation-delay:.14s;
  background:radial-gradient(circle,#fff 0 40%,#B794F4 45% 65%,rgba(183,148,244,0) 75%)}}
{chr(10).join(kf_datos)}
/* latido (aro) del corazón y chispas de match */
.scene-database [class*="f-latido-"] i{{position:absolute;inset:0;border-radius:50%;border:.6cqw solid #FF6B6B;opacity:0;
  animation-duration:var(--T);animation-iteration-count:infinite;animation-timing-function:ease-out}}
.scene-database [class*="f-chispas-"] b{{position:absolute;width:10%;aspect-ratio:1;opacity:0;transform:scale(0);
  background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23FFC857' d='M12 0c.9 6.4 5.6 11.1 12 12-6.4.9-11.1 5.6-12 12-.9-6.4-5.6-11.1-12-12 6.4-.9 11.1-5.6 12-12z'/%3E%3C/svg%3E") center/contain no-repeat;
  animation-duration:var(--T);animation-iteration-count:infinite}}
.scene-database [class*="f-chispas-"] b:nth-child(even){{width:7%;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23FF6B6B' d='M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.6 4.5c2.1 0 3.6 1.2 4.4 2.6.8-1.4 2.3-2.6 4.4-2.6 3.6 0 5.7 3.9 4.2 7.3C19.5 16.4 12 21 12 21z'/%3E%3C/svg%3E")}}
{chr(10).join(bloques)}
"""
(SALIDA / e.nombre / "escena.css").write_text(css)
