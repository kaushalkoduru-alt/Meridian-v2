# §25 — QA report on the twelve live deals

Checked 2026-08-27 against the live cache (`meridian_cache.csv`, fetched
2026-08-26T04:0x) and, where a filing settles the question, against the filing
itself. Findings only; no code changed here.

Twelve deals: the eleven in the cache, plus SLAB, which the scan verifies but
which carries no cache row — that absence is itself a finding (**C5**).

Per deal: break price, probability, risk score, data freshness, missing contract
information, missing regulatory information, missing sources, formula
application, edge cases.

## Classification

| | meaning | fix |
|---|---|---|
| **DATA** | this deal's values are wrong or stale | re-read or re-source this deal |
| **FORMULA** | the calculation is wrong for every deal | change the code once |
| **COVERAGE** | the field cannot be populated for this deal at all | build something new |

**20 findings: 7 FORMULA, 6 COVERAGE, 7 DATA.** Three need a decision before
anything is built — see *Decisions needed*.

The FORMULA findings are cross-referenced to AUDIT.md rather than restated,
except **F7**, which is new and was not visible from the code alone.

---

## Cross-cutting FORMULA findings

These apply to all twelve deals. Counted once each, not twelve times.

| ID | Finding | Reference |
|---|---|---|
| **F1** | Break price is a pre-announcement price lookup, not a model | AUDIT #8 |
| **F2** | Probability inherits F1 entirely | AUDIT #9 |
| **F3** | Risk score double-counts spread; weights unvalidated | AUDIT #10 |
| **F4** | Regulatory tags are size/sector priors, never status | AUDIT #11 |
| **F5** | `tx_value` mixes enterprise and equity basis | AUDIT #15 |
| **F6** | Financing status read from the press release, not the agreement | AUDIT #16 |
| **F7** | **The break-price lookback has no run-up detection** | new — below |

### F7 · The lookback takes the most contaminated price available — FORMULA

`get_break_price` walks back 7, 14, 21 then 30 days from the filing date and
takes the **last close in the window** — the close immediately before the
filing. Where a deal leaked or was rumoured, that is precisely the price most
inflated by the leak.

AES makes this visible because its contamination was large enough to invert the
sign. Its weekly closes into the announcement:

```
2025-11-09  13.63     2026-01-25  13.75
2025-12-07  13.43     2026-02-01  14.30   <- run-up begins
2025-12-21  13.05     2026-02-08  15.67
2026-01-04  14.30     2026-02-15  15.89
2026-01-11  13.81     2026-02-22  16.12
2026-01-18  13.69     2026-03-01  16.87   <- taken as "unaffected"
                      2026-03-08  13.95   <- announcement, -17.8%
```

The stock traded $13–14 for four months, ran up 23% over four weeks, and then
fell 17.8% on the day the 8-K was filed. `get_break_price` selected $16.87 — the
peak of the run-up, the single most deal-contaminated close in the series — and
labelled it the unaffected price.

This is distinct from the adjustment drift and the inert `spread_regression`
fallback already in AUDIT #8. Those are defects in how the number is computed;
this is a defect in **which day is chosen**, and it survives any improvement to
the other two. It is invisible from the code, which looks reasonable, and only
appears when the price series is read.

Every deal in the feed is exposed. AES is the only one where the contamination
exceeded the offer premium and produced a break price above the deal price, so
it is the only one that announces itself.

---

## Cross-cutting COVERAGE findings

### C1 · The feed cannot see any deal announced in the last 34 days — COVERAGE

`EDGAR_QUERIES` hardcodes its search windows:

```
startdt=2024-01-01&enddt=2026-06-30
startdt=2025-06-01&enddt=2026-06-30
startdt=2025-10-01&enddt=2026-07-24
```

The newest detectable announcement is **2026-07-24**. Today is 2026-08-27, so
there is a 34-day blind spot that widens by one day per day. No deal announced
since late July can enter the feed at all, and nothing in the product says so.

This is the highest-severity COVERAGE finding in the report: it is not a field
that cannot be populated for one deal, it is a whole cohort of deals that cannot
be detected.

### C2 · Outside dates exist for 11 of 12 but only 4 are cached — COVERAGE

> **WITHDRAWN.** This was read off the local cache. Production carries 11 of 12
> outside dates — see the Results section. The table below is still a correct
> record of what each agreement says; the "In the feed?" column is not.

Reading every deal's EX-2 exhibit directly today:

