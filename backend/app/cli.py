"""Comandos de administración.

Uso:
    python -m app.cli create-admin <email> <password> [--name "Nombre"]
"""
import argparse
import sys

from app.auth import get_password_hash
from app.database import SessionLocal
from app.main import run_startup_migrations
from app.models import User


def create_admin(email: str, password: str, name: str | None) -> int:
    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres.", file=sys.stderr)
        return 1
    run_startup_migrations()
    db = SessionLocal()
    try:
        email = email.strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.role = "superadmin"
            user.hashed_password = get_password_hash(password)
            user.is_active = True
            if name:
                user.full_name = name
            action = "promovido a superadmin"
        else:
            user = User(email=email, full_name=name or "Administrador", hashed_password=get_password_hash(password),
                        role="superadmin", is_active=True)
            db.add(user)
            action = "creado como superadmin"
        db.commit()
        print(f"Usuario {email} {action} (id={user.id}).")
        return 0
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Herramientas de PatitasFind")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Crea un superadmin o promueve un usuario existente")
    p.add_argument("email")
    p.add_argument("password")
    p.add_argument("--name", default=None)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.password, args.name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
