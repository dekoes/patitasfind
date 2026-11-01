"""Registro de versiones (K-DOCS) y bitácora de aceptaciones de solo inserción (K-ACEPT).

Registro: scripts/render-legal.py escribe app/legal/versiones.json ([{slug, title, version, effective_at, sha256,
requires_reacceptance, summary, url}]). «python -m app.cli sync-legal-docs» (deploy.sh y el arranque, si el archivo
cambió) lo copia a la tabla legal_documents. La versión vigente de cada documento es la más reciente cuya entrada en
vigor ya pasó; una con fecha futura es «próxima» y genera el aviso previo de 30 días (correo + aviso en la app).

Bitácora: record_acceptance() agrega una fila a legal_acceptances con la versión y la huella SHA-256 vigentes, la
fecha, la IP y el user agent. Cada fila encadena la huella de la anterior (row_hash = SHA-256(prev_hash + campos)),
así que editar o borrar una fila rompe la cadena (verify_chain). En Postgres un trigger bloquea UPDATE, DELETE y
TRUNCATE (APPEND_ONLY_SQL; lo agrega la migración 0004). Las filas se escriben bajo un candado de transacción
(pg_advisory_xact_lock) y prev_hash es único: dos aceptaciones simultáneas nunca bifurcan la cadena.
"""
import datetime
import hashlib
import json
import logging
import re
from pathlib import Path

from fastapi import Request
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import FosterHome, LegalAcceptance, LegalDocument, Product, Refuge, User, Veterinary

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
CHAIN_LOCK_KEY = 0x50464C41  # "PFLA": candado de la cadena de aceptaciones
SYNC_LOCK_KEY = 0x50464C44  # "PFLD": sincronización del registro
METHODS = ("registro", "reaceptacion", "checkout", "anexo", "donativo")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ADMIN_ROLES = ("admin", "superadmin")
MX_UTC_OFFSET = datetime.timedelta(hours=6)  # Ciudad de México (UTC-6, sin horario de verano)

TERMS_SLUG, PRIVACY_SLUG, SHOP_SLUG, DONATIONS_SLUG = "terminos", "privacidad", "terminos-tienda", "donativos"
AGE_SLUG = "mayoria-de-edad"
# Declaración de la casilla separada del registro (debe ser idéntica al texto de app/index.html #auth-adult)
AGE_DECLARATION = {
    "title": "Declaración de mayoría de edad",
    "version": "2026-10-17",
    "text": "Declaro que tengo 18 años o más.",
}
# Anexos de aliados (casilla separada sin marcar): rol -> documentos
ANNEX_SLUGS = {
    "refugio": ("terminos-refugios", "acuerdo-datos-refugios"),
    "vendedor": ("terminos-vendedores",),
    "clinica": ("terminos-clinicas",),
    # terminos-casas-de-paso 1.2 y acuerdo-datos-refugios 1.3: la Casa de paso también acepta el Acuerdo de datos
    "casa_de_paso": ("terminos-casas-de-paso", "acuerdo-datos-refugios"),
}
ANNEX_LABELS = {
    "refugio": "Para registrar tu refugio acepta los Términos para Refugios y el Acuerdo de tratamiento de datos.",
    "vendedor": "Para vender en la tienda acepta los Términos para vendedores.",
    "clinica": "Para registrar tu clínica acepta los Términos para clínicas veterinarias.",
    "casa_de_paso": ("Para registrarte como casa de paso acepta los Términos para casas de paso y el Acuerdo de "
                     "tratamiento de datos."),
}
ALL_ANNEX_SLUGS = tuple(s for slugs in ANNEX_SLUGS.values() for s in slugs)
# Títulos de respaldo mientras el registro no se ha sincronizado
FALLBACK_TITLES = {
    TERMS_SLUG: "Términos y condiciones", PRIVACY_SLUG: "Aviso de privacidad", SHOP_SLUG: "Términos de la tienda",
    DONATIONS_SLUG: "Términos de donativos", "terminos-refugios": "Términos para Refugios",
    "acuerdo-datos-refugios": "Acuerdo de tratamiento de datos para Refugios",
    "terminos-vendedores": "Términos para vendedores", "terminos-clinicas": "Términos para clínicas veterinarias",
    "terminos-casas-de-paso": "Términos para casas de paso", AGE_SLUG: AGE_DECLARATION["title"],
}

