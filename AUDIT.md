# §2 — Formula audit

Every metric the product computes or extracts, audited against the code as it
stands at `817f6be`. Findings only; no code changed.

For each metric: what it actually computes, whether it is mathematically
correct, whether it is financially meaningful, what it assumes, how it can
mislead, and what should replace it.

Values quoted are from the live cache (11 deals, fetched 2026-08-26T04:0x).

**Severity is about what a reader would conclude, not about how hard it is to
fix.**

| | meaning |
|---|---|
| **BROKEN** | produces a number that is wrong, not merely imprecise |
| **MISLEADING** | arithmetically fine, but the label promises something it does not deliver |
| **SOUND** | correct and meaningful within stated assumptions |

Six are BROKEN, six MISLEADING, seven SOUND. Four of the twelve defects trace
to a single root cause: **the break price is an unvalidated price lookup that
everything downstream treats as a modeled floor.**

---

## Summary table

| # | Metric | Verdict | One-line finding |
|---|---|---|---|
| 1 | Current price | MISLEADING | Last daily close, not a live price; labelled "current" |
| 2 | Deal price | SOUND | Cash-per-share only; non-cash deals silently mispriced |
| 3 | Gross spread | SOUND | Correct. The one formula with no caveat |
| 4 | Annualized spread | **BROKEN** | Hardcoded 180-day close for every deal |
| 5 | Days to close | **BROKEN** | "late 2026 or early 2027" parses to 31 Mar 2026 — the past |
| 6 | Expected close | MISLEADING | Free text from a press release, presented as a date |
| 7 | Outside date | SOUND | Filing-sourced, quote-backed, extension-classified |
| 8 | Break price | **BROKEN** | Unaffected close, dividend-adjusted, drifts every scan |
| 9 | Implied probability | **BROKEN** | Clamp converts a sign error into 99.9% + "Distressed" |
| 10 | Risk score | MISLEADING | Spread double-counted; 153-point range implies measurement |
| 11 | Regulatory risk | MISLEADING | Size-and-sector proxy, not regulatory status |
| 12 | RTF | SOUND | Read from the agreement with a quote |
| 13 | Target fee | SOUND | Same path as RTF |
| 14 | Fee multiple | MISLEADING | Ratio is sound; the % of deal value is not comparable |
| 15 | Transaction value | **BROKEN** | Enterprise and equity value mixed under one label |
| 16 | Financing status | MISLEADING | Press-release scan outranks the contractual reading |
| 17 | Antitrust obligation | SOUND | Ordered patterns, carve-out aware, quote-backed |
| 18 | Specific performance | SOUND | Same |
| 19 | Position sizing | **BROKEN** | Hardcoded minus sign inverts P&L when break > current |

---

## 1 · Current price (`cp`)

**Computes** — `main.py:1260`: `cp = float(h['Close'].iloc[-1])` from a
`period=5d` yfinance history.

**Mathematically correct** — Yes, for what it is: the most recent daily close.

**Financially meaningful** — Partly. It is a real traded price. It is not the
price anyone can transact at now, and the spread built on it is therefore a
historical spread, not a live one.

**Assumes** — that a daily close is close enough to a live quote for a screen
that refreshes hourly; that the last close is recent.

**Misleads** — over a weekend or holiday the "current" price is up to four days
old with no indication. The whole feed reprices only when a scan runs, so two
deals in the same table can carry closes from different days. `cp` is also the
input to spread, probability, downside and position sizing, so its staleness
propagates to every derived number without ever being disclosed.

**Replace with** — keep the daily close as the computation basis, but carry the
close's own date alongside it and render it. This is §8's LAST UPDATED, and it
is the cheapest honesty fix in the document. Where an intraday quote is
available, use it and say which one is shown.

---

## 2 · Deal price (`dp`)

**Computes** — regex extraction of cash-per-share consideration from the
announcement filing (`main.py:~1270-1345`), overridable by `VERIFIED_DEAL_TYPES`
and hand-verified tables.

**Mathematically correct** — Not an arithmetic question. Extraction correctness
per deal belongs to §25, not here.

**Financially meaningful** — Yes for all-cash deals, where consideration is a
scalar and the spread is well defined.

**Assumes** — that consideration is a fixed cash amount per share. The feed
carries a `Cash + Stock` deal type and the pricing module has blended-price
handling, but `dp` itself is one number.

**Misleads** — for any deal with a stock component, a single `dp` is a snapshot
of a moving value. The spread against it then moves with the acquirer's share
price rather than with deal risk, and nothing on the page says so. A collar, a
floating exchange ratio, or a CVR cannot be represented at all.

**Replace with** — keep the scalar for all-cash. For anything else, `dp` must
carry its consideration structure and a computed-as-of timestamp, and the
spread must be labelled as being against a floating value. Deals whose
consideration cannot be reduced to a number should say so rather than showing
one.

---

## 3 · Gross spread (`sp_pct`)

**Computes** — `main.py:1348`: `sp_pct = ((dp - cp) / cp) * 100`.

**Mathematically correct** — Yes. This is the return on capital if the deal
closes at `dp`, and dividing by `cp` rather than `dp` is the right choice: the
denominator is what a buyer actually puts up.

