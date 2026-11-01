#!/usr/bin/env python3
"""Genera el centro legal de GuauWoow desde plantillas y app/legal/datos-legales.json.

Plantillas (lo único que se edita a mano), en app/legal/plantillas/:
    <slug>.html               -> app/legal/<slug>.html (todas las páginas del centro legal)
    _parciales/<nombre>.html  -> se insertan donde la plantilla dice <!--INCLUIR:<nombre>-->
                                 (nav-legal, pie-legal; pueden llevar marcadores)
    aviso-simplificado.txt    -> app/legal/aviso-simplificado.txt, el bloque <!--INCLUIR:aviso-simplificado-->
                                 (privacidad y privacidad-simplificado) y el aviso del registro en
                                 app/index.html (entre <!-- aviso-simplificado:inicio/fin -->)
    security.txt              -> app/.well-known/security.txt (se sirve en /.well-known/security.txt)

También genera:
    app/legal/versiones.json  registro de versiones [{slug, title, version, effective_at, sha256,
                              requires_reacceptance, summary, url}] con la versión vigente de cada página y
                              las anteriores (lo lee python -m app.cli sync-legal-docs y /cumplimiento/documentos);
                              copia idéntica en backend/app/data/versiones-legales.json (va dentro de la imagen)
    app/legal/<slug>-<versión>.html  copia fija de cada versión anterior al publicar una nueva
    app/sitemap.xml           las páginas legales (entre <!-- paginas-legales:inicio/fin -->)
    docs/legal/LLENAR-DATOS.md  la lista de claves (entre <!-- claves:inicio/fin -->)

Marcadores:
    HTML: <span class="ph">[RAZÓN SOCIAL]</span>  -> clave RAZON_SOCIAL (texto antes de "," o ":",
          sin acentos, en mayúsculas). Con data-clave="X" la clave es X (notas [VERIFICAR: ...]).
    TXT:  [RAZÓN SOCIAL]
    %%SITE_URL%% se cambia por https://DOMINIO cuando DOMINIO tiene valor (si no, lo reemplaza Nginx).
    Las claves VERIFICAR_* son notas para tu abogado: true = cláusula confirmada (se borra la nota y, si
    queda vacío, su párrafo); texto = reemplaza la nota. Los datos sin llenar se quedan marcados a la vista.
    Todos los comentarios <!-- PLANTILLA: ... --> son notas internas y no llegan a la página generada.
    Resumen de cada versión (versiones.json): el párrafo de la sección #versiones que empieza con «Cambios
    principales» o «Primera versión» (o un <p class="resumen-version">).

Uso:
    python3 scripts/render-legal.py                    # genera los archivos
    python3 scripts/render-legal.py --check            # sale con 1 si faltan datos, quedan notas [VERIFICAR],
                                                       # los archivos no están al día o algo no cuadra con
                                                       # la configuración del servidor (para desplegar): DOMINIO
                                                       # vacío, RAZÓN SOCIAL/DOMICILIO distintos de EMISOR_NOMBRE/
                                                       # OPERATOR_ADDRESS, donativos con la cuenta de la plataforma
                                                       # o una versión nueva con menos de 30 días de aviso previo
    python3 scripts/render-legal.py --check-generated  # sale con 1 solo si los archivos generados no están al
                                                       # día, hay claves sin documentar o páginas rotas (CI)
    python3 scripts/render-legal.py --list             # lista las claves con su descripción
    python3 scripts/render-legal.py --init             # crea/completa datos-legales.json con todas las claves

Solo usa la biblioteca estándar (python3 >= 3.9).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
AVISO_TXT = "aviso-simplificado.txt"
SECURITY_TXT = "security.txt"
AVISO_INCLUDE = "aviso-simplificado"
SITE_NAME = " · GuauWoow"

# Documentos que se aceptan de forma expresa: una versión nueva pide aceptarla otra vez
REACCEPTANCE_SLUGS = frozenset({
    "terminos", "privacidad", "terminos-tienda",
    "terminos-refugios", "acuerdo-datos-refugios", "terminos-vendedores", "terminos-clinicas",
    "terminos-casas-de-paso",
})
# Versión que guarda el backend al aceptar (backend/app/config.py y, si se define, la variable de entorno)
CONFIG_VERSIONS = {
    "terminos": ("legal_terms_version", "LEGAL_TERMS_VERSION"),
    "privacidad": ("legal_privacy_version", "LEGAL_PRIVACY_VERSION"),
}

HTML_PH = re.compile(r'(?P<pre>[ \t]?)<span class="ph"(?: data-clave="(?P<clave>[A-Z0-9_]+)")?>\[(?P<etiqueta>[^\]<]+)\]</span>')
TXT_PH = re.compile(r"\[(?P<etiqueta>[A-ZÁÉÍÓÚÜÑ][^\]\n]*)\]")
INCLUDE_RE = re.compile(r"(?P<indent>[ \t]*)<!--INCLUIR:(?P<nombre>[a-z0-9-]+)-->")
# Comentario PLANTILLA en su propia línea (se borra la línea completa) y en medio de una línea.
# (?:(?!-->).)* evita que un comentario "se coma" el texto hasta el cierre de otro comentario.
NOTE_LINE = re.compile(r"^[ \t]*<!--\s*PLANTILLA\b(?:(?!-->).)*-->[ \t]*\r?\n", re.S | re.M)
NOTE_ANY = re.compile(r"<!--\s*PLANTILLA\b(?:(?!-->).)*-->", re.S)
HEADER_NOTE = "edita este archivo"
GENERATED = "ARCHIVO GENERADO"
REMOVED = "\x00"  # marca temporal de una nota VERIFICAR borrada (para quitar el párrafo si queda vacío)
EMPTY_LINE_BLOCK = re.compile(r"^[ \t]*<(p|li)>\s*\x00(?:\s|\x00)*</\1>[ \t]*\r?\n", re.M)
EMPTY_BLOCK = re.compile(r"<(p|li)>\s*\x00(?:\s|\x00)*</\1>")
INDEX_START = "<!-- aviso-simplificado:inicio -->"
INDEX_END = "<!-- aviso-simplificado:fin -->"
SITEMAP_START = "<!-- paginas-legales:inicio -->"
SITEMAP_END = "<!-- paginas-legales:fin -->"
DOCS_START = "<!-- claves:inicio -->"
DOCS_END = "<!-- claves:fin -->"
EMAIL_RE = re.compile(r"[^@\s<>\"]+@[^@\s<>\"]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https://\S+")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
VERSIONES_SECTION = re.compile(r'<section\b[^>]*\bid="versiones"[^>]*>(?P<body>.*?)</section>', re.S)
VERSION_LI = re.compile(r"<li>Versión: (\d{4}-\d{2}-\d{2})</li>")
VERSION_MENTION = re.compile(r"Versión:? (\d{4}-\d{2}-\d{2})")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
CANONICAL_RE = re.compile(r'<link rel="canonical" href="([^"]*)">')
EXPIRES_RE = re.compile(r"^Expires:\s*(\S+)", re.M)
SUMMARY_START = re.compile(r"^(Cambios principales|Primera versión|Esta es la primera versión)")
SENTENCE_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-ZÁÉÍÓÚÑ¿¡«])")
NOT_SUMMARY = re.compile(r"historial|^Consulta|^Todas las versiones|^Si hacemos|^Si un cambio|^Las versiones")
DEFAULT_SUMMARY = "Primera versión."
# Fecha de la revisión del código que respalda cada «estado_codigo» de las notas VERIFICAR del equipo técnico
CODE_STATUS_DATE = "2026-10-18"
ARCHIVED_SUMMARY = "Versión anterior; su texto completo queda publicado en esta dirección."

# Datos de las páginas que deben coincidir con la configuración del servidor (--check).
# (clave, variable de entorno, campo de backend/app/config.py o valor por defecto de los scripts)
SETTINGS = (
    ("COMISION_TIENDA", "MERCADOPAGO_MARKETPLACE_FEE_PERCENT", "config:mercadopago_marketplace_fee_percent"),
    ("COMISION_DONATIVOS", "MERCADOPAGO_DONATION_FEE_PERCENT", "config:mercadopago_donation_fee_percent"),
    ("TOPE_POR_DONATIVO", "DONATION_MAX_MXN", "config:donation_max_mxn"),
    ("TOPE_DIARIO_DE_DONATIVOS", "DONATION_DAILY_MAX_MXN", "config:donation_daily_max_mxn"),
    ("PLAZO_DE_RESGUARDO_DE_PERROS_ENCONTRADOS", "FOUND_DOG_HOLD_DAYS", "config:found_dog_hold_days"),
    ("PLAZO_LOCAL_DE_RESPALDOS", "BACKUP_RETENTION_DAYS", "default:14"),
    ("PLAZO_DE_CONSERVACION_DE_RESPALDOS_EXTERNOS", "BACKUP_OFFSITE_RETENTION_DAYS", "default:30"),
)
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
MONTHS = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"), start=1)}


class Paths:
    def __init__(self, root: Path):
        self.root = root
        self.app = root / "app"
        self.legal = self.app / "legal"
        self.plantillas = self.legal / "plantillas"
        self.parciales = self.plantillas / "_parciales"
        self.datos = self.legal / "datos-legales.json"
        self.ejemplo = self.legal / "datos-legales.example.json"
        self.versiones = self.legal / "versiones.json"
        # Copia dentro de backend/ para que la imagen del backend la incluya (services/legal_acceptance.py)
        self.versiones_backend = root / "backend" / "app" / "data" / "versiones-legales.json"
        self.index = self.app / "index.html"
        self.sitemap = self.app / "sitemap.xml"
        self.security = self.app / ".well-known" / SECURITY_TXT
        self.config = root / "backend" / "app" / "config.py"
        self.env = root / ".env"
        self.llenar = root / "docs" / "legal" / "LLENAR-DATOS.md"

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


# --------------------------------------------------------------------------- claves y valores
def normalize_key(etiqueta: str) -> str:
    """'PLAZO DE ENTREGA, p. ej. 3 días' -> 'PLAZO_DE_ENTREGA'; 'RAZÓN SOCIAL' -> 'RAZON_SOCIAL'."""
    base = re.split(r"[,:]", etiqueta, maxsplit=1)[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", base.upper()).strip("_")


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} no es JSON válido: {exc}") from exc


def load_json(path: Path) -> dict:
    data = read_json(path, {})
    if not isinstance(data, dict):
        raise SystemExit(f"{path} debe contener un objeto JSON {{\"CLAVE\": \"valor\"}}.")
    return {k: v for k, v in data.items() if not k.startswith("_")}


def value_for(datos: dict, clave: str):
    """Valor usable o None si falta. Las notas VERIFICAR_* aceptan true (borrar la nota)."""
    value = datos.get(clave)
    if value is None or value is False:
        return None
    if value is True:
        if clave.startswith("VERIFICAR_"):
            return True
        raise SystemExit(f"datos-legales.json: {clave} debe ser texto, no true.")
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        raise SystemExit(f"datos-legales.json: {clave} debe ser texto (recibido {type(value).__name__}).")
    return value.strip() or None


def value_html(clave: str, value: str) -> str:
    text = html.escape(value, quote=False)
    if clave.startswith("CORREO") and EMAIL_RE.fullmatch(value):
        return f'<a href="mailto:{html.escape(value)}">{text}</a>'
    return text


def parse_date(value) -> str | None:
    """'2026-11-01' o '1 de noviembre de 2026' -> '2026-11-01'; None si no es una fecha."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if ISO_DATE.fullmatch(value):
            return datetime.date.fromisoformat(value).isoformat()
        m = re.fullmatch(r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})", value.lower())
        if m and m.group(2) in MONTHS:
            return datetime.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))).isoformat()
    except ValueError:
        return None
    return None


