"""
MIS3060 HW03 - SEC EDGAR executive-change (8-K Item 5.02) scraper

For each company in COMPANIES this script:
  1. Sends the same EDGAR User-Agent header on every request (one shared requests.Session)
  2. Queries the EDGAR submissions API (https://data.sec.gov/submissions/CIK{cik}.json) and keeps
     8-K filings whose `items` field contains "5.02" (Departure of Directors or Certain Officers;
     Election of Directors; Appointment of Certain Officers) AND whose filingDate is within the
     past 12 months
  3. Downloads each matching 8-K's full text, strips the HTML, isolates the Item 5.02 section and
     extracts, for every executive/director event: event type, person's full name, title and
     effective date
  4. Creates one row per event. A filing that reports several events (e.g. one departure and one
     appointment of two different people) produces several rows.
       event_type = "departure"    person leaves a role
                    "appointment"  person is appointed/elected to a role
                    "both"         the SAME person both leaves one role and takes another
                                   (e.g. CFO steps down and becomes Vice Chair)
  5. Prints each event as it is processed:  TICKER | DATE | EVENT TYPE | NAME | TITLE
  6. Prints "TICKER: No executive events in the past 12 months" when a company has no Item 5.02
     filings in the window - that is valid data, not an error
  7. Saves everything to executive_events.csv (next to this script, i.e. hw03/)

Conventions
  * A field that cannot be extracted is written as the string "NOT_FOUND" (never a blank cell),
    matching hw03_earnings.py.
  * "Effective immediately" is stored as the filing date.
  * Dates are ISO (YYYY-MM-DD).

Extraction is rule-based (regular expressions over the Item 5.02 prose), so it is a best-effort
parser: 8-K wording varies. Filings with Item 5.02 that describe neither a departure nor an
appointment (e.g. only compensation arrangements under 5.02(e)) are reported on the console
with their URL for manual review but produce no CSV row.

Usage:  python hw03/hw03_executives.py        (requires: pip install requests)
"""

import csv
import re
import sys
import time
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

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

ITEM_CODE = "5.02"
LOOKBACK_DAYS = 365
REQUEST_DELAY_SEC = 0.25        # stay well under SEC's 10 requests/second limit
NOT_FOUND = "NOT_FOUND"

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
OLDER_SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"

CSV_PATH = Path(__file__).resolve().parent / "executive_events.csv"
CSV_COLUMNS = ["company", "ticker", "cik", "filing_date", "event_type",
               "person_name", "title", "effective_date"]

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
# Step 2: find 8-K filings with Item 5.02 in the past 12 months
# --------------------------------------------------------------------------- #

def cutoff_date(today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=LOOKBACK_DAYS)


def _collect(block: dict, cutoff: date, out: list[dict]) -> date | None:
    """Append matching filings from one submissions block; return the oldest filing date seen."""
    oldest = None
    for form, items, fdate, acc, primary in zip(
        block["form"], block["items"], block["filingDate"],
        block["accessionNumber"], block["primaryDocument"],
    ):
        d = date.fromisoformat(fdate)
        oldest = d if oldest is None or d < oldest else oldest
        if d < cutoff or form != "8-K":
            continue
        if ITEM_CODE in [i.strip() for i in items.split(",")]:
            out.append({"filing_date": fdate, "accession": acc, "primary_doc": primary})
    return oldest


def get_exec_filings(cik: str, cutoff: date) -> list[dict]:
    """8-K filings with Item 5.02 filed on/after `cutoff`, newest first."""
    data = http_get(SUBMISSIONS_URL.format(cik=cik)).json()
    found: list[dict] = []
    oldest = _collect(data["filings"]["recent"], cutoff, found)

    # The "recent" block holds ~1,000 filings. A very active filer (e.g. JPMorgan) could push the
    # 12-month window into the older archive files, so keep paging while we haven't passed the cutoff.
    if oldest is not None and oldest > cutoff:
        for extra in data["filings"].get("files", []):
            if date.fromisoformat(extra["filingTo"]) < cutoff:
                continue
            block = http_get(OLDER_SUBMISSIONS_URL.format(name=extra["name"])).json()
            _collect(block, cutoff, found)

    found.sort(key=lambda f: f["filing_date"], reverse=True)
    return found


# --------------------------------------------------------------------------- #
# Step 3a: download the 8-K and strip HTML to plain text
# --------------------------------------------------------------------------- #

