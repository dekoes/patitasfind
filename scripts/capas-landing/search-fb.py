"""Escena 'search-fb': la lupa recorre la pantalla del celular y amplía lo que hay debajo.

La lupa es un grupo que se traslada; dentro lleva un círculo recortado con la pantalla
completa AMPLIADA (m veces) que se traslada en sentido contrario (-m·d), así el lente
siempre muestra la huella/logo que tiene debajo. El borde derecho del celular, la esquina
del logo de Facebook y la huella tapados por la lupa se reconstruyen en la base.
"""
import os

import cv2
import numpy as np
from PIL import Image

from capas import SALIDA, SS, Escena, componer, pct

e = Escena("search-fb", 720, "Reportes desde WhatsApp y redes")
H, W = e.H, e.W
img = e.img
rgb, alfa = img[..., :3], img[..., 3]
lum = rgb.mean(axis=2)
yy, xx = np.mgrid[:H, :W].astype(np.float32)
DEPURA = os.environ.get("DEPURA")  # carpeta para imágenes intermedias

# ---------- geometría de la lupa ----------
C = (745.0, 664.0)  # centro del lente (ajuste del aro)
M_AMP = 2.2  # aumento del lente: la huella grande mide ~2.2 veces las huellas de la pantalla
R_ARO = 288  # radio exterior del aro (incluye el contorno oscuro y su antialias)
R_SOMBRA = 324  # la lupa proyecta un halo durazno sobre la pantalla hasta aquí
dist = np.hypot(xx - C[0], yy - C[1])


def radial_interior():
    """Radio del borde interior del aro por ángulo (primer píxel oscuro desde r=200)."""
    angulos = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    radios = []
    for t in angulos:
        r = 200.0
        while r < 260:
            x, y = int(round(C[0] + r * np.cos(t))), int(round(C[1] + r * np.sin(t)))
            if lum[y, x] < 185:
                break
            r += .5
        radios.append(r)
    radios = np.array(radios)
    # mediana circular para quitar ruido
    ext = np.concatenate([radios[-4:], radios, radios[:4]])
    radios = np.array([np.median(ext[i:i + 9]) for i in range(len(radios))])
    return angulos, radios


ang_int, rad_int = radial_interior()
interior = e.poligono([(C[0] + (r + .5) * np.cos(t), C[1] + (r + .5) * np.sin(t)) for t, r in zip(ang_int, rad_int)])
R_VIDRIO = float(rad_int.max()) + 4  # el recorte circular del contenido queda bajo el aro
disco = e.elipse((C[0] - R_ARO, C[1] - R_ARO, C[0] + R_ARO, C[1] + R_ARO))
disco_sombra = e.elipse((C[0] - R_SOMBRA, C[1] - R_SOMBRA, C[0] + R_SOMBRA, C[1] + R_SOMBRA))

# ---------- borde derecho del celular (pantalla s(y) y contorno exterior o(y)) ----------
TAPADO = (379, 930)  # filas donde la lupa tapa el borde de la pantalla (el contorno exterior reaparece en 918)
TAPADO_EXT = (379, 918)


def cruce(perfil, x0, umbral, baja=True):
    """Primer x (subpíxel) desde x0 donde el perfil cruza el umbral."""
    for x in range(x0, len(perfil) - 1):
        a, b = perfil[x], perfil[x + 1]
        if (a >= umbral > b) if baja else (a <= umbral < b):
            return x + (a - umbral) / (a - b)
    return None


s_vis, o_vis = {}, {}
for y in list(range(140, TAPADO[0])) + list(range(TAPADO_EXT[1], 1000)):
    o_vis[y] = cruce(alfa[y], 760, 128)
for y in range(140, TAPADO[0]):
    s_vis[y] = cruce(lum[y], 700, 150)
for y in range(TAPADO[1], 1000):  # abajo se empieza a buscar a la derecha del aro
    s_vis[y] = cruce(lum[y], 862, 150)


def hermite(y0, y1, f0, f1, d0, d1, y):
    t = (y - y0) / (y1 - y0)
    h = y1 - y0
    return ((2 * t ** 3 - 3 * t ** 2 + 1) * f0 + (t ** 3 - 2 * t ** 2 + t) * h * d0 +
            (-2 * t ** 3 + 3 * t ** 2) * f1 + (t ** 3 - t ** 2) * h * d1)


def curva(vis, tramo):
    ya, yb = tramo[0] - 1, tramo[1]
    arr = np.zeros(H, np.float32)
    for y, v in vis.items():
        arr[y] = v
    # pendientes con regresión en 40 filas a cada lado
    ys_a = np.arange(ya - 40, ya + 1)
    ys_b = np.arange(yb, yb + 30)
    pa = np.polyfit(ys_a, arr[ys_a], 1)
    pb = np.polyfit(ys_b, arr[ys_b], 1)
    fa, fb = np.polyval(pa, ya), np.polyval(pb, yb)
    for y in range(ya + 1, yb):
        arr[y] = hermite(ya, yb, fa, fb, pa[0], pb[0], y)
    return arr


s_y = curva(s_vis, TAPADO)
o_y = curva(o_vis, TAPADO_EXT)

# ---------- campo crema de la pantalla ----------
CREMA = np.array([253, 244.5, 229.5], np.float32)
crema_vis = ((np.abs(rgb - CREMA).max(axis=2) < 9) & (alfa > 250) & (dist > R_SOMBRA + 6)).astype(np.float32)
crema_vis = cv2.erode(crema_vis, np.ones((5, 5), np.uint8))
ys_c, xs_c = np.nonzero(crema_vis)
sel = np.arange(0, len(xs_c), 7)
X = np.c_[np.ones(len(sel)), xs_c[sel], ys_c[sel], xs_c[sel] ** 2, ys_c[sel] ** 2, xs_c[sel] * ys_c[sel]] / \
    np.array([1, W, H, W * W, H * H, W * H])