**Financially meaningful** — Yes.

**Assumes** — cash consideration, no dividends between now and close, no borrow
cost, no transaction costs, close at exactly `dp`.

**Misleads** — only by omission, and only through its inputs. A target paying a
dividend before close raises the real return above the printed spread; a
short-side borrow cost on a stock deal lowers it. Neither is modelled.

**Replace with** — nothing. This is the one formula in the audit that needs no
change. Add the dividend and financing adjustments as separate disclosed lines
rather than folding them into the headline number.

---

## 4 · Annualized spread (`ann`) — BROKEN

**Computes** — `main.py:1398`: `ann = (sp_pct / 180) * 365`.

**Mathematically correct** — The arithmetic is right. The 180 is not a
measurement of anything. It is the same constant for every deal in the feed.

**Financially meaningful** — No. An annualized return that ignores time to
close is not an annualized return; it is the gross spread multiplied by 2.028.

**Assumes** — that every merger closes in exactly 180 days.

**Misleads** — badly, and in the direction that flatters. The whole purpose of
annualizing is to make a 6% spread closing in 30 days comparable to 6% closing
in 300, which is §13's point exactly. This formula destroys the distinction it
exists to create, and then prints the result as a percentage per year:

| Deal | Spread | `ann` printed | Stated close | Days out | Honest annualized |
|---|---:|---:|---|---:|---:|
| GSAT | 9.72% | **19.70%** | 2027 | 307 | 11.6% |
| CZR | 4.52% | **9.16%** | mid-to-late 2027 | 307 | 5.4% |
| NATH | 4.24% | **8.60%** | H2 2026 | 126 | 12.3% |

Any deal closing later than 180 days is overstated by exactly `days/180` — GSAT
and CZR both by 1.70x, because the parser resolves both to the same June 2027
date. Anything closing sooner is understated: NATH by 0.70x. The distortion is
therefore not noise but a systematic tilt toward deals with long timelines,
which are precisely the ones a merger-arb desk should discount.

It also inverts the ranking. Under `ann` these three order GSAT, CZR, NATH.
Corrected, they order NATH, GSAT, CZR — the deal the screen ranks last is
actually the best of the three on return per unit time. The irony is that the
UI already has `_daDaysToClose`
(`templates/index.html:1989`) and simply does not feed it here.

**Replace with** — `sp_pct * 365 / days_to_close`, using the parsed expected
close, and only where a close date exists. Where it does not (GBCS, APGE both
carry `TBD`), print no annualized figure rather than a default. Better still,
annualize against the outside date as a worst case alongside the expected case
— that pair is far more informative than either alone, and the outside date
already exists for four deals.

**Depends on** — #5 and #6 being fixed first. Annualizing against a broken
close date substitutes one wrong number for another.

---

## 5 · Days to close — BROKEN

**Computes** — `templates/index.html:1971-1993`: `_daParseCloseDate` regexes a
year out of the free-text `close_date`, then maps a keyword to a month.

**Mathematically correct** — No. Two independent defects:

*The year and the keyword are taken from different halves of the string.* The
year regex `/(20\d{2})/` takes the **first** year in the text. The keyword
chain tests `/early/` before `/mid/` before `/late/`. AES carries
`late 2026 or early 2027`:

```
year  <- "2026"   (first match)
month <- /early/  (matches "early 2027")  -> 31 March
result: 31 March 2026 — five months in the PAST
```

That date matches neither reading of the source text. `_daDaysToClose` then
returns a negative number for a live deal.

*Ranges collapse to their earliest interpretation.* CZR's `mid-to-late 2027`
hits `/mid/` and resolves to 30 June 2027, discarding "late" — roughly five
months of time at risk, silently removed.

**Financially meaningful** — It would be, if correct. Time to close is the
denominator of every return-per-unit-time judgment a merger-arb desk makes.

**Assumes** — that a quarter or half-year phrase can be reduced to a point
estimate, and that the point should be the period's end (`Q3` -> 30 Sep). That
convention is defensible. Taking a range's early end is not.

**Misleads** — a past-dated expected close on a live deal reads as a deal
already overdue. Combined with #4, it is the input that would fix the
annualized spread, so it must be right first.

**Replace with** — parse to an interval, not a point: `(earliest, latest)`.
Bind the year to the keyword that produced the month by matching them as a
single token (`early 2027`, `late 2026`), not independently across the string.
For a range, keep both ends and show the later one for risk purposes. Where the
text yields no interval, return null and let callers print nothing.

---

## 6 · Expected close (`close_date`)

**Computes** — `extract_close_date(full_ct)` over announcement text, with a
tender-offer expiration lookup and a `VERIFIED_CLOSE_DATES` override.

**Mathematically correct** — Not arithmetic. It is a string.

**Financially meaningful** — Weakly. Values in the live cache are `2027`,
`Q3 2026`, `mid-to-late 2027`, `H2 2026`, `late 2026 or early 2027`,
`second half 2026`, `early 2027`, `TBD` (x2). These are management's public
aspiration at announcement, not a forecast and not a contractual date.

