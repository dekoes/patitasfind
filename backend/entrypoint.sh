#!/bin/bash
set -e

# Si el comando es celery, no esperamos ni migramos, solo ejecutamos
if [[ "$1" == celery* ]]; then
  exec "$@"
fi

# Esperar a que PostgreSQL esté disponible
if [ -n "$DATABASE_URL" ]; then
  echo "Esperando PostgreSQL..."
  DB_HOST=$(echo "$DATABASE_URL" | sed -n 's/.*@\([^:/]*\).*/\1/p')
  DB_PORT=$(echo "$DATABASE_URL" | sed -n 's/.*@[^:]*:\([0-9]*\).*/\1/p')
  DB_PORT=${DB_PORT:-5432}

  until pg_isready -h "$DB_HOST" -p "$DB_PORT" -q; do
    echo "PostgreSQL no está listo aún..."
    sleep 1
  done
  echo "PostgreSQL listo."
fi

# Ejecutar migraciones de Alembic automáticamente en producción
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Ejecutando migraciones..."
  alembic upgrade head
fi

# Ejecutar comando recibido (por defecto uvicorn)
exec "$@"
