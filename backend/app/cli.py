"""Command-line administration.

    python -m app.cli create-admin
    python -m app.cli create-invite --label "Alex"
    python -m app.cli sync-sec
    python -m app.cli backup
"""

import argparse
import getpass
import sys
from datetime import timedelta

from sqlalchemy import select

from .db import init_db, session_factory, utcnow
from .models import Invite, User, UserPreference, Watchlist
from .routers.auth import USERNAME_RE
from .security import MIN_PASSWORD_LENGTH, hash_password, new_invite_code, sha256
from .services import backup, sec


def create_admin(args) -> int:
    init_db()
    db = session_factory()()
    username = (args.username or input("Admin username: ")).strip().lower()
    if not USERNAME_RE.match(username):
        print("Invalid username (3–40 chars: letters, digits, '.', '_', '-').")
        return 1
    if db.scalar(select(User).where(User.username == username)):
        print("That username already exists.")
        return 1
    display = (args.display_name or input("Display name: ")).strip() or username
    pw = getpass.getpass(f"Password (min {MIN_PASSWORD_LENGTH} chars): ")
    if len(pw) < MIN_PASSWORD_LENGTH or pw != getpass.getpass("Repeat password: "):
        print("Passwords too short or do not match.")
        return 1
    user = User(username=username, display_name=display, password_hash=hash_password(pw), role="admin")
    db.add(user)
    db.flush()
    db.add(UserPreference(user_id=user.id))
    db.add(Watchlist(user_id=user.id, name="My watchlist"))
    db.commit()
    print(f"Administrator '{username}' created.")
    return 0


def create_invite(args) -> int:
    init_db()
    db = session_factory()()
    admin = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
    code = new_invite_code()
    db.add(
        Invite(
            code_hash=sha256(code),
            code_hint=code[:4],
            label=args.label,
            role="member",
            created_by_id=admin.id if admin else None,
            expires_at=utcnow() + timedelta(days=args.days),
        )
    )
    db.commit()
    print(f"Invite code (valid {args.days} days, single use): {code}")
    return 0


def sync_sec(args) -> int:
    init_db()
    db = session_factory()()
    try:
        row = sec.sync_securities(db, force=args.force)
    except sec.SyncError as exc:
        print(f"Sync failed: {exc}")
        return 1
    print(f"Loaded {row.record_count:,} securities from {sec.SOURCE_URL}")
    return 0


def do_backup(args) -> int:
    init_db()
    print(f"Backup written to {backup.create_backup(keep=args.keep)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin")
    p.add_argument("--username")
    p.add_argument("--display-name")
    p.set_defaults(func=create_admin)
    p = sub.add_parser("create-invite")
    p.add_argument("--label", default="")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(func=create_invite)
    p = sub.add_parser("sync-sec")
    p.add_argument("--force", action="store_true", help="ignore the minimum interval between syncs")
    p.set_defaults(func=sync_sec)
    p = sub.add_parser("backup")
    p.add_argument("--keep", type=int, default=14)
    p.set_defaults(func=do_backup)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