**Assumes** — that the company's stated expectation at signing is still
operative months later. Nothing re-reads it.

**Misleads** — it is presented with the same visual weight as the outside date,
which is a contractual deadline read out of the agreement with a quote. One is
a fact; the other is a press-release adjective. §20 exists precisely for this
distinction and this field is its clearest violation. Two of eleven deals carry
`TBD` and therefore have no time axis at all.

**Replace with** — keep the extraction, but re-source it: the most recent
10-Q/8-K language, not the announcement. Label it MANAGEMENT GUIDANCE with its
as-of date, visually subordinate to the outside date. Where it is `TBD`, say
"not disclosed" rather than leaving a blank that reads as missing data.

---

## 7 · Outside date — SOUND

**Computes** — `outside_date.py`. Tiered patterns over the EX-2 merger
agreement, extension clauses classified automatic vs elective, periods applied
as calendar months.

**Mathematically correct** — Yes, and the date arithmetic is deliberately
calendar-based rather than 30.44-day approximated, because a one-day error
changes whether a deadline has passed.

**Financially meaningful** — Yes. It is the hardest date in the contract and
the only one with a consequence attached.

**Assumes** — that the latest automatic extension is the operative deadline and
an elective one is not, which is the conservative reading: automatic arrives
without anyone acting, elective may never arrive at all.

**Misleads** — one live gap. Only four of twelve deals carry a date, and the
other eight show nothing. A reader cannot distinguish "this agreement sets no
outside date" from "we could not read one," which is the same failure mode §7
identifies for commitment terms. The reading is also quote-backed but not
section-numbered.

**Replace with** — nothing structural. Add the read-attempted-and-found-nothing
state so absence is explicit, and carry the section number (§8.01(c)) with the
quote. Both are §7 work, not §2.

---

## 8 · Break price (`break_price`) — BROKEN

**Computes** — `get_break_price` (`main.py:~658`): the last daily close in a
7/14/21/30-day window ending on the filing date. `break_price_method` is
hardcoded to `'historical'` immediately after. All 11 live deals carry
`historical`.

**Mathematically correct** — As a lookup, yes. As a *break price*, it is not a
model at all — it is the unaffected price with a different name.

Three defects compound:

*It is dividend-adjusted, and the adjustment moves.* yfinance 1.5.1 defaults
`auto_adjust=True` (verified). Historical closes are back-adjusted for every
dividend since. `break_price` is re-fetched on every scan, so for a
dividend-paying target the modeled break **drifts downward over the life of the
deal** with no filing, no news, and no disclosure. `cp` sits at the unadjusted
end of the same series. The subtraction `cp - break_price` therefore mixes two
different adjustment bases.

*The fallback formula is algebraically inert.* `calculate_break_price` method 2
(`main.py:~669`):

```
bp = cp - (dp - cp) * (1 / spread_pct)
```

Since `dp - cp = cp * spread_pct / 100` by definition, this reduces to:

```
bp = cp - cp/100 = 0.99 * cp
```

It returns 1% below the current price for every input, always, and labels the
result `spread_regression`. No live deal uses this path today because the
historical lookup succeeds — it is a landmine, not an active fire.

*It can exceed the deal price.* AES carries `break_price` 16.87 against `dp`
15.00 — a deal supposedly struck 11% *below* the unaffected price. That is
implausible on its face and points at either a wrong `dp`, a filing date that is
not the announcement date, or the adjustment above. Diagnosing which is §25
work, but §2's finding stands: nothing validates the relationship
`break < current` or `break < deal`, and both are violated in production.

**Financially meaningful** — No. A pre-announcement price is where the stock
traded before the deal existed. Where it trades *after* a break is a different
question: the company has burned months, spent fees, possibly lost customers,
and the sector has moved. §4 lists ten inputs that belong in this estimate. The
current implementation uses one, and not one of the ten.

**Assumes** — that the target's standalone value is unchanged since
announcement, and that the market's pre-deal valuation is the right anchor.

**Misleads** — it is rendered as "Modeled downside case" under a large dollar
figure (`templates/index.html:2128`). "Modeled" is a claim this number cannot
support. Everything downstream — probability, downside %, position sizing, and
the premium sub-score — inherits the error.

**Replace with** — §4. In the interim the honest minimum is to rename it
"unaffected price," drop the word "modeled," delete the inert
`spread_regression` fallback, and add the sanity gates: refuse to publish a
break price at or above `min(cp, dp)`, and pin the adjustment basis so it does
not drift between scans.

---

## 9 · Market-implied probability — BROKEN

**Computes** — `main.py:~2949`:

```
prob = round(((cp - bp) / (dp - bp)) * 100, 1)
prob = max(0, min(99.9, prob))
if cp < bp:  -> returns prob with signal "Distressed"
```

**Mathematically correct** — The formula is the standard two-state solve and is
correct *given a real break price*. The implementation around it is not.

*The clamp hides sign errors instead of catching them.* AES:

```
raw     = ((14.73 - 16.87) / (15.00 - 16.87)) * 100 = 114.4%
clamped = min(99.9, 114.4)                          =  99.9%
cp < bp = True                                      -> "Distressed", red
```

