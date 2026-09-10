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
# "(7) Borrowings" (BZH), "NOTE J – LONG-TERM DEBT" (NATH), "Note 8—Credit
# Agreement and Debt Facilities" (ALOT), "12. OBLIGATIONS" (AES's consolidated
# debt note). _score_heading validates that the block after is really a debt
# table, so the looser keywords here (OBLIGATIONS, CREDIT AGREEMENT) can't drag
# in a lease or pension note.
_HEAD_KW = (r'LONG[\-\s]?TERM\s+DEBT|DEBT(?:\s+AND\s+FINANCING(?:\s+ARRANGEMENTS)?)?|'
            r'BORROWINGS|NOTES?\s+PAYABLE|INDEBTEDNESS|'
            r'CREDIT\s+(?:AGREEMENTS?|FACILIT(?:Y|IES))(?:\s+AND\s+DEBT(?:\s+FACILIT(?:Y|IES))?)?|'
            r'DEBT\s+FACILIT(?:Y|IES)|FINANCING\s+ARRANGEMENTS?|'
            r'LONG[\-\s]?TERM\s+OBLIGATIONS|DEBT\s+OBLIGATIONS|OBLIGATIONS')
_HEAD_PAT = re.compile(
    r'(?:'
    r'NOTE\s+[A-Z0-9]{1,3}\s*[–—:.\-]\s*(?:' + _HEAD_KW + r')'
    r'|'
    r'\(\d{1,2}\)\s*(?:' + _HEAD_KW + r')'
    r'|'
    r'\b\d{1,2}\.\s+(?:' + _HEAD_KW + r')\b'
    r')', re.I)

# Contexts where a "Debt" heading is the WRONG note: a Schedule I / parent-only
# condensed schedule (AES — reconciles cleanly to ~$6B parent recourse debt
# while consolidated debt is ~$29B), or an MD&A contractual-obligations table.
_SCHEDULE_I = re.compile(
    r'SCHEDULE\s+I\b|CONDENSED\s+FINANCIAL\s+INFORMATION\s+OF\s+(?:THE\s+)?REGISTRANT'
    r'|PARENT\s+COMPANY\s+(?:ONLY|INFORMATION|FINANCIAL)|PARENT[\-\s]?ONLY'
    r'|\(PARENT\s+COMPANY\s+ONLY\)', re.I)
_MDNA_OBLIG = re.compile(
    r'Footnote\s+Reference|Payments?\s+Due\s+by\s+Period|Contractual\s+Obligations'
    r'|Less\s+than\s+1\s+year', re.I)
_FS_MARKER = re.compile(
    r'NOTES\s+TO\s+(?:THE\s+)?(?:CONSOLIDATED\s+)?FINANCIAL\s+STATEMENTS', re.I)

# Where the NEXT note begins — used to cut the tail of the captured block. The
# capture group holds the heading text so a running page header that repeats the
# current heading ("NOTE J – LONG-TERM DEBT (continued)") can be told apart from
# a genuine new note and skipped.
# A footnote marker inside a table — "(1) These amounts…", "(2) Excludes…" — is
# not the next note. Exclude the words such markers lead with.
_FN_LEADIN = (r'These|Exclud\w+|Includ\w+|Represent\w+|Reflect\w+|Consist\w+|'
              r'Amounts?|Primarily|Net\b|Other\b|As\s+of|For\s+the|In\s+\w|The\s+\w')
_NEXT_NOTE_PAT = re.compile(
    r'(NOTE\s+[A-Z0-9]{1,3}\s*[–—:.\-]\s*[A-Z][A-Za-z ,\-]{2,40}'
    r'|\(\d{1,2}\)\s+(?!(?:' + _FN_LEADIN + r'))[A-Z][a-z][A-Za-z ,\-]{2,40}'
    r'|\b\d{1,2}\.\s+(?!(?:' + _FN_LEADIN + r'))[A-Z][a-z]+(?:\s+[A-Za-z]+){0,3})')

_SECTION_MAX = 24000


