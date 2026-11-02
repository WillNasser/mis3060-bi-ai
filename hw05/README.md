# HW5: Modeling the Wildcat Capital Data as a Star Schema in Power BI

MIS3060 Business Intelligence with AI. This folder holds the key, grain and measure analysis for the eight clean Wildcat Capital tables, a Python script that proves it, and the Power BI star-schema model.

## Structure

```
hw05/
├── README.md              this file
├── star_design.md         Parts A, B, C, E and F (keys, grain, measures, design questions, reflection)
├── check_star.py          read-only checks: row counts, keys, foreign keys, grain, numeric columns
├── powerbi/
│   ├── hw05.pbix          the saved Power BI model (Part D)
│   └── model_view.png     full Model view screenshot
└── data/                  the eight clean CSVs (not pushed to GitHub, see below)
```

## How to run

From the `hw05` folder:

```
python check_star.py
```

It uses only the Python standard library, reads the CSVs in `data/`, and never writes or deletes anything. It prints every check with OK or PROBLEM, ends with a summary, and exits with code 0 if everything passes and 1 if any check fails.

**Data:** the eight CSVs come from the `Wildcat Capital Clean/` folder released after HW4. Copy them into `hw05/data/` before running. They are not committed because the repository's `.gitignore` excludes CSV files in subfolders.

## Power BI model

The model has 8 tables and 11 relationships, all Many to one, single direction and active, with each fact on the many side:

- `fact_transactions`, `fact_fees` and `fact_portfolio_snapshot` → `dim_client` on `client_id`
- the same three facts → `dim_advisor` on `advisor_id`
- the same three facts → `dim_date` on `date` (`txn_date`, `fee_date` and `snapshot_date`), with `dim_date` marked as the date table
- `fact_transactions` → `dim_security` on `security_id`
- `fact_portfolio_snapshot` → `dim_benchmark` on `benchmark_id`

`dim_client[advisor_id] → dim_advisor` and `dim_security[benchmark_id] → dim_benchmark` are not wired as relationships, so the model is a pure star (see Part E in `star_design.md`). Row counts of all eight tables were checked with Count cards and match the handout.

## Claude Code review of check_star.py

Claude Code reviewed the script before this commit. It confirmed the script is read-only and easy to read, and reported these findings:

| # | Finding | What I did |
|---|---|---|
| 1 | Foreign-key check ignored blanks, so a blank key anywhere would still print OK (real bug) | Fixed: only `fact_transactions.security_id` may be blank; any other blank prints PROBLEM |
| 2 | Values of only spaces counted as filled in | Fixed: values are stripped when the CSVs are loaded |
| 3 | Keys compared as text, so `1` and `1.0` would count as different values | Not changed: every ID in the data is a plain whole number, so it does not affect the results. Known limit |
| 4 | "Per month" grain was tested per date | Fixed: grain now tests client plus month (`YYYY-MM`) |
| 5 | Transactions grain repeats the primary-key check | Added a comment saying so |
| 6 | Part C lists IDs, flags and `zip_code` as numeric | Renamed to "numeric-looking columns" with a note; the real measure classification is in `star_design.md` |
| 7 | Script always exited with code 0 | Fixed: exits with code 1 if any check fails |
| 8 | `date_id` line had no blank check or OK/PROBLEM label | Fixed |
| 9 | Short rows would give missing values instead of blanks | Covered by the strip fix, which turns missing fields into blank text |

After the fixes, the script passes all 33 checks on the real data. I also tested it on a throwaway copy of the data with a blank `client_id` and a duplicate fee row added, and it reported both and exited with code 1.
