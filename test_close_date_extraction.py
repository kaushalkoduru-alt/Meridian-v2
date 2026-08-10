"""
test_close_date_extraction.py -- validates the improved close_date extraction logic.

Run locally: python test_close_date_extraction.py
Requires: GROQ_API_KEY environment variable set (same key as Railway uses)

IMPORTANT -- read before trusting any output:
This script does NOT auto-grade extractions against an answer key. There is no
answer key. Every result must be manually verified by YOU reading the source_quote
against the actual filing (a link is printed for each one). A script grading itself
against unverified labels can't catch its own errors -- that defeats the purpose.

What this does:
1. For each ticker, finds the MERGER 8-K specifically -- the filing with Item 1.01
   (entry into a material definitive agreement) -- not just the most recent 8-K.
2. Runs extract_closing_section() + the structured Groq prompt against that filing.
3. Prints: the extracted close_date, the confidence, the EXACT source_quote, and a
   direct link to the filing so you can verify the quote yourself in seconds.
4. Reports a breakdown of EXTRACTED vs ABSTAINED vs SKIPPED -- with zero automated
   correct/wrong judgment. You make that call by reading the quotes.
"""
import os
import json
import time
import requests

HEADERS = {
    "User-Agent": "Meridian Verification Script kaushal@meridian.dev",
    "Accept-Encoding": "gzip, deflate",
}

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
if not GROQ_KEY:
    print("ERROR: set GROQ_API_KEY environment variable first.")
    print('  Git Bash: export GROQ_API_KEY="your_key_here"')
    exit(1)

CLOSING_TIMEFRAME_HEADERS = [
    'expected to close', 'expected closing', 'anticipated to close',
    'anticipated closing', 'closing is expected', 'transaction is expected to close',
    'merger is expected to close', 'subject to customary closing conditions',
    'completion of the transaction', 'completion of the merger',
]

DATE_SIGNAL_WORDS = [
    'q1', 'q2', 'q3', 'q4', 'quarter', 'first half', 'second half',
    'h1', 'h2', 'early', 'mid-', 'late', 'first quarter', 'second quarter',
    'third quarter', 'fourth quarter', '2026', '2027', '2028',
    'january', 'february', 'march', 'april', 'may', 'june', 'july',
    'august', 'september', 'october', 'november', 'december',
]

def extract_closing_section(filing_text):
    text_lower = filing_text.lower()
    for header in CLOSING_TIMEFRAME_HEADERS:
        idx = text_lower.find(header)
        if idx != -1:
            window_start = max(0, idx - 200)
            window_end = min(len(filing_text), idx + 400)
            block = filing_text[window_start:window_end]
            if any(sig in block.lower() for sig in DATE_SIGNAL_WORDS):
                return block
    return None

def call_groq_close_date(closing_section):
    prompt = ("This is a section of an SEC merger filing that may state an expected closing timeframe.\n\n"
        "Filing excerpt:\n" + closing_section + "\n\n"
        "Extract the expected closing timeframe EXACTLY as stated (e.g. \"first half of 2027\", \"Q4 2026\", \"mid-2027\", \"early 2027\").\n\n"
        "Rules:\n"
        "- Only extract a timeframe if it is EXPLICITLY stated in this excerpt as when the deal/merger/transaction is expected to close or complete.\n"
        "- Do NOT infer a date from context, fiscal year mentions, or unrelated dates in the text.\n"
        "- If the excerpt does not clearly state a closing timeframe, return null for close_date and \"low\" for confidence.\n"
        "- source_quote must be the EXACT sentence or phrase from the excerpt that states the timeframe. If you cannot quote it directly from the excerpt, return null for close_date.\n\n"
        "Return JSON only in this exact format:\n"
        "{\"close_date\": \"first half of 2027\", \"confidence\": \"high\", \"source_quote\": \"the transaction is expected to close in the first half of 2027\"}\n\n"
        "Or if no timeframe is stated:\n"
        "{\"close_date\": null, \"confidence\": \"low\", \"source_quote\": \"\"}")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + GROQ_KEY, "Content-Type": "application/json"},
        json={
            "model": "llama-3.1-8b-instant",
            "max_tokens": 200,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "You are an M&A data extractor. Return only valid JSON, no other text. You never guess or infer dates that are not explicitly stated."},
                {"role": "user", "content": prompt}
            ]
        },
        timeout=15
    )
    if resp.status_code != 200:
        return {"error": "HTTP " + str(resp.status_code)}
    content = resp.json()['choices'][0]['message']['content'].strip()
    content = content.replace('```json', '').replace('```', '').strip()
    return json.loads(content)

def verification_gate(cd_data):
    cd = cd_data.get('close_date')
    confidence = cd_data.get('confidence', 'low')
    source_quote = cd_data.get('source_quote', '') or ''
    quote_has_date_signal = any(sig in source_quote.lower() for sig in DATE_SIGNAL_WORDS)

    if (cd and isinstance(cd, str) and len(cd) > 2
            and confidence == 'high'
            and len(source_quote.strip()) > 10
            and quote_has_date_signal
            and cd.lower() not in ['null', 'none', 'tbd', 'unknown']):
        return True, cd.strip(), source_quote
    return False, None, "confidence=" + confidence + ", quote=\"" + source_quote[:60] + "\""

