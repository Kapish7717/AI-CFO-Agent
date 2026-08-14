import logging
import os
import sys

from psycopg2.extras import RealDictCursor

from app.core.security import hash_password
from app.db.pool import get_connection as _pool_get_connection

logger = logging.getLogger("db.database")

# Database configuration loaded from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "cfo_agent")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

def sqlite_row_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def sqlite_to_char(val, fmt):
    if not val:
        return ""
    if len(val) >= 19:
        return val[11:19]
    return val


def strip_transaction_record(raw_record: dict) -> dict:
    """Normalizes incoming source payloads into the canonical transaction schema.

    This is the single contract that all data sources should pass through before they
    hit the user-facing transaction table. New sources only need to contribute a
    mapper, not a new storage shape.
    """
    if raw_record is None:
        return {
            'Date': None,
            'Category': 'Unknown',
            'Amount': 0.0,
            'Entity': 'Unknown',
            'Type': 'Expense',
            'Severity': 'Normal',
            'Is_Budget_Breach': False,
            'Is_Mom_Anomaly': False,
            'Anomaly_Reason': None,
        }

    row = dict(raw_record)
    date_val = (
        row.get('Date')
        or row.get('date')
        or row.get('TransactionDate')
        or row.get('Timestamp')
        or row.get('Dt')
        or row.get('created_at')
    )
    if date_val is None or date_val == '':
        normalized_date = None
    else:
        try:
            import pandas as pd
            normalized_date = pd.Timestamp(date_val)
        except Exception:
            try:
                import datetime as dt
                normalized_date = dt.datetime.fromisoformat(str(date_val).replace('Z', '+00:00'))
            except Exception:
                normalized_date = None

    amount_raw = (
        row.get('Amount')
        or row.get('amount')
        or row.get('Amt')
        or row.get('Value')
        or row.get('Total')
        or 0
    )
    try:
        amount_val = float(amount_raw)
    except Exception:
        amount_val = 0.0

    category_val = (
        row.get('Category')
        or row.get('category')
        or row.get('Cat')
        or row.get('Description')
        or row.get('Item')
        or 'Unknown'
    )
    entity_val = (
        row.get('Entity')
        or row.get('entity')
        or row.get('Vendor')
        or row.get('Merchant')
        or row.get('Payee')
        or row.get('Payer')
        or row.get('Source')
        or 'Unknown'
    )
    type_val = (
        row.get('Type')
        or row.get('type')
        or row.get('TransactionType')
        or ('Expense' if amount_val < 0 else 'Revenue')
        or 'Expense'
    )
    severity_val = row.get('Severity') or row.get('severity') or 'Normal'
    breach_val = row.get('Is_Budget_Breach', row.get('is_budget_breach', False))
    mom_val = row.get('Is_Mom_Anomaly', row.get('is_mom_anomaly', False))
    anomaly_reason = row.get('Anomaly_Reason') or row.get('anomaly_reason')

    return {
        'Date': normalized_date,
        'Category': category_val,
        'Amount': amount_val,
        'Entity': entity_val,
        'Type': type_val,
        'Severity': severity_val,
        'Is_Budget_Breach': bool(breach_val),
        'Is_Mom_Anomaly': bool(mom_val),
        'Anomaly_Reason': anomaly_reason,
    }


def strip_transaction_rows(rows: list[dict]) -> list[dict]:
    """Canonicalizes a batch of source rows so downstream DB code only sees one schema."""
    return [strip_transaction_record(row) for row in rows or []]

class SQLiteCursorWrapper:
    def __init__(self, cur):
        self.cur = cur
        self._lastrowid = None

    def execute(self, query, params=()):
        # Replace %s with ?
        query = query.replace('%s', '?')
        
        # Translate SERIAL PRIMARY KEY to INTEGER PRIMARY KEY AUTOINCREMENT
        if 'CREATE TABLE' in query.upper():
            query = query.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
            
        # Check for RETURNING
        if 'RETURNING' in query.upper():
            try:
                self.cur.execute(query, params)
                return self
            except Exception:
                parts = query.split('RETURNING')
                query_clean = parts[0].strip()
                self.cur.execute(query_clean, params)
                self._lastrowid = self.cur.lastrowid
                return self
        
        self.cur.execute(query, params)
        return self

    def fetchone(self):
        row = self.cur.fetchone()
        if not row and self._lastrowid is not None:
            val = {'id': self._lastrowid, 0: self._lastrowid}
            self._lastrowid = None
            return val
        return row

    def fetchall(self):
        return self.cur.fetchall()

    def close(self):
        self.cur.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getattr__(self, name):
        return getattr(self.cur, name)

class SQLiteConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return SQLiteCursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __getattr__(self, name):
        return getattr(self.conn, name)

def get_connection(cursor_factory=RealDictCursor):
    """Returns a pooled PostgreSQL connection producing dict rows."""
    try:
        return _pool_get_connection(cursor_factory=cursor_factory)
    except Exception as e:
        logger.error(f"Failed to acquire database connection: {e}", exc_info=True)
        raise


def close_all_pooled_connections():
    """Close every pooled DB connection (called during application shutdown)."""
    from app.db.pool import close_pool as _close_pool

    _close_pool()

def init_db():
    """Initializes Supabase-backed database tables and seeds a default user."""
    conn = None
    try:
        logger.info("[DB] Initializing Supabase database tables...")
        sys.stderr.write("[DB] Initializing Supabase database...\n")

        conn = get_connection()
        conn.autocommit = False
        cur = conn.cursor()

        # 1. Create Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) DEFAULT 'User',
                role VARCHAR(100) DEFAULT 'Finance Head',
                avatar_url VARCHAR(255) DEFAULT '/arjun_profile.png',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Create User Settings table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                expense_file_path VARCHAR(500) NULL,
                expense_file_name VARCHAR(255) NULL,
                expense_url VARCHAR(1000) NULL,
                revenue_file_path VARCHAR(500) NULL,
                revenue_file_name VARCHAR(255) NULL,
                revenue_url VARCHAR(1000) NULL,
                budget_marketing NUMERIC DEFAULT 5000,
                budget_operations NUMERIC DEFAULT 8000,
                budget_travel NUMERIC DEFAULT 2000,
                selected_month VARCHAR(50) NULL,
                llm_primary_provider VARCHAR(50) NULL,
                llm_primary_model VARCHAR(255) NULL,
                llm_fallback_provider VARCHAR(50) NULL,
                llm_fallback_model VARCHAR(255) NULL,
                api_key VARCHAR(1000) NULL,
                fallback_api_key VARCHAR(1000) NULL,
                stripe_secret_key VARCHAR(255) NULL,
                report_email VARCHAR(255) NULL,
                report_schedule VARCHAR(50) NULL
            );
        """)

        # Migrate existing tables: add LLM config columns if they don't exist yet.
        for _col, _dtype in (
            ("llm_primary_provider", "VARCHAR(50)"),
            ("llm_primary_model", "VARCHAR(255)"),
            ("llm_fallback_provider", "VARCHAR(50)"),
            ("llm_fallback_model", "VARCHAR(255)"),
            ("api_key", "VARCHAR(1000)"),
            ("fallback_api_key", "VARCHAR(1000)"),
            ("stripe_secret_key", "VARCHAR(255)"),
            ("report_email", "VARCHAR(255)"),
            ("report_schedule", "VARCHAR(50)"),
        ):
            try:
                cur.execute(f"ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS {_col} {_dtype} NULL;")
            except Exception:
                pass

        # 3. Create User Google Auth table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_google_auth (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                google_token_json TEXT NULL
            );
        """)

        # 4. Create User Chat Messages table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_chat_messages (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                sender VARCHAR(50) NOT NULL,
                message_text TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 5. Create Transactions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                date TIMESTAMP NOT NULL,
                category VARCHAR(100),
                amount NUMERIC(15, 2) NOT NULL,
                entity VARCHAR(255),
                type VARCHAR(50) NOT NULL,
                severity VARCHAR(50) DEFAULT 'Normal',
                is_budget_breach BOOLEAN DEFAULT FALSE,
                is_mom_anomaly BOOLEAN DEFAULT FALSE,
                anomaly_reason TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, date);")
        except Exception:
            pass

        # 6. Create Unified Transactions table (all external + excel sources,
        # normalized into one canonical row shape for every source).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS unified_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                external_id VARCHAR(255) NOT NULL,
                source VARCHAR(50) NOT NULL,
                transaction_type VARCHAR(50),
                direction VARCHAR(20),
                amount NUMERIC(15, 2) NOT NULL,
                currency VARCHAR(10) DEFAULT 'USD',
                transaction_date TIMESTAMP,
                description TEXT,
                category VARCHAR(100),
                counterparty VARCHAR(255),
                status VARCHAR(50),
                payment_method VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (external_id, source)
            );
        """)

        # Migrate the legacy unified_transactions layout (external_id, source,
        # amount, currency, date, status, counterparty, category) to the new schema.
        # Wrapped in a savepoint so a statement that fails (e.g. the legacy
        # `date` column already removed on a previous run) doesn't abort the
        # surrounding transaction.
        cur.execute("SAVEPOINT unified_migrate")
        try:
            for _col, _dtype in (
                ("user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE"),
                ("transaction_type", "VARCHAR(50)"),
                ("direction", "VARCHAR(20)"),
                ("transaction_date", "TIMESTAMP"),
                ("description", "TEXT"),
                ("payment_method", "VARCHAR(50)"),
                ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ):
                cur.execute(
                    f"ALTER TABLE unified_transactions ADD COLUMN IF NOT EXISTS {_col} {_dtype}"
                )

            # Only backfill from the legacy `date` column if it still exists.
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'unified_transactions' AND column_name = 'date'"
            )
            if cur.fetchone():
                cur.execute(
                    "UPDATE unified_transactions SET transaction_date = date "
                    "WHERE transaction_date IS NULL AND date IS NOT NULL"
                )
                cur.execute("ALTER TABLE unified_transactions DROP COLUMN IF EXISTS date")
        except Exception as _mig_err:
            cur.execute("ROLLBACK TO SAVEPOINT unified_migrate")
            sys.stderr.write(f"[DB] unified_transactions migration skipped: {_mig_err}\n")
        cur.execute("RELEASE SAVEPOINT unified_migrate")

        # 6b. Create dedicated Stripe Transactions table. Keeps the raw Stripe
        # payload for every charge/refund/transfer/payout in Supabase, separate
        # from the normalized unified_transactions view of the same data.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stripe_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                external_id VARCHAR(255) UNIQUE NOT NULL,
                object_type VARCHAR(50),
                amount NUMERIC(15, 2),
                currency VARCHAR(10) DEFAULT 'USD',
                transaction_date TIMESTAMP,
                description TEXT,
                counterparty VARCHAR(255),
                status VARCHAR(50),
                raw_payload JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_stripe_tx_user_date ON stripe_transactions(user_id, transaction_date);")
        except Exception:
            pass

        # 7. Create Sync Status table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sync_status (
                source VARCHAR(50) PRIMARY KEY,
                status VARCHAR(50) NOT NULL,
                last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                record_count INTEGER DEFAULT 0,
                error_message TEXT
            );
        """)

        conn.commit()

        # Optionally seed a default demo user. Disabled by default so a known
        # credential is never created in a production database.
        import os as _os
        seed_enabled = _os.environ.get("SEED_DEFAULT_USER", "").strip().lower() in {"1", "true", "yes"}
        if seed_enabled:
            default_email = "arjun@cfo.com"
            cur.execute("SELECT id FROM users WHERE email = %s", (default_email,))
            if not cur.fetchone():
                logger.warning("[DB] Seeding default demo user (SEED_DEFAULT_USER is enabled).")
                hashed_pw = hash_password("password123")
                cur.execute("""
                    INSERT INTO users (email, password_hash, full_name, role, avatar_url)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (default_email, hashed_pw, "Arjun Mehta", "Finance Head", "/arjun_profile.png"))
                user_id = cur.fetchone()['id']

                cur.execute("""
                    INSERT INTO user_settings (user_id, budget_marketing, budget_operations, budget_travel)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, 5000, 8000, 2000))
                conn.commit()

        cur.close()
        logger.info("[DB] Database initialization completed successfully.")
        sys.stderr.write("[DB] Database initialization completed successfully.\n")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"[DB ERROR] Database initialization failed: {e}", exc_info=True)
        sys.stderr.write(f"[DB ERROR] Initialization failed: {e}\n")
        raise e
    finally:
        if conn:
            conn.close()

