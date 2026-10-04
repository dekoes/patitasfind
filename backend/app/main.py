import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.database import Base, engine
from app import models  # noqa: F401 - registra los modelos en Base.metadata
from app.routers import (
    admin, ai, auth, dogs, facebook, foster_homes, lost_reports, matches, messages, notifications, orders,
    payments, products, refuges, reminders, search, uploads, users, whatsapp,
)
from app.services.realtime import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("patitasfind")

# Migraciones ligeras e idempotentes (ADD COLUMN IF NOT EXISTS). Solo PostgreSQL.
STARTUP_MIGRATIONS = [
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
]


def run_startup_migrations() -> None:
    """Crea tablas nuevas y aplica ALTERs idempotentes. Usa un advisory lock para varios workers."""
    if engine.dialect.name != "postgresql":
        Base.metadata.create_all(bind=engine)
        return
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(724501)"))
        Base.metadata.create_all(bind=conn)
        for statement in STARTUP_MIGRATIONS:
            conn.execute(text(statement))
    logger.info("Migraciones de arranque aplicadas.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_startup_migrations()
    os.makedirs(settings.upload_dir, exist_ok=True)
    yield
    await hub.shutdown()


app = FastAPI(title="PatitasFind API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Errores de validación con un `detail` legible en español (y la lista original en `errors`)."""
    fields = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path", "form")]
        fields.append(".".join(loc) or "solicitud")
    detail = "Revisa los datos enviados" + (f": {', '.join(dict.fromkeys(fields))}." if fields else ".")
    return JSONResponse(status_code=422, content={"detail": detail, "errors": jsonable_errors(exc.errors())})


def jsonable_errors(errors):
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(errors, custom_encoder={Exception: str})


for r in (
    auth, users, dogs, matches, messages, notifications, refuges, admin, products, orders, lost_reports,
    foster_homes, reminders, whatsapp, facebook, uploads, search, ai, payments,
):
    app.include_router(r.router)

os.makedirs(settings.upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/health")
def health():
    checks = {"database": "ok"}
    healthy = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc.__class__.__name__}"
        healthy = False
    if settings.redis_url:
        from app import cache

        r = cache._get_redis()
        try:
            checks["redis"] = "ok" if (r is not None and r.ping()) else "error"
        except Exception:  # noqa: BLE001
            checks["redis"] = "error"
        if checks["redis"] != "ok":
            healthy = False
    body = {"status": "ok" if healthy else "degraded", "checks": checks, "environment": settings.environment}
    return JSONResponse(status_code=200 if healthy else 503, content=body)
