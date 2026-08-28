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

Any write whose failure is invisible must check its return value and name which store it reached. redis_set silently dropped every enriched write for days while save_cache printed "Cache saved" regardless, because it ignored the return. A log line that prints on success and failure alike is worse than no log line.

Fifth and sixth instances, both of that shape: redis_set percent-encoded the whole feed into the URL path, so the enriched payload (106,794 chars) was rejected while the pre-enrichment one (54,082) fit — every scan wrote correct prices and no pricing, commitment or outside_date. And fetch_sec_ticker_map wrote {"value": ..., "ex": ...} as a JSON body, which Upstash stores verbatim, while the reader json.loads()'d it and looked for ticker_map at the top level — so the cache never hit and all 10,391 tickers were re-fetched on every start. Both fixed by putting the raw payload in the body. When a read looks like it never hits, compare the exact bytes the writer stores against the shape the reader expects.

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
