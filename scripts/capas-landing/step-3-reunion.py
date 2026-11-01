"""Escena 'step-3-reunion' (Cómo funciona · Reencuentro seguro): la chica abraza al beagle y lo aprieta,
el perro restriega la cabeza y saca la lengua, la cola menea a toda velocidad, el escudo hace pop con
destello y los corazones brotan y truenan en secuencia.

La ilustración tiene fondo transparente y casi todo es una sola figura: la figura completa va en una
pieza (para el "apretón") y las partes que se mueven encima. Debajo de cada parte se deja un relleno
que solo se extiende unos px desde lo que la rodea (ver `quitar_relleno`), así al moverse no aparecen
huecos ni fantasmas, y donde antes había fondo sigue habiendo fondo.

Este script también escribe app/img/anim/step-3-reunion/escena.css.
"""
import cv2
import numpy as np

from capas import SALIDA, Escena, rellenar

e = Escena("step-3-reunion", 600, "Reencuentro seguro con el perro")
H, W = e.H, e.W
yy, xx = np.mgrid[:H, :W].astype(np.float32)
ORIG = e.img.copy()
R, G, B, A = (ORIG[..., i] for i in range(4))


def caja_de(m, margen=40):
    ys, xs = np.nonzero(m > 0.02)
    return (max(0, xs.min() - margen), max(0, ys.min() - margen), min(W, xs.max() + margen + 1),
            min(H, ys.max() + margen + 1))


def quitar_relleno(m, extension, radio=8, encoger=None):
    """Después de recortar una pieza, deja en e.img lo que habría debajo: el color se reconstruye con
    inpaint desde lo opaco que la rodea y el alfa solo llega `extension` px hacia adentro (lo que estaba
    sobre fondo transparente queda transparente). Con `encoger`, además se deja la silueta original
    encogida esos px (para piezas grandes que se mecen, como el pelo)."""
    x0, y0, x1, y1 = caja_de(m, extension + 20)
    sub = e.img[y0:y1, x0:x1]
    mm = m[y0:y1, x0:x1]
    conocido = (sub[..., 3] > 250) & (mm < 0.02)
    rgb = np.clip(sub[..., :3], 0, 255).astype(np.uint8)
    relleno = cv2.inpaint(rgb, (~conocido).astype(np.uint8), radio, cv2.INPAINT_TELEA).astype(np.float32)
    dist = cv2.distanceTransform((~conocido).astype(np.uint8), cv2.DIST_L2, 5)
    a_rel = np.clip(extension - dist, 0, 1)
    if encoger:
        dist_fondo = cv2.distanceTransform((ORIG[y0:y1, x0:x1, 3] > 128).astype(np.uint8), cv2.DIST_L2, 5)
        a_rel = np.maximum(a_rel, np.clip(dist_fondo - encoger, 0, 1))
    a_rel = a_rel * ORIG[y0:y1, x0:x1, 3]
    # solo en el núcleo de la pieza: en su borde difuminado se queda el original (pieza + original = original)
    nucleo = np.clip((mm - 0.9) * 10, 0, 1)
    k = nucleo[..., None]
    sub[..., :3] = sub[..., :3] * (1 - k) + relleno * k
    sub[..., 3] = sub[..., 3] * (1 - nucleo) + a_rel * nucleo


def disco(cx, cy, r):
    return e.elipse((cx - r, cy - r, cx + r, cy + r))


def suave(binaria, crecer=0, sigma=0.8):
    b = binaria.astype(np.uint8)
    if crecer:
        b = cv2.dilate(b, np.ones((crecer * 2 + 1,) * 2, np.uint8))
    return cv2.GaussianBlur(b.astype(np.float32), (0, 0), sigma)


# ---------- corazones y rayitas (sueltos, sobre fondo transparente) ----------
CORAZONES = {  # nombre: caja, pivote (abajo al centro)
    "corazon-rojo-izq": ((175, 197, 274, 298), (225, 296)),
    "corazon-lila-izq": ((123, 314, 225, 418), (175, 416)),
    "corazon-rojo-der": ((872, 173, 996, 298), (925, 296)),
    "corazon-lila-der": ((933, 313, 1047, 426), (985, 424)),
}
# cada uno es un componente suelto del alfa: la máscara es el componente (un poco crecido)
n_comp, comp = cv2.connectedComponents((A > 0).astype(np.uint8), connectivity=8)


def componente(caja):
    x0, y0, x1, y1 = caja
    ids = set(np.unique(comp[y0:y1, x0:x1])) - {0}
    m = np.isin(comp, list(ids)) & (e.rect(caja) > 0.5)
    return cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)


