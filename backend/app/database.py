import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app import cache
from app.config import settings


def _is_celery_process() -> bool:
    """True si este proceso es un worker o beat de Celery (`celery -A app.celery_app ...`)."""
    argv0 = os.path.basename(sys.argv[0]) if sys.argv else ""
    return argv0 == "celery" or (argv0 == "__main__.py" and "celery" in sys.argv[0])


# Cada proceso tiene su propio pool. Cuenta con Postgres max_connections=150 (lo fija infra):
#   web:    4 workers de uvicorn x (DB_POOL_SIZE 5 + DB_MAX_OVERFLOW 5)          = 40
#   celery: 4 hijos del worker x (DB_WORKER_POOL_SIZE 2 + DB_WORKER_MAX_OVERFLOW 2) = 16 (+ beat, casi nada)
#   total ~56; queda margen para un segundo backend durante un despliegue (+40), respaldos,
#   psql/admin y las conexiones reservadas de superusuario (~110 en el peor caso).
# Las peticiones que no alcanzan conexión esperan DB_POOL_TIMEOUT segundos y luego fallan rápido
# en lugar de formar colas eternas.
IS_CELERY = _is_celery_process()
engine = create_engine(
    settings.database_url,
    pool_size=settings.db_worker_pool_size if IS_CELERY else settings.db_pool_size,
    max_overflow=settings.db_worker_max_overflow if IS_CELERY else settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Al cambiar perros o reportes se invalidan sus listados en caché (Redis), venga de donde venga el cambio
cache.watch_sessions(SessionLocal)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
