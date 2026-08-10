"""
Standalone test for milestone detection. Run locally where EDGAR is reachable.

    python test_milestones.py

Tests against REAL filings for deals currently in the feed. Prints what it found,
what it couldn't, and the evidence for every confirmed milestone.
"""
import sys, time, requests
from detect_milestones import detect_milestones, extract_meeting_date

SEC_HEADERS = {"User-Agent": "Meridian Research contact@meridianarb.com"}

# Deals currently live. filed dates from the feed.
TEST_DEALS = [
    {"ticker": "NATH", "filed": "2026-01-21", "acquirer": "Smithfield Foods"},
    {"ticker": "PAYO", "filed": "2026-04-23", "acquirer": "Nuvei"},
    {"ticker": "WBD",  "filed": "2026-04-17", "acquirer": "Paramount"},
    {"ticker": "GSAT", "filed": "2026-05-06", "acquirer": "Amazon"},
    {"ticker": "CZR",  "filed": "2026-05-19", "acquirer": "Fertitta Entertainment"},
    {"ticker": "ALOT", "filed": "2026-05-01", "acquirer": "Arcline"},
    {"ticker": "CPRX", "filed": "2026-06-20", "acquirer": "Angelini Pharma"},
    # known-closed control: should show completed
    {"ticker": "JHG",  "filed": "2026-06-18", "acquirer": "Trian Fund Management"},
]

# Build the ticker->CIK map exactly the way main.py does, so this test
# can never drift from production.
_CIK_MAP = {}
def _load_cik_map():
    global _CIK_MAP
    if _CIK_MAP:
        return
    r = requests.get("https://www.sec.gov/files/company_tickers.json",
                     headers=SEC_HEADERS, timeout=15)
    for _, v in r.json().items():
        t = str(v.get("ticker", "")).upper().strip()
        if t:
            _CIK_MAP[t] = str(v.get("cik_str", "")).zfill(10)
    print(f"[SEC] ticker map loaded: {len(_CIK_MAP)} tickers\n")

def get_cik(ticker):
    _load_cik_map()
    return _CIK_MAP.get(ticker.upper())

def fetch_text(url):
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=20)
        if r.status_code != 200:
            return ""
        import re
        txt = re.sub(r"<[^>]+>", " ", r.text)
        txt = re.sub(r"&nbsp;", " ", txt)
        txt = re.sub(r"&#\d+;", " ", txt)
        return re.sub(r"\s+", " ", txt)
    except Exception:
        return ""

ICON = {"confirmed": "[✓]", "scheduled": "[◆]", "pending": "[ ]"}

def main():
    print("=" * 78)
    print("MILESTONE DETECTION TEST — real EDGAR filings")
    print("=" * 78)

    for d in TEST_DEALS:
        t = d["ticker"]
        print(f"\n{'─'*78}\n{t}  (announced {d['filed']}, acquirer {d['acquirer']})\n{'─'*78}")
        cik = get_cik(t)
        if not cik:
            print("  CIK not found — skipping (delisted?)")
            continue
        print(f"  CIK: {cik}")
        time.sleep(0.4)

        ms = detect_milestones(t, cik, d["filed"], acquirer=d["acquirer"], fetch_text=fetch_text)

        for m in ms:
            icon = ICON.get(m["status"], "[?]")
            date = m["date"] or "—"
            print(f"  {icon} {m['label']:<24} {date:<12} {m['status']}")
            if m["evidence"]:
                print(f"       evidence: {m['evidence'][:110]}")

        conf = sum(1 for m in ms if m["status"] == "confirmed")
        sched = sum(1 for m in ms if m["status"] == "scheduled")
        print(f"\n  → {conf} confirmed, {sched} scheduled, {len(ms)-conf-sched} pending")
        time.sleep(0.6)

    print("\n" + "=" * 78)
    print("WHAT TO CHECK:")
    print("  1. Does every [✓] have a real accession number as evidence?")
    print("  2. JHG should show 'Deal Completed' confirmed (known closed).")
    print("  3. Any deal with a proxy — did the meeting date extract correctly?")
    print("     Verify against the actual filing before trusting it.")
    print("  4. Nothing should have a date without evidence.")
    print("=" * 78)

if __name__ == "__main__":
    main()