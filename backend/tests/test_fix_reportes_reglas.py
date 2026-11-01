"""Correcciones de la revisión: reportes públicos (enlaces, acuses, alertas), cuarentena PREVENTIVA de lo que un
reporte señala como abuso sexual infantil, niveles de los requerimientos de autoridades, efectos sobre WhatsApp y
retiro de publicaciones importadas en el centro de solicitudes, supresión complementaria de la transparencia,
identidad del vendedor, base de la bonificación, retenciones de fichas de adopción, perros encontrados e
interruptor legal de Facebook."""
import datetime
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AuthorityRequest, BlockedImageHash, ComplianceRequest, ContentReport, Dog, EvidenceRecord, LostReport,
    ModerationAction, Notification, Refuge, User,
)
from app.routers import cumplimiento_reportes as cr
from app.routers import cumplimiento_transparencia as tr
from app.services import facebook_monitor, images, legal_moderation as lm, reglas, solicitudes as sol, staydown
from tests.conftest import random_ip, random_phone
from tests.test_moderacion_legal import (
    _dog, _dog_row, _make_superadmin, _public_report, _query, _seed, _set, _staff, _upload,
)

API = "/cumplimiento/solicitudes"


@pytest.fixture(autouse=True)
def _fresh_staydown():
    staydown.invalidate_cache()
    yield
    staydown.invalidate_cache()


@pytest.fixture
def quiet(monkeypatch):
    """Sin correos ni despachos externos; devuelve los correos de las solicitudes."""
    sent = []
    monkeypatch.setattr(sol, "_send_email", lambda to, title, body, url=None: sent.append(
        {"to": to, "title": title, "body": body, "url": url}))
    monkeypatch.setattr("app.services.notify._dispatch", lambda *a, **k: None)
    return sent


def _ip():
    return {"X-Real-IP": random_ip()}


def _now():
    return datetime.datetime.utcnow()


# =========================================================================== reportes públicos
def test_one_anonymous_minor_report_does_not_lock_an_account(client, make_user):
    victim = make_user("Cuenta señalada")
    vid = _set(victim["email"])
    r = _public_report(client, target_type="user", target_id=vid, reason="involucra_menor",
                       details="Creo que esta cuenta es de una niña")
    assert r.status_code == 201, r.text
    assert client.post("/dogs", headers=victim["h"], json={"name": "Max", "size": "Mediano"}).status_code == 201


def test_resolve_url_needs_the_full_generated_name(client, owner, jpeg):
    url = _upload(client, owner, jpeg(_seed())).json()["url"]
    dog = _dog(client, owner, photos=[url])
    name, ext = url.rsplit("/", 1)[-1].rsplit(".", 1)
    db = SessionLocal()
    try:
        assert lm.resolve_url(db, url) == ("dog", dog["id"])
        assert lm.resolve_url(db, url.replace(f"{name}.{ext}", f"{name}_thumb.jpg")) == ("dog", dog["id"])
        for fragment in ("a", name[:1], name[:8], name[:-1]):
            assert lm.resolve_url(db, f"/uploads/{fragment}.{ext}") is None, fragment
    finally:
        db.close()


def test_minor_ack_text_and_ack_emails_capped_per_address(client, monkeypatch):
    r = _public_report(client, reason="involucra_menor", details="Una foto de mi hija en un perfil",
                       target_url="https://otro-sitio.example/foto")
    assert r.status_code == 201 and "Lo revisamos con prioridad." in r.json()["mensaje"], r.text
    sent = []
    monkeypatch.setattr(lm, "send_email", lambda to, *a, **k: sent.append(to))
    email = f"buzon-{uuid.uuid4().hex[:8]}@pruebas.mx"
    for i in range(cr.ACK_EMAILS_PER_ADDRESS_DAY + 2):
        assert _public_report(client, details=f"Reporte número {i} sin enlace", email=email).status_code == 201
    assert sent.count(email) == cr.ACK_EMAILS_PER_ADDRESS_DAY
    # Correo al equipo: uno por contenido y hora
    key = f"prueba:{uuid.uuid4().hex}"
    assert lm._alert_email_allowed(key, False) is True
    assert lm._alert_email_allowed(key, False) is False


