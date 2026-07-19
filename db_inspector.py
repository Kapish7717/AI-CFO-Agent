import os
import sqlite3

def main():
    db_path = os.path.join("db", "cfo_agent.db")
    if not os.path.exists(db_path):
        print(f"Database file not found at: {os.path.abspath(db_path)}")
        return

    print(f"Connecting to SQLite database at: {os.path.abspath(db_path)}\n")
    conn = sqlite3.connect(db_path)
    # Use a dictionary factory to print rows nicely
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        # Get list of tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row['name'] for row in cur.fetchall()]
        print(f"Found tables: {', '.join(tables)}\n" + "="*50)

        for table in tables:
            print(f"\nTable: {table}")
            cur.execute(f"PRAGMA table_info({table});")
            columns = [col['name'] for col in cur.fetchall()]
            print(f"Columns: {', '.join(columns)}")
            
            cur.execute(f"SELECT * FROM {table};")
            rows = cur.fetchall()
            print(f"Rows ({len(rows)} total):")
            for row in rows:
                print(dict(row))
            print("-" * 50)
            
    except Exception as e:
        print(f"Error inspecting database: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
