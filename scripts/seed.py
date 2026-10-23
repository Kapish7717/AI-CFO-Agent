"""Run db/seed.sql against the dev/test database.

Why this exists instead of psql:
    ``psql`` is not part of this repo's toolchain (dbmate is the only DB CLI
    installed), and dbmate only ever runs ``db/migrations/``. This runner
    executes the seed file over the app's own psycopg2 connection.

Run:
    python scripts/seed.py

Which database:
    ``DATABASE_URL_MIGRATIONS`` (port 5432, session pooler) is preferred —
    same rationale as dbmate, see db/README.md. Falls back to ``DATABASE_URL``.

    The script refuses to run when the URL looks like a production host and
    requires ``--force`` to override. Seeding is test data only.

The file is idempotent (it deletes rows it owns before inserting), so running
this repeatedly is safe. The schema must already exist — start the app once so
``init_db()`` has bootstrapped it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = REPO_ROOT / "db" / "seed.sql"

# Host substrings that must never receive seed rows. `onrender.com` is here
# because Render serves production from the same credentials pattern as dev —
# the URL shape alone is the only signal available.
PROD_MARKERS = ("production", "prod.", ".prod.", "live", "onrender.com")


def pick_url(force: bool) -> str:
    """Choose the connection URL, refusing obvious production hosts."""
    load_dotenv(REPO_ROOT / ".env")

    import os

    url = (os.environ.get("DATABASE_URL_MIGRATIONS") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        sys.exit("[seed] No DATABASE_URL_MIGRATIONS or DATABASE_URL found in .env")

    host = url.split("@")[-1].split("/")[0].lower()
    if any(marker in host for marker in PROD_MARKERS) and not force:
        sys.exit(
            f"[seed] Refusing to seed what looks like a production host ({host}).\n"
            "[seed] Test data only — pass --force if you are certain."
        )
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Load db/seed.sql into the dev/test database.")
    parser.add_argument("--force", action="store_true", help="skip the production-host guard")
    args = parser.parse_args()

    if not SEED_FILE.exists():
        sys.exit(f"[seed] Missing seed file: {SEED_FILE}")

    sql = SEED_FILE.read_text(encoding="utf-8")
    url = pick_url(args.force)

    conn = psycopg2.connect(url)
    # autocommit so the BEGIN/COMMIT already written inside seed.sql works as-is.
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print(f"[seed] Applied {SEED_FILE.name} successfully.")
        print("[seed] Logins: test@example.com / admin@example.com - password 'password123'")
        return 0
    except psycopg2.Error as exc:
        print(f"[seed] Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