# =========================================================================== cuarentena preventiva
def test_reported_csam_is_preventive_until_a_superadmin_decides(client, owner, make_user, jpeg):
    admin = _staff(make_user)
    superadmin = _make_superadmin(client)
    data = jpeg(_seed())
    url = _upload(client, owner, data).json()["url"]
    dog = _dog(client, owner, photos=[url])
    path = images.local_path_for(url)
    thumb = path.with_name(f"{path.stem}_thumb.jpg")
    r = _public_report(client, target_url=url, reason="abuso_sexual_infantil", details="Material de abuso")
    assert r.status_code == 201 and r.json()["oculto"] is True, r.text
    report = _query(ContentReport, ContentReport.folio == r.json()["folio"])[0]

    # Oculta y fuera de /uploads (restaurable), sin bloqueo por hash, sin denuncia y sin medida
    assert not path.exists() and not thumb.exists() and client.get(url).status_code == 404
    row = _dog_row(dog["id"])
    assert row.is_hidden is True and row.photos == [url]
    pending = _query(EvidenceRecord, EvidenceRecord.content_report_id == report.id)[0]
    assert pending.kind == lm.PENDING_QUARANTINE_KIND and pending.is_csam and pending.legal_hold
    assert not _query(BlockedImageHash, BlockedImageHash.evidence_id == pending.id)
    assert not _query(AuthorityRequest, AuthorityRequest.content_report_id == report.id)
    assert not _query(ModerationAction, ModerationAction.evidence_id == pending.id)
    # Otra persona puede subir la misma imagen (no está bloqueada ni se avisa de un «reintento»)
    other = make_user("Otra persona")
    assert _upload(client, other, data).status_code == 200

    # Vista protegida: metadatos y señales, nunca el material
    signals = client.get(f"/admin/cumplimiento/reportes/{report.id}/senales", headers=admin["h"])
    assert signals.status_code == 200 and "data_b64" not in signals.text
    assert signals.json()["reportantes"]["sin_cuenta"] == 1 and signals.json()["archivos"][0]["ancho"]
    # Solo un superadmin decide; la cola general solo admite confirmar o descartar
    motivo = {"motivo": "Revisé las señales: es la foto de un perro"}
    assert client.post(f"/admin/cumplimiento/reportes/{report.id}/descartar-cuarentena", headers=admin["h"],
                       json=motivo).status_code == 403
    assert client.patch(f"/admin/reports/{report.id}", headers=admin["h"],
                        json={"status": "dismissed", "notes": "Es un perro, no hay nada"}).status_code == 403
    assert client.patch(f"/admin/reports/{report.id}", headers=superadmin["h"],
                        json={"status": "resolved", "action": "hide_content"}).status_code == 400

    out = client.post(f"/admin/cumplimiento/reportes/{report.id}/descartar-cuarentena", headers=superadmin["h"],
                      json=motivo)
    assert out.status_code == 200 and out.json()["restored_files"] == 1 and out.json()["unhidden"] is True, out.text
    assert path.exists() and thumb.exists() and client.get(url).status_code == 200
    assert _dog_row(dog["id"]).is_hidden is False
    assert _query(ContentReport, ContentReport.id == report.id)[0].status == "dismissed"
    assert _query(EvidenceRecord, EvidenceRecord.id == pending.id)[0].legal_hold is False  # plazo normal


