"""Descompone las ilustraciones de la landing en capas animables.

Cada escena toma la ilustración original (PNG del commit d08f78a), recorta los
elementos que se van a animar como piezas con transparencia, reconstruye lo que
había debajo en la imagen base y escribe:

  app/img/anim/<escena>/base.webp y una .webp por pieza
  app/img/anim/<escena>/escena.html  (marcado listo para pegar en landing.html)

Requisitos: numpy, pillow, opencv-python-headless (no son dependencias de la app).
Uso: python scripts/capas-landing/<escena>.py
"""
import io
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parents[2]
COMMIT_ORIGINALES = "d08f78a"
SALIDA = REPO / "app" / "img" / "anim"
SS = 4  # supersampling para máscaras geométricas


def fuente(nombre):
    datos = subprocess.check_output(["git", "-C", str(REPO), "show", f"{COMMIT_ORIGINALES}:app/img/{nombre}.png"])
    return Image.open(io.BytesIO(datos)).convert("RGBA")


def pct(v, total):
    return f"{v / total * 100:.3f}".rstrip("0").rstrip(".") + "%"


class Escena:
    def __init__(self, nombre, ancho_salida, alt, calidad=86):
        self.nombre = nombre
        self.alt = alt
        self.calidad = calidad
        self.img = np.asarray(fuente(nombre)).astype(np.float32)
        self.H, self.W = self.img.shape[:2]
        self.opaca = self.img[..., 3].min() > 250
        self.base = self.img.copy()
        self.escala = ancho_salida / self.W
        self.tomado = np.zeros((self.H, self.W), np.float32)  # lo ya recortado no entra en otra pieza
        self.items = []  # piezas, grupos y capas html en orden de apilado
        self.grupos = {}
        (SALIDA / nombre).mkdir(parents=True, exist_ok=True)

    # ---------- máscaras ----------
    def _lienzo(self):
        return Image.new("L", (self.W * SS, self.H * SS), 0)

    def _reducir(self, lienzo):
        return np.asarray(lienzo.resize((self.W, self.H), Image.LANCZOS)).astype(np.float32) / 255

    def poligono(self, pts):
        c = self._lienzo()
        ImageDraw.Draw(c).polygon([(x * SS, y * SS) for x, y in pts], fill=255)
        return self._reducir(c)

    def elipse(self, caja):
        c = self._lienzo()
        ImageDraw.Draw(c).ellipse([v * SS for v in caja], fill=255)
        return self._reducir(c)

    def rect(self, caja, radio=0):
        c = self._lienzo()
        ImageDraw.Draw(c).rounded_rectangle([v * SS for v in caja], radius=radio * SS, fill=255)
        return self._reducir(c)

    def cuadrilatero_redondeado(self, esquinas, radio):
        """Polígono convexo con esquinas redondeadas (esquinas en orden horario)."""
        pts = []
        n = len(esquinas)
        for i in range(n):
            p0, p1, p2 = (np.array(esquinas[(i - 1) % n], float), np.array(esquinas[i], float),
                          np.array(esquinas[(i + 1) % n], float))
            a = (p0 - p1) / np.linalg.norm(p0 - p1)
            b = (p2 - p1) / np.linalg.norm(p2 - p1)
            ini, fin = p1 + a * radio, p1 + b * radio
            for t in np.linspace(0, 1, 12):  # bezier cuadrática como arco
                pts.append(tuple((1 - t) ** 2 * ini + 2 * (1 - t) * t * p1 + t ** 2 * fin))
        return self.poligono(pts)

    def oscuro(self, umbral=90):
        """Píxeles muy oscuros (contornos, marco del teléfono) para que el relleno no los arrastre."""
        return self.img[..., :3].max(axis=2) < umbral

    def por_alfa(self, region):
        """Para ilustraciones con fondo transparente: alfa original dentro de la región."""
        return (self.img[..., 3] / 255) * region

    def por_color(self, region, umbral=22, fondo=None, min_area=12, rellenar_huecos=True):
        """Píxeles de la región que se separan del color de fondo (mediana del borde de la región)."""
        ys, xs = np.nonzero(region > 0.5)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgb = self.img[..., :3]
        if fondo is None:
            borde = np.concatenate([rgb[y0, x0:x1], rgb[y1 - 1, x0:x1], rgb[y0:y1, x0], rgb[y0:y1, x1 - 1]])
            fondo = np.median(borde, axis=0)
        dif = np.abs(rgb - np.array(fondo, np.float32)).max(axis=2)
        duro = ((dif > umbral) & (region > 0.5)).astype(np.uint8)
        n, etiquetas, stats, _ = cv2.connectedComponentsWithStats(duro, 8)
        limpio = np.zeros_like(duro)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                limpio[etiquetas == i] = 1
        if rellenar_huecos:
            limpio = rellenar(limpio)
        return limpio.astype(np.float32)

    # ---------- piezas ----------
    def pieza(self, nombre, mascara, pivote=None, grupo=None, quitar=True, suave=True, umbral_alfa=(6, 70),
              clases="", estilo="", extra="", diferir=False, no_mezclar=None, exclusiva=True):
        """Recorta una pieza. `mascara` es 0..1; en imágenes opacas se suaviza el borde contra el fondo
        reconstruido para que no arrastre halo al moverse. Con `diferir` no se agrega todavía al marcado
        (sirve para recortarla antes que otra pieza que la contiene y apilarla después)."""
        m = np.clip(mascara, 0, 1).astype(np.float32)
        if exclusiva:
            m *= 1 - self.tomado
        self.tomado = np.maximum(self.tomado, (m > 0.5).astype(np.float32))
        if quitar:
            self._quitar(m, no_mezclar)
        capa = self.img.copy()
        if self.opaca and suave:
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
        else:
            capa[..., 3] = self.img[..., 3] * m
        return self.pieza_desde(nombre, capa, pivote, grupo, clases, estilo, extra, diferir)

    def pieza_desde(self, nombre, capa, pivote=None, grupo=None, clases="", estilo="", extra="", diferir=False):
        """Pieza a partir de una capa RGBA float en coordenadas de la imagen (recortada o dibujada a mano)."""
        a = capa[..., 3]
        ys, xs = np.nonzero(a > 2)
        if not len(xs):
            raise ValueError(f"pieza vacía: {nombre}")
        x0, y0 = max(0, xs.min() - 2), max(0, ys.min() - 2)
        x1, y1 = min(self.W, xs.max() + 3), min(self.H, ys.max() + 3)
        recorte = Image.fromarray(np.clip(capa[y0:y1, x0:x1], 0, 255).astype(np.uint8), "RGBA")
        w, h = max(1, round((x1 - x0) * self.escala)), max(1, round((y1 - y0) * self.escala))
        recorte.resize((w, h), Image.LANCZOS).save(SALIDA / self.nombre / f"{nombre}.webp", "WEBP",
                                                   quality=self.calidad, method=6, alpha_quality=90)
        if pivote is None:
            pivote = ((x0 + x1) / 2, (y0 + y1) / 2)
        if "a-pop" in clases.split():
            extra = '<i class="burst"></i>' + extra
        it = dict(tipo="pieza", nombre=nombre, caja=(x0, y0, x1, y1), px=(w, h), pivote=pivote, grupo=grupo,
                  clases=clases, estilo=estilo, extra=extra)
        if not diferir:
            self.items.append(it)
        return it

    def agregar(self, it, grupo=None):
        if grupo:
            it["grupo"] = grupo
        self.items.append(it)

    def grupo(self, nombre, caja, radio=None, clase="", padre=None, pivote=None, estilo=""):
        """Contenedor para animar varias piezas juntas (con clase "clip" recorta lo que sale de él)."""
        self.grupos[nombre] = dict(caja=caja, padre=padre)
        self.items.append(dict(tipo="grupo", nombre=nombre, caja=caja, radio=radio, clase=clase, grupo=padre,
                               pivote=pivote, estilo=estilo))

    def html(self, nombre, caja, contenido="", grupo=None, etiqueta="span", clases="", estilo=""):
        """Capa HTML (destellos, sellos, contadores...) posicionada en coordenadas de la imagen."""
        self.items.append(dict(tipo="html", nombre=nombre, caja=caja, contenido=contenido, grupo=grupo,
                               etiqueta=etiqueta, clases=clases, estilo=estilo))

    # ---------- fondo ----------
    def _quitar(self, m, no_mezclar=None):
        duro = (m > 0.02).astype(np.uint8)
        if self.opaca:
            hueco = cv2.dilate(duro, np.ones((7, 7), np.uint8))
            desconocido = hueco.copy()
            if no_mezclar is not None:  # esos píxeles no alimentan el relleno, pero se conservan
                malos = cv2.dilate(no_mezclar.astype(np.uint8), np.ones((5, 5), np.uint8))
                desconocido |= malos
                hueco &= 1 - no_mezclar.astype(np.uint8)
            rgb = np.clip(self.base[..., :3], 0, 255).astype(np.uint8)
            rellenado = cv2.inpaint(rgb, desconocido, 9, cv2.INPAINT_TELEA).astype(np.float32)
            self.base[..., :3] = np.where(hueco[..., None] > 0, rellenado, self.base[..., :3])
        else:
            self.base[..., 3] *= (1 - m)
            self.base[..., 3] = np.where(m > 0.9, 0, self.base[..., 3])

    def pintar(self, capa_rgba):
        """Compone (encima de la base) una capa dibujada a mano para reconstruir lo tapado."""
        a = capa_rgba[..., 3:4] / 255
        self.base[..., :3] = capa_rgba[..., :3] * a + self.base[..., :3] * (1 - a)
        self.base[..., 3] = np.maximum(self.base[..., 3], capa_rgba[..., 3])

    # ---------- salida ----------
    def _pos(self, caja, grupo):
        x0, y0, x1, y1 = caja
        if grupo:
            gx0, gy0, gx1, gy1 = self.grupos[grupo]["caja"]
            return (pct(x0 - gx0, gx1 - gx0), pct(y0 - gy0, gy1 - gy0), pct(x1 - x0, gx1 - gx0),
                    pct(y1 - y0, gy1 - gy0))
        return pct(x0, self.W), pct(y0, self.H), pct(x1 - x0, self.W), pct(y1 - y0, self.H)

    def _cadena(self, grupo):
        cadena = []
        while grupo:
            cadena.insert(0, grupo)
            grupo = self.grupos[grupo]["padre"]
        return cadena

    def guardar(self, clase_extra=""):
        base = Image.fromarray(np.clip(self.base, 0, 255).astype(np.uint8), "RGBA")
        if self.opaca:
            base = base.convert("RGB")
        bw, bh = round(self.W * self.escala), round(self.H * self.escala)
        base.resize((bw, bh), Image.LANCZOS).save(SALIDA / self.nombre / "base.webp", "WEBP",
                                                  quality=self.calidad, method=6, alpha_quality=90)
        ruta = f"img/anim/{self.nombre}"
        clases = f"scene scene-{self.nombre}" + (f" {clase_extra}" if clase_extra else "")
        lineas = [f'<div class="{clases}" data-scene="{self.nombre}">',
                  f'  <img class="scene-base" src="{ruta}/base.webp" alt="{self.alt}" width="{bw}" height="{bh}" '
                  f'loading="lazy" decoding="async">']
        abiertos = []

        def ir_a(grupo):
            cadena = self._cadena(grupo)
            while abiertos and abiertos != cadena[:len(abiertos)]:
                abiertos.pop()
                lineas.append("  " * (len(abiertos) + 1) + "</span>")

        def origen(caja, pivote):
            x0, y0, x1, y1 = caja
            px, py = pivote if pivote else ((x0 + x1) / 2, (y0 + y1) / 2)
            return f"--ox:{pct(px - x0, x1 - x0)};--oy:{pct(py - y0, y1 - y0)}"

        for it in self.items:
            ir_a(it.get("grupo"))
            sangria = "  " * (len(abiertos) + 1)
            l, t, w, h = self._pos(it["caja"], it.get("grupo"))
            estilo = (";" + it["estilo"]) if it.get("estilo") else ""
            clases = (" " + it["clases"]) if it.get("clases") else ""
            if it["tipo"] == "grupo":
                gw, gh = it["caja"][2] - it["caja"][0], it["caja"][3] - it["caja"][1]
                radio = f";border-radius:{pct(it['radio'], gw)}/{pct(it['radio'], gh)}" if it["radio"] else ""
                clase = f"grp g-{it['nombre']}" + (f" {it['clase']}" if it["clase"] else "")
                lineas.append(f'{sangria}<span class="{clase}" style="left:{l};top:{t};width:{w};height:{h};'
                              f'{origen(it["caja"], it["pivote"])}{radio}{estilo}">')
                abiertos.append(it["nombre"])
            elif it["tipo"] == "html":
                lineas.append(f'{sangria}<{it["etiqueta"]} class="fx f-{it["nombre"]}{clases}" aria-hidden="true" '
                              f'style="left:{l};top:{t};width:{w};height:{h}{estilo}">{it["contenido"]}'
                              f'</{it["etiqueta"]}>')
            else:
                src = f'{ruta}/{it["nombre"]}.webp'
                pw, ph = it["px"]
                pos = f'left:{l};top:{t};width:{w};{origen(it["caja"], it["pivote"])}{estilo}'
                img = f'<img src="{src}" alt="" width="{pw}" height="{ph}" loading="lazy" decoding="async">'
                if it["extra"]:
                    lineas.append(f'{sangria}<span class="pt p-{it["nombre"]}{clases}" style="{pos}">{img}'
                                  f'{it["extra"]}</span>')
                else:
                    lineas.append(f'{sangria}<img class="pt p-{it["nombre"]}{clases}" src="{src}" alt="" '
                                  f'width="{pw}" height="{ph}" style="{pos}" loading="lazy" decoding="async">')
        ir_a(None)
        lineas.append("</div>")
        (SALIDA / self.nombre / "escena.html").write_text("\n".join(lineas) + "\n")
        total = sum(p.stat().st_size for p in (SALIDA / self.nombre).glob("*.webp"))
        print(f"{self.nombre}: {len([i for i in self.items if i['tipo'] == 'pieza'])} piezas, "
              f"{total / 1024:.0f} KB en webp")


