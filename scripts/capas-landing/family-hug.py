"""Escena 'family-hug': la familia abraza al beagle; risas, apapacho, cola feliz y corazones."""
import cv2
import numpy as np

from rellenos import EscenaCapas, dilatar

e = EscenaCapas("family-hug", 780, "Familia reencontrando a su perro")
R, G, B = (e.img[..., i] for i in range(3))
turquesa = dilatar((G > R + 50) & (B > R + 40), 1)
piel = (R > 215) & (G > 140) & (G < 205) & (B > 90) & (B < 170)


def poli(pts):
    return e.poligono(pts) > 0.5


def cerrar(m, r=3):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return dilatar(cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0, 1)


# ---------- corazones y rayita de la cola (sueltos) ----------
corazones = []
for i, (caja, pivote, estilo) in enumerate((
        ((300, 165, 392, 258), (346, 250), "--dur:4.2s;--delay:-.3s"),
        ((236, 260, 326, 352), (281, 344), "--dur:4.8s;--delay:-2.4s"),
        ((178, 442, 248, 512), (213, 508), "--dur:4.4s;--delay:-1.3s"),
        ((1116, 182, 1198, 264), (1157, 258), "--dur:4.6s;--delay:-3.4s"),
        ((1198, 248, 1280, 326), (1239, 322), "--dur:5s;--delay:-.9s"))):
    corazones.append(e.capa(f"corazon-{i + 1}", e.islas(e.rect(caja)), pivote=pivote, clases="a-pop", estilo=estilo))
it_rayita = e.capa("rayita-cola", e.islas(e.rect((200, 510, 280, 620))), pivote=(268, 600))

# ---------- cola: sale de detrás del pantalón de mamá ----------
borde_pantalon = [(318, 664), (312, 680), (306, 696), (300, 712), (296, 730)]
z_tapa_cola = poli([(318, 650), (350, 650), (350, 745), (292, 745)] + borde_pantalon[::-1][:-1]) & ~turquesa
m_cola = poli([(292, 532), (334, 596), (334, 650)] + borde_pantalon + [(266, 728), (236, 690), (224, 640),
                                                                      (228, 588), (250, 548)])
it_cola = e.capa("cola", m_cola, pivote=(306, 706), colchon=(dilatar(z_tapa_cola, 2), 22))
it_tapa_cola = e.tapa("tapa-cola", z_tapa_cola)

# ---------- plantas (las de los lados quedan detrás de los tenis) ----------
z_tenis_mama = poli([(150, 770), (240, 750), (300, 770), (310, 930), (150, 930)]) & ~turquesa
z_tenis_papa = poli([(1282, 740), (1372, 740), (1404, 790), (1406, 940), (1282, 940)]) & ~turquesa
m_planta_izq = turquesa & poli([(30, 630), (300, 630), (300, 870), (282, 908), (30, 908)])
m_planta_der = turquesa & poli([(1355, 640), (1500, 640), (1500, 910), (1355, 910)])
it_planta_izq = e.capa("planta-izq", m_planta_izq, pivote=(150, 900), colchon=(z_tenis_mama, 18),
                       clases="a-sway", estilo="--dur:4.2s")
it_planta_der = e.capa("planta-der", m_planta_der, pivote=(1420, 900), colchon=(z_tenis_papa, 18),
                       clases="a-sway", estilo="--dur:3.8s;--delay:-1.7s")
it_tapa_mama = e.tapa("tapa-tenis-mama", z_tenis_mama & dilatar(m_planta_izq, 26))
it_tapa_papa = e.tapa("tapa-tenis-papa", z_tenis_papa & dilatar(m_planta_der, 26))
brotes = []
for i, (caja, pivote, estilo) in enumerate((
        ((390, 872, 495, 945), (442, 940), "--dur:3.2s;--delay:-.6s"),
        ((752, 888, 820, 945), (786, 940), "--dur:2.8s;--delay:-1.9s"),
        ((1145, 872, 1250, 950), (1197, 946), "--dur:3.4s;--delay:-1.1s"))):
    brotes.append(e.capa(f"brote-{i + 1}", turquesa & poli([(caja[0], caja[1]), (caja[2], caja[1]),
                                                            (caja[2], caja[3]), (caja[0], caja[3])]),
                         pivote=pivote, alcance=14, clases="a-sway", estilo=estilo))

