"""
MIS3060 HW03 - SEC EDGAR earnings history scraper

For each company in COMPANIES this script:
  1. Queries the EDGAR submissions API (https://data.sec.gov/submissions/CIK{cik}.json)
  2. Keeps 8-K filings whose `items` field contains "2.02" (Results of Operations)
  3. Selects the four most recent such filings (one per quarter)
  4. Builds the filing index URL, finds the earnings press release exhibit (EX-99.x, .htm),
     downloads it and strips the HTML to plain text
  5. Extracts revenue, diluted EPS, net income and the reporting period with regexes
  6. Prints one row per filing as it is processed
  7. Saves everything to earnings_history.csv (next to this script, i.e. hw03/)
  8. Writes the string "NOT_FOUND" wherever a field cannot be extracted (never a blank cell)

Units: revenue_reported and net_income are stored as numbers in US$ MILLIONS
(so $85.8 billion -> 85800.0). eps_diluted is US$ per share.

Usage:  python hw03/hw03_earnings.py        (requires: pip install requests)
"""

import csv
import re
import sys
import time
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# 1) SEC requires a descriptive User-Agent on every request.
USER_AGENT = "MIS3060 Villanova wnasser@villanova.edu"

COMPANIES = [
    {"company": "Apple Inc.",              "ticker": "AAPL", "cik": "0000320193"},
    {"company": "Microsoft Corporation",   "ticker": "MSFT", "cik": "0000789019"},
    {"company": "NVIDIA Corporation",      "ticker": "NVDA", "cik": "0001045810"},
    {"company": "JPMorgan Chase & Co.",    "ticker": "JPM",  "cik": "0000019617"},
    {"company": "Walmart Inc.",            "ticker": "WMT",  "cik": "0000104169"},
]

FILINGS_PER_COMPANY = 4
MIN_DAYS_BETWEEN_FILINGS = 45   # enforces "one per quarter" if a company files two 2.02 8-Ks close together
REQUEST_DELAY_SEC = 0.25        # stay well under SEC's 10 requests/second limit
NOT_FOUND = "NOT_FOUND"

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{acc}-index.htm"

CSV_PATH = Path(__file__).resolve().parent / "earnings_history.csv"
CSV_COLUMNS = ["company", "ticker", "cik", "filing_date", "period",
               "revenue_reported", "eps_diluted", "net_income"]

# All HTTP requests go through this one session, so the header is always sent.
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})


def http_get(url: str, retries: int = 3) -> requests.Response:
    """GET with polite rate limiting and simple retry on 429/5xx."""
    for attempt in range(1, retries + 1):
        time.sleep(REQUEST_DELAY_SEC)
        resp = session.get(url, timeout=30)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(2 * attempt)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"unreachable: {url}")


# --------------------------------------------------------------------------- #
# Steps 2-3: find the 8-K Item 2.02 filings
# --------------------------------------------------------------------------- #

def get_earnings_filings(cik: str) -> list[dict]:
    """Return the most recent FILINGS_PER_COMPANY 8-K filings with Item 2.02, one per quarter."""
    data = http_get(SUBMISSIONS_URL.format(cik=cik)).json()
    recent = data["filings"]["recent"]

    candidates = []
    for form, items, fdate, acc, primary in zip(
        recent["form"], recent["items"], recent["filingDate"],
        recent["accessionNumber"], recent["primaryDocument"],
    ):
        if form == "8-K" and "2.02" in [i.strip() for i in items.split(",")]:
            candidates.append({"filing_date": fdate, "accession": acc, "primary_doc": primary})

    candidates.sort(key=lambda f: f["filing_date"], reverse=True)

    selected = []
    for f in candidates:
        d = date.fromisoformat(f["filing_date"])
        if selected and (date.fromisoformat(selected[-1]["filing_date"]) - d).days < MIN_DAYS_BETWEEN_FILINGS:
            continue  # same quarter as the one we already kept
        selected.append(f)
        if len(selected) == FILINGS_PER_COMPANY:
            break
    return selected


