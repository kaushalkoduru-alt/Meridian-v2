"""
CAPITAL STRUCTURE — the target's debt, tranche by tranche, from its last 10-K

Built for a named customer: a credit club that sources ideas from the feed. A
credit member reads a deal to decide whether there is a bond or a loan worth
trading, and the first question is always "what is outstanding, at what rate,
maturing when, and what happens to it if the merger closes?" A wrong debt figure
here does not shade a score — it loses a user.

WHAT IT READS, from the most recent 10-K debt footnote:

  Per tranche  instrument type; FACE amount (what is owed, not net-of-issuance-
               costs — net captured separately where the filing splits them, as
               BZH's junior subs do: $100.8M face vs $78.5M net); for revolvers
               the amount DRAWN, not capacity (BZH's is $0 on $365M — reporting
               the capacity is wrong by $365M); the rate as the filing states it
               (a fixed coupon OR a floating formula — never forced to one
               number); maturity; and stated seniority where the filing gives
               it.

  Change of    For each tranche, what the filing says happens to it in a change
  control      of control. This is the differentiator. "Buyer shall pay all
               outstanding obligations" (NATH) — gone at close, a pass. "may be
               terminated upon a change of control" (CBZ) — likely refinanced.
               A change-of-control put / the tranche survives — tradeable, the
               credit opportunity. Captured verbatim; no waterfall modelled.

THE RECONCILIATION BARRIER

  The footnote states a total ("Total debt, net $1,029,114" for BZH, $48,143 net
  / $48,400 face for NATH). The extracted tranches, plus the filing's own
  adjustment lines (issuance costs, accretion), must sum back to it. If they do
  not, the extraction missed a tranche — and the honest output is then "capital
  structure incomplete", not a partial table. This is the premium cross-check
  equivalent: an independent number in the same filing that proves the read.

THE REFUSE CASE

  Foreign filers, recent IPOs, PE-owned targets: no usable 10-K debt footnote.
  Where it cannot be found or read, the output is "capital structure not
  disclosed" — never an empty or guessed table. A blank is honest; a wrong
  tranche is not.

METHOD

  LLM extraction against the located footnote, not regex — this is table and
  prose reading. `llm_fn` is injected the same way deal_direction/deal_commitment
  take theirs; with no model layer the module refuses rather than guessing.

  Ground truth is three hand-read targets — CBZ (one credit agreement, term loan
  + revolver, a SOFR range), BZH (five tranches, the hard table), NATH (one term
  loan, paid off at close). The extractor must reproduce those before it runs on
  anything else.

NOT WIRED IN. No feed, no display. Build, run against the three, report.
"""

import json
import re
import time

import requests

SEC_HEADERS = {"User-Agent": "Kaushal Koduru kaushalkoduru@gmail.com"}

# ── status values the caller renders ─────────────────────────────────────────
OK           = "ok"             # tranches found and they reconcile
INCOMPLETE   = "incomplete"     # tranches found but they do NOT reconcile
NOT_DISCLOSED = "not_disclosed" # no readable 10-K debt footnote — the refuse case
UNAVAILABLE  = "unavailable"    # no model layer; the module will not guess


# ════════════════════════════════════════════════════════════════════════════
# 1. FIND THE FILING
# ════════════════════════════════════════════════════════════════════════════

def _cik_for_ticker(ticker):
    """
    Ticker -> zero-padded CIK. In the live pipeline the caller already knows the
    CIK and passes it; this is only for standalone use. company_tickers.json
    drops names once they delist, and merger targets delist — so a browse-edgar
    lookup backs it up (ALOT, AVNS, CPRX were all missing from the JSON).
    """
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers=SEC_HEADERS, timeout=20)
        if r.status_code == 200:
            for row in r.json().values():
                if row.get("ticker", "").upper() == ticker.upper():
                    return str(row["cik_str"]).zfill(10)
    except Exception:
        pass
    try:
        r = requests.get(
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={ticker}&type=10-K&count=1&output=atom",
            headers=SEC_HEADERS, timeout=25)
        m = re.search(r'<cik>\s*(\d+)\s*</cik>', r.text, re.I)
        if m:
            return m.group(1).zfill(10)
    except Exception:
        pass
    return None


def _plain_text(html):
    """HTML → text. The one dependency the rest of the codebase already uses."""
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def _fetch(url):
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=30)
        time.sleep(0.12)
        if r.status_code != 200:
            return None
        return _plain_text(r.text)
    except Exception:
        return None


def _fetch_raw(url):
    """Raw HTML — for filing-index pages, whose <table> is the point."""
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=30)
        time.sleep(0.12)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


# A 10-K/A is often a Part III amendment carrying no financial statements. When
# the newest annual filing is an amendment, we take it only if it actually holds
# the statements; otherwise we fall back to the newest original 10-K. NATH's most
# recent filing is exactly this case.
def _has_financial_statements(text):
    if not text or len(text) < 40000:
        return False
    t = text.upper()
    return ("CONSOLIDATED BALANCE SHEET" in t
            and ("NOTES TO CONSOLIDATED FINANCIAL STATEMENTS" in t
                 or "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS" in t))