| Deal | Outside date | Extension | In the feed? |
|---|---|---|---|
| SLAB | 2028-02-04 | automatic | yes |
| GSAT | 2028-04-13 | automatic | **no** |
| CZR | 2027-11-27 | automatic | yes |
| APGE | 2027-06-18 | automatic | yes |
| PAYO | 2027-06-12 | automatic | **no** |
| WBD | 2027-06-04 | automatic | **no** |
| AES | 2027-06-01 | automatic | **no** |
| GBTG | 2027-02-02 | automatic | **no** |
| OGN | 2027-01-26 | elective | **no** |
| NATH | 2026-10-20 | automatic | yes |
| GBCS | 2026-08-31 | none | **no** |
| ALOT | none found | — | — |

Eleven of twelve are readable. Four are in the feed. The other seven are absent
not because the data does not exist but because their cached agreement markers
were never cleared in production — the issue raised when
`/api/admin/clear-agreement-markers` was added. **This is the single highest-value
item in this report per unit of effort: seven contractual deadlines, already
extractable, already quote-backed, sitting behind a stale marker.**

### C3 · No regulatory status exists for any deal — COVERAGE

Every deal carries `reg_tags`, and every tag is a prior computed from deal size
and sector at detection (F4). Across all twelve there is no HSR filing date, no
HSR expiration, no second request, no timing agreement, no consent decree, and
no shareholder vote date. A deal that has cleared antitrust and one facing a
second request carry identical tags.

This is the milestone detection the roadmap identifies as its biggest unlock
(§12), and it blocks §11, §16 and §17.

### C4 · No contract reading carries a section number — COVERAGE

Every commitment reading and every outside date is quote-backed, which is more
than most screens do. None carries the section it came from. GBCS's outside date
is in §9.01(b); the product can show the sentence but not the citation, so a
reader cannot navigate from the claim to the agreement. This is §7.

### C5 · SLAB is verified but absent from the cache — COVERAGE

> **WITHDRAWN.** SLAB is in production with a full reading. Same error as C2:
> the local cache is not the product.

SLAB (Silicon Laboratories / Texas Instruments, $7.5B) passes the verification
gate and yields a full agreement reading — outside date 2028-02-04, automatic,
$499M reverse fee at 6.7%. It has no row in `meridian_cache.csv`, so none of
that reaches the feed. It is the twelfth deal in name only.

### C6 · "No reverse fee exists" is indistinguishable from "not read" — COVERAGE

OGN is the one deal of twelve whose agreement yields no reverse termination fee.
The deal page renders no RTF row, which is the same thing it renders when the
exhibit was never fetched. A reader cannot tell that OGN's buyer is
contractually unbound rather than merely unexamined — and for OGN, whose
extension is the only *elective* one in the feed, that combination is exactly
what a reader needs to know.

---

## Per-deal findings

### 1 · GSAT — Amazon / Globalstar, $11.6B

| Check | Result |
|---|---|
| Break price | $72.89, 11.1% below current. No sign anomaly. F1, F7 |
| Probability | 53.4%. Plausible on its face; rests on F1 |
| Risk score | 47 / High. Driven by the 9.72% spread (F3) |
| Freshness | **D6** — 40h old |
| Contract | RTF $592M at 5.1%, STRONG. Outside date 2028-04-13 readable, **not in feed (C2)** |
| Regulatory | HSR + FTC-high priors only (F4, C3) |
| Sources | Quote-backed, no section number (C4) |
| Formula | `tx_value` 11.6 is `verified_hardcode` — correct, and unaffected by the override fix |
| Edge case | **D4** — dropped from the live feed twice during local scans |

**D4 · GSAT ages out of the rolling carry — DATA.** Two local scans on 2026-08-27
produced ten deals, not eleven, dropping GSAT both times. Its cached row was
39.7h old against `ROLLING_CARRY_MAX_AGE_HOURS = 36`, so it aged out. Its
announcement (2026-04-14) sits inside the search windows, so the scan should
re-detect it; it did not. A $11.6B deal leaving the feed silently is the failure
mode the rolling carry exists to prevent.

### 2 · WBD — Paramount / Warner Bros. Discovery, $110B