def _score_heading(text, start):
    """
    How much the block after a heading looks like the CONSOLIDATED debt NOTE
    (a dense dollar table with a stated total) rather than an MD&A mention, an
    MD&A contractual-obligations row, or a Schedule I / parent-only schedule.
    """
    w = text[max(0, start - 500):start + _SECTION_MAX]
    lookahead = text[start:start + 400]
    before = text[max(0, start - 7000):start]
    sc = 0
    if re.search(r'total\s+(?:long[\-\s]?term\s+)?(?:debt|borrowings|senior\s+notes)'
                 r'[,]?\s*(?:net)?', w, re.I):
        sc += 3
    if len(re.findall(r'\$\s*[\d,]{3,}', w)) >= 4:
        sc += 2
    if re.search(r'matur', w, re.I):
        sc += 2
    sc += min(3, len(re.findall(
        r'senior\s+notes|term\s+loan|revolv|subordinated|non[\-\s]?recourse\s+debt|'
        r'recourse\s+debt', w, re.I)))
    if re.search(r'risk\s+factors|forward[\-\s]looking\s+statements|item\s+1a', w, re.I):
        sc -= 3
    if re.search(r'consist(?:s|ed)?\s+of\s+the\s+following|was\s+as\s+follows|'
                 r'following\s+table', lookahead, re.I):
        sc += 2

    # ── the "wrong note" penalties ──────────────────────────────────────────
    # Schedule I / parent-company-only condensed schedule. AES's is titled
    # "2. Debt" and reconciles perfectly — to a total that excludes $23bn of
    # non-recourse debt.
    if _SCHEDULE_I.search(before):
        sc -= 12
    # An MD&A contractual-obligations table ("Payments Due by Period",
    # "Footnote Reference") is not the debt note.
    if _MDNA_OBLIG.search(text[start:start + 700]):
        sc -= 6
    # A cross-reference — "see note 13 – Long-term Debt", "(refer to Note 8)" —
    # is a pointer, not the note. GBTG lost its real note to one of these.
    if re.search(r'(?:see|refer\s+to|\(\s*see)\s*$', text[max(0, start - 30):start], re.I):
        sc -= 8
    if re.search(r'to\s+(?:our|the)\s+(?:accompanying\s+)?consolidated\s+financial\s+'
                 r'statements\s+included\s+elsewhere', lookahead, re.I):
        sc -= 8
    # In the financial-statement notes region (real note) vs anywhere else.
    if _FS_MARKER.search(text[max(0, start - 9000):start]):
        sc += 3
    # A bare "OBLIGATIONS" heading needs debt words right after it, or it is a
    # lease / pension / asset-retirement note.
    if re.search(r'\bOBLIGATIONS\b\s*$', text[max(0, start - 14):start + 12], re.I) \
       and not re.search(r'non[\-\s]?recourse|recourse\s+debt|senior\s+notes|'
                         r'term\s+loan|credit\s+facilit|bonds?\b|indebtedness',
                         lookahead + text[start + 400:start + 1200], re.I):
        sc -= 10
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
    return section[:30000], heading


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
    """
    [{desc, exhibit, source_form, source_date, coupon, note_year, supplemental}]
    from the 10-K exhibit index. Two reference shapes:

      A. "Indenture ... (incorporated by reference to Exhibit X of the Company's
         Form Y filed on <date>)"                    — OGN, BZH; exhibit known
      B. "Indenture (4.625% Senior Notes due 2029), dated ..., ... Previously
         filed on Form 8-K filed on <date>."         — CZR; NO exhibit number

    The window is wide (1300 chars) so a long reference line — extra trustees,
    paying agents, a UK branch — can't push the exhibit token past the end (the
    bug that put OGN's euro notes on an 8 KB supplemental instead of the 584 KB
    base indenture).
    """
    t = exhibit_index_text or ""
    refs, seen = [], set()
    for m in re.finditer(r'\bIndenture\b', t):
        win = t[m.start():m.start() + 1300]
        pre = t[max(0, m.start() - 60):m.start()]
        exhibit = form = date_txt = None
        desc_end = len(win)

        paren = re.search(
            r'\(([^)]{0,950}?(?:incorporated|previously\s+filed|filed\s+here)[^)]{0,700})\)',
            win, re.I)
        if paren:
            p = paren.group(1)
            _e = re.search(r'Exhibit\s+(\d+\.\d+(?:\([a-z0-9]+\))?)', p, re.I)
            _f = re.search(r'\bForm\s+([A-Z0-9][A-Z0-9/\-]{0,9})', p)
            _d = _DATE_RE.search(p)
            if _f and _d:
                exhibit = _e.group(1) if _e else None
                form, date_txt, desc_end = _f.group(1), _d.group(0), paren.start()

        if not form:  # shape B — no parenthetical, no exhibit number
            pv = re.search(
                r'Previously\s+filed(?:\s+with\s+the\s+SEC)?\s+on\s+Form\s+'
                r'([A-Z0-9][A-Z0-9/\-]{0,9})[^.]{0,40}?((?:' + _MONTHS_RE
                + r')\s+\d{1,2},\s+\d{4})', win, re.I)
            if pv:
                form, date_txt = pv.group(1), pv.group(2)
                desc_end = min(desc_end, pv.start())

        if not (form and date_txt):
            continue

        desc = re.sub(r'\s+', ' ', win[:desc_end]).strip(" ,.–—-")
        _d = _DATE_RE.search(date_txt)
        source_date = _iso(f"{_d.group(1)} {_d.group(2)}, {_d.group(3)}")
        coupon = re.search(r'(\d+\.\d+)\s*%', desc)
        yr = re.search(r'due\s+(\d{4})|Notes?\s+(?:due\s+)?(\d{4})', desc, re.I)
        supplemental = bool(re.search(r'supplement', pre + " " + desc, re.I))

        key = (exhibit or "?", source_date,
               coupon.group(1) if coupon else desc[:36], supplemental)
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "desc": desc,
            "exhibit": (exhibit.split("(")[0] if exhibit else None),
            "source_form": form.upper(),
            "source_date": source_date,
            "coupon": coupon.group(1) if coupon else None,
            "note_year": (yr.group(1) or yr.group(2)) if yr else None,
            "supplemental": supplemental,
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
    # CZR names its notes "CEI Senior Secured Notes due 2032" with the coupon
    # only in the Rates column — and it has both a 6.50% and a 6.00% 2032 note,
    # so year alone would put them on the same indenture. Take the coupon from
    # the rate text when the name doesn't carry one.
    c = re.search(r'(\d+\.\d+)\s*%', name)
    if not c:
        rate_txt = ((tranche.get("rate") or {}).get("text") or "")
        c = re.match(r'\s*(\d+\.\d+)\s*%', rate_txt) or re.search(r'(\d+\.\d+)\s*%\s*(?:fixed|coupon|senior|notes)', rate_txt, re.I)
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
        # A note has one base indenture and any number of supplementals (adding a
        # guarantor, releasing escrow). The change-of-control covenant is in the
        # base. Prefer base > supplemental > form-of, then exact coupon.
        for pref in (lambda r: specific(r) and not r.get("supplemental"),
                     lambda r: specific(r),
                     lambda r: True):
            for r in refs:
                if not pref(r):
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