The live site shows **99.9% probability of closing** next to a red
**"Distressed"** label, on the same deal, from the same function. Both signs
cancelled in the fraction, the clamp swallowed the evidence, and the result is
maximal confidence and maximal alarm simultaneously. A reader cannot tell which
to believe, and neither is right.

*The near-zero numerator case is separate.* WBD: `cp - bp` = $0.10 against a
healthy $2.20 denominator, giving 4.5% — a 7% spread reported as a deal the
market thinks will almost certainly fail. This is the §3 example, and the
mechanism is the numerator collapsing, not the denominator.

**Financially meaningful** — Only under a strict two-state model: the deal
closes at `dp` or breaks to `bp`, nothing else, no time value. Real outcomes
include renegotiation at a lower price, a topping bid, and a remedy-encumbered
close — which is §5.

**Assumes** — two outcomes, a correct break price, risk-neutrality, and no
discounting. The first and second are both false here.

**Misleads** — it is the most authoritative-looking number on the page and the
least supported. Four of eleven deals sit above 99% (AES 99.9% via the clamp,
ALOT 99.9%, APGE 99.4%, GBTG 99.2%) purely because their break prices are far
below current — which is a statement about the lookup window, not about deal
risk.

**Replace with** — three changes, in order. **(a)** Delete the clamp and treat
out-of-range as a hard gate: if `cp <= bp` or `dp <= bp`, the two-state model
does not apply and no probability is published — §3 says this explicitly.
**(b)** Publish only once §4 gives a defensible break price. **(c)** Frame the
output as a range implied by a break-price range, never a point estimate to one
decimal. "82%" claims a precision that 39 deals with 4 breaks cannot support.

---

## 10 · Risk score (`score`, `risk`)

**Computes** — `score_deal` (`main.py:578`) sums six components onto a base of
50, then normalizes: `((score + 35) / 153) * 100`. `get_risk` maps
`(spread, score)` to Very Low / Low / Medium / High.

**Mathematically correct** — Yes, and better than expected. The normalization
bounds are exactly right: the true achievable range is `[-35, 118]`, matching
the constants. Component maxima sum to 118 (50 + 25 + 10 + 10 + 5 + 8 + 10) and
minima to -35 (50 - 35 + 0 - 15 - 20 - 5 - 10). One edge case: a spread of
exactly 0.0 matches no branch and receives no adjustment.

**Financially meaningful** — Weakly, and less than the number implies.

*Spread is double-counted.* The spread term spans +25 to -35, which is 60 of
the 153-point range — 39% of the score. `get_risk` then re-applies spread as the
**primary gate**: `spread >= 12` returns High unconditionally, and score only
breaks ties in the 8-12 band. So the risk label is largely a relabelling of the
spread, and the score's other five factors barely reach it.

*The weights are unvalidated.* §9 already records that 39 verified deals with 4
failures could not validate the six factors in place. A 0-100 output implies a
measurement that has not been made.

**Assumes** — that these six factors are the right ones, that their relative
weights are known, and that they combine additively.

**Misleads** — "Score 82, Very Low risk" reads as calibrated. GBCS scores 82
(Very Low) on a deal whose modeled break implies a 41% drawdown and whose
transaction value is an approximation. The score cannot see either.

**Replace with** — §9's modification: keep the categories as *explanation* with
the evidence behind each, drop the composite number. If a number is retained, it
must carry the backtest that justifies it, and spread must appear once.

---

## 11 · Regulatory risk (`reg_tags`)

**Computes** — `get_regulatory_risk` (`main.py:~630`): rules over transaction
value and yfinance sector/industry, emitting agency tags at low/medium/high.

**Mathematically correct** — The thresholds are arithmetic and consistent. The
HSR trigger (~$119.5M) is a real filing threshold.

**Financially meaningful** — As a prior, yes: large deals in concentrated
sectors do draw scrutiny. As a description of where a deal actually stands with
the agencies, no.

**Assumes** — that deal size and sector predict regulatory outcome, and that
yfinance's sector string is correct and available.

**Misleads** — two ways. First, it is a static prior computed at detection that
never updates: it cannot see an HSR expiration, a second request, a timing
agreement, or a consent decree. A deal that has *cleared* antitrust carries the
same "FTC Antitrust — high" tag as one facing a second request. Second, the
sector lookup is inside a bare `except: sector=industry=''`, so a yfinance
failure silently drops tags and the deal scores *better* for it. That is a
non-deterministic input to the risk score.

**Replace with** — separate the prior from the status. Keep the size/sector
rules as REGULATORY EXPOSURE. Add REGULATORY STAGE driven by filings — this is
the milestone detection the roadmap identifies as the biggest single unlock,
feeding §11, §12, §16 and §17. Make the sector-fetch failure explicit rather
than silently favourable.

---

## 12 · Reverse termination fee (RTF) — SOUND

**Computes** — `deal_commitment.py`: pattern extraction over the EX-2 exhibit,
acquirer-side fee only, third-party fee names excluded, span-based exclusion
after a proximity window.

**Mathematically correct** — Yes. The amount is read, not derived. 11 of 12
deals carry one.