class _TextExtractor(HTMLParser):
    """Turns HTML into plain text; block-level tags become line breaks."""

    BLOCK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}
    SKIP = {"script", "style", "head", "title", "ix:header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    text = text.replace("\xa0", " ").replace(" ", " ").replace("​", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def fetch_filing_text(cik: str, filing: dict) -> tuple[str, str]:
    url = DOCUMENT_URL.format(cik_int=int(cik),
                              acc_nodash=filing["accession"].replace("-", ""),
                              doc=filing["primary_doc"])
    return html_to_text(http_get(url).text), url


# --------------------------------------------------------------------------- #
# Step 3b: isolate the Item 5.02 section
# --------------------------------------------------------------------------- #

_SECTION_START = re.compile(r"Item\s+5\.02\b", re.I)
_SECTION_END = re.compile(r"Item\s+(?:5\.0[3-9]|5\.[1-9]\d|[6-9]\.\d\d)\b|\bSIGNATURES?\b", re.I)


def item_502_section(text: str) -> str:
    """Text from 'Item 5.02' up to the next Item / signature block (longest candidate wins)."""
    best = ""
    for m in _SECTION_START.finditer(text):
        end = _SECTION_END.search(text, m.end())
        chunk = text[m.end(): end.start() if end else len(text)]
        if len(chunk) > len(best):
            best = chunk
    return best.strip() or text


# --------------------------------------------------------------------------- #
# Step 3c: extract events (rule-based)
# --------------------------------------------------------------------------- #

MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December|"
          "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec")
MONTH_NUM = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_PAT = rf"(?P<mon>{MONTHS})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{{4}}))?"
DATE_RE = re.compile(DATE_PAT)
EFFECTIVE_DATE_RE = re.compile(rf"effective\b[^.;]{{0,70}}?\b{DATE_PAT}", re.I)
EFFECTIVE_NOW_RE = re.compile(r"effective\s+(?:immediately|as\s+of\s+(?:the\s+)?date\s+hereof)", re.I)

# --- Titles ---------------------------------------------------------------- #
_PREFIX = r"(?:(?:Non-Executive|Independent|Lead|Presiding|Executive|Senior|Group|Corporate|Co-)\s*)*"
_CORE = (r"(?:Chief\s+(?:[A-Za-z&\-]+\s+){1,4}?Officer"
         r"|(?:Vice\s+)?Chair(?:man|woman|person)?(?:\s+of\s+the\s+Board(?:\s+of\s+Directors)?)?"
         r"|(?:Vice\s+)?President"
         r"|General\s+Counsel|Controller|Treasurer|(?:Corporate\s+)?Secretary"
         r"|Principal\s+(?:Executive|Financial|Accounting)\s+Officer"
         r"|Director\b(?!s)"
         r"|member\s+of\s+the\s+Board(?:\s+of\s+Directors)?"
         r"|C(?:EO|FO|OO|TO|IO|AO|LO|MO)\b)")
TITLE_RE = re.compile(rf"\b{_PREFIX}{_CORE}(?:(?:\s*,\s*|\s+(?:and|&)\s+){_PREFIX}{_CORE})*",
                      re.I)


_ABBREV = {"CEO": "Chief Executive Officer", "CFO": "Chief Financial Officer",
           "COO": "Chief Operating Officer", "CTO": "Chief Technology Officer",
           "CIO": "Chief Information Officer", "CAO": "Chief Accounting Officer",
           "CLO": "Chief Legal Officer", "CMO": "Chief Marketing Officer"}