def plain_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def page_version(text: str) -> str | None:
    """Versión impresa en la sección #versiones (o, en páginas antiguas, el primer <li>Versión: ...)."""
    section = VERSIONES_SECTION.search(text)
    found = VERSION_LI.search(section.group("body")) if section else None
    found = found or VERSION_LI.search(text)
    return found.group(1) if found else None


def page_title(text: str) -> str:
    m = TITLE_RE.search(text)
    title = plain_text(m.group(1)) if m else ""
    return title[:-len(SITE_NAME)] if title.endswith(SITE_NAME) else title


def page_summary(text: str) -> str:
    section = VERSIONES_SECTION.search(text)
    if not section:
        return ""
    body = section.group("body")
    explicit = re.search(r'<p class="resumen-version">(.*?)</p>', body, re.S)
    if explicit:
        return plain_text(explicit.group(1))
    for para in re.findall(r"<p\b[^>]*>(.*?)</p>", body, re.S):
        text = plain_text(para)
        if SUMMARY_START.match(text):
            sentences = [s for s in SENTENCE_SPLIT.split(text) if not NOT_SUMMARY.search(s)]
            if sentences:
                return " ".join(sentences)
    return DEFAULT_SUMMARY


# --------------------------------------------------------------------------- render
class Render:
    def __init__(self, paths: Paths, datos: dict, today: datetime.date | None = None):
        self.paths = paths
        self.datos = datos
        self.today = today or datetime.date.today()
        self.used: dict[str, str] = {}        # clave -> etiqueta (todas las de las plantillas)
        self.where: dict[str, set] = {}       # clave -> plantillas donde aparece
        self.missing: dict[str, str] = {}     # clave -> etiqueta (sin valor)
        self.pages: list[dict] = []           # una entrada de versiones.json por página vigente
        self.history: list[dict] = []         # versiones anteriores (versiones.json)
        self.errors: list[str] = []           # impiden --check y --check-generated
        self.blocking: list[str] = []         # además impiden generar (texto de una versión vigente)
        self.warnings: list[str] = []
        self._origin = ""
        self._partials: dict[str, str] | None = None

    # ------------------------------------------------------------------ marcadores
    def _note(self, clave: str, etiqueta: str) -> None:
        self.used.setdefault(clave, etiqueta)
        where = self.where.setdefault(clave, set())
        if self._origin:
            where.add(self._origin)

    def _value(self, clave: str, overrides: dict | None = None):
        if overrides and clave in overrides:
            return overrides[clave]
        return value_for(self.datos, clave)

    def html_text(self, template: str, overrides: dict | None = None) -> str:
        def sub(m):
            clave = m.group("clave") or normalize_key(m.group("etiqueta"))
            self._note(clave, m.group("etiqueta"))
            value = self._value(clave, overrides)
            if value is None:
                self.missing.setdefault(clave, m.group("etiqueta"))
                return m.group(0)
            if value is True:
                return REMOVED
            return m.group("pre") + value_html(clave, value)

        text = HTML_PH.sub(sub, template)
        # Una nota VERIFICAR que estaba sola en su párrafo o viñeta no deja un elemento vacío
        text = EMPTY_LINE_BLOCK.sub("", text)
        text = EMPTY_BLOCK.sub("", text)
        return text.replace(REMOVED, "")

    def txt_text(self, template: str) -> str:
        def sub(m):
            clave = normalize_key(m.group("etiqueta"))
            self._note(clave, m.group("etiqueta"))
            value = value_for(self.datos, clave)
            if value is None or value is True:
                self.missing.setdefault(clave, m.group("etiqueta"))
                return m.group(0)
            return value

        return TXT_PH.sub(sub, template)

    def aviso_html(self, template: str, link: bool) -> str:
        """Aviso simplificado en HTML: escapa el texto, marca lo que falta y (opcional) enlaza el aviso integral."""
        def piece(text: str) -> str:
            out, pos = [], 0
            for m in TXT_PH.finditer(text):
                out.append(html.escape(text[pos:m.start()], quote=False))
                clave = normalize_key(m.group("etiqueta"))
                self._note(clave, m.group("etiqueta"))
                value = value_for(self.datos, clave)
                if value is None or value is True:
                    self.missing.setdefault(clave, m.group("etiqueta"))
                    out.append(f'<span class="ph">[{html.escape(m.group("etiqueta"), quote=False)}]</span>')
                else:
                    out.append(value_html(clave, value))
                pos = m.end()
            out.append(html.escape(text[pos:], quote=False))
            return "".join(out)

        text = template.strip()
        url = URL_RE.search(text)
        if url:
            body = piece(text[:url.start()])
            target = piece(url.group(0))
            if link:
                target = f'<a href="/app/legal/privacidad.html" target="_blank" rel="noopener">{target}</a>'
            body += target + piece(text[url.end():])
        else:
            body = piece(text)
        title = "AVISO DE PRIVACIDAD SIMPLIFICADO."
        if body.startswith(title):
            # En la app (link=True) va en tono de oración, como el resto del formulario
            shown = "<b>Aviso de privacidad simplificado.</b>" if link else f"<strong>{title}</strong>"
            body = shown + body[len(title):]
        return body

    # ------------------------------------------------------------------ plantillas HTML
    def partials(self) -> dict[str, str]:
        if self._partials is None:
            self._partials = {}
            if self.paths.parciales.is_dir():
                for path in sorted(self.paths.parciales.glob("*.html")):
                    self._partials[path.stem] = path.read_text(encoding="utf-8")
        return self._partials

    def expand_includes(self, text: str, name: str, aviso_tpl: str, depth: int = 0) -> str:
        if depth > 5:
            raise SystemExit(f"plantillas/{name}: <!--INCLUIR:...--> anidado más de 5 niveles (¿se incluye a sí mismo?).")

        def sub(m):
            nombre, indent = m.group("nombre"), m.group("indent")
            if nombre == AVISO_INCLUDE:
                return indent + self.aviso_html(aviso_tpl, link=False)
            partial = self.partials().get(nombre)
            if partial is None:
                raise SystemExit(f"plantillas/{name}: <!--INCLUIR:{nombre}--> no existe en app/legal/plantillas/_parciales/.")
            body = self.expand_includes(strip_notes(partial).strip("\n"), name, aviso_tpl, depth + 1)
            lines = body.strip().splitlines()
            return "\n".join(indent + line.strip() if i == 0 else line for i, line in enumerate(lines))

        return INCLUDE_RE.sub(sub, text)

    def page_html(self, name: str, template: str, aviso_tpl: str, overrides: dict | None = None) -> str:
        banner = (f"<!-- {GENERATED} por scripts/render-legal.py desde app/legal/plantillas/{name}: "
                  "no lo edites a mano -->")
        first = NOTE_ANY.search(template)
        if first and HEADER_NOTE in first.group(0):
            text = template[:first.start()] + banner + template[first.end():]
        else:
            doctype = re.match(r"\s*<!doctype html>\s*\n", template, re.I)
            cut = doctype.end() if doctype else 0
            text = template[:cut] + banner + "\n" + template[cut:]
        text = strip_notes(text)
        text = self.expand_includes(text, name, aviso_tpl)
        domain = self._value("DOMINIO")
        if isinstance(domain, str) and "%%SITE_URL%%" in text:
            self._note("DOMINIO", "DOMINIO")
            text = text.replace("%%SITE_URL%%", "https://" + domain.removeprefix("https://").rstrip("/"))
        return self.html_text(text, overrides)

    # ------------------------------------------------------------------ todo lo que se genera
    def outputs(self) -> dict[Path, str]:
        """{archivo de salida: contenido} para todo lo que se genera."""
        for collected in (self.used, self.where, self.missing, self.pages, self.history,
                          self.errors, self.blocking, self.warnings):
            collected.clear()
        paths, result = self.paths, {}
        aviso_tpl = (paths.plantillas / AVISO_TXT).read_text(encoding="utf-8")

        self._origin = AVISO_TXT
        result[paths.legal / AVISO_TXT] = self.txt_text(aviso_tpl).rstrip("\n") + "\n"
        security_tpl = paths.plantillas / SECURITY_TXT
        if security_tpl.exists():
            self._origin = SECURITY_TXT
            result[paths.security] = self.txt_text(security_tpl.read_text(encoding="utf-8")).rstrip("\n") + "\n"

        previous = self._previous_versions()
        datos_effective = self._datos_effective_date()
        current_keys = set()
        for tpl in sorted(paths.plantillas.glob("*.html")):
            name, slug = tpl.name, tpl.stem
            template = tpl.read_text(encoding="utf-8")
            version = page_version(template)
            if not version:
                self.errors.append(f"plantillas/{name}: no tiene «<li>Versión: AAAA-MM-DD</li>» en la sección #versiones.")
                version = "sin-version"
            for printed in set(VERSION_MENTION.findall(template)) - {version}:
                self.errors.append(f"plantillas/{name}: dice «Versión {printed}» pero su sección #versiones dice {version}.")
            record = previous.get((slug, version))
            frozen = record.get("effective_at") if record and self._in_force(record.get("effective_at")) else None
            overrides = None
            if frozen:
                # Una versión ya vigente conserva su fecha aunque FECHA_DE_ENTRADA_EN_VIGOR cambie para otra versión
                raw = value_for(self.datos, "FECHA_DE_ENTRADA_EN_VIGOR")
                overrides = {"FECHA_DE_ENTRADA_EN_VIGOR": raw if parse_date(raw) == frozen else frozen}
            self._origin = name
            content = self.page_html(name, template, aviso_tpl, overrides)
            out = paths.legal / name
            result[out] = content
            digest = sha256(content)
            entry = {
                "slug": slug, "title": page_title(content), "version": version,
                "effective_at": frozen or datos_effective, "sha256": digest,
                "requires_reacceptance": slug in REACCEPTANCE_SLUGS, "summary": page_summary(content),
                "url": f"/app/legal/{name}",
            }
            if frozen and record.get("sha256") != digest:
                msg = (f"El texto de {name} versión {version} (vigente desde {frozen}) cambió. Una versión vigente no se "
                       "edita: cambia la fecha de «Versión» en la plantilla para publicar una nueva (la anterior queda "
                       "archivada) o regresa el texto/los datos a como estaban.")
                (self.blocking if entry["requires_reacceptance"] else self.warnings).append(msg)
            self.pages.append(entry)
            current_keys.add((slug, version))
            self._archive_previous(out, slug, version, previous, result)

        archived = {(e["slug"], e["version"]) for e in self.history}
        for key, record in previous.items():
            if key in current_keys or key in archived:
                continue
            record = dict(record)
            archive = paths.legal / f"{record['slug']}-{record['version']}.html"
            if record.get("url") == f"/app/legal/{record['slug']}.html" and archive.exists():
                record["url"] = f"/app/legal/{archive.name}"
            self.history.append(record)
        # Por página (slug) y, dentro de cada una, de la versión más nueva a la más antigua
        entries = sorted(self.pages + self.history, key=lambda e: e["version"], reverse=True)
        entries.sort(key=lambda e: e["slug"])
        result[paths.versiones] = json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
        if paths.versiones_backend.parent.is_dir():
            result[paths.versiones_backend] = result[paths.versiones]

        index = self.index_text(aviso_tpl)
        if index is not None:
            result[paths.index] = index
        sitemap = self.sitemap_text()
        if sitemap is not None:
            result[paths.sitemap] = sitemap
        return result

    def _previous_versions(self) -> dict[tuple, dict]:
        data = read_json(self.paths.versiones, [])
        if not isinstance(data, list):
            raise SystemExit(f"{self.paths.rel(self.paths.versiones)} debe ser una lista JSON.")
        return {(e["slug"], e["version"]): e for e in data if isinstance(e, dict) and "slug" in e and "version" in e}

    def _datos_effective_date(self) -> str | None:
        raw = value_for(self.datos, "FECHA_DE_ENTRADA_EN_VIGOR")
        if raw is None:
            return None
        parsed = parse_date(raw)
        if parsed is None:
            self.errors.append(f"FECHA_DE_ENTRADA_EN_VIGOR debe ser una fecha AAAA-MM-DD (recibido «{raw}»).")
        return parsed

    def _in_force(self, effective_at) -> bool:
        parsed = parse_date(effective_at) if effective_at else None
        return bool(parsed) and datetime.date.fromisoformat(parsed) <= self.today

    def _archive_previous(self, out: Path, slug: str, version: str, previous: dict, result: dict) -> None:
        """Al publicar una versión nueva, la anterior queda en app/legal/<slug>-<versión>.html (URL fija)."""
        if not out.exists():
            return
        old = out.read_text(encoding="utf-8")
        old_version = page_version(old)
        if GENERATED not in old or not old_version or old_version == version:
            return
        archive = self.paths.legal / f"{slug}-{old_version}.html"
        if not archive.exists():
            result[archive] = old
        record = previous.get((slug, old_version)) or {}
        self.history.append({
            "slug": slug, "title": record.get("title") or page_title(old), "version": old_version,
            "effective_at": record.get("effective_at"), "sha256": sha256(old),
            "requires_reacceptance": slug in REACCEPTANCE_SLUGS,
            "summary": record.get("summary") or (page_summary(old) if VERSIONES_SECTION.search(old) else ARCHIVED_SUMMARY),
            "url": f"/app/legal/{archive.name}",
        })

    def index_text(self, aviso_tpl: str) -> str | None:
        if not self.paths.index.exists():
            return None
        current = self.paths.index.read_text(encoding="utf-8")
        start, end = current.find(INDEX_START), current.find(INDEX_END)
        if start < 0 or end < start:
            return None
        start += len(INDEX_START)
        self._origin = ""  # mismas claves que aviso-simplificado.txt
        return current[:start] + self.aviso_html(aviso_tpl, link=True) + current[end:]

    def sitemap_text(self) -> str | None:
        if not self.paths.sitemap.exists():
            return None
        current = self.paths.sitemap.read_text(encoding="utf-8")
        start, end = current.find(SITEMAP_START), current.find(SITEMAP_END)
        if start < 0 or end < start:
            return None
        start += len(SITEMAP_START)
        rows = []
        for page in sorted(self.pages, key=lambda p: (p["slug"] != "centro-legal", p["slug"])):
            priority = "0.5" if page["slug"] == "centro-legal" else "0.3"
            lastmod = f"\n    <lastmod>{page['version']}</lastmod>" if ISO_DATE.fullmatch(page["version"]) else ""
            rows.append(f"  <url>\n    <loc>%%SITE_URL%%{page['url']}</loc>{lastmod}\n"
                        f"    <changefreq>monthly</changefreq>\n    <priority>{priority}</priority>\n  </url>")
        return current[:start] + "\n" + "\n".join(rows) + "\n  " + current[end:]