# Trigger de solo inserción para la migración 0004 (también lo aplica scripts de desarrollo). El borrado solo se
# permite a la purga de conservación, que antes ejecuta SET LOCAL patitas.allow_purge = 'on' (allow_purge()).
APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION legal_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND coalesce(current_setting('patitas.allow_purge', true), '') = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION '% es de solo inserción: % no está permitido', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;
DROP TRIGGER IF EXISTS trg_legal_acceptances_append_only ON legal_acceptances;
CREATE TRIGGER trg_legal_acceptances_append_only BEFORE UPDATE OR DELETE ON legal_acceptances
  FOR EACH ROW EXECUTE FUNCTION legal_log_append_only();
DROP TRIGGER IF EXISTS trg_legal_acceptances_no_truncate ON legal_acceptances;
CREATE TRIGGER trg_legal_acceptances_no_truncate BEFORE TRUNCATE ON legal_acceptances
  FOR EACH STATEMENT EXECUTE FUNCTION legal_log_append_only();
DROP TRIGGER IF EXISTS trg_consent_records_append_only ON consent_records;
CREATE TRIGGER trg_consent_records_append_only BEFORE UPDATE OR DELETE ON consent_records
  FOR EACH ROW EXECUTE FUNCTION legal_log_append_only();
DROP TRIGGER IF EXISTS trg_consent_records_no_truncate ON consent_records;
CREATE TRIGGER trg_consent_records_no_truncate BEFORE TRUNCATE ON consent_records
  FOR EACH STATEMENT EXECUTE FUNCTION legal_log_append_only();
