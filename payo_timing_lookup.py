"""
payo_timing_lookup.py — one-off lookup of PAYO's actual 8-K acceptance datetime from EDGAR.
Run locally: python payo_timing_lookup.py
"""
import requests
import time

HEADERS = {
    "User-Agent": "Meridian Verification Script kaushalkoduru@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

def edgar_get_json(url, pause=0.2):
    time.sleep(pause)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

# Step 1: find PAYO's CIK
print("Looking up PAYO CIK...")
data = edgar_get_json("https://www.sec.gov/files/company_tickers.json")
cik = None
for entry in data.values():
    if entry["ticker"].upper() == "PAYO":
        cik = str(entry["cik_str"]).zfill(10)
        break

if not cik:
    print("PAYO not found in ticker map.")
    exit()

print(f"PAYO CIK: {cik}")

# Step 2: get recent filings, find the 8-K announcing the Nuvei deal (around June 15, 2026)
sub = edgar_get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
recent = sub.get("filings", {}).get("recent", {})
forms = recent.get("form", [])
dates = recent.get("filingDate", [])
accessions = recent.get("accessionNumber", [])
items = recent.get("items", [])

print("\nRecent 8-K filings around the deal announcement window:")
for form, date, acc, item in zip(forms, dates, accessions, items):
    if form == "8-K" and date >= "2026-06-01":
        print(f"  {date} — accession {acc} — items: {item}")

# Step 3: for the merger-announcement 8-K (likely Item 1.01), fetch the index JSON for exact acceptance time
print("\nFetching exact acceptance datetime for each candidate filing...")
for form, date, acc, item in zip(forms, dates, accessions, items):
    if form == "8-K" and date >= "2026-06-01":
        acc_clean = acc.replace("-", "")
        url = f"https://data.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{acc}-index.json"
        try:
            idx = edgar_get_json(url, pause=0.15)
            adt = idx.get("acceptanceDateTime") or "not found"
            print(f"  {acc} ({item}): acceptanceDateTime = {adt}")
        except Exception as e:
            print(f"  {acc}: error fetching index — {e}")

print("\nThe Item 1.01 filing (merger agreement) is your true filed_at timestamp for PAYO.")