def _indenture_doc_urls(cik, source_form, source_date, exhibit_label=None,
                        fetch_index=None):
    """
    Ordered candidate document URLs for an indenture cited in the exhibit index.

    When the exhibit number is known, that doc leads. When it is not (CZR cites
    its indentures only as "Previously filed on Form 8-K filed on <date>"), every
    EX-4.x / EX-10.x document from the cited filing is returned, largest first —
    a base indenture runs 200 KB-1 MB, a supplemental or a form-of-note a few KB.
    The caller reads down the list and takes the first with a real
    change-of-control clause.
    """
    fetch_index = fetch_index or _fetch_raw
    if not source_date:
        return []
    y, mo, d = (int(x) for x in source_date.split("-"))
    near = {source_date}
    for off in (-3, -2, -1, 1, 2, 3, 4):
        try:
            from datetime import date, timedelta
            near.add((date(y, mo, d) + timedelta(days=off)).isoformat())
        except Exception:
            pass
    base = exhibit_label.split("(")[0] if exhibit_label else None
    out = []
    for r in [f for f in _all_filings(cik)
              if f["form"] == source_form and f["filed"] in near]:
        acc_nd = (r["accession"] or "").replace("-", "")
        html = fetch_index(f"https://www.sec.gov/Archives/edgar/data/"
                           f"{int(cik)}/{acc_nd}/{r['accession']}-index.html")
        if not html:
            continue
        exact, ex4x, ex10x = [], [], []
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S | re.I):
            cells = [re.sub(r'<[^>]+>', '', c).strip()
                     for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S | re.I)]
            if not cells:
                continue
            typ = " ".join(cells).upper()
            doc = next((c for c in cells if re.search(r'\.htm', c, re.I)), None)
            if not doc:
                continue
            doc = doc.split("/")[-1]
            size = 0
            for c in cells:
                if re.fullmatch(r'[\d,]{4,}', c.strip()):
                    size = int(c.replace(",", ""))
            url = (f"https://www.sec.gov/Archives/edgar/data/"
                   f"{int(cik)}/{acc_nd}/{doc}")
            if base and (f"EX-{base}" in typ or f"EX-{exhibit_label}".upper() in typ):
                exact.append((size, url))
            elif re.search(r'EX-4\b|EX-4\.', typ):
                ex4x.append((size, url))
            elif re.search(r'EX-10\b|EX-10\.', typ):
                ex10x.append((size, url))
        ordered = ([u for _, u in exact]
                   + [u for _, u in sorted(ex4x, reverse=True)]
                   + [u for _, u in sorted(ex10x, reverse=True)])
        out.extend(ordered)
    # dedupe, keep order
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _locate_coc_clause(indenture_text):
    """
    The operative change-of-control section only.

    An indenture says "Change of Control" 30+ times — in the table of contents,
    the definitions ("... the meaning assigned in the definition of 'Change of
    Control'"), covenant-suspension clauses. The one that matters grants holders
    the right to require repurchase. CZR's 4.625%/2029 indenture put the parser
    on a definitions cross-reference (no price, no put) and the model — correctly
    for what it was handed — said "no put".
    """
    if not indenture_text:
        return None
    hits = list(_COC_CLAUSE_HEAD.finditer(indenture_text))
    if not hits:
        return None
    best, best_sc = None, -1
    for h in hits:
        w = indenture_text[h.start():h.start() + 7000]
        pre = indenture_text[max(0, h.start() - 40):h.start()]
        sc = 0
        # the operative grant
        if re.search(r'right\s+to\s+require\s+the\s+(?:Issuers?|Company|Parent)\s+'
                     r'to\s+(?:re)?purchase', w, re.I):
            sc += 6
        if re.search(r'(?:Issuers?|Company)\s+shall\s+(?:be\s+required\s+to\s+)?'
                     r'(?:make\s+an\s+offer\s+to\s+(?:purchase|repurchase)|'
                     r'(?:offer\s+to\s+)?(?:purchase|repurchase))', w, re.I):
            sc += 4
        if re.search(r'shall\s+(?:be\s+required\s+to\s+)?(?:offer\s+to\s+)?'
                     r'(?:purchase|repurchase)', w, re.I):
            sc += 2
        if re.search(r'\b10[01]\s*%\s*of\s+(?:the\s+)?(?:aggregate\s+)?principal',
                     w, re.I):
            sc += 3
        elif re.search(r'\b10[01]\s*%', w):
            sc += 1
        if re.search(r'Change\s+of\s+Control\s+(?:Offer|Payment|Price)', w, re.I):
            sc += 2
        # a numbered section heading is the real clause; a bare mention is prose
        if re.match(r'Section\s+\d', h.group(0), re.I):
            sc += 2
        # ── not the operative clause ───────────────────────────────────────
        if re.search(r'(?:definition|meaning)\s+of\s*$', pre, re.I):
            sc -= 8
        if re.search(r'shall\s+have\s+the\s+meaning|has\s+the\s+meaning\s+'
                     r'(?:assigned|set\s+forth)', w[:400], re.I):
            sc -= 6
        if len(w) < 800 or re.search(r'^\s*\d{1,3}\s+Section\s+\d', w):  # ToC row
            sc -= 4
        # tie → the later hit (definitions precede the operative articles)
        if sc >= best_sc:
            best, best_sc = h, sc
    if best_sc < 3:
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
        entry["indenture_ref"] = (
            (f"EX-{ref['exhibit']}" if ref["exhibit"] else "indenture")
            + f" via {ref['source_form']} {ref['source_date']}")
        urls = _indenture_doc_urls(cik, ref["source_form"], ref["source_date"],
                                   ref["exhibit"])
        if not urls:
            entry["result"] = "indenture document could not be located on EDGAR"
            log.append(entry)
            continue
        # Read down the candidates; take the first that is an indenture with a
        # real change-of-control clause. A tiny supplemental has no clause and
        # is skipped automatically.
        cpn = ref["coupon"]
        clause, chosen = None, None
        for u in urls[:6]:
            txt = fetch(u)
            if not txt:
                continue
            head = txt[:3000].upper()
            if "INDENTURE" not in head:
                continue
            if cpn and cpn not in txt[:40000] and cpn not in txt[-40000:]:
                continue
            c = _locate_coc_clause(txt)
            if c:
                clause, chosen = c, u
                break
        if not clause:
            entry["indenture_url"] = urls[0]
            entry["result"] = "no change-of-control clause found in the indenture"
            log.append(entry)
            continue
        entry["indenture_url"] = chosen
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


