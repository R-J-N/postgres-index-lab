import json

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
DIM    = "\033[2m"
WHITE  = "\033[97m"

EXPLANATIONS = {
    "1. Hash Index — exact email lookup": {
        "what":    "Looks up a single row by exact email match.",
        "without": "Postgres does a full Sequential Scan — reads all 1M rows one by one, "
                   "comparing each email until it finds the match. Every row is touched "
                   "even though only one matches.",
        "with":    "Hash index computes hash('email') → jumps directly to the row. "
                   "Zero traversal, zero comparisons. O(1) lookup regardless of table size.",
        "why":     "Hash indexes are perfect for equality (=) on high-cardinality columns. "
                   "Useless for ranges or LIKE queries — hashing destroys ordering."
    },
    "2. B-Tree — age range query": {
        "what":    "Finds all users aged between 25 and 35 (~19% of the table).",
        "without": "Sequential Scan across all 1M rows. Slow but predictable — "
                   "reads the whole table in one pass.",
        "with":    "Even with the index, the speedup is tiny. Postgres chose Bitmap Heap Scan "
                   "but the gain is minimal because 19% of 1M rows = ~190k rows to fetch. "
                   "At that scale, random index lookups aren't faster than a sequential read. "
                   "The query planner is working correctly — it picked the cheapest plan.",
        "why":     "B-Tree indexes shine on high-selectivity queries (few rows returned). "
                   "When a query returns a large % of the table, sequential scan wins. "
                   "Narrow the range to 2-3 years and the speedup jumps dramatically."
    },
    "3. Composite Index — city + age filter": {
        "what":    "Finds users in Bangalore aged under 30 — filters on two columns.",
        "without": "Bitmap Heap Scan without the composite index — Postgres uses whatever "
                   "partial index is available, or scans broadly and filters in memory.",
        "with":    "Composite index (city, age) lets Postgres jump directly to the "
                   "'Bangalore' section, then within that section only read rows where age < 30. "
                   "Both columns are resolved inside the index before touching the heap.",
        "why":     "Column order matters — city must come first because it's the higher "
                   "selectivity filter. Querying only age without city cannot use this index "
                   "(left-prefix rule). The ~3x speedup reflects a well-targeted two-column filter."
    },
    "4. Partial Index — active users by city": {
        "what":    "Finds active users in Mumbai. The index only covers active rows.",
        "without": "Scans all users matching Mumbai, then filters by status in memory.",
        "with":    "Partial index contains only the 700k active rows — 300k inactive/banned "
                   "rows are never indexed. Index is smaller, lookups are faster.",
        "why":     "The 1.4x speedup is modest because active = 70% of rows — still a large "
                   "subset. Partial indexes give the biggest wins when the filtered subset is "
                   "small (e.g. status = 'banned' at 10%). The real benefit is also storage: "
                   "this index is 30% smaller than a full index on the same column."
    },
    "5. Covering Index — salary lookup by city": {
        "what":    "Selects city, salary, age for all users in Delhi.",
        "without": "Bitmap Heap Scan — finds rows via index, then fetches each row from "
                   "the heap (main table) to get salary and age values. Two-step I/O.",
        "with":    "Index Only Scan — salary and age are stored directly inside the index "
                   "via INCLUDE(salary, age). Postgres never touches the heap at all. "
                   "All needed values come straight from the index pages.",
        "why":     "The scan type change (Bitmap → Index Only) is the real win here, "
                   "more than the raw speedup number. Eliminating heap fetches reduces I/O "
                   "dramatically on wide tables or queries returning many rows."
    },
    "6. B-Tree — date range + ORDER BY": {
        "what":    "Finds users created in 2022 and returns them sorted, limited to 100.",
        "without": "Sequential Scan of all 1M rows → filter ~167k rows → sort all of them "
                   "→ return first 100. Three expensive steps.",
        "with":    "B-Tree stores created_at in sorted order. Postgres jumps to Jan 1 2022 "
                   "in the leaf nodes, walks forward, and stops after 100 rows. "
                   "No sort step needed — data comes out pre-ordered. LIMIT makes this "
                   "especially powerful: only 100 rows are ever read.",
        "why":     "This is the ideal B-Tree scenario — range filter + ORDER BY + LIMIT "
                   "on the same indexed column. The index handles filtering, sorting, and "
                   "early termination all at once. 260x speedup reflects this perfectly."
    },
}

def bar(value, max_value, width=30):
    filled = int((value / max_value) * width)
    return "█" * filled + "░" * (width - filled)

