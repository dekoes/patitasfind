"""Escena 'swipe': la tarjeta de Luna se desliza a la derecha (adoptar) como en Tinder."""
import numpy as np

from capas import Escena, capa_vacia, componer, dibujar

e = Escena("swipe", 1000, "Perfil de Luna lista para adoptar: desliza a la derecha para adoptar")

# ---------- decoraciones exteriores ----------
e.pieza("corazon-arriba", e.por_color(e.rect((840, 45, 920, 130))), pivote=(880, 125),
        clases="a-pop", estilo="--dur:4.6s;--delay:-.4s")
e.pieza("corazon-durazno", e.por_color(e.rect((105, 995, 190, 1085))), pivote=(147, 1080),
        clases="a-pop", estilo="--dur:5.2s;--delay:-2.6s")
e.pieza("rayitas-cafe", e.por_color(e.rect((885, 115, 945, 180))), pivote=(882, 112),
        clases="a-flash", estilo="--dur:2.3s;--delay:-.3s")
e.pieza("rayitas-lila", e.por_color(e.rect((70, 495, 160, 585))), pivote=(162, 588),
        clases="a-flash", estilo="--dur:2.6s;--delay:-1.1s")
e.pieza("rayitas-naranja", e.por_color(e.rect((55, 830, 110, 905))), pivote=(118, 850),
        clases="a-flash", estilo="--dur:2.1s;--delay:-.6s")
e.pieza("rayitas-teal", e.por_color(e.rect((995, 620, 1075, 700))), pivote=(990, 702),
        clases="a-flash", estilo="--dur:2.4s;--delay:-1.7s")
e.pieza("rayitas-teal2", e.por_color(e.rect((950, 1070, 1015, 1140))), pivote=(948, 1140),
        clases="a-flash", estilo="--dur:2.8s;--delay:-.9s")
e.pieza("planta-izq", e.por_color(e.rect((105, 1055, 282, 1262)), umbral=30), pivote=(200, 1256), no_mezclar=e.oscuro(),
        clases="a-sway", estilo="--dur:4.4s")
e.pieza("planta-der", e.por_color(e.rect((846, 1055, 1010, 1262)), umbral=30), pivote=(925, 1256), no_mezclar=e.oscuro(),
        clases="a-sway", estilo="--dur:5s;--delay:-1.8s")
# flechas: solo la parte fuera del marco del teléfono; se estiran desde su cola
e.pieza("flecha-izq", e.por_color(e.rect((150, 625, 281, 695))), pivote=(281, 656))
e.pieza("flecha-der", e.por_color(e.rect((846, 625, 975, 690))), pivote=(846, 655))
e.pieza("boton-x", e.elipse((90, 699.5, 250, 859.5)), pivote=(170, 779.5), suave=False)
e.pieza("boton-corazon", e.elipse((873.5, 699.5, 1032.5, 858.5)), pivote=(953, 779), suave=False)
e.html("onda-corazon", (873.5, 699.5, 1032.5, 858.5), '<i></i><i></i>')
e.pieza("huella-header", e.por_color(e.rect((522, 378, 598, 442))), pivote=(560, 440))

# ---------- tarjeta de Luna ----------
esquinas = [(398, 452.6), (805, 497.7), (753, 1102), (335, 1068)]
cola = e.por_color(e.poligono([(660, 664), (674, 662), (692, 675), (708, 694), (717, 722), (718, 750), (712, 768),
                               (701, 781), (689, 792), (674, 798), (662, 798), (663, 764), (674, 746), (682, 728),
                               (683, 708), (678, 690), (667, 677), (658, 671)]), fondo=(255, 255, 255), umbral=14)
# las hojas de la planta que quedan dentro del polígono se quedan en la tarjeta
r, g, b = (e.img[..., i] for i in range(3))
cola *= ~((g > r + 25) & (b > r))
it_cola = e.pieza("cola", cola, pivote=(668, 786), diferir=True)
it_rayas_cola = e.pieza("rayas-cola", e.por_color(e.rect((690, 658, 730, 698))), pivote=(690, 699), diferir=True,
                        clases="a-flash", estilo="--dur:.9s")
it_rayas_cara = e.pieza("rayas-cara", e.por_color(e.rect((408, 535, 470, 645))), pivote=(472, 592), diferir=True,
                        clases="a-flash", estilo="--dur:1.6s;--delay:-.5s")

# la tarjeta se toma de la base (ya sin cola ni rayitas) y lleva su propia sombra
tarjeta_m = e.cuadrilatero_redondeado(esquinas, 22)
tarjeta = e.base.copy()
tarjeta[..., 3] = tarjeta_m * 255
sombra = capa_vacia(e)
sombra[..., :3] = (40, 34, 30)
desplazada = np.roll(tarjeta_m, 7, axis=0)
import cv2  # noqa: E402

sombra[..., 3] = cv2.GaussianBlur(desplazada, (0, 0), 9) * 60
tarjeta = componer(sombra, tarjeta)

pantalla = (305, 330, 822, 1270)
e.grupo("pantalla", pantalla, radio=58, clase="clip")
caja_t = (318, 436, 812, 1124)
e.grupo("tarjeta", caja_t, padre="pantalla")
e.pieza_desde("tarjeta", tarjeta, grupo="tarjeta")
for it in (it_cola, it_rayas_cola, it_rayas_cara):
    it["grupo"] = "tarjeta"
    e.agregar(it)
e.html("sello", (408, 478, 640, 560), "¡Adoptar!", grupo="tarjeta")
e.html("sello-no", (590, 500, 790, 580), "Paso", grupo="tarjeta")

# ---------- pila de tarjetas debajo (se dibuja de nuevo, limpia) ----------
FONDO = (250, 248, 245)


def pila(d, s):
    d.rectangle([v * s for v in (318, 440, 812, 1121)], fill=FONDO + (255,))


def sombras(d, s):
    for caja in ((372, 466, 785, 1084), (340, 492, 766, 1100)):
        d.rounded_rectangle([v * s for v in caja], radius=24 * s, fill=(70, 55, 45, 70))


def cartas(d, s):
    d.rounded_rectangle([v * s for v in (372, 462, 785, 1080)], radius=24 * s, fill=(251, 250, 249, 255),
                        outline=(232, 228, 223, 255), width=round(1.5 * s))
    d.rounded_rectangle([v * s for v in (340, 487, 766, 1094)], radius=24 * s, fill=(253, 252, 252, 255),
                        outline=(229, 225, 220, 255), width=round(1.5 * s))


e.pintar(componer(dibujar(e, pila), dibujar(e, sombras, desenfoque=7), dibujar(e, cartas)))

# ---------- capas de efectos ----------
e.html("corazon-nav", (597, 1157, 644, 1207),
       '<svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.6 4.5c2.1 0 3.6 1.2 4.4 2.6.8-1.4 '
       '2.3-2.6 4.4-2.6 3.6 0 5.7 3.9 4.2 7.3C19.5 16.4 12 21 12 21z"/></svg>')
e.html("lluvia", (840, 560, 1080, 860), "<i></i>" * 6)

e.guardar()
