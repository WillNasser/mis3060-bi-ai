"""
MIS3060 HW03 - Corporate events timeline

Joins hw03/executive_events.csv (8-K Item 5.02 events) to hw03/earnings_history.csv
(8-K Item 2.02 earnings filings) and asks: how close to an earnings announcement do
executive changes happen, and do they come before or after it?

For every executive event:
  1. days_to_nearest_earnings = |event filing_date - nearest earnings filing_date|
     (nearest is searched only among the SAME company's earnings filings)
  2. event_timing = 'same week'      if days_to_nearest_earnings <= 7
                    'before earnings' if the event precedes that nearest earnings filing
                    'after earnings'  if the event follows it
  3. Saves everything to corporate_events_timeline.csv
  4. Prints a per-company summary, then 5. a before/after count across all companies.

Column handling: both source files have company, ticker, cik and filing_date. The
event columns keep their original names; the matched earnings filing's columns are
added with an "earnings_" prefix (earnings_filing_date, earnings_period, ...). The
duplicate company/ticker/cik columns from the earnings side are not repeated.
"""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
SAME_WEEK_DAYS = 7

earnings = pd.read_csv(HERE / "earnings_history.csv", dtype={"cik": str})
events = pd.read_csv(HERE / "executive_events.csv", dtype={"cik": str})
earnings["filing_date"] = pd.to_datetime(earnings["filing_date"])
events["filing_date"] = pd.to_datetime(events["filing_date"])

earn_cols = ["filing_date", "period", "revenue_reported", "eps_diluted", "net_income"]
rows = []
for _, ev in events.iterrows():
    same = earnings[earnings["ticker"] == ev["ticker"]].copy()
    same["gap"] = (ev["filing_date"] - same["filing_date"]).dt.days   # + = event after earnings
    # nearest by absolute gap; on a tie prefer the earlier earnings filing (larger positive gap)
    same = same.assign(abs_gap=same["gap"].abs()).sort_values(["abs_gap", "gap"], ascending=[True, False])
    best = same.iloc[0]
    gap = int(best["gap"])
    if abs(gap) <= SAME_WEEK_DAYS:
        timing = "same week"
    elif gap < 0:
        timing = "before earnings"
    else:
        timing = "after earnings"
    rec = ev.to_dict()
    rec.update({f"earnings_{c}": best[c] for c in earn_cols})
    rec["days_to_nearest_earnings"] = abs(gap)
    rec["event_timing"] = timing
    rows.append(rec)

timeline = pd.DataFrame(rows)
for c in ("filing_date", "earnings_filing_date"):
    timeline[c] = pd.to_datetime(timeline[c]).dt.strftime("%Y-%m-%d")
timeline.to_csv(HERE / "corporate_events_timeline.csv", index=False)
print(f"Saved {len(timeline)} rows to {HERE / 'corporate_events_timeline.csv'}\n")

# ---- per-company summary
print("=" * 78)
print("EXECUTIVE EVENTS RELATIVE TO NEAREST EARNINGS ANNOUNCEMENT")
print("=" * 78)
for company, g in timeline.groupby("company", sort=False):
    print(f"\n{company} ({g['ticker'].iloc[0]}) - {len(g)} event(s)")
    for _, r in g.iterrows():
        print(f"  {r['filing_date']} | {r['event_type']:<11} | {r['person_name']} ({r['title']}) "
              f"-> {r['event_timing']}, {r['days_to_nearest_earnings']} day(s) from "
              f"{r['earnings_filing_date']} earnings")
for t in sorted(set(earnings["ticker"]) - set(timeline["ticker"])):
    print(f"\n{t}: no executive events")

# ---- overall counts
counts = timeline["event_timing"].value_counts()
b, a, s = (int(counts.get(k, 0)) for k in ("before earnings", "after earnings", "same week"))
print("\n" + "=" * 78)
print(f"Across all companies ({len(timeline)} events):")
print(f"  Before earnings announcement: {b}")
print(f"  After earnings announcement:  {a}")
print(f"  Same week (within {SAME_WEEK_DAYS} days): {s}")
print(f"  Excluding same-week events, before vs. after: {b} vs. {a}")
