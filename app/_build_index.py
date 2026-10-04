#!/usr/bin/env python3
"""Genera app/index.html a partir de mockups/laminas.html (defs + secciones)."""
import re, pathlib

root = pathlib.Path('/Users/AI/Documents/proyectosIA/patitasfind')
src = (root / 'mockups/laminas.html').read_text(encoding='utf-8')

# 1) Extraer defs SVG
defs_m = re.search(r'<svg width="0" height="0".*?</svg>', src, re.S)
assert defs_m, 'defs no encontrados'
defs = defs_m.group(0)

# 2) Extraer secciones
sections = re.findall(r'<section class="phone" data-s="(\d+)"[^>]*>(.*?)</section>', src, re.S)
assert len(sections) == 35, f'esperaba 35 secciones, hay {len(sections)}'
screens = []
for sid, body in sections:
    screens.append(f'<section class="screen" data-s="{sid}">{body}</section>')
screens_html = '\n'.join(screens)

html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>PatitasFind 🐾</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@500;600;700;800&family=Patrick+Hand&display=swap" rel="stylesheet">
<link rel="stylesheet" href="styles.css?v=3">
</head>
<body>
<div id="bg" aria-hidden="true"></div>
<div id="stage">
  <div id="device">
    {defs}
    <div id="screens">
{screens_html}
    </div>
    <div id="fxLayer" aria-hidden="true"></div>
    <div id="pawLayer" aria-hidden="true"></div>
  </div>
</div>
<div id="toast" role="status"></div>
<script src="app.js"></script>
</body>
</html>
"""
(root / 'app').mkdir(exist_ok=True)
(root / 'app/index.html').write_text(html, encoding='utf-8')
print('OK: app/index.html generado,', len(html), 'bytes')