SUELTOS = np.zeros((H, W), np.float32)
it_corazones = {}
for n, (c, p) in CORAZONES.items():
    m = componente(c)
    SUELTOS = np.maximum(SUELTOS, m)
    it_corazones[n] = e.pieza(n, m, pivote=p, diferir=True, clases="a-pop")
m1, m2 = componente((1122, 678, 1157, 773)), componente((1151, 716, 1180, 804))
SUELTOS = np.maximum(SUELTOS, np.maximum(m1, m2))
it_rayita_1 = e.pieza("rayita-1", m1, pivote=(1120, 740), diferir=True)
it_rayita_2 = e.pieza("rayita-2", m2, pivote=(1140, 770), diferir=True)

# ---------- escudo: cuerpo + palomita ----------
CAJA_ESC = (650, 45, 850, 266)
teal = (G > R + 40) & (B > R + 30)
escudo_m = suave(rellenar(teal & (e.rect(CAJA_ESC) > 0.5)), crecer=2) * e.rect(CAJA_ESC)
palomita_m = suave(((R > 200) & (G > 200) & (B > 190)) & (escudo_m > 0.5) &
                   (e.poligono([(678, 100), (812, 78), (832, 140), (745, 232), (678, 172)]) > 0.5), crecer=2)
it_palomita = e.pieza("palomita", palomita_m, pivote=(735, 190), quitar=False, diferir=True)
# debajo de la palomita, el escudo se rellena con su color
x0, y0, x1, y1 = caja_de(palomita_m, 20)
sub = np.clip(e.img[y0:y1, x0:x1, :3], 0, 255).astype(np.uint8)
hueco = cv2.dilate((palomita_m[y0:y1, x0:x1] > 0.02).astype(np.uint8), np.ones((5, 5), np.uint8))
e.img[y0:y1, x0:x1, :3] = np.where(hueco[..., None] > 0, cv2.inpaint(sub, hueco, 7, cv2.INPAINT_TELEA),
                                    e.img[y0:y1, x0:x1, :3])
it_escudo = e.pieza("escudo", escudo_m, pivote=(745, 160), diferir=True, exclusiva=False)

# ---------- partes de la figura ----------
# cola: meneo desde la base; la unión con el lomo se queda en la figura
cola_pol = e.poligono([(1032, 636), (1066, 640), (1110, 676), (1136, 738), (1132, 804), (1104, 852), (1062, 878),
                       (1018, 884), (996, 862), (1004, 822), (1036, 792), (1048, 760), (1040, 716), (1028, 676)])
d_base = np.hypot(xx - 1022, yy - 858)
cola = cola_pol * np.clip((d_base - 26) / 30, 0, 1)
it_cola = e.pieza("cola", cola, pivote=(1022, 858), quitar=False, diferir=True)
quitar_relleno(cola, 14)

# pelo suelto de la izquierda: se mece desde arriba (borde derecho difuminado hacia el pelo de atrás)
pelo_pol = e.poligono([(150, 330), (230, 280), (300, 250), (400, 280), (400, 805), (300, 815), (150, 790), (100, 600),
                       (110, 440)])
pelo_pol *= 1 - suave(teal | ((B > G + 20) & (R > G)), crecer=3)   # sin pantalón ni suéter
pelo = pelo_pol * np.clip((380 - xx) / 40, 0, 1) * np.clip((yy - 285) / 40, 0, 1)
it_pelo = e.pieza("pelo", pelo, pivote=(320, 300), quitar=False, diferir=True)
quitar_relleno(pelo, 10, encoger=24)

# arete: péndulo desde el lóbulo
arete = disco(448, 386, 11.5)
it_arete = e.pieza("arete", arete, pivote=(447, 368), quitar=False, diferir=True)
quitar_relleno(arete, 40)

# lengua del perro (dentro de la cabeza): lengüetazos
lengua = e.poligono([(583, 408), (612, 395), (650, 396), (690, 404), (702, 425), (690, 448), (660, 462),
                     (628, 476), (600, 474), (584, 456), (580, 430)])
rosa = (R > 170) & (G < 150) & (R - G > 60)
lengua = suave(rellenar((lengua > 0.5) & cv2.dilate(rosa.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)),
               sigma=0.8)
it_lengua = e.pieza("lengua", lengua, pivote=(684, 418), quitar=False, diferir=True)
quitar_relleno(lengua, 200, radio=10)