def _all_filings(cik):
    """
    Every filing on record for a CIK, newest first, as
    [{form, filed, accession, primary_doc}]. Follows the `files` shards so this
    reaches filings older than the ~1,000 the main document carries — the
    senior-notes indentures are referenced back to 8-Ks from 2017-2024.
    """
    cik10 = str(cik).zfill(10)
    out = []
    try:
        sub = requests.get(f"https://data.sec.gov/submissions/CIK{cik10}.json",
                           headers=SEC_HEADERS, timeout=20).json()
    except Exception:
        return out
    blocks = [sub.get("filings", {}).get("recent", {})]
    for extra in sub.get("filings", {}).get("files", []):
        try:
            time.sleep(0.12)
            blocks.append(requests.get(
                f"https://data.sec.gov/submissions/{extra['name']}",
                headers=SEC_HEADERS, timeout=20).json())
        except Exception:
            pass
    for b in blocks:
        forms = b.get("form", [])
        for i, f in enumerate(forms):
            out.append({
                "form": f,
                "filed": b.get("filingDate", [None])[i],
                "accession": b.get("accessionNumber", [None])[i],
                "primary_doc": b.get("primaryDocument", [None])[i],
            })
    out.sort(key=lambda r: r["filed"] or "", reverse=True)
    return out


def find_target_10k(ticker, cik=None, fetch=None):
    """
    The most recent 10-K that carries financial statements.

    Returns {cik, accession, form, filed, primary_doc, doc_url, text} or None.
    `fetch` is injected for tests; defaults to the module's own fetcher.
    """
    fetch = fetch or _fetch
    cik = cik or _cik_for_ticker(ticker)
    if not cik:
        return None
    rows = [r for r in _all_filings(cik) if r["form"] in ("10-K", "10-K/A")]

    for row in rows:
        if not row["accession"] or not row["primary_doc"]:
            continue
        acc_nodash = row["accession"].replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
               f"{acc_nodash}/{row['primary_doc']}")
        text = fetch(url)
        if not _has_financial_statements(text):
            # An amendment with no statements, or an unreadable document. Keep
            # looking down the list for an original 10-K that has them.
            continue
        return {
            "cik": str(int(cik)), "accession": row["accession"], "form": row["form"],
            "filed": row["filed"], "primary_doc": row["primary_doc"],
            "doc_url": url, "text": text,
        }
    return None


# ════════════════════════════════════════════════════════════════════════════
# 2. LOCATE THE DEBT FOOTNOTE
# ════════════════════════════════════════════════════════════════════════════

# Note headings vary — "Note 10. Debt and Financing Arrangements" (CBZ),
# "(7) Borrowings" (BZH), "NOTE J – LONG-TERM DEBT" (NATH). All three shapes,
# plus the words filers actually use for the debt note.
_HEAD_PAT = re.compile(
    r'(?:'
    r'NOTE\s+[A-Z0-9]{1,3}\s*[–—:.\-]\s*'
      r'(?:LONG[\-\s]?TERM\s+DEBT|DEBT(?:\s+AND\s+FINANCING(?:\s+ARRANGEMENTS)?)?|'
       r'BORROWINGS|NOTES?\s+PAYABLE|INDEBTEDNESS|CREDIT\s+FACILITIES?|'
       r'LONG[\-\s]?TERM\s+OBLIGATIONS|DEBT\s+OBLIGATIONS)'
    r'|'
    r'\(\d{1,2}\)\s*(?:Borrowings|Debt|Long[\-\s]?Term\s+Debt|Notes?\s+Payable|'
      r'Indebtedness|Debt\s+and\s+Financing(?:\s+Arrangements)?|Debt\s+Obligations)'
    r'|'
    r'\b\d{1,2}\.\s+(?:Borrowings|Debt|Long[\-\s]?Term\s+Debt|Notes?\s+Payable|'
      r'Indebtedness)\b'
    r')', re.I)

# Where the NEXT note begins — used to cut the tail of the captured block. The
# capture group holds the heading text so a running page header that repeats the
# current heading ("NOTE J – LONG-TERM DEBT (continued)") can be told apart from
# a genuine new note and skipped.
_NEXT_NOTE_PAT = re.compile(
    r'(NOTE\s+[A-Z0-9]{1,3}\s*[–—:.\-]\s*[A-Z][A-Za-z ,\-]{2,40}'
    r'|\(\d{1,2}\)\s+[A-Z][a-z][A-Za-z ,\-]{2,40}'
    r'|\b\d{1,2}\.\s+[A-Z][a-z]+(?:\s+[A-Za-z]+){0,3})')

_SECTION_MAX = 20000