def strip_notes(text: str) -> str:
    """Quita todos los comentarios <!-- PLANTILLA: ... --> (si ocupan su línea, la línea completa)."""
    return NOTE_ANY.sub("", NOTE_LINE.sub("", text))


# --------------------------------------------------------------------------- documentación de claves
def group_titles(ejemplo_raw: dict) -> dict[str, str]:
    grupos = ejemplo_raw.get("_grupos")
    return dict(grupos) if isinstance(grupos, dict) else {}


def describe(ejemplo_raw: dict, clave: str) -> str:
    info = ejemplo_raw.get(clave)
    if isinstance(info, dict):
        return info.get("descripcion", "")
    return str(info or "")


def docs_block(ejemplo_raw: dict, render: Render) -> str:
    """Lista de claves de docs/legal/LLENAR-DATOS.md (entre <!-- claves:inicio --> y <!-- claves:fin -->)."""
    titles = group_titles(ejemplo_raw)
    by_group: dict[str, list[str]] = {g: [] for g in titles}
    for clave, info in ejemplo_raw.items():
        if clave.startswith("_") or not isinstance(info, dict):
            continue
        by_group.setdefault(info.get("grupo", "otros"), []).append(clave)

    def pages(clave: str) -> str:
        found = sorted(p.removesuffix(".html") for p in render.where.get(clave, ()))
        if len(found) > 8:
            return f"{len(found)} páginas"
        return ", ".join(found) if found else "ninguna"

    out = ["", f"_Generado por `python3 scripts/render-legal.py` desde `app/legal/datos-legales.example.json`: "
           f"{sum(len(v) for v in by_group.values())} claves. No edites esta lista a mano._", ""]
    for group, claves in by_group.items():
        if not claves:
            continue
        out += [f"### {titles.get(group, group)}", ""]
        for clave in claves:
            info = ejemplo_raw[clave]
            if clave.startswith("VERIFICAR_"):
                who = f" · revisa: {info['revisa']}" if info.get("revisa") else ""
                out.append(f"- **`{clave}`**{who} · en: {pages(clave)}")
                out.append(f"  - Qué confirmar: {info.get('descripcion', '')}")
                if info.get("estado_codigo"):
                    out.append(f"  - Estado en el código al {CODE_STATUS_DATE}: {info['estado_codigo']}")
                if info.get("sugerencia"):
                    out.append(f"  - Valor sugerido: {info['sugerencia']}")
            else:
                ejemplo = f" Ejemplo: `{info['ejemplo']}`." if info.get("ejemplo") else ""
                out.append(f"- **`{clave}`** — {info.get('descripcion', '')}{ejemplo} _En: {pages(clave)}._")
        out.append("")
    return "\n".join(out)


