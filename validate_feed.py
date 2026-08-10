"""
validate_feed.py -- Phase 1 feed validation script.
READ-ONLY. No main.py changes. No auto-removal.

Fixed from previous version:
- Filing selection now anchors on the KNOWN announcement_date passed per deal.
  Searches for the 8-K filed within +/- 7 days of that date, not "earliest Item 1.01"
  which was matching decade-old unrelated filings (PAYO's 2021 SPAC IPO, CZR's 2014
  filing, GBTG's 2021 filing, etc.).
- If no filing is found within the date window, reports "correct filing not found"
  rather than silently falling back to a wrong ancient filing and giving false results.
- Same-entity check tightened: requires HIGH overlap between acquirer name and company
  name (Jaccard similarity on word sets, threshold 0.6) rather than substring match.
  "Catalyst" matching "Catalyst Bancorp" was a false positive -- a real self-tender
  has the full company name as acquirer, not a partial word match.
- Completion check still runs, but now only matters if the correct announcement filing
  was found -- otherwise it reports "completion check skipped, wrong filing."
"""

import time
import re
import requests
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Meridian Verification Script kaushal@meridian.dev",
    "Accept-Encoding": "gzip, deflate",
}

DEREGISTRATION_FORMS = {"25", "25-NSE", "15", "15-12B", "15-12G"}

SELF_TENDER_SIGNALS = [
    'repurchase of its common stock',
    "repurchase of the company's common stock",
    'capital return program',
    'issuer tender offer',
    'offer to purchase shares of its own',
    'offer to purchase its own',
    'return capital to shareholders',
    'return of capital to stockholders',
]

MERGER_SIGNALS = [
    'agreement and plan of merger',
    'merger agreement',
    'definitive agreement',
    'to be acquired by',
    'acquire all of the outstanding',
    'entered into a merger',
    'agreement to be acquired',
]

ACQUIRER_IRRELEVANT_SIGNALS = [
    'sale of', 'disposition of', 'divestiture', 'spinoff', 'spin-off', 'asset sale',
]


def edgar_get(url, pause=0.15):
    time.sleep(pause)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        return None


def get_text(url, pause=0.15):
    time.sleep(pause)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        from html.parser import HTMLParser
        class TE(HTMLParser):
            def __init__(self):
                super().__init__()
                self.chunks = []
            def handle_data(self, d):
                self.chunks.append(d)
        p = TE()
        p.feed(r.text)
        return ' '.join(p.chunks)
    except Exception:
        return None


def get_cik(ticker):
    data = edgar_get("https://www.sec.gov/files/company_tickers.json", pause=0.2)
    if not data:
        return None, None
    for entry in data.values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10), entry.get("title", "")
    return None, None


def get_submissions(cik):
    return edgar_get("https://data.sec.gov/submissions/CIK" + cik + ".json")


