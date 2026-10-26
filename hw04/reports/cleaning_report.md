# Wildcat Capital: Data Cleaning Report

**For:** Portfolio Committee · **Prepared by:** Will Nasser · **Date:** 2026-10-26

## Executive summary

We audited the eight Wildcat Capital tables (555,401 rows) and cleaned them without touching the raw files. Seven kinds of defect were found and repaired or flagged: IDs stored as `45.0`, 200 transactions for clients that do not exist, 835 trades with negative share counts, returns written as percent text or in scientific notation, state names written out in full, and blank risk profiles. After cleaning, every table is 100% type-valid and every foreign key joins. Two problems cannot be fixed from the data and are documented instead: 28.4% of Buy and Sell trades are dated on weekends, and the Advisory Fee debits in the transaction table do not match the fee table. Use `fact_fees` for fee revenue and do not rely on transaction dates for trading-calendar analysis.

## What changed

| Issue | Rows | Action | Result |
|---|---:|---|---|
| `security_id` stored as `45.0` | 197,044 | Standardised to `45` | Transaction-to-security match 0% to 100% |
| Transactions for clients not in `dim_client` | 200 | Quarantined (saved as received) | Client match 99.933% to 100% |
| Negative shares on Buy | 835 | Sign corrected, flag added | `amount = shares x price` holds to the cent on all rows |
| `return_ytd` written as percent text | 300 | Converted (9.28% to 0.0928) | Reconciles to benchmark + alpha |
| Scientific notation (`9.9e-05`) | 891 | Rewritten as plain decimals | Values exactly equal |
| State written as full name | 78 | Converted to 2-letter code | All 20 states valid |
| `risk_profile` blank | 76 | Flagged, not filled | 3.01% of clients |
| `return_ytd` above 200% | 472 | Flagged, values unchanged | See judgment calls |

Cleaning changed 199,148 cells in total; each one is in `data/audit/value_changes.csv`. Raw rows equal clean rows plus quarantined rows for every table (fact_transactions: 298,772 = 298,572 + 200).

Left as is, with reasons in the decision log: blank `security_id`, `shares` and `price` on Deposit, Withdrawal and Advisory Fee rows (101,528 rows, no security is involved); blank `sector` on non-equities (219) and blank `expense_ratio_bps` on non-ETFs (281); the text "None" in advisor certifications (6, meaning no certification); and 858 fees and 930 snapshots dated up to 30 days before `client_since`, always on the 1st of a month.

## Scorecard, raw vs clean

| Table / measure | Raw | Clean |
|---|---:|---:|
| fact_transactions, type validity | 90.545% | 100% |
| fact_transactions, referential match | 81.95% | 100% |
| fact_portfolio_snapshot, type validity | 99.923% | 100% |
| dim_client, rule pass | 99.742% | 100% |
| fact_portfolio_snapshot, rule pass | 99.964% | 99.964% |

The raw transaction match of 81.95% pools all relationships; the real break was one of them, `security_id`, which matched 0% as delivered. The snapshot rule pass stays at 99.964% on purpose: the 472 extreme returns fail the 200% plausibility rule and are flagged, not changed. The small rise in `dim_client` completeness (99.785% to 99.799%) comes from the added flag column; the 76 blank risk profiles are still blank.

## Key judgment calls

1. **Quarantine the 200 orphan transactions instead of deleting or guessing.** They belong to 200 client IDs (2702 to 3192) that are not in `dim_client`, 0.07% of transactions. We cannot invent clients, and dropping rows silently would hide the problem. Risk: if those clients exist in another system, their activity is missing from analysis. Mitigation: the rows are saved exactly as received in `quarantine_fact_transactions_orphan_client.csv` and can be restored.
2. **Flag, do not fill, the 76 blank risk profiles.** Risk profile cannot be inferred from other columns, and a guess would put a client in the wrong suitability bucket. Risk: any analysis by risk profile leaves out 3.01% of clients unless it handles the flag `risk_profile_missing`.
3. **Flag the 472 returns above 200%, leave the values alone.** They come from 68 clients, with a maximum of 94.67 (9,467%). Return reconciles with benchmark + alpha on every row, so the scale is not the problem. In all 10,855 client-years the return implies one fixed start-of-year balance, so `return_ytd` measures balance growth including deposits, not investment performance. On the flagged rows that implied start balance has a median of 1,048, against 465,167 across all rows, and 420 snapshot rows have a balance of exactly 1,000.00. Risk: averages of `return_ytd` and `active_alpha_ytd` are skewed; use the flag or medians, and do not present this column as a time-weighted return.
4. **Correct the sign on 835 negative share counts.** All were Buy rows, and `amount = |shares| x price` holds to the cent on each, so the sign was the defect. Risk: a negative sign could in principle mean a reversal; the flag `shares_sign_fixed` marks every changed row so it can be reviewed.

## Limitations

- **Weekend trades.** 40,649 of 143,311 raw Buy/Sell rows (28.4%) fall on a weekend, spread evenly over all seven days of the week. The true dates cannot be recovered, so they are unchanged. Do not use them for settlement or trading-calendar work.
- **Advisory Fee debits do not reconcile to fees.** None of 7,653 client-months match to the cent; the debits are a median 3.11 times the fees (about 263.7 million vs 53.6 million in total). `fact_fees` follows its fee formula exactly (balance x bps / 10,000 / 12), the debits have no such rule here. We used `fact_fees` for fee revenue; the data owner should explain what the debits represent.
- **Outlier flags are not errors.** The IQR rule flags about 10% of snapshot AUM values (13,261 rows above the fence). In skewed money data, large values are often legitimate. Flagged means unusual, not wrong.
- **Rules can only confirm what we expected.** The allowed lists and bounds come from the business description and the data; there is no independent source of truth here, and `active_alpha_ytd` has no bound rule.

---
AI-assisted report — reviewed for factual accuracy on 2026-10-26 by Will Nasser
