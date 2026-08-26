# Meridian
Merger-arb screen. FastAPI on Railway. main.py + templates/index.html.

## Rules
- Nothing ships unless a real EDGAR filing proves it. Accession number or it doesn't exist.
- Never fabricate a number. Unverifiable means blank, and say so.
- Test against real filings before merging. A 200 response is not proof of correct extraction.
- Verification gate and direction check are both ENFORCING and can remove deals from the live feed.

## Recurring bug shape
The cache exists but the read happens after a write that clears it. Hit three times: detection-value freeze, direction verdicts, rolling merge. Check write order first when a cache looks empty.

Fourth instance: commitment and outside_date readings were re-fetched every scan because the deal dict is rebuilt from scratch and save_cache runs before the agreement pass. Any field expected to persist across scans must be captured at the top of fetch_deals_from_edgar, before the first write. Check this FIRST when adding any new cached field.

The flip side: caching on the document rather than on the reading means every extractor improvement is blocked by the cache until the marker is invalidated. Worth knowing before adding the next cached field.

## Gotchas
- worksheet.csv is four days of hand verification and is NOT in git. Back it up.
- Close Excel before any script touches a CSV.
- yfinance cannot price delisted tickers. Use Tiingo.
- Scans go quiet for minutes during path B lookbacks. Not hung.
- EDGAR's index.json does not always list a filing's documents. CZR's 8-K shows
  only the index pages, the complete-submission .txt and the XBRL zip, while the
  merger agreement sits in the same directory and serves fine. The human
  -index.html page lists it, and _ex2_from_index_page falls back to it.
- Not every extension names a date. APGE extends "by six (6) months" and states
  no day, so a date-only reader called it a fixed deadline. Periods are added as
  calendar months, never as 30.44-day approximations.
