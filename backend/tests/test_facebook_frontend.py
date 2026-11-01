"""Frontend de Facebook (F2–F3): contrato entre la app/panel y el backend.

- Pruebas de API (corren en el contenedor): las peticiones se arman EXACTAMENTE como las mandan
  app/compartir.js (POST /facebook/volunteer-import) y app/admin-facebook.js (grupos, CSV, estadísticas,
  lectura manual), y se revisan los campos de la respuesta que esas pantallas leen.
- Pruebas estáticas de los archivos del frontend (manifest con share_target, ids que usan los scripts,
  estados iguales a los del backend). Dentro del contenedor (/app = backend) no está app/: se omiten salvo que
  PATITASFIND_REPO apunte al repo completo (como en CI).

Nunca se llama a Apify ni a Facebook: el proveedor queda sin token o se sustituye el despacho de tareas.
"""
import json
import os
import re
import uuid
from pathlib import Path

import pytest

from app.config import settings
from app.data import estados_mx
from app.database import SessionLocal
from app.models import FacebookGroup, User
from app.routers import facebook as fb_router
from app.services import background
from app.services import facebook_groups as fbg

from conftest import _register, make_jpeg

REPO = Path(os.environ.get("PATITASFIND_REPO") or Path(__file__).resolve().parents[2])
APP_DIR = REPO / "app"
needs_frontend = pytest.mark.skipif(not (APP_DIR / "compartir.js").exists(),
                                    reason="app/ no está disponible (contenedor); usa PATITASFIND_REPO")


def _uid() -> str:
    return uuid.uuid4().hex[:10]


class Recorder:
    """Sustituye a dispatch: guarda (tarea, args) sin ejecutar nada (sin Celery ni red)."""

    def __init__(self):
        self.calls = []

    def __call__(self, task_path, *args, background_tasks=None):
        self.calls.append((task_path, args))
        return "test"


