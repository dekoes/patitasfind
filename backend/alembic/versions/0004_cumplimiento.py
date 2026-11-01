"""Cumplimiento legal: aceptaciones y consentimientos con bitácora de solo inserción, versiones de los
documentos legales, edad (18+), moderación legal (reportes públicos, evidencia, derechos de autor,
autoridades), centro de solicitudes ARCO y transparencia, doble factor de administradores, cifrado en
reposo, conservación de datos e incidentes de seguridad, y reglas de negocio (tienda, donativos,
perros encontrados).

Idempotente a propósito (IF NOT EXISTS / IF EXISTS), igual que 0002 y 0003: la base de desarrollo ya
recibió estas tablas con create_all y estas columnas con ALTER ... IF NOT EXISTS mientras se construían
las funciones. Los nombres de restricciones son los que PostgreSQL asignó ahí (content_reports_folio_key,
dogs_found_report_id_fkey), así que en una base vacía y en la de desarrollo queda el mismo esquema y
`alembic check` no encuentra diferencias.

Además del esquema:
- Triggers de solo inserción (BEFORE UPDATE OR DELETE -> RAISE EXCEPTION) en legal_acceptances y
  consent_records (también BEFORE TRUNCATE; el DELETE solo se permite a la purga de conservación con
  SET LOCAL patitas.allow_purge = 'on') y en evidence_records (sin DELETE; solo pueden cambiar la
  retención legal, la prórroga hacia arriba y la purga del archivo). Copia literal de
  services/legal_acceptance.APPEND_ONLY_SQL y services/evidence.APPEND_ONLY_SQL (una prueba las compara).
- Datos: notify_nearby vuelve a false para quien no lo aceptó con un registro de consentimiento (antes de
  0004 nadie tenía uno, así que en producción se apaga para todos y la app les invita a activarlo); el
  valor por defecto de la columna pasa a false, y la ubicación guardada (latitude/longitude) se borra en las
  cuentas con las alertas apagadas. Los donativos dejan de sumar puntos en el ranking (se
  descuentan los ya sumados, una sola vez). Los reportes abiertos reciben la prioridad de su motivo.
- order_invoices y refuge_fiscal_profiles: rfc, razón social, código postal (y correo) pasan de VARCHAR a
  TEXT porque ahora se guardan cifrados (EncryptedText). Los valores en claro siguen leyéndose tal cual
  hasta correr `python -m app.cli encrypt-private-files`.

Revision ID: 0004_cumplimiento
Revises: 0003_tienda_vets_facebook
Create Date: 2026-10-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004_cumplimiento'
down_revision = '0003_tienda_vets_facebook'
branch_labels = None
depends_on = None

# Columnas que ahora guardan texto cifrado (AES-256-GCM, services/crypto_storage.EncryptedText): longitud de antes
ENCRYPTED_COLUMNS = (
    ('order_invoices', 'rfc', 13), ('order_invoices', 'legal_name', 255), ('order_invoices', 'postal_code', 5),
    ('order_invoices', 'email', 255),
    ('refuge_fiscal_profiles', 'rfc', 13), ('refuge_fiscal_profiles', 'legal_name', 255),
    ('refuge_fiscal_profiles', 'postal_code', 5),
)

# Copia de services/legal_acceptance.APPEND_ONLY_SQL (tests/test_migracion_0004.py verifica que sean iguales)
LEGAL_LOG_APPEND_ONLY_SQL = """
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

# Copia de services/evidence.APPEND_ONLY_SQL (tests/test_migracion_0004.py verifica que sean iguales)
EVIDENCE_APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION evidence_records_append_only() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'evidence_records es de solo inserción';
  END IF;
  IF NEW.kind IS DISTINCT FROM OLD.kind OR NEW.target_type IS DISTINCT FROM OLD.target_type
     OR NEW.target_id IS DISTINCT FROM OLD.target_id OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
     OR NEW.content_report_id IS DISTINCT FROM OLD.content_report_id
     OR NEW.copyright_notice_id IS DISTINCT FROM OLD.copyright_notice_id
     OR NEW.authority_request_id IS DISTINCT FROM OLD.authority_request_id OR NEW.reason IS DISTINCT FROM OLD.reason
     OR NEW.is_csam IS DISTINCT FROM OLD.is_csam OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
     OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR NEW.prev_hash IS DISTINCT FROM OLD.prev_hash
     OR NEW.row_hash IS DISTINCT FROM OLD.row_hash OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.retained_until < OLD.retained_until
     OR (OLD.storage_path IS NOT NULL AND NEW.storage_path IS NOT NULL AND NEW.storage_path <> OLD.storage_path)
     OR (OLD.purged_at IS NOT NULL AND NEW.purged_at IS DISTINCT FROM OLD.purged_at) THEN
    RAISE EXCEPTION 'evidence_records: solo pueden cambiar la retención legal, la prórroga y la purga';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS evidence_records_append_only ON evidence_records;
