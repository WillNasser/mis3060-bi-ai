# HW4: Cleaning the Wildcat Capital Data

Will Nasser · MIS3060 · Villanova University

This folder audits, cleans and validates the eight Wildcat Capital tables. Raw data is never modified: every fix is made on a copy, every changed value is logged, and every removed row is saved to a quarantine file.

## Folder structure

```
hw04/
├── README.md                      this file
├── decision_log.md                Part B: 14 issues, six fields each, written before the cleaning code
├── scripts/
│   ├── 01_profile.py              Part A: generic profiler + audit findings
│   ├── 02_clean.py                Part C: cleaning program with checks, quarantine and audit trail
│   └── 03_validate.py             Part D: referential integrity, rules, reconciliations, scorecard
├── reports/
│   ├── profile_raw.csv            per-column profile of the raw tables
│   ├── dq_summary_raw.csv         ERROR / WARN / INFO findings on the raw tables
│   ├── ri_summary_raw.csv         key-match rates found by the profiler
│   ├── data_quality_scorecard.csv one row per table per stage (raw / clean)
│   ├── ri_results.csv             13 relationships, strict match, per stage
│   ├── rule_results.csv           rule checks, with rows evaluated / not evaluated
│   ├── reconciliations.csv        cross-column and cross-table checks (R1-R11)
│   ├── outlier_flags.csv          IQR fences per column (and per type)
│   ├── outlier_rows.csv           every flagged row
│   └── cleaning_report.md         Part E: business report for the portfolio committee
└── data/
    ├── raw/                       the 8 raw CSVs (not committed; same practice as earlier homeworks)
    ├── clean/                     8 clean tables + README_clean.md
    └── audit/                     cleaning_log.csv, value_changes.csv, quarantine_*.csv, run_manifest.csv
```

## How to run

Python 3 with pandas and numpy (`pip install pandas numpy`). Put the eight raw CSVs in `data/raw/`, open a terminal in the `hw04` folder, and run the scripts in this order:

```
python scripts/01_profile.py
python scripts/02_clean.py
python scripts/03_validate.py
```

- `01_profile.py` reads `data/raw` and writes the three profile reports to `reports/`.
- `02_clean.py` reads `data/raw`, runs every check, and only then writes `data/clean/` and `data/audit/`. It stops with `CHECK FAILED` if any proof fails, and it refuses to overwrite the raw folder.
- `03_validate.py` validates both `data/raw` and `data/clean` and writes the scorecard and the other validation reports to `reports/`.

Close any output CSV in Excel before re-running, or the script stops before it changes anything.

## How the work is organised

| Part | What | Where |
|---|---|---|
| A Audit | Generic profiler (works on any table) plus four groups of checks, tagged ERROR / WARN / INFO | `scripts/01_profile.py`, `reports/profile_raw.csv`, `reports/dq_summary_raw.csv` |
| B Decision log | 14 issues: found, why it matters, options, decision, risk. Includes the "leave as is" decisions | `decision_log.md` |
| C Cleaning | One transformation at a time, each followed by an after-state check; raw = clean + quarantined proven by ID; every changed cell logged | `scripts/02_clean.py`, `data/clean/`, `data/audit/` |
| D Validation | One reusable `check_referential_integrity()`, 10 ID + 3 date relationships, rule checks, 11 reconciliations, IQR flags, scorecard for raw and clean | `scripts/03_validate.py`, `reports/` |
| E Report | 1-2 page report for the portfolio committee | `reports/cleaning_report.md` |

## Claude Code findings and what I did about them

Claude Desktop drafted each script, I ran it in VS Code, and Claude Code reviewed it before I committed. Findings were triaged by severity: fixed, or left alone with a reason. Several scripts were reviewed twice, and a few fixes (for example the scientific-notation step) came from my own testing of the outputs, not from Claude Code.

### 01_profile.py (15 findings)

