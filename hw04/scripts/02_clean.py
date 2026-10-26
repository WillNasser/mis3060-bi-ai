#!/usr/bin/env python
"""
HW4 Part C - 02_clean.py
Reads the 8 raw Wildcat Capital tables (never modifies them), applies one
transformation at a time per decision_log.md, checks the after-state of every
step, and only after ALL checks pass writes:
    data/clean/*.csv                      8 clean tables (same names/columns + flag columns)
    data/clean/README_clean.md
    data/audit/cleaning_log.csv           table, issue, action, rows affected, note
    data/audit/value_changes.csv          table, key column, key, column, old, new
    data/audit/quarantine_*.csv           removed rows, with a reason column
    data/audit/run_manifest.csv           run id + SHA-256 of the raw inputs and of every output file

Step order (and why):
  1 Quarantine orphan-client transactions first, so we do not spend repairs on rows that
    will not be in the clean table. Quarantined rows are saved exactly as received.
  2-6 Repairs: security_id format, shares sign, return_ytd %, state names, risk flag.
  7 Verify the "leave as is" decisions (so they are proven, not assumed).
  8 Prove raw = clean + quarantined by ID, that every changed cell is logged with the right key,
    old value and new value, and that each flag column equals its condition in the raw data.
    Then stage everything, verify, and move the files into place (manifest last).

Checks use check() (raises) instead of assert, so python -O cannot switch them off.
Run from the project root:  python scripts/02_clean.py
"""
import argparse
import hashlib
import os
from datetime import datetime
from decimal import Decimal
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

# Numbers claimed in decision_log.md (raw-table counts). Each step checks against them.
EXPECT = dict(orphan_txn_rows=200, orphan_clients=200, float_ids_raw=197175,
              neg_shares_raw=836, pct_returns=300, full_state_names=78, risk_blank=76,
              cert_none=6, extreme_returns=472,   # 471 plain decimals + 1 converted percent row
              wkend_trades_raw=40649, bs_trades_raw=143311, adv_debits_raw=35766, cy_total=10855,
              sci_cells={("fact_portfolio_snapshot", "return_ytd"): 135,
                         ("fact_portfolio_snapshot", "active_alpha_ytd"): 756})
SCI_PATTERN = r"^[-+]?(\d+\.?\d*|\.\d+)[eE][-+]?\d+$"      # 9.9e-05, -1.9E-5, +1e-05, .5e-3, 1.e-5
EXTREME_RETURN = 2.0           # return_ytd above this (200%) is flagged, not changed
CENT = 0.01                   # amounts are rounded to the cent (observed max diff 0.005)
PCT_TOL = 1e-4                 # percent returns are rounded to 2 decimals (worst case ~5.1e-5)
PCT_TOL_CONVERTED = 6e-5       # rows converted from "9.28%" (2-decimal rounding: at most 5.1e-5)
PLAIN_TOL = 2e-6               # rows that were already decimals (6-decimal rounding: at most 1e-6)
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
RISK_VALUES = {"Aggressive", "Balanced", "Conservative", "Moderately Aggressive", "Moderately Conservative"}

CLEAN_LOG, VALUE_CHANGES, QUARANTINE, S = [], [], {}, {}   # S = stats used in README
ADDED_COLS = {"fact_transactions": ["shares_sign_fixed"], "dim_client": ["risk_profile_missing"],
              "fact_portfolio_snapshot": ["return_ytd_extreme"]}

STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}


# ----------------------------------------------------------------- helpers
def check(cond, msg):
    """Like assert, but cannot be removed by python -O. Stops the script on failure."""
    if not bool(cond):
        raise RuntimeError(f"CHECK FAILED: {msg}")