def docs_text(paths: Paths, ejemplo_raw: dict, render: Render) -> str | None:
    if not paths.llenar.exists():
        return None
    current = paths.llenar.read_text(encoding="utf-8")
    start, end = current.find(DOCS_START), current.find(DOCS_END)
    if start < 0 or end < start:
        return None
    start += len(DOCS_START)
    return current[:start] + docs_block(ejemplo_raw, render) + current[end:]


# --------------------------------------------------------------------------- validación de páginas
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
NOT_IN_P = {"address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figure", "footer",
            "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section",
            "table", "ul"}


class PageParser(HTMLParser):
    """Comprueba que la página esté bien formada y junta ids, enlaces y scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.links: list[tuple[str, int]] = []
        self.scripts: list[tuple[str, int]] = []
        self.canonical: str | None = None

    def _attrs(self, tag, attrs):
        line = self.getpos()[0]
        a = dict(attrs)
        if a.get("id"):
            if a["id"] in self.ids:
                self.errors.append(f"línea {line}: id repetido «{a['id']}»")
            self.ids.add(a["id"])
        if tag == "a" and a.get("href") is not None:
            self.links.append((a["href"], line))
        if tag == "link":
            rel = (a.get("rel") or "").split()
            if "canonical" in rel:
                self.canonical = a.get("href")
            elif "stylesheet" in rel and a.get("href"):
                self.links.append((a["href"], line))
        if tag == "script" and a.get("src"):
            self.scripts.append((a["src"], line))
        return line

    def handle_starttag(self, tag, attrs):
        line = self._attrs(tag, attrs)
        if tag in NOT_IN_P and any(t == "p" for t, _ in self.stack):
            self.errors.append(f"línea {line}: <{tag}> dentro de <p> (el navegador cierra el párrafo antes)")
        if tag == "a" and any(t == "a" for t, _ in self.stack):
            self.errors.append(f"línea {line}: enlace dentro de otro enlace")
        if tag not in VOID:
            self.stack.append((tag, line))

    def handle_startendtag(self, tag, attrs):
        self._attrs(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        line = self.getpos()[0]
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            return
        if any(t == tag for t, _ in self.stack):
            while self.stack and self.stack[-1][0] != tag:
                open_tag, open_line = self.stack.pop()
                self.errors.append(f"línea {open_line}: <{open_tag}> sin cerrar antes de </{tag}> (línea {line})")
            self.stack.pop()
        else:
            self.errors.append(f"línea {line}: </{tag}> sin etiqueta de apertura")

    def finish(self):
        self.close()
        for tag, line in self.stack:
            self.errors.append(f"línea {line}: <{tag}> sin cerrar")
        return self


def parse_page(text: str) -> PageParser:
    parser = PageParser()
    parser.feed(text)
    return parser.finish()


def validate_pages(paths: Paths, outputs: dict[Path, str], pages: list[dict],
                   history: list[dict] | tuple = ()) -> tuple[list[str], list[str]]:
    """(errores, scripts que faltan) de las páginas generadas: HTML bien formado, enlaces y anclas que
    existen, canonical propio, sin notas PLANTILLA ni marcadores INCLUIR, y js/*.js presentes. De las versiones
    archivadas (history) solo se revisan los enlaces: su texto no se edita, así que un ancla que ya no existe en la
    página vigente se resuelve con un id de alias en la plantilla de esa página."""
    errors, missing_scripts = [], []
    html_out = {p: t for p, t in outputs.items() if p.parent == paths.legal and p.suffix == ".html"}
    parsed: dict[Path, PageParser] = {p: parse_page(t) for p, t in html_out.items()}
    current = {paths.legal / Path(e["url"]).name for e in pages}

    def ids_of(target: Path) -> set | None:
        if target not in parsed:
            if not target.exists() or target.suffix != ".html":
                return None
            parsed[target] = parse_page(target.read_text(encoding="utf-8"))
        return parsed[target].ids

    for path in sorted(current & set(html_out)):
        text, page, name = html_out[path], parsed[path], path.name
        for problem in page.errors:
            errors.append(f"app/legal/{name}: {problem}")
        if NOTE_ANY.search(text) or "PLANTILLA:" in text:
            errors.append(f"app/legal/{name}: quedó una nota <!-- PLANTILLA ... -->")
        if "<!--INCLUIR:" in text:
            errors.append(f"app/legal/{name}: quedó un marcador <!--INCLUIR:...--> sin expandir")
        for token in set(re.findall(r"%%[A-Z_]+%%", text)) - {"%%SITE_URL%%"}:
            errors.append(f"app/legal/{name}: marcador desconocido {token}")
        if page.canonical is not None and not page.canonical.endswith(f"/app/legal/{name}"):
            errors.append(f"app/legal/{name}: el canonical apunta a {page.canonical}")
        for href, line in page.links:
            problem = check_link(paths, path, href, ids_of, set(outputs))
            if problem:
                errors.append(f"app/legal/{name}:{line}: {problem}")
        for src, line in page.scripts:
            if re.match(r"^[a-z]+:|^//", src):
                errors.append(f"app/legal/{name}:{line}: script externo {src} (la CSP solo permite 'self')")
                continue
            target = resolve(paths, path, src.split("?")[0])
            if target is not None and not target.exists():
                missing_scripts.append(f"app/legal/{name}:{line}: falta {paths.rel(target)}")
    archives = {paths.legal / Path(e["url"]).name for e in history
                if str(e.get("url") or "").startswith("/app/legal/")} - current
    for path in sorted(archives):
        text = outputs.get(path)
        if text is None:
            if not path.exists():
                continue  # history_problems ya reporta la versión archivada que falta
            text = path.read_text(encoding="utf-8")
        page = parsed.get(path) or parse_page(text)
        for href, line in page.links:
            problem = check_link(paths, path, href, ids_of, set(outputs))
            if problem:
                errors.append(f"app/legal/{path.name} (versión archivada):{line}: {problem}")
    return errors, missing_scripts


def resolve(paths: Paths, page: Path, url: str) -> Path | None:
    """Archivo que sirve una URL (relativa a la página o absoluta del sitio); None si no es un archivo."""
    if not url:
        return page
    if not url.startswith("/"):
        return Path(os.path.normpath(page.parent / url))
    if url in ("/", "/index.html"):
        return paths.app / "landing.html"
    if url in ("/app", "/app/"):
        return paths.app / "index.html"
    if url in ("/legal", "/legal/", "/app/legal", "/app/legal/"):
        return paths.legal / "centro-legal.html"
    if url.startswith("/legal/"):  # redirección /legal/<slug> -> /app/legal/<slug>.html
        slug = url[len("/legal/"):].strip("/").removesuffix(".html")
        return paths.legal / f"{slug}.html"
    if url.startswith("/app/"):
        return paths.app / url[len("/app/"):]
    if url == "/.well-known/security.txt":
        return paths.security
    return paths.app / url.lstrip("/") if "." in url.rsplit("/", 1)[-1] else None  # el resto es la API


def check_link(paths: Paths, page: Path, href: str, ids_of, generated=frozenset()) -> str | None:
    if re.match(r"^(https?:|mailto:|tel:|data:|sms:|whatsapp:)", href) or href.startswith("%%SITE_URL%%"):
        return None
    url, _, anchor = href.partition("#")
    target = resolve(paths, page, url.split("?")[0])
    if target is None:
        return None
    if target.suffix == ".html" and target.parent == paths.legal:
        ids = ids_of(target)
        if ids is None:
            return f"el enlace {href} apunta a una página que no existe"
        if anchor and anchor not in ids:
            return f"el ancla #{anchor} no existe en {target.name}"
        return None
    if target not in generated and not target.exists():
        return f"el enlace {href} apunta a un archivo que no existe"
    return None


# --------------------------------------------------------------------------- verificaciones
def config_defaults(paths: Paths) -> dict[str, str]:
    text = paths.config.read_text(encoding="utf-8") if paths.config.exists() else ""
    return {m.group(1): m.group(2) for m in re.finditer(r"^\s+(\w+): [\w |]+ = \"?([^\"\s#]+)\"?", text, re.M)}


def env_values(paths: Paths) -> dict[str, str]:
    """Variables del .env de la raíz (lo que usa el servidor) con prioridad para las del entorno."""
    values = {}
    if paths.env.exists():
        for line in paths.env.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
            if m and not line.lstrip().startswith("#"):
                values[m.group(1)] = m.group(2).strip("'\"")
    values.update({k: v for k, v in os.environ.items() if re.fullmatch(r"[A-Z0-9_]+", k)})
    return {k: v for k, v in values.items() if v != ""}


def template_versions(paths: Paths) -> list[str]:
    """Problemas si la versión impresa en terminos/privacidad no coincide con la que guarda el backend."""
    problems = []
    defaults, env = config_defaults(paths), env_values(paths)
    for slug, (field, env_name) in CONFIG_VERSIONS.items():
        tpl = paths.plantillas / f"{slug}.html"
        printed = page_version(tpl.read_text(encoding="utf-8")) if tpl.exists() else None
        if not printed:
            continue
        expected = defaults.get(field)
        if expected and expected != printed:
            problems.append(f"{slug}.html: la plantilla dice Versión {printed} pero backend/app/config.py usa {expected} "
                            f"({env_name}).")
        if env.get(env_name) and env[env_name] != printed:
            problems.append(f"{slug}.html: la plantilla dice Versión {printed} pero {env_name}={env[env_name]} en el "
                            "entorno o en .env (déjala vacía).")
    return problems


def history_problems(paths: Paths, render: Render, outputs: dict[Path, str]) -> list[str]:
    """Cada versión anterior de versiones.json existe en su URL fija con la misma huella SHA-256."""
    problems = []
    for entry in render.history:
        url = entry.get("url") or ""
        target = paths.legal / Path(url).name if url.startswith("/app/legal/") else None
        content = outputs.get(target) if target is not None else None
        if content is None and target is not None and target.exists():
            content = target.read_text(encoding="utf-8")
        if content is None:
            problems.append(f"versiones.json: {entry.get('slug')} {entry.get('version')} apunta a {url}, que no existe.")
        elif sha256(content) != entry.get("sha256"):
            problems.append(f"versiones.json: {url} no coincide con su huella SHA-256 (una versión archivada no se edita).")
    return problems


def security_problems(paths: Paths, outputs: dict[Path, str], today: datetime.date, strict: bool) -> tuple[list, list]:
    text = outputs.get(paths.security)
    if text is None:
        return [], []
    m = EXPIRES_RE.search(text)
    if not m:
        return ["app/.well-known/security.txt: falta el campo Expires."], []
    try:
        expires = datetime.datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).date()
    except ValueError:
        return [f"app/.well-known/security.txt: Expires «{m.group(1)}» no es una fecha ISO 8601."], []
    msg = (f"app/.well-known/security.txt vence el {expires.isoformat()}: cambia Expires en "
           "app/legal/plantillas/security.txt (máximo un año adelante) y vuelve a generar.")
    if expires <= today:
        return [msg], []
    if expires - today <= datetime.timedelta(days=30):
        return ([msg], []) if strict else ([], [msg])
    if expires - today > datetime.timedelta(days=366):
        return [], ["app/.well-known/security.txt: Expires está a más de un año (RFC 9116 recomienda menos)."]
    return [], []


def number_in(text) -> float | None:
    m = NUMBER_RE.search(str(text))
    return float(m.group(0).replace(",", "")) if m else None


def settings_problems(paths: Paths, datos: dict) -> tuple[list[str], list[str]]:
    """Datos de las páginas que deben coincidir con la configuración del servidor (.env o valores por defecto)."""
    errors, warnings = [], []
    defaults, env = config_defaults(paths), env_values(paths)
    effective = {}
    for clave, env_name, source in SETTINGS:
        kind, _, ref = source.partition(":")
        raw = env.get(env_name) or (defaults.get(ref) if kind == "config" else ref)
        configured = number_in(raw) if raw is not None else None
        effective[env_name] = configured
        value = value_for(datos, clave)
        if not isinstance(value, str) or configured is None:
            continue
        written = number_in(value)
        if written is None:
            errors.append(f"{clave} («{value}») debe incluir el número que usa el servidor ({env_name}={raw}).")
        elif abs(written - configured) > 1e-9:
            errors.append(f"{clave} dice «{value}» pero el servidor usa {env_name}={raw}. Deben coincidir.")
    fees = [effective.get("MERCADOPAGO_MARKETPLACE_FEE_PERCENT"), effective.get("MERCADOPAGO_DONATION_FEE_PERCENT")]
    if any(f for f in fees) and value_for(datos, "VERIFICAR_REGIMEN_PLATAFORMAS") is None:
        errors.append("Hay una comisión de GuauWoow mayor que 0 % (MERCADOPAGO_MARKETPLACE_FEE_PERCENT o "
                      "MERCADOPAGO_DONATION_FEE_PERCENT) y VERIFICAR_REGIMEN_PLATAFORMAS no es true: déjalas en 0 "
                      "hasta que tu contador confirme las obligaciones de plataforma.")
    dominio = value_for(datos, "DOMINIO")
    if not isinstance(dominio, str):
        # Sin DOMINIO, Nginx cambia %%SITE_URL%% al servir la página: los bytes que recibe la persona ya no
        # coinciden con la huella SHA-256 publicada en versiones.json (historial.html)
        errors.append("DOMINIO está vacío: las páginas se servirían con %%SITE_URL%% reemplazado por Nginx y su "
                      "contenido no coincidiría con la huella SHA-256 de versiones.json. Llena DOMINIO y vuelve a "
                      "generar.")
    elif env.get("DOMAIN") and env["DOMAIN"] != dominio:
        errors.append(f"DOMINIO dice «{dominio}» pero DOMAIN={env['DOMAIN']} en .env. Deben coincidir.")
    # Cada correo dice quién lo envía (comunicaciones.html §6): el pie sale de EMISOR_NOMBRE y OPERATOR_ADDRESS
    for clave, env_name in (("RAZON_SOCIAL", "EMISOR_NOMBRE"), ("DOMICILIO_FISCAL", "OPERATOR_ADDRESS")):
        value = value_for(datos, clave)
        if isinstance(value, str) and env.get(env_name, "").strip() != value:
            errors.append(f"{clave} dice «{value}» pero {env_name}={env.get(env_name) or '(vacío)'} en .env: el pie de "
                          "los correos usa la variable del servidor (comunicaciones.html §6). Deben coincidir.")
    # Las páginas dicen que GuauWoow no recibe ni guarda el dinero de los donativos (donativos, tarifas)
    if env.get("DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT", "").strip().lower() in ("1", "true", "yes", "on"):
        errors.append("DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT=true cobraría donativos con la cuenta de la plataforma; "
                      "las páginas legales dicen que GuauWoow no recibe ese dinero. Déjala vacía o en false.")
    contacto = value_for(datos, "CORREO_DE_CONTACTO")
    if isinstance(contacto, str) and env.get("SUPPORT_EMAIL") and env["SUPPORT_EMAIL"] != contacto:
        warnings.append(f"CORREO_DE_CONTACTO ({contacto}) y SUPPORT_EMAIL ({env['SUPPORT_EMAIL']}) son distintos.")
    return errors, warnings


def notice_problems(paths: Paths, render: Render) -> list[str]:
    """Aviso previo (historial.html §2, terminos 29.2): una versión nueva de un documento que se acepta de forma
    expresa entra en vigor al menos LEGAL_NOTICE_DAYS días (30) después de la fecha de su versión. --check."""
    defaults, env = config_defaults(paths), env_values(paths)
    days = int(number_in(env.get("LEGAL_NOTICE_DAYS") or defaults.get("legal_notice_days") or "30") or 30)
    previous = render._previous_versions()
    archived = {e["slug"] for e in render.history}
    problems = []
    for page in render.pages:
        slug, version = page["slug"], page["version"]
        if not page["requires_reacceptance"] or slug not in archived:
            continue  # primera versión: no reemplaza a otra que alguien haya aceptado
        record = previous.get((slug, version))
        if record and render._in_force(record.get("effective_at")):
            continue  # ya vigente: el aviso se revisó al publicarla
        published = parse_date(version)
        effective = parse_date(page["effective_at"]) if page["effective_at"] else None
        if published is None:
            continue
        minimum = datetime.date.fromisoformat(published) + datetime.timedelta(days=days)
        if effective is None or datetime.date.fromisoformat(effective) < minimum:
            problems.append(
                f"{slug}.html versión {version} reemplaza a una versión anterior y pide aceptarla otra vez, pero entra "
                f"en vigor {'de inmediato' if effective is None else 'el ' + effective}: FECHA_DE_ENTRADA_EN_VIGOR debe "
                f"ser {minimum.isoformat()} o después ({days} días de aviso previo, LEGAL_NOTICE_DAYS).")
    return problems


def generated_problems(paths: Paths, render: Render, outputs: dict[Path, str], ejemplo: dict,
                       strict: bool = False) -> tuple[list[str], list[str]]:
    """(errores, avisos) de --check-generated; strict=True agrega lo que solo bloquea el despliegue."""
    problems, warnings = list(render.errors) + list(render.blocking), list(render.warnings)
    for path, content in outputs.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            problems.append(f"{paths.rel(path)} no está al día: corre python3 scripts/render-legal.py")
    if paths.index.exists() and paths.index not in outputs:
        problems.append(f"app/index.html no tiene el bloque {INDEX_START} ... {INDEX_END} del aviso simplificado.")
    if paths.sitemap.exists() and paths.sitemap not in outputs:
        problems.append(f"app/sitemap.xml no tiene el bloque {SITEMAP_START} ... {SITEMAP_END} de las páginas legales.")
    undocumented = sorted(set(render.used) - set(ejemplo))
    if undocumented:
        problems.append("Claves sin documentar en app/legal/datos-legales.example.json: " + ", ".join(undocumented))
    unused = sorted(set(ejemplo) - set(render.used))
    if unused:
        problems.append("Claves documentadas que ninguna plantilla usa (quítalas de datos-legales.example.json): "
                        + ", ".join(unused))
    page_errors, missing_scripts = validate_pages(paths, outputs, render.pages, render.history)
    problems += page_errors + missing_scripts + history_problems(paths, render, outputs) + template_versions(paths)
    sec_errors, sec_warnings = security_problems(paths, outputs, render.today, strict)
    return problems + sec_errors, warnings + sec_warnings


# --------------------------------------------------------------------------- CLI
def init_datos(paths: Paths, ejemplo_raw: dict, ejemplo: dict) -> int:
    current = read_json(paths.datos, {})
    merged = {"_instrucciones": ejemplo_raw.get("_instrucciones", "")}
    merged.update({k: current.get(k, "") for k in ejemplo})
    extra = {k: v for k, v in current.items() if k not in merged and not k.startswith("_")}
    merged.update({k: v for k, v in extra.items() if v not in ("", None)})
    dropped = sorted(k for k, v in extra.items() if v in ("", None))
    paths.datos.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{paths.rel(paths.datos)}: {len(ejemplo)} claves (se conservaron los valores existentes).")
    if dropped:
        print("Se quitaron claves vacías que ya no usa ninguna plantilla: " + ", ".join(dropped))
    kept = sorted(k for k in extra if k not in dropped)
    if kept:
        print("Aviso: claves con valor que ninguna plantilla usa (revísalas): " + ", ".join(kept))
    return 0


def list_keys(ejemplo_raw: dict, ejemplo: dict) -> int:
    titles = group_titles(ejemplo_raw)
    groups: dict[str, list[str]] = {}
    for clave in ejemplo:
        info = ejemplo_raw.get(clave)
        groups.setdefault(info.get("grupo", "otros") if isinstance(info, dict) else "otros", []).append(clave)
    for group in list(titles) + [g for g in groups if g not in titles]:
        if not groups.get(group):
            continue
        print(f"== {titles.get(group, group)}")
        for clave in groups[group]:
            print(f"{clave}\n    {describe(ejemplo_raw, clave)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera el centro legal de GuauWoow.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="falla (exit 1) si faltan datos, notas [VERIFICAR] o algo no cuadra")
    mode.add_argument("--check-generated", action="store_true",
                      help="falla solo si los archivos no están al día o hay páginas rotas")
    mode.add_argument("--list", action="store_true", help="lista las claves y su descripción")
    mode.add_argument("--init", action="store_true", help="crea o completa app/legal/datos-legales.json")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--hoy", type=datetime.date.fromisoformat, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    paths = Paths(args.root.resolve())
    ejemplo_raw = read_json(paths.ejemplo, {})
    ejemplo = {k: v for k, v in ejemplo_raw.items() if not k.startswith("_")}

    if args.init:
        return init_datos(paths, ejemplo_raw, ejemplo)
    if args.list:
        return list_keys(ejemplo_raw, ejemplo)

    datos = load_json(paths.datos)
    render = Render(paths, datos, today=args.hoy)
    outputs = render.outputs()
    docs = docs_text(paths, ejemplo_raw, render)
    if docs is not None:
        outputs[paths.llenar] = docs

    if args.check or args.check_generated:
        problems, warnings = generated_problems(paths, render, outputs, ejemplo, strict=args.check)
        if paths.llenar.exists() and paths.llenar not in outputs:
            warnings.append(f"docs/legal/LLENAR-DATOS.md no tiene el bloque {DOCS_START} ... {DOCS_END}.")
        pending = [] if args.check_generated else sorted(render.missing)
        if args.check:
            setting_errors, setting_warnings = settings_problems(paths, datos)
            problems += setting_errors + notice_problems(paths, render)
            warnings += setting_warnings
        if pending:
            datos_faltantes = [c for c in pending if not c.startswith("VERIFICAR_")]
            notas = [c for c in pending if c.startswith("VERIFICAR_")]
            if datos_faltantes:
                print(f"Faltan {len(datos_faltantes)} dato(s) legales en app/legal/datos-legales.json:")
                for clave in datos_faltantes:
                    print(f"  - {clave}: {describe(ejemplo_raw, clave) or render.missing[clave]}")
            if notas:
                print(f"Quedan {len(notas)} nota(s) [VERIFICAR] para revisar con tu abogado (pon true o el texto final):")
                for clave in notas:
                    print(f"  - {clave}: {render.missing[clave]}")
        for problem in problems:
            print(f"ERROR: {problem}")
        for warning in warnings:
            print(f"Aviso: {warning}")
        unknown = sorted(set(datos) - set(render.used))
        if unknown:
            print("Aviso: claves de datos-legales.json que ninguna plantilla usa: " + ", ".join(unknown))
        if pending or problems:
            return 1
        print("Textos legales completos y al día." if args.check else
              f"Textos legales generados al día ({len(render.pages)} páginas).")
        return 0

    if render.blocking:
        for problem in render.blocking:
            print(f"ERROR: {problem}", file=sys.stderr)
        print("No se generó nada.", file=sys.stderr)
        return 1
    for path, content in outputs.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"Generado: {paths.rel(path)}")
    if paths.index.exists() and paths.index not in outputs:
        print(f"Aviso: app/index.html no tiene el bloque {INDEX_START} ... {INDEX_END}; no se actualizó.", file=sys.stderr)
    for problem in render.errors + render.warnings + template_versions(paths):
        print(f"Aviso: {problem}", file=sys.stderr)
    page_errors, missing_scripts = validate_pages(paths, outputs, render.pages, render.history)
    for problem in page_errors + missing_scripts:
        print(f"Aviso: {problem}", file=sys.stderr)
    if render.missing:
        print(f"Quedan {len(render.missing)} marcador(es) sin llenar (se ven resaltados). "
              "Revisa con: python3 scripts/render-legal.py --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
