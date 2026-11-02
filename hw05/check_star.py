"""HW5 star-schema checks: primary keys, foreign keys, grain, numeric columns.

Reads the eight Wildcat Capital CSVs in ./data and prints evidence for
star_design.md Parts A, B and C. Read-only: it never changes any file.

Run from the hw05 folder:
    python check_star.py

Exit code is 0 when every check passes and 1 if any check reports a problem.
"""
import csv
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

TABLES = [
    "dim_advisor", "dim_benchmark", "dim_client", "dim_date",
    "dim_security", "fact_fees", "fact_portfolio_snapshot", "fact_transactions",
]
EXPECTED_ROWS = {
    "dim_advisor": 25, "dim_benchmark": 8, "dim_client": 2500, "dim_date": 1827,
    "dim_security": 500, "fact_fees": 122197,
    "fact_portfolio_snapshot": 129547, "fact_transactions": 298572,
}

# Primary key of each table (dim_date is joined on `date`; date_id is also unique)
PRIMARY_KEYS = {
    "dim_advisor": ["advisor_id"],
    "dim_benchmark": ["benchmark_id"],
    "dim_client": ["client_id"],
    "dim_date": ["date"],
    "dim_security": ["security_id"],
    "fact_fees": ["fee_id"],
    "fact_portfolio_snapshot": ["snapshot_id"],
    "fact_transactions": ["txn_id"],
}

# (child table, child column, parent table, parent column)
FOREIGN_KEYS = [
    ("dim_client", "advisor_id", "dim_advisor", "advisor_id"),
    ("dim_security", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_fees", "client_id", "dim_client", "client_id"),
    ("fact_fees", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_fees", "fee_date", "dim_date", "date"),
    ("fact_portfolio_snapshot", "client_id", "dim_client", "client_id"),
    ("fact_portfolio_snapshot", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_portfolio_snapshot", "snapshot_date", "dim_date", "date"),
    ("fact_transactions", "client_id", "dim_client", "client_id"),
    ("fact_transactions", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_transactions", "security_id", "dim_security", "security_id"),
    ("fact_transactions", "txn_date", "dim_date", "date"),
]

# The only foreign key allowed to be blank: cash rows (deposits, withdrawals and
# advisory fee debits) have no security. A blank anywhere else is a problem.
ALLOWED_BLANK_FKS = {("fact_transactions", "security_id")}

# Part B: (label of the grain columns, function that builds the grain key, meaning)
GRAIN = {
    "fact_fees": (
        "client_id, month of fee_date",
        lambda r: (r["client_id"], r["fee_date"][:7]),
        "one fee row per client per month",
    ),
    "fact_portfolio_snapshot": (
        "client_id, month of snapshot_date",
        lambda r: (r["client_id"], r["snapshot_date"][:7]),
        "one snapshot row per client per month",
    ),
    # Same test as the primary key above, repeated here so Part B stands alone.
    "fact_transactions": (
        "txn_id",
        lambda r: (r["txn_id"],),
        "one row per transaction",
    ),
}

NUM = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?$")

problems = 0


def flag(ok):
    """Return OK or PROBLEM, and count the problem."""
    global problems
    if not ok:
        problems += 1
    return "OK" if ok else "PROBLEM"


def load(name):
    """Read a CSV; strip whitespace and turn missing fields into blank text."""
    with open(DATA / f"{name}.csv", newline="", encoding="utf-8-sig") as f:
        return [{k: (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(f)]


def banner(text):
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def main():
    if not DATA.exists():
        sys.exit(f"Data folder not found: {DATA}")
    tables = {t: load(t) for t in TABLES}

    banner("ROW COUNTS (compare with the handout)")
    for t in TABLES:
        n = len(tables[t])
        status = flag(n == EXPECTED_ROWS[t])
        print(f"  {t:<26}{n:>9,}  expected {EXPECTED_ROWS[t]:>9,}  {status}")

    banner("PART A: PRIMARY KEYS (unique and never blank)")
    for t, cols in PRIMARY_KEYS.items():
        keys = [tuple(r[c] for c in cols) for r in tables[t]]
        blanks = sum(1 for k in keys if "" in k)
        dups = len(keys) - len(set(keys))
        status = flag(blanks == 0 and dups == 0)
        print(f"  {t:<26}{','.join(cols):<14} blanks={blanks} duplicates={dups}  {status}")
    ids = [r["date_id"] for r in tables["dim_date"]]
    id_blanks = sum(1 for v in ids if v == "")
    id_dups = len(ids) - len(set(ids))
    status = flag(id_blanks == 0 and id_dups == 0)
    print(f"  {'dim_date':<26}{'date_id':<14} blanks={id_blanks} duplicates={id_dups}  {status}"
          "  (unique too, but the facts join on `date`)")

    banner("PART A: FOREIGN KEYS (non-blank values must exist in the parent)")
    for child, ccol, parent, pcol in FOREIGN_KEYS:
        parent_keys = {r[pcol] for r in tables[parent]}
        values = [r[ccol] for r in tables[child]]
        blanks = sum(1 for v in values if v == "")
        orphans = sum(1 for v in values if v != "" and v not in parent_keys)
        blanks_ok = blanks == 0 or (child, ccol) in ALLOWED_BLANK_FKS
        status = flag(orphans == 0 and blanks_ok)
        note = "  (blank allowed: cash rows)" if (child, ccol) in ALLOWED_BLANK_FKS else ""
        print(f"  {child}.{ccol} -> {parent}.{pcol}: "
              f"blank={blanks:,} orphans={orphans}  {status}{note}")

    banner("PART B: GRAIN (the stated grain must be unique)")
    for t, (label, key_fn, meaning) in GRAIN.items():
        keys = [key_fn(r) for r in tables[t]]
        dups = len(keys) - len(set(keys))
        status = flag(dups == 0)
        print(f"  {t:<26}grain = ({label})  [{meaning}]  duplicates={dups}  {status}")

    banner("PART C: NUMERIC-LOOKING COLUMNS IN EACH TABLE")
    print("  Note: this lists every column made of numbers, including IDs, 0/1 flags")
    print("  and zip_code. Which of them are measures is decided in star_design.md.")
    for t in TABLES:
        print(f"\n  {t}")
        for col in tables[t][0].keys():
            vals = [r[col] for r in tables[t] if r[col] != ""]
            if not vals or not all(NUM.match(v) for v in vals):
                continue
            nums = [float(v) for v in vals]
            blanks = len(tables[t]) - len(vals)
            print(f"    {col:<24} min={min(nums):>16,.4f} max={max(nums):>16,.4f} "
                  f"blanks={blanks:,}")

    banner("SUMMARY")
    if problems:
        print(f"  {problems} check(s) reported a PROBLEM.")
        sys.exit(1)
    print("  All checks passed.")


if __name__ == "__main__":
    main()