def test_reported_csam_on_an_account_or_refuge_never_quarantines(client, make_user):
    target = make_user("Cuenta reportada")
    tid = _set(target["email"])
    r = _public_report(client, target_type="user", target_id=tid, reason="abuso_sexual_infantil",
                       details="Su foto de perfil es inapropiada")
    assert r.status_code == 201, r.text
    report = _query(ContentReport, ContentReport.folio == r.json()["folio"])[0]
    assert report.priority == 0 and not report.auto_hidden
    assert not _query(AuthorityRequest, AuthorityRequest.content_report_id == report.id)
    assert not _query(EvidenceRecord, EvidenceRecord.content_report_id == report.id)


# =========================================================================== autoridades
def test_authority_level_comes_from_what_is_requested(client, make_user):
    admin = _staff(make_user)
    base = {"authority_name": "Fiscalía de prueba", "authority_type": "ministerio_publico", "authenticity_verified": True,
            "legal_basis": "CNPP art. 212"}
    r = client.post("/admin/cumplimiento/autoridades", headers=admin["h"], json={**base, "kind": "comunicaciones",
                                                                               "level": 1})
    assert r.status_code == 201 and r.json()["level"] == 2, r.text
    item = r.json()
    lowered = client.patch(f"/admin/cumplimiento/autoridades/{item['id']}", headers=admin["h"], json={"level": 1})
    assert lowered.status_code == 200 and lowered.json()["level"] == 2
    deny = client.patch(f"/admin/cumplimiento/autoridades/{item['id']}", headers=admin["h"], json={"status": "entregado"})
    assert deny.status_code == 400 and "autorización judicial" in deny.json()["detail"]
    # «Otro» y similares: el nivel se indica siempre
    assert client.post("/admin/cumplimiento/autoridades", headers=admin["h"],
                       json={**base, "kind": "otro"}).status_code == 400
    other = client.post("/admin/cumplimiento/autoridades", headers=admin["h"], json={**base, "kind": "otro", "level": 3})
    assert other.status_code == 201 and other.json()["level"] == 3
    deny = client.patch(f"/admin/cumplimiento/autoridades/{other.json()['id']}", headers=admin["h"],
                        json={"status": "entregado"})
    assert deny.status_code == 400 and "Juez de control" in deny.json()["detail"]
    # Una denuncia nuestra no necesita nivel
    assert client.post("/admin/cumplimiento/autoridades", headers=admin["h"],
                       json={**base, "kind": "denuncia", "direction": "saliente"}).status_code == 201


# =========================================================================== solicitudes
def _admin_row(email: str):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        db.expunge(u)
        return u
    finally:
        db.close()


def test_whatsapp_effects_need_a_proven_number(client, make_user, quiet):
    admin = _staff(make_user)
    phone = random_phone()
    db = SessionLocal()
    try:
        actor = db.query(User).filter(User.email == admin["email"]).first()
        for kind, details, kwargs in (("cancelacion", {"alcance": "whatsapp"}, {"delete_whatsapp": True}),
                                      ("revocacion", {"permisos": ["whatsapp"]}, {})):
            req = sol.create_solicitud(
                db, kind=kind, name="Persona Prueba", description="Quiero que borren mis datos de WhatsApp.",
                email=f"wa-{uuid.uuid4().hex[:8]}@pruebas.mx", phone=phone, details=details)
            req.identity_verified_at, req.identity_method = _now(), "correo"  # confirmó su correo, no el número
            req.status, req.outcome = "respondida", "procede"
            db.commit()
            with pytest.raises(sol.SolicitudError) as err:
                sol.make_effective(db, req, actor, **kwargs)
            assert err.value.status_code == 409 and "ELIMINAR" in err.value.detail
            db.rollback()
    finally:
        db.close()
    bot = SimpleNamespace(channel="whatsapp", identity_method="whatsapp", phone=phone)
    assert sol.proven_whatsapp_phone(bot, None) == phone
    account = SimpleNamespace(phone="+525512345678", phone_verified=True)
    web = SimpleNamespace(channel="web", identity_method="correo", phone="55 1234 5678")
    assert sol.proven_whatsapp_phone(web, account) == account.phone
    assert sol.proven_whatsapp_phone(SimpleNamespace(channel="web", identity_method="correo", phone="5599990000"),
                                     account) is None
    assert sol.proven_whatsapp_phone(web, SimpleNamespace(phone="+525512345678", phone_verified=False)) is None