# ---------- utilidades de dibujo ----------
def rellenar(binaria):
    """Rellena huecos interiores de una máscara binaria."""
    b = (binaria > 0).astype(np.uint8)
    h, w = b.shape
    lienzo = np.zeros((h + 2, w + 2), np.uint8)
    lienzo[1:-1, 1:-1] = b
    inundada = lienzo.copy()
    cv2.floodFill(inundada, None, (0, 0), 1)
    huecos = (inundada[1:-1, 1:-1] == 0)
    return (b | huecos).astype(np.uint8)


def capa_vacia(escena):
    return np.zeros((escena.H, escena.W, 4), np.float32)


def dibujar(escena, fn, desenfoque=0):
    """Dibuja con PIL a 4x y devuelve una capa RGBA float en coordenadas de la imagen.
    `fn(draw, s)` recibe el ImageDraw y el factor de escala."""
    c = Image.new("RGBA", (escena.W * SS, escena.H * SS), (0, 0, 0, 0))
    fn(ImageDraw.Draw(c), SS)
    c = c.resize((escena.W, escena.H), Image.LANCZOS)
    if desenfoque:
        c = c.filter(ImageFilter.GaussianBlur(desenfoque))
    return np.asarray(c).astype(np.float32)


def componer(*capas):
    """Apila capas RGBA float (la primera abajo)."""
    out = np.zeros_like(capas[0])
    for c in capas:
        a = c[..., 3:4] / 255
        oa = out[..., 3:4] / 255
        na = a + oa * (1 - a)
        rgb = (c[..., :3] * a + out[..., :3] * oa * (1 - a)) / np.maximum(na, 1e-6)
        out = np.concatenate([rgb, na * 255], axis=2)
    return out