CREATE TRIGGER evidence_records_append_only BEFORE UPDATE OR DELETE ON evidence_records
  FOR EACH ROW EXECUTE FUNCTION evidence_records_append_only();
"""

# Prioridad de la cola de moderación por motivo (services/legal_moderation.priority_for, al 2026-10-17)
PRIORITY_1_REASONS = ('acoso', 'abuso_sexual', 'odio_violencia_masiva', 'incitacion_odio_violencia',
                      'conductas_ilicitas', 'pornografia', 'suicidio_autolesiones', 'contenido_intimo',
                      'venta_animal', 'maltrato')
PRIORITY_2_REASONS = ('fraude', 'suplantacion')


def _has_constraint(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    names = {c.get("name") for c in insp.get_unique_constraints(table)}
    names |= {c.get("name") for c in insp.get_foreign_keys(table)}
    return name in names


def _column_type(table: str, column: str) -> str | None:
    return op.get_bind().execute(sa.text(
        "SELECT data_type FROM information_schema.columns WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar()


def _sql_list(values) -> str:
    return ", ".join("'%s'" % v for v in values)


def upgrade() -> None:
    # --- Tablas nuevas (en orden de llaves foráneas) ---------------------------------------------

    # Bóveda de evidencia (K-REPORTES): índice encadenado de solo inserción; owner_user_id sin FK a propósito
    # (la evidencia sobrevive al borrado de la cuenta). El trigger va al final.
    op.create_table('evidence_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('owner_user_id', sa.Integer(), nullable=True),
    sa.Column('content_report_id', sa.Integer(), nullable=True),
    sa.Column('copyright_notice_id', sa.Integer(), nullable=True),
    sa.Column('authority_request_id', sa.Integer(), nullable=True),
    sa.Column('reason', sa.String(length=60), nullable=True),
    sa.Column('is_csam', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('storage_path', sa.String(length=300), nullable=True),
    sa.Column('size_bytes', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('files', sa.JSON(), nullable=True),
    sa.Column('prev_hash', sa.String(length=64), nullable=True),
    sa.Column('row_hash', sa.String(length=64), nullable=False),
    sa.Column('retained_until', sa.DateTime(), nullable=False),
    sa.Column('legal_hold', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('legal_hold_reason', sa.String(length=300), nullable=True),
    sa.Column('legal_hold_by_id', sa.Integer(), nullable=True),
    sa.Column('legal_hold_at', sa.DateTime(), nullable=True),
    sa.Column('purged_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('row_hash'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_evidence_records_id'), 'evidence_records', ['id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_evidence_records_owner_user_id'), 'evidence_records', ['owner_user_id'], unique=False, if_not_exists=True)
    op.create_index('ix_evidence_records_purge', 'evidence_records', ['retained_until', 'legal_hold', 'purged_at'], unique=False, if_not_exists=True)
    op.create_index('ix_evidence_records_target', 'evidence_records', ['target_type', 'target_id'], unique=False, if_not_exists=True)

    # Folios PF-AAAA-NNNNN del centro de solicitudes (contador atómico por prefijo y año)
    op.create_table('folio_counters',
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('last_value', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.PrimaryKeyConstraint('scope', 'year'),
    if_not_exists=True,
    )

    # Registro de versiones de los documentos legales (K-DOCS), sincronizado desde versiones.json
    op.create_table('legal_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('effective_at', sa.DateTime(), nullable=True),
    sa.Column('published_at', sa.DateTime(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('requires_reacceptance', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('url', sa.String(length=255), nullable=False),
    sa.Column('notice_sent_at', sa.DateTime(), nullable=True),
    sa.Column('notice_cursor', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug', 'sha256', name='uq_legal_documents_slug_sha256'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_legal_documents_id'), 'legal_documents', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_legal_documents_slug_published', 'legal_documents', ['slug', 'published_at'], unique=False, if_not_exists=True)

    # Bitácora de cada corrida de la purga de conservación (K-CONSERV)
    op.create_table('retention_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'running'"), nullable=False),
    sa.Column('dry_run', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('results', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_retention_runs_id'), 'retention_runs', ['id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_retention_runs_started_at'), 'retention_runs', ['started_at'], unique=False, if_not_exists=True)

    # Bitácora de permisos dados o retirados (K-PREF): solo inserción (trigger al final)
    op.create_table('consent_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('purpose', sa.String(length=40), nullable=False),
    sa.Column('granted', sa.Boolean(), nullable=False),
    sa.Column('text_version', sa.String(length=40), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_consent_records_id'), 'consent_records', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_consent_records_user_purpose', 'consent_records', ['user_id', 'purpose', 'id'], unique=False, if_not_exists=True)

    # Avisos de derechos de autor (Reglamento LFDA art. 37 Quáter)
    op.create_table('copyright_notices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=24), nullable=False),
    sa.Column('kind', sa.String(length=20), server_default=sa.text("'derechos_autor'"), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'received'"), nullable=False),
    sa.Column('content_url', sa.String(length=1000), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=True),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('photo_urls', sa.JSON(), nullable=True),
    sa.Column('work', sa.Text(), nullable=False),
    sa.Column('facts', sa.Text(), nullable=False),
    sa.Column('claimant_name', sa.String(length=255), nullable=False),
    sa.Column('claimant_capacity', sa.String(length=20), nullable=False),
    sa.Column('represented_name', sa.String(length=255), nullable=True),
    sa.Column('representation_document', sa.Text(), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('alt_email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=False),
    sa.Column('address', sa.Text(), nullable=False),
    sa.Column('good_faith', sa.Boolean(), nullable=False),
    sa.Column('knows_penalty', sa.Boolean(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('uploader_user_id', sa.Integer(), nullable=True),
    sa.Column('due_at', sa.DateTime(), nullable=True),
    sa.Column('removed_at', sa.DateTime(), nullable=True),
    sa.Column('removed_by_id', sa.Integer(), nullable=True),
    sa.Column('uploader_notified_at', sa.DateTime(), nullable=True),
    sa.Column('restore_from', sa.DateTime(), nullable=True),
    sa.Column('restore_until', sa.DateTime(), nullable=True),
    sa.Column('proceeding_at', sa.DateTime(), nullable=True),
    sa.Column('proceeding_note', sa.Text(), nullable=True),
    sa.Column('restored_at', sa.DateTime(), nullable=True),
    sa.Column('admin_notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['removed_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['uploader_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_copyright_notices_id'), 'copyright_notices', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_copyright_notices_status_created', 'copyright_notices', ['status', 'created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_copyright_notices_uploader', 'copyright_notices', ['uploader_user_id', 'removed_at'], unique=False, if_not_exists=True)

    # Bitácora de aceptaciones (K-ACEPT): cadena SHA-256 (prev_hash único evita bifurcaciones), solo inserción
    op.create_table('legal_acceptances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('accepted_at', sa.DateTime(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('context', sa.JSON(), nullable=True),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('row_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prev_hash', name='uq_legal_acceptances_prev_hash'),
    sa.UniqueConstraint('row_hash'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_legal_acceptances_id'), 'legal_acceptances', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_legal_acceptances_user_slug', 'legal_acceptances', ['user_id', 'slug', 'id'], unique=False, if_not_exists=True)

    # Doble factor de administradores: códigos de recuperación de un solo uso
    op.create_table('mfa_recovery_codes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('code_hash', sa.String(length=200), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_mfa_recovery_codes_id'), 'mfa_recovery_codes', ['id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_mfa_recovery_codes_user_id'), 'mfa_recovery_codes', ['user_id'], unique=False, if_not_exists=True)

    # Registro de incidentes de seguridad (runbook §10) y tablero de estado (K-ESTADO)
    op.create_table('security_incidents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=20), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=20), server_default=sa.text("'vulneracion'"), nullable=False),
    sa.Column('incident_type', sa.String(length=30), nullable=True),
    sa.Column('severity', sa.String(length=2), server_default=sa.text("'S3'"), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'abierto'"), nullable=False),
    sa.Column('detection_source', sa.String(length=200), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('systems_affected', sa.JSON(), nullable=True),
    sa.Column('data_categories', sa.JSON(), nullable=True),
    sa.Column('components', sa.JSON(), nullable=True),
    sa.Column('affected_count', sa.Integer(), nullable=True),
    sa.Column('significant_impact', sa.Boolean(), nullable=True),
    sa.Column('significant_impact_reason', sa.Text(), nullable=True),
    sa.Column('contractual_notices', sa.JSON(), nullable=True),
    sa.Column('authority_report', sa.JSON(), nullable=True),
    sa.Column('sabg_notified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('root_cause', sa.Text(), nullable=True),
    sa.Column('immediate_actions', sa.Text(), nullable=True),
    sa.Column('definitive_actions', sa.Text(), nullable=True),
    sa.Column('evidence_ref', sa.String(length=500), nullable=True),
    sa.Column('freeze_purges', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('freeze_purges_until', sa.DateTime(), nullable=True),
    sa.Column('detected_at', sa.DateTime(), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('contained_at', sa.DateTime(), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('public', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('public_summary', sa.Text(), nullable=True),
    sa.Column('notice', sa.JSON(), nullable=True),
    sa.Column('notice_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('timeline', sa.JSON(), nullable=True),
    sa.Column('lead_id', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['lead_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_security_incidents_id'), 'security_incidents', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_security_incidents_public', 'security_incidents', ['public', 'started_at'], unique=False, if_not_exists=True)
    op.create_index('ix_security_incidents_status_detected', 'security_incidents', ['status', 'detected_at'], unique=False, if_not_exists=True)

    # Verificación reforzada de edad tras un reporte «involucra a un menor»
    op.create_table('age_checks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'required'"), nullable=False),
    sa.Column('reason', sa.String(length=40), nullable=False),
    sa.Column('content_report_id', sa.Integer(), nullable=True),
    sa.Column('requested_by_id', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('birth_date_confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('otp_sent_at', sa.DateTime(), nullable=True),
    sa.Column('otp_verified_at', sa.DateTime(), nullable=True),
    sa.Column('declaration_at', sa.DateTime(), nullable=True),
    sa.Column('method', sa.String(length=60), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['content_report_id'], ['content_reports.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_age_checks_id'), 'age_checks', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_age_checks_status_created', 'age_checks', ['status', 'created_at'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_age_checks_user_id'), 'age_checks', ['user_id'], unique=False, if_not_exists=True)

    # Requerimientos de autoridades y denuncias (niveles 1 a 3, preservación)
    op.create_table('authority_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=24), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('level', sa.Integer(), nullable=True),
    sa.Column('authority_name', sa.String(length=255), nullable=False),
    sa.Column('authority_type', sa.String(length=40), nullable=False),
    sa.Column('case_number', sa.String(length=120), nullable=True),
    sa.Column('legal_basis', sa.Text(), nullable=True),
    sa.Column('requested_data', sa.Text(), nullable=True),
    sa.Column('targets', sa.JSON(), nullable=True),
    sa.Column('involves_minor', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('life_risk', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('judicial_order', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('participant_consent', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=True),
    sa.Column('first_response_due_at', sa.DateTime(), nullable=True),
    sa.Column('authenticity_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('authenticity_method', sa.String(length=300), nullable=True),
    sa.Column('legal_review', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'recibido'"), nullable=False),
    sa.Column('decision', sa.Text(), nullable=True),
    sa.Column('response_summary', sa.Text(), nullable=True),
    sa.Column('responded_at', sa.DateTime(), nullable=True),
    sa.Column('user_notified', sa.Boolean(), nullable=True),
    sa.Column('notice_withheld_reason', sa.String(length=300), nullable=True),
    sa.Column('external_folio', sa.String(length=120), nullable=True),
    sa.Column('evidence_ids', sa.JSON(), nullable=True),
    sa.Column('content_report_id', sa.Integer(), nullable=True),
    sa.Column('handled_by_id', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['content_report_id'], ['content_reports.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['handled_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_authority_requests_id'), 'authority_requests', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_authority_requests_status_due', 'authority_requests', ['status', 'first_response_due_at'], unique=False, if_not_exists=True)

    # Staydown: hashes perceptuales de imágenes retiradas (no se pueden volver a subir)
    op.create_table('blocked_image_hashes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('ahash', sa.String(length=16), nullable=False),
    sa.Column('dhash', sa.String(length=16), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('copyright_notice_id', sa.Integer(), nullable=True),
    sa.Column('evidence_id', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('hits', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_hit_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['copyright_notice_id'], ['copyright_notices.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index('ix_blocked_image_hashes_active', 'blocked_image_hashes', ['active', 'kind'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_blocked_image_hashes_id'), 'blocked_image_hashes', ['id'], unique=False, if_not_exists=True)

    # Contraavisos (Reglamento LFDA art. 37 Septies)
    op.create_table('copyright_counter_notices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=24), nullable=False),
    sa.Column('notice_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('capacity', sa.String(length=20), nullable=False),
    sa.Column('represented_name', sa.String(length=255), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('address', sa.Text(), nullable=False),
    sa.Column('basis', sa.String(length=20), nullable=False),
    sa.Column('basis_details', sa.Text(), nullable=False),
    sa.Column('good_faith', sa.Boolean(), nullable=False),
    sa.Column('knows_penalty', sa.Boolean(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['notice_id'], ['copyright_notices.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio'),
    sa.UniqueConstraint('notice_id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_copyright_counter_notices_id'), 'copyright_counter_notices', ['id'], unique=False, if_not_exists=True)

    # Alertas de donativos acumulados (LFPIORPI: umbrales de identificación y aviso)
    op.create_table('donation_aml_flags',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('refuge_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('threshold', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('window_start', sa.DateTime(), nullable=False),
    sa.Column('donation_ids', sa.JSON(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['refuge_id'], ['refuges.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_donation_aml_flags_id'), 'donation_aml_flags', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_donation_aml_flags_pair', 'donation_aml_flags', ['user_id', 'refuge_id', 'level', 'created_at'], unique=False, if_not_exists=True)

    # Medidas de moderación con declaración de motivos y folio de apelación
    op.create_table('moderation_actions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=24), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('target_type', sa.String(length=30), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('rule', sa.String(length=60), nullable=False),
    sa.Column('rule_text', sa.String(length=300), nullable=False),
    sa.Column('detection', sa.String(length=20), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=True),
    sa.Column('ends_at', sa.DateTime(), nullable=True),
    sa.Column('content_report_id', sa.Integer(), nullable=True),
    sa.Column('copyright_notice_id', sa.Integer(), nullable=True),
    sa.Column('evidence_id', sa.Integer(), nullable=True),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('notice_sent_at', sa.DateTime(), nullable=True),
    sa.Column('notice_withheld_reason', sa.String(length=120), nullable=True),
    sa.Column('appeal_until', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['content_report_id'], ['content_reports.id'], ),
    sa.ForeignKeyConstraint(['copyright_notice_id'], ['copyright_notices.id'], ),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence_records.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_moderation_actions_id'), 'moderation_actions', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_moderation_actions_status_ends', 'moderation_actions', ['status', 'ends_at'], unique=False, if_not_exists=True)
    op.create_index('ix_moderation_actions_user', 'moderation_actions', ['user_id', 'created_at'], unique=False, if_not_exists=True)

    # Avisos enviados por incidente: una fila por persona, canal y versión del aviso
    op.create_table('security_incident_notices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('incident_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('channel', sa.String(length=10), nullable=False),
    sa.Column('notice_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'enviado'"), nullable=False),
    sa.Column('sent_at', sa.DateTime(), nullable=False),
    sa.Column('sent_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['incident_id'], ['security_incidents.id'], ),
    sa.ForeignKeyConstraint(['sent_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_security_incident_notices_id'), 'security_incident_notices', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_security_incident_notices_incident', 'security_incident_notices', ['incident_id', 'user_id'], unique=False, if_not_exists=True)

    # Centro de solicitudes (K-SOLIC): ARCO, revocación, limitación, quejas, aclaraciones, retiro de importados
    op.create_table('compliance_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'recibida'"), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=True),
    sa.Column('denial_reason', sa.String(length=40), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('channel', sa.String(length=20), server_default=sa.text("'web'"), nullable=False),
    sa.Column('acting_as', sa.String(length=20), server_default=sa.text("'titular'"), nullable=False),
    sa.Column('holder_name', sa.String(length=255), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('lost_report_id', sa.Integer(), nullable=True),
    sa.Column('content_report_id', sa.Integer(), nullable=True),
    sa.Column('order_id', sa.Integer(), nullable=True),
    sa.Column('identity_verified_at', sa.DateTime(), nullable=True),
    sa.Column('identity_method', sa.String(length=20), nullable=True),
    sa.Column('confirm_token_hash', sa.String(length=64), nullable=True),
    sa.Column('confirm_expires_at', sa.DateTime(), nullable=True),
    sa.Column('access_token_hash', sa.String(length=64), nullable=True),
    sa.Column('access_expires_at', sa.DateTime(), nullable=True),
    sa.Column('id_document_id', sa.String(length=64), nullable=True),
    sa.Column('id_document_sha256', sa.String(length=64), nullable=True),
    sa.Column('id_document_requested_at', sa.DateTime(), nullable=True),
    sa.Column('id_document_uploaded_at', sa.DateTime(), nullable=True),
    sa.Column('id_document_purged_at', sa.DateTime(), nullable=True),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.Column('first_response_due_at', sa.DateTime(), nullable=True),
    sa.Column('first_response_at', sa.DateTime(), nullable=True),
    sa.Column('respond_by', sa.DateTime(), nullable=False),
    sa.Column('respond_extended_at', sa.DateTime(), nullable=True),
    sa.Column('effective_by', sa.DateTime(), nullable=True),
    sa.Column('effective_extended_at', sa.DateTime(), nullable=True),
    sa.Column('extension_reason', sa.Text(), nullable=True),
    sa.Column('info_requested_at', sa.DateTime(), nullable=True),
    sa.Column('info_due_at', sa.DateTime(), nullable=True),
    sa.Column('info_received_at', sa.DateTime(), nullable=True),
    sa.Column('responded_at', sa.DateTime(), nullable=True),
    sa.Column('response_text', sa.Text(), nullable=True),
    sa.Column('effective_at', sa.DateTime(), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('assigned_to_id', sa.Integer(), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['content_report_id'], ['content_reports.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['lost_report_id'], ['lost_reports.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_compliance_requests_access_token_hash'), 'compliance_requests', ['access_token_hash'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_compliance_requests_confirm_token_hash'), 'compliance_requests', ['confirm_token_hash'], unique=False, if_not_exists=True)
    op.create_index('ix_compliance_requests_email', 'compliance_requests', ['email'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_compliance_requests_id'), 'compliance_requests', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_compliance_requests_kind_received', 'compliance_requests', ['kind', 'received_at'], unique=False, if_not_exists=True)
    op.create_index('ix_compliance_requests_status_respond_by', 'compliance_requests', ['status', 'respond_by'], unique=False, if_not_exists=True)
    op.create_index('ix_compliance_requests_user', 'compliance_requests', ['user_id'], unique=False, if_not_exists=True)

    # Apelaciones de medidas de moderación
    op.create_table('moderation_appeals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=24), nullable=False),
    sa.Column('action_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('arguments', sa.Text(), nullable=False),
    sa.Column('evidence_text', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=False),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['action_id'], ['moderation_actions.id'], ),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_moderation_appeals_action_id'), 'moderation_appeals', ['action_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_moderation_appeals_id'), 'moderation_appeals', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_moderation_appeals_status_due', 'moderation_appeals', ['status', 'due_at'], unique=False, if_not_exists=True)

    # Bonificación del 20 % (LFPC art. 92 Ter) por devoluciones de productos defectuosos
    op.create_table('order_bonuses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('refuge_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('reason', sa.String(length=30), nullable=True),
    sa.Column('base_amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('covered_items', sa.JSON(), nullable=True),
    sa.Column('percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'pendiente'"), nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=True),
    sa.Column('paid_at', sa.DateTime(), nullable=True),
    sa.Column('payment_reference', sa.String(length=255), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('resolved_by', sa.Integer(), nullable=True),
    sa.Column('reminded_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
    sa.ForeignKeyConstraint(['refuge_id'], ['refuges.id'], ),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_order_bonuses_id'), 'order_bonuses', ['id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_order_bonuses_refuge_id'), 'order_bonuses', ['refuge_id'], unique=False, if_not_exists=True)
    op.create_index('ix_order_bonuses_status_due', 'order_bonuses', ['status', 'due_at'], unique=False, if_not_exists=True)
    # Partidas que cubre la bonificación (bases que ya tenían la tabla)
    op.add_column('order_bonuses', sa.Column('covered_items', sa.JSON(), nullable=True), if_not_exists=True)

    # Línea de tiempo de cada solicitud
    op.create_table('compliance_request_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('public_note', sa.Text(), nullable=True),
    sa.Column('internal_note', sa.Text(), nullable=True),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['compliance_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index(op.f('ix_compliance_request_events_id'), 'compliance_request_events', ['id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_compliance_request_events_request_id'), 'compliance_request_events', ['request_id'], unique=False, if_not_exists=True)
    # --- Moderación legal: reportes públicos sin cuenta, prioridad y plazo en la cola --------------
    # Tope de 30 días del congelamiento de purgas (la tabla pudo crearse antes en la base de desarrollo)
    op.add_column('security_incidents', sa.Column('freeze_purges_until', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('content_reports', sa.Column('source', sa.String(length=20), server_default=sa.text("'app'"), nullable=False), if_not_exists=True)
    op.add_column('content_reports', sa.Column('priority', sa.Integer(), server_default=sa.text('3'), nullable=False), if_not_exists=True)
    op.add_column('content_reports', sa.Column('due_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('content_reports', sa.Column('auto_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    op.add_column('content_reports', sa.Column('folio', sa.String(length=24), nullable=True), if_not_exists=True)
    op.add_column('content_reports', sa.Column('contact_email', sa.String(length=255), nullable=True), if_not_exists=True)
    op.add_column('content_reports', sa.Column('reporter_ip', sa.String(length=64), nullable=True), if_not_exists=True)
    op.add_column('content_reports', sa.Column('target_url', sa.String(length=1000), nullable=True), if_not_exists=True)
    op.create_index('ix_content_reports_queue', 'content_reports', ['status', 'priority', 'created_at'], unique=False, if_not_exists=True)
    if not _has_constraint('content_reports', 'content_reports_folio_key'):
        op.create_unique_constraint('content_reports_folio_key', 'content_reports', ['folio'])

    # --- Reglas de negocio: retención para revisión y perros encontrados ---------------------------
    op.add_column('dogs', sa.Column('review_hold', sa.String(length=40), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('review_terms', sa.JSON(), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('review_hold_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('found_report_id', sa.Integer(), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('found_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('microchip_checked_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('microchip_result', sa.String(length=30), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('authority_notified_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('dogs', sa.Column('authority_notice', sa.String(length=255), nullable=True), if_not_exists=True)
    # Un reporte de «encontrado» se liga a una sola ficha: se desligan los duplicados (se queda la ficha más antigua;
    # la otra sigue marcada como encontrada y en resguardo hasta que se ligue a su propio reporte)
    op.execute("""
        UPDATE dogs d SET found_report_id = NULL
        WHERE d.found_report_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM dogs o WHERE o.found_report_id = d.found_report_id AND o.id < d.id)
    """)
    op.drop_index('ix_dogs_found_report_id', table_name='dogs', if_exists=True)
    op.create_index(op.f('ix_dogs_found_report_id'), 'dogs', ['found_report_id'], unique=True, if_not_exists=True)
    if not _has_constraint('dogs', 'dogs_found_report_id_fkey'):
        op.create_foreign_key('dogs_found_report_id_fkey', 'dogs', 'lost_reports', ['found_report_id'], ['id'])

    # Productos: categoría permitida, garantía (mínimo 90 días si se indica), perecedero y retención
    op.add_column('products', sa.Column('category', sa.String(length=40), nullable=True), if_not_exists=True)
    op.add_column('products', sa.Column('warranty_text', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('products', sa.Column('warranty_days', sa.Integer(), nullable=True), if_not_exists=True)
    op.add_column('products', sa.Column('is_perishable', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    op.add_column('products', sa.Column('review_hold', sa.String(length=40), nullable=True), if_not_exists=True)
    op.add_column('products', sa.Column('review_terms', sa.JSON(), nullable=True), if_not_exists=True)
    op.add_column('products', sa.Column('review_hold_at', sa.DateTime(), nullable=True), if_not_exists=True)

    # Facturas: recordatorio al refugio a las 24 h y aviso al equipo a las 72 h
    op.add_column('order_invoices', sa.Column('reminded_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('order_invoices', sa.Column('escalated_at', sa.DateTime(), nullable=True), if_not_exists=True)

    # --- Cifrado en reposo de los datos fiscales (VARCHAR -> TEXT; el texto cifrado es más largo) ---
    for table, column, _length in ENCRYPTED_COLUMNS:
        if _column_type(table, column) != 'text':
            op.alter_column(table, column, existing_type=sa.String(length=_length), type_=sa.Text(),
                            existing_nullable=False)

    # --- Refugios: consentimiento para la transparencia y borrado de identificaciones --------------
    op.add_column('refuges', sa.Column('transparency_opt_in_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('refuges', sa.Column('verification_decided_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('refuges', sa.Column('documents_purged_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('veterinaries', sa.Column('cedula_document_purged_at', sa.DateTime(), nullable=True), if_not_exists=True)

    # --- Usuarios: permisos (todos apagados por defecto), edad y doble factor ----------------------
    op.add_column('users', sa.Column('whatsapp_alerts', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    op.add_column('users', sa.Column('birth_date', sa.Date(), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('adult_declared_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('age_check_status', sa.String(length=20), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('mfa_secret_enc', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('mfa_pending_secret_enc', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('mfa_enabled_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('mfa_last_step', sa.Integer(), nullable=True), if_not_exists=True)
    op.alter_column('users', 'notify_nearby', existing_type=sa.Boolean(), server_default=sa.text('false'),
                    existing_nullable=False)

    # --- Datos ------------------------------------------------------------------------------------
    # Alertas cercanas solo con consentimiento registrado (K-PREF): se apagan para quien no tiene un último
    # registro «sí». Antes de 0004 no existía consent_records, así que en producción se apagan para todos;
    # la app les muestra una invitación para activarlas. Repetirla no cambia a quien ya las aceptó.
    op.execute("""
        UPDATE users u SET notify_nearby = false
        WHERE u.notify_nearby
          AND NOT COALESCE((SELECT c.granted FROM consent_records c
                            WHERE c.user_id = u.id AND c.purpose = 'notify_nearby'
                            ORDER BY c.id DESC LIMIT 1), false)
    """)
    # La ubicación de la cuenta solo existe para las alertas cercanas (privacidad.html §8): se borra donde están
    # apagadas (la app ya no la guarda sin ellas y apagarlas la borra)
    op.execute("UPDATE users SET latitude = NULL, longitude = NULL "
               "WHERE NOT notify_nearby AND (latitude IS NOT NULL OR longitude IS NOT NULL)")
    # Los donativos ya no suman puntos en el ranking (política de donativos): se descuenta, una sola vez por
    # refugio, lo que habían sumado (la marca 'donation_points_removed' evita repetirlo)
    op.execute("""
        WITH s AS (SELECT refuge_id, SUM(points) AS total FROM point_logs
                   WHERE action IN ('donation', 'donation_refund') GROUP BY refuge_id HAVING SUM(points) <> 0),
             todo AS (SELECT s.* FROM s WHERE NOT EXISTS (
                        SELECT 1 FROM point_logs p WHERE p.refuge_id = s.refuge_id AND p.action = 'donation_points_removed')),
             upd AS (UPDATE refuges r SET points = GREATEST(0, r.points - todo.total) FROM todo
                     WHERE r.id = todo.refuge_id RETURNING r.id)
        INSERT INTO point_logs (refuge_id, action, points, description, created_at)
        SELECT refuge_id, 'donation_points_removed', -total,
               'Los donativos ya no suman puntos en el ranking (política de donativos)', now() AT TIME ZONE 'UTC'
        FROM todo
    """)
    # Reportes abiertos: la prioridad de su motivo (los nuevos la reciben al crearse)
    op.execute(f"UPDATE content_reports SET priority = 1 WHERE status = 'open' AND priority = 3 "
               f"AND reason IN ({_sql_list(PRIORITY_1_REASONS)})")
    op.execute(f"UPDATE content_reports SET priority = 2 WHERE status = 'open' AND priority = 3 "
               f"AND reason IN ({_sql_list(PRIORITY_2_REASONS)})")
    op.execute("UPDATE content_reports SET priority = 0 WHERE status = 'open' AND priority <> 0 "
               "AND reason IN ('involucra_menor', 'abuso_sexual_infantil')")
    # Retenciones automáticas abiertas: «Estafas y venta» las de fichas de adopción y un plazo de revisión (3 días
    # hábiles ~ 5 naturales) para que la cola las marque como vencidas
    op.execute("UPDATE content_reports SET priority = 2 WHERE status = 'open' AND priority = 3 "
               "AND reason = 'retencion_automatica' AND target_type = 'dog'")
    op.execute("UPDATE content_reports SET due_at = created_at + interval '5 days' WHERE status = 'open' "
               "AND reason = 'retencion_automatica' AND due_at IS NULL")

    # --- Bitácoras de solo inserción ---------------------------------------------------------------
    op.execute(LEGAL_LOG_APPEND_ONLY_SQL)
    op.execute(EVIDENCE_APPEND_ONLY_SQL)


def downgrade() -> None:
    # Los pasos de datos no se revierten: las alertas cercanas siguen apagadas y los puntos de donativos
    # no vuelven al ranking.
    op.execute("DROP TRIGGER IF EXISTS evidence_records_append_only ON evidence_records")
    op.execute("DROP FUNCTION IF EXISTS evidence_records_append_only()")
    for table in ('legal_acceptances', 'consent_records'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}")
    op.execute("DROP FUNCTION IF EXISTS legal_log_append_only()")

    # Usuarios
    op.alter_column('users', 'notify_nearby', existing_type=sa.Boolean(), server_default=sa.text('true'),
                    existing_nullable=False)
    for column in ('mfa_last_step', 'mfa_enabled_at', 'mfa_pending_secret_enc', 'mfa_secret_enc',
                   'age_check_status', 'adult_declared_at', 'birth_date', 'whatsapp_alerts'):
        op.drop_column('users', column, if_exists=True)

    # Refugios y clínicas
    op.drop_column('veterinaries', 'cedula_document_purged_at', if_exists=True)
    for column in ('documents_purged_at', 'verification_decided_at', 'transparency_opt_in_at'):
        op.drop_column('refuges', column, if_exists=True)

    # Datos fiscales: solo se puede volver a VARCHAR si no hay valores cifrados (más largos que la columna
    # original). PostgreSQL rechaza el cambio en ese caso en lugar de recortar.
    for table, column, length in ENCRYPTED_COLUMNS:
        too_long = op.get_bind().execute(sa.text(
            f"SELECT count(*) FROM {table} WHERE length({column}) > {length}")).scalar()
        if too_long:
            raise RuntimeError(
                f"{table}.{column} tiene {too_long} valores cifrados: no se puede volver a VARCHAR({length}) "
                "sin perder datos. Restaura un respaldo anterior a 0004 en lugar de hacer downgrade.")
        op.alter_column(table, column, existing_type=sa.Text(), type_=sa.String(length=length),
                        existing_nullable=False)

    # Facturas, productos y perros
    for column in ('escalated_at', 'reminded_at'):
        op.drop_column('order_invoices', column, if_exists=True)
    for column in ('review_hold_at', 'review_terms', 'review_hold', 'is_perishable', 'warranty_days',
                   'warranty_text', 'category'):
        op.drop_column('products', column, if_exists=True)
    if _has_constraint('dogs', 'dogs_found_report_id_fkey'):
        op.drop_constraint('dogs_found_report_id_fkey', 'dogs', type_='foreignkey')
    op.drop_index('ix_dogs_found_report_id', table_name='dogs', if_exists=True)
    for column in ('authority_notice', 'authority_notified_at', 'microchip_result', 'microchip_checked_at',
                   'found_at', 'found_report_id', 'review_hold_at', 'review_terms', 'review_hold'):
        op.drop_column('dogs', column, if_exists=True)

    # Reportes (las tablas que apuntan a content_reports se borran abajo; aquí solo columnas)
    if _has_constraint('content_reports', 'content_reports_folio_key'):
        op.drop_constraint('content_reports_folio_key', 'content_reports', type_='unique')
    op.drop_index('ix_content_reports_queue', table_name='content_reports', if_exists=True)
    for column in ('target_url', 'reporter_ip', 'contact_email', 'folio', 'auto_hidden', 'due_at', 'priority',
                   'source'):
        op.drop_column('content_reports', column, if_exists=True)

    # Tablas nuevas, primero las que dependen de otras
    for table in ('compliance_request_events', 'order_bonuses', 'moderation_appeals', 'compliance_requests',
                  'security_incident_notices', 'moderation_actions', 'donation_aml_flags',
                  'copyright_counter_notices', 'blocked_image_hashes', 'authority_requests', 'age_checks',
                  'security_incidents', 'mfa_recovery_codes', 'legal_acceptances', 'copyright_notices',
                  'consent_records', 'retention_runs', 'legal_documents', 'folio_counters', 'evidence_records'):
        op.drop_table(table, if_exists=True)
