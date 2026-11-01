"""Escena 'hero': la chica le toma una foto al perrito con la app; flash, el perrito brinca de gusto."""
import cv2
import numpy as np

from capas import SALIDA
from rellenos import EscenaCapas, dilatar

e = EscenaCapas("hero", 1000, "Chica encontrando a su perro con la app")
R, G, B = (e.img[..., i] for i in range(3))
turquesa = dilatar((G > R + 60) & (B > R + 40), 1)
cafe_oscuro = (R < 165) & (G < 105) & (R > B)
pelo = (R - B > 10) & (np.maximum(np.maximum(R, G), B) < 125)
oscuro = np.maximum(np.maximum(R, G), B) < 75


def erosionar(m, r):
    return cv2.erode(m.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0


def cerrar(m, r=2):
    """Cierra la máscara de color y la engorda 1 px para llevarse el borde mezclado."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return dilatar(cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0, 1)


def poli(pts):
    return e.poligono(pts) > 0.5


# ---------- decoraciones sueltas ----------
it_rayas_lila = e.capa("rayitas-lila", e.islas(e.rect((515, 170, 660, 300))), pivote=(590, 300),
                       clases="a-flash", estilo="--dur:2.4s;--delay:-.4s")
it_rayas_rojas = e.capa("rayitas-rojas", e.islas(e.rect((745, 575, 875, 700))), pivote=(812, 702))
it_ondas = e.capa("ondas-cola", e.islas(e.rect((1020, 875, 1115, 975))), pivote=(1020, 960))

# ---------- perrito ----------
caja_perro = (700, 686, 1100, 1250)
# los dedos de la chica asoman dentro de la caja del perrito: se separan por color (la oreja es café)
zona_manos = poli([(598, 558), (734, 562), (746, 640), (744, 724), (730, 776), (708, 812), (686, 820),
                   (640, 812), (603, 797), (566, 790), (538, 772), (552, 748), (572, 728), (578, 700),
                   (592, 676), (596, 640)])
oreja_en_manos = zona_manos & cafe_oscuro & (e.rect((700, 680, 760, 830)) > 0.5)
perro = ((e.rect(caja_perro) > 0.5) & ~turquesa & ~(zona_manos & ~oreja_en_manos)).astype(np.float32)
m_planta_der = turquesa * (e.rect((1025, 1115, 1122, 1262)) > 0.5)
m_placa = perro * dilatar((R > 215) & (G > 120) & (G < 205) & (B < 110) & (e.rect((785, 912, 875, 1000)) > 0.5), 1)
m_lengua = perro * dilatar((R > 225) & (G > 100) & (G < 175) & (B > 90) & (B < 160)
                           & poli([(795, 835), (870, 835), (870, 905), (795, 905)]), 1)
m_oreja_izq = perro * cerrar(cafe_oscuro) * poli([(700, 735), (760, 706), (802, 700), (812, 722), (797, 750), (786, 790),
                                          (780, 835), (752, 858), (700, 858)])
m_oreja_der = perro * cerrar(cafe_oscuro) * poli([(936, 745), (990, 742), (1046, 800), (1046, 915), (958, 915), (948, 860),
                                          (940, 800)])
# la cabeza baja hasta el borde del collar (sin llevarse el rojo) para no dejar cachitos de cachete en el cuerpo
collar = cerrar((R > 150) & (G < 105) & (B < 95) & poli([(770, 885), (965, 885), (965, 960), (770, 960)]), 1)
m_cabeza = perro * poli([(700, 686), (1046, 686), (1046, 918), (700, 918)]) * ~collar
m_cola = perro * poli([(985, 925), (1050, 940), (1095, 990), (1098, 1065), (1080, 1115), (1052, 1146), (1028, 1150),
                       (1018, 1110), (1014, 1062), (1011, 1012), (999, 978), (982, 948)])

it_planta_der = e.capa("planta-der", m_planta_der, pivote=(1075, 1250), alcance=0,
                       clases="a-sway", estilo="--dur:3.6s;--delay:-1.2s")
it_placa = e.capa("placa", m_placa, pivote=(829, 922))
it_lengua = e.capa("lengua", m_lengua, pivote=(835, 848))
it_oreja_izq = e.capa("oreja-izq", m_oreja_izq, pivote=(785, 718))
it_oreja_der = e.capa("oreja-der", m_oreja_der, pivote=(958, 760))
ojo_p1 = oscuro & (e.elipse((816, 753, 855, 792)) > 0.5)
ojo_p2 = oscuro & (e.elipse((894, 782, 931, 824)) > 0.5)


def ojos_perro(d, s):
    tinta = (52, 34, 28, 255)
    for (x0, y, x1, h) in ((820, 770, 852, 9), (896, 802, 928, 9)):
        d.arc([x0 * s, (y - h) * s, x1 * s, (y + h) * s], 15, 165, fill=tinta, width=round(5 * s))


it_ojos_perro = e.parpadeo("ojos-perro", ojo_p1 | ojo_p2, ojos_perro, borde=3)
it_cabeza_perro = e.capa("cabeza-perro", m_cabeza, pivote=(870, 900),
                         # debajo de las orejas la cara sigue redonda (óvalo), no hasta donde llegaba la oreja
                         colchon=((((m_oreja_izq > .5) | (m_oreja_der > .5)) & (e.elipse((758, 698, 988, 908)) > .5))
                                  | (m_lengua > .5), 26))
it_cola = e.capa("cola", m_cola, pivote=(1040, 1140))
# el cuerpo se extiende debajo del cuello, la cola, la placa y la planta (no debajo de las orejas: ahí va el fondo)
orejas = (m_oreja_der > .5) | (m_oreja_izq > .5)
cuello = e.elipse((772, 838, 972, 962)) > .5
tapado_cuerpo = ((m_cabeza > .5) & ~dilatar(orejas, 3) & cuello) | (m_cola > .5) | (m_placa > .5) | (m_planta_der > .5)
it_cuerpo = e.capa("cuerpo-perro", perro, pivote=(880, 1248), colchon=(tapado_cuerpo, 34))
m_planta_centro = turquesa & poli([(546, 1062), (600, 1012), (652, 960), (700, 940), (848, 940), (848, 1262),
                                   (540, 1262)])
it_planta_centro = e.capa("planta-centro", m_planta_centro, pivote=(650, 1250), colchon=(e.rect(caja_perro) > 0.5, 26),
                          clases="a-sway", estilo="--dur:4.4s")

# ---------- chica (de adelante hacia atrás, para que cada relleno use lo que está detrás) ----------
m_planta_izq = turquesa * e.poligono([(28, 1030), (104, 1030), (132, 1062), (166, 1092), (208, 1103),
                                      (292, 1104), (322, 1140), (322, 1262), (28, 1262)])
it_planta_izq = e.capa("planta-izq", m_planta_izq, pivote=(150, 1250), alcance=26,
                       clases="a-sway", estilo="--dur:4s;--delay:-2.1s")
naranja = (R > 190) & (G > 70) & (G < 150) & (B < 120)
m_mochila = dilatar(naranja & poli([(20, 880), (52, 772), (100, 706), (176, 680), (238, 690), (262, 722),
                                    (254, 800), (246, 884), (214, 958), (150, 966), (40, 958)]), 1)
it_mochila = e.capa("mochila", m_mochila, pivote=(205, 692), alcance=30)
m_manos = zona_manos & ~oreja_en_manos & ~(erosionar(pelo, 1) & ~poli([(600, 560), (735, 560), (735, 740),
                                                                        (600, 740)]))
# el relleno debajo de las manos solo hacia el antebrazo y el pelo (a la derecha está el fondo)
it_manos = e.capa("manos", m_manos, pivote=(600, 792), alcance=34,
                  donde=poli([(520, 540), (606, 540), (606, 745), (740, 745), (740, 830), (520, 830)]))
m_arete = dilatar((R > 210) & (G > 130) & (G < 210) & (B < 100) & (e.rect((380, 490, 425, 545)) > 0.5), 1)
it_arete = e.capa("arete", m_arete, pivote=(402, 503), alcance=8)
ojo_chica = (np.maximum(np.maximum(R, G), B) < 120) & poli([(496, 482), (530, 482), (563, 490), (566, 508), (555, 538),
                                                              (508, 538), (496, 505)])


def ojo_cerrado(d, s):
    tinta = (40, 27, 24, 255)
    pts = [(503 + 56 * t, 497 + 26 * t * (1 - t) * 2 - 2 * t) for t in np.linspace(0, 1, 24)]
    d.line([(x * s, y * s) for x, y in pts], fill=tinta, width=round(6 * s), joint="curve")
    d.line([(556 * s, 495 * s), (566 * s, 489 * s)], fill=tinta, width=round(4 * s))  # pestaña


it_ojo_chica = e.parpadeo("ojo-chica", ojo_chica, ojo_cerrado, borde=3)
m_cabeza_chica = e.poligono([(196, 548), (212, 470), (300, 330), (380, 252), (470, 232), (560, 246),
                             (640, 296), (694, 380), (704, 470), (686, 556), (650, 598), (606, 610),
                             (562, 614), (522, 626), (470, 620), (404, 592), (330, 568)])
it_cabeza_chica = e.capa("cabeza-chica", m_cabeza_chica, pivote=(480, 616), alcance=34,
                         colchon=(m_arete > .3, 8))
m_puntas = pelo * e.poligono([(50, 770), (62, 700), (104, 618), (166, 560), (200, 540), (236, 552),
                              (240, 590), (214, 622), (192, 646), (160, 694), (128, 742), (108, 772)])
it_puntas = e.capa("pelo-puntas", m_puntas, pivote=(228, 560), alcance=24)

# lo que quede del perrito en la base (bordes sueltos) se borra: el perrito entero se mueve
limpiar = (e.rect((740, 686, 1122, 1262)) > 0.5) | (e.rect((700, 822, 740, 1262)) > 0.5)
e.base[..., 3] = np.where(limpiar, 0, e.base[..., 3])

# ---------- apilado ----------
e.agregar(it_planta_centro)
e.agregar(it_puntas)
e.agregar(it_mochila)
e.grupo("cabeza-chica", (196, 232, 704, 626), pivote=(480, 616))
for it in (it_cabeza_chica, it_arete, it_ojo_chica):
    e.agregar(it, "cabeza-chica")
e.grupo("manos", (530, 556, 736, 818), pivote=(600, 792))
e.agregar(it_manos, "manos")
e.html("flash", (602, 530, 722, 650), "<i></i><i></i>", grupo="manos")
e.grupo("perro", caja_perro, pivote=(880, 1248))
for it in (it_cuerpo, it_cola, it_placa):
    e.agregar(it, "perro")
e.grupo("cabeza-perro", (700, 686, 1046, 916), padre="perro", pivote=(870, 900))
for it in (it_cabeza_perro, it_lengua, it_ojos_perro, it_oreja_izq, it_oreja_der):
    e.agregar(it, "cabeza-perro")
e.agregar(it_planta_der)
e.agregar(it_planta_izq)
e.agregar(it_rayas_lila)
e.agregar(it_rayas_rojas)
e.agregar(it_ondas)

# ---------- efectos ----------
e.html("enfoque", (722, 676, 1052, 930), "<i></i><i></i>")
e.html("destello", (0, 0, e.W, e.H))
e.html("corazon", (930, 600, 1010, 680),
       '<svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.6 4.5c2.1 0 3.6 1.2 4.4 2.6.8-1.4 '
       '2.3-2.6 4.4-2.6 3.6 0 5.7 3.9 4.2 7.3C19.5 16.4 12 21 12 21z"/></svg>')
e.html("chispas", (690, 640, 1080, 960), "<i></i>" * 4)

e.guardar()

# la base del hero está arriba del pliegue: se pide con prioridad y sin lazy
ruta = SALIDA / "hero" / "escena.html"
html = ruta.read_text()
linea_base = next(l for l in html.splitlines() if 'class="scene-base"' in l)
html = html.replace(linea_base, linea_base.replace('loading="lazy"', 'fetchpriority="high"'))
ruta.write_text(html)
