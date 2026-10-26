# HW4 Decision Log: Wildcat Capital data cleaning

## Issue 1: Float-style security IDs in transactions

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.security_id` |
| **Evidence** | 197,175 rows store the ID as `45.0` instead of `45`, so they don't match `dim_security` when compared as text. |
| **Dimension violated** | Consistency, Referential Integrity |
| **Decision** | Standardize by stripping the trailing `.0`. |
| **Justification** | It's the same ID with a formatting quirk, so nothing is lost by fixing it. If I left it, about 66% of transactions would fall out of any join to the securities table. |
| **Risk** | Low. After the fix, I'll assert that every non-blank `security_id` exists in `dim_security`. |

---

## Issue 2: Blank security, shares and price on non-trade rows

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.security_id`, `shares`, `price` |
| **Evidence** | 101,597 rows (34.0%) are blank, and every one is an Advisory Fee (35,766), Deposit (35,981) or Withdrawal (29,850). Buy, Sell and Dividend rows have no blanks. |
| **Dimension violated** | None. It looks like missing data, but it comes from how the table is structured. |
| **Decision** | Leave as is. |
| **Justification** | Deposits, withdrawals and fee debits don't involve a security, shares or a price. Filling those in would mean inventing data. |
| **Risk** | Someone averaging price across all rows would get a misleading number. I'll document this in the README so others would know to filter by transaction type. |

---

## Issue 3: Negative shares on Buy transactions

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.shares` |
| **Evidence** | 836 Buy rows have negative shares. In every one, `amount` equals the absolute value of shares times price. All 59,755 Sell rows have positive shares, so a negative sign isn't how sells are recorded. |
| **Dimension violated** | Accuracy/Plausibility, Validity |
| **Decision** | Fix with `abs(shares)` and add a 0/1 flag column for the rows I changed. |
| **Justification** | The stored `amount` confirms the size of the number, so this is a repair I can check against another column, not a guess. |
| **Risk** | If the sign had some meaning I'm missing, I could throw off position totals. That seems unlikely since the amounts match and only Buys are affected. |

---

## Issue 4: Transactions for clients that don't exist

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.client_id` |
| **Evidence** | 200 rows with 200 distinct client IDs (2702 to 3192), none of which appear in `dim_client` (IDs 1 to 2525). They cover all six transaction types. Fees and snapshots have no orphan clients. |
| **Dimension violated** | Referential Integrity |
| **Decision** | Quarantine these rows to a file in `data/audit/` with the reason. |
| **Justification** | I can't create clients or guess whose transactions these are, and keeping them would break client-level reports. |
| **Risk** | If these are real clients that are just missing from the client table, I'm excluding 0.067% of transactions. The quarantine file makes it easy to restore them. |

---