campo = np.zeros((H, W, 3), np.float32)
Xall = np.stack([np.ones_like(xx), xx, yy, xx ** 2, yy ** 2, xx * yy], axis=-1) / np.array([1, W, H, W * W, H * H, W * H])
for c in range(3):
    coef = np.linalg.lstsq(X, rgb[ys_c[sel], xs_c[sel], c], rcond=None)[0]
    campo[..., c] = Xall @ coef
# residuo local (convolución normalizada) para empalmar sin costura con lo visible
resid = (rgb - campo) * crema_vis[..., None]
num = cv2.GaussianBlur(resid, (0, 0), 18)
den = cv2.GaussianBlur(crema_vis, (0, 0), 18)[..., None]
campo += num / np.maximum(den, 1e-3) * np.clip(den / .05, 0, 1)

# ---------- perfil del marco derecho (se barre a lo largo del borde) ----------
U = np.linspace(-.5, 1.6, 211)


def perfil(filas):
    acc = np.zeros((len(U), 4), np.float32)
    for y in filas:
        xs = s_y[y] + U * (o_y[y] - s_y[y])
        for c in range(4):
            acc[:, c] += np.interp(xs, np.arange(W), img[y, :, c] * (img[y, :, 3] / 255 if c < 3 else 1))
    acc /= len(filas)
    acc[:, :3] /= np.maximum(acc[:, 3:4] / 255, 1e-3)
    return acc


P_ARR = perfil(range(TAPADO[0] - 12, TAPADO[0] - 2))
P_ABA = perfil(range(955, 966))

# ---------- reconstrucción de la base bajo la lupa ----------
mango_reg = e.poligono([(870, 845), (960, 800), (1020, 840), (1185, 1030), (1180, 1120), (1100, 1140),
                        (1040, 1110), (895, 940)])
fuera_tel = (xx > o_y[:, None] + 1.5).astype(np.float32)
mango = mango_reg * fuera_tel * (1 - disco)
tapado = np.maximum(disco_sombra, mango_reg)
tapado = cv2.dilate((tapado > .01).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)

nueva = img.copy()
for y in range(H):
    xs_t = np.nonzero(tapado[y])[0]
    if not len(xs_t):
        continue
    s, o = s_y[y], o_y[y]
    if s == 0 or o == 0:  # filas sin borde medido: solo queda el mango, fuera del celular
        nueva[y, xs_t, 3] = 0
        continue
    u = (xs_t - s) / (o - s)
    w = np.clip((y - TAPADO[0]) / (TAPADO[1] - TAPADO[0]), 0, 1)
    prof = np.stack([np.interp(u, U, (1 - w) * P_ARR[:, c] + w * P_ABA[:, c]) for c in range(4)], axis=-1)
    # pantalla: campo crema; marco: perfil; fuera: transparente (el perfil ya trae el antialias)
    t = np.clip((u + .45) / .2, 0, 1)[:, None]
    prof[:, :3] = campo[y, xs_t] * (1 - t) + prof[:, :3] * t
    prof[:, 3:] = 255 * (1 - t) + prof[:, 3:] * t
    prof[u > 1.55, 3] = 0
    nueva[y, xs_t] = prof
# solo se reemplaza lo que de verdad tapa la lupa: el aro, el mango y el halo sobre la pantalla
en_pantalla = (xx < s_y[:, None] - 2) & (s_y[:, None] > 0)
reconstruir = tapado & ((dist < R_ARO + 3) | en_pantalla | (mango > 0))
e.base = np.where(reconstruir[..., None], nueva, img)

if DEPURA:
    Image.fromarray(np.clip(e.base, 0, 255).astype(np.uint8)).save(f"{DEPURA}/base0.png")
    print("R_VIDRIO", R_VIDRIO, "s/o", s_y[[378, 500, 700, 950]], o_y[[378, 500, 700, 950]])

# ---------- logo de Facebook completo (la esquina inferior derecha la tapa el aro) ----------
FB_ESQ = [(370.2, 204.5), (645.6, 170.6), (691.3, 431.9), (412.9, 470.3)]  # rectas ajustadas a los bordes
fb_m = e.cuadrilatero_redondeado(FB_ESQ, 58)
f_tallo = e.poligono([(522 - .125 * 30, 342), (570 - .132 * 30, 342), (570 + .132 * 120, 492), (522 + .125 * 120, 492)])
oculto_fb = np.clip((R_ARO + 5 - dist) / 3, 0, 1)  # 1 bajo el aro, 0 donde se ve el original
r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
azul_vis = ((b_ - r_ > 120) & (dist > R_ARO + 2)).astype(np.uint8)
azul_vis = cv2.erode(azul_vis, np.ones((5, 5), np.uint8)) * (fb_m > .99)
ys_b, xs_b = np.nonzero(azul_vis)
Xb = np.c_[np.ones(len(xs_b)), xs_b, ys_b]
azul = np.zeros((H, W, 3), np.float32)
for c in range(3):
    coef = np.linalg.lstsq(Xb, rgb[ys_b, xs_b, c], rcond=None)[0]
    azul[..., c] = coef[0] + coef[1] * xx + coef[2] * yy