# Password Hashing Helpers
# Forwarding to app.core.security (PBKDF2). Legacy SHA-256 hashes stay verifiable.
# ------------------------------------------------------------------------------
# `hash_password` and `verify_password` are imported from app.core.security above.

# User Management Helpers
def get_user_by_email(email: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email = %s", (email.strip().lower(),))
            return cur.fetchone()
    finally:
        conn.close()

def get_user_by_id(user_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cur.fetchone()
    finally:
        conn.close()

def get_all_user_ids() -> list[int]:
    """Return the ids of all user rows (used by the report scheduler)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users")
            return [r["id"] for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()

def create_user(email: str, password_raw: str, full_name: str, role: str = "Finance Head"):
    conn = get_connection()
    try:
        logger.info(f"Creating user in database: email={email.strip().lower()}, role={role}")
        hashed = hash_password(password_raw)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (email, password_hash, full_name, role)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (email.strip().lower(), hashed, full_name, role))
            user_id = cur.fetchone()['id']
            
            # Create default settings
            cur.execute("""
                INSERT INTO user_settings (user_id) VALUES (%s)
            """, (user_id,))
            conn.commit()
            logger.info(f"Successfully created user {email} (User ID: {user_id})")
            return user_id
    except Exception as e:
        logger.error(f"Error in create_user for email {email}: {e}", exc_info=True)
        conn.rollback()
        raise e
    finally:
        conn.close()

# User Settings Helpers
def get_user_settings(user_id: int):
    default_settings = {
        "user_id": user_id,
        "budget_marketing": 5000.0,
        "budget_operations": 8000.0,
        "budget_travel": 2000.0,
        "expense_file_path": None,
        "expense_file_name": None,
        "expense_url": None,
        "revenue_file_path": None,
        "revenue_file_name": None,
        "revenue_url": None,
        "selected_month": None,
        "llm_primary_provider": "mock",
        "llm_primary_model": None,
        "llm_fallback_provider": None,
        "llm_fallback_model": None,
        "api_key": None,
        "fallback_api_key": None,
        "stripe_secret_key": None,
        "report_email": None,
        "report_schedule": None
    }
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id = %s", (user_id,))
            settings = cur.fetchone()
            if not settings:
                try:
                    cur.execute("INSERT INTO user_settings (user_id) VALUES (%s)", (user_id,))
                    conn.commit()
                except Exception:
                    conn.rollback()
                cur.execute("SELECT * FROM user_settings WHERE user_id = %s", (user_id,))
                settings = cur.fetchone()
            
            if settings and isinstance(settings, dict):
                # Ensure defaults for key values
                for k, v in default_settings.items():
                    if k not in settings or settings[k] is None:
                        settings[k] = v
                return settings
            return default_settings
    except Exception as e:
        logger.error(f"Error fetching user_settings for user {user_id}: {e}")
        return default_settings
    finally:
        try:
            conn.close()
        except Exception:
            pass

def update_user_settings(user_id: int, updates: dict):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Dynamically build update query
            allowed_cols = {
                'expense_file_path', 'expense_file_name', 'expense_url',
                'revenue_file_path', 'revenue_file_name', 'revenue_url',
                'budget_marketing', 'budget_operations', 'budget_travel',
                'selected_month',
                'llm_primary_provider', 'llm_primary_model',
                'llm_fallback_provider', 'llm_fallback_model',
                'api_key', 'fallback_api_key',
                'stripe_secret_key',
                'report_email', 'report_schedule'
            }
            fields = []
            vals = []
            for k, v in updates.items():
                if k in allowed_cols:
                    fields.append(f"{k} = %s")
                    vals.append(v)
            
            if not fields:
                return
            
            vals.append(user_id)
            query = f"UPDATE user_settings SET {', '.join(fields)} WHERE user_id = %s"
            cur.execute(query, tuple(vals))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# Google Token Helpers
def get_user_google_token(user_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT google_token_json FROM user_google_auth WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row['google_token_json'] if row else None
    finally:
        conn.close()

def save_user_google_token(user_id: int, token_json_str: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_google_auth (user_id, google_token_json)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET google_token_json = EXCLUDED.google_token_json
            """, (user_id, token_json_str))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def delete_user_google_token(user_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_google_auth WHERE user_id = %s", (user_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# Chat Logs Helpers
def get_user_chat_history(user_id: int, limit: int = 50):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sender, message_text as text, TO_CHAR(timestamp, 'HH24:MI:SS') as timestamp 
                FROM user_chat_messages 
                WHERE user_id = %s 
                ORDER BY timestamp ASC 
                LIMIT %s
            """, (user_id, limit))
            return cur.fetchall()
    finally:
        conn.close()

def save_user_chat_message(user_id: int, sender: str, text: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_chat_messages (user_id, sender, message_text)
                VALUES (%s, %s, %s)
            """, (user_id, sender, text))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# Transactions Database Helpers
def delete_user_transactions(user_id: int):
    """Deletes all transactions for a user."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM transactions WHERE user_id = %s", (user_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def upsert_user_transactions(user_id: int, rows: list[dict]) -> dict:
    """Merge a batch of transactions into the user's stored data without deleting.

    Existing transactions are preserved and new rows are appended. Rows whose
    natural key (date/type/category/entity/amount) already exists are treated as
    duplicates and skipped, so re-uploading a file or appending a later period
    never clears or duplicates previously ingested data.

    Returns ``{'inserted': n, 'skipped': n, 'total': n}``.
    """
    normalized_rows = strip_transaction_rows(rows)
    total = len(normalized_rows)
    if total == 0:
        return {"inserted": 0, "skipped": 0, "total": 0}

    import datetime as _dt

    def date_key(value) -> str:
        if value is None:
            return ""
        try:
            if hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()
            if isinstance(value, _dt.datetime):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(value, _dt.date):
                return value.strftime("%Y-%m-%d")
            return str(value)
        except Exception:
            return str(value)

    def row_key(r: dict):
        try:
            amt = round(float(r.get("Amount", 0.0) or 0.0), 2)
        except Exception:
            amt = 0.0
        return (
            date_key(r.get("Date")),
            str(r.get("Type", "")).lower().strip(),
            str(r.get("Category", "")).lower().strip(),
            str(r.get("Entity", "")).lower().strip(),
            amt,
        )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Load existing natural keys once.
            cur.execute(
                "SELECT date, type, category, entity, amount FROM transactions WHERE user_id = %s",
                (user_id,),
            )
            existing = set()
            for r in cur.fetchall():
                existing.add(
                    (
                        date_key(r["date"]),
                        str(r["type"]).lower().strip(),
                        str(r["category"]).lower().strip(),
                        str(r["entity"]).lower().strip(),
                        round(float(r["amount"] or 0.0), 2),
                    )
                )

            values = []
            inserted = 0
            for row in normalized_rows:
                key = row_key(row)
                if key in existing:
                    continue
                existing.add(key)
                dt = row.get("Date")
                if hasattr(dt, "to_pydatetime"):
                    dt = dt.to_pydatetime()
                elif dt is not None and not isinstance(dt, _dt.datetime) and hasattr(dt, "isoformat"):
                    pass
                elif dt is not None:
                    dt = str(dt)
                values.append((
                    user_id,
                    dt,
                    row.get("Category", "Unknown"),
                    float(row.get("Amount", 0.0)),
                    row.get("Entity", "Unknown"),
                    row.get("Type", "Expense"),
                    row.get("Severity", "Normal"),
                    bool(row.get("Is_Budget_Breach", False)),
                    bool(row.get("Is_Mom_Anomaly", False)),
                    row.get("Anomaly_Reason"),
                ))

            if values:
                if DATABASE_URL:
                    from psycopg2.extras import execute_values
                    query = """
                        INSERT INTO transactions (
                            user_id, date, category, amount, entity, type,
                            severity, is_budget_breach, is_mom_anomaly, anomaly_reason
                        ) VALUES %s
                    """
                    execute_values(cur, query, values)
                else:
                    query = """
                        INSERT INTO transactions (
                            user_id, date, category, amount, entity, type,
                            severity, is_budget_breach, is_mom_anomaly, anomaly_reason
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    cur.cur.executemany(query, values)
                conn.commit()
                inserted = len(values)

        return {"inserted": inserted, "skipped": total - inserted, "total": total}
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def insert_user_transactions(user_id: int, rows: list[dict]):
    """Inserts a list of transactions for a user using bulk operations for PostgreSQL."""
    conn = get_connection()
    try:
        normalized_rows = strip_transaction_rows(rows)
        with conn.cursor() as cur:
            values = []
            for row in normalized_rows:
                dt = row.get('Date')
                if hasattr(dt, 'to_pydatetime'):
                    dt = dt.to_pydatetime()
                elif hasattr(dt, 'isoformat'):
                    pass
                else:
                    dt = str(dt)
                values.append((
                    user_id,
                    dt,
                    row.get('Category', 'Unknown'),
                    float(row.get('Amount', 0.0)),
                    row.get('Entity', 'Unknown'),
                    row.get('Type', 'Expense'),
                    row.get('Severity', 'Normal'),
                    bool(row.get('Is_Budget_Breach', False)),
                    bool(row.get('Is_Mom_Anomaly', False)),
                    row.get('Anomaly_Reason')
                ))
            
            if not values:
                return
                
            if DATABASE_URL:
                from psycopg2.extras import execute_values
                query = """
                    INSERT INTO transactions (
                        user_id, date, category, amount, entity, type, 
                        severity, is_budget_breach, is_mom_anomaly, anomaly_reason
                    ) VALUES %s
                """
                execute_values(cur, query, values)
            else:
                query = """
                    INSERT INTO transactions (
                        user_id, date, category, amount, entity, type, 
                        severity, is_budget_breach, is_mom_anomaly, anomaly_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                cur.cur.executemany(query, values)
                
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_user_transactions(user_id: int) -> list[dict]:
    """Retrieves all transactions for a user, sorted by date."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, date, category, amount, entity, type, 
                       severity, is_budget_breach, is_mom_anomaly, anomaly_reason 
                FROM transactions 
                WHERE user_id = %s 
                ORDER BY date ASC
            """, (user_id,))
            rows = cur.fetchall()
            
            results = []
            for r in rows:
                d = dict(r)
                
                import datetime
                dt_val = d.get('date')
                if isinstance(dt_val, str):
                    try:
                        if ' ' in dt_val:
                            dt_val = datetime.datetime.strptime(dt_val.split('.')[0], '%Y-%m-%d %H:%M:%S')
                        else:
                            dt_val = datetime.datetime.fromisoformat(dt_val.split('.')[0])
                    except Exception:
                        pass
                        
                amt_val = float(d.get('amount', 0.0))
                
                mapped = {
                    'id': d.get('id'),
                    'user_id': d.get('user_id'),
                    'Date': dt_val,
                    'Category': d.get('category'),
                    'Amount': amt_val,
                    'Entity': d.get('entity'),
                    'Type': d.get('type'),
                    'Severity': d.get('severity', 'Normal'),
                    'Is_Budget_Breach': bool(d.get('is_budget_breach', False)),
                    'Is_Mom_Anomaly': bool(d.get('is_mom_anomaly', False)),
                    'Anomaly_Reason': d.get('anomaly_reason')
                }
                results.append(mapped)
            return results
    finally:
        conn.close()

def update_transaction_anomalies(user_id: int, rows: list[dict]):
    """Updates anomaly flags for a set of transactions by ID using bulk updates."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            values = []
            for row in rows:
                tx_id = row.get('id')
                if tx_id:
                    values.append((
                        row.get('Severity', 'Normal'),
                        bool(row.get('Is_Budget_Breach', False)),
                        bool(row.get('Is_Mom_Anomaly', False)),
                        row.get('Anomaly_Reason'),
                        tx_id,
                        user_id
                    ))
            
            if not values:
                return
                
            if DATABASE_URL:
                from psycopg2.extras import execute_batch
                query = """
                    UPDATE transactions 
                    SET severity = %s, is_budget_breach = %s, is_mom_anomaly = %s, anomaly_reason = %s
                    WHERE id = %s AND user_id = %s
                """
                execute_batch(cur, query, values)
            else:
                query = """
                    UPDATE transactions 
                    SET severity = ?, is_budget_breach = ?, is_mom_anomaly = ?, anomaly_reason = ?
                    WHERE id = ? AND user_id = ?
                """
                cur.cur.executemany(query, values)
                
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