def normalize_title(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip(" ,")
    t = re.sub(r"\b(CEO|CFO|COO|CTO|CIO|CAO|CLO|CMO)\b", lambda m: _ABBREV[m.group(1)], t, flags=re.I)
    t = re.sub(r"^member of the board( of directors)?$", "Director", t, flags=re.I)
    if t.islower():
        t = t.title()
    return t


def find_titles(sent: str) -> list[dict]:
    return [{"start": m.start(), "end": m.end(), "text": normalize_title(m.group())}
            for m in TITLE_RE.finditer(sent)]


# --- Names ----------------------------------------------------------------- #
_HONORIFICS = {"mr.", "ms.", "mrs.", "dr.", "miss"}
_PARTICLES = {"de", "van", "von", "der", "den", "del", "da", "di", "la", "bin", "al", "st."}
_STOP = set("""
chief executive financial operating accounting technology information legal administrative marketing
people human resources risk strategy commercial revenue investment officer officers president vice senior
chair chairman chairwoman chairperson director directors board committee committees company corporation
corp inc co llc ltd group corporate lead independent non-executive presiding principal general counsel
controller treasurer secretary member members audit compensation nominating governance leadership
development item effective the a an on in as of by at to for from with and or upon following prior after
before this that these those he she his her they their its it we our any all such other each also however
no not is are was were be been will has have had may would could shall should exhibit form report current
securities exchange commission act nasdaq nyse new york stock market united states u.s. delaware arkansas
california washington fiscal year quarter january february march april june july august september october
november december jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday
saturday sunday signature date name title chase bank apple microsoft nvidia jpmorgan walmart wal-mart
stores amendment agreement plan award awards equity incentive unit units restricted performance cash base
salary retirement resignation departure transition consulting separation release employment letter offer
disclosure regulation fd press cover page interactive data file xbrl inline emerging growth registrant
number irs identification employer pursuant section rule cfr previously currently additionally
worldwide field operations non-competition competition non-solicitation agreements international sales
accordingly since during between until most recently notably certain named nominee nominees shareholders
stockholders annual meeting special election appointment departure compensatory arrangements
""".split())
_NAME_TOKEN = re.compile(r"^[A-Z][A-Za-z'’\-]*\.?$")
_SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv"}


def find_names(sent: str) -> list[dict]:
    """Find person-name candidates: runs of 2-4 capitalised, non-stop-word tokens, or Mr./Ms. + surname."""
    words = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", sent)]
    names: list[dict] = []
    cur: list[tuple[str, int, int]] = []
    hon = False

    def flush():
        nonlocal cur, hon
        while cur and cur[-1][0].lower() in _PARTICLES:
            cur.pop()
        if cur:
            toks = [c[0] for c in cur]
            if hon and len(toks) <= 2:
                names.append({"name": " ".join(toks), "start": cur[0][1], "end": cur[-1][2], "hon": True})
            elif not hon and 2 <= len(toks) <= 4 and toks[0].lower() not in _SUFFIXES:
                names.append({"name": " ".join(toks), "start": cur[0][1], "end": cur[-1][2], "hon": False})
        cur, hon = [], False

    for raw, s, e in words:
        if raw[0] in "(\"“":
            flush()
        core = raw.strip(",;:()\"“”")
        possessive = core.endswith(("’s", "'s", "’", "'"))
        if possessive:
            core = core[:-2] if core.endswith(("’s", "'s")) else core[:-1]
        breaks_after = raw[-1] in ",;:)" or possessive or raw[-1] in "\"”"
        low = core.lower()
        if low in _HONORIFICS:
            flush()
            hon = True
            continue
        # strip a trailing sentence period unless it is an initial ("D.") or a suffix ("Jr.")
        if core.endswith(".") and len(core) > 2 and low not in _SUFFIXES:
            core = core[:-1]
            breaks_after = True
            low = core.lower()
        is_particle = low in _PARTICLES and cur and not hon
        is_initial = bool(re.fullmatch(r"[A-Z]\.", core))
        is_name = is_initial or (bool(_NAME_TOKEN.match(core)) and low.rstrip(".") not in _STOP
                                 and low not in _HONORIFICS)
        if is_name or is_particle:
            cur.append((core, s, s + len(core)))
            if breaks_after:
                flush()
        else:
            flush()
    flush()
    return names


# --- Event cues ------------------------------------------------------------ #
DEP_RE = re.compile(
    r"\b(?:resign(?:ed|s|ing|ation)?|retir(?:e|es|ed|ing|ement)|step(?:s|ped|ping)?\s+down"
    r"|depart(?:s|ed|ing|ure)?|leav(?:e|es|ing)\b(?!\s+of\s+absence)|terminat(?:ed|es|ion)"
    r"|separat(?:e|ed|es|ion)|cease(?:s|d)?\s+to\s+(?:serve|be)|no\s+longer\s+serv(?:e|es|ing)"
    r"|(?:not|decline[sd]?\s+to)\s+(?:to\s+)?stand\s+for\s+re-?election)", re.I)
APPT_RE = re.compile(
    r"\b(?:appoint(?:ed|s|ment)?|elect(?:ed|s)|(?<!\bthe\s)nam(?:ed|es)(?!\s+executive)|promot(?:ed|es|ion)"
    r"|designat(?:ed|es)|will\s+serve\s+as|to\s+serve\s+as|will\s+become|has\s+become|will\s+join"
    r"|assum(?:e|es|ed|ing)\s+the\s+(?:role|position|title)|succeed(?:s|ed|ing)?)\b", re.I)
_SUCCEED_RE = re.compile(r"succeed(?:s|ed|ing)?", re.I)
_PASSIVE_BEFORE = re.compile(r"(?:was|been|be|is|are|were|being)\s+(?:\w+ly\s+)?$", re.I)
_OF_AFTER = re.compile(r"^\s*(?:of|by)\s+", re.I)
_SUBJECT_CUES = re.compile(r"^(?:will\s+serve|to\s+serve|will\s+become|has\s+become|will\s+join|assum|succeed)", re.I)
MAX_CUE_DISTANCE = 200


def _nearest(cands: list[dict], pos: int, side: str) -> dict | None:
    if not cands:
        return None
    return max(cands, key=lambda n: n["end"]) if side == "before" else min(cands, key=lambda n: n["start"])


def pick_name(names: list[dict], cue: re.Match, sent: str, kind: str) -> dict | None:
    """Choose the person a departure/appointment cue refers to."""
    before = [n for n in names if n["end"] <= cue.start() and cue.start() - n["end"] <= MAX_CUE_DISTANCE]
    after = [n for n in names if n["start"] >= cue.end() and n["start"] - cue.end() <= MAX_CUE_DISTANCE]
    cue_text = cue.group()
    noun = bool(re.match(r"(?:resignation|retirement|departure|termination|separation|appointment|promotion)",
                         cue_text, re.I))
    if noun and _OF_AFTER.match(sent[cue.end():]):
        return _nearest(after, cue.end(), "after") or _nearest(before, cue.start(), "before")
    if kind == "appointment":
        if _SUBJECT_CUES.match(cue_text) or _PASSIVE_BEFORE.search(sent[:cue.start()]):
            return _nearest(before, cue.start(), "before") or _nearest(after, cue.end(), "after")
        return _nearest(after, cue.end(), "after") or _nearest(before, cue.start(), "before")
    return _nearest(before, cue.start(), "before") or _nearest(after, cue.end(), "after")


def pick_title(name: dict, names: list[dict], titles: list[dict], cue: re.Match | None = None) -> str | None:
    """Closest title in the sentence that is nearer to this person than to any other person."""
    def gap(t, n):
        return n["start"] - t["end"] if t["end"] <= n["start"] else max(0, t["start"] - n["end"])
    mine = []
    for t in titles:
        g = gap(t, name)
        owner_gap = min(gap(t, n) for n in names)
        if g <= 150 and g <= owner_gap:
            mine.append((g, t["start"] < name["start"], t))
    if not mine:
        return None
    if cue is not None and len(mine) > 1:
        # several roles for one person (e.g. steps down as CFO, becomes Vice Chair): use the one
        # closest to this event's cue, preferring a title that follows the cue ("...as <title>")
        def cue_dist(item):
            t = item[2]
            return t["start"] - cue.end() if t["start"] >= cue.end() else cue.start() - t["end"] + 50
        mine.sort(key=cue_dist)
        return mine[0][2]["text"]
    mine.sort(key=lambda x: (x[0], x[1]))   # nearest first; on ties prefer the title that follows the name
    return mine[0][2]["text"]


# --- Dates ----------------------------------------------------------------- #

def _to_iso(m: re.Match, filing_date: date) -> str:
    month = MONTH_NUM[m.group("mon").lower()[:3]]
    day = int(m.group("day"))
    year = m.group("year")
    try:
        if year:
            return date(int(year), month, day).isoformat()
        d = date(filing_date.year, month, day)
        if (filing_date - d).days > 180:      # e.g. filed in December about a January date
            d = date(filing_date.year + 1, month, day)
        return d.isoformat()
    except ValueError:
        return NOT_FOUND


def find_effective_date(sentences: list[str], idxs: list[int], cue_pos: dict[int, int],
                        filing_date: date, next_ok, allow_announce_date: bool) -> str:
    """Best effective date for an event mentioned in the sentences `idxs`.

    next_ok(j): True if sentence j (the one after an event sentence) is about the same person only,
    so its "effective ..." clause may be used. allow_announce_date: fall back to the first date in
    the sentence ("On <date>, the Board appointed ...") - used for appointments only, since for a
    departure that date is usually just when the person gave notice.
    """
    # 1) "effective ... <date>" / "effective immediately" in the event sentence itself
    for i in idxs:
        m = EFFECTIVE_DATE_RE.search(sentences[i])
        if m:
            return _to_iso(m, filing_date)
        if EFFECTIVE_NOW_RE.search(sentences[i]):
            return filing_date.isoformat()
    # 2) a date after the cue in the event sentence ("will retire on March 1, 2026")
    for i in idxs:
        pos = cue_pos.get(i, 0)
        m = re.search(rf"\b(?:on|as\s+of|by|until|through|at\s+the\s+end\s+of)\s+{DATE_PAT}",
                      sentences[i][pos:], re.I)
        if m:
            return _to_iso(m, filing_date)
    # 3) the following sentence, if it only talks about this person ("The appointment is effective ...")
    for i in idxs:
        j = i + 1
        if j < len(sentences) and j not in idxs and next_ok(j):
            m = EFFECTIVE_DATE_RE.search(sentences[j])
            if m:
                return _to_iso(m, filing_date)
            if EFFECTIVE_NOW_RE.search(sentences[j]):
                return filing_date.isoformat()
    # 4) appointments: the date the Board acted
    if allow_announce_date:
        for i in idxs:
            m = DATE_RE.search(sentences[i])
            if m:
                return _to_iso(m, filing_date)
    return NOT_FOUND


# --- Sentence splitting ------------------------------------------------------ #

_SENT_SPLIT = re.compile(
    r"(?<=[a-z0-9\)”\"'’]\.)"
    r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<!\bDr\.)(?<!\bJr\.)(?<!\bSr\.)(?<!\bInc\.)(?<!\bCo\.)"
    r"(?<!\bCorp\.)(?<!\bNo\.)(?<!\bSt\.)(?<!\bU\.S\.)"
    r"\s+(?=[A-Z“\"(])")