def speedup_color(s):
    if s >= 100: return GREEN
    if s >= 10:  return CYAN
    if s >= 3:   return YELLOW
    return RED

def print_report(data):
    print(f"\n{BOLD}{WHITE}{'═'*60}{RESET}")
    print(f"{BOLD}{WHITE}  PostgreSQL Index Benchmark Report{RESET}")
    print(f"{DIM}  1,000,000 rows · 6 index types{RESET}")
    print(f"{BOLD}{WHITE}{'═'*60}{RESET}\n")

    max_speedup = max(d["speedup"] for d in data)

    for d in data:
        name    = d["name"]
        exp     = EXPLANATIONS.get(name, {})
        speedup = d["speedup"]
        sc      = speedup_color(speedup)

        # ── Header ──
        print(f"{BOLD}{CYAN}{name}{RESET}")
        print(f"{DIM}{'─'*60}{RESET}")

        # ── What this tests ──
        print(f"{BOLD}  What:{RESET} {exp.get('what','')}")
        print()

        # ── Without index ──
        print(f"{BOLD}{RED}  Without index:{RESET}")
        print(f"    Time : {RED}{d['without_ms']:.2f} ms{RESET}")
        print(f"    Plan : {d['without_plan']}")
        print(f"    {exp.get('without','')}")
        print()

        # ── With index ──
        print(f"{BOLD}{GREEN}  With index:{RESET}")
        print(f"    Time : {GREEN}{d['with_ms']:.2f} ms{RESET}")
        print(f"    Plan : {d['with_plan']}")
        print(f"    {exp.get('with','')}")
        print()

        # ── Speedup bar ──
        b = bar(speedup, max_speedup)
        print(f"  {BOLD}Speedup:{RESET} {sc}{BOLD}{speedup}×{RESET}  {sc}{b}{RESET}")
        print()

        # ── Why ──
        print(f"{BOLD}  Key insight:{RESET}")
        print(f"  {DIM}{exp.get('why','')}{RESET}")
        print(f"\n{DIM}{'═'*60}{RESET}\n")

    # ── Summary ──
    print(f"{BOLD}{WHITE}  SUMMARY{RESET}")
    print(f"{DIM}{'─'*60}{RESET}\n")

    speedups = [(d["name"], d["speedup"], d["without_ms"], d["with_ms"]) for d in data]
    speedups.sort(key=lambda x: -x[1])

    print(f"{BOLD}  Ranked by speedup:{RESET}\n")
    for name, s, wo, wi in speedups:
        sc    = speedup_color(s)
        label = name.split("—")[1].strip() if "—" in name else name
        print(f"    {sc}{s:>7}×{RESET}  {label}")
    print()

    print(f"{BOLD}  Observations:{RESET}\n")

    observations = [
        ("Hash index is king for exact lookups",
         "864x speedup on a single-row equality search. If you have a column "
         "that's always queried with =, hash index is faster than B-Tree."),

        ("B-Tree + LIMIT is devastatingly effective",
         "260x speedup when range filter, ORDER BY, and LIMIT all align on one "
         "indexed column. The index eliminates the scan, the sort, and enables "
         "early exit — three wins in one."),

        ("Low selectivity queries ignore indexes",
         "Age range returning 19% of rows got only 1.1x speedup. Postgres "
         "correctly chose a sequential scan — random I/O for 190k rows is "
         "slower than one straight read of the table."),

        ("Covering index changes the scan type entirely",
         "Bitmap Heap Scan → Index Only Scan. Eliminating heap fetches is "
         "architecturally better than just being faster — it scales as the "
         "table grows wider and the result set grows larger."),

        ("Composite indexes need the right column order",
         "city + age gave 3x speedup because city (high selectivity) leads. "
         "Reversing to age + city for a city= query would get nothing — "
         "the left-prefix rule is non-negotiable."),

        ("Partial indexes trade generality for efficiency",
         "Smaller index, faster lookups, less write overhead — but only useful "
         "when the filtered subset is small. At 70% coverage (active users) "
         "the gain is modest. At 10% (banned users) it would be dramatic."),
    ]

    for i, (title, body) in enumerate(observations, 1):
        print(f"  {BOLD}{i}. {title}{RESET}")
        print(f"     {DIM}{body}{RESET}\n")

    print(f"{BOLD}{WHITE}{'═'*60}{RESET}\n")


if __name__ == "__main__":
    with open("results.json") as f:
        data = json.load(f)
    print_report(data)
