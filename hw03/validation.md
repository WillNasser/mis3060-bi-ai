### 5A — Known-Answer Check: Earnings

| Check | Official Source | Your CSV | Match? |
|---|---|---|---|
| Apple Inc. Q3 2026 Revenue | $109.4 billion | $109.4 billion | Match |
| Apple Inc. Q3 2026 EPS Diluted | $2.02 | $2.02 | Match |

### 5B — Known-Answer Check: Executive Events

| Check | News Source Confirms? | Notes |
|---|---|---|
| Doug Petno, Chief Executive Officer | *Yes | *He was appointed CEO of the Commercial and Investment Bank |
| Appointment | Yes | N/A |
| 6/25/2026 | Yes | N/A |

### 5C — Cross-Validation: Earnings via Yahoo Finance

| Metric | From 8-K text extraction | From yfinance | Match? |
|---|---|---|---|
| Revenue | $109.4  billion | $109.4 billion | Match |
| Net Income | $29.789 billion | $29.789 billion | Match |

### 5D — Pipeline Integrity Checks

| Check | Expected | Actual | Pass/Fail |
|---|---|---|---|
| `earnings_history.csv` row count | Up to 20 (5 companies × 4 quarters) | 20 & Column Titles | Pass |
| `executive_events.csv` row count | At least 0 (document actual) | 29 | Pass |
| `corporate_events_timeline.csv` created | Yes | Yes | Pass |
| Rows with all three fields `"NOT_FOUND"` | 0 (investigate if > 0) | 0 | Pass |