# cabeza del perro: con la oreja grande; abajo (quijada/cuello) se difumina en el pecho
cabeza_pol = e.poligono([(612, 302), (645, 280), (690, 260), (740, 256), (790, 264), (845, 298), (902, 368),
                         (922, 450), (916, 540), (884, 566), (800, 562), (762, 524), (720, 500), (660, 498),
                         (626, 488), (600, 470), (592, 430), (600, 395), (588, 378), (584, 352), (592, 325)])
piel = (R > 220) & (G > 160) & (G < 215) & (B > 120) & (B < 185) & (yy > 530)   # mano de la chica
lado = np.clip((xx - 745) / 45, 0, 1)   # la oreja (a la derecha) no se difumina
cabeza = cabeza_pol * (np.clip((512 - yy) / 26, 0, 1) * (1 - lado) + lado)
cabeza *= 1 - suave(piel, crecer=2)
it_cabeza = e.pieza("cabeza-perro", cabeza, pivote=(655, 470), quitar=False, diferir=True, exclusiva=False)
quitar_relleno(cabeza, 32)

# figura completa (sin escudo, corazones ni rayitas)
figura = (1 - SUELTOS) * (1 - escudo_m)
it_figura = e.pieza("figura", figura, pivote=(600, 1205), diferir=True, exclusiva=False)
e.base[..., 3] = 0   # todo está en piezas: la base solo da el tamaño

# ---------- armado ----------
CORAZON_SVG = ('<svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.6 4.5c2.1 0 3.6 1.2 4.4 '
               '2.6.8-1.4 2.3-2.6 4.4-2.6 3.6 0 5.7 3.9 4.2 7.3C19.5 16.4 12 21 12 21z"/></svg>')
# corazoncitos que brotan del abrazo (detrás de todo)
BROTES = [((560, 180, 620, 240), "#FF6F61"), ((470, 120, 520, 170), "#B794F4"), ((860, 300, 915, 355), "#FF8A7A"),
          ((300, 240, 350, 290), "#FF6F61"), ((620, 110, 668, 158), "#FFB4A8"), ((900, 470, 950, 520), "#B794F4")]
for k, (c, color) in enumerate(BROTES):
    e.html(f"brote-{k + 1}", c, CORAZON_SVG, estilo=f";color:{color}")

e.grupo("abrazo", (100, 240, 1200, 1210), pivote=(600, 1205))
e.agregar(it_cola, "abrazo")
e.agregar(it_figura, "abrazo")
e.agregar(it_pelo, "abrazo")
e.agregar(it_arete, "abrazo")
e.html("rubor-1", (412, 352, 478, 392), grupo="abrazo")
e.html("rubor-2", (530, 300, 584, 336), grupo="abrazo")
e.grupo("perro", (570, 240, 930, 580), padre="abrazo", pivote=(655, 470))
e.agregar(it_cabeza, "perro")
e.agregar(it_lengua, "perro")
e.agregar(it_rayita_1)
e.agregar(it_rayita_2)

# escudo: onda detrás, escudo, palomita, brillo recortado con su forma y destellos
e.html("onda-escudo", (660, 70, 830, 250), "<i></i><i></i>")
e.grupo("escudo", (650, 45, 852, 265), pivote=(745, 250))
e.agregar(it_escudo, "escudo")
e.agregar(it_palomita, "escudo")
e.html("brillo-escudo", (650, 45, 852, 265), "<i></i>", grupo="escudo",
       estilo=";clip-path:polygon(8% 13%,47% 2%,93% 13%,88% 55%,69% 82%,43% 98%,20% 82%,7% 55%)")
for k, c in enumerate([(612, 60, 652, 100), (836, 40, 872, 76), (846, 180, 876, 210), (628, 196, 656, 224)]):
    e.html(f"destello-{k + 1}", c, '<svg viewBox="0 0 20 20"><path d="M10 0C11 7 13 9 20 10C13 11 11 13 10 20C9 13 '
                                    '7 11 0 10C7 9 9 7 10 0z"/></svg>')
for n, it in it_corazones.items():
    e.agregar(it)

e.guardar()

