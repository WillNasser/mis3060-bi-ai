# HW03 — AI Usage Log

**Tool:** Claude Cowork (three separate sessions, one per script)
**Pipeline result:** 20 earnings rows (4 per company × 5 companies), 28 executive events, 28-row combined timeline.

---

## 1. Prompts sent to Claude Cowork

### Specification A — earnings (`hw03/hw03_earnings.py`)

I rewrote Spec A to include the five companies and their CIKs and resent it. The final version:

```
Write me a python script that completes the following actions:

1) Sets the SEC EDGAR User-Agent header to "MIS3060 Villanova wnasser@villanova.edu" on all HTTP requests
2) For each of the five companies (Apple Inc.(Ticker: AAPL, CIK: 0000320193), Microsoft Corporation(Ticker: MSFT, CIK: 0000789019), NVIDIA Corporation(Ticker: NVDA, CIK: 0001045810), JPMorgan Chase & Co.(Ticker: JPM, CIK: 0000019617), Walmart Inc.(Ticker: WMT, CIK: 0000104169)), queries the EDGAR submissions API at https://data.sec.gov/submissions/CIK{cik}.json and filters for 8-K filings where the items field contains "2.02" (Results of Operations)
3) Selects the most recent four such filings per company (one per quarter)
4) For each filing, constructs the filing index URL, identifies the earnings press release exhibit (.htm file), downloads it, and strips HTML to plain text
5) Extracts from the plain text: quarterly revenue (as a numebr in millions or billions), diluted EPS, net income, and the reporting period (e.g., "fourth quarter fiscal 2024")
6) Prints the extracted row for each filing as it is processed, in the format: [Ticker] | [Period] | Revenue: $X | EPS: $X | Net Income: $X
7) Saves all rows to hw03/earnings_history.csv with columns: company, ticker, cik, filing_date, period, revenue_reported, eps_diluted, net_income
8) Where a field cannot be extracted (regex returns no match), stores the string "NOT_FOUND" rather than leaving the cell blank - blank cells and missing data are two different things

Save the generated script as hw03/hw03_earnings.py
```

### Specification B — executive events (`hw03/hw03_executives.py`)

```
Write me a python script that completes the following actions:

1) Sets the same EDGAR User-Agent header on all requests
2) For each of the five companies, queries the EDGAR submissions API and filters for 8-K filings where the items field contains "5.02" (Departure of Directors or Officers), and the filingDate is within the past 12 months
3) For each matching filing, downloads the full 8-K text, strips HTML, and extracts: event type ("departure" or "appointment" or "both"), the person's full name, their title, and the effective date of the change
4) If a filing reports multiple events (e.g., one departure and one appointment), creates a separate row for each event
5) Prints each extracted event as it is processed: [Ticker] | [Date] | [Event Type] | [Name] | [Title]
6) If no item 5.02 filings are found for a company in the past 12 months, prints [Ticker]: No executive events in the past 12 months - this is valid data, not an error
7) Saves all events to hw03/executive_events.csv with columns: company, ticker, cik, filing_date, event_type, person_name, title, effective_date

save the generated program as hw03/hw03_executives.py
```

### Timeline prompt (`hw03/hw03_timeline.py`)

```
Write a Python script that reads `hw03/earnings_history.csv` and `hw03/executive_events.csv`. Do the following:
1. For each executive event in the events table, calculate the number of days between the executive event's `filing_date` and the nearest earnings filing date for the same company in the earnings table. Call this `days_to_nearest_earnings`. 2. Add a column `event_timing` that categorizes each executive event as: `'before earnings'` if the event came before the nearest earnings filing, `'after earnings'` if it came after, or `'same week'` if within 7 days of an earnings filing. 3. Save the combined table to `hw03/corporate_events_timeline.csv` with all columns from both source tables plus `days_to_nearest_earnings` and `event_timing`. 4. Print a summary: for each company, list any executive events and whether they occurred before or after the nearest earnings announcement. 5. Print a final count: how many events occurred before vs. after an earnings announcement across all five companies.
```

---

## 2. Which companies' extractions required iteration

Claude Cowork could not reach sec.gov from its environment, so it tested its extraction code only on made-up filing text. I ran each script myself and sent the results back for fixes.

**Earnings (Spec A)**
- **JPMorgan and Walmart** needed follow-up regex fixes. The period extractor was widened to read JPMorgan's "Second-Quarter 2024" and "2Q24" wording, and the EPS extractor was changed to accept a plain "EPS of $4.40" when there is no "diluted" label.
- **Apple**: the table fallback took the first number on a row, which picked up a year-to-date figure instead of the quarter. This was fixed so the extractor takes the right column.
- **JPMorgan's "revenue"** is net revenue, since it is a bank. Apple reports net sales and Walmart reports total revenues, so revenue is not strictly comparable across companies.

**Executive events (Spec B)**
- **JPMorgan, Walmart and NVIDIA** rows needed fixes. My first run produced 30 rows with 13 `NOT_FOUND` cells. The problems were:
  - Phrases such as "Worldwide Field Operations" and "Non-Competition Agreements" were read as people's names.
  - Surname-only duplicates ("Combs'", "Furner") appeared as separate people from "Todd A. Combs" and "John Furner".
  - Titles were missing.
- After the fixes the file has 28 rows and 5 `NOT_FOUND` cells. The remaining `NOT_FOUND` cells are cases where the filing itself gives no title or effective date, so I left them rather than guess.
- **Walmart's January 2026 filing** (an executive reshuffle) still gives several people the same long title, "Executive Vice President, President and Chief Executive Officer". The parser is likely merging a list of executives from one sentence. I did not fix this, and I treat those title values as unreliable.

---

## 3. One thing the generated script did that I would not have thought to specify

`hw03_earnings.py` enforces "one per quarter" by de-duplicating: if a company filed two Item 2.02 8-Ks less than 45 days apart, it keeps only the more recent one. My spec said only "most recent four such filings (one per quarter)", and I would not have thought about companies that file a second Item 2.02 8-K close to the first, for example a correction or supplemental release.

**Verdict: correct, no adjustment needed.** The output has exactly 4 filings per company, roughly one quarter apart (for example Apple: 2025-10-30, 2026-01-29, 2026-04-30, 2026-07-30).

I also noticed that in the timeline script the two tables share the columns `company`, `ticker`, `cik` and `filing_date`. The script kept the event columns as they are and prefixed the earnings columns with `earnings_`, so nothing was overwritten. That was correct as written.