def _score_heading(text, start):
    """
    How much the block after a heading looks like the debt NOTE (a dense dollar
    table with a stated total) rather than an MD&A mention of the same words.
    """
    w = text[max(0, start - 500):start + _SECTION_MAX]
    sc = 0
    if re.search(r'total\s+(?:long[\-\s]?term\s+)?(?:debt|borrowings|senior\s+notes)'
                 r'[,]?\s*(?:net)?', w, re.I):
        sc += 3
    if len(re.findall(r'\$\s*[\d,]{3,}', w)) >= 4:
        sc += 2
    if re.search(r'matur', w, re.I):
        sc += 2
    sc += min(3, len(re.findall(r'senior\s+notes|term\s+loan|revolv|subordinated', w, re.I)))
    if re.search(r'risk\s+factors|forward[\-\s]looking\s+statements|item\s+1a', w, re.I):
        sc -= 3
    if re.search(r'consist(?:s|ed)?\s+of\s+the\s+following|was\s+as\s+follows|'
                 r'following\s+table', text[start:start + 320], re.I):
        sc += 2
    return sc


def _coc_context(text, already):
    """
    Change-of-control language that is not already inside the captured footnote.

    For a live merger target the 10-K often states what happens to the debt at
    close in a subsequent-events note or a credit-agreement paragraph outside the
    debt table (NATH puts it at the end of the debt note; another filer might put
    it elsewhere). BZH's 10-K says nothing — the senior-notes put lives in the
    indenture, not here — and this returns empty, which is the honest result.
    """
    out = []
    pat = re.compile(
        r'(?:change\s+(?:of|in)\s+control'
        r'|pay(?:ing)?\s+(?:all\s+)?(?:the\s+)?(?:outstanding\s+)?obligations'
        r'|repurchase[^.]{0,40}?(?:notes|indenture)'
        r'|upon\s+(?:a\s+|the\s+)?(?:consummation\s+of\s+the\s+)?merger)', re.I)
    for m in pat.finditer(text):
        seg = text[max(0, m.start() - 600):m.start() + 1300]
        if seg in already or any(seg[:200] in a for a in out):
            continue
        if not re.search(r'credit\s+facilit|senior\s+notes|indenture|term\s+loan|'
                         r'revolv|subordinated|merger\s+agreement|obligations\s+under',
                         seg, re.I):
            continue
        out.append(seg)
        if len(out) >= 4:
            break
    return out


def locate_debt_footnote(text):
    """
    Returns (section_text, heading) or (None, None).

    section_text is the debt note plus any change-of-control language found
    elsewhere in the filing, capped so it fits one model call.
    """
    if not text:
        return None, None
    cands = [(m.start(), m.group(0).strip()) for m in _HEAD_PAT.finditer(text)]
    if not cands:
        return None, None
    best = max(cands, key=lambda c: (_score_heading(text, c[0]), -c[0]))
    start, heading = best
    if _score_heading(text, start) < 4:
        # Nothing that reads like a real debt table — treat as not disclosed
        # rather than feeding the model a paragraph of risk-factor prose.
        return None, None

    heading_norm = re.sub(r'\s+', ' ', heading).strip().lower()
    tail_off = start + 1800
    end = start + _SECTION_MAX
    for m in _NEXT_NOTE_PAT.finditer(text[tail_off:start + _SECTION_MAX]):
        cand = re.sub(r'\s+', ' ', m.group(1)).strip().lower()
        after = text[tail_off + m.end():tail_off + m.end() + 20].lower()
        # a running page header repeating this same note, not a new one
        if cand == heading_norm or after.lstrip().startswith("(continued)"):
            continue
        if cand[:16] == heading_norm[:16]:
            continue
        end = tail_off + m.start()
        break
    section = text[start:end]

    extra = _coc_context(text, section)
    if extra:
        section += "\n\n--- change-of-control language elsewhere in the 10-K ---\n\n"
        section += "\n\n...\n\n".join(extra)
    return section[:24000], heading


# ════════════════════════════════════════════════════════════════════════════
# 3. THE MODEL READ
# ════════════════════════════════════════════════════════════════════════════

_INSTRUMENT_TYPES = ("term_loan", "senior_notes", "senior_secured_notes",
                     "revolver", "junior_subordinated", "convertible",
                     "mortgage", "other")

