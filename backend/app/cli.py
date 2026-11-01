"""Comandos de administración.

Uso:
    python -m app.cli create-admin <email> <password> [--name "Nombre"]
    python -m app.cli move-private-docs [--dry-run]
    python -m app.cli sync-legal-docs [--file versiones.json] [--no-notify]   # registro de versiones (K-DOCS)
    python -m app.cli verify-acceptances                                       # cadena de la bitácora (K-ACEPT)
    python -m app.cli encrypt-private-files [--rotate] [--dry-run]             # cifrado en reposo (L-seguridad)
    python -m app.cli generate-private-key                                     # llave para PRIVATE_FILES_KEY
    python -m app.cli reset-mfa <email>                                        # admin que perdió su teléfono
    python -m app.cli retention-purge [--dry-run] [--force]                    # tabla de conservación ahora
"""
import argparse
import datetime
import sys

from app.auth import PASSWORD_TOO_LONG, get_password_hash, password_too_long
from app.database import SessionLocal, engine
from app.models import User


def schema_ready() -> bool:
    """El esquema lo crea Alembic (deploy.sh / python -m app.migrate); aquí solo se avisa si falta."""
    from sqlalchemy import inspect

    if inspect(engine).has_table("users"):
        return True
    print("La base de datos no tiene tablas. Ejecuta primero: python -m app.migrate", file=sys.stderr)
    return False


def create_admin(email: str, password: str, name: str | None) -> int:
    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres.", file=sys.stderr)
        return 1
    if password_too_long(password):
        print(PASSWORD_TOO_LONG, file=sys.stderr)
        return 1
    if not schema_ready():
        return 1
    db = SessionLocal()
    try:
        email = email.strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.role = "superadmin"
            user.hashed_password = get_password_hash(password)
            user.is_active = True
            # Nueva contraseña y nuevo rol: se cierran las sesiones anteriores
            user.token_version = (user.token_version or 0) + 1
            if not user.email_verified:
                user.email_verified = True
                user.email_verified_at = datetime.datetime.utcnow()
            if name:
                user.full_name = name
            action = "promovido a superadmin"
        else:
            user = User(email=email, full_name=name or "Administrador", hashed_password=get_password_hash(password),
                        role="superadmin", is_active=True, email_verified=True,
                        email_verified_at=datetime.datetime.utcnow())
            db.add(user)
            action = "creado como superadmin"
        db.commit()
        print(f"Usuario {email} {action} (id={user.id}).")
        return 0
    finally:
        db.close()


def move_private_docs(dry_run: bool = False) -> int:
    """Mueve los documentos de refugios de /uploads/ (público) a uploads/private/ y guarda sus ids.

    Idempotente. Si el archivo también lo usa una foto (perro, reporte, producto o perfil) se copia en vez de moverse.
    """
    from pathlib import Path

    from app.config import settings
    from app.models import Refuge
    from app.routers.documents import is_document_id, legacy_name, private_dir
    from app.services import crypto_storage
    from app.services.account_deletion import referenced_uploads, upload_name

    if not schema_ready():
        return 1
    db = SessionLocal()
    moved = copied = changed = missing = 0
    try:
        base = Path(settings.upload_dir)
        private = private_dir()
        for refuge in db.query(Refuge).order_by(Refuge.id).all():
            docs = list(refuge.documents or [])
            new_docs = []
            for doc in docs:
                if isinstance(doc, str) and is_document_id(doc):
                    new_docs.append(doc)
                    continue
                # Rutas antiguas: "/uploads/x.jpg" o la URL completa del dominio propio
                name = (legacy_name(doc) or upload_name(doc)) if isinstance(doc, str) else None
                if not name:
                    print(f"Refugio {refuge.id}: documento no reconocido, se deja igual: {doc!r}")
                    new_docs.append(doc)
                    continue
                src, dst = base / name, private / name
                if src.is_file():
                    shared = bool(referenced_uploads(db, {name}, include_documents=False))
                    if not dry_run:
                        # La copia privada se guarda cifrada (AES-GCM, crypto_storage); nunca en claro
                        if not dst.exists():
                            crypto_storage.write_private(dst, src.read_bytes())
                        if not shared:
                            src.unlink()
                        thumb = base / f"{name.rsplit('.', 1)[0]}_thumb.jpg"
                        if not shared and thumb.is_file():
                            thumb.unlink()
                    copied += shared
                    moved += not shared
                elif not dst.is_file():
                    print(f"Refugio {refuge.id}: no existe el archivo {name}; se deja la ruta original.")
                    missing += 1
                    new_docs.append(doc)
                    continue
                new_docs.append(name)
            if new_docs != docs:
                changed += 1
                if not dry_run:
                    refuge.documents = new_docs
        if not dry_run:
            db.commit()
        prefix = "[simulación] " if dry_run else ""
        print(f"{prefix}Documentos movidos: {moved}, copiados (también son fotos): {copied}, "
              f"faltantes: {missing}. Refugios actualizados: {changed}.")
        return 0
    finally:
        db.close()


