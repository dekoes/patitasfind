#!/bin/bash
set -e

# Corre como el usuario sin privilegios "app" (uid 1000) en producción. Avisa claro si no puede
# escribir en la carpeta de fotos (bind mount ./backend/uploads del host).
check_upload_dir() {
  local dir="${UPLOAD_DIR:-uploads}"
  mkdir -p "$dir" 2>/dev/null || true
  if ! { touch "$dir/.write-test" && rm -f "$dir/.write-test"; } 2>/dev/null; then
    echo "ERROR: el usuario $(id -un 2>/dev/null || id -u) (uid $(id -u)) no puede escribir en $dir." >&2
    echo "       En el servidor ejecuta: sudo chown -R 1000:1000 backend/uploads  (scripts/deploy.sh lo hace)." >&2
    exit 1
  fi
}

# Si el comando es celery, no esperamos ni migramos, solo ejecutamos
# (sintaxis POSIX: el script también funciona con "sh /entrypoint.sh")
case "${1:-}" in
  celery*)
    check_upload_dir
    exec "$@"
    ;;
esac

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

case "${1:-}" in
  uvicorn*) check_upload_dir ;;
esac

# Migraciones de Alembic (producción). Si la base ya existía sin Alembic, se marca la
# baseline (stamp) en lugar de recrear tablas. Ver app/migrate.py.
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Ejecutando migraciones..."
  python -m app.migrate
fi

# Ejecutar comando recibido (por defecto uvicorn)
exec "$@"
