"""
get_close_date_sentences.py -- pulls the EXACT closing-timeframe sentence from
each deal's real merger announcement 8-K, for manual verification before hardcoding.

Run locally: python get_close_date_sentences.py
No Groq calls needed -- pure text extraction + printing. You read the sentences
yourself and decide the hardcode values.

Fixes in this version:
1. PAYO no longer uses a special-case direct accession/-index.json lookup -- that
   path 404'd and crashed the whole run on JSONDecodeError before reaching any
   other ticker. PAYO is still live in EDGAR's ticker map, so it goes through the
   same find_real_merger_8k search as every other ticker.
2. Every per-ticker network call is wrapped so a single failure prints a clear
   message and the loop CONTINUES -- one bad ticker can no longer kill the run.
3. Searches ALL Item 1.01 8-Ks for each ticker and picks the EARLIEST one whose
   text actually contains merger-agreement language, not just "most recent Item
   1.01" -- avoids picking up a later regulatory/amendment filing by mistake.
4. Always prints the raw sentence/section found, even when no clean timeframe
   exists, so you can read what the filing actually says.
"""
import time
import requests

HEADERS = {
    "User-Agent": "Meridian Verification Script kaushal@meridian.dev",
    "Accept-Encoding": "gzip, deflate",
}

MERGER_AGREEMENT_SIGNALS = [
    'agreement and plan of merger', 'merger agreement', 'definitive agreement',
    'acquire all', 'acquire the company', 'to be acquired by', 'entered into a',
]

CLOSING_TIMEFRAME_HEADERS = [
    'expected to close', 'expected closing', 'anticipated to close',
    'anticipated closing', 'closing is expected', 'transaction is expected to close',
    'merger is expected to close', 'expected to be completed',
    'completion of the transaction', 'completion of the merger',
    'consummation of the merger', 'expected to occur',
]

def get_text_from_url(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        time.sleep(0.15)
        if r.status_code != 200:
            return None
        from html.parser import HTMLParser
        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
            def handle_data(self, data):
                self.text.append(data)
        parser = TextExtractor()
        parser.feed(r.text)
        return ' '.join(parser.text)
    except Exception as e:
        print("    [text fetch error] " + str(e))
        return None

def get_cik(ticker):
    try:
        data = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=15).json()
        time.sleep(0.2)
        for entry in data.values():
            if entry["ticker"].upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        return None
    except Exception as e:
        print("  [CIK lookup error] " + str(e))
        return None

def find_real_merger_8k(ticker, cik):
    """
    Pulls ALL Item 1.01 8-Ks for this ticker, sorted EARLIEST first, and returns
    the first one whose text actually contains merger-agreement language.
    Returns None (not a crash) on any failure -- caller handles that gracefully.
    """
    try:
        sub = requests.get("https://data.sec.gov/submissions/CIK" + cik + ".json", headers=HEADERS, timeout=15).json()
        time.sleep(0.15)
    except Exception as e:
        print("  [submissions fetch error] " + str(e))
        return None

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    items = recent.get("items", [])
    filing_dates = recent.get("filingDate", [])

    candidates = []
    for form, acc, doc, item, fdate in zip(forms, accessions, primary_docs, items, filing_dates):
        if form == "8-K" and doc and item and "1.01" in str(item):
            candidates.append((fdate, acc, doc, item))

    if not candidates:
        return None

    # EARLIEST first -- the original merger agreement filing, not a later one
    candidates.sort(key=lambda c: c[0])

    for fdate, acc, doc, item in candidates:
        acc_clean = acc.replace("-", "")
        doc_url = "https://www.sec.gov/Archives/edgar/data/" + str(int(cik)) + "/" + acc_clean + "/" + doc
        text = get_text_from_url(doc_url)
        if text and any(sig in text.lower() for sig in MERGER_AGREEMENT_SIGNALS):
            return {"accession": acc, "filing_date": fdate, "url": doc_url, "text": text, "all_item101_count": len(candidates)}

    # None of the Item 1.01 filings contained merger language -- return the earliest anyway, flagged
    fdate, acc, doc, item = candidates[0]
    acc_clean = acc.replace("-", "")
    doc_url = "https://www.sec.gov/Archives/edgar/data/" + str(int(cik)) + "/" + acc_clean + "/" + doc
    text = get_text_from_url(doc_url)
    return {"accession": acc, "filing_date": fdate, "url": doc_url, "text": text or "", "all_item101_count": len(candidates), "no_merger_language_found": True}

def find_closing_sentence(text):
    """Returns the full sentence(s) around any closing-timeframe header found, or None."""
    if not text:
        return None
    text_lower = text.lower()
    for header in CLOSING_TIMEFRAME_HEADERS:
        idx = text_lower.find(header)
        if idx != -1:
            start = text.rfind('.', 0, idx)
            start = start + 1 if start != -1 else max(0, idx - 150)
            end = text.find('.', idx)
            end = end + 1 if end != -1 else min(len(text), idx + 250)
            sentence = text[start:end].strip()
            if len(sentence) > 15:
                return sentence
    return None

# ─────────────────────────────────────────────────────────────────────────
# 14 live deals -- HES and SIAL dropped (historical), PAYO added to the
# regular list (no more special-case lookup), JHG and ALOT included per request
# ─────────────────────────────────────────────────────────────────────────
TICKERS = ["WBD", "CZR", "OGN", "AES", "GBTG", "CPRX", "ASRT", "KALV",
           "AVNS", "NATH", "GSAT", "CLST", "JHG", "ALOT", "PAYO"]

for ticker in TICKERS:
    print("=" * 90)
    print(ticker)
    print("=" * 90)

    cik = get_cik(ticker)
    if not cik:
        print("  No CIK found -- ticker may be delisted/acquired (left company_tickers.json) or misspelled.")
        print("  If this deal already closed, that's WHY the lookup fails -- the ticker drops from EDGAR's live map.")
        print()
        continue

    result = find_real_merger_8k(ticker, cik)
    if not result:
        print("  No Item 1.01 8-K found at all for this CIK, or the submissions fetch failed (see error above).")
        print()
        continue

    if result.get("no_merger_language_found"):
        print("  WARNING: none of the " + str(result["all_item101_count"]) + " Item 1.01 filing(s) found contained merger-agreement language.")
        print("  Showing earliest Item 1.01 filing anyway -- may be the wrong document, verify manually.")

    print("  Filing date: " + result["filing_date"] + "  |  Accession: " + result["accession"])
    print("  URL: " + result["url"])

    sentence = find_closing_sentence(result["text"])
    if sentence:
        print("  CLOSING SENTENCE: \"" + sentence + "\"")
    else:
        print("  NO TIMEFRAME STATED IN FILING (no closing-timeframe header matched in the text).")

    print()
    time.sleep(0.3)

print("=" * 90)
print("Done. Read each printed sentence against its URL before treating it as the real date.")