def sync_legal_docs(path: str | None, notify: bool = True) -> int:
    """Copia app/legal/versiones.json (lo genera scripts/render-legal.py) a la tabla legal_documents.

    Idempotente. Si una versión nueva que pide aceptación tiene menos de LEGAL_NOTICE_DAYS de aviso, lo advierte;
    con notify, encola el aviso previo (correo + app) de las versiones nuevas con fecha de entrada en vigor.
    """
    from pathlib import Path

    from app.config import settings
    from app.services import legal_acceptance as la

    if not schema_ready():
        return 1
    file = Path(path) if path else la.versions_file()
    if file is None or not file.is_file():
        print("No se encontró versiones.json. Corre python3 scripts/render-legal.py o indica --file.", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        if settings.is_production:
            # En producción una versión nueva que pide aceptación sin los 30 días de aviso previo no se publica
            # (terminos.html 29.2; historial.html §2): se revisa antes de escribir y deploy.sh se detiene
            preview = la.sync_from_file(db, file, notify=False, dry_run=True)
            if preview["warnings"]:
                for warning in preview["warnings"]:
                    print(f"ERROR: {warning}", file=sys.stderr)
                print("No se sincronizó nada. Corrige FECHA_DE_ENTRADA_EN_VIGOR en app/legal/datos-legales.json y "
                      "vuelve a generar con python3 scripts/render-legal.py.", file=sys.stderr)
                return 1
        result = la.sync_from_file(db, file, notify=notify)
    finally:
        db.close()
    print(f"Registro legal ({result['file']}): {len(result['created'])} nuevas, {len(result['updated'])} "
          f"actualizadas, {result['unchanged']} sin cambios; avisos previos encolados: {len(result['notice_ids']) if notify else 0}.")
    for warning in result["warnings"]:
        print(f"AVISO: {warning}", file=sys.stderr)
    return 0


def verify_acceptances() -> int:
    from app.services import legal_acceptance as la

    if not schema_ready():
        return 1
    db = SessionLocal()
    try:
        result = la.verify_chain(db)
        trigger = la.append_only_active(db)
    finally:
        db.close()
    print(f"Bitácora de aceptaciones: {result['rows']} filas, cadena {'íntegra' if result['ok'] else 'ROTA'}"
          + (f" (primera fila inválida: {result['first_invalid_id']})" if not result["ok"] else "")
          + f"; trigger de solo inserción: {'activo' if trigger else 'NO instalado'}.")
    return 0 if result["ok"] else 2


def security_command(args) -> int:
    """Comandos de seguridad: encrypt-private-files, generate-private-key, reset-mfa y retention-purge."""
    from app.services import crypto_storage

    if args.command == "generate-private-key":
        print(crypto_storage.generate_key())
        return 0
    if not schema_ready():
        return 1
    db = SessionLocal()
    try:
        if args.command == "encrypt-private-files":
            try:
                # Primero los documentos antiguos de refugios que seguían en la carpeta pública de /uploads/
                legacy = crypto_storage.migrate_legacy_documents(db, dry_run=args.dry_run)
                files = crypto_storage.encrypt_private_files(rotate=args.rotate, dry_run=args.dry_run)
                columns = crypto_storage.encrypt_existing_columns(db, rotate=args.rotate, dry_run=args.dry_run)
            except crypto_storage.CryptoConfigError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            prefix = "[simulación] " if args.dry_run else ""
            print(f"{prefix}Documentos antiguos de refugios: {legacy['migrated']} pasados a la carpeta privada "
                  f"(cifrados) en {legacy['refuges']} refugios, {legacy['missing']} referencias a archivos que ya no existen, "
                  f"{legacy['public_deleted']} copias públicas borradas, {legacy['public_kept']} conservadas porque "
                  f"también son fotos públicas, {legacy['errors']} con error.")
            print(f"{prefix}Archivos privados: {files['encrypted']} cifrados, {files['rotated']} con llave nueva, "
                  f"{files['skipped']} ya estaban cifrados, {files['errors']} con error.")
            print(f"{prefix}Datos cifrados en la base: " + ", ".join(f"{k}={v}" for k, v in columns.items()))
            return 1 if (files["errors"] or legacy["errors"]) else 0
        if args.command == "reset-mfa":
            from app.models import MfaRecoveryCode

            user = db.query(User).filter(User.email == args.email.strip().lower()).first()
            if not user:
                print("No existe esa cuenta.", file=sys.stderr)
                return 1
            user.mfa_secret_enc = None
            user.mfa_pending_secret_enc = None
            user.mfa_enabled_at = None
            user.mfa_last_step = None
            user.token_version = (user.token_version or 0) + 1
            db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete(synchronize_session=False)
            from app.services.audit import record_admin_action

            record_admin_action(db, None, "auth.mfa_reset", "user", user.id, {"email": user.email, "via": "cli"})
            db.commit()
            print(f"Verificación en dos pasos de {user.email} restablecida; la configurará al volver a entrar.")
            return 0
        if args.command == "retention-purge":
            from app.services import retention

            result = retention.run_purge(db, dry_run=args.dry_run, force=args.force)
            print(f"Estado: {result['status']}")
            for clave, stats in result["results"].items():
                print(f"  {clave}: {stats}")
            return 0 if result["status"] in ("ok", "frozen", "disabled") else 1
    finally:
        db.close()
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Herramientas de GuauWoow")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Crea un superadmin o promueve un usuario existente")
    p.add_argument("email")
    p.add_argument("password")
    p.add_argument("--name", default=None)
    p = sub.add_parser("move-private-docs", help="Mueve los documentos de refugios a la carpeta privada")
    p.add_argument("--dry-run", action="store_true", help="Solo muestra lo que haría")
    p = sub.add_parser("sync-legal-docs", help="Sincroniza el registro de versiones de los documentos legales")
    p.add_argument("--file", default=None, help="Ruta de versiones.json (por defecto LEGAL_VERSIONS_FILE o la copia)")
    p.add_argument("--no-notify", action="store_true", help="No encola el aviso previo de las versiones nuevas")
    sub.add_parser("verify-acceptances", help="Recalcula la cadena de huellas de la bitácora de aceptaciones")
    # --- Seguridad (L-seguridad): cifrado en reposo, MFA y conservación ---
    p = sub.add_parser("encrypt-private-files", help="Cifra uploads/private/* y los datos fiscales que siguen en claro")
    p.add_argument("--rotate", action="store_true", help="También re-cifra lo cifrado con PRIVATE_FILES_OLD_KEYS")
    p.add_argument("--dry-run", action="store_true", help="Solo cuenta lo que haría")
    sub.add_parser("generate-private-key", help="Imprime una llave nueva para PRIVATE_FILES_KEY")
    p = sub.add_parser("reset-mfa", help="Quita la verificación en dos pasos de un admin (teléfono perdido)")
    p.add_argument("email")
    p = sub.add_parser("retention-purge", help="Aplica ahora la tabla de conservación (services/retention.py)")
    p.add_argument("--dry-run", action="store_true", help="Solo cuenta lo que borraría")
    p.add_argument("--force", action="store_true", help="Corre aunque un incidente abierto congele las purgas")
    args = parser.parse_args(argv)
    if args.command in ("encrypt-private-files", "generate-private-key", "reset-mfa", "retention-purge"):
        return security_command(args)
    if args.command == "create-admin":
        return create_admin(args.email, args.password, args.name)
    if args.command == "move-private-docs":
        return move_private_docs(args.dry_run)
    if args.command == "sync-legal-docs":
        return sync_legal_docs(args.file, notify=not args.no_notify)
    if args.command == "verify-acceptances":
        return verify_acceptances()
    return 1


if __name__ == "__main__":
    sys.exit(main())
