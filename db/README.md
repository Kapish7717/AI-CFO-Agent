# Database migrations (dbmate)

Schema changes live here as versioned SQL files, applied with
[dbmate](https://dbmate.org) — a standalone binary with no Python/Node
dependency in this repo.

```
db/
├── migrations/
│   ├── 20261016171701_baseline_schema.sql   # version 1 (no-op; see below)
│   └── 2026…_add_<thing>.sql                # future changes
├── seed.sql                                 # test data — NOT a migration
└── README.md                                # this file
```

## Setup

dbmate is installed once per machine:

```bash
winget install amacneil.dbmate     # Windows
brew install dbmate                # macOS
```

It loads `.env` automatically, so run every command from the repo root.

### Two database URLs on purpose

`.env` defines two variables pointing at the same database:

| Variable | Port | Used by | Why |
| --- | --- | --- | --- |
| `DATABASE_URL` | 6543 | the app (psycopg2 pool) | Supabase *transaction* pooler — best for many short-lived queries |
| `DATABASE_URL_MIGRATIONS` | 5432 | dbmate | Supabase *session* pooler — prepared statements survive between commands |

Port 6543 (pgbouncer, transaction mode) recycles the server connection between
statements, so dbmate intermittently fails with
`pq: unnamed prepared statement does not exist`. Session mode on 5432 (same
host, same credentials) does not have that problem. **Always pass the
migrations URL to dbmate:**

```bash
dbmate -e DATABASE_URL_MIGRATIONS up     # -e = "read the URL from this env var"
```

## Everyday commands

```bash
dbmate new add_budget_index                       # create the migration file (no DB needed)
dbmate -e DATABASE_URL_MIGRATIONS up              # apply every pending migration
dbmate -e DATABASE_URL_MIGRATIONS status          # [X] applied / [ ] pending, per file
dbmate -e DATABASE_URL_MIGRATIONS down            # roll back the latest (needs -- migrate:down)
```

Every migration file must contain both markers dbmate looks for:

```sql
-- migrate:up
ALTER TABLE user_settings ADD COLUMN budget_other NUMERIC DEFAULT 0;

-- migrate:down
ALTER TABLE user_settings DROP COLUMN IF EXISTS budget_other;
```

Migrations run in a transaction, are recorded in the `schema_migrations`
table, and are applied **once** — never edit a file that has shipped; add a new
one instead.

## How this fits with `init_db()`

Two layers, deliberately:

1. **`app/db/database.py:init_db()`** — the *baseline bootstrap*. Idempotent
   (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`), runs at every
   app start, and must keep working on an empty as well as an existing
   database. It owns the initial schema; `20261016171701_baseline_schema.sql`
   is therefore an empty anchor recording that baseline as version 1.
2. **`db/migrations/`** — every *change* to that schema afterwards. Written
   once against the state `init_db()` leaves behind, so they do **not** need to
   be idempotent and should not use `IF NOT EXISTS` as a crutch.

Migrations are **not** applied at app startup — run
`dbmate -e DATABASE_URL_MIGRATIONS up` as a deploy step (CI, release script, or
before starting the server). This keeps the dbmate binary out of the runtime
image.

## Seeding test data (`db/seed.sql`)

Test data is **not** a migration. Migrations run once, are recorded in
`schema_migrations`, and ship to production with every `dbmate up` — the exact
opposite of what seed data should do. So seeding lives in `db/seed.sql` and is
run by hand:

```bash
python scripts/seed.py     # runner (psql is not installed here; dbmate only runs migrations/)
```

The runner reads `DATABASE_URL_MIGRATIONS` from `.env`, refuses hosts that look
like production (override with `--force`), and executes the file over the app's
own psycopg2 connection. `psql "$DATABASE_URL_MIGRATIONS" -f db/seed.sql`
works too, wherever psql is available.

What it creates:

| | |
| --- | --- |
| `test@example.com` | role `user`, password `password123` |
| `admin@example.com` | role `admin`, password `password123` |
| `user_settings` | budgets 5000 / 8000 / 2000 for both |
| `unified_transactions` | 10 rows, Jul–Oct 2026, `source = 'seed'` — includes two budget breaches (Marketing 6200 > 5000, Travel 2400 > 2000) so breach and month-over-month paths are exercisable |

- **Prerequisite:** the schema must exist — start the app once (`init_db()` is
  the baseline bootstrap) before seeding.
- **Re-runnable:** the file deletes everything it owns first (the two seed
  emails and `external_id LIKE 'seed-%'`), then inserts fresh rows. Nothing
  outside this file is touched.
- **Identified by `source = 'seed'`**, so stripe/excel integration queries —
  which filter on their own source — never see these rows.
- The legacy `transactions` table is intentionally *not* seeded; reports and
  the dashboard read through `unified_transactions` (`get_user_transactions()`).
- **Never run `db/seed.sql` against production.**

## Notes

- **Never run dbmate against `DATABASE_URL` directly** (port 6543): the
  transaction pooler breaks prepared statements, so dbmate fails with
  `pq: unnamed prepared statement does not exist`. Use
  `-e DATABASE_URL_MIGRATIONS` (port 5432, session mode) as shown above. Both
  variables hold the same credentials and reach the same database.
- Keep names lowercase `snake_case` after the timestamp; put data backfills
  (`UPDATE`/`INSERT`) in the same file as the DDL they belong with.
- Tests: nothing here is imported by the app, so no test wiring is needed.