def read_raw(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def num(s):
    """Parse to number: strip $, % and spaces; accept commas only as thousands separators."""
    t = s.str.replace(r"[\$%\s]", "", regex=True)
    ok = ~t.str.contains(",") | t.str.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
    return pd.to_numeric(t.where(ok).str.replace(",", "", regex=False), errors="coerce")


def nid(s):
    return s.str.strip().str.replace(r"\.0+$", "", regex=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def shown(p):
    """Path as printed in the README: relative to the project root when possible."""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def log(table, issue, action, rows, note=""):
    CLEAN_LOG.append(dict(table=table, issue=issue, action=action, rows_affected=int(rows), note=note))
    print(f"[{table}] {issue} -> {action}: {int(rows):,} rows. {note}")


def record_changes(table, df, col, old, new):
    """Log every cell where old != new (key = first column of the table)."""
    key_col = df.columns[0]
    mask = old != new
    VALUE_CHANGES.append(pd.DataFrame({
        "table": table, "key_column": key_col, "key": df.loc[mask, key_col].values,
        "column": col, "old_value": old[mask].values, "new_value": new[mask].values}))
    return int(mask.sum())


# ------------------------------------------------------------------- steps
def step0_id_formats(T):
    """IDs used for joins must already be in canonical form (we normalise only to *compare*)."""
    for t, cols in [("dim_client", ["client_id", "advisor_id"]), ("dim_security", ["security_id", "benchmark_id"]),
                    ("fact_fees", ["client_id", "advisor_id"]),
                    ("fact_portfolio_snapshot", ["client_id", "advisor_id", "benchmark_id"]),
                    ("fact_transactions", ["client_id", "advisor_id"])]:
        for c in cols:
            check((T[t][c] == nid(T[t][c])).all(), f"{t}.{c} has IDs with spaces or a trailing .0")


def step1_quarantine_orphan_clients(T):
    """Issue 4: transactions whose client_id is not in dim_client."""
    tx, ids = T["fact_transactions"], set(T["dim_client"]["client_id"])
    check((tx["client_id"] != "").all(), "blank client_id in fact_transactions")
    orphan = ~tx["client_id"].isin(ids)
    n = int(orphan.sum())
    check(n == EXPECT["orphan_txn_rows"], f"expected {EXPECT['orphan_txn_rows']} orphan rows, got {n}")
    check(tx.loc[orphan, "client_id"].nunique() == EXPECT["orphan_clients"], "distinct orphan clients differ from log")
    q = tx[orphan].copy()
    q["quarantine_reason"] = "client_id not in dim_client"
    q["quarantine_step"] = "step1_orphan_client"
    QUARANTINE["fact_transactions_orphan_client"] = ("fact_transactions", q)
    S["q_float"] = int(q["security_id"].str.match(r"^\d+\.0+$").sum())
    S["q_neg"] = int((num(q["shares"]) < 0).sum())
    s_ids = pd.to_numeric(q["client_id"], errors="coerce")
    S["orphan_min"], S["orphan_max"] = int(s_ids.min()), int(s_ids.max())
    T["fact_transactions"] = tx[~orphan].copy()
    after = T["fact_transactions"]
    check(after["client_id"].isin(ids).all(), "orphans remain after quarantine")
    check(len(tx) == len(after) + len(q), "rows lost in quarantine step")
    log("fact_transactions", "orphan client_id", "quarantine", n,
        f"{q['client_id'].nunique()} distinct client IDs ({S['orphan_min']}-{S['orphan_max']}) not in dim_client; "
        f"saved as received to quarantine_fact_transactions_orphan_client.csv")


def step2_security_id_format(T):
    """Issue 1: 45.0 -> 45."""
    tx = T["fact_transactions"]
    mask = tx["security_id"].str.match(r"^\d+\.0+$")
    n = int(mask.sum())
    expected = EXPECT["float_ids_raw"] - S["q_float"]
    check(n == expected, f"expected {expected} float-style ids after quarantine, got {n}")
    old = tx["security_id"].copy()
    tx["security_id"] = tx["security_id"].where(~mask, tx["security_id"].str.replace(r"\.0+$", "", regex=True))
    check(not tx["security_id"].str.match(r"^\d+\.0+$").any(), "float-style ids remain")
    sec_ids = set(T["dim_security"]["security_id"])
    nonblank = tx["security_id"] != ""
    check(tx.loc[nonblank, "security_id"].isin(sec_ids).all(), "some security_id still not in dim_security")
    changed = record_changes("fact_transactions", tx, "security_id", old, tx["security_id"])
    check(changed == n, "logged changes != rows fixed")
    log("fact_transactions", "security_id stored as 45.0", "standardize", n,
        f"{EXPECT['float_ids_raw']:,} in raw; {S['q_float']} were in quarantined rows; all remaining non-blank IDs now exist in dim_security")


def step3_negative_shares(T):
    """Issue 3: negative shares on Buy rows, confirmed by amount = |shares| x price (to the cent)."""
    tx = T["fact_transactions"]
    trade = tx["txn_type"].isin(["Buy", "Sell", "Dividend"])
    sh, pr, am = num(tx["shares"]), num(tx["price"]), num(tx["amount"])
    check(sh[trade].notna().all() and pr[trade].notna().all() and am[trade].notna().all(),
          "unparseable shares/price/amount on Buy/Sell/Dividend rows")
    mask = sh < 0
    n = int(mask.sum())
    expected = EXPECT["neg_shares_raw"] - S["q_neg"]
    check(n == expected, f"expected {expected} negative-share rows after quarantine, got {n}")
    check((tx.loc[mask, "txn_type"] == "Buy").all(), "negative shares found on non-Buy rows")
    check(tx.loc[mask, "shares"].str.startswith("-").all(), "negative shares with leading spaces")
    check(((sh[mask].abs() * pr[mask] - am[mask]).abs() <= CENT).all(), "amount does not confirm |shares| x price to the cent")
    old = tx["shares"].copy()
    tx["shares"] = tx["shares"].where(~mask, tx["shares"].str.replace(r"^-", "", regex=True))
    tx["shares_sign_fixed"] = mask.astype(int).astype(str)
    sh2 = num(tx["shares"])
    check(not (sh2 < 0).any(), "negative shares remain")
    check(((sh2[trade].abs() * pr[trade] - am[trade]).abs() <= CENT).all(),
          "some Buy/Sell/Dividend rows still disagree with shares x price (to the cent)")
    changed = record_changes("fact_transactions", tx, "shares", old, tx["shares"])
    check(changed == n, "logged changes != rows fixed")
    log("fact_transactions", "negative shares on Buy", "fix (abs) + flag shares_sign_fixed", n,
        f"{EXPECT['neg_shares_raw']} in raw, {S['q_neg']} in quarantined rows; all Buy; amount = |shares| x price confirmed "
        f"within 1 cent; 0 Buy/Sell/Dividend rows now disagree")


def step3b_scientific_notation(T):
    """Issue 12: tiny numbers written as 9.9e-05 -> 0.000099 (exact; same value, consistent format)."""
    found = {}
    for t in TABLES:
        for c in T[t].columns[1:]:
            m = T[t][c].str.strip().str.match(SCI_PATTERN)
            if m.any():
                found[(t, c)] = int(m.sum())
    check(found == EXPECT["sci_cells"], f"scientific-notation cells differ from decision log: found {found}")
    for (t, c), n in found.items():
        df = T[t]
        m = df[c].str.strip().str.match(SCI_PATTERN)
        old = df[c].copy()
        new = df.loc[m, c].str.strip().map(lambda x: format(Decimal(x), "f"))
        check(all(Decimal(a) == Decimal(b) for a, b in zip(new, df.loc[m, c].str.strip())),
              f"{t}.{c}: conversion changed a value")
        S.setdefault("sci_example", {})[c] = (old[m].iloc[0], new.iloc[0])
        df[c] = df[c].where(~m, new)
        check(not df[c].str.strip().str.match(SCI_PATTERN).any(), f"{t}.{c}: scientific notation remains")
        check(record_changes(t, df, c, old, df[c]) == n, "logged changes != rows fixed")
        log(t, f"{c} in scientific notation", "standardize to plain decimal", n,
            f"e.g. {old[m].iloc[0]} -> {df.loc[m, c].iloc[0]}; every converted value is exactly equal as a decimal number (checked with Decimal)")


def step4_return_percent(T):
    """Issue 5: '9.28%' -> 0.092800, reconciled with benchmark + alpha."""
    sn = T["fact_portfolio_snapshot"]
    mask = sn["return_ytd"].str.contains("%")
    n = int(mask.sum())
    check(n == EXPECT["pct_returns"], f"expected {EXPECT['pct_returns']} percent strings, got {n}")
    check(sn.loc[mask, "return_ytd"].str.match(r"^-?\d+(\.\d{1,2})?%$").all(),
          "percent strings with more than 2 decimals; .6f formatting could round them")
    old = sn["return_ytd"].copy()
    conv = (num(sn.loc[mask, "return_ytd"]) / 100).map("{:.6f}".format)
    sn["return_ytd"] = sn["return_ytd"].where(~mask, conv)
    check(not sn["return_ytd"].str.contains("%").any(), "% remains in return_ytd")
    r, b, a = num(sn["return_ytd"]), num(sn["benchmark_return_ytd"]), num(sn["active_alpha_ytd"])
    check(r.notna().all() and b.notna().all() and a.notna().all(),
          "return_ytd / benchmark_return_ytd / active_alpha_ytd has unparseable or blank values")
    diff = (r - b - a).abs()
    S["pct_max_diff"] = float(diff[mask].max())
    S["pct_gt_1e5"] = int((diff[mask] > 1e-5).sum())
    S["nonpct_max_diff"] = float(diff[~mask].max())
    check(diff.max() <= PCT_TOL, f"return - benchmark - alpha differs by up to {diff.max():.6f}")
    check(S["pct_max_diff"] <= PCT_TOL_CONVERTED, f"converted-percent rows differ by up to {S['pct_max_diff']:.6f}")
    check(S["nonpct_max_diff"] <= PLAIN_TOL, f"plain-decimal rows differ by up to {S['nonpct_max_diff']:.6f}")
    changed = record_changes("fact_portfolio_snapshot", sn, "return_ytd", old, sn["return_ytd"])
    check(changed == n, "logged changes != rows fixed")
    log("fact_portfolio_snapshot", "return_ytd as percent text", "convert (strip %, /100)", n,
        f"reconciled to benchmark_return_ytd + active_alpha_ytd: max diff {S['pct_max_diff']:.6f} on converted rows "
        f"(2-decimal rounding), {S['nonpct_max_diff']:.6f} on the others; tolerance {PCT_TOL}")


def step4b_extreme_returns(T):
    """Issue 11: extreme year-to-date returns are flagged, never changed."""
    sn = T["fact_portfolio_snapshot"]
    r, aum = num(sn["return_ytd"]), num(sn["aum"])
    check(r.notna().all() and aum.notna().all(), "unparseable return_ytd or aum")
    check((r > -1).all(), "return_ytd at or below -100%; implied start-of-year AUM would be undefined")
    flag = r > EXTREME_RETURN
    n = int(flag.sum())
    check(n == EXPECT["extreme_returns"], f"expected {EXPECT['extreme_returns']} extreme returns, got {n}")
    sn["return_ytd_extreme"] = flag.astype(int).astype(str)
    # The scale is unambiguous: step 4 proved return_ytd = benchmark + alpha on every row.
    # Evidence for the cause: return_ytd implies one start-of-year AUM per client-year.
    base = aum / (1 + r)
    g = base.groupby([sn["client_id"], sn["year"]]).agg(["std", "mean", "size"])
    g = g[g["size"] >= 6]
    S["cy_total"] = int(len(g))
    S["cy_consistent"] = int(((g["std"] / g["mean"]) < 1e-3).sum())
    S["ext_base_median"] = float(base[flag].median())
    S["ext_base_max"] = float(base[flag].max())
    S["ext_base_le2000"] = float((base[flag] <= 2000).mean())
    S["base_median_all"] = float(base.median())
    S["aum_floor_rows"] = int((aum == 1000).sum())
    S["aum_floor_clients"] = int(sn.loc[aum == 1000, "client_id"].nunique())
    S["extreme_clients"] = int(sn.loc[flag, "client_id"].nunique())
    S["extreme_max"] = float(r.max())
    S["neg_below_half"] = int((r < -0.5).sum())
    S["ret_min"] = float(r.min())
    check(S["cy_total"] == EXPECT["cy_total"], f"client-years with 6+ snapshots: {S['cy_total']}, log says {EXPECT['cy_total']}")
    check(S["cy_consistent"] == S["cy_total"],
          f"return_ytd implies a constant start-of-year AUM in only {S['cy_consistent']} of {S['cy_total']} client-years; "
          f"the 'AUM growth' explanation in the log/README would be wrong")
    check(S["ext_base_median"] < 0.05 * S["base_median_all"], "implied start-of-year AUM on flagged rows is not small")
    check(float(aum.min()) == 1000.0 and S["aum_floor_rows"] > 0, "AUM minimum is not exactly 1000.00; 'floor' wording would be wrong")
    log("fact_portfolio_snapshot", f"return_ytd above {EXTREME_RETURN}", "flag return_ytd_extreme (values unchanged)", n,
        f"{S['extreme_clients']} clients, max {S['extreme_max']:.2f}; in {S['cy_consistent']:,} of {S['cy_total']:,} client-years "
        f"return_ytd implies a constant start-of-year AUM (so it is AUM growth incl. cash flows); "
        f"on flagged rows the implied start-of-year AUM has median {S['ext_base_median']:,.0f} (max {S['ext_base_max']:,.0f}) "
        f"vs {S['base_median_all']:,.0f} across all rows; "
        f"{S['aum_floor_rows']} snapshot rows have AUM of exactly 1000.00, the minimum in the table ({S['aum_floor_clients']} clients)")


def step5_state_codes(T):
    """Issue 6: full state names -> 2-letter codes."""
    cl = T["dim_client"]
    mask = ~cl["state"].str.match(r"^[A-Z]{2}$")
    n = int(mask.sum())
    check(n == EXPECT["full_state_names"], f"expected {EXPECT['full_state_names']} full names, got {n}")
    mapped = cl.loc[mask, "state"].map(STATE_CODES)
    check(mapped.notna().all(), f"unmapped state names: {cl.loc[mask, 'state'][mapped.isna()].unique()}")
    old = cl["state"].copy()
    cl["state"] = cl["state"].where(~mask, mapped)
    check(cl["state"].str.match(r"^[A-Z]{2}$").all(), "state not 2 uppercase letters after fix")
    check(set(cl["state"]) <= set(STATE_CODES.values()), "state contains an invalid code")
    changed = record_changes("dim_client", cl, "state", old, cl["state"])
    check(changed == n, "logged changes != rows fixed")
    log("dim_client", "state as full name", "standardize to 2-letter code", n,
        f"{cl['state'].nunique()} distinct states now, all valid codes")


def step6_risk_flag(T):
    """Issue 7: blank risk_profile -> flag, no fill."""
    cl = T["dim_client"]
    blank = cl["risk_profile"].str.strip() == ""
    n = int(blank.sum())
    check(n == EXPECT["risk_blank"], f"expected {EXPECT['risk_blank']} blank risk profiles, got {n}")
    check(set(cl.loc[~blank, "risk_profile"]) <= RISK_VALUES, "unexpected risk_profile category")
    # whitespace-only values count as blank: make them truly blank so a BI tool agrees with the flag
    old = cl["risk_profile"].copy()
    cl["risk_profile"] = cl["risk_profile"].where(~blank, "")
    ws_fixed = record_changes("dim_client", cl, "risk_profile", old, cl["risk_profile"])
    check((cl.loc[blank, "risk_profile"] == "").all(), "blank risk_profile values are not empty strings")
    cl["risk_profile_missing"] = blank.astype(int).astype(str)
    log("dim_client", "risk_profile blank", "flag risk_profile_missing (not filled)", n,
        f"{100 * n / len(cl):.2f}% of {len(cl):,} clients; {ws_fixed} whitespace-only values set to empty")


def step7_verify_leave_as_is(T, RAW):
    """Issues 2, 8, 9, 10: prove the 'leave as is' decisions."""
    tx = T["fact_transactions"]
    # Issue 2
    blank_sec = tx["security_id"] == ""
    check(set(tx.loc[blank_sec, "txn_type"]) <= {"Advisory Fee", "Deposit", "Withdrawal"}, "blank security_id on a trade row")
    check(((tx["shares"] == "") == blank_sec).all() and ((tx["price"] == "") == blank_sec).all(),
          "shares/price blanks do not line up with security_id blanks")
    check((tx.loc[tx["txn_type"].isin(["Buy", "Sell", "Dividend"]), ["security_id", "shares", "price"]] != "").all().all(),
          "blank in Buy/Sell/Dividend rows")
    log("fact_transactions", "blank security_id/shares/price", "leave as is", blank_sec.sum(),
        "all on Advisory Fee/Deposit/Withdrawal; Buy/Sell/Dividend rows have none blank")
    # Issue 8
    cl = T["dim_client"].set_index("client_id")["client_since"]
    for t, col in [("fact_fees", "fee_date"), ("fact_portfolio_snapshot", "snapshot_date")]:
        df = T[t]
        since_raw = df["client_id"].map(cl)
        check(since_raw.notna().all(), f"{t} has client_ids missing from dim_client")
        since = pd.to_datetime(since_raw, format="%Y-%m-%d")
        d = pd.to_datetime(df[col], format="%Y-%m-%d")
        early = d < since
        check(early.any(), f"{t}: no early rows; log entry would be wrong")
        gap = (since - d)[early].dt.days
        check(gap.max() <= 30, f"{t}: activity more than 30 days before client_since")
        check((d[early].dt.day == 1).all(), f"{t}: early rows not dated the 1st of the month")
        S[f"early_{t}"], S[f"early_gap_max_{t}"] = int(early.sum()), int(gap.max())
        log(t, f"{col} before client_since", "leave as is", early.sum(),
            f"max gap {int(gap.max())} days, median {gap.median():.0f}; all dated the 1st of a month (month-start billing)")
    # Issue 13: Buy/Sell dated on non-trading days (in dim_date a trading day is simply a weekday)
    tdm = T["dim_date"].set_index("date")["is_trading_day"]
    check(tdm.index.is_unique, "dim_date.date not unique")
    check(((tdm == "1") == (pd.to_datetime(tdm.index, format="%Y-%m-%d").dayofweek < 5)).all(),
          "is_trading_day is not simply 'weekday'; log wording would be wrong")
    def weekend_counts(df):
        b = df[df["txn_type"].isin(["Buy", "Sell"])]
        t_ = b["txn_date"].map(tdm)
        check(t_.notna().all(), "Buy/Sell dated outside dim_date")
        return b, int((t_ == "0").sum()), len(b)
    _, w_raw, n_raw = weekend_counts(RAW["fact_transactions"])
    check((w_raw, n_raw) == (EXPECT["wkend_trades_raw"], EXPECT["bs_trades_raw"]),
          f"weekend Buy/Sell in raw: {w_raw} of {n_raw}; decision log says {EXPECT['wkend_trades_raw']} of {EXPECT['bs_trades_raw']}")
    bs, S["wkend_trades"], S["bs_trades"] = weekend_counts(tx)
    S["wkend_raw"], S["bs_raw"] = w_raw, n_raw
    dow_share = pd.to_datetime(bs["txn_date"], format="%Y-%m-%d").dt.day_of_week.value_counts(normalize=True)
    check(len(dow_share) == 7, "Buy/Sell rows do not fall on all seven days of the week")
    S["dow_min"], S["dow_max"] = float(dow_share.min()), float(dow_share.max())
    check(0.12 <= S["dow_min"] and S["dow_max"] <= 0.17, "Buy/Sell rows are not spread evenly over the week (each day should be near 1/7)")
    log("fact_transactions", "Buy/Sell dated on a non-trading day", "leave as is", S["wkend_trades"],
        f"{100 * S['wkend_trades'] / S['bs_trades']:.1f}% of {S['bs_trades']:,} Buy/Sell rows after quarantine ({S['wkend_raw']:,} of {S['bs_raw']:,} in raw); "
        f"each day of the week holds {100 * S['dow_min']:.1f}%-{100 * S['dow_max']:.1f}% of them (even spread), "
        f"true trade dates cannot be recovered, so dates are not changed")
    # Issue 14: Advisory Fee debits do not reconcile to fact_fees
    at = tx[tx["txn_type"] == "Advisory Fee"]
    af = T["fact_fees"][T["fact_fees"]["fee_type"] == "Advisory"]
    check(int((RAW["fact_transactions"]["txn_type"] == "Advisory Fee").sum()) == EXPECT["adv_debits_raw"],
          "Advisory Fee debits in raw differ from the decision log")
    check(num(at["amount"]).notna().all() and num(af["amount"]).notna().all(), "unparseable Advisory amounts")
    # fact_fees follows the fee schedule: amount = aum_basis x bps_charged / 10000 / 12 (to the cent)
    fa, fb, fm = num(af["aum_basis"]), num(af["bps_charged"]), num(af["amount"])
    check(fa.notna().all() and fb.notna().all(), "unparseable aum_basis/bps_charged on Advisory fees")
    check(((fa * fb / 10000 / 12 - fm).abs() <= CENT).all(), "Advisory fees do not follow aum_basis x bps / 12")
    g1 = at.assign(m=at["txn_date"].str[:7], a=num(at["amount"])).groupby(["client_id", "m"])["a"].sum()
    g2 = af.assign(m=af["fee_date"].str[:7], a=num(af["amount"])).groupby(["client_id", "m"])["a"].sum()
    both = pd.concat([g1.rename("t"), g2.rename("f")], axis=1).dropna()
    S["adv_txn_n"], S["adv_fee_n"], S["adv_both"] = len(at), len(af), len(both)
    S["adv_match"] = int(((both["t"] - both["f"]).abs() <= CENT).sum())
    check((both["f"] > 0).all(), "a client-month has an Advisory fee of 0 or less")
    S["adv_ratio"] = float((both["t"] / both["f"]).median())
    S["adv_txn_total"], S["adv_fee_total"] = float(num(at["amount"]).sum()), float(num(af["amount"]).sum())
    S["adv_total_ratio"] = S["adv_txn_total"] / S["adv_fee_total"]
    check(S["adv_both"] > 0 and S["adv_match"] == 0, "Advisory Fee reconciliation result changed; log wording would be wrong")
    check(S["adv_total_ratio"] > 1.5, "Advisory debits total is close to the fees total; 'does not reconcile' wording would be wrong")
    log("fact_transactions", "Advisory Fee debits vs fact_fees Advisory fees (rows_affected = client-months compared)", "leave as is", S["adv_both"],
        f"no client-month matches to the cent (0 of {S['adv_both']:,}); debits are a median {S['adv_ratio']:.2f}x the fees; "
        f"total debits {S['adv_txn_total']:,.0f} vs total Advisory fees {S['adv_fee_total']:,.0f} ({S['adv_total_ratio']:.1f}x); "
        f"fact_fees amounts follow aum_basis x bps_charged / 12 to the cent, the debits have no such rule here, so they are treated as separate figures")
    # Issue 9
    sec = T["dim_security"]
    etf = sec["is_etf"].str.lower() == "true"
    check((sec.loc[sec["asset_class"] == "Equity", "sector"] != "").all(), "Equity security with blank sector")
    check((sec.loc[sec["asset_class"] != "Equity", "sector"] == "").all(), "non-equity security with a sector")
    check((sec.loc[etf, "expense_ratio_bps"] != "").all() and (sec.loc[~etf, "expense_ratio_bps"] == "").all(),
          "expense_ratio_bps does not line up with is_etf")
    log("dim_security", "blank sector", "leave as is", (sec["sector"] == "").sum(),
        "blank only for non-equity securities; filled for every Equity")
    log("dim_security", "blank expense_ratio_bps", "leave as is", (sec["expense_ratio_bps"] == "").sum(),
        "blank only for non-ETFs; filled for every ETF")
    # Issue 10
    cert = T["dim_advisor"]["certifications"]
    check((cert == "None").sum() == EXPECT["cert_none"], "count of 'None' certifications differs from log")
    log("dim_advisor", "certifications = 'None'", "leave as is", (cert == "None").sum(),
        "means no certification; keep as text, read files with keep_default_na=False")


def step8_verify_all(T, RAW):
    """The row, change-log and flag proofs happen here, before anything is written."""
    vc = pd.concat(VALUE_CHANGES, ignore_index=True) if VALUE_CHANGES else pd.DataFrame(
        columns=["table", "key_column", "key", "column", "old_value", "new_value"])
    q_by_table = {t: [] for t in TABLES}
    for name, (t, q) in QUARANTINE.items():
        q_by_table[t].append(q)
    print("\nRow reconciliation by ID (raw = clean + quarantined):")
    recon = []
    for t in TABLES:
        raw, clean = RAW[t], T[t]
        k = raw.columns[0]
        check(list(clean.columns[:raw.shape[1]]) == list(raw.columns), f"{t}: original columns changed")
        check(set(clean.columns) - set(raw.columns) == set(ADDED_COLS.get(t, [])), f"{t}: unexpected columns")
        check(raw[k].is_unique and clean[k].is_unique, f"{t}: primary key not unique")
        qs = pd.concat(q_by_table[t], ignore_index=True) if q_by_table[t] else raw.iloc[0:0]
        check(qs[k].is_unique, f"{t}: duplicate keys in quarantine")
        raw_ids, clean_ids, q_ids = set(raw[k]), set(clean[k]), set(qs[k])
        check(not (clean_ids & q_ids), f"{t}: a row is both clean and quarantined")
        check(clean_ids | q_ids == raw_ids and len(raw) == len(clean) + len(qs),
              f"{t}: clean + quarantined IDs do not equal raw IDs")
        # quarantined rows must be exactly as received
        if len(qs):
            check(qs[list(raw.columns)].set_index(k).equals(raw.set_index(k).loc[qs[k]]),
                  f"{t}: quarantined rows differ from raw")
        # every changed cell is logged with the right key, old and new value
        r, c = raw.set_index(k).loc[clean[k]], clean.set_index(k)
        for col in raw.columns[1:]:
            m = (r[col] != c[col]).values
            actual = pd.DataFrame({"key": c.index[m], "old": r[col].values[m], "new": c[col].values[m]})
            lg = vc[(vc["table"] == t) & (vc["column"] == col)]
            logged = pd.DataFrame({"key": lg["key"].values, "old": lg["old_value"].values, "new": lg["new_value"].values})
            check(len(actual) == len(logged), f"{t}.{col}: {len(actual)} cells differ but {len(logged)} logged")
            if len(actual):
                j = actual.merge(logged, on=["key", "old", "new"], how="outer", indicator=True)
                check((j["_merge"] == "both").all(), f"{t}.{col}: logged keys/old/new values do not match the actual changes")
        check(set(vc.loc[vc["table"] == t, "column"]) <= set(raw.columns), f"{t}: change logged for a non-original column")
        # flag columns must equal the condition they claim, recomputed from the RAW values
        rr = raw.set_index(k).loc[clean[k]]
        for fc in ADDED_COLS.get(t, []):
            check(set(c[fc]) <= {"0", "1"}, f"{t}.{fc}: flag has values other than 0/1")
            if fc == "shares_sign_fixed":
                want = num(rr["shares"]) < 0
            elif fc == "risk_profile_missing":
                want = rr["risk_profile"].str.strip() == ""
            else:                                           # return_ytd_extreme
                rv = num(rr["return_ytd"])
                want = rv.where(~rr["return_ytd"].str.contains("%"), rv / 100) > EXTREME_RETURN
            check(((c[fc] == "1").values == want.values).all(), f"{t}.{fc}: flag does not match the raw-data condition")
        recon.append((t, len(raw), len(clean), len(qs)))
        print(f"  {t:26s} raw {len(raw):>8,} = clean {len(clean):>8,} + quarantined {len(qs):>4,}")
        log(t, "row reconciliation", "verify raw = clean + quarantined (by ID)", len(raw),
            f"raw {len(raw)} = clean {len(clean)} + quarantined {len(qs)}; all changed cells logged with matching key/old/new")
    S["zip_leading_zero"] = int(T["dim_client"]["zip_code"].str.startswith("0").sum())
    return vc, recon


def step9_write(T, vc, recon, clean_dir, audit_dir, raw_dir, raw_hashes):
    clean_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    # Old files from earlier runs must not sit beside the new ones (the README says "every removed row is in quarantine_*.csv").
    this_run = {f"quarantine_{n}.csv" for n in QUARANTINE}
    stale = [p.name for p in audit_dir.glob("quarantine_*.csv") if p.name not in this_run]
    check(not stale, f"old quarantine files in {audit_dir} not from this run: {stale}; move them away and re-run")
    out_clean = {f"{t}.csv" for t in TABLES} | {"README_clean.md"}
    extra = [p.name for p in clean_dir.iterdir() if p.is_file() and p.name not in out_clean]
    check(not extra, f"unexpected files in {clean_dir}: {extra}; move them away and re-run")
    # Stage each output folder inside itself (same drive, so the final move cannot fail on a different drive).
    sc, sa = clean_dir / ".stage", audit_dir / ".stage"
    for d in (sc, sa):
        leftover = [p for p in d.rglob("*") if p.is_file()] if d.exists() else []
        check(not leftover, f"leftover files in staging folder {d} from a failed run; inspect and remove it, then re-run")
        d.mkdir(parents=True, exist_ok=True)
    kw = dict(index=False, encoding="utf-8", lineterminator="\n")
    for t in TABLES:
        T[t].to_csv(sc / f"{t}.csv", **kw)
    vc.to_csv(sa / "value_changes.csv", **kw)
    for name, (t, q) in QUARANTINE.items():
        q.to_csv(sa / f"quarantine_{name}.csv", **kw)
    pd.DataFrame(CLEAN_LOG).to_csv(sa / "cleaning_log.csv", **kw)
    write_readme(sc, recon, clean_dir, audit_dir)
    staged = [(p, clean_dir / p.name) for p in sorted(sc.iterdir()) if p.is_file()] + \
             [(p, audit_dir / p.name) for p in sorted(sa.iterdir()) if p.is_file()]
    check(len([1 for p, _ in staged if p.parent == sc]) == len(out_clean), "staged clean folder is incomplete")
    check(len([1 for p, _ in staged if p.parent == sa]) == 2 + len(QUARANTINE), "staged audit folder is incomplete")
    # Manifest: run id + hashes of the raw inputs and of every output. It is moved last, so an old manifest
    # next to new files (a run that stopped half-way) is detectable: the hashes would not match.
    rows = [dict(run_id=RUN_ID, role="raw_input", file=f"{t}.csv", bytes=(raw_dir / f"{t}.csv").stat().st_size, sha256=raw_hashes[t])
            for t in TABLES]
    rows += [dict(run_id=RUN_ID, role="output", file=shown(dst), bytes=src.stat().st_size, sha256=sha256(src)) for src, dst in staged]
    pd.DataFrame(rows).to_csv(sa / "run_manifest.csv", **kw)
    staged.append((sa / "run_manifest.csv", audit_dir / "run_manifest.csv"))
    # The raw files must be byte-for-byte what we read at the start (checked BEFORE touching any output).
    check(all(sha256(raw_dir / f"{t}.csv") == raw_hashes[t] for t in TABLES), "a raw file changed while the script was running")
    # Pre-flight: every destination that exists must be writable (e.g. not open in Excel). Nothing has moved yet.
    locked = []
    for _, dst in staged:
        if dst.exists():
            try:
                with open(dst, "r+b"):
                    pass
            except OSError:
                locked.append(dst.name)
    check(not locked, f"these output files cannot be overwritten (open in Excel?): {locked}; close them and re-run. No output was changed.")
    moved = []
    try:
        for src, dst in staged:
            os.replace(src, dst)                                 # replaces a file of the same name
            moved.append(dst.name)
    except OSError as e:
        raise RuntimeError(f"STOPPED WHILE MOVING OUTPUTS ({e}). Already replaced: {moved}. The output folders now mix "
                           f"files from this run and an earlier one. Fix the cause and re-run before using any output.") from e
    for src, dst in staged:
        if dst.name != "run_manifest.csv":
            check(sha256(dst) == next(r["sha256"] for r in rows if r["role"] == "output" and r["file"] == shown(dst)),
                  f"{dst.name} differs from what was staged")
    check(all(sha256(raw_dir / f"{t}.csv") == raw_hashes[t] for t in TABLES), "a raw file changed during the run")
    for d in (sc, sa):
        try:
            d.rmdir()
        except OSError:
            print(f"note: could not remove the empty folder {d}; it is harmless and is reused next run")
    print(f"\nRun {RUN_ID}: wrote {len(TABLES)} clean tables + README_clean.md to {clean_dir}")
    print(f"Wrote cleaning_log.csv, value_changes.csv ({len(vc):,} cells), {len(QUARANTINE)} quarantine file(s), run_manifest.csv to {audit_dir}")
    print("Raw files verified unchanged (SHA-256 before and after).")


def write_readme(out_dir, recon, clean_dir, audit_dir):
    rows = "\n".join(f"| {t} | {a:,} | {b:,} | {c:,} |" for t, a, b, c in recon)
    txt = f"""# Clean Wildcat Capital tables: README

Produced by `scripts/02_clean.py` (run {RUN_ID}) from the raw files. The script hashes the raw files (SHA-256) before and after
and stops if they differ; the hashes of the inputs and of every output are in `{shown(audit_dir)}/run_manifest.csv`.
Every changed value is in `{shown(audit_dir)}/value_changes.csv`; every removed row is in `{shown(audit_dir)}/quarantine_*.csv`.

## Row accounting
| Table | Raw rows | Clean rows | Quarantined |
|---|---:|---:|---:|
{rows}

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
- **Text (not number):** dim_client.zip_code ({S['zip_leading_zero']} zips start with 0), all names, tickers, city, state, certifications (the value "None" is real, not null)
- **Whole number:** all `*_id` columns, years, months, age, quarter, week_of_year, years_experience, the 0/1 flag columns and is_* date flags
- **Date:** dim_date.date, dim_client.client_since, fee_date, snapshot_date, txn_date
- **Decimal:** amounts, aum, aum_basis, price, shares, bps_charged, initial_aum, returns and alpha, cash_pct, expense_ratio_bps
- **True/False:** dim_client.is_active, dim_security.is_etf
- Blanks in shares, price, security_id, sector and expense_ratio_bps are **structural** (see below), not missing data

## Flag columns added
- `fact_transactions.shares_sign_fixed`: 1 if the raw shares value was negative and was converted to its absolute value (confirmed against amount = shares x price to the cent)
- `dim_client.risk_profile_missing`: 1 if risk_profile was blank in the raw data (value not filled)
- `fact_portfolio_snapshot.return_ytd_extreme`: 1 if return_ytd is above {EXTREME_RETURN} ({EXTREME_RETURN * 100:.0f}%); the value itself is unchanged. A flag means "do not trust as an investment return", not "wrong"

## Known limitations (not fixed, and why)
- **risk_profile blank for {EXPECT['risk_blank']} clients:** it cannot be inferred from other columns, so it is flagged and left blank.
- **{S['early_fact_fees']:,} fee rows and {S['early_fact_portfolio_snapshot']:,} snapshot rows are dated before client_since:** by at most {max(S['early_gap_max_fact_fees'], S['early_gap_max_fact_portfolio_snapshot'])} days, always the 1st of a month; consistent with month-start billing, so left alone.
- **Blank security_id, shares and price on Advisory Fee, Deposit and Withdrawal rows:** correct by design (no security involved).
- **Blank sector (non-equity) and expense_ratio_bps (non-ETF):** not applicable, not missing.
- **{EXPECT['orphan_txn_rows']} transactions for client IDs not in dim_client were quarantined:** if those clients exist elsewhere, restore them from the quarantine file.
- **{EXPECT['extreme_returns']} snapshot rows ({S['extreme_clients']} clients) have return_ytd above {EXTREME_RETURN}, up to {S['extreme_max']:.2f}:** flagged, not changed. In {S['cy_consistent']:,} of {S['cy_total']:,} client-years (6+ snapshots) return_ytd implies one constant start-of-year AUM, so it is AUM growth including deposits and withdrawals, not a time-weighted investment return. On the flagged rows the implied start-of-year AUM is small: median {S['ext_base_median']:,.0f} (maximum {S['ext_base_max']:,.0f}, {100 * S['ext_base_le2000']:.0f}% at or below 2,000) versus a median of {S['base_median_all']:,.0f} across all rows. {S['aum_floor_rows']} snapshot rows ({S['aum_floor_clients']} clients) have AUM of exactly 1000.00, which is also the minimum in the table (a floor). Averages of return_ytd and active_alpha_ytd will be skewed; use the flag or medians.
- **{S['wkend_trades']:,} of {S['bs_trades']:,} Buy/Sell rows ({100 * S['wkend_trades'] / S['bs_trades']:.1f}%) are dated on a weekend:** each day of the week holds {100 * S['dow_min']:.1f}%-{100 * S['dow_max']:.1f}% of the Buy/Sell rows (and dim_date treats every weekday as a trading day), so the dates look synthetic. In the raw table it was {S['wkend_raw']:,} of {S['bs_raw']:,}. The true trade dates cannot be recovered, so they are left as is; do not use transaction dates for settlement or trading-calendar analysis.
- **Advisory Fee debits in fact_transactions do not reconcile to Advisory fees in fact_fees:** 0 of {S['adv_both']:,} client-months with both match to the cent; the debits are a median {S['adv_ratio']:.2f}x the fees ({S['adv_txn_n']:,} debits totalling {S['adv_txn_total']:,.0f} vs {S['adv_fee_n']:,} fees totalling {S['adv_fee_total']:,.0f}). The debits total {S['adv_total_ratio']:.1f}x the fees. fact_fees amounts equal aum_basis x bps_charged / 10000 / 12 to the cent (checked for every Advisory fee), the debits have no such rule here, so use fact_fees for fee revenue and treat the debits as separate figures.
- **Scientific notation:** {EXPECT['sci_cells'][('fact_portfolio_snapshot', 'return_ytd')]} return_ytd and {EXPECT['sci_cells'][('fact_portfolio_snapshot', 'active_alpha_ytd')]} active_alpha_ytd values written like {S['sci_example']['return_ytd'][0]} were rewritten as plain decimals ({S['sci_example']['return_ytd'][1]}). The values are exactly equal (checked with Decimal for every cell); only the text format changed.
- **Negative returns are not flagged:** {S['neg_below_half']:,} rows are below -50% (minimum {S['ret_min']:.3f}). Because return_ytd is AUM growth since the start of the year, these mean AUM fell by more than half (consistent with withdrawals, which this data cannot confirm); they are left as is.
- **Scale of return_ytd:** plain values are decimals (0.99 = 99%). This is verified, because return_ytd = benchmark_return_ytd + active_alpha_ytd holds on every row within {PCT_TOL}.
- **return_ytd converted from percent text:** values were rounded to 2 decimals in the source, so return - benchmark - alpha differs by up to {S['pct_max_diff']:.6f} on those {EXPECT['pct_returns']} rows (tolerance {PCT_TOL}).
"""
    (out_dir / "README_clean.md").write_text(txt, encoding="utf-8")


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(find_raw()))
    ap.add_argument("--clean", default=str(ROOT / "data" / "clean"))
    ap.add_argument("--audit", default=str(ROOT / "data" / "audit"))
    a = ap.parse_args()
    raw_dir, clean_dir, audit_dir = Path(a.raw).resolve(), Path(a.clean).resolve(), Path(a.audit).resolve()
    for name, d in [("clean", clean_dir), ("audit", audit_dir)]:
        check(d != raw_dir and raw_dir not in d.parents and d not in raw_dir.parents,
              f"--{name} folder must not be, or contain, or sit inside the raw folder")
    for lst in (CLEAN_LOG, VALUE_CHANGES):
        lst.clear()
    QUARANTINE.clear()
    S.clear()
    raw_hashes = {t: sha256(raw_dir / f"{t}.csv") for t in TABLES}
    RAW = {t: read_raw(raw_dir / f"{t}.csv") for t in TABLES}
    T = {t: df.copy() for t, df in RAW.items()}
    print("Loaded raw:", ", ".join(f"{t} {len(df):,}" for t, df in RAW.items()), "\n")
    for step in (step0_id_formats, step1_quarantine_orphan_clients, step2_security_id_format,
                 step3_negative_shares, step3b_scientific_notation, step4_return_percent, step4b_extreme_returns, step5_state_codes,
                 step6_risk_flag):
        step(T)
    step7_verify_leave_as_is(T, RAW)
    vc, recon = step8_verify_all(T, RAW)
    print("\nAll checks passed. Writing outputs...")
    step9_write(T, vc, recon, clean_dir, audit_dir, raw_dir, raw_hashes)


if __name__ == "__main__":
    main()
