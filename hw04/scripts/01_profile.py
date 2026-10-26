#!/usr/bin/env python
"""
HW4 Part A - 01_profile.py
Generic profiler + data-quality checks for the Wildcat Capital tables.

* profile_table() works on ANY DataFrame read as text (dtype=str,
  keep_default_na=False). Nothing in it is hard-coded to a table.
* Checks are grouped as the assignment asks:
    1 Column level        2 Single-table rules
    3 Referential integrity   4 Cross-table business rules
  Groups 1 and 3 are convention-driven (column names / first column = key).
  Table-specific business rules live in TABLE_RULES / cross_table_checks and are
  clearly separated from the generic profiler.
* Severity: ERROR (wrong / will break a join or calculation),
            WARN (probably wrong, investigate), INFO (worth knowing).

Assumptions written down (so they are not hidden in the code):
* The first column of every table is its primary key.
* Column types come from the column NAME when it is obvious (*_date, *_since -> date;
  *_id, amount, price, shares, aum, ... -> numeric; is_* -> boolean) and from the VALUES
  otherwise. A name-based type means unparseable values are reported even when most of a
  column is bad.
* Fees: amount = aum_basis x bps_charged / 10000 / 12 (monthly fee on an annual rate).
* Amounts are rounded to the cent. Percent text such as "9.28%" is rounded to 2 decimals,
  so return = benchmark + alpha is allowed 1e-4 on percent rows and 1e-5 elsewhere.
* "Today" is fixed at AS_OF (the end of dim_date) so results do not change by calendar day.
* Keys are compared strictly: only an empty cell counts as a blank key.

Usage (from the project root, venv active):
    python scripts/01_profile.py                       # profiles data/raw
    python scripts/01_profile.py --in data/clean --tag clean
Outputs: reports/profile_<tag>.csv, reports/dq_summary_<tag>.csv, reports/ri_summary_<tag>.csv
"""
import argparse
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


AS_OF = pd.Timestamp("2024-12-31")
NULL_TOKENS = {"none", "nan", "null", "n/a", "na", "nat", "-", "--", "?", "unknown", "#n/a"}
TRUE_T, FALSE_T = {"true", "t", "yes", "y", "1"}, {"false", "f", "no", "n", "0"}
BOOL_TOKENS = TRUE_T | FALSE_T
NUM_TOKENS = {"amount", "price", "shares", "aum", "bps", "pct", "return", "alpha", "age", "year", "years",
              "month", "quarter", "experience", "ratio", "basis", "id", "mm", "ytd"}
NONNEG_TOKENS = {"shares", "price", "amount", "aum", "age", "bps", "experience", "pct", "basis"}
TRADE_TYPES = {"buy", "sell", "dividend"}
KNOWN_TXN_TYPES = TRADE_TYPES | {"deposit", "withdrawal", "advisory fee"}
FINDINGS, RI_ROWS, CHECKED_PARSE = [], [], set()


# ----------------------------------------------------------------- helpers
def add(table, group, check, column, sev, n, total, detail=""):
    """Record a finding (skipped when nothing is affected)."""
    n = int(n)
    if n == 0:
        return
    FINDINGS.append(dict(
        table=table, group=group, check=check, column=column, severity=sev,
        rows_affected=n, pct_of_rows=round(100 * n / total, 3) if total else 0.0,
        detail=str(detail)[:300]))