_PROMPT = """You are extracting a company's debt capital structure from the debt \
footnote of its 10-K. Accuracy over completeness: a wrong figure is worse than \
a blank. Use ONLY what the text states. Never infer or estimate an amount.

Company: {company} (ticker {ticker})

Return a single JSON object, no prose, with this exact shape:

{{
  "disclosure_found": true|false,      // is there a real debt table with tranche-level detail here?
  "currency_unit": "thousands"|"millions"|"dollars",   // the unit the TABLE is stated in
  "as_of": "the balance-sheet date the current-year figures are stated as of, e.g. 2025-09-30",

  "stated_net_total": {{
    // the filing's own total-debt line, AFTER debt issuance costs / discount / accretion.
    // If the table splits current and long-term with no combined line, sum those
    // two subtotals and say so in "note".
    "label": "verbatim label(s), e.g. 'Total debt, net'",
    "amount": <number in currency_unit>,
    "note": "how it was derived if you summed subtotals, else null"
  }},
  "stated_face_total": {{
    "label": "verbatim label for an aggregate PRINCIPAL / face total if the filing states one (e.g. a maturities-table total), else null",
    "amount": <number or null>
  }},

  "tranches": [
    {{
      "instrument_type": one of {types},
      "name": "verbatim label from the filing",
      "face_amount": <number or null>,   // PRINCIPAL owed, gross of issuance costs/discount/accretion
      "net_amount": <number or null>,    // carrying amount if the filing states it for THIS tranche
      "drawn": <number or null>,         // revolvers only: amount actually borrowed
      "capacity": <number or null>,      // revolvers only: total commitment / borrowing base
      "rate": {{
        "kind": "fixed"|"floating",
        "text": "verbatim: a coupon like '5.875%' OR a formula like 'SOFR + 1.40%, 5.175% at period end'. Never force a single number onto a range or a formula."
      }},
      "maturity": "YYYY-MM or YYYY-MM-DD or the filing's words",
      "issuance_date": "YYYY-MM if the filing gives when this note/loan was issued (e.g. a redemption table's 'Issuance Date' column), else null",
      "seniority": "verbatim ranking language, or null if the filing does not state it",
      "change_of_control": "what the filing says happens to THIS tranche on a change of control / merger, or null",
      "change_of_control_quote": "the sentence it came from, or null"
    }}
  ],

  "adjustments": [
    // every line the filing SUBTRACTS from (or adds to) gross principal to reach the net total:
    // unamortized debt issuance costs, original issue discount, unamortized accretion, premium.
    // Amounts NEGATIVE when they reduce debt. Do not include tranche principal here.
    {{"label": "Unamortized debt issuance costs", "amount": -6611}},
    {{"label": "Unamortized accretion, Junior Subordinated Notes", "amount": -22303}}
  ],

  "notes": "anything the reader needs — a tranche shown only as an aggregate subtotal, a face amount given only in prose, etc."
}}

The arithmetic that must hold (the filing's own bridge):
  sum(tranche face_amount, or drawn for revolvers) + sum(adjustments) == stated_net_total.amount

Rules:
- A revolver with nothing drawn is debt of 0. Put 0 in "drawn", the commitment in "capacity". Never report capacity as the debt figure.
- face_amount is principal. If the filing shows a tranche only net (e.g. "net of unamortized accretion of $22,303"), set net_amount to the shown figure and face_amount to principal (net + the accretion/discount), and still list that accretion in "adjustments".
- "change_of_control" is per tranche. A general credit-agreement change-of-control provision applies to the tranches under that agreement — say so in the quote. If nothing in the text addresses a tranche, use null. Do not guess.
- No real debt table here (foreign filer, no disclosure): set "disclosure_found" false, tranches empty.

DEBT FOOTNOTE TEXT:
----------------------------------------
{section}
----------------------------------------
JSON:"""


def build_prompt(ticker, company, section_text):
    return _PROMPT.format(ticker=ticker, company=company or ticker,
                          section=section_text,
                          types=", ".join(f'"{t}"' for t in _INSTRUMENT_TYPES))


def _parse_model_json(raw):
    """Model output → dict. Tolerates a ```json fence and leading/trailing prose."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r'^```(?:json)?', '', s).strip()
    s = re.sub(r'```$', '', s).strip()
    # first balanced-looking object
    i = s.find("{")
    j = s.rfind("}")
    if i == -1 or j == -1 or j <= i:
        return None
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# 3b. CHANGE OF CONTROL FROM THE EX-4 INDENTURE (public notes only)
# ════════════════════════════════════════════════════════════════════════════
#
# The debt footnote almost never states what a public note does in a change of
# control — that clause lives in the indenture, filed as EX-4 and usually
# incorporated by reference to the 8-K that issued the note. For a credit
# member this is the whole question: senior notes with a change-of-control put
# are exactly what they would buy, and whether the put survives the merger is
# the trade. So for senior/convertible notes with a null footnote reading we
# follow the reference, find the "Change of Control" clause, and read the put
# terms — that clause only, not the whole 300k-character indenture.
#
# No indenture on file, or no clause found: the field stays null. Not guessed.

_MONTHS_RE = (r'January|February|March|April|May|June|July|August|September|'
              r'October|November|December')
_MONTH_NUM = {m: i for i, m in enumerate(
    "January February March April May June July August September October "
    "November December".split(), 1)}

# Rows in the 10-K exhibit index name an indenture and then, in a parenthetical,
# the filing it was filed with. Curly apostrophes survive the HTML strip, so the
# parse is done in pieces over a window rather than one brittle pattern.
_DATE_RE = re.compile(r'(' + _MONTHS_RE + r')\s+(\d{1,2}),?\s+(\d{4})')

# The operative section, by the names indentures actually give it.
_COC_CLAUSE_HEAD = re.compile(
    r'(?:Section\s+[0-9]+\.[0-9]+\s+)?'
    r'(?:Change\s+of\s+Control(?:\s+Triggering\s+Event)?'
    r'|Repurchase\s+at\s+the\s+Option\s+of\s+Holders(?:\s+Upon\s+a\s+Change\s+of\s+Control)?'
    r'|Offer\s+to\s+Repurchase\s+Upon\s+(?:a\s+)?Change\s+of\s+Control'
    r'|Purchase\s+of\s+(?:the\s+)?(?:Securities|Notes)\s+Upon\s+a\s+Change\s+of\s+Control)'
    r'\s*\.', re.I)

_COC_PROMPT = """This is the change-of-control section of a public note \
indenture. Read ONLY what is here. Return one JSON object:

{{
  "has_change_of_control_put": true|false,   // may holders REQUIRE the company to repurchase their notes on a change of control?
  "repurchase_price": "e.g. '101% of principal plus accrued and unpaid interest', verbatim, or null",
  "trigger": "one sentence: what counts as a change of control here",
  "note_survives": true|false,   // true unless the text says the notes are automatically redeemed/cancelled on a change of control (a put is the holder's option, so the note otherwise survives)
  "quote": "the single operative sentence, verbatim"
}}

CLAUSE:
----------------------------------------
{clause}
----------------------------------------
JSON:"""


def _iso(month_day_year):
    m = re.match(r'(' + _MONTHS_RE + r')\s+(\d{1,2}),\s+(\d{4})', month_day_year)
    if not m:
        return None
    return f"{m.group(3)}-{_MONTH_NUM[m.group(1)]:02d}-{int(m.group(2)):02d}"


def _parse_indenture_refs(exhibit_index_text):
    """[{desc, exhibit, source_form, source_date, coupon, note_year}] from the
    10-K exhibit index — one entry per 'Indenture ... (incorporated by
    reference to Exhibit X of the ... Form Y filed on <date>)' row."""
    t = exhibit_index_text or ""
    refs, seen = [], set()
    for m in re.finditer(r'\bIndenture\b', t):
        win = t[m.start():m.start() + 480]
        paren = re.search(r'\(([^)]{0,400}?(?:incorporated|filed)[^)]{0,360})\)', win)
        if not paren:
            continue
        p = paren.group(1)
        exh = re.search(r'Exhibit\s+(\d+\.\d+(?:\([a-z0-9]+\))?)', p, re.I)
        form = re.search(r'\bForm\s+([A-Z0-9][A-Z0-9/\-]{0,9})', p)
        dm = _DATE_RE.search(p)
        if not (exh and form and dm):
            continue
        desc = re.sub(r'\s+', ' ', win[:paren.start()]).strip(" ,–—-")
        coupon = re.search(r'(\d+\.\d+)\s*%', desc)
        yr = re.search(r'due\s+(\d{4})|Notes?\s+(?:due\s+)?(\d{4})', desc, re.I)
        key = (exh.group(1), dm.group(0))
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "desc": desc,
            "exhibit": exh.group(1).split("(")[0],
            "source_form": form.group(1).upper(),
            "source_date": _iso(f"{dm.group(1)} {dm.group(2)}, {dm.group(3)}"),
            "coupon": coupon.group(1) if coupon else None,
            "note_year": (yr.group(1) or yr.group(2)) if yr else None,
        })
    return refs


def _match_ref(tranche, refs):
    """
    Pick the indenture ref for a tranche — conservatively.

    A wrong indenture returns a confident wrong put, so the rule is: when the
    tranche names a coupon, it matches ONLY a ref for that exact coupon. If the
    issuer identifies its indentures by coupon (OGN: "Indenture ... with respect
    to 4.125% Senior Secured Notes due 2028") and ours is not among them, the
    answer is None — never the nearest same-year indenture, which is a different
    note's document. Year / issuance-date matching is a fallback only for refs
    that carry no coupon at all (BZH's older indentures name none).
    """
    name = tranche.get("name") or ""
    c = re.search(r'(\d+\.\d+)\s*%', name)
    coupon = c.group(1) if c else None
    y = re.search(r'\b(19|20)\d{2}\b', name) or re.search(r'\b(19|20)\d{2}\b',
                                                          str(tranche.get("maturity") or ""))
    year = y.group(0) if y else None
    iss = str(tranche.get("issuance_date") or "")
    iss_ym = iss[:7] if re.match(r'\d{4}-\d{2}', iss) else None

    def specific(r):
        return not re.search(r'form\s+of\s+(?:indenture|.{0,20}debt securities)',
                             r["desc"], re.I)

    if coupon:
        for want_specific in (True, False):
            for r in refs:
                if want_specific and not specific(r):
                    continue
                if r["coupon"] == coupon and (
                        not (year and r["note_year"]) or r["note_year"] == year):
                    return r
        # A ref names a DIFFERENT coupon for our tranche's year: that ref is a
        # sibling note's indenture, and falling through to year matching would
        # grab it. Refuse instead. (BZH's 2017 indenture row names no coupon and
        # no sibling shares 2027, so its 5.875% notes still resolve by date.)
        if year and any(r["coupon"] and r["coupon"] != coupon
                        and r["note_year"] == year for r in refs):
            return None

    for want_specific in (True, False):
        for r in refs:
            if want_specific and not specific(r):
                continue
            if year and r["note_year"] == year:
                return r
            if iss_ym and (r["source_date"] or "").startswith(iss_ym):
                return r
    return None


