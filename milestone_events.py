"""
Regulatory / milestone EVENTS for one deal, read from SEC filings only.

Every event is a dated fact with the accession it came from and the sentence it
was read out of. No LLM, no inference: a sentence either asserts the event in
the past tense or it is skipped. Nothing here feeds scoring or either
enforcing gate; it is a display/flag layer.

Two things the first real filings taught (NATH, IMXI):
  * The ACQUIRER's filings carry events the target never files. IMXI's NY/CA
    regulatory story is in Western Union's 8-K (0001193125-26-350419), not in
    anything IMXI filed after its vote. Both filers are scanned.
  * The proxy carries regulatory dates no 8-K does. NATH's HSR expiry and
    CFIUS clearance are only in the DEFM14A. Proxies are scanned too.

What this cannot see: anything said only in press releases that were never
attached to a filing, and jurisdiction COUNTS ("52 of 53").
"""
import re
import time
import threading
from datetime import datetime

import requests

from detect_milestones import extract_meeting_date

HEADERS = {"User-Agent": "MeridianResearch/1.0 (kaushalkoduru@gmail.com)",
           "Accept-Encoding": "gzip, deflate"}
CACHE_TTL = 6 * 3600
_cache, _lock = {}, threading.Lock()
_tickers = {"t": 0, "rows": []}

MONTHS = (r"(?:January|February|March|April|May|June|July|August|September|"
          r"October|November|December)")
DATE_RE = re.compile(MONTHS + r"\s+\d{1,2},\s+20\d{2}")

REGULATORS = [  # (regex, display name) — first hit in the sentence wins
    (r"\bNYDFS\b|New York State Department of Financial Services", "NYDFS"),
    (r"\bDFPI\b|California Department of Financial Protection", "California DFPI"),
    (r"\bCFIUS\b|Committee on Foreign Investment", "CFIUS"),
    (r"\bSAMR\b|State Administration for Market Regulation", "China SAMR"),
    (r"European Commission|\bEC\b", "European Commission"),
    (r"\bFTC\b|Federal Trade Commission", "FTC"),
    (r"\bDOJ\b|Department of Justice|Antitrust Division", "DOJ"),
    (r"Competition and Markets Authority|\bCMA\b", "UK CMA"),
    (r"Competition Bureau", "Competition Bureau (Canada)"),
    (r"Bundeskartellamt", "Bundeskartellamt"),
    (r"Federal Reserve|\bFRB\b", "Federal Reserve"),
    (r"Office of the Comptroller|\bOCC\b", "OCC"),
    (r"\bFCC\b|Federal Communications Commission", "FCC"),
    (r"\bFERC\b", "FERC"),
    (r"\bHSR\b|Hart-Scott-Rodino", "HSR (FTC/DOJ)"),
]
# A sentence that is hedged, conditional or forward-looking does not assert an event.
MODAL = re.compile(
    r"\b(could|may|might|would|should|if|unless|until|provided that|no assurance|"
    r"expects?|anticipates?|intends?|required to|subject to|conditioned|condition to|"
    r"cannot be|will be|shall|in the event|absent)\b", re.I)
PAST_DATE_GUARD = re.compile(r"(granted|previously|originally|dated|filed|filings|submitted|"
                             r"entered into|announced)\W+(?:\w+\W+){0,3}$", re.I)


def _sentences(text):
    text = re.sub(r"\s+", " ", text.replace("\u200b", " ").replace("\xa0", " "))
    # "p.m. Eastern Time" and "Inc. (" are not sentence ends.
    text = re.sub(r"\b(a\.m|p\.m|Inc|Corp|Co|Ltd|No|U\.S|Mr|Ms|Dr|St|Nos)\.",
                  lambda m: m.group(0).replace(".", "\u2024"), text)
    return [x.replace("\u2024", ".") for x in re.split(r"(?<=[.;])\s+(?=[A-Z\u201c\"(])", text)]


def _regulator(s):
    for rx, name in REGULATORS:
        if re.search(rx, s):
            return name
    return None