def _imported_report() -> int:
    db = SessionLocal()
    try:
        r = LostReport(dog_name=f"Importado {uuid.uuid4().hex[:5]}", report_type="lost", photos=[], source="facebook",
                       status="active", description="Se perdió en la colonia Roma.",
                       external_url=f"https://www.facebook.com/groups/1234/posts/{uuid.uuid4().int % 10**15}")
        db.add(r)
        db.commit()
        return r.id
    finally:
        db.close()


def _lost(rid) -> LostReport:
    db = SessionLocal()
    try:
        r = db.get(LostReport, rid)
        db.expunge(r)
        return r
    finally:
        db.close()


def test_imported_removal_depends_on_relation(client, quiet):
    def ask(rid, relacion):
        r = client.post(API, headers=_ip(), json={
            "tipo": "retiro_importado", "nombre": "Persona Prueba", "email": f"r-{uuid.uuid4().hex[:8]}@pruebas.mx",
            "descripcion": "Pido el retiro de esta publicación.", "enlace": f"https://guauwoow.com/app/?report={rid}",
            "relacion": relacion, "acepta_privacidad": True})
        assert r.status_code == 201, r.text
        return r.json()

    other = _imported_report()
    ack = ask(other, "otro")
    assert ack["publicacion_oculta"] is False and _lost(other).is_hidden is False  # solo entra a la cola
    appears = _imported_report()
    ack_ap = ask(appears, "aparezco")
    assert ack_ap["publicacion_oculta"] is True and _lost(appears).is_hidden is True
    author = _imported_report()
    ack_au = ask(author, "autor")
    assert "confirmes tu correo" in ack_au["mensaje"]
    db = SessionLocal()
    try:
        # Aunque confirmen el correo, quien aparece no la borra sola; la persona autora sin confirmar tampoco
        db.query(ComplianceRequest).filter(ComplianceRequest.folio == ack_ap["folio"]).update(
            {ComplianceRequest.identity_verified_at: _now()})
        db.commit()
        done = sol.enforce_imported_removals(db, now=_now() + datetime.timedelta(hours=49))
        assert ack_ap["folio"] not in done and ack_au["folio"] not in done and ack["folio"] not in done
    finally:
        db.close()
    assert _lost(appears).purged_at is None and _lost(author).purged_at is None
    # Si el equipo responde que no procede, «otro» no vuelve a mostrar algo que otra medida ocultó
    db = SessionLocal()
    try:
        db.query(LostReport).filter(LostReport.id == other).update({LostReport.is_hidden: True})
        db.commit()
        req = db.query(ComplianceRequest).filter(ComplianceRequest.folio == ack["folio"]).first()
        sol._restore_imported(db, req, None, _now())
        db.commit()
    finally:
        db.close()
    assert _lost(other).is_hidden is True


# =========================================================================== transparencia
def _bucket(donations=0, sales=0):
    def money(n):
        return Decimal(100 * n)

    return {"ventas": {"casos": sales, "bruto": money(sales), "reembolsos": Decimal(0), "comision": Decimal(0),
                       "retenciones": Decimal(0), "neto": money(sales)},
            "donativos": {"casos": donations, "bruto": money(donations), "comision": Decimal(0), "neto": money(donations)},
            "donativos_por_la_plataforma": Decimal(0)}


def _meta(rid, named):
    return {"id": rid, "nombre": f"Refugio {rid}", "ciudad": "Puebla", "verificado_desde": None,
            "forma_juridica": "Persona moral" if named else "Persona física", "donataria_autorizada": False,
            "publica_con_nombre": named}


def _fake_money(monkeypatch, data: dict, named: set):
    monkeypatch.setattr(tr, "money_by_refuge", lambda db, start, end, refuge_id=None, by_month=False: data)
    monkeypatch.setattr(tr, "refuge_meta", lambda db, ids: {i: _meta(i, i in named) for i in ids if i is not None})


