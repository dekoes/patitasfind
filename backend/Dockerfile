# Imagen del backend de GuauWoow (API FastAPI, Celery worker y beat usan la misma imagen).
#   Producción:  docker build -t patitasfind-backend:<sha> --build-arg GIT_SHA=<sha> backend
#   Desarrollo:  docker build --build-arg INSTALL_DEV=true ...   (agrega pytest/httpx; lo hace docker-compose.yml)
# Debian trixie (stable con soporte de seguridad completo); se fija la versión exacta de Python.
ARG PYTHON_IMAGE=python:3.11.16-slim-trixie

# ---------------- Etapa 1: compila las dependencias como wheels (gcc y libpq-dev no llegan a la imagen final)
FROM ${PYTHON_IMAGE} AS builder
ARG INSTALL_DEV=false
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt requirements-dev.txt ./
RUN if [ "$INSTALL_DEV" = "true" ]; then req=requirements-dev.txt; else req=requirements.txt; fi \
    && pip wheel --wheel-dir /wheels -r "$req"

# ---------------- Etapa 2: imagen de ejecución (sin compiladores, usuario sin privilegios)
FROM ${PYTHON_IMAGE}
ARG INSTALL_DEV=false
ARG GIT_SHA=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GIT_SHA=${GIT_SHA}
LABEL org.opencontainers.image.title="patitasfind-backend" \
      org.opencontainers.image.revision="${GIT_SHA}"

# libpq5 para psycopg2 y postgresql-client para pg_isready (entrypoint.sh)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Usuario "app" (uid/gid 1000): el host debe dar escritura en backend/uploads a ese uid
# (scripts/deploy.sh hace chown 1000:1000 backend/uploads).
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /wheels /tmp/wheels
COPY requirements.txt requirements-dev.txt /tmp/req/
RUN if [ "$INSTALL_DEV" = "true" ]; then req=requirements-dev.txt; else req=requirements.txt; fi \
    && pip install --no-index --find-links /tmp/wheels -r "/tmp/req/$req" \
    && rm -rf /tmp/wheels /tmp/req

WORKDIR /app
# El código queda de root (solo lectura para "app"); solo uploads y el horario de beat son escribibles
COPY . .
RUN mkdir -p /app/uploads /var/lib/celery \
    && chown app:app /app/uploads /var/lib/celery

# Script de arranque: espera DB, ejecuta migraciones y luego el servidor
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

USER app
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
