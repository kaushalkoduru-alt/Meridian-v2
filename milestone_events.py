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
    r"cannot be|will be|will have|must|shall|in the event|absent|neither|nor)\b", re.I)
PAST_DATE_GUARD = re.compile(r"(previously|originally|dated|filed|filings|submitted|"
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


def _event_date(s, trig_pos, filing_date, prefer_before=False):
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
    if after and not prefer_before:
        return after[0][1], "stated"
    if before:
        return before[-1][1], "stated"
    return filing_date, "filing_date"


# (type, label, adverse, trigger regex, extra require regex or None, use regulator?)
RULES = [
    ("hsr_expired", "HSR waiting period expired / early termination", False,
     r"\b(expired|was terminated|has been terminated|early termination[^.]{0,160}\bgranted\b|granted early termination)\b",
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
    ("agency_review_closed", "Antitrust review closed", False,
     r"\b(clos(?:ed|ing)|conclud(?:ed|ing)|terminat(?:ed|ing))\b[^.]{0,25}\b(?:its|the)\s+(?:antitrust\s+)?(?:investigation|review)\b|\bcompleted\s+its\s+(?:analysis|review|investigation)\b",
     None, True),
    ("approval_suspended", "Regulatory approval suspended", True,
     r"\b(suspend\w*|revok\w*|withdr[ae]w\w*|rescind\w*)\b[^.]{0,80}\bapproval\b|\bapproval\b[^.]{0,80}\b(suspended|revoked|withdrawn|rescinded)\b",
     None, True),
    ("outside_date_extended", "Outside date extended", True,
     r"\b(extended|has extended|have extended|agreed to extend|amended[^.]{0,80}to extend)\b[^.]{0,80}\b(End Date|Outside Date|Termination Date|Drop[- ]Dead Date|Outside Closing Date)\b[^.]{0,80}\b(?:to|until)(?=\s+" + MONTHS + ")",
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
            if typ in ("reg_approval", "approval_suspended", "outside_date_extended", "deal_repriced", "agency_review_closed") and not (
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
            d, basis = _event_date(s, m.end(), filing_date, prefer_before=(typ == "outside_date_extended"))
            if "[" in s:
                continue  # unfinished draft text ("on [August")
            # A proxy narrates history and restates conditions; only a DATED past
            # assertion counts there. An 8-K reports the event itself, so its
            # filing date is an acceptable fallback.
            if form_kind != "8-K" and basis != "stated":
                continue
            if typ == "outside_date_extended" and form_kind != "8-K":
                continue  # proxy text about the extension mechanism / negotiations
            if typ == "second_request" and basis != "stated":
                continue  # undated second-request mentions are background
            out.append({"type": typ, "label": label, "adverse": adverse,
                        "regulator": reg, "date": d, "date_basis": basis,
                        "quote": s.strip()})
    return out


# ── EDGAR plumbing ────────────────────────────────────────────────────────────
def _get(url, **kw):
    last = None
    for attempt in range(4):
        time.sleep(0.12 + attempt * 1.5)
        try:
            r = requests.get(url, headers=HEADERS, timeout=25, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code}")
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError:
            raise                      # 404 etc: a real answer, do not retry
        except requests.exceptions.RequestException as e:
            last = e
    raise last


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


_GENERIC = {"america", "americas", "usa", "us", "u", "s", "a", "inc", "corp", "co", "company", "holdings",
            "holding", "group", "ltd", "plc", "llc", "lp", "the", "and", "of", "partners", "management",
            "capital", "bidco", "investments"}


def _toks(name):
    name = re.sub(r"\((?:[^)]*)\)", " ", name or "")          # "(AMZN) (CIK 000...)"
    name = name.replace("\u2019", "").replace("'", "")          # Brink's -> brinks
    return [t for t in re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split()]


def _name_matches(acquirer, cand):
    """Conservative: every distinctive acquirer word is in the candidate's name
    (Teledyne -> TELEDYNE TECHNOLOGIES), or the candidate's distinctive words
    are all in the acquirer's (BRINKS CO -> The Brink's Company)."""
    a = [t for t in _toks(acquirer) if t not in _GENERIC]
    c = [t for t in _toks(cand) if t not in _GENERIC]
    if not a or not c:
        return False
    return all(t in c for t in a) or all(t in a for t in c)


def _fulltext_filers(target, announced):
    """Filers OTHER than the target whose 8-K/425 text names the target since
    announcement: [(cik, display_name, hits)]. EDGAR full-text search."""
    short = re.sub(r"[,.]?\s+(Inc|Corp|Corporation|Co|Company|Ltd|PLC|Holdings)\b\.?.*$", "", target or "", flags=re.I).strip()
    if len(short) < 3:
        return []
    r = _get("https://efts.sec.gov/LATEST/search-index",
             params={"q": '"' + short + '"', "forms": "8-K,425,SC 14D9,SC TO-T",
                             "startdt": announced, "enddt": datetime.utcnow().strftime("%Y-%m-%d")})
    r.raise_for_status()
    out = {}
    for h in r.json().get("hits", {}).get("hits", []):
        src = h.get("_source", {})
        for cik, dn in zip(src.get("ciks", []), src.get("display_names", [])):
            d = out.setdefault(int(cik), [dn, 0])
            d[1] += 1
    return [(c, v[0], v[1]) for c, v in out.items()]


def resolve_acquirer(ticker, target, acquirer, announced, target_cik=None):
    """(cik, method) or (None, reason). Never guesses: a candidate must both
    name the target in its own filings AND have a name matching the acquirer."""
    cik = resolve_cik(acquirer)
    if cik:
        return cik, "sec_name"
    try:
        cands = [c for c in _fulltext_filers(target, announced)
                 if c[0] != target_cik and _name_matches(acquirer, c[1])]
    except Exception as e:
        return None, f"full-text search failed: {e}"
    if cands:
        cands.sort(key=lambda c: -c[2])
        return cands[0][0], "fulltext"
    return None, "no SEC filer by that name mentions the target (likely private / foreign buyer)"


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


def _docs(f, fails=None):
    base = f"https://www.sec.gov/Archives/edgar/data/{f['cik']}/{f['acc'].replace('-', '')}/"
    docs = [(f["doc"], base + f["doc"])]
    if f["form"].startswith("8-K"):
        try:
            idx = _get(base).text
            for h in re.findall(r'href="/Archives/[^"]*/([^"/]*ex-?99[^"/]*\.htm)"', idx, re.I):
                docs.append((h, base + h))
        except Exception:
            if fails is not None:
                fails.append(f"{f['acc']} exhibit index")
    return docs


def build_timeline(ticker, target, acquirer, announced, acquirer_cik=None, target_cik=None):
    """Milestone events since `announced` (YYYY-MM-DD) from target + acquirer filings."""
    tc = target_cik or next((r["cik_str"] for r in _ticker_rows() if r["ticker"] == ticker), None)
    ac, how = (acquirer_cik, "given") if acquirer_cik else resolve_acquirer(ticker, target, acquirer, announced, tc)
    anchors = (_norm(target), _norm(acquirer), ticker)
    events, seen, notes, fails = [], set(), [], []
    if not tc:
        notes.append("target CIK not found")
    if not ac:
        notes.append(f"acquirer not scanned: {how}")
        if how.startswith("full-text search failed"):
            fails.append("acquirer lookup")
    for cik, role in ((tc, "target"), (ac, "acquirer")):
        if not cik:
            continue
        try:
            filings = sorted(_filings(cik, announced), key=lambda f: (f["date"], not f["form"].startswith("8-K")))
        except Exception as e:
            notes.append(f"{role} filings unreadable: {e}")
            fails.append(f"{role} filing list")
            continue
        for f in filings:
            for name, url in _docs(f, fails):
                try:
                    txt = _text(url)
                except Exception:
                    fails.append(f"{f['acc']} {name}")
                    continue
                norm_txt = re.sub(r"\s+", " ", txt.replace("​", " ").replace("\xa0", " "))
                found = extract_events(txt, f["date"], anchors, "8-K" if f["form"].startswith("8-K") else f["form"])
                # Vote: only the TARGET's own 5.07 is its shareholder vote.
                if role == "target" and "5.07" in f["items"] and name == f["doc"]:
                    found += _vote_events(norm_txt, f["date"])
                # Meeting date from the proxy text.
                if role == "target" and f["form"] in ("DEFM14A", "PREM14A"):
                    md, phrase = extract_meeting_date(txt, filed_date=f["date"])
                    if md and _acquirer_meeting(norm_txt, phrase, acquirer):
                        md = None  # the ACQUIRER's holders' meeting, not the target's
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
    if any(e["type"] in ("vote_passed", "vote_failed", "vote_held") for e in events):
        events = [e for e in events if e["type"] != "vote_scheduled"]
    # A second request that a later-dated waiting-period expiry / clearance has
    # followed is history, not a live risk signal.
    cleared = [e["date"] for e in events if e["type"] in ("hsr_expired", "cfius_clearance", "agency_review_closed")]
    events = [e for e in events
              if not (e["type"] == "second_request" and any(c >= e["date"] for c in cleared))]
    stated = {(e["type"], e["regulator"]) for e in events if e["date_basis"] == "stated"}
    events = [e for e in events if e["date_basis"] == "stated" or (e["type"], e["regulator"]) not in stated]
    events.sort(key=lambda e: (e["date"], e["filed"]), reverse=True)
    for e in events:
        if e["type"] == "second_request":
            e["caveat"] = ("This records that a Second Request was issued, not that it is unresolved. "
                           "No later clearance was found in the filings Meridian read, but a clearance "
                           "disclosed elsewhere would not show here.")
        elif e["type"] == "approval_suspended":
            e["caveat"] = ("This records the suspension as of the filing. A later reinstatement may not "
                           "be reflected until a filing reports it.")
    if fails:
        notes.append(f"{len(fails)} document(s) could not be read; timeline may be incomplete")
    return {"events": events, "notes": notes, "partial": bool(fails),
            "adverse": [e for e in events if e["adverse"]]}


def _acquirer_meeting(text, phrase, acquirer):
    """True when the matched meeting phrase sits in a sentence about the
    acquirer's own stockholder meeting (K-C and FOX proxies describe both)."""
    i = text.find(re.sub(r"\s+", " ", phrase or ""))
    if i < 0:
        return False
    w = _norm(acquirer).split()
    if not w:
        return False
    start = max(text.rfind('. ', 0, i) + 2, i - 200)   # this sentence only
    ctx = text[start:i + len(phrase) + 30].lower()
    a0 = re.escape(w[0])
    return bool(re.search(a0 + r"\W+(?:\w+\W+){0,4}(?:special\W+)?(?:meeting|stockholders|shareholders|holders)", ctx)
                or re.search(r"(?:meeting|stockholders|shareholders|holders)\W+of\W+(?:the\W+)?(?:holders\W+of\W+)?" + a0, ctx))


# The merger proposal, in the ways Item 5.07 words it.
_MERGER_PROP = re.compile(
    r"Merger\s+(?:Agreement\s+)?Proposal"
    r"|proposal\s+to\s+(?:adopt|approve)[^.]{0,120}?(?:Merger\s+Agreement|Agreement\s+and\s+Plan\s+of\s+Merger)"
    r"|(?:approved|adopted)\s+(?:and\s+(?:approved|adopted)\s+)?the\s+(?:Merger\s+Agreement|Agreement\s+and\s+Plan\s+of\s+Merger)"
    r"|adopt(?:ion\s+of)?\s+the\s+(?:Merger\s+Agreement|Agreement\s+and\s+Plan\s+of\s+Merger)", re.I)
# How a sentence refers to the merger proposal.
_MERGER_ID = re.compile(
    r"Merger\s+(?:Agreement\s+)?Proposal|Proposal\s+1\b"
    r"|\bto\s+(?:adopt|approve)\s+the\s+(?:Merger\s+Agreement|Agreement\s+and\s+Plan\s+of\s+Merger)"
    r"|proposal\s+to\s+(?:adopt|approve)[^.]{0,120}?(?:Merger\s+Agreement|Agreement\s+and\s+Plan\s+of\s+Merger)"
    r"|(?:adopted|approved)\s+(?:and\s+(?:adopted|approved)\s+)?the\s+(?:Merger\s+Agreement|Agreement\s+and\s+Plan\s+of\s+Merger)", re.I)
_FAIL = re.compile(r"\b(?:did\s+not\s+(?:receive|obtain|approve|adopt)|was\s+not\s+(?:approved|adopted)|not\s+approved|rejected|was\s+not\s+obtained)\b", re.I)
_PASS = re.compile(r"\b(?:approved|adopted)\b", re.I)
# Board action, recommendations and hypotheticals are not a stockholder result.
_NOT_RESULT = re.compile(r"\b(?:Board|board of directors|unanimous\w*|previously|recommend\w*|if|may|will|would|could|necessary|insufficient)\b")


def _vote_events(text, filing_date):
    """The target's merger-vote result from its Item 5.07, or [].

    Only a meeting that voted on the MERGER counts: an annual-meeting 5.07 has no
    merger proposal in it and yields nothing. passed / failed need an explicit
    stockholder-result sentence tied to the merger proposal; if the filing only
    shows a vote table, a neutral 'vote held' event carries the counts instead of
    a guessed verdict."""
    i = text.find("Item 5.07")
    if i < 0:
        return []
    end = re.search(r"Item\s+(?:7\.01|8\.01|9\.01)|SIGNATURE", text[i + 40:])
    sec = text[i: i + 40 + end.start()] if end else text[i:]
    if not _MERGER_PROP.search(sec):
        return []
    d = re.search(r"On\s+(" + MONTHS + r"\s+\d{1,2},\s+20\d{2}),.{0,400}?meeting", sec)
    date, basis = filing_date, "filing_date"
    if d:
        date, basis = datetime.strptime(re.sub(r"\s+", " ", d.group(1)), "%B %d, %Y").strftime("%Y-%m-%d"), "stated"

    def ev(typ, label, adverse, q):
        return [{"type": typ, "label": label, "adverse": adverse, "regulator": None,
                 "date": date, "date_basis": basis, "quote": q.strip()[:500]}]

    def clip(pos, end):
        q = sec[max(0, pos - 150): end + 150]
        q = q[q.find(" ") + 1:] if pos - 150 > 0 else q          # whole words only
        return q[: q.rfind(" ")] if end + 150 < len(sec) else q

    markers = [m2.end() for m2 in _MERGER_ID.finditer(sec)]
    sides = [m2.start() for m2 in re.finditer(r"advisory|compensation|golden\s+parachute|adjourn", sec, re.I)]
    for verdict, rx in (("fail", _FAIL), ("pass", _PASS)):
        for hit in rx.finditer(sec):
            before = sec[max(0, hit.start() - 200): hit.start()]
            after = sec[hit.end(): hit.end() + 140]
            if re.search(r"\b(?:Board|board of directors|previously|unanimously|recommend\w*|if|may|could)\b", before[-90:]):
                continue
            # the nearest thing named before the verdict must be the merger, not the
            # compensation / adjournment proposal that follows it
            lm = max([x for x in markers if x <= hit.start()], default=-1)
            ls = max([x for x in sides if x <= hit.start()], default=-1)
            near_merger = lm > ls and hit.start() - lm < 700
            named_after = re.search(r"Merger\s+Agreement|Merger\s+Proposal|Agreement\s+and\s+Plan\s+of\s+Merger", after[:70], re.I) \
                and not re.search(r"advisory|compensation", sec[max(0, hit.start() - 60): hit.end() + 70], re.I)
            subject = re.search(r"(?:stockholders|shareholders|holders|Proposal(?:\s+\d)?|proposal|Merger(?:\s+Agreement)?|which|was|were)\W+(?:\w+\W+){0,3}$", before, re.I)
            if not (near_merger or named_after) or not subject:
                continue
            if verdict == "fail":
                return ev("vote_failed", "Shareholder vote failed", True, clip(hit.start(), hit.end()))
            return ev("vote_passed", "Shareholder vote passed", False, clip(hit.start(), hit.end()))
    # "Each proposal was approved ... Because Proposal 1 was approved" style
    for x in [x for x in _sentences(sec) if 25 < len(x) < 600]:
        if re.search(r"\b(?:each|both|all)\s+(?:of\s+the\s+)?proposals?\s+(?:was|were)\s+approved", x, re.I):
            return ev("vote_passed", "Shareholder vote passed", False, x)
    # "there were sufficient votes to approve the Merger Agreement Proposal" is not
    # a result either; fall back to the table, stated neutrally.
    t = re.search(r"(?:Merger(?:\s+Agreement)?\s+Proposal|Proposal\s+1)\s*:?\s*Votes?\s+For[^A-Za-z]{0,10}(?:Votes?\s+)?Against.{0,120}", sec, re.I)
    if t:
        return ev("vote_held", "Shareholder vote held (see result in filing)", False, t.group(0))
    return []


def get_timeline(ticker, target, acquirer, announced):
    with _lock:
        hit = _cache.get(ticker)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    res = build_timeline(ticker, target, acquirer, announced)
    with _lock:
        # a partial read expires in 10 minutes instead of CACHE_TTL
        _cache[ticker] = (time.time() - (CACHE_TTL - 600 if res.get("partial") else 0), res)
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