## Issue 5: Percent-formatted returns in snapshots

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot.return_ytd` |
| **Evidence** | 300 values are text like `9.28%`, while every other row is a decimal like `0.0928`. |
| **Dimension violated** | Validity, Consistency |
| **Decision** | Convert by removing the `%` and dividing by 100. |
| **Justification** | The rest of the column uses decimals, so these rows are the same measure written a different way. |
| **Risk** | The percent values appear to be rounded to two decimals, so alpha may not match return minus benchmark exactly on these rows. I'll check the converted values against `benchmark_return_ytd + active_alpha_ytd` and record the result in the cleaning log. |

---

## Issue 6: Full state names in the client table

| Field | Entry |
|---|---|
| **Table / column** | `dim_client.state` |
| **Evidence** | 78 rows use a full name: Pennsylvania 25, Florida 15, New York 14, New Jersey 13, California 5, Illinois 4, Texas 2. The rest use 2-letter codes. |
| **Dimension violated** | Consistency |
| **Decision** | Standardize to 2-letter codes. |
| **Justification** | Each name maps to exactly one code, so there's no guessing involved. If I skipped this, a report by state would split the same state into two groups. |
| **Risk** | Low. I'll assert that every state is two uppercase letters after the fix. |

---

## Issue 7: Missing risk profile

| Field | Entry |
|---|---|
| **Table / column** | `dim_client.risk_profile` |
| **Evidence** | 76 blank values, about 3.0% of the 2,525 clients. The other rows use five valid categories. |
| **Dimension violated** | Completeness |
| **Decision** | Flag with a 0/1 column called `risk_profile_missing`, and don't fill in a value. |
| **Justification** | Risk profile describes how much risk a client is comfortable with. Guessing one could mislead the committee, and no other column gives me a reliable answer. |
| **Risk** | Those clients will be left out of any risk-based analysis unless someone uses the flag. |

---

## Issue 8: Fees and snapshots dated before the client start date

| Field | Entry |
|---|---|
| **Table / column** | `fact_fees.fee_date`, `fact_portfolio_snapshot.snapshot_date` compared with `dim_client.client_since` |
| **Evidence** | 858 fee rows and 930 snapshot rows come before `client_since`. None are more than 30 days early (median 15 days for fees), and fee dates fall on the 1st of the month. |
| **Dimension violated** | None found. I checked for Accuracy/Plausibility. |
| **Decision** | Leave as is. |
| **Justification** | The first monthly fee or snapshot falls in the month the client started, while `client_since` is usually mid-month. That fits month-start billing and doesn't look like an error. |
| **Risk** | If clients were actually billed before they joined, that would be a real problem. The 30-day cap makes the harmless explanation more likely. |

---

## Issue 9: Blank sector and expense ratio in securities

| Field | Entry |
|---|---|
| **Table / column** | `dim_security.sector`, `dim_security.expense_ratio_bps` |
| **Evidence** | `sector` is blank for all 219 non-equity securities (Fixed Income 120, Alternative 58, Cash Equivalent 41) and filled for all 281 Equity ones. `expense_ratio_bps` is blank on 281 securities, and my audit found no ETF without a value. |
| **Dimension violated** | None. It looks like missing data, but it's part of how the table is built. |
| **Decision** | Leave as is. |
| **Justification** | Sector only applies to equities, and expense ratios only apply to ETFs, so a blank here means "not applicable". |
| **Risk** | Low. Someone might read the blanks as missing data, so I'll explain it in the README. |

---

## Issue 10: The text "None" in advisor certifications

| Field | Entry |
|---|---|
| **Table / column** | `dim_advisor.certifications` |
| **Evidence** | The word `None` appears in 6 of the 25 advisor rows. Every other row lists actual certifications (CFA, CFP, CIMA). |
| **Dimension violated** | None. It looks like a null value, but it's a real value meaning the advisor has no certifications. |
| **Decision** | Leave as is. |
| **Justification** | The advisors with `None` have no certifications, which is information we want to keep. Turning it into a blank would make it look like missing data. |
| **Risk** | Some tools read the text "None" as null by default, so I'll read every file as text and note this in the README. |

---

## Issue 11: Extreme year-to-date returns in snapshots

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot.return_ytd` (and `active_alpha_ytd`) |
| **Evidence** | 472 rows (68 clients) have return_ytd above 2.0, up to 94.67 (about 9,467%). That is 471 plain decimals plus 1 percent row after conversion. In every one of the 10,855 client-years with at least 6 snapshots, aum / (1 + return_ytd) gives the same start-of-year AUM, so return_ytd is AUM growth since the start of the year. On these rows the implied start-of-year AUM has a median of about 1,049, compared with about 465,167 across all rows. 420 snapshot rows (92 clients) have AUM of exactly 1000.00. |
| **Dimension violated** | Accuracy/Plausibility |
| **Decision** | Leave the values as is and add a 0/1 flag column, `return_ytd_extreme`, for return_ytd above 2.0. Negative returns (minimum -0.994) are not flagged. |
| **Justification** | return_ytd equals benchmark_return_ytd plus active_alpha_ytd on every row, which also shows the plain values are decimals, not percents. I can't recompute a true investment return without knowing when deposits and withdrawals happened, so changing the values would mean inventing data. Negative values look plausible as AUM changes. |
| **Risk** | Averages of return_ytd and alpha will be skewed by these rows. Users should use the flag or medians. A threshold of 2.0 is a judgment call. |

---

## Issue 12: Scientific notation in snapshot returns

| Field | Entry |
|---|---|
| **Table / column** | `fact_portfolio_snapshot.return_ytd` and `active_alpha_ytd` |
| **Evidence** | 135 return_ytd values and 756 active_alpha_ytd values are written like `9.9e-05`, while the rest of each column uses plain decimals like `0.019504`. All of them are smaller than 0.0001 in absolute value. Converting them to plain decimals gives exactly the same numbers (I checked every cell). |
| **Dimension violated** | Consistency, Validity |
| **Decision** | Standardize to plain decimals (`9.9e-05` becomes `0.000099`). |
| **Justification** | It's the same value written two ways, so nothing is lost. A strict parser or BI tool can read the scientific-notation values as text instead of numbers. |
| **Risk** | Low. After the fix I check that every converted value equals the original numerically and that none remain. |

---

## Issue 13: Buy and Sell transactions dated on weekends

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions.txn_date` (Buy and Sell rows) against `dim_date.is_trading_day` |
| **Evidence** | 40,649 of 143,311 Buy and Sell rows (28.4%) fall on a non-trading day. Transactions are spread almost evenly over all seven days of the week. In `dim_date`, every weekday is marked as a trading day, so the non-trading days are only weekends. |
| **Dimension violated** | Accuracy/Plausibility |
| **Decision** | Leave as is. |
| **Justification** | Real trades don't settle on weekends, but I can't recover the true trade dates from other columns. Moving the dates would mean inventing data. |
| **Risk** | Any analysis that depends on the trading calendar, such as settlement timing, would be wrong. I'll document this in the README. |

---

## Issue 14: Advisory Fee debits do not match the fees table

| Field | Entry |
|---|---|
| **Table / column** | `fact_transactions` (txn_type = Advisory Fee) against `fact_fees` (fee_type = Advisory) |
| **Evidence** | There are 35,766 Advisory Fee debits and 32,370 Advisory fee rows. Only 7,653 client-months have both, and in none of them do the monthly totals match to the cent. The debits are a median of 3.11 times the fees, and total about 263.8 million versus 53.6 million. |
| **Dimension violated** | Accuracy, Consistency |
| **Decision** | Leave as is. |
| **Justification** | I can't tell which table is right, and no column lets me reconcile them. The fee amounts themselves do follow the fee formula (AUM × bps / 10000 / 12), so I'd treat `fact_fees` as the fee source. |
| **Risk** | Using the debits instead of the fees would overstate fee revenue by roughly a factor of five. |