def test_funds_never_reveal_a_refuge_by_subtraction(monkeypatch):
    start, end = datetime.datetime(2026, 1, 1, 6), datetime.datetime(2026, 4, 1, 6)
    # Una sola persona física sin consentimiento: «Otros» y el total de donativos se suprimen, y no se dice cuántos son
    _fake_money(monkeypatch, {(1, None): _bucket(10), (2, None): _bucket(8), (3, None): _bucket(6)}, {1, 2})
    out = tr.funds_section(None, start, end, 5)
    assert [r["id"] for r in out["refugios"]] == [1, 2]
    others = out["otros_refugios"]
    assert others["refugios"] is None and others["donativos"]["suprimido"] is True
    assert out["totales"]["donativos"]["suprimido"] is True
    assert out["totales"]["ventas"]["casos"] == 0  # sin ventas no hay nada que despejar
    # Tres o más Refugios sin nombre que suman el umbral: se publican «Otros» y el total
    _fake_money(monkeypatch, {(1, None): _bucket(10), (2, None): _bucket(8), (3, None): _bucket(2),
                              (4, None): _bucket(2), (5, None): _bucket(2)}, {1, 2})
    out = tr.funds_section(None, start, end, 5)
    assert out["otros_refugios"]["refugios"] == 3 and out["otros_refugios"]["donativos"]["casos"] == 6
    assert out["totales"]["donativos"]["casos"] == 24
    # Un Refugio con nombre con pocas ventas: esas ventas van a «Otros», no quedan como diferencia del total
    _fake_money(monkeypatch, {(1, None): _bucket(10, 2), (2, None): _bucket(8, 9)}, {1, 2})
    out = tr.funds_section(None, start, end, 5)
    assert out["refugios"][0]["ventas"]["suprimido"] is True
    assert out["totales"]["ventas"]["suprimido"] is True  # 11 - 9 = 2 ventas de un solo Refugio


def test_monthly_series_applies_complementary_suppression(monkeypatch):
    start, end = datetime.datetime(2026, 1, 1, 6), datetime.datetime(2026, 4, 1, 6)
    data = {(1, "2026-01"): _bucket(10), (1, "2026-02"): _bucket(2), (1, "2026-03"): _bucket(6),
            (2, "2026-03"): _bucket(6), (3, "2026-02"): _bucket(0, 7)}
    _fake_money(monkeypatch, data, {1, 2})
    series = {m["mes"]: m for m in tr.monthly_series(None, start, end, 5)}
    # Febrero tiene menos de 5 donativos: se suprime también el mes publicado más chico (enero)
    assert series["2026-02"]["donativos"]["suprimido"] and series["2026-01"]["donativos"]["suprimido"]
    assert series["2026-03"]["donativos"]["casos"] == 12
    # Ventas de un solo Refugio sin nombre: no se publican aunque pasen del umbral
    assert series["2026-02"]["ventas"].get("suprimido") is True


def test_arco_on_time_counts_the_extension():
    received = datetime.datetime(2001, 3, 5, 15)
    start, end = datetime.datetime(2001, 3, 1), datetime.datetime(2001, 4, 1)
    db = SessionLocal()
    ids = []
    try:
        before = sol.arco_stats(db, start, end)
        original = sol.business_deadline(received, sol.ARCO_RESPONSE_DAYS)
        extended = sol.business_deadline(original, sol.ARCO_RESPONSE_DAYS)
        for n, responded in enumerate((original + datetime.timedelta(days=3), extended + datetime.timedelta(days=1))):
            req = ComplianceRequest(
                folio=f"PF-2001-T{uuid.uuid4().hex[:6].upper()}", kind="acceso", status="cerrada", name="Prueba",
                email="arco@pruebas.mx", channel="web", description="Prueba de plazos", received_at=received,
                respond_by=extended, respond_extended_at=received + datetime.timedelta(days=5),
                responded_at=responded, created_at=received, updated_at=received)
            db.add(req)
            db.flush()
            ids.append(req.id)
        db.commit()
        after = sol.arco_stats(db, start, end)
        assert after["respondidas"] - before["respondidas"] == 2
        assert after["respondidas_a_tiempo"] - before["respondidas_a_tiempo"] == 1  # la ampliación cuenta
    finally:
        db.query(ComplianceRequest).filter(ComplianceRequest.id.in_(ids or [0])).delete(synchronize_session=False)
        db.commit()
        db.close()


