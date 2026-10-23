-- db/seed.sql — TEST DATA ONLY. Never run this against production.
--
-- Seeding is deliberately *not* a dbmate migration: migrations are schema and
-- run once, tracked in `schema_migrations`. Test data changes far more often,
-- must be re-runnable, and must never ship to prod — so it lives here and is
-- run by hand against a dev/test database:
--
--     psql "$DATABASE_URL_MIGRATIONS" -f db/seed.sql
--
-- Prerequisite: the schema must exist. Start the app once (init_db() is the
-- baseline bootstrap) or run init_db() manually before seeding.
--
-- The file is idempotent: it first deletes every row it owns, then inserts
-- fresh copies. Rows are owned by the two seed emails and the `seed-` prefix
-- on external_id, so nothing outside this file is touched.

BEGIN;

-- --------------------------------------------------------------------------- #
-- 1. Clean up any previous run
-- --------------------------------------------------------------------------- #
DELETE FROM unified_transactions WHERE external_id LIKE 'seed-%';
DELETE FROM user_settings
WHERE user_id IN (SELECT id FROM users WHERE email IN ('test@example.com', 'admin@example.com'));
DELETE FROM users
WHERE email IN ('test@example.com', 'admin@example.com');

-- --------------------------------------------------------------------------- #
-- 2. Users
--    password for BOTH accounts: password123
--    (PBKDF2-HMAC-SHA256, 600k iterations — same format as app.core.security)
-- --------------------------------------------------------------------------- #
INSERT INTO users (email, password_hash, full_name, role, avatar_url) VALUES
    ('test@example.com',
     'pbkdf2_sha256$600000$4bb0a2c0b93b8de0a7bddb040a26c28b$zrYFf_M1y15Tf8Uub42D7e6OvWJcM6t4_m4S2tZ6wgk=',
     'Test User', 'user', '/arjun_profile.png'),
    ('admin@example.com',
     'pbkdf2_sha256$600000$4bb0a2c0b93b8de0a7bddb040a26c28b$zrYFf_M1y15Tf8Uub42D7e6OvWJcM6t4_m4S2tZ6wgk=',
     'Test Admin', 'admin', '/arjun_profile.png');

-- --------------------------------------------------------------------------- #
-- 3. Settings (defaults mirror init_db()/create_user())
-- --------------------------------------------------------------------------- #
INSERT INTO user_settings (user_id, budget_marketing, budget_operations, budget_travel, selected_month)
SELECT id, 5000, 8000, 2000, '2026-10'
FROM users WHERE email = 'test@example.com';

INSERT INTO user_settings (user_id, budget_marketing, budget_operations, budget_travel, selected_month)
SELECT id, 5000, 8000, 2000, '2026-10'
FROM users WHERE email = 'admin@example.com';

-- --------------------------------------------------------------------------- #
-- 4. Transactions — 3 months (Jul–Oct 2026) so month-over-month analytics,
--    budget breaches and the RAG/report paths all have something to read.
--    source = 'seed' marks them as test rows and keeps them out of the
--    stripe/excel integration queries (which filter on their own source).
--    Two rows deliberately exceed their budget so breach handling is testable:
--      2026-09-18 Marketing 6200  > budget_marketing 5000
--      2026-10-06 Travel    2400  > budget_travel    2000
-- --------------------------------------------------------------------------- #
INSERT INTO unified_transactions
    (user_id, external_id, source, transaction_type, direction, amount, currency,
     transaction_date, description, category, counterparty, status, payment_method)
SELECT u.id, v.external_id, 'seed', v.transaction_type, v.direction, v.amount, 'USD',
       v.transaction_date::timestamp, v.description, v.category, v.counterparty,
       'completed', v.payment_method
FROM users u
CROSS JOIN (VALUES
    ('seed-tx-001', 'revenue', 'inflow',  12000.00, '2026-07-05', 'Consulting retainer — July',   'Revenue',    'Acme Corp',       'ach'),
    ('seed-tx-002', 'expense', 'outflow',  3200.00, '2026-07-12', 'Paid social campaign',        'Marketing',  'Meta Ads',        'card'),
    ('seed-tx-003', 'expense', 'outflow',  5400.00, '2026-07-20', 'Engineering contractor',      'Payroll',    'Ravi Kumar',      'ach'),
    ('seed-tx-004', 'revenue', 'inflow',  14500.00, '2026-08-04', 'Consulting retainer — August','Revenue',    'Acme Corp',       'ach'),
    ('seed-tx-005', 'expense', 'outflow',  4100.00, '2026-08-15', 'Client onsite travel',        'Travel',     'Delta Airlines',  'card'),
    ('seed-tx-006', 'expense', 'outflow',  2900.00, '2026-08-28', 'SaaS subscriptions',          'Software',   'Stack of tools',  'card'),
    ('seed-tx-007', 'revenue', 'inflow',  11800.00, '2026-09-03', 'Consulting retainer — Sept',  'Revenue',    'Acme Corp',       'ach'),
    ('seed-tx-008', 'expense', 'outflow',  6200.00, '2026-09-18', 'Search ads — over budget',    'Marketing',  'Google Ads',      'card'),
    ('seed-tx-009', 'expense', 'outflow',  2400.00, '2026-10-06', 'Conference travel — over budget', 'Travel', 'United Airlines', 'card'),
    ('seed-tx-010', 'expense', 'outflow',  7100.00, '2026-10-15', 'Office rent — October',       'Operations', 'WeWork',          'ach')
) AS v (external_id, transaction_type, direction, amount, transaction_date,
        description, category, counterparty, payment_method)
WHERE u.email = 'test@example.com'
ON CONFLICT (external_id, source, user_id) DO NOTHING;

COMMIT;