@pytest.fixture
def no_tasks(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(background, "dispatch", rec)
    monkeypatch.setattr(fbg, "dispatch", rec)
    monkeypatch.setattr(fb_router, "dispatch", rec)
    return rec


def _set_role(email, role):
    db = SessionLocal()
    try:
        db.query(User).filter(User.email == email).update({User.role: role})
        db.commit()
    finally:
        db.close()


@pytest.fixture
def admin(client):
    u = _register(client, "Admin Panel Facebook")
    _set_role(u["email"], "admin")
    yield u
    _set_role(u["email"], "user")  # que la base de desarrollo no acumule admins de prueba


@pytest.fixture
def cleanup_groups():
    urls: list[str] = []
    yield urls
    db = SessionLocal()
    try:
        db.query(FacebookGroup).filter(FacebookGroup.group_url.in_(urls)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- app: voluntarios (compartir.js)
def test_volunteer_import_with_app_payload(client, user, no_tasks):
    """Mismo cuerpo que submitShare(): url limpia, texto, ciudad, estado del selector (nombre oficial), tipo, fotos y
    la aceptación de la leyenda (#sh-consent)."""
    up = client.post("/upload/multiple", headers=user["h"], files=[("files", ("p.jpg", make_jpeg(11), "image/jpeg"))])
    assert up.status_code == 200, up.text
    photos = up.json()["urls"]
    url = f"https://www.facebook.com/groups/ejemplo{_uid()}/posts/1"
    body = {"url": url, "text": "Se perdió perrito café en Ecatepec, responde a Rocky. Llamar 55 1234 5678",
            "city": "Ecatepec", "state": "México", "report_type": "lost", "photos": photos, "consent": True}
    r = client.post("/facebook/volunteer-import", headers=user["h"], json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    # Lo que leen showShareDone() y el detalle del reporte (etiqueta «vía voluntario»)
    assert isinstance(data["id"], int) and data["source"] == "volunteer"
    assert data["state"] == "México" and data["report_type"] == "lost" and data["photos"] == photos
    assert "1234 5678" not in (data.get("description") or "")
    public = client.get(f"/lost-reports/{data['id']}")
    assert public.status_code == 200 and public.json()["source"] == "volunteer"
    # Lo que lee Compartir.importedHtml(): enlace al original (solo importados) y fecha si se conoce
    assert public.json()["external_url"] == url and "external_posted_at" in public.json()

    # Duplicado: 409 con report_id (compartir.js lo usa para «Ver el reporte»)
    dup = client.post("/facebook/volunteer-import", headers=user["h"], json=body)
    assert dup.status_code == 409
    assert dup.json()["report_id"] == data["id"] and dup.json()["detail"]


@pytest.mark.parametrize("state", ["Estado de México", "Ciudad de México", "Nuevo León"])
def test_volunteer_import_accepts_state_names_from_app(client, make_user, no_tasks, state):
    """El selector manda el nombre oficial corto; el geocodificador puede dar el largo: ambos se normalizan."""
    u = make_user("Voluntaria Estados")
    r = client.post("/facebook/volunteer-import", headers=u["h"], json={
        "url": f"https://www.facebook.com/groups/g{_uid()}/posts/{_uid()}", "text": "Encontré este perrito, busca a su familia",
        "city": None, "state": state, "report_type": "found", "photos": [], "consent": True})
    assert r.status_code == 201, r.text
    assert r.json()["state"] == estados_mx.normalize_state(state)


def test_lost_report_form_sends_state(client, user, no_tasks, monkeypatch):
    """El formulario de perdido/encontrado manda «state» (Compartir.reportState('rf'))."""
    monkeypatch.setattr(settings, "apify_token", None)
    r = client.post("/lost-reports", headers=user["h"], json={
        "dog_name": "Rocky E2E", "report_type": "lost", "city": "Roma Norte, CDMX", "country": "México",
        "state": "Ciudad de México", "latitude": 19.4326, "longitude": -99.1332, "photos": []})
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "Ciudad de México"


# --------------------------------------------------------------------------- panel: admin-facebook.js
def test_admin_panel_group_flow(client, admin, user, no_tasks, cleanup_groups, monkeypatch):
    monkeypatch.setattr(settings, "apify_token", None)  # proveedor no configurado: sin lecturas
    url = f"https://www.facebook.com/groups/panel{_uid()}"
    cleanup_groups.append(url)
    # Alta como la manda el formulario (incluye kind y url, que el backend ignora)
    payload = {"name": "Perritos perdidos Mérida (prueba)", "group_url": url, "state": "Yucatán", "city": "Mérida",
               "is_active": True, "kind": "group", "url": url}
    assert client.post("/admin/facebook/groups", headers=user["h"], json=payload).status_code == 403
    r = client.post("/admin/facebook/groups", headers=admin["h"], json=payload)
    assert r.status_code == 201, r.text
    g = r.json()
    for field in ("id", "name", "group_url", "state", "city", "is_active", "kind", "last_fetched_at", "last_post_at",
                  "posts_fetched_total", "reports_created_total", "cost_estimate_total", "last_error"):
        assert field in g, field
    assert g["kind"] == "group" and g["state"] == "Yucatán"

    # Lista con los parámetros del panel: kind=group y state
    listed = client.get("/admin/facebook/groups", headers=admin["h"], params={"kind": "group", "state": "Yucatán"})
    assert listed.status_code == 200 and isinstance(listed.json(), list)
    assert g["id"] in [x["id"] for x in listed.json()]
    assert all(x["kind"] == "group" for x in listed.json())

    # Editar (mismo cuerpo que el formulario) y pausar
    r = client.patch(f"/admin/facebook/groups/{g['id']}", headers=admin["h"], json={
        "name": "Perritos perdidos Yucatán (prueba)", "group_url": url, "state": "Yucatán", "city": None, "is_active": True})
    assert r.status_code == 200, r.text
    assert r.json()["city"] is None
    r = client.patch(f"/admin/facebook/groups/{g['id']}", headers=admin["h"], json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    # «Leer ahora» sin APIFY_TOKEN: error claro (el panel lo muestra tal cual)
    r = client.post(f"/admin/facebook/groups/{g['id']}/fetch", headers=admin["h"])
    assert r.status_code == 503 and "APIFY_TOKEN" in r.json()["detail"]

    assert client.delete(f"/admin/facebook/groups/{g['id']}", headers=admin["h"]).status_code == 204


def test_admin_stats_fields_read_by_panel(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "apify_token", None)
    r = client.get("/admin/facebook/stats", headers=admin["h"])
    assert r.status_code == 200, r.text
    st = r.json()
    # Aviso del proveedor
    assert st["provider_configured"] is False and st["actor"]
    # Barra de gasto contra presupuesto
    budget = st["budget"]
    for key in ("daily_budget_usd", "spent_today_usd", "remaining_usd", "exhausted", "cost_per_1000_posts_usd"):
        assert key in budget, key
    # Textos del aviso y costo máximo de «Leer ahora»
    for key in ("fetch_interval_hours", "post_ttl_days", "max_posts_per_run"):
        assert key in st["settings"], key
    # Historial por día (el panel acepta "history" o "daily") y estadísticas por grupo (resumen sin el filtro de estado)
    days = st.get("history", st.get("daily"))
    assert isinstance(days, list) and {"date", "spent_usd"} <= set(days[0])
    assert isinstance(st["groups"], list)
    assert "volunteer_reports" in st["totals"]
    monkeypatch.setattr(settings, "apify_token", "token-de-prueba")
    assert client.get("/admin/facebook/stats", headers=admin["h"]).json()["provider_configured"] is True


def test_admin_csv_import_like_panel(client, admin, cleanup_groups):
    """El panel manda el archivo original en multipart (campo "file"); acepta ";" y encabezados en español."""
    a, b = f"https://www.facebook.com/groups/csv{_uid()}", f"https://www.facebook.com/groups/csv{_uid()}"
    cleanup_groups.extend([a, b])
    csv_text = ("﻿name,state,city,group_url\n"
                f"\"Perritos perdidos Zapopan, Jal. (prueba)\",Jalisco,Zapopan,{a}\n"
                f"Grupo sin ciudad (prueba),Estado de México,,{b}\n"
                "Fila mala,Narnia,,https://example.com/x\n")
    r = client.post("/admin/facebook/groups/import-csv", headers=admin["h"],
                    files={"file": ("grupos.csv", csv_text.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["created"] == 2 and len(res["errors"]) == 1 and res["errors"][0]["line"] == 4
    assert res["message"]
    # Excel en español: punto y coma y Latin-1
    excel = f"nombre;estado;ciudad;url\nPerritos Querétaro (prueba);Querétaro;Querétaro;{a}\n".encode("latin-1")
    r = client.post("/admin/facebook/groups/import-csv", headers=admin["h"],
                    files={"file": ("excel.csv", excel, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    db = SessionLocal()
    try:
        g = db.query(FacebookGroup).filter(FacebookGroup.group_url == a).first()
        assert g.state == "Querétaro" and g.name == "Perritos Querétaro (prueba)"
        assert db.query(FacebookGroup).filter(FacebookGroup.group_url == b).first().state == "México"
    finally:
        db.close()


# --------------------------------------------------------------------------- archivos del frontend
def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _ids_used(js: str) -> set[str]:
    """Ids fijos que un script busca con $('#id') / $("#id") (no los que arma con plantillas)."""
    return set(re.findall(r"""\$\(\s*['"]#([A-Za-z][\w-]*)['"]""", js))


def _ids_in(html: str) -> set[str]:
    return set(re.findall(r"""\sid=["']([^"']+)["']""", html))


@needs_frontend
def test_manifest_share_target():
    m = json.loads(_read("app/manifest.webmanifest"))
    st = m["share_target"]
    assert st["method"] == "GET" and st["action"].startswith(m["scope"])
    assert st["params"] == {"title": "title", "text": "text", "url": "url"}


@needs_frontend
def test_compartir_ids_exist_and_script_order():
    js, html = _read("app/compartir.js"), _read("app/index.html")
    # Los del detalle de un reporte importado (#rp-author...) los arma la propia plantilla de compartir.js
    missing = _ids_used(js) - _ids_in(html) - _ids_in(js)
    assert not missing, f"ids que usa compartir.js y no están en index.html: {missing}"
    # Se expone en window (app.js lo consulta con window.Compartir) y carga después de app.js
    assert "window.Compartir =" in js
    assert html.index("/app/app.js") < html.index("/app/compartir.js")
    app_js = _read("app/app.js")
    assert "Compartir.reportState('rf')" in app_js and "Compartir.openFromParams" in app_js


@needs_frontend
def test_admin_facebook_ids_exist_and_section_moved():
    js, html = _read("app/admin-facebook.js"), _read("app/admin.html")
    missing = _ids_used(js) - _ids_in(html)
    assert not missing, f"ids que usa admin-facebook.js y no están en admin.html: {missing}"
    assert html.index("/admin/admin.js") < html.index("/app/admin-facebook.js")
    assert "async function loadFacebook" in js
    assert "function loadFacebook" not in _read("app/admin.js")  # ya no está duplicada en admin.js
    assert "Proveedor no configurado (APIFY_TOKEN)" in js


@needs_frontend
def test_frontend_states_match_backend():
    names = set(estados_mx.STATE_NAMES)
    comp = _read("app/compartir.js")
    block = comp[comp.index("const MX_STATES"):comp.index("const STATE_NAMES")]
    assert set(re.findall(r"\[\s*'([^']+)',\s*\[", block)) == names
    adm = _read("app/admin-facebook.js")
    block = adm[adm.index("const FB_STATES"):adm.index("];", adm.index("const FB_STATES"))]
    assert set(re.findall(r'"([^"]+)"', block)) == names


@needs_frontend
def test_docs_csv_format_and_warning():
    doc = _read("docs/facebook-grupos.md")
    assert "name,state,city,group_url" in doc
    assert "verificar antes de activar" in doc
    assert "APIFY_TOKEN" in doc and "share_target" in doc


@needs_frontend
def test_imported_report_detail_hooks():
    """Detalle de un reporte importado: etiqueta con enlace al original y «Soy el autor: retirar» sin cuenta."""
    js, app_js = _read("app/compartir.js"), _read("app/app.js")
    assert "Compartir.importedHtml(r)" in app_js and "Compartir.bindImported(r)" in app_js
    assert "/facebook/author-removal" in js and 'rel="noopener noreferrer nofollow"' in js
    assert "consent: true" in js  # submitShare manda la aceptación de la leyenda
    # La copia ya no promete alertas a vecinos (los envíos no tienen coordenadas)
    assert "Avisamos a la gente de la zona" not in js and "refugios y casas de paso de tu ciudad" in js
    # No hay manejadores en línea (CSP)
    assert not re.search(r"\son[a-z]+=\"", js)
