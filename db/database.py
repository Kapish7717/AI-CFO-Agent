import os
import hashlib
import json
import sys
import psycopg2
import logging
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("db.database")

# Database configuration loaded from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "cfo_agent")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")

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

def get_connection():
    """Establishes connection to the PostgreSQL database with fallback to local SQLite database."""
    try:
        if DATABASE_URL:
            logger.debug("Connecting to database using DATABASE_URL...")
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            logger.debug("Database connection established using DATABASE_URL.")
            return conn
        else:
            try:
                logger.debug(f"Connecting to database {DB_NAME} at {DB_HOST}:{DB_PORT} as user {DB_USER}...")
                conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    cursor_factory=RealDictCursor
                )
                logger.debug("Database connection established.")
                return conn
            except Exception as pg_err:
                logger.warning(f"PostgreSQL connection failed: {pg_err}. Falling back to SQLite local database...")
                import sqlite3
                sqlite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cfo_agent.db")
                conn = sqlite3.connect(sqlite_path)
                conn.row_factory = sqlite_row_factory
                conn.create_function("TO_CHAR", 2, sqlite_to_char)
                return SQLiteConnectionWrapper(conn)
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}", exc_info=True)
        raise e

def init_db():
    """Initializes database tables and seeds a default user."""
    conn = None
    try:
        logger.info("[DB] Initializing PostgreSQL database tables...")
        sys.stderr.write("[DB] Initializing PostgreSQL database...\n")
        # Connect to template1 to ensure the database exists
        try:
            if not DATABASE_URL:
                logger.info(f"Connecting to database template1 at {DB_HOST}:{DB_PORT} as {DB_USER} to check if {DB_NAME} exists...")
                admin_conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    database="template1",
                    user=DB_USER,
                    password=DB_PASSWORD
                )
                admin_conn.autocommit = True
                with admin_conn.cursor() as cur:
                    cur.execute(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'")
                    if not cur.fetchone():
                        logger.info(f"[DB] Database '{DB_NAME}' does not exist. Creating it...")
                        sys.stderr.write(f"[DB] Database '{DB_NAME}' does not exist. Creating it...\n")
                        cur.execute(f"CREATE DATABASE {DB_NAME}")
                admin_conn.close()
        except Exception as e:
            logger.warning(f"[DB Warning] Could not check or create database '{DB_NAME}' from template1: {e}")
            sys.stderr.write(f"[DB Warning] Could not check or create database '{DB_NAME}' from template1: {e}\n")

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
                selected_month VARCHAR(50) NULL
            );
        """)

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

        conn.commit()

        # Seed default user if not exists
        default_email = "arjun@cfo.com"
        cur.execute("SELECT id FROM users WHERE email = %s", (default_email,))
        if not cur.fetchone():
            logger.info(f"[DB] Seeding default user: {default_email} / password123")
            sys.stderr.write(f"[DB] Seeding default user: {default_email} / password123\n")
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
def hash_password(password: str, salt: str = None) -> str:
    """Hashes a password using SHA-256 with a random salt."""
    if not salt:
        salt = os.urandom(16).hex()
    pwd_hash = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
    return f"{salt}:{pwd_hash}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verifies a password against its stored hash."""
    try:
        salt, pwd_hash = stored_hash.split(':')
        new_hash = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
        return new_hash == pwd_hash
    except Exception:
        return False

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
        "selected_month": None
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
                'selected_month'
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

def insert_user_transactions(user_id: int, rows: list[dict]):
    """Inserts a list of transactions for a user using bulk operations for PostgreSQL."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            values = []
            for row in rows:
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