**Financially meaningful** — Yes, and it is the single most useful contractual
fact the product extracts: it prices the acquirer's option to walk.

**Assumes** — that the largest acquirer-payable fee in the agreement is the
operative RTF.

**Misleads** — one real gap, and it is §6's: the fee is extracted without its
*trigger*. A $7B fee payable only on antitrust failure is a different instrument
from one payable on any termination, and the product currently shows both as
"$7.0B". Verdict thresholds are applied to the amount without regard to what
makes it payable.

**Replace with** — nothing in the extraction. Add trigger classification
(regulatory / financing / other) and payability conditions per §6.

---

## 13 · Target termination fee (`company_fee`) — SOUND

**Computes** — same extraction path, company-side.

**Mathematically correct** — Yes. GBCS's case is the good test: two identical
$400,000 fees one sentence apart, correctly attributed to each side.

**Financially meaningful** — Yes: it prices the target's cost of accepting a
superior proposal, and so bounds how contestable the deal is.

**Assumes** — that company-side and acquirer-side fees are distinguishable by
their surrounding language. They were, across all twelve.

**Misleads** — same §6 gap as #12: no trigger. A target fee payable on a
fiduciary-out is different from one payable on a vote failure, and only the
first says anything about a competing bid.

**Replace with** — nothing structural. Add triggers per §6.

---

## 14 · Fee multiple (`asymmetry`) and fee as % of deal value

**Computes** — `asymmetry = reverse_fee / company_fee`. Separately,
`reverse_fee_pct = reverse_fee / deal_value`, thresholded at 3% for the
STRONG/WEAK verdict.

**Mathematically correct** — The ratio is correct and unit-free. The percentage
is arithmetically correct but its denominator is not consistent — see #15.

**Financially meaningful** — The ratio is genuinely good: it needs no external
input, both terms come from the same document, and it directly measures which
side is more bound. 1.0x (GBCS) says the parties are symmetrically committed;
2.3x (WBD) says the acquirer is carrying most of the risk.

**Assumes** — for the percentage, that `deal_value` means the same thing across
deals. It does not.

