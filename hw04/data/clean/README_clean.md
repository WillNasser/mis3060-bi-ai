# Clean Wildcat Capital tables: README

Produced by `scripts/02_clean.py` (run 20261026-144821) from the raw files. The script hashes the raw files (SHA-256) before and after
and stops if they differ; the hashes of the inputs and of every output are in `data/audit/run_manifest.csv`.
Every changed value is in `data/audit/value_changes.csv`; every removed row is in `data/audit/quarantine_*.csv`.

## Row accounting
| Table | Raw rows | Clean rows | Quarantined |
|---|---:|---:|---:|
| dim_advisor | 25 | 25 | 0 |
| dim_client | 2,525 | 2,525 | 0 |
| dim_date | 1,827 | 1,827 | 0 |
| dim_security | 500 | 500 | 0 |
| dim_benchmark | 8 | 8 | 0 |
| fact_fees | 122,197 | 122,197 | 0 |
| fact_portfolio_snapshot | 129,547 | 129,547 | 0 |
| fact_transactions | 298,772 | 298,572 | 200 |

## Relationships (primary key -> foreign key)
These are the relationships of the data model; `scripts/03_validate.py` tests every one of them (this script only proves client_id, security_id and the Buy/Sell dates).
ID-based (10):
- dim_advisor.advisor_id -> dim_client.advisor_id, fact_fees.advisor_id, fact_portfolio_snapshot.advisor_id, fact_transactions.advisor_id
- dim_client.client_id -> fact_fees.client_id, fact_portfolio_snapshot.client_id, fact_transactions.client_id
- dim_benchmark.benchmark_id -> dim_security.benchmark_id, fact_portfolio_snapshot.benchmark_id
- dim_security.security_id -> fact_transactions.security_id (blank for Advisory Fee, Deposit, Withdrawal rows)

Date-based (3), joined to dim_date.date: fact_fees.fee_date, fact_portfolio_snapshot.snapshot_date, fact_transactions.txn_date

## Column types for a BI tool
All files are text in the CSV; set these on import.
- **Text (not number):** dim_client.zip_code (232 zips start with 0), all names, tickers, city, state, certifications (the value "None" is real, not null)
- **Whole number:** all `*_id` columns, years, months, age, quarter, week_of_year, years_experience, the 0/1 flag columns and is_* date flags
- **Date:** dim_date.date, dim_client.client_since, fee_date, snapshot_date, txn_date
- **Decimal:** amounts, aum, aum_basis, price, shares, bps_charged, initial_aum, returns and alpha, cash_pct, expense_ratio_bps
- **True/False:** dim_client.is_active, dim_security.is_etf
- Blanks in shares, price, security_id, sector and expense_ratio_bps are **structural** (see below), not missing data

## Flag columns added
- `fact_transactions.shares_sign_fixed`: 1 if the raw shares value was negative and was converted to its absolute value (confirmed against amount = shares x price to the cent)
- `dim_client.risk_profile_missing`: 1 if risk_profile was blank in the raw data (value not filled)
- `fact_portfolio_snapshot.return_ytd_extreme`: 1 if return_ytd is above 2.0 (200%); the value itself is unchanged. A flag means "do not trust as an investment return", not "wrong"

## Known limitations (not fixed, and why)
- **risk_profile blank for 76 clients:** it cannot be inferred from other columns, so it is flagged and left blank.
- **858 fee rows and 930 snapshot rows are dated before client_since:** by at most 30 days, always the 1st of a month; consistent with month-start billing, so left alone.
- **Blank security_id, shares and price on Advisory Fee, Deposit and Withdrawal rows:** correct by design (no security involved).
- **Blank sector (non-equity) and expense_ratio_bps (non-ETF):** not applicable, not missing.
- **200 transactions for client IDs not in dim_client were quarantined:** if those clients exist elsewhere, restore them from the quarantine file.
- **472 snapshot rows (68 clients) have return_ytd above 2.0, up to 94.67:** flagged, not changed. In 10,855 of 10,855 client-years (6+ snapshots) return_ytd implies one constant start-of-year AUM, so it is AUM growth including deposits and withdrawals, not a time-weighted investment return. On the flagged rows the implied start-of-year AUM is small: median 1,048 (maximum 55,897, 56% at or below 2,000) versus a median of 465,167 across all rows. 420 snapshot rows (92 clients) have AUM of exactly 1000.00, which is also the minimum in the table (a floor). Averages of return_ytd and active_alpha_ytd will be skewed; use the flag or medians.
- **40,630 of 143,218 Buy/Sell rows (28.4%) are dated on a weekend:** each day of the week holds 14.1%-14.5% of the Buy/Sell rows (and dim_date treats every weekday as a trading day), so the dates look synthetic. In the raw table it was 40,649 of 143,311. The true trade dates cannot be recovered, so they are left as is; do not use transaction dates for settlement or trading-calendar analysis.
- **Advisory Fee debits in fact_transactions do not reconcile to Advisory fees in fact_fees:** 0 of 7,653 client-months with both match to the cent; the debits are a median 3.11x the fees (35,742 debits totalling 263,709,737 vs 32,370 fees totalling 53,617,373). The debits total 4.9x the fees. fact_fees amounts equal aum_basis x bps_charged / 10000 / 12 to the cent (checked for every Advisory fee), the debits have no such rule here, so use fact_fees for fee revenue and treat the debits as separate figures.
- **Scientific notation:** 135 return_ytd and 756 active_alpha_ytd values written like 9.9e-05 were rewritten as plain decimals (0.000099). The values are exactly equal (checked with Decimal for every cell); only the text format changed.
- **Negative returns are not flagged:** 1,662 rows are below -50% (minimum -0.994). Because return_ytd is AUM growth since the start of the year, these mean AUM fell by more than half (consistent with withdrawals, which this data cannot confirm); they are left as is.
- **Scale of return_ytd:** plain values are decimals (0.99 = 99%). This is verified, because return_ytd = benchmark_return_ytd + active_alpha_ytd holds on every row within 0.0001.
- **return_ytd converted from percent text:** values were rounded to 2 decimals in the source, so return - benchmark - alpha differs by up to 0.000050 on those 300 rows (tolerance 0.0001).
