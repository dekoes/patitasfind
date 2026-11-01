"""Centro legal: generación de páginas, registro de versiones y validaciones de scripts/render-legal.py.

No usa la base de datos ni la app: corre igual con `pytest --noconftest tests/test_render_legal.py`.
En el contenedor (/app = backend) no existe scripts/; se omite salvo que PATITASFIND_REPO apunte al repo.
"""
import datetime
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path

import pytest

REPO = Path(os.environ.get("PATITASFIND_REPO") or Path(__file__).resolve().parents[2])
RENDER_SCRIPT = REPO / "scripts" / "render-legal.py"
pytestmark = pytest.mark.skipif(not RENDER_SCRIPT.exists(), reason="scripts/render-legal.py no está disponible (contenedor)")

JS_STUBS = ("cookies", "solicitudes", "reportes", "transparencia", "conservacion", "estado", "historial")
REACCEPTANCE = {"terminos", "privacidad", "terminos-tienda", "terminos-refugios", "acuerdo-datos-refugios",
                "terminos-vendedores", "terminos-clinicas", "terminos-casas-de-paso"}


@pytest.fixture(scope="module")
def rl():
    spec = importlib.util.spec_from_file_location("render_legal", RENDER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path):
    """Copia mínima del repo: plantillas, ejemplo, legal.css, config.py, páginas raíz de la app y stubs de js/."""
    root = tmp_path / "repo"
    legal = root / "app" / "legal"
    shutil.copytree(REPO / "app" / "legal" / "plantillas", legal / "plantillas")
    shutil.copy(REPO / "app" / "legal" / "datos-legales.example.json", legal)
    shutil.copy(REPO / "app" / "legal" / "legal.css", legal)
    (legal / "js").mkdir()
    for name in JS_STUBS:
        (legal / "js" / f"{name}.js").write_text("", encoding="utf-8")
    (root / "app" / "landing.html").write_text("<!doctype html><title>x</title>\n", encoding="utf-8")
    (root / "app" / "index.html").write_text(
        '<div id="privacy-short"><!-- aviso-simplificado:inicio -->viejo<!-- aviso-simplificado:fin --></div>\n',
        encoding="utf-8")
    (root / "app" / "sitemap.xml").write_text(
        "<urlset>\n  <!-- paginas-legales:inicio -->\n  <!-- paginas-legales:fin -->\n</urlset>\n", encoding="utf-8")
    (root / "backend" / "app" / "data").mkdir(parents=True)
    shutil.copy(REPO / "backend" / "app" / "config.py", root / "backend" / "app" / "config.py")
    (root / "docs" / "legal").mkdir(parents=True)
    (root / "docs" / "legal" / "LLENAR-DATOS.md").write_text("# Guía\n<!-- claves:inicio -->\n<!-- claves:fin -->\n",
                                                             encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Las variables del servidor no deben influir en las comparaciones de --check."""
    for name in ("LEGAL_TERMS_VERSION", "LEGAL_PRIVACY_VERSION", "MERCADOPAGO_MARKETPLACE_FEE_PERCENT",
                 "MERCADOPAGO_DONATION_FEE_PERCENT", "DONATION_MAX_MXN", "DONATION_DAILY_MAX_MXN", "FOUND_DOG_HOLD_DAYS",
                 "BACKUP_RETENTION_DAYS", "BACKUP_OFFSITE_RETENTION_DAYS", "DOMAIN", "SUPPORT_EMAIL", "EMISOR_NOMBRE",
                 "OPERATOR_ADDRESS", "DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT", "LEGAL_NOTICE_DAYS"):
        monkeypatch.delenv(name, raising=False)


def filled(example: dict, **extra) -> dict:
    data = {}
    for key in example:
        if key.startswith("_"):
            continue
        data[key] = True if key.startswith("VERIFICAR_") else f"Valor {key} <&>"
    data.update({
        "CORREO_DE_PRIVACIDAD": "privacidad@guauwoow.com", "CORREO_DE_SEGURIDAD": "seguridad@guauwoow.com",
        "DOMINIO": "guauwoow.com", "FECHA_DE_ENTRADA_EN_VIGOR": "2026-11-20",
        "COMISION_TIENDA": "0 %", "COMISION_DONATIVOS": "0 %", "TOPE_POR_DONATIVO": "$50,000 MXN",
        "TOPE_DIARIO_DE_DONATIVOS": "$50,000 MXN", "PLAZO_DE_RESGUARDO_DE_PERROS_ENCONTRADOS": "30 días naturales",
        "PLAZO_LOCAL_DE_RESPALDOS": "14 días naturales", "PLAZO_DE_CONSERVACION_DE_RESPALDOS_EXTERNOS": "30 días naturales",
    })
    data.update(extra)
    return data


def write_datos(root: Path, data: dict) -> None:
    (root / "app" / "legal" / "datos-legales.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def example_of(root: Path) -> dict:
    return json.loads((root / "app" / "legal" / "datos-legales.example.json").read_text(encoding="utf-8"))


def zero_marketplace_fee(root: Path) -> None:
    """--check exige comisión 0 mientras VERIFICAR_REGIMEN_PLATAFORMAS no esté confirmado."""
    config = root / "backend" / "app" / "config.py"
    text = re.sub(r"(mercadopago_marketplace_fee_percent: float = )[\d.]+", r"\g<1>0.0", config.read_text(encoding="utf-8"))
    config.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- el repositorio
def test_normalize_key(rl):
    assert rl.normalize_key("RAZÓN SOCIAL") == "RAZON_SOCIAL"
    assert rl.normalize_key("PLAZO DE ENTREGA, p. ej. 3 a 10 días hábiles") == "PLAZO_DE_ENTREGA"
    assert rl.normalize_key("TOPE POR DONATIVO: monto máximo en pesos") == "TOPE_POR_DONATIVO"
    assert rl.normalize_key("CONTACTO 24/7 PARA AUTORIDADES") == "CONTACTO_24_7_PARA_AUTORIDADES"


def test_repo_outputs_are_up_to_date(rl, capsys):
    """Las páginas del repo coinciden con las plantillas, están bien formadas, sus enlaces y scripts existen y
    todas las claves están documentadas (lo mismo que corre el CI)."""
    assert rl.main(["--check-generated", "--root", str(REPO)]) == 0, capsys.readouterr().out


def test_example_documents_exactly_the_used_keys(rl):
    paths = rl.Paths(REPO)
    render = rl.Render(paths, {})
    render.outputs()
    raw = json.loads(paths.ejemplo.read_text(encoding="utf-8"))
    example = {k for k in raw if not k.startswith("_")}
    assert set(render.used) == example and len(example) >= 250
    groups = raw["_grupos"]
    for key in example:
        info = raw[key]
        assert info["grupo"] in groups and info["descripcion"], key
        if key.startswith("VERIFICAR_"):
            assert info["revisa"] and info["sugerencia"], key
        else:
            assert info.get("ejemplo"), key
    datos = json.loads(paths.datos.read_text(encoding="utf-8"))
    assert example <= set(datos), "datos-legales.json debe tener todas las claves (python3 scripts/render-legal.py --init)"
    # Sinónimos unificados: una sola clave por dato
    for retired in ("ESTATUS_DE_LA_MARCA_ANTE_EL_IMPI", "PLAZO_DE_RESOLUCION_DE_QUEJAS", "DOMICILIO_FISCAL_SI_ES_DISTINTO",
                    "FECHA_DE_ULTIMA_REVISION_NORMATIVA", "FECHA_ULTIMA_REVISION_LEGAL", "PROVEEDOR_SMS"):
        assert retired not in example


def test_every_template_is_rendered_and_registered(rl):
    paths = rl.Paths(REPO)
    templates = sorted(p.stem for p in paths.plantillas.glob("*.html"))
    assert len(templates) >= 50 and "centro-legal" in templates
    entries = json.loads(paths.versiones.read_text(encoding="utf-8"))
    assert paths.versiones_backend.read_text(encoding="utf-8") == paths.versiones.read_text(encoding="utf-8")
    current = {}
    for entry in entries:
        assert set(entry) == {"slug", "title", "version", "effective_at", "sha256", "requires_reacceptance", "summary", "url"}
        assert entry["requires_reacceptance"] is (entry["slug"] in REACCEPTANCE)
        target = paths.legal / Path(entry["url"]).name
        assert entry["url"].startswith("/app/legal/") and target.exists(), entry["url"]
        assert rl.sha256(target.read_text(encoding="utf-8")) == entry["sha256"], entry["url"]
        if entry["url"] == f"/app/legal/{entry['slug']}.html":
            current[entry["slug"]] = entry
    assert sorted(current) == templates
    for slug, entry in current.items():
        page = (paths.legal / f"{slug}.html").read_text(encoding="utf-8")
        assert entry["title"] and entry["summary"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["version"])
        assert "<!-- PLANTILLA" not in page and "<!--INCLUIR:" not in page and rl.GENERATED in page
        assert 'data-cookie-prefs' in page and 'class="header-nav"' in page  # parciales nav-legal y pie-legal
    assert current["terminos"]["summary"].startswith("Cambios principales respecto de la versión 2026-10-16")
    # La versión anterior de los Términos queda en una URL fija
    assert any(e["slug"] == "terminos" and e["version"] == "2026-10-16" and e["url"] == "/app/legal/terminos-2026-10-16.html"
               for e in entries)


def test_template_versions_match_config(rl):
    """La versión impresa en terminos/privacidad es la que guarda el backend al aceptar (LEGAL_*_VERSION)."""
    from_config = rl.config_defaults(rl.Paths(REPO))
    assert from_config["legal_terms_version"] == from_config["legal_privacy_version"] == "2026-10-17"
    assert rl.template_versions(rl.Paths(REPO)) == []


def test_sitemap_and_security_txt(rl):
    paths = rl.Paths(REPO)
    sitemap = paths.sitemap.read_text(encoding="utf-8")
    for tpl in paths.plantillas.glob("*.html"):
        assert f"<loc>%%SITE_URL%%/app/legal/{tpl.name}</loc>" in sitemap, tpl.name
    assert "2026-10-16" not in sitemap  # las versiones archivadas no se listan
    security = paths.security.read_text(encoding="utf-8")
    assert security.startswith("Contact: mailto:") and "Expires: " in security and "Policy: https://" in security


# --------------------------------------------------------------------------- en una copia temporal
def test_render_with_placeholders_then_check(rl, repo, capsys):
    assert rl.main(["--root", str(repo)]) == 0  # sin datos: genera con marcadores visibles
    legal = repo / "app" / "legal"
    terminos = (legal / "terminos.html").read_text(encoding="utf-8")
    assert '<span class="ph">[RAZÓN SOCIAL]</span>' in terminos and "PLANTILLA:" not in terminos
    assert "ARCHIVO GENERADO" in terminos and "%%SITE_URL%%/app/legal/terminos.html" in terminos
    assert (repo / "app" / ".well-known" / "security.txt").read_text(encoding="utf-8").startswith(
        "Contact: mailto:[CORREO DE SEGURIDAD]")
    guide = (repo / "docs" / "legal" / "LLENAR-DATOS.md").read_text(encoding="utf-8")
    assert "**`RAZON_SOCIAL`**" in guide and "Valor sugerido:" in guide
    capsys.readouterr()
    assert rl.main(["--check", "--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "RAZON_SOCIAL" in out and "VERIFICAR_FACTURACION" in out
    assert rl.main(["--check-generated", "--root", str(repo)]) == 0, capsys.readouterr().out


def test_full_render_fills_everything(rl, repo, capsys):
    zero_marketplace_fee(repo)
    data = filled(example_of(repo), VERIFICAR_SENTRY="Sentry está configurado sin grabación de sesiones.")
    write_datos(repo, data)
    # El pie de los correos sale de estas variables y debe coincidir con las páginas (comunicaciones.html §6)
    (repo / ".env").write_text(f"EMISOR_NOMBRE={data['RAZON_SOCIAL']}\nOPERATOR_ADDRESS={data['DOMICILIO_FISCAL']}\n",
                               encoding="utf-8")
    assert rl.main(["--root", str(repo), "--hoy", "2026-10-17"]) == 0
    capsys.readouterr()
    assert rl.main(["--check", "--root", str(repo), "--hoy", "2026-10-17"]) == 0, capsys.readouterr().out

    legal = repo / "app" / "legal"
    for tpl in (legal / "plantillas").glob("*.html"):
        text = (legal / tpl.name).read_text(encoding="utf-8")
        assert 'class="ph"' not in text and "[VERIFICAR" not in text and "\x00" not in text, tpl.name
        assert "%%SITE_URL%%" not in text and "https://guauwoow.com/app/legal/" + tpl.name in text, tpl.name
        assert not re.search(r"<p>\s*</p>|<li>\s*</li>", text), tpl.name  # notas borradas sin párrafos vacíos
    terminos = (legal / "terminos.html").read_text(encoding="utf-8")
    assert "Valor RAZON_SOCIAL &lt;&amp;&gt;" in terminos and "<&>" not in terminos
    assert "Vigente desde: 2026-11-20" in terminos
    privacidad = (legal / "privacidad.html").read_text(encoding="utf-8")
    assert '<a href="mailto:privacidad@guauwoow.com">privacidad@guauwoow.com</a>' in privacidad
    assert "<!--INCLUIR" not in privacidad and "https://guauwoow.com/app/legal/privacidad.html" in privacidad
    cookies = (legal / "cookies.html").read_text(encoding="utf-8")
    assert "Sentry está configurado sin grabación de sesiones." in cookies
    txt = (legal / "aviso-simplificado.txt").read_text(encoding="utf-8")
    assert "[" not in txt and "Valor RAZON_SOCIAL <&>" in txt and "privacidad@guauwoow.com" in txt
    security = (repo / "app" / ".well-known" / "security.txt").read_text(encoding="utf-8")
    assert "Contact: mailto:seguridad@guauwoow.com" in security
    assert "https://guauwoow.com/.well-known/security.txt" in security
    index = (repo / "app" / "index.html").read_text(encoding="utf-8")
    assert "viejo" not in index and '<a href="/app/legal/privacidad.html" target="_blank" rel="noopener">' in index
    assert "<b>Aviso de privacidad simplificado.</b>" in index
    entries = json.loads((legal / "versiones.json").read_text(encoding="utf-8"))
    assert {e["effective_at"] for e in entries} == {"2026-11-20"}


def test_check_detects_stale_outputs_and_version_mismatch(rl, repo, capsys):
    assert rl.main(["--root", str(repo)]) == 0
    plantilla = repo / "app" / "legal" / "plantillas" / "terminos.html"
    plantilla.write_text(plantilla.read_text(encoding="utf-8").replace("Índice", "Contenido", 1), encoding="utf-8")
    capsys.readouterr()
    assert rl.main(["--check-generated", "--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "app/legal/terminos.html no está al día" in out and "versiones.json no está al día" in out

    assert rl.main(["--root", str(repo)]) == 0
    config = repo / "backend" / "app" / "config.py"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace('legal_terms_version: str = "', 'legal_terms_version: str = "1999-01-01"  # "', 1),
                      encoding="utf-8")
    capsys.readouterr()
    assert rl.main(["--check-generated", "--root", str(repo)]) == 1
    assert "LEGAL_TERMS_VERSION" in capsys.readouterr().out


def test_inconsistent_version_mentions_fail(rl, repo, capsys):
    plantilla = repo / "app" / "legal" / "plantillas" / "terminos-tienda.html"
    text = plantilla.read_text(encoding="utf-8")
    assert "Versión 2026-10-17" in text
    plantilla.write_text(text.replace("Versión 2026-10-17", "Versión 2026-10-01", 1), encoding="utf-8")
    assert rl.main(["--root", str(repo)]) == 0
    capsys.readouterr()
    assert rl.main(["--check-generated", "--root", str(repo)]) == 1
    assert "terminos-tienda.html: dice «Versión 2026-10-01»" in capsys.readouterr().out


def test_new_version_archives_previous_one(rl, repo, capsys):
    assert rl.main(["--root", str(repo)]) == 0
    legal = repo / "app" / "legal"
    old = (legal / "cookies.html").read_text(encoding="utf-8")
    plantilla = legal / "plantillas" / "cookies.html"
    text = plantilla.read_text(encoding="utf-8").replace("<li>Versión: 2026-10-17</li>", "<li>Versión: 2027-01-15</li>")
    plantilla.write_text(text, encoding="utf-8")
    assert rl.main(["--root", str(repo)]) == 0
    archive = legal / "cookies-2026-10-17.html"
    assert archive.read_text(encoding="utf-8") == old
    entries = [e for e in json.loads((legal / "versiones.json").read_text(encoding="utf-8")) if e["slug"] == "cookies"]
    assert [e["version"] for e in entries] == ["2027-01-15", "2026-10-17"]
    assert entries[1]["url"] == "/app/legal/cookies-2026-10-17.html" and entries[1]["sha256"] == rl.sha256(old)
    capsys.readouterr()
    assert rl.main(["--check-generated", "--root", str(repo)]) == 0, capsys.readouterr().out
    # Una versión archivada no se edita
    archive.write_text(old.replace("Cookies", "Galletas", 1), encoding="utf-8")
    assert rl.main(["--check-generated", "--root", str(repo)]) == 1
    assert "cookies-2026-10-17.html no coincide con su huella SHA-256" in capsys.readouterr().out


def test_effective_version_is_frozen(rl, repo, capsys):
    zero_marketplace_fee(repo)
    data = filled(example_of(repo), FECHA_DE_ENTRADA_EN_VIGOR="2026-11-01")
    write_datos(repo, data)
    assert rl.main(["--root", str(repo), "--hoy", "2026-10-20"]) == 0
    # Ya vigente: otra fecha de entrada en vigor (para una versión futura) no cambia la de esta versión
    write_datos(repo, {**data, "FECHA_DE_ENTRADA_EN_VIGOR": "2027-03-01"})
    capsys.readouterr()
    assert rl.main(["--check-generated", "--root", str(repo), "--hoy", "2026-12-01"]) == 0, capsys.readouterr().out
    # Antes de entrar en vigor sí puede cambiar
    assert rl.main(["--check-generated", "--root", str(repo), "--hoy", "2026-10-25"]) == 1
    # Cambiar el texto de un documento vigente que se acepta: no se genera nada
    write_datos(repo, {**data, "RAZON_SOCIAL": "Otra razón social, S.A.S."})
    terminos = (repo / "app" / "legal" / "terminos.html").read_text(encoding="utf-8")
    capsys.readouterr()
    assert rl.main(["--root", str(repo), "--hoy", "2026-12-01"]) == 1
    assert "versión vigente no se edita" in capsys.readouterr().err
    assert (repo / "app" / "legal" / "terminos.html").read_text(encoding="utf-8") == terminos


def test_settings_must_match_server(rl, repo, capsys):
    data = filled(example_of(repo), COMISION_TIENDA="10 %", TOPE_POR_DONATIVO="$20,000 MXN", DOMINIO="otro.mx",
                  VERIFICAR_REGIMEN_PLATAFORMAS="")
    write_datos(repo, data)
    (repo / ".env").write_text("DOMAIN=guauwoow.com\nMERCADOPAGO_MARKETPLACE_FEE_PERCENT=10\n", encoding="utf-8")
    assert rl.main(["--root", str(repo)]) == 0
    capsys.readouterr()
    assert rl.main(["--check", "--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "TOPE_POR_DONATIVO dice «$20,000 MXN» pero el servidor usa DONATION_MAX_MXN=50000.0" in out
    assert "VERIFICAR_REGIMEN_PLATAFORMAS no es true" in out
    assert "DOMINIO dice «otro.mx» pero DOMAIN=guauwoow.com" in out
    assert "COMISION_TIENDA dice" not in out  # 10 % coincide con el .env


def test_broken_pages_are_reported(rl, repo, capsys):
    plantilla = repo / "app" / "legal" / "plantillas" / "accesibilidad.html"
    text = plantilla.read_text(encoding="utf-8")
    text = text.replace('href="historial.html"', 'href="historial.html#no-existe"', 1)
    text = text.replace("<p>", "<p><div>bloque</div>", 1)
    text = text.replace("</main>", '<a href="no-existe.html">x</a><script src="js/falta.js"></script></main>', 1)
    plantilla.write_text(text, encoding="utf-8")
    (repo / "app" / "legal" / "js" / "estado.js").unlink()
    assert rl.main(["--root", str(repo)]) == 0  # genera, pero avisa
    capsys.readouterr()
    assert rl.main(["--check-generated", "--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "el ancla #no-existe no existe en historial.html" in out
    assert "<div> dentro de <p>" in out
    assert "el enlace no-existe.html apunta a una página que no existe" in out
    assert "falta app/legal/js/falta.js" in out and "falta app/legal/js/estado.js" in out


def test_unknown_include_and_leaked_notes(rl, repo):
    plantilla = repo / "app" / "legal" / "plantillas" / "creditos.html"
    text = plantilla.read_text(encoding="utf-8")
    plantilla.write_text(text.replace("<!--INCLUIR:pie-legal-->", "<!--INCLUIR:no-existe-->", 1), encoding="utf-8")
    with pytest.raises(SystemExit, match="INCLUIR:no-existe"):
        rl.main(["--root", str(repo)])
    note = "<!-- PLANTILLA: nota interna\n con varias líneas y una flecha -> aquí -->"
    plantilla.write_text(text.replace("</main>", f"<p>Antes {note} después.</p>\n  {note}\n</main>", 1), encoding="utf-8")
    assert rl.main(["--root", str(repo)]) == 0
    rendered = (repo / "app" / "legal" / "creditos.html").read_text(encoding="utf-8")
    assert "PLANTILLA" not in rendered and "nota interna" not in rendered and "<p>Antes  después.</p>" in rendered


def test_security_txt_expiry(rl, repo, capsys):
    assert rl.main(["--root", str(repo)]) == 0
    expires = re.search(r"Expires: (\d{4}-\d{2}-\d{2})", (repo / "app" / ".well-known" / "security.txt").read_text()).group(1)
    day = datetime.date.fromisoformat(expires)
    capsys.readouterr()
    soon = (day - datetime.timedelta(days=10)).isoformat()
    assert rl.main(["--check-generated", "--root", str(repo), "--hoy", soon]) == 0  # en CI solo avisa
    assert "security.txt vence" in capsys.readouterr().out
    late = (day + datetime.timedelta(days=1)).isoformat()
    assert rl.main(["--check-generated", "--root", str(repo), "--hoy", late]) == 1


def test_init_and_list(rl, repo, capsys):
    datos = repo / "app" / "legal" / "datos-legales.json"
    datos.write_text(json.dumps({"RFC": "PFM2601011A2", "CLAVE_VIEJA": "", "OTRA_VIEJA": "con valor"}), encoding="utf-8")
    assert rl.main(["--init", "--root", str(repo)]) == 0
    merged = json.loads(datos.read_text(encoding="utf-8"))
    assert merged["RFC"] == "PFM2601011A2" and "CLAVE_VIEJA" not in merged and merged["OTRA_VIEJA"] == "con valor"
    assert set(example_of(repo)) - {"_grupos"} <= set(merged)
    capsys.readouterr()
    assert rl.main(["--list", "--root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "== Identidad y empresa" in out and "RAZON_SOCIAL" in out and "== Notas VERIFICAR para tu abogado" in out


def test_summary_parsing(rl):
    section = ('<section class="card section" id="versiones"><ul><li>Versión: 2026-10-17</li></ul>'
               "<p>Primera versión de este Acuerdo. Consulta todas las versiones en el <a>historial</a>.</p></section>")
    assert rl.page_summary(section) == "Primera versión de este Acuerdo."
    generic = ('<section id="versiones"><ul><li>Versión: 2026-10-17</li></ul>'
               "<p>Las versiones anteriores están en el historial.</p></section>")
    assert rl.page_summary(generic) == rl.DEFAULT_SUMMARY
    explicit = '<section id="versiones"><p class="resumen-version">Se agregó la sección 4.</p></section>'
    assert rl.page_summary(explicit) == "Se agregó la sección 4."
    assert rl.parse_date("1 de noviembre de 2026") == "2026-11-01" and rl.parse_date("mañana") is None