# =========================================================================== tienda
def test_bonus_base_is_the_claimed_items_never_shipping():
    items = [SimpleNamespace(id=1, product_id=10, quantity=1, unit_price=Decimal("100")),
             SimpleNamespace(id=2, product_id=11, quantity=2, unit_price=Decimal("150"))]
    order = SimpleNamespace(items=items, subtotal=Decimal("400"), total=Decimal("450"), shipping_total=Decimal("50"))
    base, covered = reglas._bonus_base(order)
    assert base == 400 and [c["order_item_id"] for c in covered] == [1, 2]
    base, covered = reglas._bonus_base(order, Decimal("100"))
    assert base == 100 and covered is None
    base, covered = reglas._bonus_base(order, Decimal("100"), [1])
    assert base == 100 and [c["order_item_id"] for c in covered] == [1]
    base, covered = reglas._bonus_base(order, Decimal("450"))
    assert base == 400 and len(covered) == 2  # el envío no cuenta
    base, covered = reglas._bonus_base(order, Decimal("400"), [2], previous=[{"order_item_id": 1}])
    assert base == 400 and {c["order_item_id"] for c in covered} == {1, 2}


def test_seller_identity_needs_verified_buyer(client, unverified):
    db = SessionLocal()
    try:
        rid = db.query(Refuge.id).filter(Refuge.status == "approved").first()
    finally:
        db.close()
    if rid:
        assert client.get(f"/products/sellers/{rid[0]}/identity", headers=unverified["h"]).status_code == 403


# =========================================================================== adopción
@pytest.mark.parametrize("text", [
    "Pedimos una cuota de ＄500", "la cuоta es simbólica", "son quinientos pesitos", "cooperación de 300",
    "c0sto de recuperación", "aportación $200 para vacunas",
])
def test_fee_variants_are_held(text):
    assert reglas.adoption_terms(text)[0] == "cobro_adopcion", text


def test_released_hold_comes_back_with_a_new_amount_and_rejection_is_appealable(client, owner, make_user):
    admin = _staff(make_user)
    r = client.post("/dogs", headers=owner["h"], json={"name": "Luna", "size": "Chico",
                                                       "description": "Pedimos una cuota de $500 para vacunas"})
    assert r.status_code == 201, r.text
    dog_id = r.json()["id"]
    hold = _query(ContentReport, ContentReport.target_type == "dog", ContentReport.target_id == dog_id,
                  ContentReport.reason == reglas.HOLD_REPORT_REASON)[0]
    assert hold.priority == 2 and hold.due_at is not None and hold.due_at > _now()
    assert client.post(f"/admin/reglas/retenciones/dog/{dog_id}", headers=admin["h"],
                       json={"decision": "liberar"}).status_code == 200
    # Misma redacción: sigue publicada; un monto nuevo la regresa a revisión
    same = client.patch(f"/dogs/{dog_id}", headers=owner["h"], json={"description": "Pedimos una cuota de $500 para vacunas"})
    assert same.status_code == 200 and _dog_row(dog_id).is_hidden is False
    more = client.patch(f"/dogs/{dog_id}", headers=owner["h"],
                        json={"description": "Pedimos una cuota de $500 para vacunas y cooperación de 300"})
    assert more.status_code == 200 and _dog_row(dog_id).is_hidden is True
    r = client.post(f"/admin/reglas/retenciones/dog/{dog_id}", headers=admin["h"],
                    json={"decision": "rechazar", "notas": "Pide dinero por la adopción del perro."})
    assert r.status_code == 200, r.text
    action = _query(ModerationAction, ModerationAction.target_type == "dog", ModerationAction.target_id == dog_id)[-1]
    assert action.folio.startswith("MOD-") and action.detection == "filtro" and action.evidence_id
    assert action.appeal_until is not None and action.user_id == _set(owner["email"])
    note = _query(Notification, Notification.user_id == action.user_id, Notification.type == "content_hidden")[-1]
    assert action.folio in note.body and "Pide dinero" in note.body