| Check | Result |
|---|---|
| Break price | $28.80 against a $28.90 current. Numerator collapses to $0.10 (AUDIT #9) |
| Probability | 4.5% — a 7.27% spread reported as near-certain failure. F1, F2 |
| Risk score | 50 / Medium |
| Freshness | **D6**, and **D7** below |
| Contract | RTF $7.0B, STRONG. Outside date **2027-06-04**, automatic — readable, **not in feed (C2)** |
| Regulatory | HSR + FTC-high priors. Full FTC review is real but untracked (C3) |
| Sources | Quote-backed, no section number (C4) |
| Formula | **D2** below |
| Edge case | Largest deal in the feed and the one whose probability is least meaningful |

**D2 · The Q3 2026 close guidance is stale — DATA.** WBD's `close_date` reads
`Q3 2026`, which ends in 34 days. The deal was announced 2026-02-27, is $110B,
faces a full FTC review, and carries a $7B *regulatory* termination fee. Its own
merger agreement sets an End Date that **automatically extends to June 4, 2027**
— 247 days beyond the guidance the screen displays.

A company guiding to Q3 2026 while signing an agreement that contemplates June
2027 was guiding optimistically at signing; six months on with antitrust
unresolved, that guidance is almost certainly stale. The hardcoded 180-day
divisor was masking this — with the divisor removed, WBD annualizes at 78%,
which is arithmetically correct and financially meaningless.

**Needs a decision** — see *Decisions needed*.

**D7 · The cached `tx_value` predates its own fix — DATA.** The cache still
carries 77.72 / `equity_calc_approx`. `resolve_tx_value` (commit `b798bd6`)
returns 110.0 / `verified_hardcode`, but no scan has run in production since, so
the RTF percentage still displays 9.0% rather than 6.4%. Self-clearing on the
next scan; listed because it is live right now.

### 3 · GBCS — Black Pearl / Selectis Health, $20M

| Check | Result |
|---|---|
| Break price | $3.20, **41.0% below current**. The largest modeled drawdown in the feed. F1, F7 |
| Probability | 87.1% / "High" |
| Risk score | **82 / Very Low** — see D3 |
| Freshness | **D6** |
| Contract | RTF $400,000 at 2.0%, WEAK (correct since `817f6be`). Outside date **2026-08-31** — **four days away**, **not in feed (C2)** |
| Regulatory | "Standard Review" only — below the HSR threshold, correctly |
| Sources | Quote-backed; §9.01(b) known but not carried (C4) |
| Formula | `ann` correctly suppressed — `close_date` is TBD |
| Edge case | **D3** |

**D3 · A deal four days from its contractual deadline is scored Very Low risk —
DATA.** GBCS's agreement reads: *"if the Acceptance Time shall not have occurred
on or before August 31, 2026 (the 'Outside Date')"* — §9.01(b), no extension
clause of any kind. Four days from today.

The feed shows: expected close **TBD**, no outside date, risk **Very Low**, score
82 — the second-highest in the feed. The score cannot see the outside date
because the score does not take it as an input (F3), and the outside date is not
in the feed at all (C2). A deal with a fixed deadline expiring this week, a 41%
modeled drawdown, and a 2.0% reverse fee is presented as the safest thing on the
screen bar one.

This is the clearest demonstration in the report that C2 is not a cosmetic gap.

### 4 · CZR — Fertitta Entertainment / Caesars, $17.6B

| Check | Result |
|---|---|
| Break price | $28.78, 2.9% below current — a thin cushion on a $17.6B deal. F1, F7 |
| Probability | 39.6% |
| Risk score | 56 / Low |
| Freshness | **D6** |
| Contract | RTF $450M at **2.6% — WEAK**, below the 3% threshold. Outside date 2027-11-27, automatic, in feed |
| Regulatory | HSR + FTC-high priors (F4, C3) |
| Sources | Quote-backed, no section number (C4). Its EX-2 is one of two reachable only via the index-page fallback |
| Formula | Expected close resolves *after* the outside date — see **Decision 2** |
| Edge case | Its `index.json` omits its own documents |

### 5 · NATH — Smithfield Foods / Nathan's Famous, $450M

| Check | Result |
|---|---|
| Break price | $91.82, 6.1% below current. F1, F7 |
| Probability | 59.2% |
| Risk score | 78 / Very Low |
| Freshness | **D6** |
| Contract | RTF $7M at **1.6% — WEAK**. Outside date 2026-10-20, automatic, in feed |
| Regulatory | HSR prior only |
| Sources | Quote-backed, no section number (C4) |
| Formula | Expected close (H2 2026) resolves after the outside date — **Decision 2** |
| Edge case | 217 days since announcement, the oldest in the feed, with 54 days to its deadline |

### 6 · PAYO — Nuvei / Payoneer, $3.0B

| Check | Result |
|---|---|
| Break price | $6.75, 5.3% below current. F1, F7 |
| Probability | 55.4% |
| Risk score | 74 / Low |
| Freshness | **D6** |
| Contract | RTF $165M at 5.5%, STRONG. Outside date 2027-06-12, automatic — **not in feed (C2)** |
| Regulatory | HSR + FTC-medium + concentration priors (F4, C3) |
| Sources | Quote-backed, no section number (C4) |
| Formula | Expected close (mid-2027) resolves 18 days after the outside date — **Decision 2** |
| Edge case | Its exhibit is the zero-padded `dp248400_ex0201.htm` that the name regex had to be widened for |

### 7 · AES — GIP / EQT consortium / AES Corp, $10.7B

| Check | Result |
|---|---|
| Break price | **$16.87, above both current ($14.73) and deal ($15.00)** — **D1** |
| Probability | Correctly **gated** since `b798bd6`; was 99.9% beside a red "Distressed" label |
| Risk score | 63 / Low |
| Freshness | **D6** |
| Contract | RTF $588M at 5.5%, STRONG. Outside date 2027-06-01, automatic — **not in feed (C2)** |
| Regulatory | HSR + DOJ-high priors (Utilities) (F4, C3) |
| Sources | Quote-backed, no section number (C4) |
| Formula | Position-size sign error fixed this session; was printing a $3,632 gain as a loss |
| Edge case | The only deal that announces its own break-price contamination |

**D1 · The break price is the peak of a pre-announcement run-up — DATA.** See
**F7** for the price series. $16.87 is the 2026-02-27 close, the last before the
8-K, and the highest print in four months. The stock fell 17.8% the next
session. **Needs a decision** — see *Decisions needed*.

### 8 · OGN — Sun Pharma / Organon, $3.7B

| Check | Result |
|---|---|
| Break price | $11.23, 18.4% below current. F1, F7 |
| Probability | 91.0% / "Very High" |
| Risk score | 67 / Low |
| Freshness | **D6** |
| Contract | **No reverse termination fee in the agreement (C6)** — the only such deal. Outside date 2027-01-26, **elective** — the only elective one — **not in feed (C2)** |
| Regulatory | HSR + FTC-medium + concentration priors (F4, C3) |
| Sources | Quote-backed, no section number (C4) |
| Formula | Expected close (early 2027) resolves after the outside date — **Decision 2** |
| Edge case | An elective extension means the **base** date governs, which makes its absence from the feed more consequential than the others' |

### 9 · GBTG — Long Lake / Global Business Travel, $6.3B

| Check | Result |
|---|---|
| Break price | $5.93, **37.3% below current**. F1, F7 |
| Probability | **99.2%** — a near-certainty produced by the size of the gap to the break price, not by deal evidence (F2) |
| Risk score | 65 / Low |
| Freshness | **D6** |
| Contract | RTF $270M at 4.3%, STRONG. Outside date 2027-02-02, automatic — **not in feed (C2)** |
| Regulatory | HSR + FTC-high priors (F4, C3) |
| Sources | Quote-backed, no section number (C4) |
| Formula | `financing_signal` is `contingent` from the press release while the agreement was read separately (F6) |
| Edge case | 0.32% spread with a 37% modeled drawdown — the worst risk/reward ratio in the feed, presented as Low risk |

### 10 · APGE — AbbVie / Apogee Therapeutics, $10.9B

| Check | Result |
|---|---|
| Break price | $90.38, **33.0% below current**. F1, F7 |
| Probability | **99.4%** — same mechanism as GBTG (F2) |
| Risk score | 76 / Very Low |
| Freshness | **D6** |
| Contract | RTF $381M at 3.5%, STRONG. Outside date 2027-06-18, automatic (period-stated), in feed |
| Regulatory | HSR + FTC-high + concentration priors (F4, C3) |
| Sources | Quote-backed, no section number (C4) |
| Formula | `ann` correctly suppressed — `close_date` is TBD |
| Edge case | Its automatic extension is stated as "six (6) months" with no date; the base date is 2026-12-18 |

### 11 · ALOT — Arcline / AstroNova, $270M

| Check | Result |
|---|---|
| Break price | $16.69, **42.4% below current** — the largest gap in the feed. F1, F7 |
| Probability | **99.9%**, the maximum the feed produces (F2) |
| Risk score | **88 / Very Low** — the highest score in the feed |
| Freshness | **D6** |
| Contract | RTF $10M at 3.6%, STRONG. **No outside date readable — D5** |
| Regulatory | HSR prior only |
| Sources | Quote-backed, no section number (C4) |
| Formula | 0.03% spread — effectively closed, and `ann` of 0.32% reflects that correctly |
| Edge case | Highest score, highest probability, largest modeled drawdown, no deadline |

**D5 · No outside date is readable from ALOT's agreement — DATA.** The only deal
of twelve where the extractor returns nothing. Whether the agreement genuinely
omits a termination date or the extractor missed a phrasing is not established
here; it needs the exhibit read by hand. Until then it is indistinguishable
from the seven deals whose dates exist but are not cached (C2), which is the
C6 problem in a different field.

### 12 · SLAB — Texas Instruments / Silicon Laboratories, $7.5B

| Check | Result |
|---|---|
| Break price | **not computed — no cache row (C5)** |
| Probability | not computed (C5) |
| Risk score | not computed (C5) |
| Freshness | n/a — never written |
| Contract | RTF $499M at 6.7%, STRONG. Outside date 2028-02-04, automatic, two chained extensions. All readable today |
| Regulatory | none computed (C5) |
| Sources | Quote-backed on direct read; nothing rendered |
| Formula | n/a |
| Edge case | Passes the verification gate, reads cleanly, and reaches no user |

---

## Feed-wide DATA finding

**D6 · The whole feed is 40 hours stale, past its own carry threshold — DATA.**
Every row carries `fetched: 2026-08-26T04:0x`. As of this check that is ~40
hours, against `ROLLING_CARRY_MAX_AGE_HOURS = 36` — the threshold at which the
code's own rule says a deal should be dropped rather than carried. The product
displays no freshness indicator (§8), so a reader sees prices, spreads and
probabilities with nothing to say when any of it was last true. The `cp` field
is a daily close in the first place (AUDIT #1), so the true staleness is worse
than the timestamp suggests.

---

## Decisions needed

Three findings need a judgment call rather than a fix. Each is presented with
both readings.

### Decision 1 · What should AES's break price be?

The cached $16.87 is wrong under either reading — the disagreement is only about
what replaces it, and the two candidates land within $0.12 of each other.

**Reading A — the lookback picked a contaminated day.** The genuine unaffected
price is the pre-run-up level, ~$13.75 (late January 2026, before the four-week
climb). The deal is then a 9% premium to unaffected, and everything normalises:

```
bp = 13.75   downside -6.65%   probability 78.4%   model applies
```

**Reading B — take the market's own post-announcement verdict.** The stock
settled at ~$13.87 immediately after the 8-K, which is where it traded once the
deal terms were known. That is arguably a better estimate of where it goes on a
break than any pre-announcement price:

```
bp = 13.87   downside -5.84%   probability 76.1%   model applies
```

The two differ by 2.3 points of probability. What matters is that both refute
$16.87. **My recommendation is A** — it is the definition the field already
claims ("unaffected price") and it generalises to every deal, whereas B only
exists for deals that have already announced. But B is the more honest estimate
of break behaviour and is worth considering as the §4 basis.

### Decision 2 · Should expected close be a point or an interval?

Four deals — CZR, NATH, PAYO, OGN — now show an expected close **after** their
contractual outside date:

| Deal | Guidance | Resolves to | Outside date | Apparent gap |
|---|---|---|---|---|
| NATH | H2 2026 | 2026-12-31 | 2026-10-20 | -72d |
| OGN | early 2027 | 2027-03-31 | 2027-01-26 | -64d |
| CZR | mid-to-late 2027 | 2027-12-31 | 2027-11-27 | -34d |
| PAYO | mid-2027 | 2027-06-30 | 2027-06-12 | -18d |

**This is not four data errors, and it would be a mistake to record it as such.**
Every one of those outside dates falls *inside* the period management guided to:
Oct 20 is in H2 2026, Jan 26 is in early 2027, Nov 27 is in late 2027, Jun 12 is
mid-2027. The guidance and the contract agree. The contradiction is manufactured
by the parser I changed this week, which collapses a period to its **last day**.

The end-of-period convention was chosen deliberately for risk-conservatism — it
never understates time at risk. It also guarantees this appearance whenever a
contractual deadline sits inside a guided period, which is the normal case.

**Option A — keep the point estimate at period end.** Simple, conservative,
already shipped. Accept that expected close will frequently print after the
outside date, and suppress or annotate the comparison.

**Option B — carry the interval.** Store `(earliest, latest)` and render
"H2 2026" as the range it is. The annualized spread then has a range too, which
is more honest and more work, and §19 confidence levels would consume it
naturally.

**Option C — annualize against the outside date instead.** The contractual
deadline is a hard fact where the guidance is an adjective (AUDIT #6). For NATH
this changes the annualized figure from 12.28% to 28.7% — a very different
trade. Arguably the most defensible number in the product, and it is available
for 11 of 12 deals the moment C2 is cleared.

I have not picked one because the choice changes the headline number on every
deal, and because C2 must be resolved first for option C to be possible at all.

### Decision 3 · Is GBCS four days from resolution, or four days from trouble?

GBCS's outside date is 2026-08-31 with no extension clause. Either the deal
closes this week, or on 1 September either party can walk with a $400,000 fee
against a $20M deal. The feed says expected close TBD and risk Very Low.

The QA finding (D3) is that the product cannot see this at all. What it *means*
is a judgment about the deal, not about the code: a tender offer four days from
a fixed deadline with the stock at $5.42 against $5.75 is either about to
complete or about to lapse, and nothing in the filings read here settles which.
Worth a hand check before the date passes, because it is the one finding in this
report with an expiry.

---

## What to fix first

Ordered by value per unit of effort, not by severity.

1. **C2 — clear the agreement markers in production.** Seven contractual
   deadlines, already extractable, already quote-backed, behind a stale marker.
   The endpoint exists. This is the cheapest large gain available and it is what
   makes D3 and Decision 2 option C possible.
2. **C1 — the 34-day detection blind spot.** A dated constant. Until it moves,
   the feed silently stops seeing new deals.
3. **D1 / F7 — the break-price lookback.** Decision 1 first, then §4.
4. **D4 — GSAT leaving the feed.** A $11.6B deal disappearing silently.
5. **D2 — re-source expected close** from the latest filing rather than the
   announcement, per AUDIT #6.

Everything else waits on §4 or on milestone detection, which the roadmap already
sequences correctly.

---

# Results — EDGAR window, and three decided items

Applied 2026-08-27, after the report above.

## Correction to C2, from production

**C2 as written is wrong.** It claimed outside dates were cached for only 4 of
12 deals. That was read off the local cache, which had diverged. Production
returns **12 deals with 11 outside dates** — every marker had been cleared and
rescanned:

```
AES  2027-06-01 automatic   ALOT  none          APGE 2027-06-18 automatic
CZR  2027-11-27 automatic   GBCS  2026-08-31 fixed      GBTG 2027-02-02 automatic
GSAT 2028-04-13 automatic   NATH  2026-10-20 automatic  OGN  2027-01-26 elective
PAYO 2027-06-12 automatic   SLAB  2028-02-04 automatic  WBD  2027-06-04 automatic
```

C5 is also wrong on the same evidence: SLAB **is** in production, with a full
reading. Both findings came from checking the local cache instead of the live
feed, which is the error the method section warned against and which I made
anyway. The local cache is not the product.

What survives: ALOT still has no outside date (**D5**), and OGN's is the only
elective one (**C6** stands — its absent RTF is still indistinguishable from an
unread one).

One thing production *does* show: `ann` still carries the 180-day constant
(GBCS 12.35 = 6.09 × 2.028), so the deployment predates `b798bd6`. The
annualization fix is committed but not live.

## 1 · The EDGAR search window rolls — C1 fixed

`EDGAR_QUERIES` became `EDGAR_QUERY_PHRASES` plus `edgar_queries()`, which
computes the window per scan rather than at import — so a process that stays up
for weeks cannot drift back into the same blind spot a day at a time.

**`enddt`** is now today + 1. The buffer is not cosmetic: EDGAR timestamps in
Eastern time while the scan computes in UTC, so for several hours a day a bare
"today" excludes filings that are already public.

**`startdt` had the mirror-image problem, and it is worth naming separately.**
It was fixed at 2024-01-01 (four queries), 2025-06-01 and 2025-10-01. Those
never went stale in the sense of missing new filings — they went stale by
*widening forever*, spending a fixed 300-result budget on filings that the age
gate discards on arrival. It is now `today - 548` days, which is not an
arbitrary number: it is the same horizon as the `days > 548` gate that drops any
deal as "likely closed". Aligning the two is lossless, because anything outside
it was being thrown away after being fetched.

The scan now logs its window, so a future drift is visible rather than silent:

```
[Scan] EDGAR window 2025-02-25 -> 2026-08-28 (548d lookback, matching the age gate)
```

### What the blind spot was hiding

A scan with the corrected window returned **19 deals against the 12 known** —
**eight new**, and the filing dates say plainly what had been happening:

| Ticker | Company | Acquirer | Filed | Spread | Inside the old window? |
|---|---|---|---|---:|---|
| HZO | MarineMax | Safe Harbor | 2026-08-10 | 1.55% | **no** |
| BWMN | Bowman Consulting | Bernhard Capital | 2026-08-10 | 1.13% | **no** |
| BZH | Beazer Homes | Dream Finders | 2026-08-07 | 0.84% | **no** |
| ATKR | Atkore | Prysmian S.p.A | 2026-08-03 | 1.43% | **no** |
| BOW | Bowhead Specialty | undisclosed | 2026-08-03 | 1.22% | **no** |
| CBZ | CBIZ | undisclosed | 2026-07-29 | 0.60% | **no** |
| DSGR | Distribution Solutions Group | undisclosed | 2026-07-16 | 0.49% | yes |
| RAMP | LiveRamp | Publicis Groupe | 2026-05-18 | 1.99% | yes (DEFM14A path) |

**Six of the eight were announced after 2026-07-24** and could not have been
detected at all. That is the blind spot, populated: roughly one deal a week for
five weeks, none of which reached the feed, with nothing logged and nothing
failing.

DSGR and RAMP were inside the old window and missed for other reasons — RAMP
arrives through the DEFM14A proxy path, whose window was the one that stopped at
2026-07-24. Their appearance is a bonus of the widened `startdt`, not of the
`enddt` fix.

Three of the eight (BOW, CBZ, DSGR) carry `Undisclosed` acquirers and no close
date, which is the ordinary review-queue path and not a defect in this change.

**These eight are candidates, not confirmed feed members.** They are subject to
the verification gate and the direction check like anything else, and both are
enforcing. What this scan establishes is that the deals exist, are priced, and
were previously unreachable. A gated scan run through the server confirmed
ATKR, BOW, BWMN and HZO reaching the cache mid-pass; the remaining four had not
resolved when this was written.

**One cost worth stating.** The 548-day `startdt` makes each scan noticeably
slower — the wider window pulls in a long tail of already-closed deals that are
fetched before being discarded as delisted, skipped for having no Item 1.01, or
rejected by the spread gate. That filtering works correctly, but it is work. If
scan duration becomes a problem, the lookback is the dial, and shortening it
trades detection depth for time. It should not be shortened below the 548-day
age gate without moving the gate too, or the two will disagree again in the
other direction.

## 2 · AES break price — D1 decided

`get_break_price` now consults `VERIFIED_UNAFFECTED_PRICES` before its lookback,
the way `get_break_price`'s siblings already consult `VERIFIED_ACQUIRERS` and
`VERIFIED_TX_VALUES`. AES is set to **$13.75**, and `break_price_method` reads
`verified_unaffected` rather than `historical`, because the provenance is
genuinely different and mislabelling it would repeat AUDIT #8's complaint about
the word "modeled".

The series that settles it — AES daily closes, January into February 2026:

```
01-12  13.54    01-20  13.28    01-28  14.65    02-03  15.71  <- breaks the range
01-13  13.48    01-21  13.74    01-29  14.51    02-04  15.37
01-14  13.51    01-22  14.09    01-30  14.30    02-05  15.22
01-15  13.93    01-23  13.75    02-02  14.38    02-06  15.67
01-16  13.69                                    02-27  16.87  <- taken as unaffected
                                                03-02  13.87  <- 8-K, -17.8%
```

A 13.28–14.39 range through January, a clean break above it on 2026-02-03 that
never reverts, and a 17.8% collapse on the announcement itself. $13.75 is the
2026-01-23 close: a real traded price, inside the quiet range, before the break.

The consequence is that AES's two-state model becomes readable again — break
$13.75 sits below both the $14.73 current and the $15.00 deal price, giving a
probability near 78% where the gate previously (correctly) refused to publish
one at all.

### Do other deals have the same pattern? — a check that did not produce a fix

Yes, and that is the problem. A 150-day scan comparing each deal's last
pre-filing close against the median of its own earlier window flags **seven of
twelve** as elevated into their announcement:

| Deal | baseline | last close | elevation |
|---|---:|---:|---:|
| ALOT | 9.30 | 16.69 | +79.5% |
| OGN | 7.42 | 11.23 | +51.3% |
| PAYO | 5.01 | 6.75 | +34.7% |
| WBD | 23.01 | 28.80 | +25.2% |
| AES | 13.54 | 16.87 | +24.6% |
| APGE | 72.69 | 90.38 | +24.3% |
| GSAT | 61.04 | 72.89 | +19.4% |
| CZR | 24.57 | 28.78 | +17.1% |

Widening the window to 400 days made it worse, not better: GSAT then reads a
240% "run-up" and WBD 187%, because both roughly tripled over a year on their
own news. **Price alone cannot separate deal speculation from business
momentum.** An automatic detector shipped against this evidence would replace
one wrong break price with a different wrong break price on most of the feed.

So `VERIFIED_UNAFFECTED_PRICES` holds exactly one entry, and the check above is
recorded here as a list of candidates for hand verification rather than as
logic. This is the same shape the project already uses by hand: `worksheet.csv`
records AMPS's premium as measured "to the Oct 15 2024 unaffected close, before
the strategic review announcement", and VOXX entered at $8.00 — a *negative*
premium to a $7.50 deal — because four months of a public process had already
lifted it off $2.85. What distinguishes those cases is a **filing** (a strategic
review, a sale process), not a price shape. Detecting them properly is a §4
problem and needs the filings, not the tape.

## 3 · Expected close capped at the deadline — Decision 2 decided

`cap_expected_close(close_date, outside)` bounds the expected close at the
contractual deadline and records `close_date_capped_to` when the cap binds.
`days_to_close` and `ann` are recomputed from the capped date.

It runs inside the agreement pass rather than at deal construction, because the
outside date is read from the EX-2 exhibit hundreds of lines later — when the
deal dict is built there is no deadline to bound anything against.

**Not applied to an elective deadline.** There the reported date is the *base*,
and a party may push it out, so guidance landing after it is not impossible.

| Deal | Guidance resolves to | Outside date | Result |
|---|---|---|---|
| NATH | 2026-12-31 | 2026-10-20 automatic | **capped to 2026-10-20** |
| CZR | 2027-12-31 | 2027-11-27 automatic | **capped to 2027-11-27** |
| PAYO | 2027-06-30 | 2027-06-12 automatic | **capped to 2027-06-12** |
| GBCS | 2026-09-30 | 2026-08-31 fixed | **capped to 2026-08-31** |
| OGN | 2027-03-31 | 2027-01-26 **elective** | not capped — base extends to 2027-04-26 |
| WBD | 2026-09-30 | 2027-06-04 automatic | unchanged |
| GSAT | 2027-12-31 | 2028-04-13 automatic | unchanged |
| AES | 2027-03-31 | 2027-06-01 automatic | unchanged |
| GBTG | 2026-12-31 | 2027-02-02 automatic | unchanged |
| APGE | 2026-09-30 | 2027-06-18 automatic | unchanged |
| ALOT | 2026-09-30 | none | unchanged |

Exactly the four impossible dates are removed. No deal whose guidance already
sat inside its deadline moves, which was the requirement: the headline number
changes only where it was impossible.

Worth restating, because it is the part most easily misread: **those four were
never four data errors.** Every one of those deadlines falls *inside* the period
management guided to — 20 October is in H2 2026, 27 November is in late 2027.
The guidance and the contract agreed all along. The impossibility was
manufactured by the end-of-period point estimate, and the cap removes it without
touching the conservative convention that produced it.

## 4 · GBCS — no fix, by decision

Left as it stands: outside date 2026-08-31, four days out, no extension clause,
scored 82 and labelled Very Low risk. The outcome will be the evidence.

Recording the argument it makes, because that is the point of leaving it:
**the risk score has no time input at all.** `score_deal` takes spread, deal
type, days *since* announcement, regulatory tags, break premium and financing
signal. Nothing about how long the deal has left. A deal four days from a fixed
contractual deadline and a deal four years from one score identically on that
axis, and GBCS is the case where that produces a visibly wrong answer: 82 is the
second-highest score in the feed.

Days-to-outside-date is the obvious missing factor, and it is now available for
11 of 12 deals. It belongs in §9's rebuild rather than as a patch to the current
weights, since adding a seventh unvalidated factor to six unvalidated factors
does not make the number more trustworthy. But GBCS is the argument for it, and
if the deal lapses on 1 September that argument gets stronger.

## Finding status after this pass

| | Status |
|---|---|
| **C1** EDGAR blind spot | **fixed** — window rolls, eight deals recovered |
| **C2** outside dates cached for 4 of 12 | **withdrawn** — wrong, production has 11 of 12 |
| **C5** SLAB absent | **withdrawn** — wrong, SLAB is in production |
| **D1** AES break price | **fixed** — $13.75, hand-verified |
| **D2** WBD stale guidance | open — capping does not reach it; its deadline is June 2027 |
| **D3** GBCS scored Very Low | **open by decision** — see above |
| **D5** ALOT no outside date | open — still needs a hand read of the exhibit |
| **D7** WBD `tx_value` | open until production deploys `b798bd6` |
| **F7** break-price lookback | open — AES patched by hand, mechanism unchanged, §4 owns it |
| Decision 2 | **decided** — cap, not denominator switch |

Two findings withdrawn on production evidence, two fixed, one closed by
decision. Sixteen of the twenty stand.
