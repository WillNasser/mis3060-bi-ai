#!/usr/bin/env python
"""
HW4 Part D - 03_validate.py
Validation of the eight Wildcat Capital tables, run on BOTH stages (raw and clean).

Contains
  * check_referential_integrity()  ONE reusable function (keep it for Assignment 5)
  * RELATIONSHIPS                  the 10 ID-based + 3 date-based relationships
  * RULES                          rule-based checks (ranges, allowed codes, sign rules, formats)
  * RECONCILIATIONS                cross-column / cross-table checks (recomputed vs stored values)
  * IQR outlier flags              on columns with no natural bound
  * data_quality_scorecard.csv     one row per table per stage

Definitions used in the scorecard (all percentages, 0-100)
  completeness      non-blank cells / cells that must be filled. A cell is only "required" when it
                    applies: security_id/shares/price only on Buy/Sell/Dividend rows, sector only for
                    Equity, expense_ratio_bps only for ETFs (see REQUIRED_IF).
  key_uniqueness    rows whose key is non-blank and appears only once (ALL copies of a duplicated key fail).
                    Keys checked: the first column of every table, plus dim_date.date (three relationships join on it).
  type_validity     non-blank cells that are valid for their declared type in SCHEMA. The check is
                    strict: 45.0 is not a valid int, 9.28% is not a valid number.
  rule_pass         rule evaluations that pass. Blank and unparseable values are not evaluated
                    (completeness and type_validity already count them).
  referential_match non-null foreign keys found in the parent table (strict, exact text match, no trimming),
                    POOLED over all of the table's relationships. referential_worst_pct / _relationship show the
                    weakest single relationship, so one broken link cannot hide inside the pool. Tables that are
                    never a child in a relationship are left blank.
Rows that a check cannot evaluate (blank, unparseable, condition not met, parent missing) are never silently
dropped: rule_results.csv and reconciliations.csv carry rows_not_evaluated / rows_skipped for every check.
Allowed lists and bounds in RULES were chosen from the business description and what the data showed; they can
confirm the data against that description, they are not an independent source of truth.

Run from the project root:  python scripts/03_validate.py
Outputs (reports/): data_quality_scorecard.csv, ri_results.csv, rule_results.csv,
                    reconciliations.csv, outlier_flags.csv, outlier_rows.csv
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def find_raw():
    """Raw tables: hw04/data/raw if it exists, else Data/raw (older layout), else Data/raw next to hw04."""
    for p in (ROOT / "data" / "raw", ROOT / "Data" / "raw", ROOT.parent / "Data" / "raw"):
        if p.is_dir():
            return p
    return ROOT / "data" / "raw"


TABLES = ["dim_advisor", "dim_client", "dim_date", "dim_security", "dim_benchmark",
          "fact_fees", "fact_portfolio_snapshot", "fact_transactions"]
TRADE_TYPES = ["Buy", "Sell", "Dividend"]
KNOWN_TXN_TYPES = ["Buy", "Sell", "Dividend", "Deposit", "Withdrawal", "Advisory Fee"]
STATE_CODES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
                  "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())


def check(cond, msg):
    if not bool(cond):
        raise RuntimeError(f"CHECK FAILED: {msg}")


# ----------------------------------------------------------------- helpers
def _txt(s):
    """Text view of a column: trimmed, missing stays missing."""
    return s.astype("string").str.strip()


def _b(x):
    """Boolean Series with missing treated as False."""
    return x.fillna(False).astype(bool)


def _blank(s):
    t = _txt(s)
    return _b(t.isna() | t.eq(""))


def _num(s):
    return pd.to_numeric(_txt(s), errors="coerce").astype("float64")


def _num_pct(s):
    """Percent-aware parse (9.28% -> 0.0928); used only where the identity being tested is the point."""
    t = _txt(s)
    pct = _b(t.str.endswith("%"))
    v = pd.to_numeric(t.str.rstrip("%"), errors="coerce")
    return v.where(~pct, v / 100)


def _date(s):
    return pd.to_datetime(_txt(s), format="%Y-%m-%d", errors="coerce")


def read_tables(folder):
    return {t: pd.read_csv(Path(folder) / f"{t}.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
            for t in TABLES}


# =========================================================================
# PART D.1  The reusable referential-integrity function
# =========================================================================
def check_referential_integrity(fact_df, fact_key, dim_df, dim_key, normalize=False):
    """Does every non-blank value of fact_df[fact_key] exist in dim_df[dim_key]?

    Self-contained (needs only pandas): copy this one function into Assignment 5.

    Matching is EXACT text equality, as a BI tool would join it: " 5" does not match "5", "007" does
    not match "7", and a float-typed key column ("5.0") does not match an integer key ("5").
    normalize=True is a diagnostic only: it trims spaces and drops a trailing '.0' from numeric-looking
    keys on both sides (45.0 == 45), but leaves text such as "v1.0" alone.
    A blank key is an empty or whitespace-only text or a missing value. Single-column keys only,
    case-sensitive.

    Returns a dict:
      n_rows, null_key_rows, null_key_rate     fact rows with a blank / missing key and their share of all rows
      non_null_rows, matched_rows, match_rate  match_rate = matched / non-null keys (1.0 = perfect);
                                               NaN when there is no non-null key at all (nothing was tested)
      orphan_row_count, orphan_rows            fact rows whose non-null key is missing from the dimension
      distinct_orphan_keys, orphan_key_examples
      dim_rows, dim_null_key_rows              parent table: its size and its blank keys
      dim_duplicate_key_rows, dim_key_unique   parent rows whose key appears more than once; True when 0
                                               (a duplicated parent key makes every join multiply rows)
    Rates are fractions between 0 and 1.
    """
    for df_, col_, nm in ((fact_df, fact_key, "fact_df"), (dim_df, dim_key, "dim_df")):
        if col_ not in df_.columns:
            raise ValueError(f"{nm} has no column '{col_}' (columns: {list(df_.columns)})")

    def prep(s):
        t = s.astype("string")
        if normalize:
            t = t.str.strip().str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True)
        return t

    def blank(t):
        return (t.isna() | t.str.strip().eq("")).fillna(False).astype(bool)

    f, d = prep(fact_df[fact_key]), prep(dim_df[dim_key])
    null, d_null = blank(f), blank(d)
    d_ok = d[~d_null]
    dim_keys = set(d_ok)
    matched = f.isin(dim_keys).fillna(False).astype(bool) & ~null
    orphan = ~null & ~matched
    n, nn = len(fact_df), int((~null).sum())
    dup_rows = int(d_ok.duplicated(keep=False).sum())
    return dict(
        n_rows=n, null_key_rows=int(null.sum()), null_key_rate=(null.sum() / n) if n else float("nan"),
        non_null_rows=nn, matched_rows=int(matched.sum()),
        match_rate=(matched.sum() / nn) if nn else float("nan"),
        orphan_row_count=int(orphan.sum()), orphan_rows=fact_df[orphan],
        distinct_orphan_keys=int(f[orphan].nunique()),
        orphan_key_examples=" | ".join(map(str, f[orphan].drop_duplicates().head(3))),
        dim_rows=len(dim_df), dim_null_key_rows=int(d_null.sum()),
        dim_duplicate_key_rows=dup_rows, dim_key_unique=(dup_rows == 0))


def selftest_ri():
    fact = pd.DataFrame({"k": ["1", "2", "2", "x", None, "", "2.0"]})
    dim = pd.DataFrame({"id": ["1", "2"]})
    r = check_referential_integrity(fact, "k", dim, "id")
    check(r["n_rows"] == 7 and r["null_key_rows"] == 2 and r["non_null_rows"] == 5, "RI selftest: null counts")
    check(r["matched_rows"] == 3 and r["orphan_row_count"] == 2 and r["distinct_orphan_keys"] == 2, "RI selftest: strict")
    r2 = check_referential_integrity(fact, "k", dim, "id", normalize=True)
    check(r2["matched_rows"] == 4 and r2["orphan_row_count"] == 1, "RI selftest: normalize")
    check(abs(r["match_rate"] - 0.6) < 1e-9 and abs(r["null_key_rate"] - 2 / 7) < 1e-9, "RI selftest: rates")
    check(r["dim_key_unique"] and r["dim_duplicate_key_rows"] == 0 and r["dim_rows"] == 2, "RI selftest: clean parent")
    # exact matching: spaces and zero padding do not match
    r3 = check_referential_integrity(pd.DataFrame({"k": [" 1 ", "007"]}), "k", pd.DataFrame({"id": ["1", "7"]}), "id")
    check(r3["matched_rows"] == 0 and r3["orphan_row_count"] == 2, "RI selftest: whitespace / zero padding must not match")
    # duplicate and blank parent keys are reported, not hidden
    r4 = check_referential_integrity(fact, "k", pd.DataFrame({"id": ["1", "1", "2", ""]}), "id")
    check(r4["matched_rows"] == 3 and r4["dim_duplicate_key_rows"] == 2 and not r4["dim_key_unique"]
          and r4["dim_null_key_rows"] == 1, "RI selftest: duplicate / blank parent keys")
    # empty child and all-blank child: nothing was tested, so no 100%
    r5 = check_referential_integrity(fact.iloc[0:0], "k", dim, "id")
    r6 = check_referential_integrity(pd.DataFrame({"k": ["", None]}), "k", dim, "id")
    check(np.isnan(r5["match_rate"]) and np.isnan(r6["match_rate"]) and r6["null_key_rows"] == 2, "RI selftest: empty child")
    # normalize only touches numeric-looking keys
    r7 = check_referential_integrity(pd.DataFrame({"k": ["v1.0", "45.0"]}), "k", pd.DataFrame({"id": ["v1", "45"]}), "id",
                                     normalize=True)
    check(r7["matched_rows"] == 1 and r7["orphan_row_count"] == 1, "RI selftest: normalize must not touch 'v1.0'")
    try:
        check_referential_integrity(fact, "nope", dim, "id")
        raise RuntimeError("missing column was not reported")
    except ValueError:
        pass


# (fact table, fact column, dimension table, dimension column) : 10 ID-based + 3 date-based
RELATIONSHIPS = [
    ("dim_client", "advisor_id", "dim_advisor", "advisor_id"),
    ("dim_security", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_fees", "client_id", "dim_client", "client_id"),
    ("fact_fees", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "client_id", "dim_client", "client_id"),
    ("fact_portfolio_snapshot", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_transactions", "client_id", "dim_client", "client_id"),
    ("fact_transactions", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_transactions", "security_id", "dim_security", "security_id"),
    ("fact_fees", "fee_date", "dim_date", "date"),
    ("fact_portfolio_snapshot", "snapshot_date", "dim_date", "date"),
    ("fact_transactions", "txn_date", "dim_date", "date"),
]


def run_ri(T, stage):
    rows = []
    for ft, fc, dt, dc in RELATIONSHIPS:
        s = check_referential_integrity(T[ft], fc, T[dt], dc)
        nrm = check_referential_integrity(T[ft], fc, T[dt], dc, normalize=True)
        rows.append(dict(stage=stage, relationship=f"{ft}.{fc} -> {dt}.{dc}", child_table=ft, fact_rows=s["n_rows"],
                         null_key_rows=s["null_key_rows"], null_key_rate_pct=round(100 * s["null_key_rate"], 3),
                         non_null_rows=s["non_null_rows"], matched_rows=s["matched_rows"],
                         match_rate_pct=round(100 * s["match_rate"], 3),
                         match_rate_after_removing_dot0_pct=round(100 * nrm["match_rate"], 3),
                         orphan_rows=s["orphan_row_count"], distinct_orphan_keys=s["distinct_orphan_keys"],
                         orphan_key_examples=s["orphan_key_examples"], parent_table=dt, parent_rows=s["dim_rows"],
                         parent_null_keys=s["dim_null_key_rows"], parent_duplicate_key_rows=s["dim_duplicate_key_rows"]))
    return pd.DataFrame(rows)


# =========================================================================
# PART D.2  Schema, completeness, key uniqueness, type validity
# =========================================================================
SCHEMA = {
    "dim_advisor": dict(advisor_id="int", first_name="text", last_name="text", region="text",
                        years_experience="int", aum_target_mm="num", certifications="text"),
    "dim_client": dict(client_id="int", first_name="text", last_name="text", age="int", city="text", state="text",
                       zip_code="text", risk_profile="text", client_tier="text", primary_account_type="text",
                       initial_aum="num", client_since="date", advisor_id="int", is_active="bool"),
    "dim_date": dict(date_id="int", date="date", year="int", quarter="int", month="int", month_name="text",
                     week_of_year="int", day_of_week="text", is_month_end="int", is_quarter_end="int",
                     is_year_end="int", is_trading_day="int"),
    "dim_security": dict(security_id="int", ticker="text", name="text", asset_class="text", sector="text",
                         benchmark_id="int", is_etf="bool", expense_ratio_bps="num"),
    "dim_benchmark": dict(benchmark_id="int", name="text", asset_class="text", ticker_proxy="text"),
    "fact_fees": dict(fee_id="int", client_id="int", advisor_id="int", fee_date="date", fee_type="text",
                      aum_basis="num", bps_charged="num", amount="num"),
    "fact_portfolio_snapshot": dict(snapshot_id="int", client_id="int", advisor_id="int", benchmark_id="int",
                                    snapshot_date="date", year="int", month="int", aum="num", return_ytd="num",
                                    benchmark_return_ytd="num", active_alpha_ytd="num", cash_pct="num",
                                    account_type="text"),
    "fact_transactions": dict(txn_id="int", client_id="int", advisor_id="int", security_id="int", txn_date="date",
                              txn_type="text", shares="num", price="num", amount="num"),
}
# columns that only exist after cleaning (flags); they are type- and completeness-checked when present
OPTIONAL_SCHEMA = {"fact_transactions": dict(shares_sign_fixed="flag"), "dim_client": dict(risk_profile_missing="flag"),
                   "fact_portfolio_snapshot": dict(return_ytd_extreme="flag")}
_is_trade = lambda d: _b(_txt(d["txn_type"]).isin(TRADE_TYPES))
# a blank or mistyped txn_type is NOT a reason to excuse a blank security_id/shares/price
_needs_trade_fields = lambda d: _is_trade(d) | _b(~_txt(d["txn_type"]).isin(KNOWN_TXN_TYPES))
REQUIRED_IF = {
    ("dim_security", "sector"): lambda d: _b(_txt(d["asset_class"]).eq("Equity")),
    ("dim_security", "expense_ratio_bps"): lambda d: _b(_txt(d["is_etf"]).str.lower().eq("true")),
    ("fact_transactions", "security_id"): _needs_trade_fields,
    ("fact_transactions", "shares"): _needs_trade_fields,
    ("fact_transactions", "price"): _needs_trade_fields,
}
# the opposite direction (blank where it must be blank) is tested by the blank_when rules in RULES


def schema_cols(df, t):
    cols = dict(SCHEMA[t])
    cols.update({c: k for c, k in OPTIONAL_SCHEMA.get(t, {}).items() if c in df.columns})
    return cols


def valid_for_type(s, kind):
    """Strict and untrimmed: a value with leading/trailing spaces is not a valid int/number."""
    t = s.astype("string")
    if kind == "int":
        return _b(t.str.match(r"^-?\d+$"))
    if kind == "num":
        return _b(t.str.match(r"^-?\d+(\.\d+)?$"))
    if kind == "date":
        return _b(pd.to_datetime(t, format="%Y-%m-%d", errors="coerce").notna() & t.str.match(r"^\d{4}-\d{2}-\d{2}$"))
    if kind == "bool":
        return _b(t.isin(["True", "False"]))
    if kind == "flag":
        return _b(t.isin(["0", "1"]))
    return pd.Series(True, index=s.index)


def completeness(df, t):
    req = blank_req = 0
    for c in schema_cols(df, t):
        need = REQUIRED_IF[(t, c)](df) if (t, c) in REQUIRED_IF else pd.Series(True, index=df.index)
        req += int(need.sum())
        blank_req += int((need & _blank(df[c])).sum())
    return (100 * (1 - blank_req / req) if req else 100.0), req, blank_req


KEY_COLUMNS = {"dim_date": ["date_id", "date"]}       # dim_date.date is the join key of three relationships


def key_uniqueness(df, t):
    """A row passes only if each key column is non-blank and its value appears once in the table."""
    if not len(df):
        return 100.0, 0
    bad = pd.Series(False, index=df.index)
    for k in KEY_COLUMNS.get(t, [df.columns[0]]):
        bad |= _blank(df[k]) | _b(df[k].astype("string").duplicated(keep=False))
    return 100 * (1 - bad.sum() / len(df)), int(bad.sum())


def type_validity(df, t):
    ok = tot = 0
    for c, kind in schema_cols(df, t).items():
        if kind == "text":
            continue
        present = ~_blank(df[c])
        tot += int(present.sum())
        ok += int((present & valid_for_type(df[c], kind)).sum())
    return (100 * ok / tot if tot else 100.0), tot, tot - ok


# =========================================================================
# PART D.3  Rule-based checks (natural business bounds)
# =========================================================================
RULES = []


def rule(table, column, name, kind, when=None, **p):
    RULES.append(dict(table=table, column=column, name=name, kind=kind, when=when, p=p))


def rng(table, col, lo=None, hi=None, lo_incl=True, hi_incl=True, name=None, when=None):
    label = name or f"{col} in {'[' if lo_incl else '('}{lo},{hi}{']' if hi_incl else ')'}"
    rule(table, col, label, "range", when, lo=lo, hi=hi, lo_incl=lo_incl, hi_incl=hi_incl)


def allowed(table, col, values, name=None):
    rule(table, col, name or f"{col} in allowed list", "allowed", None, values=set(values))


def regex(table, col, pat, name):
    rule(table, col, name, "regex", None, pat=pat)


def date_range(table, col, lo, hi, name=None):
    """lo / hi: a Timestamp, or "DIM_DATE_MIN" / "DIM_DATE_MAX" (taken from dim_date.date of the same stage)."""
    label = lambda x: x.date() if hasattr(x, "date") else x
    rule(table, col, name or f"{col} between {label(lo)} and {label(hi)}", "date_range", None, lo=lo, hi=hi)


def blank_when(table, col, cond, name):
    """Structural blanks: where cond(df) is true the column MUST be blank (a fill-in error fails)."""
    rule(table, col, name, "blank_when", None, cond=cond)


def date_part(table, col, datecol, part, name):
    rule(table, col, name, "func", None, fn=lambda d: _date_part_eval(d, col, datecol, part))


def _date_part_eval(d, col, datecol, part):
    dt_ = _date(d[datecol])
    exp = {"year": dt_.dt.year, "month": dt_.dt.month, "quarter": dt_.dt.quarter}.get(part)
    if part == "day_name":
        exp, v = dt_.dt.day_name(), _txt(d[col])
        ev = ~_blank(d[col]) & dt_.notna()
        return ev, _b(ev & (v != exp))
    if part == "month_name":
        exp, v = dt_.dt.month_name(), _txt(d[col])
        ev = ~_blank(d[col]) & dt_.notna()
        return ev, _b(ev & (v != exp))
    if part.startswith("is_"):
        exp = {"is_month_end": dt_.dt.is_month_end, "is_quarter_end": dt_.dt.is_quarter_end,
               "is_year_end": dt_.dt.is_year_end}[part].astype(int)
    v = _num(d[col])
    ev = v.notna() & dt_.notna()
    return ev, _b(ev & (v != exp))


NOT_PADDED = r"^\S(.*\S)?$"      # allowed/regex rules see the UNTRIMMED text, so padding fails them
# dim_advisor
allowed("dim_advisor", "region", ["Northeast", "Southeast", "Mid-Atlantic", "West", "Midwest"])
rng("dim_advisor", "years_experience", 0, 50)
rng("dim_advisor", "aum_target_mm", 0, None, lo_incl=False, name="aum_target_mm > 0")
regex("dim_advisor", "certifications", r"^(None|(?!.*(CFA|CFP|CIMA).*\2)(CFA|CFP|CIMA)(, (CFA|CFP|CIMA))*)$",
      "certifications is None or a list of distinct CFA/CFP/CIMA")
# dim_benchmark
allowed("dim_benchmark", "asset_class", ["Equity", "Fixed Income", "International", "Small Cap", "Emerging", "Cash", "Multi-Asset"])
regex("dim_benchmark", "ticker_proxy", r"^[A-Z0-9_]{2,12}$", "ticker_proxy format")
# dim_client
rng("dim_client", "age", 18, 110)
allowed("dim_client", "state", STATE_CODES, "state is a valid 2-letter code")
regex("dim_client", "zip_code", r"^\d{5}$", "zip_code is 5 digits")
allowed("dim_client", "risk_profile", ["Conservative", "Moderately Conservative", "Balanced", "Moderately Aggressive", "Aggressive"])
allowed("dim_client", "client_tier", ["Retail", "HNW", "UHNW"])
allowed("dim_client", "primary_account_type", ["Taxable", "IRA", "Roth IRA", "529", "Trust"])
rng("dim_client", "initial_aum", 0, None, lo_incl=False, name="initial_aum > 0")
date_range("dim_client", "client_since", pd.Timestamp("1990-01-01"), "DIM_DATE_MAX", "client_since between 1990-01-01 and the last dim_date date")
allowed("dim_client", "is_active", ["True", "False"])
for c in ("first_name", "last_name", "city"):
    regex("dim_client", c, NOT_PADDED, f"{c} has no leading/trailing spaces")
# dim_date
rng("dim_date", "month", 1, 12)
rng("dim_date", "quarter", 1, 4)
rng("dim_date", "week_of_year", 1, 53)
allowed("dim_date", "day_of_week", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
allowed("dim_date", "month_name", ["January", "February", "March", "April", "May", "June", "July", "August",
                                    "September", "October", "November", "December"])
for c in ("is_month_end", "is_quarter_end", "is_year_end", "is_trading_day"):
    allowed("dim_date", c, ["0", "1"])
date_part("dim_date", "year", "date", "year", "year agrees with date")
date_part("dim_date", "month", "date", "month", "month agrees with date")
date_part("dim_date", "quarter", "date", "quarter", "quarter agrees with date")
date_part("dim_date", "day_of_week", "date", "day_name", "day_of_week agrees with date")
date_part("dim_date", "month_name", "date", "month_name", "month_name agrees with date")
for c in ("is_month_end", "is_quarter_end", "is_year_end"):
    date_part("dim_date", c, "date", c, f"{c} agrees with date")
# dim_security
regex("dim_security", "ticker", r"^[A-Z]{1,5}([.-][A-Z])?$", "ticker is 1-5 capital letters (optional .B / -B share class)")
allowed("dim_security", "asset_class", ["Equity", "Fixed Income", "Alternative", "Cash Equivalent"])
allowed("dim_security", "sector", ["Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy",
                                   "Financials", "Healthcare", "Industrials", "Materials", "Real Estate",
                                   "Technology", "Utilities"])
allowed("dim_security", "is_etf", ["True", "False"])
rng("dim_security", "expense_ratio_bps", 0, 300)
blank_when("dim_security", "sector", lambda d: _b(~_txt(d["asset_class"]).eq("Equity")), "sector is blank when asset_class is not Equity")
blank_when("dim_security", "expense_ratio_bps", lambda d: _b(_txt(d["is_etf"]).str.lower().eq("false")),
           "expense_ratio_bps is blank when is_etf is False")
# fact_fees
allowed("fact_fees", "fee_type", ["Management", "Advisory", "Custodial", "Performance"])
rng("fact_fees", "aum_basis", 0, None, lo_incl=False, name="aum_basis > 0")
rng("fact_fees", "bps_charged", 0, 300)
rng("fact_fees", "amount", 0, None, name="amount >= 0")
date_range("fact_fees", "fee_date", "DIM_DATE_MIN", "DIM_DATE_MAX", "fee_date within the dim_date range")
# fact_portfolio_snapshot
rng("fact_portfolio_snapshot", "month", 1, 12)
date_range("fact_portfolio_snapshot", "snapshot_date", "DIM_DATE_MIN", "DIM_DATE_MAX", "snapshot_date within the dim_date range")
date_part("fact_portfolio_snapshot", "year", "snapshot_date", "year", "year agrees with snapshot_date")
date_part("fact_portfolio_snapshot", "month", "snapshot_date", "month", "month agrees with snapshot_date")
rng("fact_portfolio_snapshot", "aum", 0, None, lo_incl=False, name="aum > 0")
rng("fact_portfolio_snapshot", "cash_pct", 0, 1)
rng("fact_portfolio_snapshot", "return_ytd", -1, None, name="return_ytd >= -100%")
rng("fact_portfolio_snapshot", "return_ytd", None, 2.0, name="return_ytd <= 200% (plausibility screen: values above it are flagged by 02_clean.py, not changed)")
rng("fact_portfolio_snapshot", "benchmark_return_ytd", -1, None, name="benchmark_return_ytd >= -100%")
allowed("fact_portfolio_snapshot", "account_type", ["Taxable", "IRA", "Roth IRA", "529", "Trust"])
# fact_transactions
allowed("fact_transactions", "txn_type", ["Buy", "Sell", "Dividend", "Deposit", "Withdrawal", "Advisory Fee"])
rng("fact_transactions", "shares", 0, None, lo_incl=False, name="shares > 0")
rng("fact_transactions", "price", 0, None, lo_incl=False, name="price > 0")
rng("fact_transactions", "amount", 0, None, lo_incl=False, name="amount > 0 (all types are recorded as positive)")
date_range("fact_transactions", "txn_date", "DIM_DATE_MIN", "DIM_DATE_MAX", "txn_date within the dim_date range")
for _c in ("security_id", "shares", "price"):
    blank_when("fact_transactions", _c, lambda d: _b(_txt(d["txn_type"]).isin(["Deposit", "Withdrawal", "Advisory Fee"])),
               f"{_c} is blank on Deposit/Withdrawal/Advisory Fee rows")


def _bound(x, T):
    if isinstance(x, str):
        d = _date(T["dim_date"]["date"])
        return d.min() if x == "DIM_DATE_MIN" else d.max()
    return x


def eval_rule(df, r, T):
    """Return (evaluated mask, failed mask). Blank and unparseable values are not evaluated."""
    col, k, p = r["column"], r["kind"], r["p"]
    if k == "func":
        return p["fn"](df)
    if k == "blank_when":
        ev = _b(p["cond"](df))
        return ev, _b(ev & ~_blank(df[col]))
    ev = ~_blank(df[col])
    if r["when"] is not None:
        ev &= r["when"](df)
    s = df[col].astype("string")                      # untrimmed: padded values fail allowed/regex rules
    if k == "range":
        v = _num(df[col])
        ev &= v.notna() & np.isfinite(v)               # inf / nan text is not evaluated (type_validity counts it)
        ok = pd.Series(True, index=df.index)
        if p["lo"] is not None:
            ok &= (v >= p["lo"]) if p["lo_incl"] else (v > p["lo"])
        if p["hi"] is not None:
            ok &= (v <= p["hi"]) if p["hi_incl"] else (v < p["hi"])
        return ev, _b(ev & ~_b(ok))
    if k == "allowed":
        return ev, _b(ev & ~_b(s.isin(p["values"])))
    if k == "regex":
        return ev, _b(ev & ~_b(s.str.match(p["pat"])))
    if k == "date_range":
        d = _date(df[col])
        ev &= d.notna()
        lo, hi = _bound(p["lo"], T), _bound(p["hi"], T)
        return ev, _b(ev & ((d < lo) | (d > hi)))
    raise ValueError(k)


def run_rules(T, stage):
    rows = []
    for r in RULES:
        df = T[r["table"]]
        ev, fail = eval_rule(df, r, T)
        rows.append(dict(stage=stage, table=r["table"], column=r["column"], rule=r["name"], kind=r["kind"],
                         rows_total=len(df), rows_evaluated=int(ev.sum()), rows_not_evaluated=len(df) - int(ev.sum()),
                         rows_failed=int(fail.sum()),
                         pass_rate_pct=round(100 * (1 - fail.sum() / ev.sum()), 3) if ev.sum() else 100.0,
                         example_failing_values=" | ".join(map(str, df.loc[fail, r["column"]].head(3)))))
    return pd.DataFrame(rows)


# =========================================================================
# PART D.4  Cross-table / cross-column reconciliations
# =========================================================================
def recon_row(stage, name, tables, n_eval, n_fail, desc, note="", n_scope=None):
    """rows_in_scope = rows the check is about; rows_skipped = in scope but not evaluable (never silently dropped)."""
    scope = int(n_eval if n_scope is None else n_scope)
    return dict(stage=stage, reconciliation=name, tables=tables, rows_in_scope=scope, rows_evaluated=int(n_eval),
                rows_skipped=scope - int(n_eval), rows_failed=int(n_fail),
                pass_rate_pct=round(100 * (1 - n_fail / n_eval), 3) if n_eval else np.nan, description=desc, note=note)


def _lookup(df, key, val, conv=_txt):
    """key -> value map from a parent table. Returns (map with the first copy of each key, duplicate-key rows)."""
    k, v = _txt(df[key]), conv(df[val])
    m = pd.Series(v.values, index=k.values)
    return m[~m.index.duplicated()], int(k.duplicated(keep=False).sum())


def _mx(x):
    return float(x.max()) if len(x) else float("nan")


def run_reconciliations(T, stage):
    out = []
    tx, fe, sn, cl, dd = T["fact_transactions"], T["fact_fees"], T["fact_portfolio_snapshot"], T["dim_client"], T["dim_date"]
    # R1 stored amount vs recomputed shares x price (signed shares: a negative sign is a defect)
    trade = _is_trade(tx)
    sh, pr, am = _num(tx["shares"]), _num(tx["price"]), _num(tx["amount"])
    ev = trade & sh.notna() & pr.notna() & am.notna()
    d1 = (sh * pr - am).abs()
    bad = _b(ev & (d1 > 0.01))
    out.append(recon_row(stage, "R1 txn amount = shares x price", "fact_transactions", ev.sum(), bad.sum(),
                         "Buy/Sell/Dividend rows; tolerance 1 cent (amounts are rounded to the cent)",
                         f"largest difference among passing rows {_mx(d1[ev & ~bad]):.4f}", n_scope=trade.sum()))
    # R2 stored fee vs aum_basis x bps / 10000 / 12
    a, b, f = _num(fe["amount"]), _num(fe["aum_basis"]), _num(fe["bps_charged"])
    exp = b * f / 10000 / 12
    ev = a.notna() & exp.notna()
    d2 = (a - exp).abs()
    bad = _b(ev & (d2 > 0.01))
    out.append(recon_row(stage, "R2 fee amount = aum_basis x bps / 10000 / 12", "fact_fees", ev.sum(), bad.sum(),
                         "all fee types; tolerance 1 cent (the amount is rounded to the cent)",
                         f"largest difference found {_mx(d2[ev]):.4f}", n_scope=len(fe)))
    # R3 alpha = return - benchmark, percent-aware
    r, bm, al = _num_pct(sn["return_ytd"]), _num_pct(sn["benchmark_return_ytd"]), _num_pct(sn["active_alpha_ytd"])
    ev = r.notna() & bm.notna() & al.notna()
    d3 = (r - bm - al).abs()
    bad = _b(ev & (d3 > 1e-4))
    out.append(recon_row(stage, "R3 active_alpha = return_ytd - benchmark_return_ytd", "fact_portfolio_snapshot", ev.sum(), bad.sum(),
                         "percent text is converted first; one tolerance (1e-4) for both stages, because returns that were "
                         "stored as percent text are rounded to 2 decimals (worst case about 5e-5)",
                         f"largest difference found {_mx(d3[ev]):.6f}", n_scope=len(sn)))
    # R4 fee basis vs snapshot AUM
    f2 = fe[_txt(fe["fee_type"]).eq("Advisory").fillna(False)]
    fx = pd.DataFrame({"k": _txt(f2["client_id"]), "d": _date(f2["fee_date"]), "basis": _num(f2["aum_basis"])}).dropna()
    sx = pd.DataFrame({"k": _txt(sn["client_id"]), "d": _date(sn["snapshot_date"]), "aum": _num(sn["aum"])}).dropna()
    fxu, sxu = fx.drop_duplicates(["k", "d"]), sx.drop_duplicates(["k", "d"])
    j = fxu.merge(sxu, on=["k", "d"])
    bad = ((j["basis"] - j["aum"]).abs() > np.maximum(0.001 * j["aum"].abs(), 1.0)).sum()
    out.append(recon_row(stage, "R4 Advisory fee aum_basis = snapshot aum", "fact_fees, fact_portfolio_snapshot", len(j), bad,
                         "same client and same date (fees and snapshots are both dated the 1st of the month); tolerance 0.1% or $1",
                         f"{len(fxu) - len(j)} Advisory fee client-dates had no snapshot; "
                         f"{len(fx) - len(fxu)} duplicate Advisory client-dates and {len(sx) - len(sxu)} duplicate snapshot client-dates ignored",
                         n_scope=len(fxu)))
    # R5 advisor on fact = advisor of the client
    cmap, c_dup = _lookup(cl, "client_id", "advisor_id")
    for t in ("fact_fees", "fact_portfolio_snapshot", "fact_transactions"):
        df = T[t]
        m = _txt(df["client_id"]).map(cmap)
        ev = m.notna() & ~_blank(df["advisor_id"])
        bad = _b(ev & (m != _txt(df["advisor_id"])))
        out.append(recon_row(stage, f"R5 {t}.advisor_id = client's advisor", f"{t}, dim_client", ev.sum(), bad.sum(),
                             "advisor on the fact row equals dim_client.advisor_id",
                             f"{len(df) - int(ev.sum())} rows skipped (client_id not in dim_client, or blank advisor); "
                             f"{c_dup} dim_client rows share a duplicated client_id (first copy used)", n_scope=len(df)))
    # R6 snapshot account type = client's account type
    amap, a_dup = _lookup(cl, "client_id", "primary_account_type")
    m = _txt(sn["client_id"]).map(amap)
    ev = m.notna() & ~_blank(sn["account_type"])
    out.append(recon_row(stage, "R6 snapshot account_type = client primary_account_type", "fact_portfolio_snapshot, dim_client",
                         ev.sum(), _b(ev & (m != _txt(sn["account_type"]))).sum(), "same account type on both tables",
                         f"{len(sn) - int(ev.sum())} rows skipped (client_id not in dim_client, or blank account_type); "
                         f"{a_dup} duplicated client_id rows in dim_client", n_scope=len(sn)))
    # R7 no activity before the client started (month-level: fees/snapshots are dated the 1st of the month)
    smap, s_dup = _lookup(cl, "client_id", "client_since", conv=_date)
    for t, dc in (("fact_transactions", "txn_date"), ("fact_fees", "fee_date"), ("fact_portfolio_snapshot", "snapshot_date")):
        df = T[t]
        since = _txt(df["client_id"]).map(smap)
        d = _date(df[dc])
        ev = since.notna() & d.notna()
        month_start = since.dt.to_period("M").dt.to_timestamp()
        bad = _b(ev & (d < month_start))
        exact = int(_b(ev & (d < since)).sum())
        out.append(recon_row(stage, f"R7 {t} not before client_since (month)", f"{t}, dim_client", ev.sum(), bad.sum(),
                             "activity dated before the month the client started",
                             f"MONTH-LEVEL check (fees and snapshots are dated the 1st of the month), so it is looser than "
                             f"'not before client_since'; against the exact client_since date {exact:,} rows are earlier. "
                             f"{len(df) - int(ev.sum())} rows skipped (client_id not in dim_client or bad date)", n_scope=len(df)))
    # R8 trades on trading days
    tdm, t_dup = _lookup(dd, "date", "is_trading_day")
    tr = tx[_txt(tx["txn_type"]).isin(["Buy", "Sell"]).fillna(False)]
    td = _txt(tr["txn_date"]).map(tdm)
    ev = td.notna()
    out.append(recon_row(stage, "R8 Buy/Sell dated on a trading day", "fact_transactions, dim_date", ev.sum(), _b(ev & (td != "1")).sum(),
                         "dim_date.is_trading_day = 1",
                         f"see R10: is_trading_day is tested against the weekday. {len(tr) - int(ev.sum())} Buy/Sell rows skipped "
                         f"(date not in dim_date); {t_dup} duplicated dates in dim_date", n_scope=len(tr)))
    # R9 Advisory Fee transactions vs fact_fees (client-month)
    def monthly(df, dcol):
        x = pd.DataFrame({"k": _txt(df["client_id"]), "m": _date(df[dcol]).dt.to_period("M").astype(str), "a": _num(df["amount"])})
        x = x[_date(df[dcol]).notna()].dropna()
        return x.groupby(["k", "m"])["a"].sum()
    at = tx[_txt(tx["txn_type"]).eq("Advisory Fee").fillna(False)]
    af = fe[_txt(fe["fee_type"]).eq("Advisory").fillna(False)]
    g1, g2 = monthly(at, "txn_date"), monthly(af, "fee_date")
    both = pd.concat([g1.rename("txn"), g2.rename("fee")], axis=1).dropna()
    out.append(recon_row(stage, "R9 Advisory Fee transactions = Advisory fees (client-month)", "fact_transactions, fact_fees",
                         len(both), ((both["txn"] - both["fee"]).abs() > 0.01).sum(),
                         "monthly sum of Advisory Fee debits vs monthly sum of Advisory fees; tolerance 1 cent",
                         f"{len(g1) - len(both)} client-months with an Advisory Fee debit have no Advisory fee row; {len(g2) - len(both)} the other way",
                         n_scope=len(g1)))
    # R10 dim_date.is_trading_day is simply "weekday" (this is what R8's wording relies on)
    dts, itd = _date(dd["date"]), _num(dd["is_trading_day"])
    ev = dts.notna() & itd.notna()
    wk = (dts.dt.day_of_week < 5)
    out.append(recon_row(stage, "R10 dim_date.is_trading_day = weekday (no holidays)", "dim_date", ev.sum(),
                         _b(ev & ((itd == 1) != wk)).sum(), "is_trading_day is 1 exactly on Monday-Friday",
                         "if this fails, R8 and the 'weekend trade' wording change", n_scope=len(dd)))
    # R11 dim_date has exactly one row per calendar day, no gaps or repeats (the date key is unique and complete)
    valid = dts.dropna()
    expected_days = int((valid.max() - valid.min()).days + 1) if len(valid) else 0
    missing_days = expected_days - int(valid.nunique())
    dup_rows = int(valid.duplicated().sum())
    out.append(recon_row(stage, "R11 dim_date is one row per calendar day", "dim_date", expected_days, missing_days + dup_rows,
                         "calendar days between the first and last date vs distinct dates; repeated dates count as failures",
                         f"{missing_days} missing days, {dup_rows} repeated dates, {len(dd) - len(valid)} unparseable dates",
                         n_scope=expected_days))
    return pd.DataFrame(out)


# =========================================================================
# PART D.5  IQR outlier flags (columns with no natural upper bound)
# =========================================================================
# (table, column, split by) : unlike values are not pooled (deposits vs trades, fee types)
OUTLIER_COLUMNS = [("dim_client", "initial_aum", None), ("fact_portfolio_snapshot", "aum", None),
                   ("fact_transactions", "amount", "txn_type"), ("fact_fees", "amount", "fee_type")]
OUTLIER_NOTE = ("Flagged means unusual relative to the rest of the column (or of its group), not wrong: in skewed money data "
                "many legitimate large values fall outside Q3 + 1.5 x IQR. Every flagged row is listed in outlier_rows.csv.")


def run_outliers(T, stage):
    rows, flagged = [], []
    for t, c, g in OUTLIER_COLUMNS:
        df = T[t]
        v = _num(df[c])
        grp = _txt(df[g]) if g else pd.Series("all", index=df.index, dtype="string")
        for gv in sorted(grp.dropna().unique()):
            m = _b(grp == gv) & v.notna()
            vv = v[m]
            if not len(vv):
                continue
            q1, q3 = vv.quantile(0.25), vv.quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            below, above = vv < lo, vv > hi
            rows.append(dict(stage=stage, table=t, column=c, group=gv, n_values=len(vv), q1=round(q1, 2), q3=round(q3, 2),
                             iqr=round(iqr, 2), lower_fence=round(lo, 2), upper_fence=round(hi, 2),
                             n_below=int(below.sum()), n_above=int(above.sum()),
                             pct_flagged=round(100 * (below | above).mean(), 3), max_value=round(vv.max(), 2),
                             interpretation=OUTLIER_NOTE))
            for side, mk in (("below", below), ("above", above)):
                if mk.any():
                    idx = vv.index[mk.values]
                    flagged.append(pd.DataFrame({"stage": stage, "table": t, "key_column": df.columns[0],
                                                 "key": df.loc[idx, df.columns[0]].values, "column": c, "group": gv,
                                                 "value": vv[idx].values, "side": side}))
    fl = pd.concat(flagged, ignore_index=True) if flagged else pd.DataFrame(
        columns=["stage", "table", "key_column", "key", "column", "group", "value", "side"])
    return pd.DataFrame(rows), fl


# =========================================================================
# Scorecard
# =========================================================================
def run_stage(T, stage):
    for t in TABLES:
        missing = set(SCHEMA[t]) - set(T[t].columns)
        check(not missing, f"{stage}.{t}: missing columns {missing}")
    ri = run_ri(T, stage)
    rules = run_rules(T, stage)
    rec = run_reconciliations(T, stage)
    out, out_rows = run_outliers(T, stage)
    rows = []
    for t in TABLES:
        df = T[t]
        comp, _, _ = completeness(df, t)
        uniq, _ = key_uniqueness(df, t)
        typ, _, _ = type_validity(df, t)
        rl = rules[rules["table"] == t]
        rp = 100 * (1 - rl["rows_failed"].sum() / rl["rows_evaluated"].sum()) if rl["rows_evaluated"].sum() else np.nan
        rr = ri[ri["child_table"] == t]
        rm = 100 * rr["matched_rows"].sum() / rr["non_null_rows"].sum() if len(rr) and rr["non_null_rows"].sum() else np.nan
        worst_pct, worst_rel = np.nan, ""
        if len(rr) and rr["match_rate_pct"].notna().any():
            w = rr.loc[rr["match_rate_pct"].idxmin()]
            worst_pct, worst_rel = w["match_rate_pct"], w["relationship"]
        rows.append(dict(table=t, stage=stage, rows=len(df), completeness_pct=round(comp, 3), key_uniqueness_pct=round(uniq, 3),
                         type_validity_pct=round(typ, 3), rule_pass_pct=round(rp, 3), referential_match_pct=round(rm, 3),
                         referential_worst_pct=worst_pct, referential_worst_relationship=worst_rel))
    return pd.DataFrame(rows), ri, rules, rec, out, out_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(find_raw()))
    ap.add_argument("--clean", default=str(ROOT / "data" / "clean"))
    ap.add_argument("--out", default=str(ROOT / "reports"))
    a = ap.parse_args()
    raw_dir, clean_dir, out = Path(a.raw).resolve(), Path(a.clean).resolve(), Path(a.out).resolve()
    for nm, d in (("raw", raw_dir), ("clean", clean_dir)):
        check(out != d and d not in out.parents and out not in d.parents,
              f"--out must not be, contain, or sit inside the {nm} data folder")
    selftest_ri()
    print("check_referential_integrity self-test passed\n")
    res = []
    for stage, folder in (("raw", raw_dir), ("clean", clean_dir)):
        T = read_tables(folder)
        print(f"Validating {stage}: " + ", ".join(f"{t} {len(df):,}" for t, df in T.items()))
        res.append(run_stage(T, stage))
    names = ["data_quality_scorecard", "ri_results", "rule_results", "reconciliations", "outlier_flags", "outlier_rows"]
    frames = {}
    for i, nm in enumerate(names):
        df = pd.concat([r[i] for r in res], ignore_index=True)
        if nm == "data_quality_scorecard":
            tb = {t: k for k, t in enumerate(TABLES)}
            df["_s"] = df["stage"].map({"raw": 0, "clean": 1})
            df = df.sort_values(["table", "_s"], key=lambda s: s.map(tb) if s.name == "table" else s).drop(columns="_s")
        frames[nm] = df
    # write every report to a temporary name first, then rename them all, so a failure cannot leave a mix
    out.mkdir(parents=True, exist_ok=True)
    tmp = {nm: out / f".{nm}.csv.tmp" for nm in names}
    for nm in names:
        frames[nm].to_csv(tmp[nm], index=False)
    for nm in names:
        os.replace(tmp[nm], out / f"{nm}.csv")
    print("\nData quality scorecard (percent):")
    print(frames["data_quality_scorecard"].drop(columns=["referential_worst_relationship"]).to_string(index=False))
    ri = frames["ri_results"]
    print("\nReferential integrity (strict, exact text match):")
    print(ri[["stage", "relationship", "null_key_rate_pct", "match_rate_pct", "match_rate_after_removing_dot0_pct",
              "orphan_rows", "distinct_orphan_keys", "parent_duplicate_key_rows"]].to_string(index=False))
    if (ri["parent_duplicate_key_rows"] > 0).any() or (ri["parent_null_keys"] > 0).any():
        print("WARNING: a parent table has duplicate or blank keys; see parent_* columns in ri_results.csv")
    rec = frames["reconciliations"]
    print("\nReconciliations:")
    print(rec[["stage", "reconciliation", "rows_in_scope", "rows_evaluated", "rows_skipped", "rows_failed", "pass_rate_pct"]].to_string(index=False))
    print("\nOutlier flags (IQR 1.5x):")
    print(frames["outlier_flags"][["stage", "table", "column", "group", "n_values", "n_below", "n_above", "pct_flagged"]].to_string(index=False))
    print("\n" + OUTLIER_NOTE)
    print(f"\nSaved {', '.join(n + '.csv' for n in names)} to {out}")


if __name__ == "__main__":
    main()