"""


class ComplianceError(Exception):
    """Error con código para el frontend: main.py lo convierte en {"detail", "code", **extra}."""

    def __init__(self, status_code: int, detail: str, code: str, **extra):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.extra = extra


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def allow_purge(db: Session) -> None:
    """Permite DELETE en las bitácoras de solo inserción dentro de la transacción actual (purga de conservación)."""
    if _is_postgres(db):
        db.execute(text("SET LOCAL patitas.allow_purge = 'on'"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- archivo de versiones
def _candidates() -> list[Path]:
    app_dir = Path(__file__).resolve().parents[1]  # backend/app
    paths = []
    if settings.legal_versions_file:
        paths.append(Path(settings.legal_versions_file))
    paths.append(app_dir / "data" / "versiones-legales.json")
    paths.append(app_dir.parents[1] / "app" / "legal" / "versiones.json")  # repositorio completo (fuera de Docker)
    return paths


def versions_file() -> Path | None:
    for path in _candidates():
        if path.is_file():
            return path
    return None


def parse_effective(value) -> datetime.datetime | None:
    """'2026-11-20' (día en la Ciudad de México) o ISO con hora -> datetime UTC sin zona. None/'' -> None."""
    if value in (None, ""):
        return None
    raw = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            day = datetime.date.fromisoformat(raw)
            return datetime.datetime.combine(day, datetime.time()) + MX_UTC_OFFSET
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed


def load_entries(path: Path | None = None) -> list[dict]:
    """Lee y valida versiones.json. Las entradas inválidas se omiten con un aviso en el log."""
    path = path or versions_file()
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("documentos") or data.get("documents") or []
    entries = []
    for raw in data if isinstance(data, list) else []:
        if not isinstance(raw, dict):
            continue
        slug = str(raw.get("slug") or "").strip()
        sha = str(raw.get("sha256") or "").strip().lower()
        version = str(raw.get("version") or "").strip()
        if not SLUG_RE.match(slug) or not SHA_RE.match(sha) or not version or len(version) > 20:
            logger.warning("versiones.json: entrada inválida omitida: %r", {k: raw.get(k) for k in ("slug", "version")})
            continue
        entries.append({
            "slug": slug, "sha256": sha, "version": version,
            "title": str(raw.get("title") or FALLBACK_TITLES.get(slug) or slug)[:255],
            "effective_at": parse_effective(raw.get("effective_at")),
            "requires_reacceptance": bool(raw.get("requires_reacceptance")),
            "summary": (str(raw["summary"]).strip() or None) if raw.get("summary") else None,
            "url": str(raw.get("url") or f"/app/legal/{slug}.html")[:255],
        })
    return entries


def sync_documents(db: Session, entries: list[dict], now: datetime.datetime | None = None,
                   dry_run: bool = False) -> dict:
    """Copia las entradas al registro (idempotente; hace commit). Devuelve {created, updated, unchanged, warnings,
    notice_ids}. notice_ids: versiones nuevas que reemplazan a otra y piden aceptación (aviso previo).
    dry_run=True calcula lo mismo y deshace todo (para revisar los avisos antes de escribir)."""
    now = now or _now()
    if _is_postgres(db):
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SYNC_LOCK_KEY})
    created, updated, unchanged, warnings, notice_ids = [], [], 0, [], []
    newest: dict[str, str] = {}
    for entry in entries:
        newest[entry["slug"]] = max(newest.get(entry["slug"], ""), entry["version"])
    for entry in entries:
        row = db.query(LegalDocument).filter(LegalDocument.slug == entry["slug"],
                                             LegalDocument.sha256 == entry["sha256"]).first()
        if row is not None:
            changed = False
            for field in ("title", "version", "effective_at", "requires_reacceptance", "summary", "url"):
                if getattr(row, field) != entry[field]:
                    setattr(row, field, entry[field])
                    changed = True
            if changed:
                updated.append(row)
            else:
                unchanged += 1
            continue
        previous = (db.query(LegalDocument).filter(LegalDocument.slug == entry["slug"])
                    .order_by(LegalDocument.published_at.desc(), LegalDocument.id.desc()).first())
        # Versiones anteriores que trae el archivo (historial): se publicaron en su fecha, no hoy
        published = now
        if entry["version"] < newest[entry["slug"]]:
            published = min(now, _version_date(entry["version"]) or now)
        row = LegalDocument(published_at=published, created_at=now, **entry)
        db.add(row)
        db.flush()
        created.append(row)
        historical = entry["version"] < newest[entry["slug"]]
        supersedes = not historical and previous is not None and previous.version < entry["version"]
        if supersedes and entry["requires_reacceptance"]:
            notice_ids.append(row.id)
            effective = entry["effective_at"]
            if effective is None or effective - now < datetime.timedelta(days=settings.legal_notice_days):
                warnings.append(
                    f"{entry['slug']} {entry['version']}: es un cambio que pide aceptación y entra en vigor "
                    f"{'de inmediato' if effective is None else effective.strftime('%Y-%m-%d')}, con menos de "
                    f"{settings.legal_notice_days} días de aviso previo (historial.html §2). Define "
                    "FECHA_DE_ENTRADA_EN_VIGOR al menos 30 días después de publicar.")
    out = {"created": [r.id for r in created], "updated": [r.id for r in updated], "unchanged": unchanged,
           "warnings": warnings, "notice_ids": notice_ids}
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return out


def sync_from_file(db: Session, path: Path | None = None, notify: bool = True, dry_run: bool = False) -> dict:
    path = path or versions_file()
    if path is None:
        return {"created": [], "updated": [], "unchanged": 0, "warnings": ["No se encontró versiones.json."],
                "notice_ids": [], "file": None}
    result = sync_documents(db, load_entries(path), dry_run=dry_run)
    result["file"] = str(path)
    if notify and not dry_run:
        from app.services.background import dispatch

        for doc_id in result["notice_ids"]:
            try:
                dispatch("app.tasks.legal_docs.send_change_notices", doc_id)
            except Exception:  # noqa: BLE001 - el aviso se reintenta en la tarea diaria
                logger.exception("No se pudo despachar el aviso del documento %s", doc_id)
    return result


def sync_if_changed(db: Session) -> dict | None:
    """Arranque: sincroniza solo si el archivo trae alguna huella que el registro no tiene."""
    path = versions_file()
    if path is None:
        return None
    entries = load_entries(path)
    if not entries:
        return None
    known = {(s, h) for s, h in db.query(LegalDocument.slug, LegalDocument.sha256).all()}
    if all((e["slug"], e["sha256"]) in known for e in entries):
        return None
    return sync_from_file(db, path)


# --------------------------------------------------------------------------- registro vigente
def _key(row: LegalDocument) -> tuple:
    # Las versiones son fechas (AAAA-MM-DD): a igual fecha de vigencia gana la versión más nueva
    return (row.effective_at or row.published_at, row.version, row.id)


def _version_date(version: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.combine(datetime.date.fromisoformat(version), datetime.time()) + MX_UTC_OFFSET
    except ValueError:
        return None


def rows_by_slug(db: Session, slugs=None) -> dict[str, list[LegalDocument]]:
    q = db.query(LegalDocument)
    if slugs is not None:
        q = q.filter(LegalDocument.slug.in_(list(slugs)))
    grouped: dict[str, list[LegalDocument]] = {}
    for row in q.order_by(LegalDocument.slug, LegalDocument.published_at, LegalDocument.id).all():
        grouped.setdefault(row.slug, []).append(row)
    return grouped


def in_force(rows: list[LegalDocument], now: datetime.datetime | None = None) -> LegalDocument | None:
    now = now or _now()
    valid = [r for r in rows if r.effective_at is None or r.effective_at <= now]
    return max(valid, key=_key) if valid else None


def upcoming(rows: list[LegalDocument], now: datetime.datetime | None = None) -> LegalDocument | None:
    """La próxima versión con fecha futura, si es distinta de la vigente."""
    now = now or _now()
    current = in_force(rows, now)
    future = [r for r in rows if r.effective_at is not None and r.effective_at > now
              and (current is None or r.version != current.version)]
    return min(future, key=_key) if future else None


def current_document(db: Session, slug: str) -> LegalDocument | None:
    return in_force(rows_by_slug(db, [slug]).get(slug, []))


def doc_out(row: LegalDocument | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id, "slug": row.slug, "title": row.title, "version": row.version, "sha256": row.sha256,
        "effective_at": row.effective_at, "published_at": row.published_at,
        "requires_reacceptance": row.requires_reacceptance, "summary": row.summary, "url": row.url,
    }


def registry(db: Session) -> list[dict]:
    """Para /cumplimiento/documentos e historial.js: vigente, próxima e historial (más reciente primero)."""
    now = _now()
    out = []
    for slug, rows in rows_by_slug(db).items():
        current = in_force(rows, now)
        nxt = upcoming(rows, now)
        head = current or nxt or rows[-1]
        history = []
        for r in sorted(rows, key=_key, reverse=True):
            item = doc_out(r)
            item["status"] = ("vigente" if current is not None and r.id == current.id
                              else "proxima" if r.effective_at is not None and r.effective_at > now else "anterior")
            history.append(item)
        out.append({
            "slug": slug, "title": head.title, "url": head.url, "requires_reacceptance": head.requires_reacceptance,
            "vigente": doc_out(current), "proxima": doc_out(nxt), "versiones": history,
        })
    out.sort(key=lambda d: d["title"].lower())
    return out


# --------------------------------------------------------------------------- bitácora encadenada
def _canonical(row: LegalAcceptance) -> str:
    accepted = row.accepted_at.replace(tzinfo=None).isoformat(timespec="microseconds") if row.accepted_at else None
    return json.dumps({
        "user_id": row.user_id, "slug": row.slug, "version": row.version, "sha256": row.sha256,
        "accepted_at": accepted, "ip": row.ip, "user_agent": row.user_agent, "method": row.method,
        "context": row.context or None,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def row_digest(prev_hash: str, row: LegalAcceptance) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical(row)).encode("utf-8")).hexdigest()


def _builtin(slug: str) -> tuple[str, str, dict]:
    """(versión, sha256, contexto) cuando el documento no está en el registro (desarrollo sin sincronizar)."""
    if slug == AGE_SLUG:
        return AGE_DECLARATION["version"], sha256_text(AGE_DECLARATION["text"]), {}
    version = settings.legal_privacy_version if slug == PRIVACY_SLUG else settings.legal_terms_version
    return version, sha256_text(f"sin-registro:{slug}:{version}"), {"registro": "sin_sincronizar"}


def _request_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    from app.dependencies import client_ip

    ip = (client_ip(request) or "")[:64] or None
    ua = (request.headers.get("user-agent") or "")[:255] or None
    return ip, ua


def resolve_version(db: Session, slug: str, version: str | None = None, sha256: str | None = None,
                    allow_upcoming: bool = True) -> tuple[str, str, LegalDocument | None]:
    """Versión y huella a registrar. Con version+sha256 deben coincidir con una fila vigente (o próxima)."""
    rows = rows_by_slug(db, [slug]).get(slug, [])
    if version is None and sha256 is None:
        current = in_force(rows)
        if current is not None:
            return current.version, current.sha256, current
        builtin_version, builtin_sha, _ = _builtin(slug)
        return builtin_version, builtin_sha, None
    now = _now()
    current = in_force(rows, now)
    nxt = upcoming(rows, now) if allow_upcoming else None
    acceptable = [r for r in rows if (current is not None and r.version == current.version)
                  or (nxt is not None and r.version == nxt.version)]
    for row in acceptable:
        if row.version == version and row.sha256 == (sha256 or "").lower():
            return row.version, row.sha256, row
    if not rows and slug == AGE_SLUG:
        builtin_version, builtin_sha, _ = _builtin(slug)
        if version == builtin_version and (sha256 or "").lower() == builtin_sha:
            return builtin_version, builtin_sha, None
    raise ComplianceError(409, "Ese documento cambió mientras lo leías. Recarga para revisar la versión vigente.",
                          "legal_version_mismatch", slug=slug)


def record_acceptance(db: Session, user: User, slug: str, method: str, request: Request | None = None, *,
                      version: str | None = None, sha256: str | None = None, context: dict | None = None,
                      commit: bool = False) -> LegalAcceptance:
    """Agrega una aceptación a la bitácora con la versión y huella vigentes (o las indicadas, ya validadas)."""
    if method not in METHODS:
        raise ValueError(f"método de aceptación inválido: {method}")
    if not SLUG_RE.match(slug or ""):
        raise ValueError(f"slug inválido: {slug!r}")
    version, sha, row = resolve_version(db, slug, version, sha256)
    ctx = dict(context or {})
    if row is None and slug != AGE_SLUG:
        ctx.setdefault("registro", "sin_sincronizar")
    ip, ua = _request_meta(request)
    if _is_postgres(db):
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CHAIN_LOCK_KEY})
    last = db.query(LegalAcceptance.row_hash).order_by(LegalAcceptance.id.desc()).limit(1).scalar()
    entry = LegalAcceptance(
        user_id=user.id, slug=slug, version=version, sha256=sha, accepted_at=_now(), ip=ip, user_agent=ua,
        method=method, context=ctx or None, prev_hash=last or GENESIS_HASH,
    )
    entry.row_hash = row_digest(entry.prev_hash, entry)
    db.add(entry)
    if slug == TERMS_SLUG:
        user.terms_version = version
        user.terms_accepted_at = entry.accepted_at
    elif slug == PRIVACY_SLUG:
        user.privacy_version = version
    db.flush()
    if commit:
        db.commit()
    return entry


def verify_chain(db: Session, batch: int = 2000) -> dict:
    """Recalcula la cadena completa. El ancla es el prev_hash de la primera fila que queda (tras una purga)."""
    previous = None
    anchor_id = None
    count = 0
    last_id = 0
    while True:
        rows = (db.query(LegalAcceptance).filter(LegalAcceptance.id > last_id)
                .order_by(LegalAcceptance.id).limit(batch).all())
        if not rows:
            break
        for row in rows:
            if previous is None:
                anchor_id = row.id
                expected_prev = row.prev_hash
            else:
                expected_prev = previous
            if row.prev_hash != expected_prev or row_digest(row.prev_hash, row) != row.row_hash:
                return {"ok": False, "rows": count, "first_invalid_id": row.id, "anchor_id": anchor_id,
                        "last_hash": previous}
            previous = row.row_hash
            count += 1
            last_id = row.id
        db.expunge_all()
    return {"ok": True, "rows": count, "first_invalid_id": None, "anchor_id": anchor_id, "last_hash": previous}


def append_only_active(db: Session) -> bool:
    """True si el trigger de solo inserción ya está instalado (migración 0004)."""
    if not _is_postgres(db):
        return False
    return bool(db.execute(text(
        "SELECT 1 FROM pg_trigger WHERE tgname = 'trg_legal_acceptances_append_only' AND NOT tgisinternal"
    )).first())


def accepted_versions(db: Session, user_id: int, slugs) -> dict[str, set[str]]:
    rows = (db.query(LegalAcceptance.slug, LegalAcceptance.version)
            .filter(LegalAcceptance.user_id == user_id, LegalAcceptance.slug.in_(list(slugs))).distinct().all())
    out: dict[str, set[str]] = {}
    for slug, version in rows:
        out.setdefault(slug, set()).add(version)
    return out


def has_accepted_current(db: Session, user: User, slug: str) -> bool:
    version, _, row = resolve_version(db, slug)
    if row is None and slug in ALL_ANNEX_SLUGS:
        # Sin registro sincronizado: cuenta cualquier aceptación previa del anexo
        return bool(accepted_versions(db, user.id, [slug]).get(slug))
    return version in accepted_versions(db, user.id, [slug]).get(slug, set())


# --------------------------------------------------------------------------- a quién aplica cada documento
def user_roles(db: Session, user: User) -> set[str]:
    roles = set()
    refuge = (db.query(Refuge).filter(Refuge.user_id == user.id, Refuge.status.in_(("pending", "approved")))
              .order_by(Refuge.id.desc()).first())
    if refuge is not None:
        roles.add("refugio")
        sells = (db.query(Product.id).filter(Product.refuge_id == refuge.id).first() is not None
                 or (refuge.payment_account is not None and refuge.payment_account.status == "connected"))
        if sells:
            roles.add("vendedor")
    if db.query(Veterinary.id).filter(Veterinary.owner_user_id == user.id,
                                      Veterinary.status.in_(("pending", "verified"))).first():
        roles.add("clinica")
    if db.query(FosterHome.id).filter(FosterHome.user_id == user.id,
                                      FosterHome.status.in_(("pending", "approved"))).first():
        roles.add("casa_de_paso")
    return roles


def applicable(db: Session, user: User) -> dict[str, dict]:
    """slug -> {blocking, reason}. Términos y Aviso: todas las cuentas; anexos: según el rol de aliado;
    terminos-tienda: quien ya compró (se vuelve a aceptar en el siguiente pago, no bloquea)."""
    if user.role in ADMIN_ROLES:
        return {}
    out = {TERMS_SLUG: {"blocking": True, "role": None}, PRIVACY_SLUG: {"blocking": True, "role": None}}
    for role in user_roles(db, user):
        for slug in ANNEX_SLUGS[role]:
            out[slug] = {"blocking": False, "role": role}
    if accepted_versions(db, user.id, [SHOP_SLUG]).get(SHOP_SLUG):
        out[SHOP_SLUG] = {"blocking": False, "role": "comprador", "at_checkout": True}
    return out


def _legacy_ok(user: User, slug: str, version: str) -> bool:
    """Cuentas anteriores a la bitácora: cuenta la versión guardada en el perfil."""
    if slug == TERMS_SLUG:
        return user.terms_version == version
    if slug == PRIVACY_SLUG:
        return user.privacy_version == version
    return False


def pending_for(db: Session, user: User) -> dict:
    """Documentos por aceptar (vigentes) y avisos de versiones próximas para esta cuenta."""
    rules = applicable(db, user)
    if not rules:
        return {"pendientes": [], "avisos": []}
    now = _now()
    grouped = rows_by_slug(db, rules.keys())
    accepted = accepted_versions(db, user.id, rules.keys())
    pendientes, avisos = [], []
    for slug, rule in rules.items():
        rows = grouped.get(slug, [])
        current = in_force(rows, now)
        mine = accepted.get(slug, set())
        if current is not None and current.requires_reacceptance and current.version not in mine \
                and not _legacy_ok(user, slug, current.version):
            nxt = upcoming(rows, now)
            if nxt is None or nxt.version not in mine:
                item = doc_out(current)
                item.update({"blocking": rule["blocking"], "role": rule.get("role"),
                             "at_checkout": bool(rule.get("at_checkout")),
                             "reason": "nueva_version" if mine else ("anexo" if slug in ALL_ANNEX_SLUGS else "primera_vez"),
                             "method": "anexo" if (slug in ALL_ANNEX_SLUGS and not mine) else "reaceptacion"})
                pendientes.append(item)
        nxt = upcoming(rows, now)
        if nxt is not None and nxt.requires_reacceptance and nxt.version not in mine:
            item = doc_out(nxt)
            item["days_left"] = max(0, (nxt.effective_at - now).days)
            item["role"] = rule.get("role")
            avisos.append(item)
    pendientes.sort(key=lambda d: (not d["blocking"], d["title"]))
    avisos.sort(key=lambda d: d["effective_at"])
    return {"pendientes": pendientes, "avisos": avisos}


LEGAL_ACCEPTANCE_REQUIRED = "legal_acceptance_required"
LEGAL_ACCEPTANCE_MESSAGE = ("Actualizamos los Términos o el Aviso de Privacidad. Para seguir usando tu cuenta acepta la "
                            "versión vigente.")


def blocking_pending(db: Session, user: User) -> list[str]:
    """Términos y Aviso de Privacidad vigentes que la cuenta todavía no acepta (terminos.html 29.2, historial.html §3):
    las acciones de escritura (dependencies.get_verified_user) responden 403 legal_acceptance_required hasta
    aceptarlos. Misma regla que pending_for para los documentos que bloquean, con dos consultas."""
    if user.role in ADMIN_ROLES:
        return []
    slugs = (TERMS_SLUG, PRIVACY_SLUG)
    now = _now()
    grouped = rows_by_slug(db, slugs)
    accepted = accepted_versions(db, user.id, slugs)
    out = []
    for slug in slugs:
        rows = grouped.get(slug, [])
        current = in_force(rows, now)
        if current is None or not current.requires_reacceptance:
            continue
        mine = accepted.get(slug, set())
        if current.version in mine or _legacy_ok(user, slug, current.version):
            continue
        nxt = upcoming(rows, now)
        if nxt is not None and nxt.version in mine:
            continue
        out.append(slug)
    return out


def audience_query(db: Session, slug: str):
    """Cuentas a las que se avisa de una nueva versión de `slug` (correo + aviso en la app)."""
    q = db.query(User).filter(User.is_active.is_(True), User.deleted_at.is_(None), User.role.notin_(ADMIN_ROLES))
    if slug in ANNEX_SLUGS["refugio"]:
        owners = User.id.in_(db.query(Refuge.user_id).filter(Refuge.status.in_(("pending", "approved"))))
        if slug in ANNEX_SLUGS["casa_de_paso"]:  # el Acuerdo de datos también lo aceptan las Casas de paso
            owners = owners | User.id.in_(db.query(FosterHome.user_id).filter(
                FosterHome.status.in_(("pending", "approved"))))
        q = q.filter(owners)
    elif slug in ANNEX_SLUGS["vendedor"]:
        q = q.filter(User.id.in_(db.query(Refuge.user_id).join(Product, Product.refuge_id == Refuge.id)))
    elif slug in ANNEX_SLUGS["clinica"]:
        q = q.filter(User.id.in_(db.query(Veterinary.owner_user_id).filter(
            Veterinary.status.in_(("pending", "verified")))))
    elif slug in ANNEX_SLUGS["casa_de_paso"]:
        q = q.filter(User.id.in_(db.query(FosterHome.user_id).filter(FosterHome.status.in_(("pending", "approved")))))
    elif slug == SHOP_SLUG:
        q = q.filter(User.id.in_(db.query(LegalAcceptance.user_id).filter(LegalAcceptance.slug == SHOP_SLUG)))
    elif slug not in (TERMS_SLUG, PRIVACY_SLUG):
        return q.filter(False)
    return q


# --------------------------------------------------------------------------- anexos de aliados
def annex_documents(db: Session, role: str) -> list[dict]:
    out = []
    for slug in ANNEX_SLUGS[role]:
        version, sha, row = resolve_version(db, slug)
        out.append({"slug": slug, "title": row.title if row else FALLBACK_TITLES.get(slug, slug), "version": version,
                    "sha256": sha, "url": row.url if row else f"/app/legal/{slug}.html"})
    return out


def accept_annex(db: Session, user: User, role: str, accepted: bool | None, request: Request | None = None,
                 context: dict | None = None) -> list[LegalAcceptance]:
    """Casilla separada del anexo del rol. Si no la marcó y no tiene aceptada la versión vigente: con
    LEGAL_ANNEX_REQUIRED (producción) responde 400 code=annex_required; si no, solo no se registra nada."""
    missing = [slug for slug in ANNEX_SLUGS[role] if not has_accepted_current(db, user, slug)]
    if not missing:
        return []
    if not accepted:
        if settings.effective_legal_annex_required:
            raise ComplianceError(400, ANNEX_LABELS[role], "annex_required", role=role,
                                  documents=[d for d in annex_documents(db, role) if d["slug"] in missing])
        return []
    return [record_acceptance(db, user, slug, "anexo", request, context=context) for slug in missing]


ALLY_ANNEX_PENDING = "ally_annex_pending"


def missing_annexes(db: Session, user: User | None, roles) -> list[str]:
    """Anexos de los roles sin la versión vigente aceptada. Vacío si LEGAL_ANNEX_REQUIRED está apagado (desarrollo)
    o no hay a quién pedirlo. terminos-refugios 1.3: tener aceptada la versión vigente es requisito para solicitar y
    conservar la verificación y para recibir donativos o vender."""
    if user is None or not settings.effective_legal_annex_required:
        return []
    return [slug for role in roles for slug in ANNEX_SLUGS[role] if not has_accepted_current(db, user, slug)]


def require_ally_annexes(db: Session, owner: User | None, roles, detail: str, status_code: int = 409,
                         notify_title: str | None = None) -> None:
    """Corta la acción (verificar, donar a, comprar a) si la cuenta aliada no tiene aceptados sus anexos vigentes.

    Responde code=ally_annex_pending (no abre la ventana de anexos de quien llama: el pendiente es de la cuenta
    aliada). Con notify_title, avisa a la cuenta aliada para que los acepte desde Inicio."""
    missing = missing_annexes(db, owner, roles)
    if not missing:
        return
    if notify_title:
        from app.models import Notification

        titles = ", ".join(FALLBACK_TITLES.get(slug, slug) for slug in missing)
        db.add(Notification(user_id=owner.id, type="legal_change", title=notify_title[:255],
                            body=f"Acepta en la app la versión vigente de: {titles}. Mientras tanto no podemos "
                                 "verificar tu cuenta ni recibir donativos o ventas para ti.",
                            data={"url": "/app/#inicio", "slugs": missing}))
        db.commit()
    raise ComplianceError(status_code, detail, ALLY_ANNEX_PENDING, documents=missing)


def acceptances_for_export(db: Session, user_id: int) -> list[dict]:
    rows = db.query(LegalAcceptance).filter(LegalAcceptance.user_id == user_id).order_by(LegalAcceptance.id).all()
    return [{"slug": r.slug, "version": r.version, "sha256": r.sha256, "accepted_at": r.accepted_at, "ip": r.ip,
             "user_agent": r.user_agent, "method": r.method, "context": r.context, "row_hash": r.row_hash}
            for r in rows]


def count_acceptances(db: Session) -> int:
    return db.query(func.count(LegalAcceptance.id)).scalar() or 0