| Severity | Finding | What I did |
|---|---|---|
| High | The `return_ytd` range check mixed percent-text rows with 471 plain decimals above 2.0, and missed percent rows inside the range | Percent-aware parsing; extreme returns reported as their own finding (`extreme_return_ytd`, 472 rows) and logged as Issue 11 |
| High | Values that did not parse were skipped silently by the table rules | Unparseable values are reported as findings; name-based types (`*_id`, `amount`, `is_*`) so they are reported even when most of a column fails |
| High | Duplicate primary keys checked on raw text (`45` vs `45.0`) | Keys normalised before the duplicate check |
| High | No rules depended on transaction type; blank `security_id` severity came from the column name | Blank checks are type-aware (Buy/Sell/Dividend must have them; Deposit/Withdrawal/Advisory Fee legitimately don't) |
| Medium | Orphan clients counted as account-type mismatches; true/false spelling check unreliable; near-duplicate check ignored signs; cross-table checks hid duplicates | Fixed each (orphans skipped explicitly, boolean tokens handled, minus sign kept in near-duplicate keys, duplicates reported) |
| Medium | Table rules crashed when a column was missing | `@requires(...)` guards skip a rule with a clear message |
| Low | Misleading counts, noisy INFO findings, `--out` equal to `--in`, results changing by calendar day, repeated `main()` calls | Fixed: counts corrected, `--out` must differ from `--in`, "today" fixed at 2024-12-31, state reset on each run |

### 02_clean.py, first review (13 findings)

| Severity | Finding | What I did |
|---|---|---|
| High | "Every changed cell is logged" compared counts only | Now joins the log to the raw and clean values by key, old value and new value |
| High | Rows reconciled by count, not by ID | Raw = clean + quarantined is now proven by ID (no overlap, unique keys, IDs add up) |
| High | Missing values in the `return_ytd` reconciliation were skipped | The script stops if any of the three columns is blank or unparseable |
| High | Checks used `assert`, which `python -O` removes | Replaced with a `check()` function that raises |
| Medium | Tables written before all checks passed; stale quarantine files | All checks run first; outputs are staged and written at the end |
| Medium | `--clean` could point at the raw folder | The script refuses a clean or audit folder that is, contains or sits inside the raw folder |
| Medium | 1% / $1 tolerance too loose for the shares sign fix | Measured the real worst difference (0.005) and tightened to 1 cent |
| Medium/Low | Rows silently skipped (orphan clients in later checks, unparsed values), ID format mismatch, checks that cannot fail, whitespace-only risk values, log notes claiming more than was checked, hard-coded README numbers | Each addressed: explicit checks, notes reworded or computed from the data, whitespace-only values cleared |

### 02_clean.py, second review of the final version (high 1, medium 4, low many)

| Severity | Finding | What I did |
|---|---|---|
| High | Outputs could be half-written while being moved into place (Excel lock, different drive) | Each output folder stages inside itself; every destination is tested as writable first; a manifest with a run ID and SHA-256 hashes is moved last; a failed move says the folders may mix old and new files |
| Medium | Old files from earlier runs could sit beside new ones | Old quarantine files or unexpected files in `clean/` now stop the run |
| Medium | New proofs not checked against the decision log | Raw counts (40,649 of 143,311 weekend trades; 35,766 Advisory debits; 10,855 client-years) are now checked |
| Medium | Notes claimed things the code never tested (even weekday spread, "AUM growth", "floor", fee formula) | Each claim is now computed and checked, or reworded |
| Medium | README relationships were fixed text | README says `03_validate.py` tests all 13; this script only proves the ones it tests |
| Low | -100% return divided by zero; sci-notation pattern too narrow; flag columns never checked; tolerances loose; hard-coded README text; "raw not modified" unproven | Range check first; broader pattern with exact `Decimal` comparison; flags recomputed from raw; tighter tolerances; README text computed; raw files hashed before and after |

### 03_validate.py (about 25 findings)

| Severity | Finding | What I did |
|---|---|---|
| High | Duplicate parent keys were hidden, and `dim_date.date` uniqueness was never checked | The RI function now reports the parent's size, blank keys and duplicate-key rows; the uniqueness score covers `dim_date.date`; R11 checks one row per calendar day |
| Medium | Empty tables crashed completeness or scored 100% referential match; key uniqueness did not match its definition | Empty tables score NaN or 100% as appropriate; every copy of a duplicated key now fails |
| Medium | "Strict" matching trimmed spaces; RI function not self-contained; missing column gave a bare `KeyError` | Exact text matching; the function needs only pandas; clear error message; self-test covers whitespace, zero padding, duplicates, empty tables |
| Medium | Rows silently left out of rules and reconciliations; R7 for transactions weaker than its label; R8 wording not tested; outlier "flags" were only counts | `rows_not_evaluated` / `rows_skipped` columns; R7 note gives the exact-date count; new R10 tests `is_trading_day` against the weekday; every flagged row is listed in `outlier_rows.csv` |
| Medium | Completeness gaps (case-sensitive ETF test, mistyped `txn_type`, no check in the other direction) | Fixed, and new `blank_when` rules check that structural blanks stay blank |
| Low | Hard-coded dates and years, infinity passed range rules, ticker and certification rules too strict or loose, loose tolerances, IQR mixed unlike values, report files written one at a time | Bounds from `dim_date`; finite values only; broader ticker rule and no duplicate certifications; largest differences reported; IQR split by transaction and fee type; reports written together |

Findings I left alone: the allowed lists were chosen from the business description and what the data showed, so they can only confirm the data (stated in the script's docstring); there is no bound rule on `active_alpha_ytd`; the RI function has no composite-key or case-insensitive option, which this schema does not need; R3 keeps its 1e-4 tolerance, now reported with the largest difference found.

## Key results

See `reports/data_quality_scorecard.csv` and `reports/cleaning_report.md`. Every number in the report comes from the script output in this folder.
