-- 0001 baseline — the starting point of versioned migrations.
--
-- This migration defines no schema: the initial schema (users, user_settings,
-- unified_transactions, qbo_*, stripe_* and friends) is created by the
-- idempotent bootstrap in app/db/database.py:init_db(), which runs on every
-- application start and works against both empty and existing databases.
-- Re-creating that DDL here would duplicate it and let the two copies drift.
--
-- So version 1 of this database is defined as "whatever init_db() produces",
-- and every schema change after it gets its own file:
--
--     dbmate new <snake_case_name>
--
-- See db/README.md for the workflow. This file exists only so dbmate's
-- schema_migrations table has a first row to chain from.

-- migrate:up

-- No statements: the baseline lives in init_db() (see comment above).

-- migrate:down

-- Nothing to undo: init_db() owns the baseline schema and is idempotent.
