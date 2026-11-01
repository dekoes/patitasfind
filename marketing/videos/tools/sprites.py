"""Separa cada personaje u objeto de una ilustración transparente en su propio PNG (componentes conexos del canal alfa).
Uso: python sprites.py nombre [dilatacion] [area_minima]"""
import sys
from collections import deque

import numpy as np
from PIL import Image, ImageFilter


def separar(nombre, dil=9, area_min=6000):
    im = Image.open(f"src/{nombre}.png").convert("RGBA")
    alfa = im.getchannel("A")
    # dilatar para unir piezas cercanas (persona + su celular, perro + su sombra)
    unida = np.asarray(alfa.filter(ImageFilter.MaxFilter(dil))) > 40
    h, w = unida.shape
    etiqueta = np.zeros((h, w), np.int32)
    n = 0
    cajas = []
    for y0 in range(h):
        fila = unida[y0]
        for x0 in np.nonzero(fila & (etiqueta[y0] == 0))[0]:
            if etiqueta[y0, x0]:
                continue
            n += 1
            cola = deque([(y0, x0)])
            etiqueta[y0, x0] = n
            minx = maxx = x0
            miny = maxy = y0
            area = 0
            while cola:
                y, x = cola.popleft()
                area += 1
                minx, maxx, miny, maxy = min(minx, x), max(maxx, x), min(miny, y), max(maxy, y)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and unida[ny, nx] and not etiqueta[ny, nx]:
                        etiqueta[ny, nx] = n
                        cola.append((ny, nx))
            if area >= area_min:
                cajas.append((n, area, minx, miny, maxx, maxy))
    a = np.asarray(alfa)
    salida = []
    for i, (lab, area, x0, y0, x1, y1) in enumerate(sorted(cajas, key=lambda c: (c[3] // 200, c[2]))):
        mascara = (etiqueta == lab)
        recorte = np.asarray(im).copy()
        recorte[..., 3] = np.where(mascara, a, 0)
        pieza = Image.fromarray(recorte).crop((max(0, x0 - 4), max(0, y0 - 4), min(w, x1 + 5), min(h, y1 + 5)))
        ruta = f"sprites/{nombre}-{i:02d}.png"
        pieza.save(ruta)
        salida.append((ruta, pieza.size, ((x0 + x1) // 2, (y0 + y1) // 2)))
    for s in salida:
        print(*s)


if __name__ == "__main__":
    separar(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 9, int(sys.argv[3]) if len(sys.argv) > 3 else 6000)