def _found(reporter_email, days_ago=0, **fields) -> int:
    db = SessionLocal()
    try:
        uid = db.query(User.id).filter(User.email == reporter_email).scalar()
        r = LostReport(reporter_id=uid, dog_name="Encontrado", report_type="found", photos=[], status="active",
                       source="app", city="Puebla", created_at=_now() - datetime.timedelta(days=days_ago), **fields)
        db.add(r)
        db.commit()
        return r.id
    finally:
        db.close()


def test_found_report_links_one_dog_and_the_wait_counts_from_the_listing(client, owner):
    old = _found(owner["email"], days_ago=40)
    dog = _dog(client, owner)
    r = client.patch(f"/dogs/{dog['id']}", headers=owner["h"], json={
        "found_report_id": old, "microchip_checked": True, "microchip_result": "sin_chip", "authority_notified": True,
        "authority_notice": "Centro de Atención Canina, folio 9"})
    assert r.status_code == 200 and "plazo" in r.json()["found_hold"]["missing"], r.text  # no se acorta la espera
    assert client.post("/dogs", headers=owner["h"], json={"name": "Otro", "found_report_id": old}).status_code == 409
    hidden = _found(owner["email"], days_ago=40, is_hidden=True)
    assert client.post("/dogs", headers=owner["h"], json={"name": "Otro", "found_report_id": hidden}).status_code == 400
    # Si el reporte se oculta antes de cumplir el plazo, el resguardo sigue aunque pasen los días
    db = SessionLocal()
    try:
        db.query(Dog).filter(Dog.id == dog["id"]).update({Dog.found_at: _now() - datetime.timedelta(days=31)})
        db.query(LostReport).filter(LostReport.id == old).update({LostReport.is_hidden: True})
        db.commit()
        row = db.get(Dog, dog["id"])
        assert "reporte_activo" in reglas.found_hold_missing(db, row)
        # En el perfil del refugio tampoco aparece para otras personas
        uid = db.query(User.id).filter(User.email == owner["email"]).scalar()
        refuge = Refuge(user_id=uid, name=f"Refugio {uuid.uuid4().hex[:5]}", status="approved")
        db.add(refuge)
        db.commit()
        refuge_id = refuge.id
    finally:
        db.close()
    public = client.get(f"/refuges/{refuge_id}/dogs", params={"status": "all"}).json()
    assert dog["id"] not in [d["id"] for d in public]
    mine = client.get(f"/refuges/{refuge_id}/dogs", params={"status": "all"}, headers=owner["h"]).json()
    assert dog["id"] in [d["id"] for d in mine]


# =========================================================================== Facebook
def test_page_ingestion_needs_the_legal_switch(client, make_user, monkeypatch):
    admin = _staff(make_user)
    monkeypatch.setattr(settings, "fb_groups_enabled", False)
    monkeypatch.setattr(settings, "facebook_page_access_token", "page-token")
    assert client.post("/facebook/scrape-all", headers=admin["h"]).status_code == 409
    assert client.post("/facebook/scrape", headers=admin["h"], params={"group_id": 1}).status_code == 409
    with pytest.raises(facebook_monitor.FacebookImportDisabled):
        facebook_monitor.ingest_page(None, SimpleNamespace(kind="page", page_id="patitas"))
