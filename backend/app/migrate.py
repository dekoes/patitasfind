"""Migraciones de Alembic: la única forma de crear o cambiar el esquema (la app ya no hace create_all).

Uso (deploy.sh lo corre UNA vez antes de cambiar contenedores; entrypoint.sh cuando RUN_MIGRATIONS=true):
    python -m app.migrate

- Base vacía: `alembic upgrade head` crea todo desde la baseline.
- Base creada antes con create_all + STARTUP_MIGRATIONS (tiene `users` pero ninguna versión registrada):
  se aplican una sola vez los LEGACY_STATEMENTS (los ALTER/CREATE INDEX idempotentes que antes corrían en
  cada arranque), se hace `alembic stamp 0001_baseline` (no se recrean tablas) y luego `upgrade head`.
- Base ya versionada: `upgrade head`.
Un advisory lock de PostgreSQL evita que dos contenedores migren a la vez.
"""
import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import engine

BASELINE = "0001_baseline"
LOCK_ID = 724502
# Un ALTER que espera un candado detrás de una transacción abierta bloquearía a toda la app: mejor fallar
# (y abortar el despliegue sin tocar lo que está corriendo) que esperar sin límite.
LOCK_TIMEOUT = "60s"
logger = logging.getLogger("patitasfind.migrate")