def _event_date(s, trig_pos, filing_date):
    """Date the EVENT happened. Prefer 'on <date>' just after the trigger word,
    else the nearest date before it. Dates that are only context ('previously
    granted on', 'filed on') are ignored. Fallback: the filing date, labelled."""
    cands = []
    for m in DATE_RE.finditer(s):
        if PAST_DATE_GUARD.search(s[max(0, m.start() - 45):m.start()]):
            continue
        try:
            iso = datetime.strptime(re.sub(r"\s+", " ", m.group(0)), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        cands.append((m.start(), iso))
    after = [c for c in cands if c[0] >= trig_pos and c[0] - trig_pos <= 60]
    before = [c for c in cands if c[0] < trig_pos]
    if after:
        return after[0][1], "stated"
    if before:
        return before[-1][1], "stated"
    return filing_date, "filing_date"


# (type, label, adverse, trigger regex, extra require regex or None, use regulator?)
RULES = [
    ("hsr_expired", "HSR waiting period expired / early termination", False,
     r"\b(expired|was terminated|has been terminated|early termination[^.]{0,60}(?:was |been )?granted|granted early termination)\b",
     r"waiting period[^.]*\b(HSR|Hart-Scott)|\b(HSR|Hart-Scott)[^.]*waiting period", False),
    ("second_request", "Second Request issued", True,
     r"\b(received|issued|issuing|was issued|has issued|were issued)\b[^.]{0,80}second request|second request[^.]{0,80}\b(was issued|was received|issued)\b",
     None, False),
    ("cfius_clearance", "CFIUS clearance obtained", False,
     r"CFIUS\s+Clearance\s+(?:was|has been)\s+obtained|CFIUS[^.]{0,120}(?:completed|concluded)[^.]{0,120}no unresolved national security concerns",
     None, False),
    ("reg_approval", "Regulatory approval received", False,
     r"\b(received|obtained|granted)\b[^.]{0,80}\b(approval|clearance)\b|\b(approval|clearance)\b[^.]{0,60}\b(was|has been) (granted|received|obtained)\b",
     None, True),
    ("approval_suspended", "Regulatory approval suspended", True,
     r"\b(suspend\w*|revok\w*|withdr[ae]w\w*|rescind\w*)\b[^.]{0,80}\bapproval\b|\bapproval\b[^.]{0,80}\b(suspended|revoked|withdrawn|rescinded)\b",
     None, True),
    ("outside_date_extended", "Outside date extended", True,
     r"\b(extend\w*|extension)\b[^.]{0,160}\b(End Date|Outside Date|Termination Date|Drop[- ]Dead Date|Outside Closing Date)\b",
     None, False),
    ("deal_repriced", "Deal price / terms amended", False,
     r"\b(entered into|executed|agreed to)\b[^.]{0,120}\bAmendment\b[^.]{0,200}\b(increas\w*|decreas\w*|reduc\w*|revis\w*)\w*[^.]{0,80}\b(merger consideration|per share|offer price|purchase price)\b",
     None, False),
    ("deal_amended", "Merger agreement amended", False,
     r"\bAmendment No\.?\s*\d+\s+to\s+(?:the\s+)?(?:Agreement and Plan of Merger|Merger Agreement)",
     None, False),
]
# Approval words must also be about THIS deal.
DEAL_ANCHOR = re.compile(r"\b(Merger|merger|transaction|acquisition|Acquisition)\b")


def extract_events(text, filing_date, anchors=(), form_kind="8-K"):
    """Sentence-level events from one document. Returns dicts (no accession yet)."""
    out = []
    for s in _sentences(text):
        if len(s) < 25 or len(s) > 900:
            continue
        if re.search(r"[“\"]\s*[A-Z][\w ]+\s*[”\"]\s+(means|shall mean|has the meaning)", s):
            continue  # a definition, not an event
        for typ, label, adverse, trig, need, use_reg in RULES:
            if typ in ("deal_repriced", "deal_amended") and form_kind != "8-K":
                continue  # proxy background narrates negotiations; only a filed 8-K amends
            m = re.search(trig, s, re.I)
            if not m:
                continue
            if need and not re.search(need, s, re.I | re.S):
                continue
            # Suspension/adverse wording is not a forward-looking hedge problem
            # for the modal check only when it reports something that happened.
            if MODAL.search(s) and not (typ in ("approval_suspended", "second_request")
                                        and re.search(r"\b(sent|received|issued|suspend(?:ed|ing))\b", s, re.I)
                                        and not re.search(r"\b(could|may|might|if|unless|no assurance)\b", s, re.I)):
                continue
            if typ in ("reg_approval", "approval_suspended", "outside_date_extended", "deal_repriced") and not (
                    DEAL_ANCHOR.search(s) or any(a and a.lower() in s.lower() for a in anchors)):
                continue  # generic wording needs the deal named; HSR/CFIUS/second-request text is specific
            reg = _regulator(s)
            if use_reg and not reg:
                continue
            if typ == "hsr_expired":
                reg = "HSR (FTC/DOJ)"
            if typ == "cfius_clearance":
                reg = "CFIUS"
            if typ == "reg_approval" and reg == "CFIUS":
                continue  # typed as cfius_clearance
            d, basis = _event_date(s, m.start(), filing_date)
            out.append({"type": typ, "label": label, "adverse": adverse,
                        "regulator": reg, "date": d, "date_basis": basis,
                        "quote": s.strip()})
    return out


# ── EDGAR plumbing ────────────────────────────────────────────────────────────
def _get(url, **kw):
    time.sleep(0.12)
    r = requests.get(url, headers=HEADERS, timeout=25, **kw)
    r.raise_for_status()
    return r


def _text(url):
    from bs4 import BeautifulSoup
    return BeautifulSoup(_get(url).text, "html.parser").get_text(" ")


def _ticker_rows():
    if time.time() - _tickers["t"] > 86400 or not _tickers["rows"]:
        _tickers["rows"] = list(_get("https://www.sec.gov/files/company_tickers.json").json().values())
        _tickers["t"] = time.time()
    return _tickers["rows"]


def _norm(n):
    n = re.sub(r"\b(inc|corp|corporation|co|company|holdings?|group|ltd|plc|the|llc)\b\.?", " ", (n or "").lower())
    return " ".join(re.sub(r"[^a-z0-9& ]+", " ", n).split())


def resolve_cik(name):
    """CIK for an exact normalised-name match, else None (never guess)."""
    want = _norm(name)
    if not want:
        return None
    hits = {r["cik_str"] for r in _ticker_rows() if _norm(r["title"]) == want}
    return next(iter(hits)) if len(hits) == 1 else None


def _filings(cik, since):
    r = _get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json").json()["filings"]["recent"]
    for i, form in enumerate(r["form"]):
        if r["filingDate"][i] < since:
            continue
        items = r["items"][i] or ""
        if form in ("8-K", "8-K/A") and re.search(r"\b(1\.01|1\.02|5\.07|7\.01|8\.01)\b", items):
            pass
        elif form in ("DEFM14A", "PREM14A", "DEFA14A", "SC 14D9", "SC 14D9/A"):
            pass
        else:
            continue
        yield {"cik": int(cik), "form": form, "date": r["filingDate"][i], "acc": r["accessionNumber"][i],
               "items": items, "doc": r["primaryDocument"][i]}


def _docs(f):
    base = f"https://www.sec.gov/Archives/edgar/data/{f['cik']}/{f['acc'].replace('-', '')}/"
    docs = [(f["doc"], base + f["doc"])]
    if f["form"].startswith("8-K"):
        try:
            idx = _get(base).text
            for h in re.findall(r'href="/Archives/[^"]*/([^"/]*ex-?99[^"/]*\.htm)"', idx, re.I):
                docs.append((h, base + h))
        except Exception:
            pass
    return docs


def build_timeline(ticker, target, acquirer, announced, acquirer_cik=None, target_cik=None):
    """Milestone events since `announced` (YYYY-MM-DD) from target + acquirer filings."""
    tc = target_cik or next((r["cik_str"] for r in _ticker_rows() if r["ticker"] == ticker), None)
    ac = acquirer_cik or resolve_cik(acquirer)
    anchors = (_norm(target), _norm(acquirer), ticker)
    events, seen, notes = [], set(), []
    if not tc:
        notes.append("target CIK not found")
    if not ac:
        notes.append("acquirer CIK not resolved; acquirer filings not scanned")
    for cik, role in ((tc, "target"), (ac, "acquirer")):
        if not cik:
            continue
        try:
            filings = sorted(_filings(cik, announced), key=lambda f: (f["date"], not f["form"].startswith("8-K")))
        except Exception as e:
            notes.append(f"{role} filings unreadable: {e}")
            continue
        for f in filings:
            for name, url in _docs(f):
                try:
                    txt = _text(url)
                except Exception:
                    continue
                norm_txt = re.sub(r"\s+", " ", txt.replace("​", " ").replace("\xa0", " "))
                found = extract_events(txt, f["date"], anchors, "8-K" if f["form"].startswith("8-K") else f["form"])
                # Vote: only the TARGET's own 5.07 is its shareholder vote.
                if role == "target" and "5.07" in f["items"] and name == f["doc"]:
                    found += _vote_events(norm_txt, f["date"])
                # Meeting date from the proxy text.
                if role == "target" and f["form"] in ("DEFM14A", "PREM14A"):
                    md, phrase = extract_meeting_date(txt, filed_date=f["date"])
                    if md:
                        found.append({"type": "vote_scheduled", "label": "Shareholder meeting scheduled",
                                      "adverse": False, "regulator": None, "date": md,
                                      "date_basis": "stated", "quote": phrase})
                for e in found:
                    # Verification: the quote must be in the filing verbatim and the
                    # date must not precede the announcement. Otherwise drop.
                    q = re.sub(r"\s+", " ", e["quote"])
                    if q not in norm_txt:
                        continue
                    if e["date"] < announced or (e["type"] != "vote_scheduled" and e["date"] > f["date"]):
                        continue
                    key = (e["type"], e["regulator"], e["date"])
                    if key in seen:
                        continue
                    seen.add(key)
                    events.append({**e, "quote": q[:600], "accession": f["acc"], "form": f["form"],
                                   "filer": role, "filed": f["date"],
                                   "url": f"https://www.sec.gov/Archives/edgar/data/{f['cik']}/"
                                          f"{f['acc'].replace('-', '')}/{name}"})
    # Once the vote has a result, "meeting scheduled" is stale noise.
    if any(e["type"] in ("vote_passed", "vote_failed") for e in events):
        events = [e for e in events if e["type"] != "vote_scheduled"]
    stated = {(e["type"], e["regulator"]) for e in events if e["date_basis"] == "stated"}
    events = [e for e in events if e["date_basis"] == "stated" or (e["type"], e["regulator"]) not in stated]
    events.sort(key=lambda e: (e["date"], e["filed"]), reverse=True)
    return {"events": events, "notes": notes,
            "adverse": [e for e in events if e["adverse"]]}


def _vote_events(text, filing_date):
    """Target's own Item 5.07: the clause reporting the merger proposal's result,
    with the vote count when the filing gives one."""
    m = re.search(r"([^.:]{0,80}?\b(approved|did not approve|failed to approve|rejected|not approved)\b"
                  r"[^.:]{0,40}proposal to adopt the Merger Agreement[^.:]{0,160}?"
                  r"(?:by the following count:\s*Votes For\s+Votes Against\s+Abstentions\s+Broker Non-Votes\s+[\d,]+\s+[\d,]+\s+[\d,]+)?)", text)
    if not m:
        return []
    failed = m.group(2).lower() != "approved"
    d = re.search(r"On (" + MONTHS + r" \d{1,2}, 20\d{2}),[^.]{0,200}?special meeting", text)
    date, basis = filing_date, "filing_date"
    if d:
        date, basis = datetime.strptime(d.group(1), "%B %d, %Y").strftime("%Y-%m-%d"), "stated"
    return [{"type": "vote_failed" if failed else "vote_passed",
             "label": "Shareholder vote failed" if failed else "Shareholder vote passed",
             "adverse": failed, "regulator": None, "date": date, "date_basis": basis,
             "quote": m.group(1).strip()}]


def get_timeline(ticker, target, acquirer, announced):
    with _lock:
        hit = _cache.get(ticker)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    res = build_timeline(ticker, target, acquirer, announced)
    with _lock:
        _cache[ticker] = (time.time(), res)
    return res


# ── non-blocking access: a page request never waits on EDGAR ──────────────────
_inflight = set()
_errors = {}          # ticker -> time of last failed build (back off 10 min)


def peek(ticker):
    """Cached timeline or None. Never does I/O."""
    with _lock:
        hit = _cache.get(ticker)
    return hit[1] if hit and time.time() - hit[0] < CACHE_TTL else None


def kick(ticker, target, acquirer, announced):
    """Start a background build unless one is running (or failed <10 min ago).
    Returns 'ready' | 'pending' | 'error'."""
    if peek(ticker) is not None:
        return "ready"
    with _lock:
        if ticker in _inflight:
            return "pending"
        if time.time() - _errors.get(ticker, 0) < 600:
            return "error"
        _inflight.add(ticker)

    def run():
        try:
            get_timeline(ticker, target, acquirer, announced)
            _errors.pop(ticker, None)
        except Exception as e:
            print(f"[Milestones] {ticker}: build failed: {e}")
            _errors[ticker] = time.time()
        finally:
            with _lock:
                _inflight.discard(ticker)

    threading.Thread(target=run, daemon=True).start()
    return "pending"