def _resolve_exhibit_url(cik, source_form, source_date, exhibit_label,
                         fetch_index=None):
    """The filing on `source_date` of type `source_form` → the URL of its
    EX-<exhibit_label> document."""
    fetch_index = fetch_index or _fetch_raw
    if not source_date:
        return None
    want = source_date
    near = {want}
    # 'dated' vs 'filed on' can differ by a day or two
    y, mo, d = (int(x) for x in want.split("-"))
    for off in (-3, -2, -1, 1, 2, 3):
        try:
            from datetime import date, timedelta
            near.add((date(y, mo, d) + timedelta(days=off)).isoformat())
        except Exception:
            pass
    cand = [r for r in _all_filings(cik)
            if r["form"] == source_form and r["filed"] in near]
    for r in cand:
        acc_nd = (r["accession"] or "").replace("-", "")
        idx = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nd}/{r['accession']}-index.html"
        html = fetch_index(idx)
        if not html:
            continue
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S | re.I)
        base = exhibit_label.split("(")[0]
        best = None
        for row in rows:
            cells = [re.sub(r'<[^>]+>', '', c).strip()
                     for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S | re.I)]
            if not cells:
                continue
            typ = " ".join(cells).upper()
            doc = next((c for c in cells if re.search(r'\.htm', c, re.I)), None)
            if not doc:
                continue
            if f"EX-{base}" in typ or f"EX-{exhibit_label}".upper() in typ:
                best = doc
                if f"EX-{exhibit_label}".upper() in typ:
                    break
            elif best is None and "EX-4" in typ:
                best = doc
        if best:
            return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{acc_nd}/{best.split('/')[-1]}")
    return None


def _locate_coc_clause(indenture_text):
    """The change-of-control section only. Prefers a real 'Section N.N Change of
    Control .' heading over the definitions and the table of contents."""
    if not indenture_text:
        return None
    hits = list(_COC_CLAUSE_HEAD.finditer(indenture_text))
    if not hits:
        return None
    # score each: a heading followed by obligation language ("shall offer to
    # purchase", "101%") is the operative clause, not the ToC line or a
    # cross-reference.
    best, best_sc = None, -1
    for h in hits:
        w = indenture_text[h.start():h.start() + 7000]
        sc = 0
        if re.search(r'shall\s+(?:be\s+required\s+to\s+)?(?:offer\s+to\s+)?'
                     r'(?:purchase|repurchase)', w, re.I):
            sc += 3
        if re.search(r'\b101\s*%|\b100\s*%', w):
            sc += 2
        if re.search(r'Holders?\b', w):
            sc += 1
        if len(w) < 800:
            sc -= 3
        if sc > best_sc:
            best, best_sc = h, sc
    if best_sc < 2:
        return None
    return indenture_text[max(0, best.start() - 200):best.start() + 8000]


def indenture_coc_for_notes(cik, exhibit_index_text, tranches, llm_fn, fetch=None):
    """
    Fill the change-of-control field for public-note tranches from their
    indentures. Mutates the tranche dicts in place; returns a per-tranche log.

    A tranche is only touched when its footnote change_of_control is null AND it
    is a note (senior_notes / senior_secured_notes / convertible).
    """
    fetch = fetch or _fetch
    refs = _parse_indenture_refs(exhibit_index_text)
    log = []
    if not refs:
        return [{"note": "no indenture references found in the 10-K exhibit index"}]

    for tr in tranches:
        if tr.get("instrument_type") not in (
                "senior_notes", "senior_secured_notes", "convertible"):
            continue
        if tr.get("change_of_control"):
            continue
        entry = {"tranche": tr.get("name")}
        ref = _match_ref(tr, refs)
        if not ref:
            entry["result"] = "no matching indenture reference"
            log.append(entry)
            continue
        entry["indenture_ref"] = (f"EX-{ref['exhibit']} via {ref['source_form']} "
                                  f"{ref['source_date']}")
        url = _resolve_exhibit_url(cik, ref["source_form"], ref["source_date"],
                                   ref["exhibit"])
        if not url:
            entry["result"] = "indenture document could not be located on EDGAR"
            log.append(entry)
            continue
        entry["indenture_url"] = url
        clause = _locate_coc_clause(fetch(url))
        if not clause:
            entry["result"] = "no change-of-control clause found in the indenture"
            log.append(entry)
            continue
        try:
            parsed = _parse_model_json(llm_fn(_COC_PROMPT.format(clause=clause)))
        except Exception as e:
            entry["result"] = f"model call failed: {e}"
            log.append(entry)
            continue
        if not parsed or not parsed.get("has_change_of_control_put"):
            entry["result"] = "no holder put in the change-of-control clause"
            log.append(entry)
            continue
        price = parsed.get("repurchase_price") or "the change-of-control price"
        survives = parsed.get("note_survives", True)
        tr["change_of_control"] = (
            f"Change-of-control put: holders may require repurchase at {price}"
            + ("; the note otherwise survives the merger (the put is the "
               "holder's option) — tradeable, the credit opportunity"
               if survives else "; the indenture provides for redemption on a "
               "change of control"))
        tr["change_of_control_quote"] = parsed.get("quote")
        tr["change_of_control_source"] = entry["indenture_ref"]
        entry["result"] = f"put at {price}; survives={survives}"
        log.append(entry)
    return log