**Misleads** — the 3% threshold is applied against a denominator that is
sometimes enterprise value and sometimes equity value (#15). The same fee can be
STRONG or WEAK depending on which extraction path a deal happened to take. WBD
is the live example: `tx_value` 77.72 (equity approximation) gives 9.0%, while
the hand-verified 110.0 (enterprise) gives 6.4%. Both cross the 3% threshold
here, so no verdict flips today — but nothing prevents it.

**Replace with** — keep the ratio as the headline; it is the more robust of the
two. Gate the percentage on a consistent denominator and state which basis is
used. Where the basis is unknown, show the ratio and the dollar amount and
suppress the percentage.

---

## 15 · Transaction value (`tx_value`) — BROKEN

**Computes** — `extract_transaction_value` (regex), falling back to
`compute_equity_tx_fallback` for cash deals, with a `VERIFIED_TX_VALUES`
override. `tx_value_source` records which path ran.

**Mathematically correct** — Each path is internally fine. The composition is
not.

*Two different quantities share one field.* Live sources split
`regex_enterprise` (6 deals) and `equity_calc_approx` (4 deals) plus one
`verified_hardcode`. Enterprise value includes net debt; equity value does not.
For a leveraged target these differ by a large multiple, and the field is
consumed as though one number.

*The verified override is inverted.* `main.py:1361`:

```
if ticker in VERIFIED_TX_VALUES and not tx_value:
```

The hand-verified value applies **only when extraction failed**. WBD's
approximation (77.72) therefore wins over its hand-verified enterprise value
(110.0), a 29% error on a field feeding the RTF percentage and three regulatory
thresholds. This is backwards relative to `VERIFIED_ACQUIRERS`, where the
project's own documentation states the hardcodes "always win and are never
overwritten."

**Financially meaningful** — Only if the basis is stated. It currently is not,
outside the `tx_value_source` field, which is not rendered.

**Assumes** — that a single scalar can represent deal size across cash, PE and
tender structures.

**Misleads** — it is the denominator for the RTF percentage (#14) and the input
to every regulatory threshold (#11). A deal whose equity value falls below $1B
when its enterprise value exceeds it will lose its FTC/DOJ tag and gain score
for the omission.

**Replace with** — carry `equity_value` and `enterprise_value` as separate
fields, populate what is known, and require callers to name which they want.
Invert the override so verified values win. Render the basis wherever the number
appears.

---

## 16 · Financing status (`financing_signal`)

**Computes** — `extract_financing_signal(full_ct)` over the **8-K announcement
text**, yielding committed / confident / contingent / unknown, worth +10 to -10
in the score.

**Mathematically correct** — Not arithmetic; a keyword classification.

**Financially meaningful** — The question is: is the buyer's obligation
conditioned on getting funded? That is decisive for PE deals.

**Assumes** — that a press release characterises financing as reliably as the
contract does.

**Misleads** — and this is the sharpest finding in the section: **the product
reads this question twice, from two documents, and the score uses the weaker
one.** `deal_commitment.check_financing` reads the actual merger agreement for a
financing condition and returns STRONG/WEAK/UNKNOWN with a quote. `score_deal`
does not consume it — it consumes the press-release scan (`main.py:1326`). So a
deal whose *agreement* contains no financing condition (contractually strong)
can score -10 because its *press release* used hedged language, and vice versa.
Five of eleven deals carry `unknown`, contributing 0 and hiding the disagreement
entirely.

**Replace with** — make the contractual reading authoritative and demote the
press-release scan to a fallback used only where no agreement was read. Where
they disagree, that disagreement is itself a signal worth surfacing. This is
close to free: both readings already exist on the deal record.

---

## 17 · Antitrust obligation — SOUND

**Computes** — `check_antitrust_efforts`: hell-or-high-water patterns ordered
strongest-first, with a carve-out check that downgrades a strong covenant
qualified elsewhere in the agreement.

**Mathematically correct** — Not arithmetic. The ordering is right, and the
qualified-HOHW case — a strong covenant capped two paragraphs later — is handled
explicitly rather than by pattern ordering alone. That is the expensive error in
this domain and it is guarded.

**Financially meaningful** — Yes. It states whether the buyer must fight for
clearance or may walk when it gets hard.

**Assumes** — that efforts language is confined to a readable span and that the
strongest matching phrase governs.

**Misleads** — only through the UNKNOWN state, which conflates "the agreement is
silent" with "the parser could not read it" — the §7 gap. No section number is
carried.

**Replace with** — nothing structural. Add section numbers and split UNKNOWN
into not-present vs not-read.

---

## 18 · Specific performance — SOUND

**Computes** — `check_specific_performance`: distinguishes a full right to
compel closing from one limited to enforcing covenants short of closing.

**Mathematically correct** — Not arithmetic. The limited-vs-full distinction is
the one that matters and it is drawn.

**Financially meaningful** — Yes. Without it, the RTF is the buyer's exit price;
with it, the target can force the deal shut. It is the term that determines
whether the RTF is a ceiling on the buyer's downside or merely a fee.

**Assumes** — that the limiting language sits near the grant. It did across all
twelve.

**Misleads** — §6's gap: exceptions and caps are not extracted, and specific
performance conditioned on financing being available is materially weaker than
an unconditional right. Both currently read STRONG.

**Replace with** — nothing structural. Add exceptions and caps per §6.

---

## 19 · Position sizing — BROKEN

**Computes** — `templates/index.html:2135-2151`. For each of five notional
sizes: `shares = floor(inv / cp)`, `up = (sp_pct/100) * inv`,
`dn = (break_downside/100) * inv`.

**Mathematically correct** — No.

*The sign is hardcoded.* The downside cell renders:

```
'−$' + Math.round(Math.abs(dn)).toLocaleString()
```

A literal minus sign, wrapped around an absolute value. For AES, whose
`break_downside` is **+14.53%**, the model implies a $3,632 *gain* on a $25,000
position if the deal breaks. The table prints **−$3,632**. Worse, the column
header above it renders `_daSgn(bd)` = "+14.53%", so the header and the cells in
the same table contradict each other.

*The base is inconsistent.* Returns are computed on `inv`, but only
`floor(inv/cp) * cp` is actually deployed. The residual cash earns the deal
spread in this table. Small, but it is a real overstatement on every row.

**Financially meaningful** — Only as arithmetic on a break price that #8 shows
is not a model. The table's authority comes from its specificity — five rows of
exact dollars — and every one of those dollars inherits an unvalidated input.

**Assumes** — a two-state outcome, full deployment, no leverage, no borrow cost,
no time value, no probability weighting.

**Misleads** — it is the most concrete-looking element on the deal page and sits
closest to an actual trading decision. "If Breaks −$3,632" on AES is wrong in
sign, and the reader has no way to see that.

**Replace with** — remove the hardcoded sign and let the value carry it; a
positive break outcome should read as a gain and prompt the question of why the
break price sits above the current price. Compute on deployed capital, not
notional. Expected P&L and probability weighting are §14 and are correctly
deferred until §4 and §5 land — but the sign error is not a §14 problem and
should not wait.

---

## What this audit implies for sequence

The roadmap's order holds, with one adjustment.

**Confirmed:** §3 and §4 are correctly identified as the highest-value work.
Four metrics depend on the break price being real — #8 itself, #9 through both
halves of its fraction, #19 through `break_downside`, and #10 through the
premium sub-score. Nothing built on top of it is worth refining until it is.

The other two BROKEN metrics have separate roots and are worth naming so they
do not get swept into §4: #15 is an override-precedence bug, and #4/#5 are a
time-to-close problem. Neither is fixed by a better break price.

**Adjustment:** four defects here are independent of §4 and cost hours, not
weeks. None require the break-price engine to exist:

1. **#19 sign error** — one hardcoded character, actively wrong on the live site
2. **#9 clamp** — deleting it converts a hidden contradiction into a visible gate
3. **#15 override inversion** — one boolean, restores hand-verified values
4. **#5 date parser** — binds year to keyword, fixes a past-dated expected close

**#4's 180-day constant** is a fifth, blocked only on #5.

These are §3 and §25 work that happens to be cheap. Doing them first removes
four wrong numbers from production while §4 is designed.

**One finding needs a decision, not a fix:** AES's break price (16.87) exceeds
its deal price (15.00). That is either a bad `dp`, a filing date that is not the
announcement date, or an adjustment artifact — and it is the kind of thing the
§25 pass exists to resolve deal by deal. It is flagged here because it is what
exposed the #9 clamp.

---

# Results — four defects fixed

Applied 2026-08-27. Four of the defects above, all independent of the
break-price engine, so none waited on §3 or §4.

**§3 and §25 both stay open.** This is partial work on each: the break price
itself (#8) is untouched, and the per-deal QA pass has not been done.

Numbering note: the request labelled the annualized-spread fix `#19`; it is `#4`
here. `#19` is the position-size sign error, which was **not** in this batch and
remains open — see *Still open* below.

## Method

Every claim below rests on the live cache, not on reading the code. A snapshot
script captured, for all 11 deals, every value the four fixes could move —
`tx_value`, parsed close date, days to close, `ann`, regulatory tags, regulatory
sub-score, total score, risk band, probability — and was run once before the
changes and once after, against **the same cached prices**, so the diff isolates
the code change rather than mixing in market movement.

The yfinance sector lookup inside `get_regulatory_risk` sits in a bare `except`
that silently blanks the sector on failure, which would have shown up as a
spurious diff in the regulatory cascade. It was pinned to one fetch and reused
for both runs.

The close-date parser exists twice, once in Python for the server-computed
annualized spread and once in JavaScript for the rendered date. Both were
rewritten and then **executed against each other** — the JS in the running app
via the browser, the Python directly — across twelve inputs. They agree on all
twelve.

## 1 · Probability: gated, not clamped (#9)

`max(0, min(99.9, prob))` deleted. `two_state_applies(cp, dp, bp)` now runs
*before* the fraction and returns `(False, reason)` where the model cannot
produce a probability: break price at or above current, break price at or above
deal, or current above deal. The endpoint then publishes no number and says why.

AES, from the running app:

```
BEFORE   probability 99.9   signal "Distressed"   (raw 114.4, clamped)
AFTER    probability null   model_applies false
         "A close-or-break probability cannot be read from these prices: the
          modeled break price is at or above the current price, so there is no
          downside left for the model to price. The break price is a model
          estimate, not an observed floor."
```

No other deal changed. WBD, ALOT, GBCS and CZR still resolve and still return
the same numbers.

**Deliberately not gated:** WBD's 4.5%. Its numerator collapses to $0.10 against
a healthy $2.20 denominator, but every price is in the right order and the model
genuinely applies — the number is wrong because the *break price* is wrong. That
is #8, and gating it here would hide a break-price defect behind a model-scope
message. §3 and §4 own it.

## 2 · Annualized spread reads the deal's own clock (#4)

`ann = (sp_pct/180)*365` replaced with `annualized_spread(spread_pct, days)`,
fed by `days_to_close(close_date)`. Returns `None` — not a fallback constant —
where the close date is unknown, already passed, or beyond `ANNUALIZE_MAX_DAYS`
(1460). `days_to_close` is now stored on the deal record.

Same prices, same spreads, only the divisor changed:

| Deal | Spread | Days | `ann` before | `ann` after | Effect |
|---|---:|---:|---:|---:|---|
| GSAT | 9.72% | 491 | 19.71% | **7.23%** | overstated 2.7x |
| WBD | 7.27% | 34 | 14.74% | **78.05%** | understated 5.3x |
| CZR | 4.52% | 491 | 9.17% | **3.36%** | overstated 2.7x |
| NATH | 4.24% | 126 | 8.60% | **12.28%** | understated 1.4x |
| PAYO | 4.08% | 307 | 8.27% | **4.85%** | overstated 1.7x |
| AES | 1.83% | 216 | 3.71% | **3.09%** | overstated 1.2x |
| OGN | 1.82% | 216 | 3.69% | **3.08%** | overstated 1.2x |
| GBTG | 0.32% | 126 | 0.65% | **0.93%** | understated 1.4x |
| ALOT | 0.03% | 34 | 0.06% | **0.32%** | understated 5.3x |
| GBCS | 6.09% | — | 12.35% | **—** | no close date |
| APGE | 0.19% | — | 0.39% | **—** | no close date |

Every deal moved. Two now correctly show nothing.

The ranking inversion is resolved: under the constant CZR (9.17%) outranked
NATH (8.60%); NATH actually earns 3.7x more per unit of time (12.28% vs 3.36%).

## 3 · Verified transaction value wins (#15)

The guard `if ticker in VERIFIED_TX_VALUES and not tx_value` became
`resolve_tx_value(ticker, extracted, source)`, lifted out of the scan loop so it
is directly testable. A hand-verified entry now always wins, matching
`VERIFIED_ACQUIRERS`.

**The full cascade, WBD.** Five displayed values move; five do not.

| Value | Before | After |
|---|---|---|
| `tx_value` | 77.72 | **110.0** |
| `tx_value_source` | `equity_calc_approx` | **`verified_hardcode`** |
| Deal value, as rendered | $77.7B | **$110.0B** |
| Reverse fee, % of deal value | 9.01% (shown 9.0%) | **6.36% (shown 6.4%)** |
| FTC tag reason text | "deal of $77.7B" | **"deal of $110.0B"** |
| RTF verdict | STRONG | STRONG — unchanged |
| Fee asymmetry | 2.33x | 2.33x — independent of `tx_value` |
| Commitment summary | 1 of 3 favour closing | unchanged |
| Regulatory tags | HSR low, FTC high | **unchanged** |
| Total score / risk band | 50 / Medium | unchanged |

**The audit was wrong about one thing here, and the data says so.** Entry #15
predicted the regulatory tags "may reclassify." They do not. Every threshold —
HSR at $0.12B, FTC-high at $5B, market concentration at $2B — is crossed at both
$77.72B and $110.0B, so no tag, no level, and therefore no regulatory sub-score,
total score or risk band moves. The reverse-fee percentage was the only computed
consequence; the rest of the cascade is display text.

The verdict does not flip either: 9.01% and 6.36% both clear the 3% threshold.
The exposure remains real — a deal straddling that threshold would flip on this
field alone — but on today's feed it is latent, not live.

GSAT already read `verified_hardcode` because its extraction had failed, so it
is unaffected. No other live deal is in `VERIFIED_TX_VALUES`.

## 4 · Close-date parser (#5)

Rewritten in both `main.py` (`parse_close_date`) and `templates/index.html`
(`_daParseCloseDate`). A year is now combined only with a qualifier from **its
own clause** — each year token sees only the text between the previous year
token and itself — which makes the defect inexpressible rather than patched.
Every qualifier resolves to the last day it can mean; where several periods are
named, the latest wins; nothing between two stated periods is ever synthesised.

| Raw text | Before | After | Why |
|---|---|---|---|
| `late 2026 or early 2027` | 2026-03-31 | **2027-03-31** | year and month came from different clauses |
| `mid-to-late 2027` | 2027-06-30 | **2027-12-31** | compound range now takes its later bound |
| `2027` | 2027-06-30 | **2027-12-31** | a bare year is a period; June was its midpoint |
| `Q3 2026` | 2026-09-30 | 2026-09-30 | unchanged |
| `H2 2026` | 2026-12-31 | 2026-12-31 | unchanged |
| `second half 2026` | 2026-12-31 | 2026-12-31 | unchanged |
| `early 2027` | 2027-03-31 | 2027-03-31 | unchanged |
| `mid-2027` | 2027-06-30 | 2027-06-30 | unchanged |
| `TBD` | null | null | unchanged |

AES's `days_to_close` goes from **-149 to +216**. It was showing a live deal as
five months overdue.

## Verification

`test_formulas.py`, 42 checks, all passing. Cases are live deals, not synthetic
ones. `test_commitment.py` (54), `test_outside_date.py` and `test_flags.py` all
still pass.

A local scan then ran the full pipeline with the fixes in place and wrote a
cache carrying the corrected values — `days_to_close` populated, `ann` empty for
the two deals with no close date, WBD at `110.0 / verified_hardcode`. The
browser confirms the server-side `days_to_close` and the client-side
`_daParseCloseDate` agree for all ten deals, and that a null `ann` renders as an
em-dash rather than a zero.

That scan dropped GSAT from the local feed. It is unrelated to these changes:
GSAT's prior row was 39.7 hours old against `ROLLING_CARRY_MAX_AGE_HOURS = 36`,
so it aged out of the rolling carry. Nothing in these four fixes touches
detection or carry, and the two deals whose `ann` is now null survived.

## What the fixes exposed but did not fix

**WBD now annualizes at 78%.** That is arithmetically correct — a 7.27% spread
34 days from close *is* ~78% annualized — and it makes a data-quality problem
visible that the 180-day constant had been flattening. WBD's `close_date` reads
`Q3 2026`, which ends in 34 days, on a deal announced in February 2026 that
faces a full FTC review and carries a $7B regulatory termination fee. That
guidance is almost certainly stale. This is exactly what audit entry #6
describes: the expected close is read once at announcement and never
re-sourced. The annualized figure is now only as good as that field, which is
the right dependency and an uncomfortable one. **§25 item.**

**AES's break price still exceeds its deal price.** The gate stops it producing
a false probability, but the underlying data is still wrong: `break_price` 16.87
against `dp` 15.00. Still a §25 diagnosis — bad `dp`, a filing date that is not
the announcement date, or the dividend-adjustment artifact in #8.

## Still open

- **#19, the position-size sign error.** Not in this batch. AES's modeled break
  *gain* still prints as `−$3,632` while the column header above it reads
  `+14.53%`. One hardcoded character in `templates/index.html`, and the cheapest
  of the five defects that entry identified.
- **#8, the break price**, and everything resting on it. §4.
- The two parsers are now duplicated logic in two languages held in agreement by
  a test rather than by construction. Storing `days_to_close` on the record —
  which this change starts doing — is the path to deleting the JS copy.
