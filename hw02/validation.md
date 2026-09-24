# HW02 Validation — Wildcat Capital Transaction Portfolio

## 2A — Known-Answer Benchmarks

| Check | Expected | Your Script Produced | Match? | Notes |
|---|---|---|---|---|
| Dataset shape | (298772, 9) | (298772, 9) | Yes | |
| Null count — `security_id` | 101,597 | 101,597 | Yes | |
| Null count — `amount` | 0 | 0 | Yes | |
| Unique `txn_type` values | 6 | 6 | Yes | |
| Count of `Buy` transactions | 83,556 | 83,556 | Yes | |
| `txn_date` data type | object | str | Yes | Pandas 2.x/3.x displays the default string dtype as `str` instead of the older `object` label. Still a text column, not a real date type — same conceptual answer, just a newer pandas display convention. |
| Earliest `txn_date` | 2020-01-01 | 2020-01-01 | Yes | |
| Latest `txn_date` | 2024-12-30 | 2024-12-30 | Yes | |
| Duplicate `txn_id` count | 0 | 0 | Yes | |
| Mean `amount` | $54,075.17 | $54,075.17 | Yes | |
| Median `amount` | $41,220.48 | $41,220.49 | Off by $0.01 | Floating-point rounding difference: `describe()`'s internal rounding and Python's `:.2f` string formatting round a borderline value (~41220.485) in slightly different directions. Same underlying value, not a calculation error. |
| Skewness of `amount` | 1.15 | 1.15 | Yes | |
| Correlation `shares`–`amount` | 0.65 | 0.65 | Yes | |
| Correlation `price`–`amount` | 0.64 | 0.64 | Yes | |
| Correlation `shares`–`price` | 0.00 | 0.00 | Yes | |
| Negative `shares` count (Buy only) | 836 | 836 | Yes | Confirmed all 836 negative-share rows are `Buy` transactions — every other type shows 0 negative-share rows in the by-type breakdown. |
| Profile file created | Yes | Yes | Yes | `hw02/hw02_profile.txt` |
| Chart files created (3) | Yes | Yes | Yes | `hist_amount.png`, `box_amount_by_type.png`, `scatter_shares_amount.png` — all present in `hw02/charts/` |

---

## 2B — Explain the Code and Output

*(Completed in a new, separate Claude Cowork session using the two required prompts.)*

1. Did Claude's predicted outputs (from Prompt 1) match what you actually saw in the terminal? List any discrepancies.

   Structurally, yes. Claude correctly predicted the section-by-section format, labels, and computations for every one of the 17 items without ever seeing my actual data. The one thing it couldn't predict, by its own admission, was the real numbers - it hadn't been given `fact_transactions.csv`, so it filled in placeholders (`$X,XXX.XX`, `N,NNN`, etc.) instead of actual values. When I compared its placeholder structure against my real terminal output, every section lined up correctly: no structural discrepancies, just placeholders vs. real numbers as expected.

2. What did Claude flag as potentially unexpected or worth investigating (from Prompt 2)?

   Five things: (1) 836 `Buy` transactions with negative `shares` values, which it called "the biggest thing I'd chase down before running further analysis"; (2) the large gap between Advisory Fee's mean ($7,375) and median ($859), an 8.6x difference suggesting a handful of unusually large fee events; (3) `txn_date` being stored as a string rather than a real datetime, which could cause chronological sorting/filtering to behave unexpectedly later; (4) `security_id`, `shares`, and `price` being stored as `float64` instead of integer types, a side effect of having NaNs in those columns, which could cause silent join failures against integer-keyed tables; and (5) a cosmetic matplotlib deprecation warning tied to the `boxplot()` fallback logic, which it noted doesn't affect the actual output.

3. Did Claude mention the 101,597 null values in `security_id`? What explanation did it give?

   Yes. It pointed out that the null counts in `security_id`, `shares`, and `price` are all exactly 101,597, and that this number equals the combined count of Deposit (35,981) + Withdrawal (29,850) + Advisory Fee (35,766) transactions from the `txn_type` breakdown. Its explanation: those three transaction types aren't security trades, so they have no associated security, share count, or price - meaning the missingness is structural and expected by design, not a data quality problem, though it recommended confirming that's intentional before imputing or dropping those rows.

4. Did Claude flag the `txn_date` column as a concern? Why would that matter for a time-series analysis?

   Yes. It flagged that `txn_date` is stored as a string and never actually converted to a real date type within the DataFrame itself (the script only parses a temporary copy to compute min/max). It explained that this matters because date comparisons on strings sort lexicographically rather than chronologically, which happens to work correctly for `YYYY-MM-DD` formatted strings, but is fragile and would break for any other date format or for date arithmetic (like computing days between transactions), which requires the column to be converted to `datetime` first.