# ALTERs idempotentes que la app aplicaba en cada arranque antes de Alembic (solo PostgreSQL). Dejan una
# base antigua en el estado de 0001_baseline; lo nuevo va en revisiones de alembic/versions/.
LEGACY_STATEMENTS = [
    # --- previas ---
    "ALTER TABLE lost_reports ADD COLUMN IF NOT EXISTS report_type VARCHAR(50) DEFAULT 'lost'",
    "ALTER TABLE lost_reports ALTER COLUMN reporter_id DROP NOT NULL",
    "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL",
    "ALTER TABLE dogs ADD COLUMN IF NOT EXISTS color VARCHAR(100)",
    # --- usuarios ---
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_otp_hash VARCHAR(128)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_otp_expires_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500)",
    # --- verificación de teléfono, cuenta y consentimiento legal ---
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_otp_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_otp_sent_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(64)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version VARCHAR(20)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_version VARCHAR(20)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP",
    "CREATE INDEX IF NOT EXISTS ix_users_google_sub ON users(google_sub)",
    # Teléfonos a E.164 (+52 y 10 dígitos) para poder compararlos
    r"UPDATE users SET phone = '+52' || phone WHERE phone ~ '^[2-9][0-9]{9}$'",
    r"UPDATE users SET phone = '+52' || substr(phone, 3) WHERE phone ~ '^52[2-9][0-9]{9}$'",
    r"UPDATE users SET phone = '+52' || substr(phone, 4) WHERE phone ~ '^521[2-9][0-9]{9}$'",
    r"UPDATE users SET phone = '+52' || substr(phone, 5) WHERE phone ~ '^\+521[2-9][0-9]{9}$'",
    # (El UPDATE que marcaba el teléfono del usuario demo como verificado se eliminó: seed_data.py ya lo
    #  crea verificado en desarrollo y en producción la cuenta demo está bloqueada.)
    # Un teléfono verificado por cuenta activa: si había duplicados se conserva el más antiguo
    """UPDATE users u SET phone_verified = FALSE WHERE u.phone_verified AND u.is_active AND u.phone IS NOT NULL
       AND EXISTS (SELECT 1 FROM users o WHERE o.phone = u.phone AND o.phone_verified AND o.is_active AND o.id < u.id)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_verified_phone ON users(phone) WHERE phone_verified AND is_active AND phone IS NOT NULL",
    # --- perros ---
    "ALTER TABLE dogs ADD COLUMN IF NOT EXISTS ai_analysis JSON",
    "ALTER TABLE dogs ADD COLUMN IF NOT EXISTS photo_signature JSON",
    # --- reportes ---
    "ALTER TABLE lost_reports ADD COLUMN IF NOT EXISTS source VARCHAR(30) NOT NULL DEFAULT 'app'",
    "ALTER TABLE lost_reports ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50)",
    "ALTER TABLE lost_reports ADD COLUMN IF NOT EXISTS external_url VARCHAR(500)",
    "ALTER TABLE lost_reports ADD COLUMN IF NOT EXISTS ai_analysis JSON",
    "ALTER TABLE lost_reports ADD COLUMN IF NOT EXISTS photo_signature JSON",
    "ALTER TABLE lost_reports ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP",
    # --- conversaciones ---
    "ALTER TABLE conversations ALTER COLUMN match_id DROP NOT NULL",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS lost_report_id INTEGER REFERENCES lost_reports(id)",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_a_id INTEGER REFERENCES users(id)",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_b_id INTEGER REFERENCES users(id)",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMP",
    """UPDATE conversations c SET user_a_id = m.user_id, user_b_id = d.owner_id
       FROM matches m JOIN dogs d ON d.id = m.dog_id
       WHERE c.match_id = m.id AND (c.user_a_id IS NULL OR c.user_b_id IS NULL)""",
    """UPDATE conversations c SET last_message_at = sub.last_at
       FROM (SELECT conversation_id, MAX(created_at) AS last_at FROM messages GROUP BY conversation_id) sub
       WHERE sub.conversation_id = c.id AND c.last_message_at IS NULL""",
    # --- notificaciones / recordatorios ---
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS data JSON",
    "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS notified_at TIMESTAMP",
    # --- tienda ---
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS share_name BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot_interactions ADD COLUMN IF NOT EXISTS opted_out_at TIMESTAMP",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS provider VARCHAR(30)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS provider_preference_id VARCHAR(255)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS provider_payment_id VARCHAR(255)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP",
    # --- fuentes de Facebook ---
    "ALTER TABLE facebook_groups ADD COLUMN IF NOT EXISTS page_id VARCHAR(100)",
    "ALTER TABLE facebook_groups ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'manual'",
    "ALTER TABLE facebook_groups ADD COLUMN IF NOT EXISTS city VARCHAR(100)",
    # --- índices ---
    "CREATE INDEX IF NOT EXISTS idx_dogs_status ON dogs(status)",
    "CREATE INDEX IF NOT EXISTS idx_dogs_city ON dogs(city)",
    "CREATE INDEX IF NOT EXISTS idx_dogs_owner ON dogs(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_dogs_geo ON dogs(latitude, longitude)",
    "CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)",
    "CREATE INDEX IF NOT EXISTS idx_matches_user ON matches(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_matches_dog ON matches(dog_id)",
    "CREATE INDEX IF NOT EXISTS idx_refuges_status ON refuges(status)",
    "CREATE INDEX IF NOT EXISTS idx_lost_reports_status ON lost_reports(status)",
    "CREATE INDEX IF NOT EXISTS idx_lost_reports_geo ON lost_reports(latitude, longitude)",
    "CREATE INDEX IF NOT EXISTS idx_lost_reports_external ON lost_reports(external_url)",
    "CREATE INDEX IF NOT EXISTS idx_foster_homes_status ON foster_homes(status)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read)",
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_users ON conversations(user_a_id, user_b_id)",
    # índices declarados en los modelos que create_all no agregaba a tablas existentes
    "CREATE INDEX IF NOT EXISTS ix_bot_interactions_phone ON bot_interactions(phone)",
    "CREATE INDEX IF NOT EXISTS ix_conversations_user_a_id ON conversations(user_a_id)",
    "CREATE INDEX IF NOT EXISTS ix_conversations_user_b_id ON conversations(user_b_id)",
    "CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages(conversation_id)",
]


def _config() -> Config:
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def apply_legacy(conn) -> None:
    """Base anterior a Alembic: aplica los ALTER heredados para dejarla como la baseline (idempotente)."""
    for statement in LEGACY_STATEMENTS:
        conn.execute(text(statement))
    logger.info("ALTER heredados aplicados (%d sentencias).", len(LEGACY_STATEMENTS))


def run() -> str:
    cfg = _config()
    with engine.connect() as conn:
        is_pg = engine.dialect.name == "postgresql"
        if is_pg:
            conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
            conn.execute(text(f"SET lock_timeout = '{LOCK_TIMEOUT}'"))
        try:
            tables = set(inspect(conn).get_table_names())
            current = None
            if "alembic_version" in tables:
                current = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            cfg.attributes["connection"] = conn
            if current is None and "users" in tables:
                logger.info("Base existente sin Alembic: se aplican los ALTER heredados y se marca como %s.", BASELINE)
                if is_pg:
                    apply_legacy(conn)
                command.stamp(cfg, BASELINE)
                action = "stamped"
            else:
                action = "upgraded"
            command.upgrade(cfg, "head")
            conn.commit()
            return action
        except Exception:
            conn.rollback()
            raise
        finally:
            if is_pg:
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                conn.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    try:
        print(f"Migraciones: {run()}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR en migraciones: {exc}", file=sys.stderr)
        sys.exit(1)