# ════════════════════════════════════════════════════════════════════════════
# 4. RECONCILE
# ════════════════════════════════════════════════════════════════════════════

def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _unit_tolerance(unit, total):
    """
    The pieces are the filing's own numbers, so the bridge should close to the
    dollar. The band only absorbs rounding when a tranche's face is given in
    prose to one decimal ("$100.8 million") against a table stated to the
    thousand.
    """
    base = abs(total) * 0.004
    if (unit or "").startswith("million"):
        return max(base, 0.2)
    if (unit or "").startswith("thousand"):
        return max(base, 30.0)
    return max(base, 30000.0)


def _tranche_debt_amount(tr):
    """Principal that counts as this tranche's debt: drawn for a revolver, else
    face (falls back to net only when face is absent)."""
    if tr.get("instrument_type") == "revolver":
        return _num(tr.get("drawn"))
    face = _num(tr.get("face_amount"))
    return face if face is not None else _num(tr.get("net_amount"))


def reconcile(parsed):
    """
    Does the filing's own bridge close?

        sum(tranche principal) + sum(adjustments) == stated net total

    A gap means a tranche (or an adjustment line) was missed, and the caller
    must show "capital structure incomplete" rather than a partial table.

    Returns {ok, net_total, computed, delta, tolerance, face_check, method,
             missing_amounts}.
    """
    unit = (parsed or {}).get("currency_unit")
    net = (parsed or {}).get("stated_net_total") or {}
    net_total = _num(net.get("amount"))

    tranches = (parsed or {}).get("tranches") or []
    adj = (parsed or {}).get("adjustments") or []

    tvals, missing = [], []
    for t in tranches:
        v = _tranche_debt_amount(t)
        if v is None:
            missing.append(t.get("name"))
        else:
            tvals.append(v)
    avals = [_num(a.get("amount")) for a in adj]
    avals = [a for a in avals if a is not None]

    if net_total is None:
        return {"ok": False, "net_total": None, "computed": None, "delta": None,
                "tolerance": None, "face_check": None, "missing_amounts": missing,
                "method": "the filing's net total-debt figure could not be read"}
    if missing:
        return {"ok": False, "net_total": net_total, "computed": None,
                "delta": None, "tolerance": None, "face_check": None,
                "missing_amounts": missing,
                "method": f"{len(missing)} tranche(s) carry no amount — cannot bridge"}

    computed = round(sum(tvals) + sum(avals), 4)
    tol = _unit_tolerance(unit, net_total)
    delta = round(computed - net_total, 4)

    face_check = None
    face = (parsed or {}).get("stated_face_total") or {}
    face_total = _num(face.get("amount"))
    if face_total is not None:
        face_sum = round(sum(tvals), 4)
        face_check = {
            "stated": face_total, "sum_of_tranche_face": face_sum,
            "delta": round(face_sum - face_total, 4),
            "ok": abs(face_sum - face_total) <= tol,
        }

    return {
        "ok": abs(delta) <= tol,
        "net_total": net_total,
        "computed": computed,
        "delta": delta,
        "tolerance": tol,
        "face_check": face_check,
        "missing_amounts": [],
        "method": (f"sum of {len(tvals)} tranche principal + {len(avals)} "
                   f"adjustment line(s) vs '{net.get('label')}'"),
    }


# ════════════════════════════════════════════════════════════════════════════
# 5. ORCHESTRATE
# ════════════════════════════════════════════════════════════════════════════