# ---------- CSS ----------
T = 6.4
css = f"""/* Generado por scripts/capas-landing/step-3-reunion.py — no editar a mano */
.scene-step-3-reunion{{--T:{T}s}}
/* el abrazo aprieta dos veces por ciclo */
.scene-step-3-reunion .g-abrazo{{animation:s3Abrazo var(--T) infinite}}
@keyframes s3Abrazo{{
  0%,100%{{transform:none}}
  6%{{transform:scale(1.06,.94) rotate(-1deg)}}
  10%{{transform:scale(.97,1.035) rotate(.6deg)}}
  14%{{transform:scale(1.045,.955) rotate(-.6deg)}}
  19%{{transform:scale(1) rotate(0)}}
  30%{{transform:rotate(-2deg)}}
  42%{{transform:rotate(1.8deg)}}
  50%{{transform:rotate(0)}}
  56%{{transform:scale(1.07,.93) rotate(-1.4deg)}}
  61%{{transform:scale(.97,1.04) rotate(.8deg)}}
  65%{{transform:scale(1.05,.95) rotate(-.6deg)}}
  71%{{transform:rotate(0)}}
  80%{{transform:rotate(1.8deg)}}
  90%{{transform:rotate(-1.4deg)}}
}}
/* el perro restriega la cabeza contra la chica */
.scene-step-3-reunion .g-perro{{animation:s3Perro var(--T) ease-in-out infinite}}
@keyframes s3Perro{{
  0%,100%{{transform:rotate(0)}}
  6%{{transform:rotate(-6deg) translate(-1%,-.8%)}}
  12%{{transform:rotate(4deg)}}
  18%{{transform:rotate(-5deg) translate(-.6%,0)}}
  25%{{transform:rotate(3deg)}}
  32%{{transform:rotate(-1.5deg)}}
  40%{{transform:rotate(1.5deg)}}
  48%{{transform:rotate(0)}}
  56%{{transform:rotate(-7deg) translate(-1.2%,-1%)}}
  62%{{transform:rotate(4.5deg)}}
  68%{{transform:rotate(-5deg)}}
  74%{{transform:rotate(3deg)}}
  82%{{transform:rotate(-2deg)}}
  90%{{transform:rotate(1deg)}}
}}
.scene-step-3-reunion .p-lengua{{animation:s3Lengua .9s ease-in-out infinite}}
@keyframes s3Lengua{{0%,100%{{transform:rotate(0)}}25%{{transform:rotate(9deg) scale(1.04,1.08)}}50%{{transform:rotate(-3deg)}}70%{{transform:rotate(6deg) scaleY(1.06)}}}}
/* cola a toda velocidad, con rayitas */
.scene-step-3-reunion .p-cola{{animation:s3Cola .26s ease-in-out infinite alternate}}
@keyframes s3Cola{{0%{{transform:rotate(-16deg)}}100%{{transform:rotate(12deg)}}}}
.scene-step-3-reunion .p-rayita-1,.scene-step-3-reunion .p-rayita-2{{animation:s3Rayita .52s ease-out infinite}}
.scene-step-3-reunion .p-rayita-2{{animation-delay:-.26s}}
@keyframes s3Rayita{{0%{{transform:translateX(-30%) scale(.6);opacity:0}}30%{{transform:translateX(0) scale(1.1);opacity:1}}70%{{transform:translateX(12%) scale(1);opacity:1}}100%{{transform:translateX(30%) scale(.8);opacity:0}}}}
/* pelo y arete */
.scene-step-3-reunion .p-pelo{{animation:s3Pelo 3.2s ease-in-out infinite alternate}}
@keyframes s3Pelo{{0%{{transform:rotate(2.4deg) skewY(-1.5deg)}}100%{{transform:rotate(-2.6deg) skewY(1.5deg)}}}}
.scene-step-3-reunion .p-arete{{animation:s3Arete 1.1s ease-in-out infinite alternate}}
@keyframes s3Arete{{0%{{transform:rotate(-24deg)}}100%{{transform:rotate(24deg)}}}}
/* rubor que se enciende con cada apretón */
.scene-step-3-reunion .f-rubor-1,.scene-step-3-reunion .f-rubor-2{{border-radius:50%;opacity:0;
  background:radial-gradient(closest-side,rgba(255,110,120,.55),rgba(255,110,120,0));animation:s3Rubor var(--T) infinite}}
@keyframes s3Rubor{{0%,2%,30%,50%,82%,100%{{opacity:0}}8%,20%{{opacity:1}}58%,72%{{opacity:1}}}}
/* corazoncitos que brotan y suben */
.scene-step-3-reunion [class*="f-brote-"] svg{{width:100%;height:100%;display:block;fill:currentColor}}
.scene-step-3-reunion [class*="f-brote-"]{{opacity:0;animation:s3Brote 2.6s ease-out infinite}}
.scene-step-3-reunion .f-brote-2{{animation-delay:-.45s}}
.scene-step-3-reunion .f-brote-3{{animation-delay:-.9s}}
.scene-step-3-reunion .f-brote-4{{animation-delay:-1.35s}}
.scene-step-3-reunion .f-brote-5{{animation-delay:-1.8s}}
.scene-step-3-reunion .f-brote-6{{animation-delay:-2.2s}}
@keyframes s3Brote{{
  0%{{transform:translateY(40%) scale(.2) rotate(-15deg);opacity:0}}
  15%{{transform:translateY(0) scale(1.15) rotate(8deg);opacity:1}}
  60%{{transform:translateY(-110%) scale(1) rotate(-8deg);opacity:.9}}
  100%{{transform:translateY(-200%) scale(.6) rotate(10deg);opacity:0}}
}}
/* escudo: pop con rebote, palomita que salta, onda, brillo y destellos */
.scene-step-3-reunion .g-escudo{{animation:s3Escudo var(--T) infinite}}
@keyframes s3Escudo{{
  0%,24%,100%{{transform:none}}
  28%{{transform:translateY(3%) scale(1.12,.86)}}
  33%{{transform:translateY(-12%) scale(.92,1.1) rotate(-6deg)}}
  38%{{transform:translateY(0) scale(1.14,.9) rotate(4deg)}}
  42%{{transform:scale(.96,1.04) rotate(-2deg)}}
  46%{{transform:scale(1)}}
  80%{{transform:none}}
  84%{{transform:rotate(-7deg)}}
  88%{{transform:rotate(6deg)}}
  92%{{transform:rotate(-3deg)}}
  96%{{transform:none}}
}}
.scene-step-3-reunion .p-palomita{{animation:s3Palomita var(--T) infinite}}
@keyframes s3Palomita{{
  0%,30%,100%{{transform:none}}
  33%{{transform:scale(0) rotate(-40deg)}}
  38%{{transform:scale(1.45) rotate(8deg)}}
  42%{{transform:scale(.9) rotate(-3deg)}}
  46%{{transform:scale(1.08)}}
  50%{{transform:none}}
}}
.scene-step-3-reunion .f-onda-escudo i{{position:absolute;inset:0;border-radius:50%;border:1cqw solid #33C7BE;opacity:0;animation:s3Onda var(--T) infinite}}
.scene-step-3-reunion .f-onda-escudo i+i{{animation-delay:.2s;border-color:#86E0D4}}
@keyframes s3Onda{{0%,37%{{transform:scale(.7);opacity:0}}39%{{opacity:.9}}58%,100%{{transform:scale(1.9);opacity:0}}}}
.scene-step-3-reunion .f-brillo-escudo{{overflow:hidden}}
.scene-step-3-reunion .f-brillo-escudo i{{position:absolute;top:-20%;left:-50%;width:30%;height:140%;opacity:0;
  background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.85),rgba(255,255,255,0));
  transform:translateX(0) rotate(22deg);animation:s3Brillo var(--T) infinite}}
@keyframes s3Brillo{{0%,40%{{transform:translateX(0) rotate(22deg);opacity:0}}41%{{opacity:1}}52%{{transform:translateX(560%) rotate(22deg);opacity:1}}53%,100%{{transform:translateX(560%) rotate(22deg);opacity:0}}}}
.scene-step-3-reunion [class*="f-destello-"] svg{{width:100%;height:100%;display:block;fill:#FFD166}}
.scene-step-3-reunion [class*="f-destello-"]{{opacity:0;animation:s3Destello var(--T) infinite}}
.scene-step-3-reunion .f-destello-2{{animation-delay:.12s}}
.scene-step-3-reunion .f-destello-3{{animation-delay:.24s}}
.scene-step-3-reunion .f-destello-4{{animation-delay:.36s}}
@keyframes s3Destello{{0%,37%{{transform:scale(0) rotate(0);opacity:0}}41%{{transform:scale(1.3) rotate(45deg);opacity:1}}46%{{transform:scale(.8) rotate(70deg);opacity:1}}52%,100%{{transform:scale(0) rotate(120deg);opacity:0}}}}
"""
# corazones: aparecen en secuencia, laten, flotan y truenan
for k, n in enumerate(["corazon-rojo-izq", "corazon-rojo-der", "corazon-lila-izq", "corazon-lila-der"]):
    css += (f".scene-step-3-reunion .p-{n}>img,.scene-step-3-reunion .p-{n}>.burst{{animation-duration:var(--T);"
            f"animation-delay:{-T * (0.92 - k * 0.11):.2f}s}}\n")
(SALIDA / e.nombre / "escena.css").write_text(css)
