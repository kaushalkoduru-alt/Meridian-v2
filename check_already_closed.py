"""
check_already_closed.py -- read-only check for whether any currently-live Meridian
deals have ALREADY CLOSED, by checking EDGAR for completion signals.

Run locally: python check_already_closed.py
No main.py changes. No writes anywhere. Pure read + print.

Checks two signals per ticker, same logic verify_deals.py used for the historical
audit, applied here to the current live feed instead:
  1. Form 25 / Form 15 / 15-12B / 15-12G -- deregistration/delisting filings,
     which a target files shortly after a merger closes and it stops being a
     standalone public reporting company.
  2. Item 2.01 8-K ("Completion of Acquisition or Disposition of Assets") --
     filed by either party on or near the actual closing date.
A ticker that fires either signal is almost certainly already closed and should
be excluded the same way KALV was.

This is read-only diagnostic output. You decide what to exclude -- this script
makes no main.py edits.
"""
import time
import requests

HEADERS = {
    "User-Agent": "Meridian Verification Script kaushal@meridian.dev",
    "Accept-Encoding": "gzip, deflate",
}

DEREGISTRATION_FORMS = {"25", "25-NSE", "15", "15-12B", "15-12G"}

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

def check_ticker(ticker):
    cik = get_cik(ticker)
    if not cik:
        print("  No CIK found in EDGAR's live ticker map.")
        print("  >>> THIS ITSELF IS A SIGNAL: a ticker that recently closed/delisted")
        print("      can disappear from company_tickers.json entirely. Worth a manual")
        print("      check on whether this ticker still trades, separate from the")
        print("      filing-based signals below.")
        return

    try:
        sub = requests.get("https://data.sec.gov/submissions/CIK" + cik + ".json", headers=HEADERS, timeout=15).json()
        time.sleep(0.15)
    except Exception as e:
        print("  [submissions fetch error] " + str(e))
        return

    name = sub.get("name", "unknown")
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    items = recent.get("items", [])

    print("  Entity: " + name + "  |  CIK: " + cik)

    found_signal = False

    # Signal 1: deregistration / delisting forms
    for form, date, acc in zip(forms, dates, accessions):
        if form in DEREGISTRATION_FORMS:
            print("  *** DEREGISTRATION SIGNAL: Form " + form + " filed " + date + ", accession " + acc + " ***")
            found_signal = True

    # Signal 2: Item 2.01 completion 8-K
    for form, date, acc, item in zip(forms, dates, accessions, items):
        if form == "8-K" and item and "2.01" in str(item):
            print("  *** COMPLETION SIGNAL: 8-K Item 2.01 filed " + date + ", accession " + acc + " ***")
            found_signal = True

    if not found_signal:
        print("  No deregistration or completion filing found -- no evidence this deal has closed.")
    else:
        print("  >>> RECOMMEND EXCLUDING THIS TICKER, same treatment as KALV. <<<")

# Current ~13 remaining live tickers after the 5-change diff (KALV already
# being excluded separately, so it's left out of this check -- already handled).
TICKERS = ["WBD", "CZR", "OGN", "AES", "GBTG", "CPRX", "ASRT",
           "AVNS", "NATH", "GSAT", "CLST", "JHG", "ALOT", "PAYO"]

print("Checking " + str(len(TICKERS)) + " tickers for signs of already-closed deals...\n")
print("(KALV already confirmed closed and excluded separately -- not re-checked here)\n")

flagged = []

for ticker in TICKERS:
    print("=" * 70)
    print(ticker)
    print("=" * 70)
    check_ticker(ticker)
    print()
    time.sleep(0.3)

print("=" * 70)
print("Done. Any ticker printed with *** above should be reviewed for exclusion.")
print("This script made no changes -- exclude manually in EXCLUDED_TICKERS yourself.")