def get_cik(ticker):
    data = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=15).json()
    time.sleep(0.2)
    for entry in data.values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    return None

def get_merger_8k_text(ticker, cik):
    sub = requests.get("https://data.sec.gov/submissions/CIK" + cik + ".json", headers=HEADERS, timeout=15).json()
    time.sleep(0.15)
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
        return None, None, None, None, None

    candidates.sort(key=lambda c: c[0], reverse=True)
    fdate, acc, doc, item = candidates[0]

    if len(candidates) > 1:
        print("  NOTE: " + ticker + " has " + str(len(candidates)) + " Item 1.01 filings -- using most recent (" + fdate + "). Verify this is the right deal.")

    acc_clean = acc.replace("-", "")
    doc_url = "https://www.sec.gov/Archives/edgar/data/" + str(int(cik)) + "/" + acc_clean + "/" + doc
    try:
        r = requests.get(doc_url, headers=HEADERS, timeout=15)
        time.sleep(0.15)
        if r.status_code == 200:
            from html.parser import HTMLParser
            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text = []
                def handle_data(self, data):
                    self.text.append(data)
            parser = TextExtractor()
            parser.feed(r.text)
            return ' '.join(parser.text), acc, fdate, item, doc_url
    except Exception as e:
        print("  Error fetching " + doc_url + ": " + str(e))
    return None, None, None, None, None

TEST_TICKERS = [
    "WBD", "CZR", "OGN", "AES", "GBTG", "CPRX", "ASRT", "KALV",
    "AVNS", "NATH", "GSAT", "CLST", "PAYO", "HES", "SIAL",
]

print("Testing " + str(len(TEST_TICKERS)) + " tickers against their Item 1.01 merger 8-Ks...\n")
print("No auto-grading. Read each source_quote against the filing URL printed before trusting it.\n")
results = []

for ticker in TEST_TICKERS:
    print("--- " + ticker + " ---")

    cik = get_cik(ticker)
    if not cik:
        print("  No CIK found, skipping")
        results.append({"ticker": ticker, "outcome": "SKIP", "reason": "no CIK"})
        continue

    filing_text, accession, fdate, item_tag, doc_url = get_merger_8k_text(ticker, cik)
    if not filing_text:
        print("  No Item 1.01 (merger agreement) 8-K found for this ticker, skipping")
        results.append({"ticker": ticker, "outcome": "SKIP", "reason": "no Item 1.01 filing found"})
        continue

    print("  Filing: " + accession + " | " + fdate + " | items: " + str(item_tag))
    print("  URL: " + doc_url)

    closing_section = extract_closing_section(filing_text)
    if not closing_section:
        print("  No closing-timeframe section found in the merger 8-K -- would NOT call Groq (correctly abstains)")
        results.append({
            "ticker": ticker, "outcome": "NO_SECTION_FOUND",
            "accession": accession, "url": doc_url,
        })
        continue

    cd_data = call_groq_close_date(closing_section)
    if "error" in cd_data:
        print("  Groq error: " + cd_data['error'])
        results.append({"ticker": ticker, "outcome": "GROQ_ERROR", "reason": cd_data["error"]})
        continue

    accepted, value, detail = verification_gate(cd_data)

    if accepted:
        print("  EXTRACTED: \"" + value + "\"")
        print("  SOURCE QUOTE: \"" + detail + "\"")
        print("  >>> VERIFY this quote appears in the filing at the URL above before trusting it <<<")
        outcome = "EXTRACTED"
    else:
        print("  ABSTAINED: " + detail)
        outcome = "ABSTAINED"

    results.append({
        "ticker": ticker, "outcome": outcome,
        "extracted": value if accepted else None,
        "source_quote": detail if accepted else None,
        "accession": accession, "url": doc_url,
    })
    time.sleep(3.5)

print("\n\n=== SUMMARY (counts only -- no correctness judgment, that's on you) ===")
extracted = [r for r in results if r["outcome"] == "EXTRACTED"]
abstained = [r for r in results if r["outcome"] in ("ABSTAINED", "NO_SECTION_FOUND")]
skipped = [r for r in results if r["outcome"] in ("SKIP", "GROQ_ERROR")]

print("\nEXTRACTED (" + str(len(extracted)) + ") -- verify each source_quote against its filing URL:")
for r in extracted:
    print("  " + r['ticker'] + ": \"" + r['extracted'] + "\"")
    print("    quote: \"" + r['source_quote'] + "\"")
    print("    url:   " + r['url'])

print("\nABSTAINED (" + str(len(abstained)) + ") -- extractor found no confident date:")
for r in abstained:
    print("  " + r['ticker'])

print("\nSKIPPED (" + str(len(skipped)) + ") -- no usable filing found, not a model judgment:")
for r in skipped:
    print("  " + r['ticker'] + ": " + r.get('reason', 'unknown'))

print("\n\nNEXT STEP: open each EXTRACTED url above, find the source_quote in the actual")
print("filing text, and confirm it says what the script claims. Only after every single")
print("EXTRACTED row checks out against the real filing does 'zero wrong' hold.")