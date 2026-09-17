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

## Entry gates guard admission; nothing used to guard exit
A deal that enters the feed correctly can still go bad later — terminated, closed, or genuinely stalled — and until this was built nothing ever re-read the filings to check. STAA's merger was terminated 2026-01-06 (Item 1.02, "Merger Agreement was terminated") and stayed on the live feed five months, scored and displayed, because nothing looked. check_terminations() now runs every scan inside save_cache, on the full merged list (fresh + carried), so this can't recur — but the general lesson is: admission is not the only gate a deal needs. Ask "what filing would tell us this deal ended, and are we reading it" for any state that isn't announcement-time.

Related: a passed outside date is not one state, it's two opposite ones — a deal can pass its deadline because it stalled (High risk, correct) or because the tender succeeded and the deadline just stopped mattering (GBCS: 90.93% tendered, accepted for payment, squeeze-out pending). The fix that made GBCS's risk band correct again the first time (dedup tie-break letting a later-dated hit win) had its own blind spot: GBCS's own closing 8-K also carried Item 1.01 (for an unrelated post-closing Credit Agreement) and won the tie, silently swapping the tracked accession for a document with no merger terms in it at all. When two hits both look like "the operative document," check what the OTHER items on the same filing say before trusting the tie-break — 2.01/5.01 alongside 1.01 means the filing is reporting a closing, not proposing new terms.

Any flag that changes what a deal shows or how it scores has to live where the deal record lives. VALIDATION_FLAGS (completion signals, now termination) was in-memory only — correct until the process restarted, at which point a terminated deal had nothing stopping it from reappearing until daily_validation_loop got around to re-flagging it. Terminated status now has its own persisted key (meridian_terminated_v1, Redis + local-file fallback), checked before anything is re-derived. If it drives the feed, it needs the same durability the feed itself gets.

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
