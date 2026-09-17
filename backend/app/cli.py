"""Operational commands for the backend; run only from a trusted terminal."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import password_hasher
from .db import _session_factory
from .models import AuditLog, User, UserRole


def create_initial_admin(args: argparse.Namespace) -> int:
    """Create exactly one initial administrator after migrations have run."""
    password = getpass.getpass("Initial admin password: ")
    confirmation = getpass.getpass("Confirm initial admin password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("Initial admin password must contain at least 12 characters.", file=sys.stderr)
        return 2

    db = _session_factory()()
    try:
        existing_admin = db.scalar(select(User.id).where(User.role == UserRole.ADMIN).limit(1))
        if existing_admin is not None:
            print("An administrator already exists; refusing to create another.", file=sys.stderr)
            return 1
        user = User(
            username=args.username,
            email=args.email,
            display_name=args.display_name,
            password_hash=password_hasher.hash(password),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            AuditLog(
                user_id=user.id,
                action="auth.initial_admin_created",
                target_entity="user",
                target_id=user.id,
                details={"username": user.username},
                ip_address=None,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        print("Username or email already exists; no administrator was created.", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"Initial administrator '{args.username}' created.")
    return 0


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description="Asset Reconciliation backend operational commands")
    commands = command_parser.add_subparsers(dest="command", required=True)
    initial_admin = commands.add_parser("create-initial-admin", help="Create the first ADMIN user")
    initial_admin.add_argument("--username", required=True)
    initial_admin.add_argument("--email", required=True)
    initial_admin.add_argument("--display-name", required=True)
    initial_admin.set_defaults(handler=create_initial_admin)
    return command_parser


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