def assess_capital_structure(ticker, company=None, cik=None,
                             llm_fn=None, fetch=None, filing=None):
    """
    Top-level. Returns a dict the caller can render or store.

    { status, ticker, as_of, source: {accession, form, filed, url, heading},
      currency_unit, stated_net_total, stated_face_total, tranches: [...],
      reconciliation: {...}, change_of_control: [...], model_notes, reason }

    status:
      ok            tranches found and they reconcile
      incomplete    tranches found, they do NOT reconcile — show the caveat, not the table
      not_disclosed no readable 10-K debt footnote (the refuse case)
      unavailable   no model layer wired in
    """
    if llm_fn is None:
        return {"status": UNAVAILABLE, "ticker": ticker,
                "reason": "capital-structure extraction requires the model layer; "
                          "no llm_fn was provided"}

    filing = filing or find_target_10k(ticker, cik=cik, fetch=fetch)
    if not filing:
        return {"status": NOT_DISCLOSED, "ticker": ticker,
                "reason": "no 10-K with financial statements found for this target "
                          "(foreign filer, recent IPO, or PE-owned)"}

    section, heading = locate_debt_footnote(filing["text"])
    if not section:
        return {"status": NOT_DISCLOSED, "ticker": ticker,
                "source": {"accession": filing["accession"], "form": filing["form"],
                           "filed": filing["filed"], "url": filing["doc_url"]},
                "reason": "10-K found but its debt footnote could not be located"}

    try:
        raw = llm_fn(build_prompt(ticker, company, section))
    except Exception as e:
        return {"status": NOT_DISCLOSED, "ticker": ticker,
                "source": {"accession": filing["accession"], "form": filing["form"],
                           "filed": filing["filed"], "url": filing["doc_url"],
                           "heading": heading},
                "reason": f"model call failed: {e}"}

    parsed = _parse_model_json(raw)
    if not parsed or not parsed.get("disclosure_found") or not parsed.get("tranches"):
        return {"status": NOT_DISCLOSED, "ticker": ticker,
                "source": {"accession": filing["accession"], "form": filing["form"],
                           "filed": filing["filed"], "url": filing["doc_url"],
                           "heading": heading},
                "reason": "debt footnote located but no tranche-level disclosure could be read"}

    all_tranches = parsed.get("tranches") or []

    # ── change of control for public notes, from the EX-4 indenture ──────────
    # The footnote is silent on it for almost every note; the clause is in the
    # indenture. Only runs for notes still carrying a null reading.
    indenture_log = []
    if any(t.get("instrument_type") in ("senior_notes", "senior_secured_notes",
                                        "convertible") and not t.get("change_of_control")
           for t in all_tranches):
        try:
            indenture_log = indenture_coc_for_notes(
                filing["cik"], filing["text"], all_tranches, llm_fn, fetch=fetch)
        except Exception as e:
            indenture_log = [{"note": f"indenture pass failed: {e}"}]

    # ── separate real debt from undrawn capacity ────────────────────────────
    # A $0-drawn facility stays in the output — undrawn capacity is information a
    # credit analyst wants — but it is not a debt tranche and must not sit with
    # the weight of one. It carries no principal, so moving it out does not
    # touch the reconciliation.
    debt_tranches, undrawn = [], []
    for t in all_tranches:
        amt = _tranche_debt_amount(t)
        if t.get("instrument_type") == "revolver" and (amt in (0, 0.0, None)):
            undrawn.append({
                "name": t.get("name"),
                "capacity": t.get("capacity"),
                "rate": t.get("rate"),
                "maturity": t.get("maturity"),
                "seniority": t.get("seniority"),
                "status": "undrawn — $0 borrowed; capacity context, not debt",
            })
        else:
            debt_tranches.append(t)

    rec = reconcile({**parsed, "tranches": debt_tranches})
    status = OK if rec["ok"] else INCOMPLETE
    coc = [{"name": t.get("name"),
            "treatment": t.get("change_of_control"),
            "quote": t.get("change_of_control_quote"),
            "source": t.get("change_of_control_source", "10-K debt footnote")}
           for t in debt_tranches]

    return {
        "status": status,
        "ticker": ticker,
        "as_of": parsed.get("as_of"),
        "currency_unit": parsed.get("currency_unit"),
        "source": {
            "accession": filing["accession"], "form": filing["form"],
            "filed": filing["filed"], "url": filing["doc_url"], "heading": heading,
        },
        "stated_net_total": parsed.get("stated_net_total"),
        "stated_face_total": parsed.get("stated_face_total"),
        "tranches": debt_tranches,
        "undrawn_facilities": undrawn,
        "reconciliation": rec,
        "change_of_control": coc,
        "indenture_log": indenture_log,
        "model_notes": parsed.get("notes"),
        "reason": (None if status == OK else
                   "the extracted tranches do not bridge to the filing's stated "
                   "total — a tranche or an adjustment line was probably missed; "
                   "show 'capital structure incomplete', not the partial table"),
    }


# ── the model layer, wired the same way as the rest of the pipeline ──────────
def anthropic_llm_fn(api_key, model="claude-sonnet-5", max_tokens=16000):
    """Returns an llm_fn(prompt)->str backed by the Anthropic messages API."""
    def _fn(prompt):
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  "system": "You extract structured debt data from SEC filings. "
                            "Return only valid JSON.",
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        # Join every text block; a max_tokens stop still yields partial text that
        # _parse_model_json can often salvage. Anything else is a real failure
        # and the raw body is the only useful thing to see.
        parts = [b.get("text", "") for b in body.get("content", [])
                 if b.get("type") == "text"]
        text = "".join(parts).strip()
        if not text:
            raise RuntimeError(f"no text in response (stop_reason="
                               f"{body.get('stop_reason')}): {str(body)[:300]}")
        return text
    return _fn