def split_sentences(section: str) -> list[str]:
    out = []
    for line in section.split("\n"):
        line = line.strip()
        if line:
            out.extend(s.strip() for s in _SENT_SPLIT.split(line) if s.strip())
    return out


# --- Putting it together --------------------------------------------------- #

def _surname(name: str) -> str:
    toks = [t for t in name.split() if t.lower() not in _SUFFIXES]
    return toks[-1].lower().rstrip(".") if toks else ""


def extract_events(text: str, filing_date: date) -> list[dict]:
    """Return one dict per event: event_type, person_name, title, effective_date."""
    section = item_502_section(text)
    sentences = split_sentences(section)
    parsed = [(find_names(s), find_titles(s)) for s in sentences]

    # surname -> full name, so "Mr. Cook" can be resolved to "Timothy D. Cook"
    surname_map: dict[str, set[str]] = {}
    for names, _ in parsed:
        for n in names:
            if not n["hon"]:
                surname_map.setdefault(_surname(n["name"]), set()).add(n["name"])

    def resolve(n: dict) -> str:
        if n["hon"]:
            full = surname_map.get(_surname(n["name"]), set())
            return next(iter(full)) if len(full) == 1 else n["name"]
        return n["name"]

    # person -> aggregated info
    people: dict[str, dict] = {}
    order: list[str] = []

    def record(person: str, kind: str, title: str | None, si: int, cue_start: int):
        p = people.get(person)
        if p is None:
            p = people[person] = {"kinds": {}, "sent_idx": [], "cue_pos": {}}
            order.append(person)
        if title and kind not in p["kinds"]:
            p["kinds"][kind] = title
        else:
            p["kinds"].setdefault(kind, None)
        if si not in p["sent_idx"]:
            p["sent_idx"].append(si)
            p["cue_pos"][si] = cue_start
        if p["kinds"].get(kind) is None and title:
            p["kinds"][kind] = title

    def fallback_title(si: int, cue: re.Match, titles: list[dict], person: str) -> str | None:
        """Used when no title 'belongs' to the person: any title in the sentence nearest the cue,
        then a title in the next sentence if that sentence is only about this person, then
        'Director' for Board seats."""
        if titles:
            after = [t for t in titles if t["start"] >= cue.end()]
            t = min(after, key=lambda t: t["start"]) if after else max(titles, key=lambda t: t["end"])
            return t["text"]
        nxt = si + 1
        if nxt < len(sentences) and all(resolve(n) == person for n in parsed[nxt][0]) and parsed[nxt][1]:
            return parsed[nxt][1][0]["text"]
        if re.search(r"\b(?:to|of|on|from)\s+the\s+(?:Company['’]s\s+)?Board\b", sentences[si], re.I):
            return "Director"
        return None

    for si, (sent, (names, titles)) in enumerate(zip(sentences, parsed)):
        if not names:
            continue
        # skip biography sentences that only mention years well before the filing
        years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", sent)]
        if years and max(years) < filing_date.year - 1:
            continue
        for kind, regex in (("departure", DEP_RE), ("appointment", APPT_RE)):
            for cue in regex.finditer(sent):
                if kind == "appointment" and _SUCCEED_RE.fullmatch(cue.group()):
                    # "X will succeed Y as CFO": X is appointed, Y (the name that follows) departs
                    who = pick_name(names, cue, sent, "appointment")
                    gone = _nearest([n for n in names if n["start"] >= cue.end()
                                     and n["start"] - cue.end() <= 60], cue.end(), "after")
                    if gone:
                        g = resolve(gone)
                        record(g, "departure",
                               pick_title(gone, names, titles, cue) or fallback_title(si, cue, titles, g),
                               si, cue.start())
                else:
                    who = pick_name(names, cue, sent, kind)
                if who:
                    w = resolve(who)
                    record(w, kind, pick_title(who, names, titles, cue) or fallback_title(si, cue, titles, w),
                           si, cue.start())

    for short in [k for k in order if len(k.split()) == 1]:
        full = [k for k in order if len(k.split()) > 1 and _surname(k) == _surname(short)]
        if len(full) == 1:
            tgt, src = people[full[0]], people[short]
            for kind, title in src["kinds"].items():
                if tgt["kinds"].get(kind) is None:
                    tgt["kinds"][kind] = title
            for si in src["sent_idx"]:
                if si not in tgt["sent_idx"]:
                    tgt["sent_idx"].append(si)
                    tgt["cue_pos"][si] = src["cue_pos"][si]
            del people[short]
            order.remove(short)

    def next_ok_for(person: str):
        def ok(j: int) -> bool:
            return all(resolve(n) == person for n in parsed[j][0])
        return ok

    events = []
    for person in order:
        p = people[person]
        kinds = p["kinds"]
        title_dep, title_app = kinds.get("departure"), kinds.get("appointment")
        if "departure" in kinds and "appointment" in kinds:
            event_type = "both"
            if title_dep and title_app and title_dep != title_app:
                title = f"{title_app} (appointed); {title_dep} (departing)"
            else:
                title = title_app or title_dep
        elif "appointment" in kinds:
            event_type, title = "appointment", title_app
        else:
            event_type, title = "departure", title_dep
        events.append({
            "event_type": event_type,
            "person_name": person,
            "title": title or NOT_FOUND,
            "effective_date": find_effective_date(sentences, p["sent_idx"], p["cue_pos"], filing_date,
                                                  next_ok_for(person), "appointment" in kinds),
        })
    return events


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def process_company(co: dict, cutoff: date, rows: list[dict]) -> None:
    print(f"\n== {co['company']} ({co['ticker']}, CIK {co['cik']}) ==")
    try:
        filings = get_exec_filings(co["cik"], cutoff)
    except Exception as exc:
        print(f"[{co['ticker']}] ERROR fetching submissions: {exc}", file=sys.stderr)
        return

    if not filings:
        # Valid data, not an error: many companies have no executive changes in a given year.
        print(f"{co['ticker']}: No executive events in the past 12 months")
        return

    for filing in filings:
        try:
            text, url = fetch_filing_text(co["cik"], filing)
            events = extract_events(text, date.fromisoformat(filing["filing_date"]))
        except Exception as exc:
            print(f"[{co['ticker']}] ERROR on {filing['accession']}: {exc}", file=sys.stderr)
            continue

        if not events:
            print(f"{co['ticker']} | {filing['filing_date']} | no departure/appointment detected "
                  f"in Item 5.02 (review manually): {url}")
            continue

        for ev in events:
            row = {"company": co["company"], "ticker": co["ticker"], "cik": co["cik"],
                   "filing_date": filing["filing_date"], **ev}
            rows.append(row)
            print(f"{row['ticker']} | {row['filing_date']} | {row['event_type']} | "
                  f"{row['person_name']} | {row['title']}")


def main() -> None:
    cutoff = cutoff_date()
    print(f"Item {ITEM_CODE} 8-K filings filed on or after {cutoff.isoformat()}")
    rows: list[dict] = []
    for co in COMPANIES:
        process_company(co, cutoff, rows)

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} event(s) to {CSV_PATH}")


if __name__ == "__main__":
    main()
