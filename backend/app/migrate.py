"""Migraciones de Alembic seguras para bases existentes.

Uso (lo llama entrypoint.sh cuando RUN_MIGRATIONS=true):
    python -m app.migrate

- Base vacía: `alembic upgrade head` crea todo desde la baseline.
- Base creada antes con create_all (tiene `users` pero ninguna versión registrada): se hace
  `alembic stamp 0001_baseline` (no se recrean tablas) y luego `upgrade head`.
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
logger = logging.getLogger("patitasfind.migrate")


def _config() -> Config:
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def run() -> str:
    cfg = _config()
    with engine.connect() as conn:
        is_pg = engine.dialect.name == "postgresql"
        if is_pg:
            conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        try:
            tables = set(inspect(conn).get_table_names())
            current = None
            if "alembic_version" in tables:
                current = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            cfg.attributes["connection"] = conn
            if current is None and "users" in tables:
                logger.info("Base existente sin Alembic: se marca como %s.", BASELINE)
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