res = (rgb - azul) * azul_vis[..., None]
azul += cv2.GaussianBlur(res, (0, 0), 12) / np.maximum(cv2.GaussianBlur(azul_vis.astype(np.float32), (0, 0), 12), 1e-3)[..., None] * \
    np.clip(cv2.GaussianBlur(azul_vis.astype(np.float32), (0, 0), 12) / .05, 0, 1)[..., None]
BLANCO_F = np.array([253, 253, 253], np.float32)
sintetico = campo * (1 - fb_m[..., None]) + fb_m[..., None] * (azul * (1 - f_tallo[..., None]) + BLANCO_F * f_tallo[..., None])
fb_rgb = rgb * (1 - oculto_fb[..., None]) + sintetico * oculto_fb[..., None]
fb_region = cv2.dilate((fb_m > .01).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)


def despegar(rgb_fuente, fondo, region, nucleo, t0=6, t1=60, exacto=True):
    """Capa RGBA separada de un fondo opaco conocido (alfa por diferencia de color, como pieza())."""
    dif = np.abs(rgb_fuente - fondo).max(axis=2)
    # alfa mínimo para que el color despegado no se salga de 0..255 (así la mezcla reproduce el original)
    sube = np.where(rgb_fuente > fondo, (rgb_fuente - fondo) / np.maximum(255 - fondo, 1),
                    (fondo - rgb_fuente) / np.maximum(fondo, 1)).max(axis=2)
    a = np.maximum(np.clip((dif - t0) / (t1 - t0), 0, 1), nucleo)
    if exacto:
        a = np.maximum(a, sube)
    a *= region
    seguro = np.maximum(a, 1e-3)[..., None]
    capa = np.zeros((H, W, 4), np.float32)
    capa[..., :3] = np.clip(np.where(a[..., None] > .02, fondo + (rgb_fuente - fondo) / seguro, rgb_fuente), 0, 255)
    capa[..., 3] = a * 255
    return capa


