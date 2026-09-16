# Meridian — Live Site Claims Inventory

Audited: templates/index.html (landing, arb primer, methodology, privacy, dashboard,
deal-detail JS, paywall modal) cross-checked against main.py, deal_flags.py,
worksheet.csv, historical_deals.csv/historical_excluded.csv.

Categories: **EXTRACTION** (fact from a filing/code, verify against source),
**MODEL** (asserts break likelihood/probability/outcome, needs the historical
backtest), **UNSUPPORTABLE** (neither — flag for cut or relabel).

| # | Claim (verbatim or close paraphrase) | Location | Category | Evidence needed |
|---|---|---|---|---|
| 1 | "Every active US merger, pulled straight from EDGAR filings and priced against the tape in real time" | Landing §What You Get, card 01 (index.html:1015) | EXTRACTION | Spot-check N live deals: accession numbers exist, price timestamp matches last scan |
| 2 | "Six factors composited into one score... exact formula is public, no black box" | Landing card 02 (1021) | UNSUPPORTABLE | Contradicts methodology page, which lists **7** factors (fact-strip says "7", hero text says "six", paywall modal says "6-factor model"). Pick one number and fix everywhere |
| 3 | "A modeled downside floor for every deal... You see the risk before you take it" | Landing card 03 (1027) | UNSUPPORTABLE | Calls break price a "floor," but deal-detail copy says the opposite: "on the 4 historical breaks the stock landed below it every time... Low confidence, biased high" (2848, 2996). A number the data undershoots 100% of the time is not a floor — reword or cut "floor" |
| 4 | "DOJ, FCC, and shareholder gates mapped for every deal, with the one risk that actually matters called out" | Landing card 04 (1033) | UNSUPPORTABLE | `FCC` does not appear anywhere in main.py or deal_flags.py; no shareholder-vote gate exists. Regulatory factor only covers Standard Review / HSR / FTC-DOJ / Market Concentration / CFIUS. Cut "FCC" and "shareholder gates" or build them first |
| 5 | "Every deal is checked against its definitive agreement before it reaches the board" | Landing, "Verified" card (1041) | EXTRACTION | Confirm the verification gate (verification.py / deal_gate.py) actually blocks publish for every deal, not just flags it — check for a bypass path |
| 6 | "Prices, terms, and dates come from the actual SEC filings, not a data vendor's summary" | Landing, "Sourced" card (1045) | UNSUPPORTABLE | Terms/dates: true (EDGAR). **Prices are not**: main.py prices via yfinance (Yahoo) and Tiingo for delisted names, neither of which is a filing. Reword to scope "prices" out or name the real source |
| 7 | "Data sourced from SEC EDGAR and Yahoo Finance" | Footer (1255) | EXTRACTION | True for the common case; omits Tiingo fallback for delisted tickers (CLAUDE.md gotcha) — minor, low priority |
| 8 | "Refreshed Hourly" / "Prices refresh hourly alongside deal data" | Dashboard header (1215), footer (1256) | EXTRACTION | Verified: `asyncio.sleep(3600)` scan loop in main.py:3925/4041. Confirmed true |
| 9 | "Past model performance does not guarantee future results" | Footer disclaimer (1085, 1258, 1651) | UNSUPPORTABLE | Implies a performance history exists; site elsewhere says the forward track record "begins June 2026" (1764, 1916). Stale boilerplate — cut until there is a track record, or reword to "the historical weights are not validated" |
| 10 | "The size of the gap [spread] correlates strongly with the odds a deal closes" | Methodology, "key insight" (1792) | MODEL | This is the central causal claim — the backtest must test it directly at real sample size |
| 11 | "Deals trading below 8% spread reflect market confidence in closure. Deals above 12% reflect elevated break risk." | Methodology (1792), risk bands (1890–1906) | MODEL | Needs backtest support for the specific 8%/12% cutoffs, not just direction |
| 12 | Spread Quality point table (0–3%:+12 ... 25%+:−18) | Methodology Factor 01 (1802–1808) | MODEL | Backtest: do these bands actually rank-order outcomes in the sample? |
| 13 | Consideration scoring (+8 cash/tender, +4 stock leg, +0 unclear) | Methodology Factor 02 (1819–1822) | MODEL | Backtest: does consideration type predict close/break independent of spread? |
| 14 | Days Elapsed scoring (+10 <90d ... −15 500+d) | Methodology Factor 03 (1828–1831) | MODEL | Backtest: does deal age predict break risk, or proxy for something else (e.g. regulatory delay)? |
| 15 | Regulatory scoring (+5 Standard ... −18 CFIUS) | Methodology Factor 04 (1837–1843) | MODEL | Backtest — site already admits (1925) 3 of 4 known breaks involved a regulator, but n=4 "is far too few to prove anything" |
| 16 | "Premium size is not scored... a large premium is not evidence a deal will close" | Methodology Factor 05 (1848–1849) | EXTRACTION (negative claim) | Verify code truly assigns +0 regardless of premium size (quick grep of scoring function) |
| 17 | Financing Signal scoring (+10 committed ... −10 contingent) | Methodology Factor 06 (1856–1861) | MODEL | Backtest: does financing certainty language predict outcome? |
| 18 | Contractual Deadline scoring (−25 passed outside date ... +0 far/no date) | Methodology Factor 07 (1868–1872) | MODEL | Backtest — plausibly the strongest mechanical signal, but still unvalidated per site's own footnote |
| 19 | "Base score starts at 50... normalizes from its −38…95 range onto 0–100" | Methodology footnote (1876) | EXTRACTION | Verified against code: main.py:1051–1054 matches exactly |
| 20 | Risk band descriptions: "Maximum conviction," "High confidence," "Uncertain zone," "Elevated risk... pricing in significant break probability" | Methodology risk classification (1888–1906) | MODEL | Same backtest as #10/#11 — the adjectives assert calibration the site hasn't yet earned |
| 21 | "We hand checked 39 completed merger deals from 2022 to 2025... 89.7% of deals closed... 126 median days to close... 4 deals that fell apart" | Methodology track record (1919–1923) | EXTRACTION | **Highest priority.** worksheet.csv (90 rows) gets ~42 cash-completed deals / 88.1% closed / 5 broken under a naive filter — close but not exact. The precise 39/89.7%/126/4 filter (cash-only, no CVR, excludes non-merger rows) must be reconstructed and locked down as the authoritative dataset before the backtest starts |
| 22 | "Every one was read directly from its SEC filing, not from a data vendor" (re: the 39 deals) | Methodology (1919) | EXTRACTION | Spot-check a sample of the 39 for `verified_by_hand=y` and an accession number, per worksheet.csv columns |
| 23 | "All four deals that failed were bought by regular companies rather than private equity firms, and three of those were blocked or challenged by regulators" | Methodology (1925) | EXTRACTION | Verify against the reconstructed 39-deal set once #21 is locked down |
| 24 | "Cash deals only... left out because Meridian cannot price them" | Methodology (1926) | EXTRACTION | Consistent with worksheet.csv deal_type field and CVR exclusions (e.g. STCN) — confirm no cash+stock or contingent-payout row leaked into the 39 |
| 25 | "Market-implied close probability" (per-deal %) | Deal detail, Market Environment (2839–2848) | MODEL | This is the number the backtest must calibrate — needs a reliability/calibration check (of deals shown at ~70%, do ~70% close?) |
| 26 | "on the 4 historical breaks the stock landed below [the break price] every time" | Deal detail (2848, 2967, 2996) | EXTRACTION | Same dataset as #21/#23 — must stay consistent with whatever the locked 39-deal set says once reconciled |
| 27 | "Break-even close probability" / levered vs. unlevered return framing | Deal detail (2871–2882) | MODEL (derived) | Arithmetic is fine given inputs; only the underlying probability input (#25) needs backtest support |
| 28 | Risk tooltip: "Spread of X% puts this deal in the High Risk zone... elevated break probability... pricing in significant deal risk" | Deal card JS (2196) | MODEL | Same backtest as #10/#11 |
| 29 | "These are analyst-set weights, not backtested. The forward record calibrates them as deals resolve." | Score breakdown footer (3290) | Self-disclosure (keep) | Already honest — once the backtest runs, either update this line to cite it or leave it if the backtest still can't validate at n=39 |
| 30 | "No analytics service, no tracking pixel, no advertising network, and no third-party cookies" | Privacy page (1967) | EXTRACTION | Verified: no analytics/tracking script tags found in index.html |
| 31 | "Your data is not sold. Ever." / "not shared... except [Clerk, Stripe, hosting]" | Privacy page (1971–1973) | EXTRACTION | Verify against actual third-party calls in main.py (Clerk, Stripe, Railway only — no others) |
| 32 | "The scores, break prices and probabilities are one analyst's model applied to public filings — they can be wrong" | Privacy page (1977) | Self-disclosure (keep) | Appropriately hedged, no action needed |
| 33 | Arb-primer $50/$48.50 worked example | Arb primer (1125–1135) | Illustrative, not a claim | N/A — clearly hypothetical, no verification needed |
| 34 | "The spread is really a probability in disguise... nearly certain... where the opportunity lives" | Arb primer (1146–1147) | MODEL (general theory) | Softer/more general than #10; still rests on the same backtest for "correlates strongly" |

## Priority order for the two backtests
- **MODEL backtest** must cover #10–#20, #25, #27–#28 — all rest on "spread/factor X predicts outcome" and share one dataset.
- **EXTRACTION reconciliation** must resolve #21–#24, #26 first, since the MODEL backtest's n and definition of "completed deal" depend on that exact 39-deal set existing and being reproducible from worksheet.csv.
- **Fix immediately, no backtest needed:** #2 (6 vs 7 factors), #3 (break price called a "floor"), #4 (fabricated FCC/shareholder coverage), #6 (prices misattributed to filings), #9 (stale "past performance" line).
