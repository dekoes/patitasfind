"""Migración 0004_cumplimiento: bitácoras de solo inserción instaladas, SQL de los triggers igual al de los
servicios y pasos de datos (alertas cercanas apagadas sin consentimiento)."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import engine
from app.services import evidence, legal_acceptance

MIGRATION = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0004_cumplimiento.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0004", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trigger_sql_matches_services():
    """La migración lleva una copia literal: si cambia el servicio, hace falta una migración nueva."""
    m = _migration()
    assert m.LEGAL_LOG_APPEND_ONLY_SQL.strip() == legal_acceptance.APPEND_ONLY_SQL.strip()
    assert m.EVIDENCE_APPEND_ONLY_SQL.strip() == evidence.APPEND_ONLY_SQL.strip()
    assert m.down_revision == "0003_tienda_vets_facebook"


def test_append_only_triggers_installed(schema):
    with engine.connect() as conn:
        names = set(conn.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    assert {"trg_legal_acceptances_append_only", "trg_legal_acceptances_no_truncate",
            "trg_consent_records_append_only", "trg_consent_records_no_truncate",
            "evidence_records_append_only"} <= names


@pytest.mark.parametrize("statement", [
    "UPDATE legal_acceptances SET ip = 'x'",
    "DELETE FROM legal_acceptances",
    "TRUNCATE legal_acceptances",
    "UPDATE consent_records SET granted = NOT granted",
    "DELETE FROM consent_records",
    "DELETE FROM evidence_records",
    "UPDATE evidence_records SET content_sha256 = 'x'",
])
def test_logs_reject_changes(schema, statement):
    """Las bitácoras rechazan UPDATE/DELETE/TRUNCATE aunque no haya filas que coincidan con un WHERE: se
    inserta una fila de prueba dentro de una transacción que se revierte."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            uid = conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
            conn.execute(text(
                "INSERT INTO legal_acceptances (user_id, slug, version, sha256, accepted_at, method, prev_hash, row_hash)"
                " VALUES (:u, 'prueba-0004', 'v', repeat('a', 64), now(), 'registro', md5(random()::text) || "
                "md5(random()::text), md5(random()::text) || md5(random()::text))"), {"u": uid})
            conn.execute(text(
                "INSERT INTO consent_records (user_id, purpose, granted, text_version, channel, created_at)"
                " VALUES (:u, 'notify_nearby', false, 'prueba', 'app', now())"), {"u": uid})
            conn.execute(text(
                "INSERT INTO evidence_records (kind, target_type, content_sha256, row_hash, retained_until, created_at)"
                " VALUES ('prueba', 'dog', repeat('b', 64), md5(random()::text) || md5(random()::text), now(), now())"))
            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text(statement))
        finally:
            trans.rollback()


def test_evidence_allows_legal_hold_and_purge_marks(schema):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(
                "INSERT INTO evidence_records (kind, target_type, content_sha256, row_hash, retained_until, created_at,"
                " storage_path) VALUES ('prueba', 'dog', repeat('c', 64), md5(random()::text) || md5(random()::text),"
                " now(), now(), 'x.bin')"))
            conn.execute(text("UPDATE evidence_records SET legal_hold = true, retained_until = retained_until + "
                              "interval '1 day' WHERE kind = 'prueba'"))
            conn.execute(text("UPDATE evidence_records SET storage_path = NULL, purged_at = now() WHERE kind = 'prueba'"))
        finally:
            trans.rollback()


def test_notify_nearby_defaults_off(schema):
    """Alertas cercanas apagadas por defecto (K-PREF); el paso de datos de 0004 las apaga sin consentimiento."""
    with engine.connect() as conn:
        default = conn.execute(text(
            "SELECT column_default FROM information_schema.columns WHERE table_name = 'users' "
            "AND column_name = 'notify_nearby'")).scalar()
    assert default == "false"
    assert "notify_nearby = false" in MIGRATION.read_text()
