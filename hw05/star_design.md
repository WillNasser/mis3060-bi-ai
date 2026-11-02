# HW5: Star Schema Design — Wildcat Capital

All evidence below comes from `check_star.py` (run `python check_star.py` from this folder).

## Part A — Keys

| Table | Type | Primary key | Foreign keys (column → table[column]) |
|---|---|---|---|
| dim_advisor | Dimension | `advisor_id` | — |
| dim_benchmark | Dimension | `benchmark_id` | — |
| dim_client | Dimension | `client_id` | `advisor_id` → dim_advisor[advisor_id] |
| dim_date | Dimension | `date` (`date_id` is also unique, but the facts match on `date`) | — |
| dim_security | Dimension | `security_id` | `benchmark_id` → dim_benchmark[benchmark_id] |
| fact_fees | Fact | `fee_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`fee_date` → dim_date[date] |
| fact_portfolio_snapshot | Fact | `snapshot_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`benchmark_id` → dim_benchmark[benchmark_id]<br>`snapshot_date` → dim_date[date] |
| fact_transactions | Fact | `txn_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`security_id` → dim_security[security_id] (can be blank)<br>`txn_date` → dim_date[date] |

**Blank keys:** `fact_transactions[security_id]` is blank on 101,528 rows. These are the cash rows: Deposit (35,956), Withdrawal (29,830) and Advisory Fee (35,742) add up to exactly 101,528. They are not trades, so there is no security to point to. Every other foreign key is never blank.

**Integrity proof (check_star.py):** every primary key is unique and never blank, and every non-blank foreign key exists in its parent table (0 orphans in all 13 foreign keys).

## Part B — Grain

- **fact_transactions:** One row represents one transaction (a buy, sell, dividend, deposit, withdrawal or advisory fee debit) for one client on one date. `txn_id` is unique.
- **fact_fees:** One row represents one fee charge of a single fee type billed to one client on the first day of one month. (`client_id`, `fee_date`) is unique.
- **fact_portfolio_snapshot:** One row represents one client's account snapshot (AUM, returns and cash percentage) as of the first day of one month. (`client_id`, `snapshot_date`) is unique.

## Part C — Measures

Test used for every column: if I add this value across clients, across months, and across both, what does the total represent?

### fact_fees

| Column | Classification | How it may be summed or averaged |
|---|---|---|
| `amount` | Additive | Dollars of fee charged. It can be summed across clients, months, fee types and advisors to give total fees collected. |
| `aum_basis` | Semi-additive | A balance at one point in time. It can be summed across clients within a single month (total AUM) but not across months, because that counts the same money again each month. Across months use the average or the latest value. |
| `bps_charged` | Non-additive | A rate in basis points. It is never summed; it may be averaged only if weighted by `aum_basis`. |

### fact_portfolio_snapshot

| Column | Classification | How it may be summed or averaged |
|---|---|---|
| `aum` | Semi-additive | A balance at the start of the month. It can be summed across clients within one month but not across months; across months use the average or the latest value. |
| `return_ytd` | Non-additive | A percentage return. It cannot be added across clients or months; average it weighted by `aum`. |
| `benchmark_return_ytd` | Non-additive | A percentage return for the benchmark. It cannot be added across any dimension. |
| `active_alpha_ytd` | Non-additive | The difference between two rates (`return_ytd` minus `benchmark_return_ytd`), so it cannot be added. |
| `cash_pct` | Non-additive | The share of the portfolio held in cash. Percentages are not added; weight by `aum` to combine them. |

### fact_transactions

| Column | Classification | How it may be summed or averaged |
|---|---|---|
| `amount` | Additive | Dollars. It can be summed across clients, dates, securities and advisors. It is positive for every transaction type (money in and money out alike), so always group or filter by `txn_type` first; a total across all types mixes inflows with outflows. |
| `shares` | Additive | A quantity traded (a flow, not a balance), so it sums across clients and months. It is only meaningful within a single security, since shares of different securities are different units. Blank on cash rows. |
| `price` | Non-additive | A price per share. It cannot be added; average it weighted by `shares`. Blank on cash rows. |

### Numeric columns that are not measures

- **Keys:** `fee_id`, `snapshot_id`, `txn_id`, and the foreign keys `client_id`, `advisor_id`, `benchmark_id`, `security_id` on the fact tables
- **Date parts:** `year` and `month` on `fact_portfolio_snapshot`
- **Flags:** `is_return_suspect` (`fact_portfolio_snapshot`) and `is_post_departure_txn` (`fact_transactions`)

### Numeric attributes in the dimension tables that should never be summed

| Column | Table | Reason |
|---|---|---|
| `age` | dim_client | A property of a person; use the average or a range. |
| `zip_code` | dim_client | A label made of digits. |
| `initial_aum` | dim_client | The balance at sign-up, a fixed client attribute. It looks like AUM but is not current; use `fact_portfolio_snapshot[aum]`. |
| `years_experience` | dim_advisor | A property of an advisor; use the average or max. |
| `aum_target_mm` | dim_advisor | A per-advisor target in millions of dollars; a sum has no meaning on its own. |
| `expense_ratio_bps` | dim_security | A rate, so non-additive. |
| `year`, `quarter`, `month`, `week_of_year` | dim_date | Calendar labels, not amounts. |
| `is_month_end`, `is_quarter_end`, `is_year_end`, `is_trading_day` | dim_date | 0/1 flags used for filtering. |

The `*_id` columns in the dimensions are keys, so they are also not measures.

## Part E — Relationships and design questions

**(a) Blank `security_id` on transactions.** 101,528 of the 298,572 transaction rows have no `security_id`. These are the cash rows: Deposits (35,956), Withdrawals (29,830) and Advisory Fee debits (35,742) add up to exactly that number. Money moving in or out of an account, or a fee being charged, does not involve buying or selling any security, so there is no security to point to. This is not a defect. A key is only blank where the row has nothing to relate to, and every one of the 196,990 rows that do have a `security_id` matches a real security (0 orphans). In Power BI the relationship still works: the blank rows appear as a `(Blank)` row when grouping by a `dim_security` column, and that row is the cash activity. Filling the blanks with an invented security, or deleting those rows, would hide real cash flows and break the row count.

**(b) `advisor_id` on `dim_client` and all three facts.** I kept the three direct relationships active: `fact_transactions`, `fact_fees` and `fact_portfolio_snapshot` each connect to `dim_advisor[advisor_id]`. I did not create `dim_client[advisor_id] → dim_advisor`. Power BI allows only one active path between two tables, and if `dim_client` also linked to `dim_advisor`, each fact table could reach the advisor two ways, directly and through the client. Power BI would then have to make one of them inactive, and when I let it auto-detect, it deactivated the `client_id` relationships, which would have stopped client attributes like risk profile from filtering the facts. I checked that every fact row's `advisor_id` matches that client's advisor, so the direct link gives the same answer as going through the client and no information is lost. Keeping the direct relationships also keeps the model a plain star. A slicer on `dim_advisor` filters all three fact tables.

**(c) Joining to the date dimension.** I joined on `dim_date[date]`, not `dim_date[date_id]`. The facts store real calendar dates (`txn_date`, `fee_date` and `snapshot_date`), and those values match `dim_date[date]` exactly. The `date_id` is just a running number (1 to 1,827) that none of the fact tables contain, so joining on it would match nothing, or silently wrong rows, and the date slicer would show `(Blank)`. `date` is also unique in `dim_date`, which a Many-to-one relationship needs, and it is the column I marked as the date table, which time-intelligence functions require. I checked that every fact date exists in `dim_date` (0 orphans in all three relationships).

**(d) Star or snowflake.** Two foreign keys connect one dimension to another: `dim_client[advisor_id] → dim_advisor` and `dim_security[benchmark_id] → dim_benchmark`. I did not keep either as a relationship, so every dimension connects only to the fact tables and the model is a star. For the advisor link, a second path to `dim_advisor` would conflict with the direct fact relationships (see b). For the benchmark link, `fact_portfolio_snapshot` already connects directly to `dim_benchmark`, and the transactions table reaches securities through `dim_security`, so a security-to-benchmark link would create a snowflake branch that no visual needs. The `advisor_id` and `benchmark_id` columns are still in those dimension tables, so nothing is lost; the information is just not wired as a relationship.

**Conformed dimensions.** `dim_client`, `dim_advisor` and `dim_date` are conformed: each connects to all three fact tables, so one slicer on any of them filters transactions, fees and snapshots at the same time. `dim_security` connects only to `fact_transactions` and `dim_benchmark` only to `fact_portfolio_snapshot`, because only those facts have those keys.

## Part F — Reflection

1. **Transactions:** *What was net client cash flow (deposits minus withdrawals) each quarter, by advisor?* **Not answerable in one visual without DAX.** `amount` is positive for both deposits and withdrawals, so summing it by quarter adds money in to money out. The fix in the schema: add a signed amount to `fact_transactions` (positive for deposits, negative for withdrawals, buys and fees as appropriate), or a direction column of +1 and -1, so a plain sum gives net flow.
2. **Fees:** *How much fee revenue did we earn each year, by fee type?* **Answerable in one visual.** A column chart with `dim_date[year]` on the axis, `fee_type` as the legend and the sum of `fact_fees[amount]` as the value. `amount` is additive, so the default sum is correct.
3. **Snapshots:** *What was total AUM at the start of each month, by advisor?* **Answerable in one visual.** A line chart with month on the axis, `dim_advisor` as the legend and the sum of `aum`. Each month holds one snapshot per client, so the sum across clients is correct. Rolling this up to a year would add twelve months of the same balances together, so a yearly total would need DAX or an extra filter.
