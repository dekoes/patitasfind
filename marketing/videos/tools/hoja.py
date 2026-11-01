"""Hoja de contacto de fotogramas para revisar: python hoja.py prefijo salida.jpg [columnas]"""
import glob
import sys

from PIL import Image, ImageDraw

pref, out = sys.argv[1], sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 5
fs = sorted(glob.glob(f"build/stills/{pref}-*.png"))
tw, th = 300, 533
rows = (len(fs) + cols - 1) // cols
hoja = Image.new("RGB", (cols * tw, rows * (th + 24)), "white")
d = ImageDraw.Draw(hoja)
for i, f in enumerate(fs):
    im = Image.open(f).convert("RGB").resize((tw, th))
    x, y = (i % cols) * tw, (i // cols) * (th + 24)
    hoja.paste(im, (x, y))
    d.text((x + 6, y + th + 4), f.split("-")[-1][:-4] + " s", fill="black")
hoja.save(out, quality=85)