# --------------------------------------------------------------------------- #
# Step 4: filing index -> press release exhibit -> plain text
# --------------------------------------------------------------------------- #

class _IndexParser(HTMLParser):
    """Collects table rows from the filing index page as lists of (text, href) cells."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._in_cell = [], None, None, False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._in_cell = {"text": "", "href": None}, True
        elif tag == "a" and self._in_cell and self._cell["href"] is None:
            self._cell["href"] = dict(attrs).get("href")

    def handle_data(self, data):
        if self._in_cell:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            self._row.append((self._cell["text"].strip(), self._cell["href"]))
            self._in_cell = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def find_exhibit_url(index_url: str) -> str | None:
    """Locate the EX-99.x .htm document (the earnings press release) on a filing index page."""
    parser = _IndexParser()
    parser.feed(http_get(index_url).text)

    exhibits = []
    for row in parser.rows:
        doc_type = next((t for t, _ in row if t.upper().startswith("EX-99")), None)
        href = next((h for _, h in row if h and h.lower().split("?")[0].endswith((".htm", ".html"))), None)
        if doc_type and href:
            if "doc=" in href:                     # inline-XBRL viewer link -> real path
                href = href.split("doc=", 1)[1]
            exhibits.append((doc_type.upper(), urljoin("https://www.sec.gov", href)))

    if not exhibits:
        return None
    exhibits.sort(key=lambda e: e[0])              # EX-99.1 before EX-99.2
    return exhibits[0][1]


class _TextExtractor(HTMLParser):
    """Strips HTML to plain text: one line per block/table row, cells separated by spaces."""

    BLOCK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section"}
    SKIP = {"script", "style", "ix:header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    text = unescape("".join(extractor.parts)).replace("\xa0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n"))
    return "\n".join(ln for ln in lines if ln)


# --------------------------------------------------------------------------- #
# Step 5: field extraction
# --------------------------------------------------------------------------- #

UNIT_TO_MILLIONS = {"billion": 1000.0, "million": 1.0, "thousand": 0.001}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
ORDINAL_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _signed(m: re.Match) -> float:
    """Value from a table match with groups (optional '(' , number); parentheses mean negative."""
    return -_num(m.group(2)) if m.group(1) else _num(m.group(2))


def _is_non_gaap(text: str, start: int) -> bool:
    """True if the match is qualified as 'non-GAAP' earlier in the same sentence."""
    prefix = re.split(r"\.\s|[\u2022;]", text[max(0, start - 40):start])[-1]
    return "non-gaap" in prefix.lower()


def _table_units(text: str) -> float | None:
    """Multiplier to millions for table figures, from a '(in millions' / '(in thousands' note."""
    m = re.search(r"in\s+(millions|thousands)", text, re.I)
    if not m:
        return None
    return 1.0 if m.group(1).lower() == "millions" else 0.001


def extract_revenue(text: str, flat: str):
    """Quarterly revenue in $ millions."""
    # Narrative: "revenue of $85.8 billion", "net sales increased 11% to $143.3 billion", ...
    pat = re.compile(
        r"(?:total\s+)?(?:net\s+)?(?:revenues?|net\s+sales)\b(?:(?!\.\s)[^$]){0,80}?\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million)",
        re.I)
    for m in pat.finditer(flat):
        if not _is_non_gaap(flat, m.start()):
            return round(_num(m.group(1)) * UNIT_TO_MILLIONS[m.group(2).lower()], 3)

    # Table row: "Total net sales 85,777 ..."
    units = _table_units(text)
    if units:
        row = re.search(
            r"^(?:total\s+)?(?:net\s+sales|net\s+revenues?|revenues?)\b[^\n\d$(]{0,40}?\s*\$?\s*(\()?([\d,]+(?:\.\d+)?)",
            text, re.I | re.M)
        if row:
            return round(_signed(row) * units, 3)
    return NOT_FOUND


def extract_eps(text: str, flat: str):
    """GAAP diluted EPS in $ per share."""
    patterns = [
        r"(?:earnings|income)\s+per\s+diluted\s+share\b(?:(?!\.\s)[^$]){0,60}?\$\s?(\d+\.\d+)",
        r"diluted\s+(?:(?:net\s+)?(?:earnings|income)\s+)?(?:\(loss\)\s+)?per\s+(?:common\s+)?share\b(?:(?!\.\s)[^$]){0,60}?\$\s?(\d+\.\d+)",
        r"diluted\s+(?:eps|earnings)\b(?:(?!\.\s)[^$]){0,40}?\$\s?(\d+\.\d+)",
        r"\b(?:GAAP\s+)?EPS\b(?:(?!\.\s)[^$]){0,40}?\$\s?(\d+\.\d+)",
    ]
    for p in patterns:
        for m in re.finditer(p, flat, re.I):
            if not _is_non_gaap(flat, m.start()):
                return float(m.group(1))

    # Table row: "Diluted earnings per share $ 1.40 $ 1.26"
    for m in re.finditer(r"^[^\n]{0,30}?diluted[^\n\d]{0,80}?\s*\$?\s*(\()?(\d+\.\d{2})", text, re.I | re.M):
        if not _is_non_gaap(text, m.start()):
            return -float(m.group(2)) if m.group(1) else float(m.group(2))
    return NOT_FOUND


def extract_net_income(text: str, flat: str):
    """GAAP net income in $ millions (attributable to the company when both are shown)."""
    pat = re.compile(
        r"net\s+(?:quarterly\s+)?(?:income|earnings)\b(?:(?!\.\s)[^$]){0,60}?\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million)",
        re.I)
    for m in pat.finditer(flat):
        if not _is_non_gaap(flat, m.start()):
            return round(_num(m.group(1)) * UNIT_TO_MILLIONS[m.group(2).lower()], 3)

    units = _table_units(text)
    if units:
        tail = r"\b[^\n\d$(]{0,60}?\s*\$?\s*(\()?([\d,]+(?:\.\d+)?)"
        for label in (
            r"^(?:consolidated\s+)?net\s+(?:income|earnings)(?:\s+\(loss\))?\s+attributable\s+to\s+(?!non)",
            r"^(?:consolidated\s+)?net\s+(?:income|earnings)(?:\s+\(loss\))?",
        ):
            row = re.search(label + tail, text, re.I | re.M)
            if row:
                return round(_signed(row) * units, 3)
    return NOT_FOUND


def extract_period(text: str, flat: str) -> str:
    """Reporting period, e.g. 'fourth quarter fiscal 2024'.

    The reported quarter is the first one named in the release (title / opening
    paragraph). Later mentions are prior-year comparisons or next-quarter outlook,
    so the earliest match by position wins.
    """
    found = []  # (position, year, quarter, fiscal?)

    def add(m, q, yr, fiscal):
        found.append((m.start(), int(yr if len(yr) == 4 else "20" + yr), q, bool(fiscal)))

    # "fourth quarter [of] [fiscal] [year] 2024"  /  "fourth quarter and fiscal [year] 2024"
    for m in re.finditer(r"\b(first|second|third|fourth)[\s-]+quarter(?:\s+(?:of|and))?\s+(fiscal\s+)?(?:year\s+)?(20\d\d)\b", flat, re.I):
        add(m, ORDINALS[m.group(1).lower()], m.group(3), m.group(2))
    # "fiscal [year] 2024 fourth quarter"
    for m in re.finditer(r"\b(fiscal)\s+(?:year\s+)?(20\d\d)\s+(first|second|third|fourth)\s+quarter\b", flat, re.I):
        add(m, ORDINALS[m.group(3).lower()], m.group(2), m.group(1))
    # "Q4 FY25", "Q4 2024", "Q4 fiscal 2025"
    for m in re.finditer(r"\bQ([1-4])\s*(FY|fiscal\s+)?\s*'?((?:20)?\d\d)\b", flat, re.I):
        add(m, int(m.group(1)), m.group(3), m.group(2))
    # "FY25 Q4", "fiscal 2025 Q4"
    for m in re.finditer(r"\b(FY|fiscal\s+)\s*'?((?:20)?\d\d)\s*Q([1-4])\b", flat, re.I):
        add(m, int(m.group(3)), m.group(2), m.group(1))
    # "2Q24", "4Q 2024"
    for m in re.finditer(r"\b([1-4])Q\s?((?:20)?\d\d)\b", flat):
        add(m, int(m.group(1)), m.group(2), None)

    if found:
        _, year, q, fiscal = min(found, key=lambda f: f[0])
        return f"{ORDINAL_WORDS[q]} quarter {'fiscal ' if fiscal else ''}{year}"

    # Fallback: "quarter ended June 30, 2024"
    m = re.search(r"quarter\s+ended\s+([A-Z][a-z]+\s+\d{1,2},\s+20\d\d)", flat)
    if m:
        return f"quarter ended {m.group(1)}"
    return NOT_FOUND


# --------------------------------------------------------------------------- #
# Step 6: formatting for the console
# --------------------------------------------------------------------------- #

def fmt_millions(v) -> str:
    if v == NOT_FOUND:
        return NOT_FOUND
    return f"${v / 1000:,.2f}B" if abs(v) >= 1000 else f"${v:,.1f}M"


def fmt_eps(v) -> str:
    return NOT_FOUND if v == NOT_FOUND else f"${v:.2f}"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def process_filing(co: dict, filing: dict) -> dict:
    row = {"company": co["company"], "ticker": co["ticker"], "cik": co["cik"],
           "filing_date": filing["filing_date"], "period": NOT_FOUND,
           "revenue_reported": NOT_FOUND, "eps_diluted": NOT_FOUND, "net_income": NOT_FOUND}

    acc = filing["accession"]
    index_url = ARCHIVES_URL.format(cik_int=int(co["cik"]), acc_nodash=acc.replace("-", ""), acc=acc)

    exhibit_url = find_exhibit_url(index_url)
    if not exhibit_url:
        raise RuntimeError(f"no EX-99 .htm exhibit found at {index_url}")

    text = html_to_text(http_get(exhibit_url).text)
    flat = re.sub(r"\s+", " ", text)

    row["period"] = extract_period(text, flat)
    row["revenue_reported"] = extract_revenue(text, flat)
    row["eps_diluted"] = extract_eps(text, flat)
    row["net_income"] = extract_net_income(text, flat)
    return row


def main() -> int:
    rows = []
    for co in COMPANIES:
        print(f"\n== {co['company']} ({co['ticker']}, CIK {co['cik']}) ==")
        try:
            filings = get_earnings_filings(co["cik"])
        except Exception as exc:
            print(f"[{co['ticker']}] ERROR fetching submissions: {exc}", file=sys.stderr)
            continue
        if not filings:
            print(f"[{co['ticker']}] no 8-K Item 2.02 filings found")

        for filing in filings:
            try:
                row = process_filing(co, filing)
            except Exception as exc:  # keep going; record the filing with NOT_FOUND fields
                print(f"[{co['ticker']}] ERROR on {filing['accession']}: {exc}", file=sys.stderr)
                row = {"company": co["company"], "ticker": co["ticker"], "cik": co["cik"],
                       "filing_date": filing["filing_date"], "period": NOT_FOUND,
                       "revenue_reported": NOT_FOUND, "eps_diluted": NOT_FOUND, "net_income": NOT_FOUND}
            rows.append(row)
            print(f"{row['ticker']} | {row['period']} | Revenue: {fmt_millions(row['revenue_reported'])} "
                  f"| EPS: {fmt_eps(row['eps_diluted'])} | Net Income: {fmt_millions(row['net_income'])}")

    # Step 7-8: save; every cell is either a value or the literal "NOT_FOUND"
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} rows to {CSV_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
