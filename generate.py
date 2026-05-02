import psycopg2
import random
from faker import Faker
from datetime import datetime, timedelta

fake = Faker()

CITIES   = ["Mumbai", "Delhi", "Bangalore", "Chennai",
            "Hyderabad", "Pune", "Kolkata", "Ahmedabad"]
STATUSES = ["active", "inactive", "banned"]

# active is 70% of rows — makes partial index interesting
STATUS_WEIGHTS = [0.70, 0.20, 0.10]

def random_status():
    return random.choices(STATUSES, weights=STATUS_WEIGHTS)[0]

def random_timestamp():
    start = datetime(2018, 1, 1)
    return start + timedelta(seconds=random.randint(0, 6 * 365 * 24 * 3600))

def generate_batch(n):
    return [
        (
            fake.unique.email(),
            random.randint(18, 75),
            random.choice(CITIES),
            random_status(),
            round(random.uniform(20000, 200000), 2),
            random_timestamp(),
        )
        for _ in range(n)
    ]

conn = psycopg2.connect(
    host="localhost", port=5432,
    database="indexdb", user="admin", password="secret"
)
cur = conn.cursor()

TOTAL      = 1_000_000
BATCH_SIZE = 10_000
batches    = TOTAL // BATCH_SIZE

print(f"Inserting {TOTAL:,} rows in {batches} batches...")

for i in range(batches):
    batch = generate_batch(BATCH_SIZE)
    cur.executemany("""
        INSERT INTO users (email, age, city, status, salary, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, batch)
    conn.commit()

    if (i + 1) % 10 == 0:
        pct = ((i + 1) / batches) * 100
        print(f"  {(i+1)*BATCH_SIZE:>10,} rows inserted  ({pct:.0f}%)")

cur.close()
conn.close()
print("Done! 1,000,000 rows inserted.")
