import psycopg2
import json
import re

conn = psycopg2.connect(
    host="localhost", port=5432,
    database="indexdb", user="admin", password="secret"
)
conn.autocommit = True
cur = conn.cursor()

results = []

def extract_time(explain_output):
    """Pull execution time in ms from EXPLAIN ANALYZE output."""
    for line in explain_output:
        match = re.search(r"Execution Time: ([\d.]+) ms", line[0])
        if match:
            return float(match.group(1))
    return None

def extract_plan(explain_output):
    """Get the scan type used — e.g. Index Scan, Seq Scan."""
    for line in explain_output:
        for scan in ["Index Only Scan", "Index Scan", "Bitmap Heap Scan",
                     "Seq Scan", "Hash"]:
            if scan in line[0]:
                return scan
    return "Unknown"

def run_benchmark(name, index_sql, query_sql, drop_sql=None):
    print(f"\n{'='*50}")
    print(f"Benchmark: {name}")

    # --- drop index if it already exists from a previous run ---
    if drop_sql:
        cur.execute(drop_sql)

    # --- warm up buffer cache so first run isn't penalised ---
    cur.execute(query_sql)

    # --- WITHOUT index ---
    cur.execute(f"EXPLAIN ANALYZE {query_sql}")
    without_rows = cur.fetchall()
    without_time = extract_time(without_rows)
    without_plan = extract_plan(without_rows)
    print(f"  Without index: {without_time:>8.2f} ms  ({without_plan})")

    # --- create the index ---
    print(f"  Creating index...")
    cur.execute(index_sql)

    # --- run ANALYZE so planner knows the index exists ---
    cur.execute("ANALYZE users;")

    # --- WITH index ---
    cur.execute(f"EXPLAIN ANALYZE {query_sql}")
    with_rows = cur.fetchall()
    with_time = extract_time(with_rows)
    with_plan = extract_plan(with_rows)
    print(f"  With index:    {with_time:>8.2f} ms  ({with_plan})")

    speedup = round(without_time / with_time, 1) if with_time else None
    print(f"  Speedup:       {speedup}x")

    results.append({
        "name":         name,
        "without_ms":   without_time,
        "with_ms":      with_time,
        "speedup":      speedup,
        "without_plan": without_plan,
        "with_plan":    with_plan,
        "index_sql":    index_sql,
        "query_sql":    query_sql,
    })

# ─────────────────────────────────────────
# Drop all indexes before starting
# ─────────────────────────────────────────
print("Dropping existing indexes...")
for idx in ["idx_email_hash", "idx_age_btree", "idx_city_age_composite",
            "idx_active_partial", "idx_covering", "idx_created_at"]:
    cur.execute(f"DROP INDEX IF EXISTS {idx};")

# ─────────────────────────────────────────
# 1. Hash Index — exact email lookup
# ─────────────────────────────────────────
cur.execute("SELECT email FROM users LIMIT 1;")
sample_email = cur.fetchone()[0]

run_benchmark(
    name      = "1. Hash Index — exact email lookup",
    index_sql = "CREATE INDEX idx_email_hash ON users USING HASH (email);",
    drop_sql  = "DROP INDEX IF EXISTS idx_email_hash;",
    query_sql = f"SELECT * FROM users WHERE email = '{sample_email}';"
)

# ─────────────────────────────────────────
# 2. B-Tree — age range query
# ─────────────────────────────────────────
run_benchmark(
    name      = "2. B-Tree — age range query",
    index_sql = "CREATE INDEX idx_age_btree ON users (age);",
    drop_sql  = "DROP INDEX IF EXISTS idx_age_btree;",
    query_sql = "SELECT * FROM users WHERE age BETWEEN 25 AND 35;"
)

# ─────────────────────────────────────────
# 3. Composite Index — city + age filter
# ─────────────────────────────────────────
run_benchmark(
    name      = "3. Composite Index — city + age filter",
    index_sql = "CREATE INDEX idx_city_age_composite ON users (city, age);",
    drop_sql  = "DROP INDEX IF EXISTS idx_city_age_composite;",
    query_sql = "SELECT * FROM users WHERE city = 'Bangalore' AND age < 30;"
)

# ─────────────────────────────────────────
# 4. Partial Index — active users only
# ─────────────────────────────────────────
run_benchmark(
    name      = "4. Partial Index — active users by city",
    index_sql = "CREATE INDEX idx_active_partial ON users (city) WHERE status = 'active';",
    drop_sql  = "DROP INDEX IF EXISTS idx_active_partial;",
    query_sql = "SELECT * FROM users WHERE city = 'Mumbai' AND status = 'active';"
)

# ─────────────────────────────────────────
# 5. Covering Index — no heap fetch needed
# ─────────────────────────────────────────
run_benchmark(
    name      = "5. Covering Index — salary lookup by city",
    index_sql = "CREATE INDEX idx_covering ON users (city) INCLUDE (salary, age);",
    drop_sql  = "DROP INDEX IF EXISTS idx_covering;",
    query_sql = "SELECT city, salary, age FROM users WHERE city = 'Delhi';"
)

# ─────────────────────────────────────────
# 6. B-Tree — created_at range + sort
# ─────────────────────────────────────────
run_benchmark(
    name      = "6. B-Tree — date range + ORDER BY",
    index_sql = "CREATE INDEX idx_created_at ON users (created_at);",
    drop_sql  = "DROP INDEX IF EXISTS idx_created_at;",
    query_sql = """SELECT * FROM users
                   WHERE created_at BETWEEN '2022-01-01' AND '2022-12-31'
                   ORDER BY created_at LIMIT 100;"""
)

# ─────────────────────────────────────────
# Save results
# ─────────────────────────────────────────
with open("results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*50}")
print("All benchmarks done! Results saved to results.json")

cur.close()
conn.close()
