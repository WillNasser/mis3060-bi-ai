# Spectification A

*Write me a python script that completes the following actions:*

1) Sets the SEC EDGAR User-Agent header to "MIS3060 Villanova wnasser@villanova.edu" on all HTTP requests 
2) For each of the five companies (Apple Inc.(Ticker: AAPL, CIK: 0000320193), Microsoft Corporation(Ticker: MSFT, CIK: 0000789019), NVIDIA Corporation(Ticker: NVDA, CIK: 0001045810), JPMorgan Chase & Co.(Ticker: JPM, CIK: 0000019617), Walmart Inc.(Ticker: WMT, CIK: 0000104169)), queries the EDGAR submissions API at https://data.sec.gov/submissions/CIK{cik}.json and filters for 8-K filings where the items field contains "2.02" (Results of Operations) 
3) Selects the most recent four such filings per company (one per quarter) 
4) For each filing, constructs the filing index URL, identifies the earnings press release exhibit (.htm file), downloads it, and strips HTML to plain text
5) Extracts from the plain text: quarterly revenue (as a numebr in millions or billions), diluted EPS, net income, and the reporting period (e.g., "fourth quarter fiscal 2024")
6) Prints the extracted row for each filing as it is processed, in the format: [Ticker] | [Period] | Revenue: $X | EPS: $X | Net Income: $X
7) Saves all rows to hw03/earnings_history.csv with columns: company, ticker, cik, filing_date, period, revenue_reported, eps_diluted, net_income
8) Where a field cannot be extracted (regex returns no match), stores the string "NOT_FOUND" rather than leaving the cell blank - blank cells and missing data are two different things



# Specification B

*Write me a python script that completes the following actions:*

1) Sets the same EDGAR User-Agent header on all requests
2) For each of the five companies, queries the EDGAR submissions API and filters for 8-K filings where the items field contains "5.02" (Departure of Directors or Officers), and the filingDate is within the past 12 months
3) For each matching filing, downloads the full 8-K text, strips HTML, and extracts: event type ("departure" or "appointment" or "both"), the person's full name, their title, and the effective date of the change
4) If a filing reports multiple events (e.g., one departure and one appointment), creates a separate row for each event
5) Prints each extracted event as it is processed: [Ticker] | [Date] | [Event Type] | [Name] | [Title]
6) If no item 5.02 filings are found for a company in the past 12 months, prints [Ticker]: No executive events in the past 12 months - this is valid data, not an error
7) Saves all events to hw03/executive_events.csv with columns: company, ticker, cik, filing_date, event_type, person_name, title, effective_date