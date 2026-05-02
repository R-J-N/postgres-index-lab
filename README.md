# PostgreSQL Index Benchmark Lab

A hands-on benchmarking project to understand how different PostgreSQL indexing
strategies affect query performance at scale. All benchmarks run against a
1,000,000 row dataset generated with realistic data distributions.

## What this covers

| Index type       | Query pattern                        |
|------------------|--------------------------------------|
| Hash             | Exact equality lookup on email       |
| B-Tree           | Range query on age                   |
| Composite        | Multi-column filter on city + age    |
| Partial          | Filtered subset — active users only  |
| Covering         | Index-only scan, no heap fetch       |
| B-Tree + LIMIT   | Date range + ORDER BY + early exit   |

## Project structure
postgres-index-lab/
├── schema.py       # creates the users table
├── generate.py     # inserts 1M rows using Faker
├── benchmark.py    # runs EXPLAIN ANALYZE with/without each index
├── report.py       # prints results with explanations to terminal
├── results.json    # captured benchmark output
└── .gitignore

## Dataset

The `users` table has 7 columns, each chosen to test a specific index type:

```sql
CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    email      VARCHAR(120),   -- hash index
    age        INTEGER,        -- b-tree range
    city       VARCHAR(80),    -- composite + partial + covering
    status     VARCHAR(10),    -- partial index filter (70% active, 20% inactive, 10% banned)
    salary     NUMERIC(10,2),  -- covering index payload
    created_at TIMESTAMP       -- b-tree range + order by
);
```

Status distribution is intentionally skewed (70/20/10) to make partial index
behaviour realistic — a uniform distribution would make the benchmark misleading.

## Prerequisites

- Docker
- Python 3.8+

## Setup

### 1. Start PostgreSQL via Docker

```bash
docker run --name index-lab \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_USER=admin \
  -e POSTGRES_DB=indexdb \
  -p 5432:5432 \
  -d postgres:16
```

### 2. Install Python dependencies

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install psycopg2-binary faker flask pandas
```

### 3. Create table and generate data

```bash
python schema.py       # creates the users table
python generate.py     # inserts 1M rows — takes ~3 minutes
```

### 4. Run benchmarks

```bash
python benchmark.py    # runs all 6 benchmarks, writes results.json
```

### 5. View the report

```bash
python report.py       # prints full analysis to terminal
```

## How the benchmark works

Each benchmark follows the same pattern:

1. Drop any existing index for that column
2. Warm up the buffer cache by running the query once (so cold cache
   doesn't unfairly penalise the no-index run)
3. Run `EXPLAIN ANALYZE` without the index — capture time + scan type
4. Create the index, then run `ANALYZE` so the query planner picks it up
5. Run `EXPLAIN ANALYZE` again — capture time + scan type
6. Calculate speedup ratio and save to `results.json`

## Results

These were captured on a local machine (Apple M2, Docker, PostgreSQL 16).
Your numbers will vary but the relative patterns should hold.

| Index type              | Without index | With index | Speedup | Scan type (with)  |
|-------------------------|---------------|------------|---------|-------------------|
| Hash — email lookup     | 15.57 ms      | 0.02 ms    | 864x    | Index Scan        |
| B-Tree — age range      | 36.44 ms      | 33.94 ms   | 1.1x    | Bitmap Heap Scan  |
| Composite — city + age  | 19.90 ms      | 6.55 ms    | 3x      | Bitmap Heap Scan  |
| Partial — active + city | 18.08 ms      | 12.64 ms   | 1.4x    | Bitmap Heap Scan  |
| Covering — city salary  | 19.16 ms      | 11.17 ms   | 1.7x    | Index Only Scan   |
| B-Tree — date + ORDER   | 18.26 ms      | 0.07 ms    | 260x    | Index Scan        |

## What I learned

### 1. Selectivity determines whether an index gets used
The B-Tree age range query returned ~190k rows (19% of the table) and got only
a 1.1x speedup. Postgres deliberately ignored the index because sequential
reads are faster than 190k random disk jumps. Indexes only help when a query
is highly selective — fetching a small fraction of total rows.

### 2. Hash indexes are the fastest possible equality lookup
864x speedup on a single-row email lookup. A hash index computes
`hash(value)` and jumps directly to the row — O(1) regardless of table size.
The tradeoff is that hash indexes are useless for range queries, sorting,
or LIKE patterns since hashing destroys the natural ordering of values.

### 3. B-Tree + LIMIT is extremely powerful
260x speedup on the date range query. When a B-Tree index covers the filter
column, the ORDER BY column, and a LIMIT is applied — all three operations
collapse into a single index walk. Postgres jumps to the start of the range,
reads forward in sorted order, and stops after hitting the LIMIT. The rest
of the table is never touched.

### 4. Covering indexes eliminate an entire I/O layer
The covering index changed the scan type from Bitmap Heap Scan to Index Only
Scan. Normally even an indexed query requires two steps — find the row
location in the index, then fetch the actual row from the heap to get the
column values. A covering index stores the needed column values directly
inside the index, making the heap fetch unnecessary entirely.

### 5. Composite indexes depend on column order
The composite index on `(city, age)` works for `WHERE city = x AND age < y`
and `WHERE city = x` alone, but is completely useless for `WHERE age < y`
alone. This is the left-prefix rule — the leading column must appear in the
query filter. High-selectivity columns should lead.

### 6. Partial indexes trade generality for efficiency
The partial index on active users gave a modest 1.4x speedup because active
accounts are 70% of the table — still a large subset. The real benefit of
partial indexes appears when the indexed subset is small and frequently
queried (e.g. `status = 'banned'` at 10%). Smaller index = less memory,
faster lookups, lower write overhead.

## Key takeaway

> The query planner already knows what it's doing. The job of indexing is
> not to force a faster path — it's to give the planner better options to
> choose from. Understanding selectivity, column ordering, and I/O patterns
> is what separates an index that helps from one that does nothing.