# ---------- manos que apapachan ----------
m_mano_mama = cerrar(piel & poli([(606, 598), (700, 590), (772, 610), (778, 690), (700, 700), (612, 690)]), 2) \
    & poli([(600, 592), (780, 592), (782, 700), (600, 700)])
it_mano_mama = e.capa("mano-mama", m_mano_mama, pivote=(612, 650), alcance=30)
m_mano_papa = cerrar(piel & poli([(890, 600), (1060, 596), (1112, 640), (1112, 750), (890, 750)]), 2) \
    & poli([(886, 594), (1116, 594), (1116, 752), (886, 752)])
it_mano_papa = e.capa("mano-papa", m_mano_papa, pivote=(1100, 680), alcance=30)

# ---------- cabezas (de adelante hacia atrás: niño, perro, mamá, papá) ----------
m_nino = poli([(826, 380), (868, 334), (950, 326), (1040, 366), (1084, 430), (1080, 505), (1052, 545),
               (1000, 562), (940, 566), (880, 552), (846, 505), (832, 450)]) & ~turquesa
it_nino = e.capa("cabeza-nino", m_nino, pivote=(955, 560), alcance=40)

m_oreja = poli([(660, 362), (672, 362), (686, 372), (690, 400), (700, 440), (712, 480), (716, 510), (706, 536),
                (680, 550), (650, 546), (620, 526), (607, 490), (614, 450), (640, 395)])
m_lengua = cerrar((R > 225) & (G > 95) & (G < 160) & (B > 70) & (B < 140)
                  & poli([(780, 410), (850, 410), (850, 480), (780, 480)]), 1)
collar = cerrar((R > 200) & (G > 80) & (G < 140) & (B < 120) & poli([(700, 482), (850, 482), (850, 540), (700, 540)]), 1)
m_perro = poli([(688, 330), (718, 292), (790, 282), (850, 298), (878, 330), (880, 380), (872, 420), (852, 480),
                (836, 504), (790, 512), (740, 508), (712, 498), (700, 440), (688, 390)]) & ~collar
it_oreja = e.capa("oreja-perro", m_oreja, pivote=(668, 372), alcance=34)
it_lengua = e.capa("lengua", m_lengua, pivote=(812, 425))
it_perro = e.capa("cabeza-perro", m_perro, pivote=(785, 505), alcance=40,
                  colchon=((dilatar(m_nino, 2) | m_lengua | m_oreja), 22))

m_mama = e.poligono([(420, 210), (450, 150), (520, 98), (600, 92), (680, 116), (726, 150), (740, 200), (748, 262), (724, 300),
                     (706, 326), (694, 392), (656, 424), (600, 434), (556, 428), (496, 412), (438, 382),
                     (396, 330), (378, 278)])
it_mama = e.capa("cabeza-mama", m_mama, pivote=(596, 432), alcance=40,
                 colchon=(dilatar(m_perro | m_oreja, 2), 24))
m_papa = e.poligono([(745, 245), (714, 200), (708, 110), (758, 30), (860, 12), (962, 26), (1022, 78), (1052, 150), (1050, 232),
                     (1012, 282), (990, 322), (940, 350), (880, 350), (848, 332), (800, 300), (770, 270)])
it_papa = e.capa("cabeza-papa", m_papa, pivote=(928, 342), alcance=40,
                 colchon=(dilatar(m_perro | m_nino, 2), 24))

# ---------- apilado ----------
for it in (it_papa, it_mama, it_planta_izq, it_planta_der, it_tapa_mama, it_tapa_papa, *brotes, it_cola,
           it_tapa_cola, it_rayita):
    e.agregar(it)
e.grupo("cabeza-perro", (600, 280, 884, 552), pivote=(785, 505))
for it in (it_perro, it_lengua, it_oreja):
    e.agregar(it, "cabeza-perro")
for it in (it_nino, it_mano_mama, it_mano_papa, *corazones):
    e.agregar(it)
e.html("corazones", (560, 120, 1100, 560), "<i></i>" * 6)

e.guardar()