5. Open your three chart files. Does what you see in each image match Claude's explanation of that section of the output? Note any differences.

   Mostly yes. The histogram matches exactly: mean sits to the right of the median with visible right skew, consistent with the 1.15 skewness value. The box plot is ordered by median, as predicted, though the actual vertical order in the image runs ascending from top to bottom rather than descending. The scatter plot does color by `txn_type` with semi-transparent points as described, but in practice the sheer number of `Buy` points (83,556) visually dominates the plot and makes the other five categories hard to distinguish. Claude's explanation described the mechanism correctly, but didn't anticipate how much overlap would obscure the other categories in practice.

6. Paste one follow-up question you asked Claude, and Claude's answer.

   **My question:** "Should I treat the negative-share Buy transactions as errors or legitimate reversals, and how would I tell the difference?"
   
   **Claude's answer:** Claude explained there's no single field that settles it definitively, but laid out five diagnostics to build a case either way: (1) check whether `amount` carries the same sign as `shares` — in this dataset `amount`'s minimum is $13.33 (always positive) even though `shares` goes as low as −499.63, which is inconsistent with how a true reversal would flow through the books (money moving back out would show as a negative amount too); (2) group by `client_id` + `security_id` and look for a same-magnitude positive Buy near in time to each negative row — a real reversal should have a paired offsetting transaction; (3) check whether a dedicated "Correction"/"Reversal" `txn_type` exists — it doesn't, only Buy, Sell, Dividend, Deposit, Advisory Fee, Withdrawal, which is a mild point against "legitimate"; (4) check whether the negative values mirror the shape of the positive Buy distribution, since a clean mirror-image pattern looks more like a systematic sign bug than organic reversal events; (5) check whether the negative rows are randomly scattered across clients/advisors/dates (pointing to a data/import artifact) versus clustered (pointing to a real operational event). Claude's overall read: the positive-`amount`-with-negative-`shares` pattern is the most telling signal, and a suspiciously round ~1% of Buy rows (836 of 83,556) affected leans toward a systematic data issue rather than legitimate reversals — though it recommended running the pairing check (#2) against the actual data before concluding.

---

## 2C — Business Check & Cross-Validation

**Business-reasonableness questions** *(answer in your own words — do not paste Claude's response as your answer here)*

1. `security_id`, `shares`, and `price` are all null in exactly 101,597 rows. Looking at the `txn_type` value counts, which three transaction types would you expect to have no security — and why? Do the counts add up to 101,597?

   *The three transaction types that would have no security involved are Deposit. Advisory Fee, and Withdrawal. This is because these do not involve trading a specific stock or bond, rather it is just cash moving in and out of the account. There are 35,981 data points of Deposit, 35,766 data points of Advisory Fee, and 29,850 data points of Withdrawal, which ultimately add up to 101,597.*

2. There are 83,556 Buy transactions and 59,755 Sell transactions. What does it mean for a wealth management firm to have significantly more Buys than Sells over a five-year period?

   *This means the firm's AUM is likely growing over the five-year period, since more shares are being purchased than sold off. This is consistent with new client inflows and dividend reinvestment, rather than a wave of withdrawals or clients pulling out.*

3. The `txn_date` column is stored as a string (type `object`/`str`) rather than a date. If Claude Cowork generated code to compute the average number of days between transactions, what would go wrong if the dates remained as strings?

   *If the data remained as strings, python would not be able to make any calculations because it is considered text instead of a number and would just return an error.*

4. Wildcat Capital has 2,700 clients served by 25 advisors. Is that ratio — roughly 108 clients per advisor — plausible for a registered investment advisory firm?

   *After some research online, I have established that the average client-advisor ratio at registered investment advisory firms hovers around 100. This would imply that Wildcat Capital's ratio is relatively plausible.*

5. 836 `Buy` transactions have negative `shares` values (as low as −499.63), while every other transaction type in the dataset has only positive share values. What are two plausible business explanations for a negative share count on a Buy transaction, and what would you do next to determine which explanation is more likely?

   *Two plausible business explanations for a negative share count are a reversal or correction of a previous purchase, or a different accounting convention for certain accounts or sources. I’d check for matching positive Buys or patterns by broker to distinguish reversals from different sign conventions.*

**Cross-validation**

- **Prompt A:** *"Write Python to count rows in fact_transactions.csv where txn_type equals exactly 'Buy'."*
- **Prompt B:** *"Write Python to count the total rows in fact_transactions.csv, then subtract the count of rows where txn_type is Sell, Deposit, Withdrawal, Dividend, or Advisory Fee."*

6. What did each script return?

   *83,556 from both. Prompt A via direct filtering, Prompt B via total minus the other five types.*

7. Do the results agree? If not, which one is wrong and why?

   *Yes, they agree exactly.*

8. Why is it useful to verify a count using subtraction rather than direct filtering?

   *Verifying with subtraction is useful because it forces you to account for every row, not just the rows that match one specific filter. If there were a typo or stray space in txn_type that a direct filter for "Buy" would silently miss, the subtraction method would catch it. A direct filter alone can only tell you what it found, not what it might be missing.*
