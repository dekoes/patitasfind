"""Quita el fondo claro de las ilustraciones de teléfono rellenando desde las orillas.
Uso: python quitar_fondo.py nombre [tolerancia]  (lee src/<nombre>.png, escribe masks/<nombre>.png)"""
import sys
from collections import deque

import numpy as np
from PIL import Image, ImageFilter


def recortar(nombre, tol=28):
    im = Image.open(f"src/{nombre}.png").convert("RGB")
    a = np.asarray(im).astype(int)
    h, w, _ = a.shape
    orilla = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    fondo = np.median(orilla, axis=0)
    candidato = np.abs(a - fondo).sum(axis=2) < tol * 3
    visto = np.zeros((h, w), bool)
    cola = deque()
    for x in range(w):
        for y in (0, h - 1):
            if candidato[y, x] and not visto[y, x]:
                visto[y, x] = True
                cola.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if candidato[y, x] and not visto[y, x]:
                visto[y, x] = True
                cola.append((y, x))
    while cola:
        y, x = cola.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and candidato[ny, nx] and not visto[ny, nx]:
                visto[ny, nx] = True
                cola.append((ny, nx))
    alfa = Image.fromarray(np.where(visto, 0, 255).astype("uint8"))
    alfa = alfa.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    salida = im.convert("RGBA")
    salida.putalpha(alfa)
    salida.save(f"masks/{nombre}.png")
    print(nombre, "fondo", fondo.astype(int), "quitado %.0f%%" % (100 * visto.mean()))


if __name__ == "__main__":
    recortar(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 28)
