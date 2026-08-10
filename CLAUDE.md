# Meridian
Merger-arb screen. FastAPI on Railway. main.py + templates/index.html.

## Rules
- Nothing ships unless a real EDGAR filing proves it. Accession number or it doesn't exist.
- Never fabricate a number. Unverifiable means blank, and say so.
- Test against real filings before merging. A 200 response is not proof of correct extraction.
- Verification gate and direction check are both ENFORCING and can remove deals from the live feed.

## Recurring bug shape
The cache exists but the read happens after a write that clears it. Hit three times: detection-value freeze, direction verdicts, rolling merge. Check write order first when a cache looks empty.

## Gotchas
- worksheet.csv is four days of hand verification and is NOT in git. Back it up.
- Close Excel before any script touches a CSV.
- yfinance cannot price delisted tickers. Use Tiingo.
- Scans go quiet for minutes during path B lookbacks. Not hung.