nucleo_fb = cv2.erode((fb_m > .5).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
capa_fb = despegar(fb_rgb, campo, fb_region, nucleo_fb)

if DEPURA:
    Image.fromarray(np.clip(capa_fb, 0, 255).astype(np.uint8)).crop((340, 150, 720, 500)).save(f"{DEPURA}/fb.png")

# ---------- huellas de la pantalla ----------
teal = ((g_ - r_ > 60) & (alfa > 200)).astype(np.float32)
fuera_aro = (dist > R_ARO - 1.5).astype(np.float32)


def caja_m(x0, y0, x1, y1):
    return ((xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)).astype(np.float32)


def capa_huella(mascara_teal, rgb_fuente):
    # borde de 2 px; dentro del halo de la lupa solo 1 px para no arrastrar el durazno
    m8 = mascara_teal.astype(np.uint8)
    region = np.where(dist < R_SOMBRA, cv2.dilate(m8, np.ones((3, 3), np.uint8)),
                      cv2.dilate(m8, np.ones((5, 5), np.uint8))).astype(np.float32)
    nucleo = cv2.erode(mascara_teal.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
    return despegar(rgb_fuente, campo, region, nucleo)


# huella 1: el dedo derecho lo tapa el aro -> elipse del tamaño del dedo izquierdo, ajustada a la parte visible
T_DEDO = np.radians(25.5)
dedo_pts = [(472 + 20.2 * np.cos(f) * np.cos(T_DEDO) - 26.9 * np.sin(f) * np.sin(T_DEDO),
             601.5 + 20.2 * np.cos(f) * np.sin(T_DEDO) + 26.9 * np.sin(f) * np.cos(T_DEDO))
            for f in np.linspace(0, 2 * np.pi, 120, endpoint=False)]
dedo_der = e.poligono(dedo_pts)
dedo_vis = teal * caja_m(449, 574, 500, 630) * (dist > R_ARO + 2)
TEAL_DEDO = np.median(rgb[dedo_vis > 0], axis=0)
oculto_dedo = np.clip((R_ARO + 3 - dist) / 3, 0, 1)
dedo_rgb = campo * (1 - dedo_der[..., None]) + TEAL_DEDO * dedo_der[..., None]
t1_m = teal * caja_m(320, 510, 500, 680) * fuera_aro
n_, lab_, st_, _ = cv2.connectedComponentsWithStats(t1_m.astype(np.uint8), 8)
t1_m = np.isin(lab_, [i for i in range(1, n_) if st_[i, cv2.CC_STAT_AREA] > 300]).astype(np.float32)
zona_dedo = cv2.dilate((dedo_der > 0).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32) * oculto_dedo
h1_rgb = rgb * (1 - zona_dedo[..., None]) + dedo_rgb * zona_dedo[..., None]
h1_rgb = np.where(((dist < R_ARO) & (zona_dedo == 0))[..., None], campo, h1_rgb)
capa_h1 = capa_huella(np.maximum(t1_m * (1 - oculto_dedo), dedo_der > .5), h1_rgb)
capa_h2 = capa_huella(teal * caja_m(375, 845, 575, 1030) * fuera_aro, rgb)

# huella grande del lente (se usa ampliada en el vidrio y, reducida 1/M_AMP, como huella 3 de la pantalla)
interior_ero = cv2.erode((interior > .5).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(np.float32)
CREMA_INT = np.median(rgb[(interior_ero > 0) & (teal < .5) & (dist < 170)], axis=0)
t_grande = teal * interior_ero
fondo_int = np.broadcast_to(CREMA_INT, rgb.shape).astype(np.float32)
reg_g = cv2.dilate(t_grande.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(np.float32) * interior_ero
capa_grande = despegar(rgb, fondo_int, reg_g, cv2.erode(t_grande.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32))
reduce = np.float32([[1 / M_AMP, 0, C[0] - C[0] / M_AMP], [0, 1 / M_AMP, C[1] - C[1] / M_AMP]])


def transformar(capa, matriz, tam=(W, H)):
    """Transforma una capa RGBA (premultiplicada para no ensuciar los bordes)."""
    pre = capa.copy()
    pre[..., :3] *= pre[..., 3:4] / 255
    out = cv2.warpAffine(pre, matriz, tam, flags=cv2.INTER_LANCZOS4 if matriz[0, 0] >= 1 else cv2.INTER_AREA)
    out = np.clip(out, 0, None)
    out[..., 3] = np.clip(out[..., 3], 0, 255)
    out[..., :3] = np.clip(out[..., :3] / np.maximum(out[..., 3:4] / 255, 1e-3), 0, 255)
    out[..., :3] *= (out[..., 3:4] > .5)
    return out


# reducir con buena calidad: primero se reduce al tamaño y después se ubica
capa_h3 = transformar(capa_grande, reduce)

# ---------- base final: pantalla crema bajo las piezas de la pantalla ----------
for capa in (capa_fb, capa_h1, capa_h2):
    hueco = cv2.dilate((capa[..., 3] > 1).astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    e.base[hueco, :3] = campo[hueco]
    e.base[hueco, 3] = 255

# ---------- piezas de la lupa ----------
# aro (todo el disco menos el interior del vidrio) con su alfa original; el borde exterior sigue el
# contorno oscuro real para no arrastrar el logo ni el crema que lo rodean
def radial_exterior():
    """Radio del último píxel oscuro del contorno, buscando desde afuera hacia el centro."""
    radios = []
    for t in ang_int:
        r = float(R_ARO)
        while r > 268:
            x, y = int(round(C[0] + r * np.cos(t))), int(round(C[1] + r * np.sin(t)))
            if lum[y, x] < 85 and alfa[y, x] > 128:
                break
            r -= .5
        radios.append(r + .5)
    radios = np.array(radios)
    ext = np.concatenate([radios[-3:], radios, radios[:3]])
    return np.array([np.median(ext[i:i + 7]) for i in range(len(radios))])


rad_ext = radial_exterior()
borde_aro = e.poligono([(C[0] + (r + 1)  * np.cos(t), C[1] + (r + 1) * np.sin(t)) for t, r in zip(ang_int, rad_ext)])
interior_aro = cv2.erode((interior > .5).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
capa_aro = img.copy()
capa_aro[..., 3] = alfa * borde_aro * (1 - interior_aro)

# halo durazno: un solo tono (dirección principal de la diferencia con el crema) con alfa variable,
# así sobre el logo o las huellas se lee como sombra y en reposo reproduce el original
pantalla_crema = (xx < s_y[:, None] - 3) & (s_y[:, None] > 0) & (np.abs(e.base[..., :3] - campo).max(axis=2) < 3)
excluir = cv2.dilate(((capa_fb[..., 3] + capa_h1[..., 3] + capa_h2[..., 3]) > 1).astype(np.uint8),
                     np.ones((5, 5), np.uint8)).astype(bool)
anillo = (dist > R_ARO - 3) & (dist < R_SOMBRA + 2) & pantalla_crema & ~excluir
D = (rgb - campo)[anillo & (dist > R_ARO + 1)]
_, _, vt = np.linalg.svd(D, full_matrices=False)
v = vt[0] * np.sign(vt[0].sum())  # hacia más oscuro: componentes negativas
v = -np.abs(v) if v.sum() > 0 else v
proy = (rgb - campo) @ v
escala = np.percentile(proy[anillo], 99.5) / .55  # el halo más intenso queda con alfa .55
K = np.clip(CREMA + v * escala, 0, 255)
dirK = K - campo
a_halo = ((rgb - campo) * dirK).sum(axis=2) / np.maximum((dirK ** 2).sum(axis=2), 1)
a_halo = np.clip(a_halo, 0, 1) * anillo * np.clip((R_SOMBRA + 2 - dist) / 6, 0, 1)
capa_halo = np.zeros((H, W, 4), np.float32)
capa_halo[..., :3] = K
capa_halo[..., 3] = cv2.GaussianBlur(a_halo, (0, 0), 1.2) * 255

# brillos del vidrio: lo que el interior se aparta del crema (sin la huella)
lejos_huella = 1 - cv2.dilate(t_grande.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(np.float32)
# el sombreado del vidrio se suaviza (convolución normalizada, sin la huella) para que no arrastre el grano
# del original: sobre el logo azul ese grano se vería como puntitos blancos
reg_b = ((interior > .5) * lejos_huella).astype(np.float32)
num_b = cv2.GaussianBlur((rgb - fondo_int) * reg_b[..., None], (0, 0), 1.6)
den_b = cv2.GaussianBlur(reg_b, (0, 0), 1.6)[..., None]
rgb_suave = fondo_int + num_b / np.maximum(den_b, 1e-3)
capa_brillo = despegar(rgb_suave, fondo_int, (interior > .02) * lejos_huella, np.zeros((H, W), np.float32), t0=4, t1=40,
                       exacto=False)
capa_brillo[..., 3] = np.where(capa_brillo[..., 3] < 8, 0, capa_brillo[..., 3])

# mango: la parte fuera del aro; se prolonga hacia adentro bajo el aro para poder girarlo
capa_mango = img.copy()
capa_mango[..., 3] = alfa * mango
ang = np.degrees(np.arctan2(yy - C[1], xx - C[0]))
bajo_aro = (dist > R_ARO - 26) & (dist <= R_ARO - 1) & (ang > 30) & (ang < 56)
src_x = (C[0] + (R_ARO + 5) * np.cos(np.radians(ang))).astype(np.float32)
src_y = (C[1] + (R_ARO + 5) * np.sin(np.radians(ang))).astype(np.float32)
prolongado = cv2.remap(capa_mango, src_x, src_y, cv2.INTER_LINEAR)
capa_mango = np.where(bajo_aro[..., None], prolongado, capa_mango)

# ---------- pantalla completa (S) y su versión ampliada para el vidrio (A) ----------
pantalla = componer(e.base.copy(), capa_fb, capa_h1, capa_h2)  # la huella 3 ampliada es la grande original
CAJA_A = (-290, -330, 1040, 1530)  # zona del plano ampliado que llega a verse durante el recorrido
aw, ah = CAJA_A[2] - CAJA_A[0], CAJA_A[3] - CAJA_A[1]
amplia = np.float32([[M_AMP, 0, (C[0] - C[0] * M_AMP) - CAJA_A[0]], [0, M_AMP, (C[1] - C[1] * M_AMP) - CAJA_A[1]]])
capa_amp = transformar(pantalla, amplia, (aw, ah))
# en reposo el lente muestra exactamente la huella grande original
grande_en_a = transformar(capa_grande, np.float32([[1, 0, -CAJA_A[0]], [0, 1, -CAJA_A[1]]]), (aw, ah))
capa_amp = componer(capa_amp, grande_en_a)

if DEPURA:
    for n, c in (("h1", capa_h1), ("h2", capa_h2), ("h3", capa_h3), ("aro", capa_aro), ("halo", capa_halo),
                 ("brillo", capa_brillo), ("mango", capa_mango), ("pantalla", pantalla)):
        Image.fromarray(np.clip(c, 0, 255).astype(np.uint8)).save(f"{DEPURA}/{n}.png")
    Image.fromarray(np.clip(capa_amp, 0, 255).astype(np.uint8)).resize((aw // 3, ah // 3)).save(f"{DEPURA}/amp.png")
    Image.fromarray(np.clip(e.base, 0, 255).astype(np.uint8)).save(f"{DEPURA}/base.png")

if DEPURA:
    # reposo: la composición de todas las capas debe dar la ilustración original
    vidrio = e.elipse((C[0] - R_VIDRIO, C[1] - R_VIDRIO, C[0] + R_VIDRIO, C[1] + R_VIDRIO))
    amp_reposo = transformar(capa_amp, np.float32([[1, 0, CAJA_A[0]], [0, 1, CAJA_A[1]]]))
    amp_reposo[..., 3] *= vidrio
    reposo = componer(e.base.copy(), capa_fb, capa_h1, capa_h2, capa_h3, capa_mango, amp_reposo, capa_brillo,
                      capa_halo, capa_aro)
    fondo = np.zeros_like(img)
    fondo[..., :3] = (243, 239, 232)
    fondo[..., 3] = 255
    orig = img.copy()
    orig[..., 3] = np.where(orig[..., 3] > 240, 255, orig[..., 3])  # el original trae alfa 251-254 en lo opaco
    a1, a2 = componer(fondo, reposo), componer(fondo, orig)
    dif = np.abs(a1[..., :3] - a2[..., :3]).max(axis=2)
    print("K", K.round(1), "v", v.round(3))
    print("dif reposo: media %.2f, p99 %.1f, max %.0f" % (dif.mean(), np.percentile(dif, 99), dif.max()))
    Image.fromarray(np.clip(dif * 4, 0, 255).astype(np.uint8)).save(f"{DEPURA}/dif.png")
    Image.fromarray(np.clip(a1, 0, 255).astype(np.uint8)).save(f"{DEPURA}/reposo.png")

# =====================================================================
# Salida: piezas, grupos y capas de efectos
# =====================================================================
# rayitas lila: salen desde el lado que mira a la lupa / al celular
e.pieza("rayita-1", e.por_alfa(e.rect((915, 238, 1002, 372))), pivote=(921, 368), clases="a-flash",
        estilo="--dur:1.9s;--delay:-.2s")
e.pieza("rayita-2", e.por_alfa(e.rect((966, 338, 1076, 434))), pivote=(972, 428), clases="a-flash",
        estilo="--dur:1.9s;--delay:-.5s")
e.pieza("rayita-3", e.por_alfa(e.rect((130, 760, 230, 828))), pivote=(226, 802), clases="a-flash",
        estilo="--dur:2.3s;--delay:-1.1s")
e.pieza("rayita-4", e.por_alfa(e.rect((143, 850, 233, 923))), pivote=(229, 858), clases="a-flash",
        estilo="--dur:2.3s;--delay:-1.4s")

# logo de Facebook con su globito de notificaciones
e.grupo("fb", (360, 160, 700, 480), pivote=(545, 470))
e.pieza_desde("fb", capa_fb, grupo="fb")
e.html("badge", (628, 128, 708, 208), "<i>1</i><i>2</i><i>3</i>", grupo="fb")
e.pieza_desde("huella-1", capa_h1, pivote=(405, 672))
e.pieza_desde("huella-2", capa_h2, pivote=(470, 1018))
e.pieza_desde("huella-3", capa_h3, pivote=(745, 740))

# lupa: se traslada; dentro, el vidrio recortado con la pantalla ampliada
LUPA = (C[0] - R_SOMBRA, C[1] - R_SOMBRA, 1190, 1145)
e.grupo("lupa", LUPA, pivote=C)
e.pieza_desde("halo", capa_halo, grupo="lupa")
e.pieza_desde("mango", capa_mango, pivote=C, grupo="lupa")
VIDRIO = (C[0] - R_VIDRIO, C[1] - R_VIDRIO, C[0] + R_VIDRIO, C[1] + R_VIDRIO)
e.grupo("vidrio", VIDRIO, radio=R_VIDRIO, clase="clip", padre="lupa")
aw_px, ah_px = round(aw * e.escala), round(ah * e.escala)
Image.fromarray(np.clip(capa_amp, 0, 255).astype(np.uint8), "RGBA").resize((aw_px, ah_px), Image.LANCZOS).save(
    SALIDA / e.nombre / "ampliada.webp", "WEBP", quality=80, method=6, alpha_quality=80)
e.items.append(dict(tipo="pieza", nombre="ampliada", caja=CAJA_A, px=(aw_px, ah_px), pivote=C, grupo="vidrio",
                    clases="", estilo="", extra=""))
e.html("destello", VIDRIO, "<i></i>", grupo="lupa")
e.pieza_desde("brillo", capa_brillo, grupo="lupa")
e.pieza_desde("aro", capa_aro, grupo="lupa")
e.html("chispas", (C[0] - 360, C[1] - 360, C[0] + 360, C[1] + 360), "<b></b>" * 6, grupo="lupa")

# avisos que llegan de WhatsApp y de redes
e.html("aviso-wa", (850, 40, 1010, 185),
       '<svg viewBox="0 0 64 58"><path d="M32 3C16 3 4 13.6 4 26.5c0 7 3.6 13.3 9.3 17.6L10 55l13-6.3c2.8.7 5.8 1.1 9 1.1 '
       '16 0 28-10.6 28-23.3S48 3 32 3z"/><g fill="#fff"><ellipse cx="22.5" cy="20" rx="3.6" ry="4.6"/>'
       '<ellipse cx="32" cy="16.5" rx="3.6" ry="4.6"/><ellipse cx="41.5" cy="20" rx="3.6" ry="4.6"/>'
       '<path d="M32 24.5c-5.2 0-9.5 6.4-9.5 9.6 0 2.8 2.6 3.6 4.6 3.6 1.8 0 3.2-1 4.9-1s3.1 1 4.9 1c2 0 4.6-.8 '
       '4.6-3.6 0-3.2-4.3-9.6-9.5-9.6z"/></g></svg>')
e.html("aviso-fb", (20, 70, 160, 196),
       '<svg viewBox="0 0 64 58"><path d="M32 3C16 3 4 13.6 4 26.5c0 7 3.6 13.3 9.3 17.6L10 55l13-6.3c2.8.7 5.8 1.1 9 1.1 '
       '16 0 28-10.6 28-23.3S48 3 32 3z"/><path fill="#fff" d="M32 39s-11-6.6-11-14c0-3.6 2.7-6.2 5.8-6.2 2.2 0 4 1.2 '
       '5.2 3 1.2-1.8 3-3 5.2-3 3.1 0 5.8 2.6 5.8 6.2 0 7.4-11 14-11 14z"/></svg>')
e.guardar()

# =====================================================================
# CSS: el recorrido de la lupa y la pantalla ampliada se generan juntos para que vayan sincronizados
# =====================================================================
T = 11  # segundos del ciclo
CW = W / 100  # px de la imagen por cqw (la escena es cuadrada: sirve también en vertical)
P0 = C
FB, H1, H2 = (530, 322), (410, 598), (474, 912)
A1, A2, A3, A4 = (672, 420), (425, 445), (372, 772), (652, 892)
SALE = "cubic-bezier(.45,.05,.62,.7)"   # arranca despacio (hacia un punto de paso)
LLEGA = "cubic-bezier(.28,.42,.45,1)"   # frena al llegar
QUIETO = "ease-in-out"


def mas(p, dx, dy):
    return (p[0] + dx, p[1] + dy)


# (porcentaje, centro del lente, escala de la lupa, latido de la huella ampliada, curva del tramo siguiente)
RECORRIDO = [
    (0, P0, 1, 1, QUIETO), (2, P0, 1.06, 1.16, QUIETO), (4, P0, .98, .95, QUIETO), (6, P0, 1, 1, SALE),
    (13, A1, 1.04, 1, LLEGA), (20, FB, 1, 1, QUIETO), (24, mas(FB, -14, 8), 1, 1, QUIETO),
    (28, mas(FB, 10, -6), 1, 1, QUIETO), (31, FB, 1, 1, SALE),
    (37, A2, 1.04, 1, LLEGA), (42, H1, 1, 1, QUIETO), (44, H1, 1.07, 1.18, QUIETO), (46, H1, .98, .95, QUIETO),
    (48, H1, 1, 1, SALE),
    (54, A3, 1.04, 1, LLEGA), (60, H2, 1, 1, QUIETO), (62, H2, 1.07, 1.18, QUIETO), (64, H2, .98, .95, QUIETO),
    (67, H2, 1, 1, SALE),
    (74, A4, 1.04, 1, LLEGA), (81, mas(P0, -10, -8), 1, 1, QUIETO), (84, P0, 1, 1, QUIETO),
    (86, P0, 1.1, 1.22, QUIETO), (88, P0, .97, .93, QUIETO), (90, P0, 1.04, 1.07, QUIETO), (92, P0, 1, 1, QUIETO),
    (100, P0, 1, 1, QUIETO),
]


def num(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) > 5e-4 else "0"


def fotogramas(nombre, fn):
    lineas = []
    for pc, pos, s_lupa, k, curva in RECORRIDO:
        dx, dy = (pos[0] - C[0]) / CW, (pos[1] - C[1]) / CW
        lineas.append(f"  {pc}%{{transform:{fn(dx, dy, s_lupa, k)};animation-timing-function:{curva}}}")
    return f"@keyframes {nombre}{{\n" + "\n".join(lineas) + "\n}"


kf_lupa = fotogramas("sfLupa", lambda dx, dy, s, k: f"translate({num(dx)}cqw,{num(dy)}cqw) scale({num(s)})")
kf_amp = fotogramas("sfAmpliada", lambda dx, dy, s, k: f"scale({num(k)}) translate({num(-M_AMP * dx)}cqw,"
                                                         f"{num(-M_AMP * dy)}cqw)")

# chispas alrededor del aro (evitan el mango)
chispas = []
for i, ang_c in enumerate((-150, -105, -62, -18, 150, 196)):
    t = np.radians(ang_c)
    chispas.append(f".scene-search-fb .f-chispas b:nth-child({i + 1}){{left:{50 + 45 * np.cos(t) - 5:.2f}%;"
                   f"top:{50 + 45 * np.sin(t) - 5:.2f}%;animation-delay:{i * .04:.2f}s}}")

css = f"""/* ============================================================
   search-fb: la lupa recorre el celular y amplía lo que tiene debajo
   (generado por scripts/capas-landing/search-fb.py: no editar a mano)
   ============================================================ */
.scene-search-fb{{--T:{T}s}}
.scene-search-fb .g-lupa{{animation:sfLupa var(--T) infinite}}
.scene-search-fb .p-ampliada{{animation:sfAmpliada var(--T) infinite}}
{kf_lupa}
{kf_amp}
/* el mango gira alrededor del lente: se acomoda en cada vuelta y abajo se tuerce para no salirse */
.scene-search-fb .p-mango{{animation:sfMango var(--T) ease-in-out infinite}}
@keyframes sfMango{{
  0%,6%,20%,31%,42%,48%,84%,100%{{transform:none}}
  10%{{transform:rotate(9deg)}}14%{{transform:rotate(-7deg)}}17%{{transform:rotate(4deg)}}
  24%{{transform:rotate(-6deg)}}28%{{transform:rotate(6deg)}}
  35%{{transform:rotate(11deg)}}39%{{transform:rotate(-6deg)}}
  52%{{transform:rotate(-16deg)}}57%{{transform:rotate(-46deg)}}60%,67%{{transform:rotate(-40deg)}}
  62%{{transform:rotate(-43deg)}}64%{{transform:rotate(-38deg)}}
  71%{{transform:rotate(-26deg)}}74%{{transform:rotate(-19deg)}}79%{{transform:rotate(7deg)}}82%{{transform:rotate(-4deg)}}
}}
/* destello dentro del vidrio cada vez que encuentra una huella */
.scene-search-fb .f-destello{{border-radius:50%}}
.scene-search-fb .f-destello i{{position:absolute;inset:0;border-radius:50%;opacity:0;
  background:radial-gradient(circle,rgba(255,255,255,.95) 0,rgba(255,255,255,.55) 35%,rgba(255,255,255,0) 70%);
  animation:sfDestello var(--T) infinite}}
@keyframes sfDestello{{
  0%,5%,42%,47%,60%,65%,84%,91%,100%{{opacity:0;transform:scale(.6)}}
  1.5%,43.5%,61.5%{{opacity:.8;transform:scale(1)}}
  86%{{opacity:.95;transform:scale(1.05)}}
}}
.scene-search-fb .f-chispas b{{position:absolute;width:10%;aspect-ratio:1;opacity:0;transform:scale(0);
  background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23FFC857' d='M12 0c.9 6.4 5.6 11.1 12 12-6.4.9-11.1 5.6-12 12-.9-6.4-5.6-11.1-12-12 6.4-.9 11.1-5.6 12-12z'/%3E%3C/svg%3E") center/contain no-repeat;
  animation:sfChispa var(--T) infinite}}
.scene-search-fb .f-chispas b:nth-child(even){{width:7%;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%2333C7BE' d='M12 0c.9 6.4 5.6 11.1 12 12-6.4.9-11.1 5.6-12 12-.9-6.4-5.6-11.1-12-12 6.4-.9 11.1-5.6 12-12z'/%3E%3C/svg%3E")}}
{chr(10).join(chispas)}
@keyframes sfChispa{{
  0%,43%,61%,85%{{opacity:0;transform:scale(0) rotate(0)}}
  2%,45%,63%{{opacity:1;transform:scale(1.15) rotate(45deg)}}
  5%,48%,66%{{opacity:0;transform:scale(.4) rotate(90deg)}}
  87.5%{{opacity:1;transform:scale(1.4) rotate(45deg)}}
  91%{{opacity:1;transform:scale(.9) rotate(80deg)}}
  95%,100%{{opacity:0;transform:scale(.3) rotate(120deg)}}
}}
/* el logo de Facebook brinca cuando llega un aviso; las huellas laten cuando la lupa no las cubre */
.scene-search-fb .g-fb{{animation:sfFb var(--T) infinite}}
@keyframes sfFb{{
  0%,7%,43%,51%,61%,69%,85%,95%,100%{{transform:none}}
  1.5%,44.5%,62.5%,86.5%{{transform:scale(1.1,.86)}}
  3.5%,46.5%,64.5%,88.5%{{transform:translateY(-12%) scale(.95,1.07) rotate(-4deg)}}
  5.5%,48.5%,66.5%,90.5%{{transform:scale(1.06,.93) rotate(2deg)}}
  92.5%{{transform:translateY(-5%) rotate(-2deg)}}
}}
.scene-search-fb .f-badge{{opacity:0;transform:scale(0);animation:sfBadge var(--T) infinite}}
.scene-search-fb .f-badge i{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  border-radius:50%;background:#FF5A5A;border:.45cqw solid #fff;box-shadow:0 .3cqw .8cqw rgba(0,0,0,.18);
  color:#fff;font:800 4.4cqw/1 'Baloo 2',sans-serif;font-style:normal;opacity:0}}
.scene-search-fb .f-badge i:nth-child(1){{animation:sfB1 var(--T) infinite}}
.scene-search-fb .f-badge i:nth-child(2){{animation:sfB2 var(--T) infinite}}
.scene-search-fb .f-badge i:nth-child(3){{animation:sfB3 var(--T) infinite}}
@keyframes sfBadge{{
  0%,43.5%{{opacity:0;transform:scale(0)}}
  45%{{opacity:1;transform:scale(1.35)}}47%{{transform:scale(.92)}}48.5%,62%{{transform:scale(1)}}
  63%{{transform:scale(1.3)}}65%,86%{{transform:scale(1)}}87%{{transform:scale(1.4)}}89%,96%{{opacity:1;transform:scale(1)}}
  98%,100%{{opacity:0;transform:scale(0)}}
}}
@keyframes sfB1{{0%,62.5%,100%{{opacity:1}}62.6%,99.9%{{opacity:0}}}}
@keyframes sfB2{{0%,62.5%{{opacity:0}}62.6%,86.5%{{opacity:1}}86.6%,100%{{opacity:0}}}}
@keyframes sfB3{{0%,86.5%{{opacity:0}}86.6%,100%{{opacity:1}}}}
.scene-search-fb .p-huella-1{{animation:sfHuella1 var(--T) infinite}}
.scene-search-fb .p-huella-2{{animation:sfHuella2 var(--T) infinite}}
.scene-search-fb .p-huella-3{{animation:sfHuella3 var(--T) infinite}}
@keyframes sfHuella1{{
  0%,62%,70%,86%,94%,100%{{transform:none}}
  63.5%,87.5%{{transform:scale(1.12,.86)}}
  66%,90%{{transform:translateY(-14%) scale(.94,1.08) rotate(-8deg)}}
  68%,92%{{transform:scale(1.06,.94) rotate(4deg)}}
}}
@keyframes sfHuella2{{
  0%,21%,29%,43%,50%,100%{{transform:none}}
  22.5%,44.5%{{transform:scale(1.12,.86)}}
  25%,47%{{transform:translateY(-14%) scale(.94,1.08) rotate(7deg)}}
  27%,49%{{transform:scale(1.06,.94) rotate(-4deg)}}
}}
@keyframes sfHuella3{{
  0%,29%,37%,51%,58%,100%{{transform:none}}
  30.5%,52.5%{{transform:scale(1.14,.85)}}
  33%,55%{{transform:translateY(-16%) scale(.94,1.1) rotate(-9deg)}}
  35%,57%{{transform:scale(1.07,.93) rotate(5deg)}}
}}
/* avisos de WhatsApp y de redes que salen del celular */
.scene-search-fb .f-aviso-wa svg,.scene-search-fb .f-aviso-fb svg{{display:block;width:100%;height:100%;overflow:visible;
  filter:drop-shadow(0 .4cqw 0 rgba(40,30,60,.18))}}
.scene-search-fb .f-aviso-wa svg{{fill:#25D366;transform-origin:15% 95%}}
.scene-search-fb .f-aviso-fb svg{{fill:#1877F2;transform-origin:85% 95%}}
.scene-search-fb .f-aviso-wa,.scene-search-fb .f-aviso-fb{{opacity:0}}
.scene-search-fb .f-aviso-wa{{animation:sfAvisoWa var(--T) infinite}}
.scene-search-fb .f-aviso-fb{{animation:sfAvisoFb var(--T) infinite}}
@keyframes sfAvisoWa{{
  0%,44%{{opacity:0;transform:translate(-30%,30%) scale(.2)}}
  46.5%{{opacity:1;transform:translate(0,0) scale(1.15)}}
  48.5%{{transform:scale(.95)}}
  50%,56%{{opacity:1;transform:translate(0,-6%) scale(1) rotate(-3deg)}}
  60%,85%{{opacity:0;transform:translate(10%,-30%) scale(.8)}}
  86%{{opacity:0;transform:translate(-30%,30%) scale(.2)}}
  88.5%{{opacity:1;transform:translate(0,0) scale(1.2) rotate(4deg)}}
  90.5%{{transform:scale(.95)}}
  92%,95%{{opacity:1;transform:translate(0,-6%) scale(1)}}
  99%,100%{{opacity:0;transform:translate(10%,-30%) scale(.8)}}
}}
@keyframes sfAvisoFb{{
  0%,62%{{opacity:0;transform:translate(30%,30%) scale(.2)}}
  64.5%{{opacity:1;transform:translate(0,0) scale(1.15)}}
  66.5%{{transform:scale(.95)}}
  68%,74%{{opacity:1;transform:translate(0,-6%) scale(1) rotate(3deg)}}
  78%,87%{{opacity:0;transform:translate(-10%,-30%) scale(.8)}}
  88%{{opacity:0;transform:translate(30%,30%) scale(.2)}}
  90.5%{{opacity:1;transform:translate(0,0) scale(1.2) rotate(-4deg)}}
  92.5%{{transform:scale(.95)}}
  94%,96%{{opacity:1;transform:translate(0,-6%) scale(1)}}
  100%{{opacity:0;transform:translate(-10%,-30%) scale(.8)}}
}}
"""
(SALIDA / e.nombre / "escena.css").write_text(css)
