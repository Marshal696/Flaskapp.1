import sqlite3
conn = sqlite3.connect("db.sqlite")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT UNIQUE,
        aes_key_encrypted TEXT,
        last_seen TEXT,
        status TEXT
    )
""")
conn.commit()
conn.close()
exit()