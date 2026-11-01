"""Inserta en app/landing.html el marcado de cada escena generada y junta su CSS.

Reemplaza lo que haya entre <!--escena:NOMBRE--> y <!--/escena--> por
app/img/anim/NOMBRE/escena.html (si la escena aún no existe, deja lo que había), y copia
app/img/anim/NOMBRE/escena.css al final de app/landing-anim.css, entre
/*escenas*/ y /*/escenas*/, para que la landing descargue un solo CSS.
Uso: python3 scripts/capas-landing/insertar.py
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANDING = REPO / "app" / "landing.html"
CSS = REPO / "app" / "landing-anim.css"
ANIM = REPO / "app" / "img" / "anim"

BLOQUE = re.compile(r"(?P<sangria>[ \t]*)<!--escena:(?P<nombre>[\w-]+)-->\n.*?\n[ \t]*<!--/escena-->", re.S)
BLOQUE_CSS = re.compile(r"\n*/\*escenas\*/.*?/\*/escenas\*/\n?", re.S)
insertadas = []


def reemplazo(m):
    sangria, nombre = m["sangria"], m["nombre"]
    archivo = ANIM / nombre / "escena.html"
    if not archivo.exists():
        print(f"  {nombre}: sin escena generada, se deja igual")
        return m[0]
    cuerpo = "\n".join(sangria + linea if linea else linea for linea in archivo.read_text().rstrip("\n").split("\n"))
    insertadas.append(nombre)
    print(f"  {nombre}: insertada")
    return f"{sangria}<!--escena:{nombre}-->\n{cuerpo}\n{sangria}<!--/escena-->"


html = LANDING.read_text()
nuevo, n = BLOQUE.subn(reemplazo, html)
LANDING.write_text(nuevo)
print(f"{n} bloques revisados en {LANDING.relative_to(REPO)}")

partes = []
for nombre in insertadas:
    archivo = ANIM / nombre / "escena.css"
    if archivo.exists():
        partes.append(f"/* ---------- escena: {nombre} (img/anim/{nombre}/escena.css) ---------- */\n"
                      + archivo.read_text().strip() + "\n")
css = BLOQUE_CSS.sub("\n", CSS.read_text()).rstrip("\n") + "\n"
if partes:
    css += "\n/*escenas*/\n" + "\n".join(partes) + "/*/escenas*/\n"
CSS.write_text(css)
print(f"{len(partes)} CSS de escena juntados en {CSS.relative_to(REPO)}")