def _to_millions(amount, unit):
    """A figure + its currency unit -> $ millions."""
    a = _num(amount)
    if a is None:
        return None
    u = (unit or "").lower()
    if u.startswith("thousand"):
        return a / 1000.0
    if u.startswith("billion"):
        return a * 1000.0
    if u.startswith("dollar") or u.startswith("unit"):
        return a / 1e6
    return a  # already millions


def consolidated_total_guard(full_text, parsed, debt_tranches):
    """
    Reconciling to A total is not enough — it must be the CONSOLIDATED total.

    AES read Schedule I (parent-only, ~$6.0B) and bridged to it perfectly while
    consolidated debt is ~$29B — $23.2B of it non-recourse subsidiary debt that
    the located note never mentions. Returns a reason string when the extracted
    total is materially short of a non-recourse / subsidiary debt figure the
    10-K discloses elsewhere, and no extracted tranche accounts for it.
    """
    net = (parsed or {}).get("stated_net_total") or {}
    net_m = _to_millions(net.get("amount"), (parsed or {}).get("currency_unit"))
    if net_m is None or net_m <= 0:
        return None

    names = " ".join((t.get("name") or "") for t in debt_tranches).lower()
    if re.search(r'non[\-\s]?recourse|subsidiary\s+debt|project\s+debt', names):
        return None  # the extraction already covers non-recourse debt

    disc = None
    for m in re.finditer(
            r'(?:approximately\s+)?\$\s*([\d.,]+)\s*(billion|million)\s+'
            r'(?:was|of|in|is|represented|represents)?\s*non[\-\s]?recourse',
            full_text, re.I):
        v = _to_millions(m.group(1).replace(",", ""),
                         "billion" if m.group(2).lower().startswith("b") else "million")
        disc = max(disc or 0, v or 0)
    for m in re.finditer(
            r'non[\-\s]?recourse\s+(?:long[\-\s]?term\s+)?debt[^.$]{0,60}?'
            r'\$\s*([\d.,]+)\s*(billion|million)', full_text, re.I):
        v = _to_millions(m.group(1).replace(",", ""),
                         "billion" if m.group(2).lower().startswith("b") else "million")
        disc = max(disc or 0, v or 0)

    if disc and disc > 500 and net_m < 0.6 * (net_m + disc):
        return ("the located note reconciles to ${:,.0f}M, but the 10-K discloses "
                "~${:,.0f}M of non-recourse / subsidiary debt it does not include "
                "— this is a parent-only or partial schedule, not the consolidated "
                "debt note".format(net_m, disc))
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

    # Reconciling is not enough — it must be the CONSOLIDATED total, not a
    # parent-only / Schedule I schedule.
    wrong_note = consolidated_total_guard(filing["text"], parsed, debt_tranches)
    if wrong_note:
        status = INCOMPLETE

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
        "reason": (None if status == OK else wrong_note if wrong_note else
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
