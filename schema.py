import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5432,
    database="indexdb", user="admin", password="secret"
)
cur = conn.cursor()

cur.execute("DROP TABLE IF EXISTS users;")

cur.execute("""
    CREATE TABLE users (
        id         SERIAL PRIMARY KEY,
        email      VARCHAR(120) NOT NULL,
        age        INTEGER,
        city       VARCHAR(80),
        status     VARCHAR(10),
        salary     NUMERIC(10, 2),
        created_at TIMESTAMP
    );
""")

conn.commit()
cur.close()
conn.close()
print("Table created.")