def read_table(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def to_num(s):
    """Strip $, % and spaces; accept commas only as thousands separators (so '1,5' stays unparsed)."""
    t = s.str.replace(r"[\$%\s]", "", regex=True)
    ok = ~t.str.contains(",") | t.str.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
    return pd.to_numeric(t.where(ok).str.replace(",", "", regex=False), errors="coerce")


def to_date(s):
    return pd.to_datetime(s.str.strip(), format="%Y-%m-%d", errors="coerce")


def bool_flags(s):
    """(value, known): value is True for true-like tokens; known is False for unrecognised text."""
    low = s.str.strip().str.lower()
    return low.isin(TRUE_T), low.isin(BOOL_TOKENS)


def nid(s):
    """Normalise an ID for matching: trim and drop a trailing .0 ."""
    return s.str.strip().str.replace(r"\.0+$", "", regex=True)


def is_present(s, strict=False):
    """strict=True: only an empty cell is blank (use for keys). Otherwise null-like tokens count too."""
    st = s.str.strip()
    if strict:
        return st != ""
    return ~((st == "") | st.str.lower().isin(NULL_TOKENS))


def hint_type(col):
    c = col.lower()
    toks = set(c.split("_"))
    if c.startswith("is_"):
        return "bool"
    if c == "date" or c.endswith("_date") or c.endswith("_since"):
        return "date"
    if "name" in toks:
        return None
    if toks & NUM_TOKENS:
        return "numeric"
    return None


def col_type(col, ps):
    h = hint_type(col)
    if h:
        return h
    if len(ps) == 0:
        return "empty"
    if ps.str.lower().isin(BOOL_TOKENS).all():
        return "bool"
    if to_date(ps).notna().mean() >= 0.8:
        return "date"
    if to_num(ps).notna().mean() >= 0.8:
        return "numeric"
    return "text"


def examples(s, k=3):
    return " | ".join(map(str, s.head(k).tolist()))


def P(df, t, col, kind="num"):
    """Parse a column for a rule. If the generic profile did not already check it, report
    values that do not parse, so a rule never skips them silently."""
    s = df[col]
    v = to_num(s) if kind == "num" else to_date(s)
    if (t, col) not in CHECKED_PARSE:
        bad = is_present(s) & v.isna()
        add(t, 1, "unparseable_value", col, "WARN", bad.sum(), len(df), f"{kind}: {examples(s[bad])}")
        CHECKED_PARSE.add((t, col))
    return v


# --------------------------------------------------- Generic column profile
def profile_table(df, name):
    """Return one dict per column. Works on any all-text DataFrame."""
    out, n = [], len(df)
    for c in df.columns:
        s = df[c]
        st = s.str.strip()
        blank = st == ""
        tok = st.str.lower().isin(NULL_TOKENS) & ~blank
        present = ~(blank | tok)
        ps, p = st[present], s[present]
        t = col_type(c, ps)
        row = dict(table=name, column=c, n_rows=n, blank_n=int(blank.sum()),
                   null_token_n=int(tok.sum()), distinct=int(s.nunique()), guessed_type=t,
                   type_source="name" if hint_type(c) else "values")
        row["whitespace_n"] = int(((s != st) | s.str.contains(r"\s{2,}")).sum())   # rows, counted once
        fail = pd.Series(False, index=ps.index)
        if t == "numeric":
            fail = to_num(ps).isna()
        elif t == "date":
            fail = to_date(ps).isna()
        elif t == "bool":
            fail = ~ps.str.lower().isin(BOOL_TOKENS)
        row["parse_fail_n"] = int(fail.sum())
        row["parse_fail_pct"] = round(100 * fail.mean(), 3) if len(ps) else 0.0
        row["parse_fail_examples"] = examples(ps[fail])
        shapes = ps.str.replace(r"\d+", "9+", regex=True).str.replace(r"[A-Za-z]+", "A+", regex=True)
        vc = shapes.value_counts()
        row["n_shapes"] = int(len(vc))
        row["top_shapes"] = "; ".join(f"{k} ({100 * v / max(len(ps), 1):.1f}%)" for k, v in vc.head(3).items())
        row["min_len"] = int(ps.str.len().min()) if len(ps) else np.nan
        row["max_len"] = int(ps.str.len().max()) if len(ps) else np.nan
        if t == "numeric":
            nums = to_num(ps).dropna()
            row["num_min"] = nums.min() if len(nums) else np.nan
            row["num_max"] = nums.max() if len(nums) else np.nan
            row["num_negative_n"] = int((nums < 0).sum())
        else:
            row["num_min"] = row["num_max"] = np.nan
            row["num_negative_n"] = 0
        row["leading_zero_n"] = int(ps.str.match(r"^0\d+").sum())
        row["float_style_int_n"] = int(ps.str.match(r"^\d+\.0+$").sum())
        row["symbol_n"] = int(ps.str.contains(r"[\$%,]").sum()) if t == "numeric" else 0
        row["sci_notation_n"] = int(ps.str.match(r"^-?\d+(\.\d+)?[eE][-+]?\d+$").sum()) if t == "numeric" else 0
        row["allowed_values"] = ("; ".join(f"{k}={v}" for k, v in ps.value_counts().items())
                                 if ps.nunique() <= 15 else "")
        # spelling variants of one category: count only the minority spellings
        v_n, v_ex = 0, ""
        if t in ("text", "bool") and 1 < p.nunique() <= 5000:
            key = p.str.lower().str.replace(r"[^a-z0-9]", "", regex=True) if t == "text" else p.str.strip().str.lower()
            if t == "bool":                          # True/true/TRUE are variants; 1 vs 0 are not
                key = p.str.strip().str.lower().map(lambda x: "T" if x in TRUE_T else ("F" if x in FALSE_T else x))
            cnt = pd.DataFrame({"key": key.values, "raw": p.values}).groupby(["key", "raw"]).size().reset_index(name="n")
            multi = cnt.groupby("key")["raw"].transform("nunique") > 1
            cm = cnt[multi]
            if len(cm):
                dom = cm.sort_values("n", ascending=False).drop_duplicates("key")[["key", "raw"]].rename(columns={"raw": "dom"})
                mm = cm.merge(dom, on="key")
                mm = mm[mm["raw"] != mm["dom"]]
                v_n = int(mm["n"].sum())
                v_ex = " ; ".join(f"{d!r} <- {sorted(set(g['raw']))}" for d, g in list(mm.groupby("dom"))[:3])
        row["variant_rows_n"], row["variant_examples"] = v_n, v_ex
        out.append(row)
    return out


# ------------------------------------------- Group 1: column-level findings
def column_findings(df, name, prof):
    n = len(df)
    for r in prof:
        c = r["column"]
        idlike = c.endswith("_id")
        if r["guessed_type"] in ("numeric", "date", "bool"):
            CHECKED_PARSE.add((name, c))
        add(name, 1, "blank_values", c, "WARN" if idlike else "INFO", r["blank_n"], n,
            "blank cells; decide if structural (legitimate) or missing")
        add(name, 1, "null_token_text", c, "WARN", r["null_token_n"], n,
            "literal text like None/NaN that is not read as null; decide meaning")
        add(name, 1, "whitespace", c, "WARN", r["whitespace_n"], n, "leading/trailing/double spaces")
        if r["guessed_type"] == "bool":
            add(name, 1, "unrecognized_boolean", c, "ERROR", r["parse_fail_n"], n, r["parse_fail_examples"])
        else:
            add(name, 1, "unparseable_value", c, "ERROR" if idlike else "WARN", r["parse_fail_n"], n,
                f"fail as {r['guessed_type']} ({r['type_source']}-based): {r['parse_fail_examples']}")
        if idlike:
            add(name, 1, "float_style_id", c, "ERROR", r["float_style_int_n"], n, "IDs like 45.0 will not match 45")
        add(name, 1, "leading_zeros", c, "INFO", r["leading_zero_n"], n, "keep as text or zeros are lost")
        add(name, 1, "currency_or_percent_symbols", c, "WARN", r["symbol_n"], n, "$ , % inside numeric values")
        add(name, 1, "scientific_notation", c, "WARN", r["sci_notation_n"], n,
            "numbers written like 9.9e-05 in a column of plain decimals (parses, but formats inconsistently)")
        add(name, 1, "category_spelling_variants", c, "WARN", r["variant_rows_n"], n,
            "rows using a minority spelling: " + r["variant_examples"])
        if set(c.lower().split("_")) & NONNEG_TOKENS:
            add(name, 1, "negative_values", c, "INFO", r["num_negative_n"], n, "check sign rule for this column")
    k = df.columns[0]
    add(name, 1, "primary_key_duplicates", k, "ERROR", nid(df[k]).duplicated(keep="first").sum(), n,
        f"{k} must be unique (compared after trimming and removing a trailing .0)")
    add(name, 1, "primary_key_blank", k, "ERROR", (~is_present(df[k], strict=True)).sum(), n)


# --------------------------------------------- Group 2: single-table rules
def single_table_generic(df, name):
    n = len(df)
    body = df.columns[1:]
    exact = df.duplicated(subset=list(body), keep="first")
    add(name, 2, "duplicate_rows_ignoring_key", "(all but key)", "WARN", exact.sum(), n,
        "same content under a different key")
    norm = df[body].apply(lambda s: s.str.lower().str.replace(r"[^a-z0-9.\-]", "", regex=True))   # keeps the minus sign
    near = norm.duplicated(keep="first")
    add(name, 2, "near_duplicate_rows", "(all but key)", "WARN", (near & ~exact).sum(), n,
        "identical after case/space/punctuation normalisation (signs are kept)")


def requires(*cols):
    """Skip a table's rules, with an ERROR finding, if an expected column is missing."""
    def deco(fn):
        def wrapper(df, t):
            missing = [c for c in cols if c not in df.columns]
            if missing:
                add(t, 2, "expected_column_missing", ",".join(missing), "ERROR", len(df), len(df), "table rules skipped")
                return
            return fn(df, t)
        return wrapper
    return deco


def _rng(df, t, col, lo=None, hi=None, sev="WARN", grp=1, label="out_of_range"):
    v = P(df, t, col)
    bad = pd.Series(False, index=df.index)
    if lo is not None:
        bad |= v < lo
    if hi is not None:
        bad |= v > hi
    add(t, grp, label, col, sev, bad.sum(), len(df), f"expected {lo}..{hi}; e.g. {examples(df.loc[bad, col])}")


def _regex(df, t, col, pat, sev="WARN", grp=1, label="bad_format"):
    bad = is_present(df[col]) & ~df[col].str.match(pat)
    add(t, grp, label, col, sev, bad.sum(), len(df), f"expected /{pat}/; e.g. {examples(df.loc[bad, col])}")


def _rel(a, b, tol=0.01, floor=1.0):
    """True where |a-b| exceeds max(tol*|b|, floor)."""
    return (a - b).abs() > np.maximum(tol * b.abs(), floor)


@requires("years_experience", "aum_target_mm")
def rules_dim_advisor(df, t):
    _rng(df, t, "years_experience", 0, 50)
    _rng(df, t, "aum_target_mm", 0.0001)


@requires("age", "state", "zip_code", "initial_aum", "client_since")
def rules_dim_client(df, t):
    age = P(df, t, "age")
    impossible = (age < 0) | (age > 120)
    unusual = ((age < 18) | (age > 110)) & ~impossible
    add(t, 1, "age_impossible", "age", "ERROR", impossible.sum(), len(df), "expected 0..120")
    add(t, 1, "age_unusual", "age", "WARN", unusual.sum(), len(df), "expected 18..110")
    _regex(df, t, "state", r"^[A-Z]{2}$")
    _regex(df, t, "zip_code", r"^\d{5}$", label="zip_not_5_digits")
    _rng(df, t, "initial_aum", 0.0001)
    d = P(df, t, "client_since", "date")
    add(t, 1, "future_or_ancient_date", "client_since", "WARN", ((d > AS_OF) | (d < pd.Timestamp("1990-01-01"))).sum(), len(df))


@requires("ticker", "is_etf", "expense_ratio_bps")
def rules_dim_security(df, t):
    _regex(df, t, "ticker", r"^[A-Z]{1,5}$")
    _rng(df, t, "expense_ratio_bps", 0, 300)
    k = df["ticker"].str.strip().str.upper()
    add(t, 2, "duplicate_ticker", "ticker", "WARN", k.duplicated(keep="first").sum(), len(df))
    etf, known = bool_flags(df["is_etf"])
    has = is_present(df["expense_ratio_bps"])
    add(t, 2, "etf_without_expense_ratio", "expense_ratio_bps", "WARN", (known & etf & ~has).sum(), len(df))
    add(t, 2, "non_etf_with_expense_ratio", "expense_ratio_bps", "WARN", (known & ~etf & has).sum(), len(df))
    add(t, 1, "blank_expense_ratio_non_etf", "expense_ratio_bps", "INFO", (known & ~etf & ~has).sum(), len(df),
        "probably legitimate structure (only ETFs have it)")


@requires("date", "year", "month", "quarter")
def rules_dim_date(df, t):
    d = P(df, t, "date", "date")
    n = len(df)
    for col, exp in [("year", d.dt.year), ("month", d.dt.month), ("quarter", d.dt.quarter)]:
        v = P(df, t, col)
        add(t, 2, "contradicts_date", col, "ERROR", ((v != exp) & v.notna() & d.notna()).sum(), n)
    for col, exp in [("day_of_week", d.dt.day_name()), ("month_name", d.dt.month_name())]:
        if col in df:
            add(t, 2, "contradicts_date", col, "ERROR", ((df[col].str.strip() != exp) & d.notna()).sum(), n)
    for col, exp in [("is_month_end", d.dt.is_month_end), ("is_quarter_end", d.dt.is_quarter_end),
                     ("is_year_end", d.dt.is_year_end)]:
        if col in df:
            val, known = bool_flags(df[col])
            add(t, 2, "contradicts_date", col, "ERROR", ((val != exp) & known & d.notna()).sum(), n)
    valid = d.dropna()
    add(t, 2, "duplicate_dates", "date", "ERROR", valid.duplicated().sum(), n, "date must be unique: facts join on it")
    if len(valid):
        missing = len(pd.date_range(valid.min(), valid.max())) - valid.nunique()
        add(t, 2, "calendar_missing_days", "date", "ERROR", missing, n, "days absent between first and last date")
    if "is_trading_day" in df:
        val, known = bool_flags(df["is_trading_day"])
        add(t, 2, "weekend_marked_trading", "is_trading_day", "WARN", ((d.dt.day_of_week >= 5) & val & known).sum(), n)


@requires("amount", "aum_basis", "bps_charged", "fee_date", "fee_type", "client_id")
def rules_fact_fees(df, t):
    n = len(df)
    a, b, f = P(df, t, "amount"), P(df, t, "aum_basis"), P(df, t, "bps_charged")
    exp = b * f / 10000 / 12
    bad = a.notna() & exp.notna() & _rel(a, exp, 0.01, 1.0)
    by_type = df.loc[bad, "fee_type"].str.strip().value_counts().to_dict()
    add(t, 2, "amount_vs_aum_x_bps_div_12", "amount", "WARN", bad.sum(), n,
        f"amount differs >1% from aum_basis*bps/10000/12 (rule applied to every fee_type); by type {by_type}; "
        f"e.g. {examples(df.loc[bad, 'amount'])}")
    _rng(df, t, "bps_charged", 0, 300)
    _rng(df, t, "aum_basis", 0.0001)
    _rng(df, t, "amount", 0)
    P(df, t, "fee_date", "date")
    key = pd.concat([nid(df["client_id"]), df["fee_date"].str.strip(), df["fee_type"].str.strip().str.lower()], axis=1)
    add(t, 2, "duplicate_natural_key", "client_id+fee_date+fee_type", "WARN", key.duplicated(keep="first").sum(), n,
        "one fee per client/month/type expected")


@requires("snapshot_date", "year", "month", "return_ytd", "benchmark_return_ytd", "active_alpha_ytd",
          "cash_pct", "aum", "client_id")
def rules_fact_portfolio_snapshot(df, t):
    n = len(df)
    d = P(df, t, "snapshot_date", "date")
    for col, exp in [("year", d.dt.year), ("month", d.dt.month)]:
        v = P(df, t, col)
        add(t, 2, "contradicts_date", col, "ERROR", ((v != exp) & v.notna() & d.notna()).sum(), n)
    pct = df["return_ytd"].str.contains("%")
    r = P(df, t, "return_ytd")
    r = r.where(~pct, r / 100)                                   # percent text -> decimal, as the cleaner does
    bm, al = P(df, t, "benchmark_return_ytd"), P(df, t, "active_alpha_ytd")
    tol = pd.Series(np.where(pct, 1e-4, 1e-5), index=df.index)
    bad = r.notna() & bm.notna() & al.notna() & ((r - bm - al).abs() > tol)
    add(t, 2, "alpha_not_return_minus_benchmark", "active_alpha_ytd", "WARN", bad.sum(), n,
        f"after converting % rows; tolerance 1e-4 on % rows (2-decimal rounding), 1e-5 elsewhere; e.g. {examples(df.loc[bad, 'active_alpha_ytd'])}")
    add(t, 1, "return_below_minus_100pct", "return_ytd", "ERROR", (r < -1).sum(), n, "a return cannot be below -100%")
    ext = r > 2
    add(t, 1, "extreme_return_ytd", "return_ytd", "WARN", ext.sum(), n,
        "above 2.0 (200%) after converting % rows; consistent with benchmark+alpha, so a plausibility issue (see decision log)")
    _rng(df, t, "cash_pct", 0, 1)
    aum = P(df, t, "aum")
    _rng(df, t, "aum", 0.0001)
    add(t, 1, "aum_exactly_1000", "aum", "INFO", (aum == 1000).sum(), n, "possible AUM floor of 1000.00")
    key = pd.concat([nid(df["client_id"]), df["snapshot_date"].str.strip()], axis=1)
    add(t, 2, "duplicate_natural_key", "client_id+snapshot_date", "WARN", key.duplicated(keep="first").sum(), n)


@requires("txn_type", "security_id", "shares", "price", "amount", "txn_date", "client_id")
def rules_fact_transactions(df, t):
    n = len(df)
    tt = df["txn_type"].str.strip().str.lower()
    trade = tt.isin(TRADE_TYPES)
    add(t, 2, "unknown_txn_type", "txn_type", "WARN", (~tt.isin(KNOWN_TXN_TYPES)).sum(), n,
        f"expected one of {sorted(KNOWN_TXN_TYPES)}; e.g. {examples(df.loc[~tt.isin(KNOWN_TXN_TYPES), 'txn_type'])}")
    sec, shp, prc = (is_present(df[c], strict=True) for c in ("security_id", "shares", "price"))
    add(t, 2, "trade_missing_security_id", "security_id", "ERROR", (trade & ~sec).sum(), n, "Buy/Sell/Dividend needs a security")
    add(t, 2, "trade_missing_shares", "shares", "ERROR", (trade & ~shp).sum(), n)
    add(t, 2, "trade_missing_price", "price", "ERROR", (trade & ~prc).sum(), n)
    non = ~trade & tt.isin(KNOWN_TXN_TYPES)
    add(t, 2, "non_trade_with_security_shares_price", "security_id", "WARN", (non & (sec | shp | prc)).sum(), n,
        "Deposit/Withdrawal/Advisory Fee rows normally have no security, shares or price")
    add(t, 1, "blank_security_on_non_trade", "security_id", "INFO", (non & ~sec).sum(), n,
        "legitimate structure: cash flows and fee debits have no security")
    sh, pr, am = P(df, t, "shares"), P(df, t, "price"), P(df, t, "amount")
    both = sh.notna() & pr.notna() & am.notna()
    bad = both & _rel(am, sh * pr, 0.0, 0.01)                    # amounts are rounded to the cent
    add(t, 2, "amount_vs_shares_x_price", "amount", "WARN", bad.sum(), n,
        f"differs by more than 1 cent; e.g. {examples(df.loc[bad, 'amount'])}")
    _rng(df, t, "shares", 0.0000001)
    _rng(df, t, "price", 0.0000001)
    P(df, t, "txn_date", "date")


TABLE_RULES = {
    "dim_advisor": rules_dim_advisor, "dim_client": rules_dim_client,
    "dim_security": rules_dim_security, "dim_date": rules_dim_date,
    "fact_fees": rules_fact_fees, "fact_portfolio_snapshot": rules_fact_portfolio_snapshot,
    "fact_transactions": rules_fact_transactions,
}


# ------------------------------------------ Group 3: referential integrity
def ri_stats(fact_vals, dim_vals):
    """Raw + normalised match stats. Keys are compared strictly (only empty = blank)."""
    n = len(fact_vals)
    present = is_present(fact_vals, strict=True)
    raw_match = fact_vals[present].isin(set(dim_vals)).sum()
    fn, dn = nid(fact_vals), set(nid(dim_vals))
    norm_ok = present & fn.isin(dn)
    orphan = present & ~fn.isin(dn)
    return dict(n=n, null_key=int((~present).sum()), present=int(present.sum()),
                raw_match=int(raw_match), norm_match=int(norm_ok.sum()),
                orphan_rows=int(orphan.sum()), orphan_keys=int(fn[orphan].nunique()),
                orphan_examples=examples(fn[orphan].drop_duplicates()))


def ri_checks(tables):
    pks = {t: df.columns[0] for t, df in tables.items() if t.startswith("dim_")}
    pk_to_table = {v: k for k, v in pks.items() if k != "dim_date"}
    for t, df in tables.items():
        for c in df.columns:
            if c == df.columns[0]:
                continue
            if c in pk_to_table and pk_to_table[c] != t:
                dim = pk_to_table[c]
                s = ri_stats(df[c], tables[dim][c])
                label = f"{t}.{c} -> {dim}.{c}"
            elif c.endswith("_date") and "dim_date" in tables and t != "dim_date":
                s = ri_stats(df[c], tables["dim_date"]["date"])
                label = f"{t}.{c} -> dim_date.date"
            else:
                continue
            n = s["n"]
            add(t, 3, "orphan_foreign_keys", c, "ERROR", s["orphan_rows"], n,
                f"{label}: {s['orphan_keys']} distinct orphan keys; e.g. {s['orphan_examples']}")
            add(t, 3, "key_format_mismatch", c, "ERROR", s["norm_match"] - s["raw_match"], n,
                f"{label}: matches only after trimming/.0 removal (e.g. 45.0 vs 45)")
            add(t, 3, "null_foreign_key", c, "WARN", s["null_key"], n,
                f"{label}: blank key; legitimate only if the row type has no such entity")
            RI_ROWS.append(dict(relationship=label, fact_rows=n, null_keys=s["null_key"],
                                match_rate_raw_pct=round(100 * s["raw_match"] / max(s["present"], 1), 3),
                                match_rate_normalised_pct=round(100 * s["norm_match"] / max(s["present"], 1), 3),
                                orphan_rows=s["orphan_rows"], distinct_orphan_keys=s["orphan_keys"]))


# -------------------------------------- Group 4: cross-table business rules
def cross_table_checks(tables):
    cl = tables.get("dim_client")
    if cl is None or not {"client_id", "advisor_id", "client_since", "primary_account_type"} <= set(cl.columns):
        return
    ck = nid(cl["client_id"])
    dup = ck.duplicated(keep="first")
    add("dim_client", 4, "duplicate_client_ids_ignored", "client_id", "INFO", dup.sum(), len(cl),
        "cross-table checks use the first row for each client_id")
    c1 = cl[~dup].assign(_k=ck[~dup]).set_index("_k")
    adv_map, since_map = nid(c1["advisor_id"]), to_date(c1["client_since"])
    acct_map = c1["primary_account_type"].str.strip()
    datecols = {"fact_fees": "fee_date", "fact_portfolio_snapshot": "snapshot_date", "fact_transactions": "txn_date"}
    for t, dc in datecols.items():
        df = tables.get(t)
        if df is None or not {"client_id", "advisor_id", dc} <= set(df.columns):
            continue
        m = nid(df["client_id"]).map(adv_map)
        bad = m.notna() & is_present(df["advisor_id"], strict=True) & (m != nid(df["advisor_id"]))
        add(t, 4, "advisor_differs_from_client_advisor", "advisor_id", "WARN", bad.sum(), len(df),
            "fact advisor != dim_client advisor (could be a legit reassignment; verify)")
        early = to_date(df[dc]) < nid(df["client_id"]).map(since_map)
        add(t, 4, "activity_before_client_since", dc, "WARN", early.sum(), len(df))
    snap, fees = tables.get("fact_portfolio_snapshot"), tables.get("fact_fees")
    if snap is not None and "account_type" in snap:
        mapped = nid(snap["client_id"]).map(acct_map)
        add("fact_portfolio_snapshot", 4, "account_type_differs_from_client", "account_type", "WARN",
            (mapped.notna() & (mapped != snap["account_type"].str.strip())).sum(), len(snap),
            "snapshot account_type != dim_client.primary_account_type")
    if snap is not None and fees is not None and {"aum_basis", "fee_type", "fee_date"} <= set(fees) and "aum" in snap:
        f = fees[fees["fee_type"].str.strip().str.lower() == "advisory"]
        fd = pd.DataFrame({"k": nid(f["client_id"]), "d": to_date(f["fee_date"]), "basis": to_num(f["aum_basis"])}).dropna(subset=["k", "d"])
        sd = pd.DataFrame({"k": nid(snap["client_id"]), "d": to_date(snap["snapshot_date"]), "aum": to_num(snap["aum"])}).dropna(subset=["k", "d"])
        add("fact_fees", 4, "duplicate_advisory_fee_keys_ignored", "client_id+fee_date", "INFO", fd.duplicated(["k", "d"]).sum(), len(fd))
        add("fact_portfolio_snapshot", 4, "duplicate_snapshot_keys_ignored", "client_id+snapshot_date", "INFO", sd.duplicated(["k", "d"]).sum(), len(sd))
        j = fd.drop_duplicates(["k", "d"]).merge(sd.drop_duplicates(["k", "d"]), on=["k", "d"])
        if len(j) == 0 and len(fd):
            add("fact_fees", 4, "aum_check_join_empty", "client_id+fee_date", "ERROR", len(fd), len(fd),
                "no Advisory fee matched a snapshot on client and date; the AUM reconciliation did not run")
        bad = _rel(j["basis"], j["aum"], 0.001, 1.0)
        add("fact_fees", 4, "aum_basis_vs_snapshot_aum", "aum_basis", "WARN", bad.sum(), len(j),
            f"Advisory fees whose aum_basis != snapshot aum, same client and date (of {len(j)} matched)")
        add("fact_fees", 4, "advisory_fee_without_snapshot", "client_id+fee_date", "INFO", len(fd.drop_duplicates(["k", "d"])) - len(j), len(fd))


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(find_raw()))
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--tag", default="raw")
    a = ap.parse_args()
    inp, out = Path(a.inp).resolve(), Path(a.out).resolve()
    if inp == out:
        raise SystemExit("--out must be a different folder from --in (output CSVs would be read back as tables)")
    out.mkdir(parents=True, exist_ok=True)
    FINDINGS.clear(); RI_ROWS.clear(); CHECKED_PARSE.clear()
    files = sorted(inp.glob("*.csv"), key=lambda p: (not p.stem.startswith("dim_"), p.stem))
    tables = {p.stem: read_table(p) for p in files}
    print(f"Loaded {len(tables)} tables from {inp}")
    profile = []
    for name, df in tables.items():
        prof = profile_table(df, name)
        profile += prof
        column_findings(df, name, prof)
        single_table_generic(df, name)
        if name in TABLE_RULES:
            TABLE_RULES[name](df, name)
        print(f"  profiled {name}: {len(df):,} rows x {df.shape[1]} cols")
    ri_checks(tables)
    cross_table_checks(tables)
    pd.DataFrame(profile).to_csv(out / f"profile_{a.tag}.csv", index=False)
    cols = ["table", "group", "check", "column", "severity", "rows_affected", "pct_of_rows", "detail"]
    fd = pd.DataFrame(FINDINGS, columns=cols)
    fd["_s"] = fd["severity"].map({"ERROR": 0, "WARN": 1, "INFO": 2})
    fd = fd.sort_values(["table", "group", "_s"]).drop(columns="_s")
    fd.to_csv(out / f"dq_summary_{a.tag}.csv", index=False)
    pd.DataFrame(RI_ROWS).to_csv(out / f"ri_summary_{a.tag}.csv", index=False)
    print("\nFindings by table and severity:")
    if len(fd):
        print(fd.groupby(["table", "severity"]).size().unstack(fill_value=0).to_string())
    else:
        print("  (no findings)")
    print(f"\nSaved profile_{a.tag}.csv, dq_summary_{a.tag}.csv, ri_summary_{a.tag}.csv to {out}")


if __name__ == "__main__":
    main()
