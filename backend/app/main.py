import logging
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.config import settings
from app.database import engine
from app.dependencies import PHONE_VERIFICATION_CODE, PHONE_VERIFICATION_MESSAGE, PhoneVerificationRequired
from app.observability import RequestContextMiddleware, init_sentry, setup_logging
from app.routers import (
    admin, ai, auth, dogs, facebook, foster_homes, lost_reports, matches, messages, notifications, orders,
    payments, products, refuges, reminders, search, uploads, users, whatsapp,
)
from app.routers import documents
from app.routers import reports
from app.routers import veterinaries
from app.routers import fiscal
from app.routers import cumplimiento_docs
from app.routers import cumplimiento_solicitudes, cumplimiento_transparencia
from app.routers import cumplimiento_reportes
from app.routers import cumplimiento_seguridad
from app.routers import reglas as reglas_router
from app.services.legal_acceptance import ComplianceError
from app.services.realtime import hub

setup_logging()
init_sentry("backend")
logger = logging.getLogger("patitasfind")

# /health responde "degraded" (503) cuando la carpeta de fotos tiene menos espacio libre que esto
LOW_DISK_FREE_PERCENT = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    # El esquema lo administra Alembic (python -m app.migrate, lo corre deploy.sh / entrypoint.sh con
    # RUN_MIGRATIONS=true); la app no crea ni altera tablas al arrancar.
    os.makedirs(settings.upload_dir, exist_ok=True)
    _sync_legal_documents()
    yield
    await hub.shutdown()


def _sync_legal_documents() -> None:
    """Registro de versiones legales (K-DOCS): si versiones.json trae huellas nuevas, se sincroniza al arrancar."""
    from app.database import SessionLocal
    from app.services.legal_acceptance import sync_if_changed

    db = SessionLocal()
    try:
        result = sync_if_changed(db)
        if result:
            logger.info("Registro legal sincronizado al arrancar: %s nuevas, %s actualizadas.",
                        len(result["created"]), len(result["updated"]))
            for warning in result["warnings"]:
                logger.warning("Registro legal: %s", warning)
    except Exception:  # noqa: BLE001 - p. ej. la tabla aún no existe: no impide arrancar
        db.rollback()
        logger.exception("No se pudo sincronizar el registro de documentos legales al arrancar.")
    finally:
        db.close()


app = FastAPI(
    title="GuauWoow API", version="2.1.0", lifespan=lifespan,
    # En producción no se publican la documentación ni el esquema OpenAPI
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.effective_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(PhoneVerificationRequired)
async def phone_verification_handler(request: Request, exc: PhoneVerificationRequired):
    return JSONResponse(status_code=403, content={"detail": PHONE_VERIFICATION_MESSAGE, "code": PHONE_VERIFICATION_CODE})


@app.exception_handler(ComplianceError)
async def compliance_error_handler(request: Request, exc: ComplianceError):
    """Errores con código para el frontend: age_check_required, annex_required, legal_version_mismatch..."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code, **exc.extra})


@app.exception_handler(PoolTimeoutError)
async def pool_timeout_handler(request: Request, exc: PoolTimeoutError):
    """Pool de conexiones agotado (DB_POOL_TIMEOUT): un 503 rápido en lugar de una cola eterna."""
    logger.warning("Pool de conexiones agotado en %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503,
                        content={"detail": "Hay mucha demanda en este momento, inténtalo de nuevo en unos segundos."})


@app.exception_handler(OperationalError)
async def database_unavailable_handler(request: Request, exc: OperationalError):
    """PostgreSQL caído o reiniciándose (probado apagándolo con la app en marcha): antes la app recibía un 500 en texto
    plano «Internal Server Error». Ahora un 503 con un mensaje que la app muestra tal cual y que invita a reintentar."""
    logger.error("Base de datos no disponible en %s %s: %s", request.method, request.url.path, str(exc).splitlines()[0][:200])
    return JSONResponse(status_code=503, headers={"Retry-After": "15"},
                        content={"detail": "GuauWoow no está disponible por un momento. Inténtalo de nuevo en unos minutos."})


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

app.include_router(documents.router)
app.include_router(reports.router)
app.include_router(veterinaries.router)
app.include_router(fiscal.router)
app.include_router(cumplimiento_docs.router)
app.include_router(cumplimiento_solicitudes.router)
app.include_router(cumplimiento_transparencia.router)
app.include_router(cumplimiento_reportes.router)
app.include_router(cumplimiento_seguridad.router)  # conservación, estado del servicio, incidentes, MFA del panel
app.include_router(reglas_router.router)  # reglas de negocio: comprobante, bonificaciones, retenciones

os.makedirs(settings.upload_dir, exist_ok=True)
# PublicUploads responde 404 a /uploads/private/ (documentos privados de refugios)
app.mount("/uploads", documents.PublicUploads(directory=settings.upload_dir), name="uploads")


def _check_error(exc: Exception) -> str:
    """Valor de una revisión fallida; en producción no se revela la clase de la excepción."""
    return "error" if settings.is_production else f"error: {exc.__class__.__name__}"


def uploads_free_percent() -> float:
    """Porcentaje de espacio libre en el disco de la carpeta de fotos."""
    usage = shutil.disk_usage(settings.upload_dir)
    return usage.free * 100 / usage.total if usage.total else 0.0


@app.get("/health")
def health():
    checks = {"database": "ok"}
    healthy = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        checks["database"] = _check_error(exc)
        healthy = False
    if settings.redis_url:
        from app import cache

        try:
            r = cache._get_redis()
            checks["redis"] = "ok" if (r is not None and r.ping()) else "error"
        except Exception:  # noqa: BLE001
            checks["redis"] = "error"
        if checks["redis"] != "ok":
            healthy = False
    # Disco de las fotos: con menos del 5 % libre las subidas y los respaldos empezarían a fallar
    try:
        free = uploads_free_percent()
        if free < LOW_DISK_FREE_PERCENT:
            checks["uploads"] = "error" if settings.is_production else f"error: {free:.1f}% libre"
            healthy = False
        else:
            checks["uploads"] = "ok"
    except OSError as exc:
        checks["uploads"] = _check_error(exc)
        healthy = False
    body = {"status": "ok" if healthy else "degraded", "checks": checks}
    if not settings.is_production:
        body["environment"] = settings.environment
    return JSONResponse(status_code=200 if healthy else 503, content=body)