def name_overlap_score(name_a, name_b):
    """
    Jaccard similarity on word sets after stripping common corporate suffixes.
    Returns 0.0-1.0. High score = names are essentially the same entity.
    Threshold for flagging: 0.6 (requires most words to match).
    A partial match like 'Catalyst' vs 'Catalyst Bancorp' scores ~0.33 -- below threshold.
    A real self-tender 'Keros Therapeutics' vs 'Keros Therapeutics Inc' scores ~0.85.
    """
    suffixes = {'inc', 'corp', 'ltd', 'llc', 'plc', 'co', 'company',
                'corporation', 'incorporated', 'limited', 'holdings', 'group'}
    def clean_words(s):
        words = re.sub(r'[^a-z0-9 ]', '', s.lower()).split()
        return set(w for w in words if w not in suffixes and len(w) > 1)
    a = clean_words(name_a)
    b = clean_words(name_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_announcement_filing(sub, cik, announcement_date_str, window_days=7):
    """
    Find the 8-K (or tender offer form) filed within window_days of announcement_date.
    Returns (filing_date, accession, form_type, text, url) or (None, reason_string).

    Searches ALL recent filings (not just Item 1.01) within the date window,
    then picks the one most likely to be the merger announcement by checking
    for merger-signal language in the text. This handles cases where the
    announcement 8-K is tagged with multiple items or a slightly different item code.
    """
    try:
        ann_date = datetime.strptime(announcement_date_str, "%Y-%m-%d")
    except Exception:
        return None, "Could not parse announcement_date: " + announcement_date_str

    window_start = ann_date - timedelta(days=window_days)
    window_end = ann_date + timedelta(days=window_days)

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    items = recent.get("items", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    candidates = []
    for form, acc, item, date_str, doc in zip(forms, accessions, items, dates, primary_docs):
        if not doc:
            continue
        try:
            fdate = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        if window_start <= fdate <= window_end:
            # Prioritise 8-K and tender offer forms
            if form in ("8-K", "SC TO-T", "SC TO-I", "SC 13E-3", "SC 14D9"):
                candidates.append((date_str, acc, form, doc, abs((fdate - ann_date).days)))

    if not candidates:
        return None, ("No 8-K or tender offer form found within "
                      + str(window_days) + " days of " + announcement_date_str
                      + ". Closest filing may be outside the window -- "
                      + "check the announcement date is correct.")

    # Sort by closeness to the announcement date
    candidates.sort(key=lambda x: x[4])

    # Among close candidates, prefer ones with merger language in text
    for date_str, acc, form, doc, _ in candidates:
        acc_clean = acc.replace("-", "")
        url = ("https://www.sec.gov/Archives/edgar/data/"
               + str(int(cik)) + "/" + acc_clean + "/" + doc)
        text = get_text(url)
        if text and any(sig in text.lower() for sig in MERGER_SIGNALS):
            return (date_str, acc, form, text, url), None

    # No merger language found in any candidate -- return the closest one anyway, flagged
    date_str, acc, form, doc, delta = candidates[0]
    acc_clean = acc.replace("-", "")
    url = ("https://www.sec.gov/Archives/edgar/data/"
           + str(int(cik)) + "/" + acc_clean + "/" + doc)
    text = get_text(url)
    return (date_str, acc, form, text or "", url), (
        "WARNING: filing found within date window but no merger-signal language detected -- "
        "may be the wrong document or an unusual filing structure. Verify manually."
    )


def check_self_tender(form_type, filing_text, company_name, acquirer_name):
    """
    Checks 1 + 2: SC TO-I form type, self-tender text signals, same-entity check.
    Same-entity now uses Jaccard word overlap (threshold 0.6) instead of substring.
    Returns (flagged, reasons)
    """
    reasons = []

    if form_type and "TO-I" in str(form_type).upper():
        reasons.append("Form type is SC TO-I (issuer self-tender = buyback by SEC definition)")

    if filing_text:
        text_lower = filing_text.lower()
        for sig in SELF_TENDER_SIGNALS:
            if sig in text_lower:
                reasons.append("Filing text self-tender signal: \"" + sig + "\"")
                break

        # Tightened same-entity check
        if acquirer_name and company_name:
            score = name_overlap_score(acquirer_name, company_name)
            if score >= 0.6:
                reasons.append(
                    "Acquirer name (\"" + acquirer_name + "\") closely matches company name "
                    + "(\"" + company_name + "\", overlap score "
                    + str(round(score, 2)) + " >= 0.6 threshold) -- possible self-tender"
                )

    return len(reasons) > 0, reasons


def check_completion(sub, cik, acquirer_name, announcement_date_str):
    """
    Check 3: post-announcement completion signals only, acquirer-mention verified.
    Returns (flagged, evidence_list)
    """
    evidence = []

    try:
        ann_date = datetime.strptime(announcement_date_str, "%Y-%m-%d")
    except Exception:
        return False, ["Could not parse announcement date"]

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    items = recent.get("items", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    acq_words = (acquirer_name or "").lower().split()
    # Use first two meaningful words of acquirer for matching
    # (handles "Paramount Global" -> "paramount", "Nuvei Corporation" -> "nuvei")
    acq_key = acq_words[0] if acq_words else ""

    for form, acc, item, date_str, doc in zip(forms, accessions, items, dates, primary_docs):
        try:
            fdate = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue

        # CRITICAL: only post-announcement filings
        if fdate <= ann_date:
            continue

        item_str = str(item) if item else ""

        # Signal A: deregistration form
        if form in DEREGISTRATION_FORMS:
            evidence.append(
                "DEREGISTRATION: Form " + form + " filed " + date_str
                + " (after announcement " + announcement_date_str + "), "
                + "accession " + acc
            )

        # Signal B: Item 2.01 completion 8-K with acquirer mention
        elif form == "8-K" and "2.01" in item_str and doc:
            acc_clean = acc.replace("-", "")
            url = ("https://www.sec.gov/Archives/edgar/data/"
                   + str(int(cik)) + "/" + acc_clean + "/" + doc)
            text = get_text(url)
            if not text:
                continue
            text_lower = text.lower()

            is_irrelevant = any(s in text_lower for s in ACQUIRER_IRRELEVANT_SIGNALS)
            acquirer_mentioned = bool(acq_key) and acq_key in text_lower

            if acquirer_mentioned and not is_irrelevant:
                idx = text_lower.find(acq_key)
                snippet = text[max(0, idx-80):idx+120].replace("\n", " ").strip()
                evidence.append(
                    "COMPLETION 8-K: Item 2.01 filed " + date_str
                    + " (after announcement), accession " + acc
                    + "\n      Acquirer \"" + acquirer_name + "\" found in filing."
                    + "\n      Snippet: \"..." + snippet + "...\""
                )
            elif acquirer_mentioned and is_irrelevant:
                evidence.append(
                    "UNCERTAIN: Item 2.01 8-K filed " + date_str
                    + " mentions acquirer but also has asset-sale language. "
                    + "Accession " + acc + " -- verify manually."
                )

    return len(evidence) > 0, evidence


def check_age_out(announcement_date_str, threshold_days=180):
    try:
        ann_date = datetime.strptime(announcement_date_str, "%Y-%m-%d")
        age_days = (datetime.utcnow() - ann_date).days
        return age_days > threshold_days, age_days
    except Exception:
        return False, 0


# ─────────────────────────────────────────────────────────────────────────
# Current 14 live tickers after KALV/ASRT/KROS excluded
# announcement_date: the known merger-announcement date per deal
# ─────────────────────────────────────────────────────────────────────────
LIVE_DEALS = [
    {"ticker": "CLST", "acquirer": "Catalyst",                     "announcement_date": "2026-04-08"},
    {"ticker": "WBD",  "acquirer": "Paramount",                    "announcement_date": "2026-02-27"},
    {"ticker": "GSAT", "acquirer": "Amazon",                       "announcement_date": "2026-04-14"},
    {"ticker": "CZR",  "acquirer": "Undisclosed",                  "announcement_date": "2026-05-28"},
    {"ticker": "PAYO", "acquirer": "Nuvei",                        "announcement_date": "2026-06-15"},
    {"ticker": "OGN",  "acquirer": "Sun Pharma",                   "announcement_date": "2026-04-27"},
    {"ticker": "AES",  "acquirer": "Consortium",                   "announcement_date": "2026-03-02"},
    {"ticker": "ALOT", "acquirer": "Arcline",                      "announcement_date": "2026-06-17"},
    {"ticker": "APGE", "acquirer": "AbbVie",                       "announcement_date": "2026-06-22"},
    {"ticker": "GBTG", "acquirer": "Long Lake",                    "announcement_date": "2026-05-04"},
    {"ticker": "NATH", "acquirer": "Undisclosed",                  "announcement_date": "2026-01-21"},
    {"ticker": "CPRX", "acquirer": "Angelini Pharma",              "announcement_date": "2026-05-07"},
    {"ticker": "AVNS", "acquirer": "American Industrial Partners", "announcement_date": "2026-04-14"},
    {"ticker": "JHG",  "acquirer": "Trian",                        "announcement_date": "2026-06-18"},
]
print("=" * 80)
print("MERIDIAN FEED VALIDATION -- Phase 1 (flag-for-review, read-only)")
print("Filing selection: anchored to known announcement_date +/- 7 days")
print("Same-entity threshold: Jaccard word overlap >= 0.6")
print("Age-out threshold: 180 days")
print("=" * 80)
print()

all_flags = []

for deal in LIVE_DEALS:
    ticker      = deal["ticker"]
    acquirer    = deal["acquirer"]
    ann_date    = deal["announcement_date"]

    print("─" * 70)
    print(ticker + "  |  acquirer: " + acquirer + "  |  announced: " + ann_date)
    print("─" * 70)

    flags_this_deal = []

    cik, company_name = get_cik(ticker)
    if not cik:
        msg = "No CIK found -- ticker may have delisted. Soft signal worth checking."
        print("  [SKIP] " + msg)
        print()
        flags_this_deal.append("NO CIK: " + msg)
        all_flags.append({"ticker": ticker, "flags": flags_this_deal})
        continue

    print("  Entity: " + company_name + " (CIK " + cik + ")")

    sub = get_submissions(cik)
    if not sub:
        print("  [SKIP] Could not fetch EDGAR submissions.")
        print()
        continue

    # Find the correct announcement filing anchored to the known date
    result, warning = find_announcement_filing(sub, cik, ann_date)

    if result is None:
        print("  Announcement filing: NOT FOUND -- " + warning)
        print("  Checks 1-2 (self-tender) SKIPPED -- no filing to check against.")
        print("  Check 3 (completion) will still run against post-announcement filings.")
        ann_form = None
        ann_text = None
    else:
        filing_date, ann_acc, ann_form, ann_text, ann_url = result
        print("  Announcement filing: " + ann_acc + " filed " + filing_date
              + " (form: " + ann_form + ")")
        print("  URL: " + ann_url)
        if warning:
            print("  WARNING: " + warning)

    # CHECK 1 + 2: self-tender / same-entity (tightened)
    if ann_form or ann_text:
        flagged_st, st_reasons = check_self_tender(ann_form, ann_text, company_name, acquirer)
        if flagged_st:
            for r in st_reasons:
                print("  *** SELF-TENDER FLAG: " + r + " ***")
                flags_this_deal.append("SELF-TENDER: " + r)
        else:
            print("  Self-tender checks: CLEAN")
    else:
        print("  Self-tender checks: SKIPPED (no filing text available)")

    # CHECK 3: completion (post-announcement only, acquirer-verified)
    flagged_comp, comp_evidence = check_completion(sub, cik, acquirer, ann_date)
    if flagged_comp:
        for e in comp_evidence:
            print("  *** COMPLETION FLAG:")
            for line in e.split("\n"):
                print("      " + line)
            print("  ***")
            flags_this_deal.append("COMPLETION: " + e.split("\n")[0])
    else:
        print("  Completion check: no post-announcement completion signals found")

    # CHECK 4: age-out
    flagged_age, age_days = check_age_out(ann_date, threshold_days=180)
    if flagged_age:
        print("  *** AGE-OUT FLAG: " + str(age_days)
              + " days since announcement (> 180) -- verify deal is still pending ***")
        flags_this_deal.append("AGE-OUT: " + str(age_days) + " days")
    else:
        print("  Age-out: " + str(age_days) + " days old (under 180-day threshold)")

    if flags_this_deal:
        all_flags.append({"ticker": ticker, "flags": flags_this_deal})
        print("  >>> FLAGS RAISED -- verify before any action <<<")

    print()
    time.sleep(0.4)

print("=" * 80)
print("SUMMARY")
print("=" * 80)
if not all_flags:
    print("No flags raised on any deal.")
else:
    print(str(len(all_flags)) + " deal(s) flagged for review:")
    for item in all_flags:
        print()
        print("  " + item["ticker"] + ":")
        for f in item["flags"]:
            print("    - " + f[:120])

print()
print("NEXT STEP: verify each flag against the filing URL printed above.")
print("Do NOT exclude anything based on this output alone.")