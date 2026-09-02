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

---

# Diagnosis — the deals showing no annualized figure

2026-08-28, against the production feed. No code changed; the parser is not
widened here, because two of the three causes would not be helped by widening it
and one of them would be made worse.

The feed read 19 deals with 8 missing `ann` when this ran, against the 20/9
reported. Deals enter and leave between scans; the split below is unaffected.

## The split

| | Cause | Count | Deals |
|---|---|---:|---|
| **(a)** | No close date in the filing — the em-dash is correct | **5** | BOW, BZH, CBZ, DSGR, RAMP |
| **(b)** | Stated in the filing, not read | **1** | SLAB |
| **(c)** | Parsed or present, dropped downstream | **2** | APGE, BWMN |

**The single (b) is not a missing phrasing.** That matters, because widening the
patterns was the obvious response and it would have fixed nothing.

## (a) · Five deals genuinely state no close date

BOW, BZH, CBZ, DSGR and RAMP were each searched across their 8-K body and their
press release for any quarter/half/early-mid-late token within 150 characters of
close, complete or consummate language. Nothing in any of them.

Three of the five (BOW, CBZ, DSGR) also carry `Undisclosed` acquirers, and two
have 8-K bodies of 213 and 210 characters — these are incorporation-by-reference
filings whose substance is entirely in exhibits. For these the em-dash is the
honest output and there is nothing to fix.

## (b) · SLAB states it twice and the reader never sees it — the 5,000-char cap

`extract_close_date` searches `clean_text[:5000]`. SLAB's guidance appears in
both documents, and both times past that boundary:

```
d62897d8k.htm      offset 12,483 / 29,531
  "...The parties anticipate the Merger to close in the first half of 2027,
   subject to, among other conditions, approval by the Company's stockholders..."

d62897dex991.htm   offset  5,517 / 18,890
  "...The transaction is expected to close in the first half of 2027, subject
   to receipt of regulatory approvals and other customary..."
```

The press release misses the window by 517 characters.

**The patterns handle this phrasing perfectly.** Given the sentence directly,
`extract_close_date` returns `'first half of 2027'` and `parse_close_date`
resolves it to 2027-06-30. Given the same text at offset 4,900 it still works;
at 6,000 it returns `TBD`. The boundary is the whole defect:

```
extract_close_date(sentence)                -> 'first half of 2027'
extract_close_date('x'*4900 + sentence)     -> 'first half of 2027'
extract_close_date('x'*6000 + sentence)     -> 'TBD'
```

So this is a **window** problem, not a **vocabulary** problem. Widening the
phrase patterns would not have moved SLAB by one character, and the fix — if one
is wanted — is to raise or remove the cap, which is a different change with a
different risk: the cap is what stops the reader wandering into the merger
agreement, where dozens of dates appear in contexts that are not guidance.

The related check the rewrite raised: this week's parser refuses `2027` on its
own ("The parties expect the transaction to close in 2027") because a bare year
with no qualifier trips the abstention guard. That is deliberate and it is not
what is happening to any of these nine — every (a) deal states no date at all,
and SLAB states a fully qualified one.

## (c) · Two deals whose close date never reaches the calculation

Neither APGE's nor BWMN's close date comes from the filing. `extract_close_date`
returns `TBD` for both 8-Ks, and neither document contains a quarter token inside
the 5,000-char window at all. Both values came from the **LLM enrichment pass**,
and that pass has two problems.

**It writes `close_date` without recomputing what depends on it.** At
[main.py:2003](main.py:2003):

```python
if deal.get('close_date') == 'TBD':
    deal['close_date'] = cd.strip()
    enriched = True
```

`days_to_close` and `ann` were computed hundreds of lines earlier, at deal
construction, from the `TBD` that was there at the time — so both are `None` and
stay `None`. APGE therefore shows `close_date: Q3 2026`, which `parse_close_date`
resolves to 2026-09-30 without complaint, beside `days_to_close: None` and no
annualized figure. The date is present, parseable, and never used. This is the
same shape as the enrichment-ordering bug already recorded in CLAUDE.md: a field
set after the thing that consumes it has already run.

**Its output is not checked against the filing.** BWMN carries `close_date:
Q2 2026` on a deal announced **2026-08-10**. Q2 2026 ended six weeks before the
announcement. `days_to_close` is **-61** and `annualized_spread` correctly
refuses a passed date — so BWMN's em-dash is right by accident, arrived at
through a fabricated date rather than an absent one. Nothing in the pipeline
compares an enriched close date against the announcement date it must follow.

## What this implies for the response

The three causes need three different things, which is why they were worth
separating before touching the parser.

- **(a), five deals** — nothing. The em-dash is the correct output and the
  feed is being honest. §8's freshness work would let it say *"not disclosed"*
  rather than showing a blank, which is a display improvement, not a parser one.
- **(b), one deal** — a decision about the 5,000-character cap, not a
  vocabulary change. Raising it recovers SLAB and any other deal whose guidance
  sits deep in an 8-K; it also exposes the reader to the merger agreement's
  dates, which is what the cap exists to prevent. Scoping the search to the
  press release exhibit and the 8-K body while raising the cap within them would
  get both, and is the option I would put first.
- **(c), two deals** — a real bug and independent of the parser. The enrichment
  pass must recompute `days_to_close` and `ann` after it writes `close_date`,
  and it must reject a close date that precedes the announcement. BWMN's Q2 2026
  would have been caught by the second check alone.

**Nine deals do not lack a stated close date.** Five genuinely do, one states it
clearly and is not read for a reason unrelated to phrasing, and two have dates
that are either unused or wrong. Widening the parser addresses none of them.

---

# Results — four fixes from the close-date diagnosis

Applied 2026-08-28.

## 1 · Nothing the enrichment pass produced was checked against the filing

The audit of that pass is worse than the BWMN case suggested. It produces three
fields, and **not one of them was validated against the document it claims to
come from**:

| Field | Guard before | Against the filing? |
|---|---|---|
| `close_date` | non-empty, not the literal `"TBD"` | **no** |
| `tx_value` | numeric, between 0.01 and 500 | **no** |
| `acquirer` | two-or-more word overlap with the target's name | **no** |

`close_date` had effectively nothing, which is how BWMN came to carry `Q2 2026`
on a deal announced 2026-08-10 — six weeks after that quarter ended.

`tx_value` was worse than unvalidated: it was **mislabelled**. A model-supplied
number was stored with `tx_value_source = 'regex_enterprise'`, which claims the
value was pulled out of the filing by pattern match. The provenance field is the
entire audit trail for that number, and it was saying the wrong thing. It now
reads `llm_enriched`, and the log line says "model estimate, not
filing-extracted".

`acquirer` had a guard that only ever compared the answer against the *target's*
name. It never asked whether the name appears in the filing at all, so a
plausible company the model supplied from its own knowledge would have been
stored with nothing behind it. Feeding it "Berkshire Hathaway" against Atkore's
8-K, the old guard accepted it.

That guard also had a hole of its own: it required a **two-word** overlap, so a
single-word target passed straight through. `Atkore Inc.` offered as the
acquirer of Atkore Inc. reduces to `{atkore}` on both sides — an overlap of one
— and was accepted. Now refused, along with any name whose words are a subset of
the target's.

**What each field now requires**

- `close_date` — must resolve to a date, must fall **after** the announcement,
  and must be within `ENRICHED_CLOSE_MAX_DAYS` (1,260, about three and a half
  years). Failing any of those it is **discarded, not stored**. A blank is
  honest; a fabricated date is not.
- `acquirer` — must not be the target, must not be a subset of the target's
  name, and **must appear in the filing text**. Matched on significant words
  rather than the whole string, because filings write "Prysmian S.p.A." where
  the model returns "Prysmian" and an exact match would refuse correct answers.
- `tx_value` — range check unchanged, provenance corrected. Cross-checking the
  magnitude against the filing is left alone deliberately: AUDIT #15 shows the
  field already conflates enterprise and equity value, and a check written
  before that is settled would encode the confusion.

Both refusals log their reason, so a discarded value is visible rather than
silently absent:

```
[Enrich] BWMN close_date REFUSED — backwards: 'Q2 2026' resolves to 2026-06-30,
         before the 2026-08-10 announcement
[Enrich] ATKR acquirer REFUSED — 'Berkshire Hathaway' does not appear anywhere
         in the filing text
```

## 2 · A changed close date now recomputes what depends on it

The pass set `deal['close_date']` and stopped. `days_to_close` and `ann` had
been computed hundreds of lines earlier from the `TBD` that was there at the
time, so both stayed `None` — which is how APGE came to show a perfectly
parseable `Q3 2026` beside a null `days_to_close` and no annualized figure. The
date was present, readable, and never used.

Both are now recomputed at the point of assignment, and the log line shows all
three together so the next instance is visible in the scan output:

```
[Enrich] APGE close_date: Q3 2026 (days_to_close 33, ann 1.11)
```

This is the fourth appearance of the enrichment-ordering shape already recorded
in CLAUDE.md — a field written after the thing that consumes it has run.

## 3 · The close-date reader was the tightest cap in the file by 5x

`extract_close_date` read `clean_text[:5000]`. Every sibling reading the same
`full_ct` reads more:

| Reader | Cap |
|---|---:|
| `extract_transaction_value` | 25,000 |
| `extract_acquirer` | 15,000 |
| `get_tender_offer_expiration` | 10,000 |
| `extract_close_date` | **5,000** |

Nothing justified close_date being the outlier. Raised to **25,000**, matched to
`extract_transaction_value` rather than to a newly invented number, on the
grounds that both read the same text and have no reason to disagree about how
much of it is worth reading.

SLAB is recovered from both of its documents:

```
d62897d8k.htm     (29,531 chars)  ->  'first half of 2027'   (offset 12,483)
d62897dex991.htm  (18,890 chars)  ->  'first half of 2027'   (offset  5,517)
```

**Correcting the diagnosis above:** it said the cap "exists to stop the reader
wandering into the merger agreement". That was wrong. `full_ct` is one filing
document at a time, and `extract_transaction_value` already reads 25,000
characters of exactly the same text — so whatever exposure exists, this change
does not add it. The 5,000 was not a considered trade-off, it was an outlier.

What else the cap was truncating is now answerable: only `close_date` used it,
so nothing else was affected. The three other readers were already past it.

## 4 · Windows under a month are not annualized

`ANNUALIZE_MIN_DAYS = 30`. Below it `annualized_spread` returns `None` and the
display shows the raw spread with the days remaining instead.

**Why 30.** Annualizing assumes the capital can be redeployed into a comparable
position at that rate when the deal closes. Inside a month that assumption stops
holding — there is no reliable supply of merger-arb positions to roll into on a
weekly cadence, so the figure describes a return nobody can compound. The
arithmetic turns brittle at the same point: the multiplier is 12x at 30 days,
73x at 5, and 365x at 1, so a spread that is mostly bid-ask noise becomes the
largest number on the page. 30 rather than 20 because one month is where the
redeployment story stops being arguable, and a round boundary is easier to
explain than a threshold tuned to make one deal look sensible.

**A floor, not a cap.** Nothing is clamped to a maximum. A genuine 78%
annualized on a 34-day close is real and still prints. Clamping is what the
probability endpoint did before it was deleted, and it converted a sign error
into a confident-looking 99.9% — the lesson was to refuse the number, not to
bend it.

**What the floor suppresses across the feed: one deal.**

| Deal | days | spread | `ann` before | `ann` now |
|---|---:|---:|---:|---|
| GBCS | 1 | 6.09% | **2,222.85%** | suppressed — shows "— · 1d to close" |
| ALOT | 31 | 0.03% | 0.35% | 0.35% — one day above the floor, unaffected |
| NATH | 51 | 3.58% | 25.62% | 25.62% |

Every other deal either sits well above the floor or already had no annualized
figure for the reasons in the diagnosis above. GBCS is the only deal the floor
touches, and it is the deal that prompted it — four days from a fixed outside
date with no extension clause, now showing the days rather than a four-digit
percentage.

The display substitution is in both places the figure appears: `_daAnn` on the
deal page and `annCell` on the dashboard. Verified in the browser:

```
GBCS  suppressed, 1d     -> — · 1d to close
ALOT  just above floor   -> +0.35%
NATH  normal             -> +25.62%
SLAB  no close date      -> —
BWMN  past close date    -> —
```

## Coverage

`test_formulas.py` is at 136 checks. The new ones cover the BWMN backwards date,
the acquirer-absent-from-filing case the old guard accepted, the single-word
target that slipped its two-word overlap rule, the floor at 29/30/31 days, the
explicit not-clamped case, and SLAB's phrase at both of its real offsets.

---

# Provenance inventory — every field on a deal record

2026-08-28. Groundwork for §7; **§7 is not implemented here**. A provenance
system built on labels that already misdescribe their sources would be worse
than none, so this establishes what each label currently means before anything
is built on it.

38 fields on the production record. For each: where the value actually comes
from, whether the stored label matches, and whether anything checks it before it
reaches the cache.

**Legend** — `LIES`: the stored label misdescribes the source. `NO LABEL`:
multiple possible sources collapse into one field with nothing recording which
ran. `PARTIAL`: a label exists for some sources and not others, so its absence
is ambiguous.

## The inventory

| Field | Actual source | Label | Label honest? | Validated before cache |
|---|---|---|---|---|
| `accession` | EDGAR metadata | — | n/a | yes — the gate resolves it to a real filing |
| `acquirer` | filing regex **or** hardcode **or** LLM | none | **NO LABEL** | own-name overlap; LLM path now checks the filing |
| `acquirer_type` | keyword list over `acquirer` | — | n/a | **none** — see GSAT below |
| `agreement_read` | internal marker (accession) | — | honest | n/a |
| `ann` | computed from `sp_pct` ÷ `days_to_close` | — | n/a | floor + ceiling on days |
| `break_downside` | computed from `cp`, `break_price` | — | n/a | none |
| `break_price` | yfinance close **or** hardcode **or** inert formula | `break_price_method` | **MISLEADING** | none — AUDIT #8 |
| `break_price_method` | the label itself | — | see below | n/a |
| `close_date` | filing regex **or** SC TO-T **or** hardcode **or** LLM | `close_date_source` | **PARTIAL** | LLM path only (new) |
| `close_date_capped_to` | computed from outside date | — | honest | n/a |
| `commitment` | EX-2 filing extraction | quote | honest | quote present; no section (C4) |
| `company` | SEC ticker map **or** yfinance **or** literal placeholder | none | **NO LABEL** | none |
| `cp` | yfinance daily close | none | **NO LABEL** | > $1, non-empty. No as-of date — AUDIT #1 |
| `days_old` | computed from `filed` | — | honest | n/a |
| `days_to_close` | computed from `close_date` | — | n/a | inherits `close_date`'s gap |
| `deal_type` | EDGAR query **or** keyword reclass **or** hardcode | none | **NO LABEL** | **none** — see GSAT below |
| `direction` | computed verdict | verdict + reason | honest | enforcing gate |
| `dp` | filing regex | none | **NO LABEL** | spread range only, never against the filing |
| `fetched` | system clock | — | honest | n/a |
| `filed` | EDGAR metadata | — | honest | n/a |
| `financing_signal` | press-release keyword scan | none | **NO LABEL** | none — AUDIT #16 |
| `flags` | filing extraction | quote (`context`) | honest | quote present |
| `gate` | computed verdict | verdict + accession | honest | is itself the validator |
| `outside_date` | EX-2 filing extraction | quote + pattern tier | honest | plausibility window, quote |
| `pricing` | hardcoded structure + yfinance quote | 13 barriers + `acquirer_price_at` | honest | **the strongest in the record** |
| `reg_tags` | computed from `tx_value` + yfinance sector | none | **NO LABEL** | none — silent blanking, AUDIT #11 |
| `risk` | computed from `sp_pct`, `score` | — | n/a | none |
| `risk_at_detection` | frozen snapshot | — | honest | write-once |
| `score` | computed, six factors | — | n/a | bounds correct, weights unvalidated |
| `score_at_detection` | frozen snapshot | — | honest | write-once |
| `score_history` | accumulated snapshots | timestamps | honest | FIFO cap |
| `sp_pct` | computed from `dp` **or** blended | `sp_pct_headline` present ⇒ blended | **PARTIAL** | integrity check (new) |
| `sp_pct_at_detection` | frozen snapshot | — | honest | write-once |
| `sp_pct_headline` | computed, pre-blended | — | honest | n/a |
| `spread_history` | accumulated snapshots | timestamps | honest | FIFO cap |
| `ticker` | EDGAR metadata | — | honest | resolves against SEC map |
| `tx_value` | filing regex **or** yfinance calc **or** hardcode **or** LLM | `tx_value_source` | **WAS LYING** — fixed, undeployed | range only |
| `tx_value_source` | the label itself | — | see below | n/a |

## Fields whose label does not match the source

**`tx_value_source` — the one already found, and it is live right now.** The fix
labelling model output `llm_enriched` is committed but **not deployed**, so
production shows 15 of 19 deals as `regex_enterprise` and that label currently
cannot distinguish a filing regex from a model guess.

It has a live casualty. **CBZ carries `tx_value: 60.0` — sixty billion dollars —
labelled `regex_enterprise`:**

```
CBZ shares outstanding   54,263,879
deal price               $55.00
implied equity value     $2.98B
stored tx_value          $60.0B      20x overstatement
```

CBIZ, Inc. is a ~$3B accounting and benefits firm. No filing states a $60
billion transaction. The range guard (`0.01 <= tx <= 500`) passed it because 60
is a plausible number in the abstract — nothing compared it to the company. It
flips the deal's DOJ Antitrust tag from `medium` to `high` (the $5B threshold)
and would set its reverse-fee percentage 20x too low.

**The label cannot even tell you which failure occurred.** Either the regex
matched a wrong figure or the model supplied one; `regex_enterprise` is stamped
on both paths today. That ambiguity is itself the finding — a provenance label
that cannot distinguish its own two sources is not provenance.

**`break_price_method: 'historical'`** is not false but it is misleading in the
way §7 exists to prevent. It names a *method* for what is a bare price lookup —
the last close before the filing date — and the deal page renders the result
under "Modeled downside case". 18 of 19 deals carry it. AUDIT #8 and QA F7 cover
the substance; the point here is that the label reads as though a model ran.

**`close_date_source` is PARTIAL, which is a trap.** It is set only on the LLM
path. Its *absence* therefore means "filing regex, or tender-offer lookup, or
hardcode" — three different provenances sharing one empty value. A reader
checking for the label would conclude an unlabelled date is filing-sourced. Same
shape as `equity_calc_approx`, which says "approximate" but not that the share
count behind it came from **yfinance, not the filing** — so a value the label
presents as calculated is half external API.

## Fields that reach the feed unvalidated

**`deal_type` and `acquirer_type`, with a live error.** GSAT — **Amazon**
acquiring Globalstar — is stored as `deal_type: Private Equity` and
`acquirer_type: Private Equity`. Amazon is not a private equity firm.
`get_acquirer_type` returns `'Private Equity'` unconditionally when `deal_type`
already says so, so one unvalidated field propagates into a second. `deal_type`
itself comes from whichever EDGAR query matched, then keyword reclassification —
and the code's own comment records that reclassification "only fires on fresh
EDGAR hits, not on deals carried forward", so a stale classification can persist
indefinitely. `acquirer_type` also matches on `holdings`, `partners` and
`capital`, which appear in plenty of strategic acquirers' names.

**`dp`, the most important extracted number in the product, carries no
provenance at all.** It is validated only by the spread falling in a plausible
range — never against the filing text that produced it. A wrong `dp` inside the
range is invisible, and it drives spread, probability, position sizing and the
sort.

**`financing_signal`** — press-release keyword scan, no label, and a
*contractual* reading of the same question already exists in `deal_commitment`
and is not consulted (AUDIT #16). 10 of 19 read `unknown`.

**`reg_tags`** — computed from `tx_value` (see CBZ) and a yfinance sector fetch
inside a bare `except` that silently blanks on failure, which drops tags and
makes the deal score *better*.

**`company`** — falls back to yfinance, then to a literal `"{ticker} (name
pending)"` string that would render as a company name. No deal carries it today.

**`cp`** — a daily close with no as-of date attached (AUDIT #1).

## What this means for §7

Three things have to happen in order, and the order matters.

1. **Correct the labels that misdescribe their source** — deploy the
   `tx_value_source` fix, and split `break_price_method`'s `'historical'` into
   something that says "last close before announcement" rather than implying a
   method.
2. **Give every multi-source field a label at all.** `acquirer`, `close_date`,
   `deal_type`, `company` and `dp` each have two to four possible origins and
   between them one partial label. Until each says which path ran, a "view
   evidence" interaction has nothing to point at.
3. **Only then build the interaction.** §7 wants a reader to go from a
   classification to the agreement language behind it. Today that chain is
   complete for `commitment`, `outside_date`, `flags` and `pricing` — all
   quote-backed or barrier-backed — and broken for everything else.

The four fields already carrying real provenance are the model to copy.
`pricing` is the strongest: thirteen named barriers, an acquirer price with its
own timestamp, and a hand-verified structure that records the accession it was
read from. Nothing else in the record approaches it, and it is worth noting that
it is also the only field where a bad value has ever been caught before display.

---

# Results — the two live errors from the provenance inventory

2026-08-28. Both are DATA errors with a FORMULA cause, so both fixes are to the
mechanism. Neither value is hardcoded.

## 1 · A transaction value is now checked against its own company

`tx_value_plausible()` compares the extracted value to `shares_outstanding ×
deal_price` and rejects anything wildly inconsistent with it. On rejection the
value is nulled at the point of extraction, which lets the existing equity-calc
fallback produce a defensible number in its place rather than leaving a blank.
The same check runs on the enrichment path, so a model cannot route around it.

**The band came from the feed, not from intuition.** Ratio of stored `tx_value`
to computed equity value, all 19 production deals:

```
0.97  0.99  1.00  1.00  1.00  1.07  1.08  1.09  1.13  1.18
1.19  1.20  1.27  1.28  1.30  1.34          <- sixteen deals, near parity
2.46  BZH                                   <- genuinely leveraged
2.79  CZR                                   <- genuinely leveraged
20.10 CBZ                                   <- 7x beyond the next-highest
```

The ratio is enterprise-to-equity in all but name: legitimately above 1 for a
target carrying debt, legitimately below 1 for one carrying net cash. The
ceiling is **5.0x** — clear of Caesars at 2.79x with room for an LBO target more
leveraged than anything in the feed — and the floor **0.4x**, which still
catches a value an order of magnitude too small. CBZ is rejected with four times
the margin of the nearest real value.

### What the check rejects across the feed

**CBZ, and nothing else.**

```
CBZ   $60.0B is 20.1x this deal's equity value
      ($2.98B = 54,263,879 shares x $55.00), above the 5.0x ceiling
```

The other eighteen pass, including both leveraged targets. So CBZ is alone —
which is the answer to whether this was one bad extraction or a systemic one,
and it is the better of the two answers.

Unknowable inputs pass rather than reject: no share count, no deal price, no
`tx_value`. Refusing on absence would discard good values every time yfinance is
unavailable, which trades a rare wrong number for a frequent missing one.

## 2 · Acquirer type is read from the acquirer

`get_acquirer_type` opened with `if deal_type == 'Private Equity': return
'Private Equity'`, short-circuiting before it ever looked at the buyer. GSAT
reached production as `acquirer_type: Private Equity` with **Amazon** as the
acquirer, because its `deal_type` had been set to Private Equity by whichever
EDGAR query matched first. The second field looked like an independent
judgement and was a copy of the first.

That branch is gone. The verdict now comes from the acquirer's own name, and a
deal with no named buyer returns **`Unknown`** rather than defaulting to
`Strategic` — the old default was a claim, not an absence.

The `deal_type` parameter is kept and deliberately unused, so call sites do not
move and so the removed dependency stays visible in the signature.

**Change across the feed: GSAT only.**

```
GSAT   Private Equity -> Strategic     (acquirer Amazon, deal_type Private Equity)
```

Every other deal's type was already derived from its acquirer's name and is
unchanged, including both genuine PE buyers — Arcline and Bernhard Capital
Partners — which are now caught by their own names rather than by a `deal_type`
that may itself be wrong.

## The same inheritance shape elsewhere

`deal_type` is the common parent, and it is the field the inventory flagged as
having no provenance label and no validation. Three more things read it:

| Consumer | What it inherits | Live effect |
|---|---|---|
| `score_deal` | +10 All Cash / +8 Tender Offer / **+5 Private Equity** | GSAT scores **5 points low** on a misclassification |
| equity-calc fallback | only fires for `All Cash` / `Tender Offer` | a misclassified deal gets no `tx_value` fallback |
| tender-offer expiry lookup | only fires for `Tender Offer` | a misclassified deal loses a real close date |

**The score one is live now.** GSAT is typed Private Equity, so it takes the +5
band instead of the +10 its all-cash structure earns — a 5-point deficit on a
153-point scale, on a deal whose acquirer is Amazon. I have not changed it:
altering the score weights is §9 work, and adding a correction on top of six
unvalidated weights would make the number harder to reason about, not easier.
Fixing `deal_type` itself is what resolves all three, and that is a validation
problem rather than an arithmetic one.

One smaller finding from the same sweep: `get_regulatory_risk(ticker, acquirer,
tx_value, deal_type)` takes `deal_type` and never reads it. Harmless, but it
reads as though regulatory exposure depends on deal structure when it does not —
the tags come from size and sector alone.

## Coverage

`test_formulas.py` is at 156 checks. The new ones cover CBZ at 20.1x, the same
deal's true value passing, both leveraged targets surviving the ceiling, a
net-cash target below parity, an order-of-magnitude-low value being caught, the
three unknowable-input cases passing, GSAT reading Strategic under either
`deal_type`, both real PE buyers still caught by name, and the four ways an
absent acquirer yields `Unknown`.

---

# BWMN's close date — cause (c), and why the validator never saw it

2026-08-28. The validator added in `1429e54` works. It was wired to one path,
and BWMN's value takes a different one.

## Ruling out (a) and (b)

**(b) is out.** `parse_close_date('Q2 2026')` resolves to 2026-06-30 against a
2026-08-10 announcement, and the validator refuses it correctly when asked:

```
validate_close_date('Q2 2026', '2026-08-10')
  -> (None, "backwards: 'Q2 2026' resolves to 2026-06-30,
             before the 2026-08-10 announcement")
```

**(a) is out.** The fix is deployed — `close_date_source` and `acquirer_source`
appear on other deals — and nothing is cached. Every deal in the feed carries a
`fetched` timestamp from the same three-minute window (22:01–22:03), so all 19
were freshly scanned and none was carried by `rolling_merge`. BWMN's "Q2 2026"
is produced fresh on every scan.

## (c) · The value comes from the filing, not the model

`close_date_source` is `None` on BWMN, and that field is only set on the
enrichment path. The value comes from `extract_close_date(full_ct)` at deal
construction, which has no validation at all.

Reading every document in the accession as the scan does:

| Document | chars | `extract_close_date` |
|---|---:|---|
| `d69901d8k.htm` | 41,774 | `TBD` |
| `d69901dex101.htm` | 40,691 | `TBD` |
| `d69901dex21.htm` | 359,662 | `TBD` |
| `d69901dex991.htm` | 42,328 | `'2026'` |
| **`d69901dex992.htm`** | **16,180** | **`'Q2 2026'`** |

EX-99.2 is the **merger** press release — *"Bowman Consulting Group Enters into
Definitive Agreement to be Acquired by Bernhard Capital Partners for $43.00 Per
Share in Cash"*. The Q-token it yields is at offset 4,803, in a cross-reference
to that same morning's **separate earnings release**:

> "…Bowman's **Q2 2026** Earnings Results — In a separate press release today,
> Bowman announced…"

Bowman filed one 8-K covering both its quarterly results and its acquisition.
The standalone pattern `\b(Q[1-4]\s+20\d{2})\b` requires no close, complete or
consummate language nearby, so it matched a heading about earnings and returned
it as merger close guidance.

**And a bad value here suppresses the guarded path.** The enrichment pass only
runs when `close_date == 'TBD'`:

```python
needs_cd = deal.get('close_date') == 'TBD'
```

Because the regex produced something, `needs_cd` was False, the enrichment pass
skipped BWMN entirely, and the validator that would have caught the date was
never asked. An unvalidated path did not merely bypass the check — it prevented
the checked path from running.

## The fix, and the exposure it exposes

`validate_enriched_close_date` is renamed `validate_close_date` — it was never
enrichment-specific, only enrichment-wired — and is now applied on **every path
that writes the field**: the construction regex, the tender-offer expiry lookup,
and the enrichment pass. A rejected value returns the field to `TBD`, which also
re-opens the enrichment path that the bad value had been blocking.

**Across the feed it rejects one value: BWMN's.** The other thirteen dated deals
pass, including SLAB's newly recovered "first half of 2027" and HZO's bare
"2026" on an 2026-08-10 announcement.

### Which other fields have this exposure

The question was whether a validator guarding only new writes leaves the feed
uncorrected. The real shape here is narrower and more useful: **a validator
guarding only one of several paths that write the same field.**

| Field | Paths that write it | Guarded |
|---|---|---|
| `close_date` | regex · tender expiry · hardcode · LLM | **all four** (was: LLM only) |
| `tx_value` | regex · equity calc · hardcode · LLM | **all four** — `52ec1d5` wired both ends |
| `acquirer` | regex · hardcode · LLM | **LLM only** |

`acquirer` is the remaining gap, and it is milder: `extract_acquirer` takes its
answer from the filing by construction, so the filing-presence check that makes
the LLM guard useful is trivially satisfied. What it does not get is the
target-name subset test, which is worth adding when §7 touches this field.

Hardcodes are hand-verified by definition and are the intended override, so they
are correctly unguarded in all three rows.

## BWMN's acquirer type — checked against the filing, and correct

Unlike GSAT, this one did not inherit. EX-99.2's headline reads *"…to be
Acquired by **Bernhard Capital Partners** for $43.00 Per Share in Cash"*, and
Bernhard Capital Partners is a private equity firm. `deal_type` is `All Cash`,
so there was nothing for the old short-circuit to propagate even before it was
removed:

```
get_acquirer_type('All Cash', 'Bernhard Capital Partners') -> Private Equity
```

That verdict comes from the acquirer's own name via the `capital` and `partners`
keywords. **BWMN's `acquirer_type: Private Equity` is right, and right for the
right reason.**

One thing the same reading corrects: the earlier diagnosis called this accession
an earnings 8-K. It is both — Item 2.02 and the merger in one filing, with the
merger agreement at EX-2.1 (359,662 characters) and two press releases. The
`accession` on the record is correct.

`test_formulas.py` is at 161 checks.

---

# Extending the close-date search to the agreement and the proxy

2026-08-28. Six deals with no close date — BOW, BZH, CBZ, DSGR, RAMP, BWMN —
searched across their merger agreement and any 2026 proxy, in addition to the
8-K and press release already checked.

**One of the six states a close date. Five state none anywhere.** And the one
that does cannot currently be read, for reasons that are not about where we
looked.

## What each source yielded

| Deal | EX-2.1 | Proxy | Verdict |
|---|---|---|---|
| BOW | 268,130 chars — nothing | DEF 14A (annual) — nothing | no date stated |
| BZH | 380,919 chars — nothing | none filed since 2026-01-01 | no date stated |
| **CBZ** | 397,141 chars — nothing | **PREM14A 2026-08-27 — states it** | **date found** |
| DSGR | 334,448 chars — nothing | none filed since 2026-01-01 | no date stated |
| RAMP | 336,132 chars — nothing | DEFM14A + PREM14A, 1.18M chars each — nothing | no date stated |
| BWMN | 356,095 chars — nothing | DEF 14A (annual) — nothing | no date stated |

The merger agreements are unanimous: **none of the six states expected timing**.
That is the expected result and worth recording rather than re-testing later.
Agreements define closing mechanically — "the Closing shall occur on the second
Business Day following satisfaction of the conditions" — and a mechanical
definition names no quarter. Roughly 1.7 million characters of agreement text
across the six produced no dated guidance at all.

RAMP is the strongest negative. Its DEFM14A and PREM14A run 1.18 million
characters each and still contain no expected-close phrase near close, complete
or consummate language. A proxy that size not stating timing is a real absence,
not a search that came up short.

## CBZ · the one date, and why it still does not resolve

CBZ's PREM14A, filed 2026-08-27, states it twice:

> "**Effective Time of the Merger; Closing.** Assuming timely satisfaction of
> necessary closing conditions set forth in the Merger Agreement, including the
> adoption of the Merger Agreement by the Company's stockholders, we antic…"
> — offset 27,140

> "…completing the Merger as quickly as possible. We currently anticipate that
> the Merger will be **completed during the fourth quarter of 2026**, but we
> cannot be certain when or if the conditions to the Merger will be satisfied…"
> — offset 102,755

That is unambiguous guidance from the target itself, dated three weeks ago.
Against a 2026-07-29 announcement it would pass `validate_close_date` without
difficulty — Q4 2026 resolves to 2026-12-31, comfortably after.

**It does not resolve, and extending the search is not sufficient to make it.**
Two independent blockers, neither of which is about which documents we read:

**The phrasing.** `extract_close_date` cannot read "fourth quarter of 2026" even
handed the sentence alone:

```
extract_close_date('We currently anticipate that the Merger will be completed
                    during the fourth quarter of 2026, ...')   ->  'TBD'
parse_close_date('fourth quarter of 2026')                     ->  2026-12-31
```

The resolver handles it. The extractor does not. Its patterns carry an explicit
accommodation for the half-year form — `(?:half[-\s]+of[-\s]+)?` — and no
equivalent for the quarter form, so "second half of 2026" is read and "fourth
quarter of 2026" is not. That looks like an omission in a pattern that already
intended to cover written-out periods, rather than a deliberate exclusion.

**The cap.** The phrase sits at offset 102,755 of an 884,167-character proxy.
`CLOSE_DATE_SCAN_CHARS` is 25,000, which is right-sized for an 8-K and is
nothing against a proxy.

**I have not changed either.** The instruction was to extend the search rather
than widen a pattern, and both of these are pattern-and-cap changes. They are
put here as a decision:

- Adding `(?:quarter[-\s]+of[-\s]+)?` alongside the existing `half of` form is
  narrow — `(?:first|second|third|fourth)\s+quarter\s+of\s+20\d{2}` can only
  mean a calendar quarter, and the value still passes `validate_close_date`. It
  is the smallest change that recovers CBZ.
- The cap would need a per-document-type value: 25,000 for an 8-K, something far
  larger for a proxy. Raising it globally reintroduces the exposure the audit
  already noted, since a proxy contains hundreds of dates that are not guidance.

Both are needed together. Either alone leaves CBZ at TBD.

## Two corrections to the earlier diagnosis

**BOW and DSGR were read from the wrong CIK, so the earlier "no dated close
guidance" for those two rested on nothing.** My diagnostic scripts hardcoded
CIK `0002006986` for BOW and `0000703351` for DSGR. Those are **Adagio Medical
Holdings** and **Brinker International** — unrelated companies. Every fetch
returned EDGAR's `NoSuchKey` error XML, which BeautifulSoup rendered as a couple
of hundred characters of text, and the searches then found nothing in it. The
"213-char 8-K body" and "210-char 8-K body" reported earlier as evidence of
incorporation-by-reference filings were error pages.

The product was never affected: `SEC_CIK_MAP` holds the correct values
(BOW → 0002002473, DSGR → 0000703604). This was my error, not the pipeline's.
Both have now been read at the correct paths — 268,130 and 334,448 characters of
merger agreement, plus both press releases — and the conclusion survives: neither
states a close date. But it needed redoing before it could be relied on.

That is the second time this session a diagnostic of mine produced a wrong
reading by looking at the wrong source; the first was reading the local cache
instead of production for C2 and C5. Both were caught by checking the data
again rather than by the code.

**BOW's merger agreement is invisible to the exhibit finder.** It is filed as
`triplecrown-mergeragreemen.htm` — the deal's project name, with no `ex2` token
anywhere in it:

```
_pick_ex2(['triplecrown-mergeragreemen.htm'])  ->  None
_pick_ex2(['d131211dex21.htm'])                ->  'd131211dex21.htm'
```

`_EX2_NAME` matches on the filename, and the index-page fallback added for CZR
applies the same test, so neither path reaches it. This explains BOW carrying no
commitment reading and no outside date while every sibling deal has both — the
268,130-character agreement is sitting in the accession, fetchable, and named in
a way the finder cannot see. It is a different failure from CZR's (whose
`index.json` omitted a correctly-named document); here the document is listed and
the name is the obstacle. Worth fixing by falling back to the EDGAR **document
type** column on the index page, which reads `EX-2.1` regardless of filename.

## Answer

**One of six resolves as a source finding: CBZ, from its PREM14A.** It does not
yet resolve in the product, and closing that gap needs a pattern form and a
per-document cap rather than a wider search.

**Five state no expected close date in any of the four document types.** For
BOW, BZH, DSGR, RAMP and BWMN, `TBD` is the correct answer and stays. RAMP's two
proxies at 1.18 million characters each are the clearest case: the absence is
real, not unreached.

---

# The exhibit is found by its type, and the quarter form is read

2026-08-31.

## 1 · Document type is the primary test; filename is the fallback

`_ex2_by_document_type` reads the **Type** column from the filing index page,
which EDGAR fills regardless of what the filer agent named the file:

```
<td>2</td> <td>EX-2.1</td>
<td><a href="...triplecrown-mergeragreemen.htm">...</a></td>
<td>EX-2.1</td> <td>677278</td>
```

Type is tried first; `_pick_ex2`'s filename matching is now the fallback for
filings whose index page cannot be read. Rows are parsed whole — link and type
taken from the same `<tr>` — so a type from one row can never attach to a
document from another. That is the mistake the close-date parser made across
clauses, and it is cheap to not repeat.

### The sweep: two deals, and the filename test explains both

**Two of nineteen deals have no agreement reading: ATKR and BOW. Both have an
EX-2 that filename matching cannot see, and type-based discovery finds both.**

| Deal | EX-2 by type | By filename |
|---|---|---|
| **ATKR** | `atkr_mergerk.htm` | **None** |
| **BOW** | `triplecrown-mergeragreemen.htm` | **None** |
| the other 17 | found | found — identical |

The correspondence is exact: every deal missing a reading is a deal whose
exhibit the filename test missed, and no deal with a reading was affected. There
is no residual population — the two failures and the two gaps are the same two
deals.

BOW's file is the deal's project codename ("Triple Crown"). ATKR's is
`atkr_mergerk.htm` — the ticker plus an abbreviation, no `ex2` token either.
Codenames and house abbreviations are ordinary in M&A, so a reader keyed on
filenames will keep missing them at roughly this rate: 2 in 19, about 10%.

The seventeen conventional names still match both ways, so the fallback keeps
carrying them if an index page is ever unreadable.

This also subsumes the CZR case from earlier. CZR's `index.json` omitted its
documents entirely while the index page listed them; the type reader uses the
index page, so it now handles both the missing-listing failure and the
unrecognisable-name failure through one path.

## 2 · "fourth quarter of 2026", and a cap sized to the document

**The phrasing.** Four patterns carried `(?:half[-\s]+of[-\s]+)?` and no quarter
twin, so `second half of 2026` read and `fourth quarter of 2026` did not — while
`parse_close_date` resolved either without complaint. All four now carry
`(?:(?:half|quarter)[-\s]+of[-\s]+)?`. This completes an accommodation that was
already there rather than loosening one: the form is still anchored to close,
complete or consummate language, and the result still passes
`validate_close_date`.

**The cap.** `PROXY_CLOSE_DATE_SCAN_CHARS = 400000`, against 25,000 for an 8-K.
CBZ's PREM14A is 884,167 characters and states its expected close at offset
102,755 — under 3% of the way in. Proxies restate the transaction at length
before reaching the section that discusses timing, so a cap sized for a press
release sees almost none of one.

It is bounded rather than removed. A proxy contains hundreds of dates that are
not close guidance — record dates, fiscal year ends, option expiries — and the
400,000 ceiling plus the requirement for close language nearby are what keep the
reader from wandering into them.

**CBZ, end to end on the real document:**

```
CBZ PREM14A  884,167 chars
  8-K cap    25,000  -> 'TBD'
  proxy cap 400,000  -> 'fourth quarter of 2026'
  validate vs 2026-07-29 announcement -> accepted
  resolves to 2026-12-31
```

## Settled: five deals state no expected close date anywhere

**Do not re-test these.** BOW, BZH, DSGR, RAMP and BWMN were searched across all
four document types — 8-K body, press release, merger agreement, and any 2026
proxy — totalling roughly 1.7 million characters of agreement text plus RAMP's
two 1.18-million-character proxies. None contains an expected-close phrase near
close, complete or consummate language.

| Deal | 8-K | Press release | EX-2.1 | Proxy |
|---|---|---|---|---|
| BOW | — | — | 268,130 chars, nothing | DEF 14A (annual), nothing |
| BZH | — | — | 380,919 chars, nothing | none filed since 2026-01-01 |
| DSGR | — | — | 334,448 chars, nothing | none filed since 2026-01-01 |
| RAMP | — | — | 336,132 chars, nothing | DEFM14A + PREM14A, 1.18M each, nothing |
| BWMN | — | — | 356,095 chars, nothing | DEF 14A (annual), nothing |

`TBD` is the correct value for all five and it is not a coverage gap. The
merger agreements are unanimous and that is structural, not incidental:
agreements define closing mechanically — "the Closing shall occur on the second
Business Day following satisfaction of the conditions" — and a mechanical
definition names no quarter. A future pass looking for close dates in EX-2.1
should expect to find none there for any deal.

Two of the five are worth re-checking **only** on a new filing. BZH and DSGR have
filed no proxy at all yet; when their DEFM14A appears it will very likely state
timing, as CBZ's did. BOW and BWMN have only annual DEF 14As, which are not
merger proxies. RAMP is the settled case — its merger proxies exist, run to 1.18
million characters each, and state nothing.

## Coverage

`test_formulas.py` is at 176 checks. New: both codenamed exhibits defeating the
filename test, the seventeen conventional names still matching, the near-miss
rejections still holding, CBZ's phrasing extracting and resolving, the three
other written-out quarter forms, the half form and Q-abbreviation unchanged, the
proxy cap reading CBZ's real offset where the 8-K cap cannot, and the proxy cap
remaining bounded.

---

# Three things that did not land — causes

2026-08-31. Production has rescanned since the report, which changes two of the
three answers.

## 1 · BOW and ATKR — already fixed, and the premise has moved

Neither (a), (b) nor (c) as posed. **The document-type fix landed and worked on
both.** Production now shows:

```
BOW    agreement_read 0001628280-26-051540   commitment yes   outside_date yes
ATKR   agreement_read 0001666138-26-000016   commitment yes   outside_date NO
```

BOW is complete. ATKR's exhibit is now found and read — `atkr_mergerk.htm`, the
file filename matching could not see — which is why it has a commitment reading
it did not have before. Its missing outside date is a **different problem**, and
`agreement_read` being set proves the EX-2 discovery is not it.

**The outside-date extractor is what fails for ATKR**, and for three others:

| Deal | EX-2 read | chars | `extract_outside_date` |
|---|---|---:|---|
| ATKR | `atkr_mergerk.htm` | 358,070 | none found |
| ALOT | `d100857dex21.htm` | 264,736 | none found |
| HZO | `d135056dex21.htm` | 371,013 | none found |
| RAMP | `tm2614904d1_ex2-1.htm` | 336,132 | none found |

ATKR's agreement contains **24 occurrences of "End Date"**, so the term is
defined and the extractor is not reaching its date. The only dated End Date
clause in the document is a capital-expenditure provision — "For the period
after September 30, 2027 until the End Date, the Capex Budget shall be…" — so
the operative date is expressed some other way, most likely as a period from
signing like APGE's "six (6) months". That is an extractor gap, out of scope
here, and now four deals wide.

No cache marker was involved. The (b) hypothesis is a good one in general — a
cache that records absence must be invalidated when the detection method changes
— but `agreement_read` is only set after an exhibit is successfully read, so a
failed lookup leaves no marker and retries on the next scan by construction.

## 2 · CBZ — the proxy path was never wired, and CBZ resolved without it

CBZ now reads `fourth quarter of 2026` in production. **It did not come from the
proxy.** It came from the press release, which the quarter-form pattern fix made
readable:

```
CBZ 8-K body       37,644 chars -> 'TBD'
CBZ press release  22,179 chars -> 'fourth quarter of 2026'   (within the 25,000 cap)
```

So the pattern half of that fix carried CBZ on its own, and that masked the
other half being dead. **`PROXY_CLOSE_DATE_SCAN_CHARS` was defined and never
referenced.** `extract_close_date` had exactly one call site — on `full_ct`, with
the default cap — and `scan_chars` was never passed by anything:

```
grep -n 'extract_close_date('        ->  def (1450)  +  one call site (1953)
grep -n 'PROXY_CLOSE_DATE_SCAN_CHARS' ->  the definition, and nothing else
grep -n 'scan_chars='                 ->  the signature, and nothing else
```

The capability was built and never connected. That is the answer: **only into
the function that was tested.**

Now wired. `close_date_from_proxy(ticker, cik, announced)` runs in the agreement
pass for deals still reading TBD, finds the most recent DEFM14A / PREM14A /
PRER14A filed *after* the announcement, reads it with the proxy cap, and puts
the result through `validate_close_date`. Annual DEF 14As are excluded — they
are governance documents and BOW's and BWMN's were checked last pass and hold no
deal timing. `days_to_close` and `ann` are recomputed from whatever it returns.

Against the live filings:

```
[Proxy] CBZ:  PREM14A 2026-08-27 (896,239 chars) -> 'fourth quarter of 2026'
[Proxy] BOW:  PREM14A 2026-08-28 gave '2027' — REJECTED, too coarse
[Proxy] ATKR: PREM14A 2026-08-28 gave '2026' — REJECTED, too coarse
[Proxy] RAMP: DEFM14A 2026-07-06 gave '2026' — REJECTED, too coarse
```

BOW and ATKR have both filed preliminary proxies since the last pass, which the
earlier search could not have seen.

## 3 · The bare year — three in the feed, and all three rejections are right

`validate_close_date` now requires quarter or half granularity. A year alone
resolves to 31 December and therefore passed every other test while naming a
365-day window, which tells a reader nothing the announcement date did not. An
exact date is exempt: it is finer than a quarter, not coarser.

**Three deals carried one: ATKR `2026`, HZO `2026`, GSAT `2027`.** All three are
now refused, and checking what produced them shows the rule is catching more
than coarseness:

**BOW and ATKR — stray matches from boilerplate.** Their PREM14As are
*preliminary*, with the dates still unfilled as `[•]` placeholders. The years the
extractor found are in mailing-date and share-price sentences:

> "This proxy statement … are first being mailed to the stockholders on or about
> **[•] [•], 2026**."
> "…as compared to the closing share price of the Common Stock as of **July 31,
> 2026**, of $72…"

Neither is close guidance. These would have become `close_date` values, and
through them `days_to_close` and `ann`. The granularity rule refuses them.

**RAMP is different, and worth acting on.** Its DEFM14A states timing precisely:

> "…we currently expect the **Closing to occur by December 31, 2026**."

That is an exact date, not a bare year. `extract_close_date` reduced it to
`'2026'` because its patterns look for qualifier-plus-year forms and have none
for a written-out calendar date in close-guidance context — and
`parse_close_date` only accepts an exact date in ISO form. So the rule correctly
rejects the residue, but the underlying guidance is real, specific, better than
any quarter, and currently being thrown away.

**This is the obvious next fix and I have not made it:** a pattern for
`(?:by|on or before|no later than)\s+<Month> <D>, <YYYY>` in close-guidance
context, plus written-out date support in `parse_close_date`. It is a third
pattern change and the instruction this pass named three items, so it is left
here as a decision. RAMP is the only deal in the feed currently affected.

## Net effect

| Deal | before | after |
|---|---|---|
| CBZ | `TBD` → now `fourth quarter of 2026` | unchanged, and no longer dependent on one source |
| ATKR | `2026` | `TBD` — boilerplate year refused |
| HZO | `2026` | `TBD` — bare year refused |
| GSAT | `2027` | `TBD` — bare year refused |
| RAMP | `TBD` | `TBD` — exact date exists, extractor cannot read it |

Three deals lose a close date and therefore an annualized figure. That is the
intended direction: each was resting on a year-wide window or, for ATKR, on a
sentence about mailing proxies. `TBD` is the honest value for all three.

`test_formulas.py` is at 194 checks.

---

# Written-out close dates, and why four agreements yield no outside date

2026-08-31.

## 1 · An exact date is read, and kept exact

Two patterns added ahead of every period form, handling `Month D, YYYY` and
`D Month YYYY`. `parse_close_date` learned both orders. The result is returned
whole — `December 31, 2026`, resolving to 2026-12-31 — rather than collapsed to
a quarter boundary, because a stated day is better guidance than "Q4 2026" and
rounding it to one throws away the precision that made it worth reading.

Exact patterns run **first**, so a coarser form appearing earlier in the same
document cannot outrank them.

**The anchor is expectation plus close language, inside one sentence.** `[^.]`
cannot cross a period, so an "expect" belonging to an earlier sentence can never
license a date in this one. That is what keeps the boilerplate out, and the
boilerplate is real — three of the four cases below come from live filings:

```
"as compared to the closing share price ... as of July 31, 2026, of $72"   -> TBD
"first being mailed to the stockholders on or about [•] [•], 2026"         -> TBD
"the record date for the special meeting is September 15, 2026"            -> TBD
"until the execution of the Merger Agreement on August 2, 2026"            -> TBD
```

The first carries a date *and* the word "closing" and is still refused, both by
the sentence anchor and by an explicit guard on `clos\w*\s+(?:share|sale|stock)?
\s*price`. The placeholder case is refused structurally: `[•] [•], 2026` has no
month, so `Month D, YYYY` cannot match it. The bare-year granularity rule from
the previous pass is untouched and still catches what gets past these.

### The sweep: one deal, not many

**RAMP is the only deal in the feed whose exact close date was being coarsened.**

```
RAMP  DEFM14A 2026-07-06 (1,196,428 chars)
      "we currently expect the Closing to occur by December 31, 2026"
      was: '2026' -> refused as a bare year
      now: 'December 31, 2026' -> 2026-12-31, 122 days out, ann 6.01%
```

Every other deal states a period, not a day. Re-reading all nineteen proxies:
AES `late 2026`, APGE `third quarter of 2026`, CBZ `fourth quarter of 2026`,
GBTG `second half of 2026`, NATH `first half of 2026`, OGN `early 2027`, PAYO
`mid-2027`, SLAB `first half of 2027`, CZR states nothing. None is an exact
date. So the extractor was not "silently coarsening precise guidance" across the
feed — the precise guidance is rare, and RAMP had the only instance.

**One thing the sweep did expose.** ATKR and HZO carried `2026` from a pattern
that requires no close language whatsoever:

```
pattern #11:  (?:fiscal|calendar)\s+(?:year\s+)?(20\d{2})
ATKR press release  ->  matched "fiscal 2026"
```

Atkore's press release mentions its **fiscal year**. That became the deal's
expected close date. Neither ATKR's nor HZO's press release contains a
close-guidance sentence at all. The granularity rule already refuses the output,
so nothing reaches the feed today — but the pattern manufactures a date from any
mention of a fiscal year and is unsound on its own terms. Narrowing it to
require close language is the obvious follow-up; it is a pattern change, so it
is left here rather than made.

## 2 · The four missing outside dates — all one shape

ATKR, ALOT, HZO and RAMP have agreement readings and no outside date. **All four
define the deadline as a period measured from the agreement date, never as a
calendar date.** Here is what each actually says:

**ATKR** — `atkr_mergerk.htm`, @230,404
> "…(b) by either the Company or Buyer, if: (i) the Effective Time shall not
> have occurred on or before **the first Business Day that is twelve (12) months
> after the date of this Agreement** (the "End Date")…"

**ALOT** — `d100857dex21.htm`, @200,362
> "…(a) if the Merger has not been consummated on or before **the date that is
> one hundred and fifty (150) days after the date of this Agreement** (the
> "Outside Date")…"

**RAMP** — `tm2614904d1_ex2-1.htm`, @270,361
> "…(d) by either Parent or the Company, in the event that the Effective Time
> has not occurred on or before **the date that is twelve (12) months after the
> date hereof** (the "Outside Date")…"

**HZO** — `d135056dex21.htm`, @268,886
> "…(b) by either of the Company or Parent: (i) if the Effective Time shall not
> have occurred on or prior to **the date which is nine months following the date
> of this Agreement** (as such date may be extended pursuant to this Section
> 7.01(b)(i), the "Outside Date")…"

Every `PATTERNS` entry in `outside_date.py` terminates in `_DATE_WORDS` or
`_DATE_SLASH` — a calendar date. None of these four sentences contains one, so
no pattern can match and the module correctly returns nothing rather than
guessing. This is not a near-miss on phrasing; it is a shape the reader was
never built for.

It is distinct from APGE's case, which the module already handles. APGE has a
**dated base** that is then extended by a period — "the End Date shall be
automatically extended by six (6) months" off December 18, 2026. These four have
**no dated base at all**: the period is the definition.

Four variants across four agreements, which is worth noting before anyone writes
one regex for it:

| Deal | phrasing | period |
|---|---|---|
| ATKR | "the first Business Day that is twelve (12) months after the date of this Agreement" | 12 months, rounded to a business day |
| ALOT | "the date that is one hundred and fifty (150) days after the date of this Agreement" | 150 days |
| RAMP | "the date that is twelve (12) months after the date hereof" | 12 months, "hereof" not "of this Agreement" |
| HZO | "the date which is nine months following the date of this Agreement" | 9 months, **spelled out with no numeral** |

HZO is the awkward one: "nine months" has no `(9)` to key on, so a pattern built
around the numeral-in-parentheses convention that `_DURATION` already uses would
miss it. ATKR's "first Business Day that is" also sits between the preposition
and the period.

**What a fix would produce**, using each deal's filing date as the agreement
date:

| Deal | filed | period | outside date |
|---|---|---|---|
| ALOT | 2026-06-17 | +150 days | ~2026-11-14 |
| HZO | 2026-08-10 | +9 months | ~2027-05-10 |
| RAMP | 2026-05-18 | +12 months | ~2027-05-18 |
| ATKR | 2026-08-03 | +12 months | ~2027-08-03 |

Those are computable and would take the feed from 15 of 19 outside dates to 19
of 19. **Not implemented** — the instruction was to show the phrasing before
widening anything, and the four variants above are the argument for looking at
them together rather than patching one at a time. Two further questions belong
with that decision: whether the agreement date is the filing date (it is not
always — the agreement is signed a day or two before the 8-K) and whether the
extension provisos that follow each of these clauses, which `_classify_extension`
would need to read, change the answer.

`test_formulas.py` is at 210 checks.

---

# Anchored patterns, and deadlines defined as a period from signing

2026-08-31.

## 1 · It was not one unanchored pattern, it was four

The group carried its own admission in a comment — *"Standalone qualifier
patterns (no surrounding close language required)"*:

```
\b(Q[1-4]\s+20\d{2})\b
\b((?:first|second|third|fourth|early|mid|late)[-\s]+…20\d{2})\b
calendar\s+year\s+(20\d{2})
(?:fiscal|calendar)\s+(?:year\s+)?(20\d{2})
```

All four now require close, complete or consummate language in the **same
sentence**, in either order, because a date can sit on either side of the verb —
"expected to close in Q3 2026" and "a Q4 2026 closing is anticipated".

This is the third time a pattern matched unrelated text and was caught
downstream. The other two came from this same group: BWMN's `Q2 2026` from an
earnings cross-reference, and ATKR's `fiscal 2026`. Both were stopped later — by
the announcement-order check and by the bare-year rule — which made them
harmless by accident. A pattern that fires on unrelated text and relies on a
later guard is one guard away from shipping.

### What anchoring changed, measured on the real documents

Re-extracting every deal's close date from its own filing, before and after:

| Deal | before | after | |
|---|---|---|---|
| ATKR | `2026` | `TBD` | spurious — from "fiscal 2026" |
| BOW | `second quarter of 2026` | `TBD` | spurious — from its **earnings** release |
| OGN | `2026` | `early 2027` | **improved** — the bare year was masking the real guidance |
| RAMP | `2025` | `2026` | **improved** — it was returning a year in the **past** |

Four changed, and **no real guidance was lost**. Two spurious values removed and
two improved: in both improvement cases an unanchored pattern was firing earlier
in the list and shadowing a correct, more specific reading further down. RAMP
returning `2025` is the clearest illustration — a date before the deal was
announced, produced by a pattern that never checked what it was reading.

## 2 · Deadlines defined as a period from signing

`_relative_deadline` reads the four clauses, `extract_agreement_date` supplies
the anchor, and `extract_outside_date` falls through to them when no dated base
exists. Both number conventions are handled — the numeral in parentheses when
present, the spelled-out word when not.

One bound had to change. `_period` capped every count at 120 regardless of
unit, which was written for months and silently refused ALOT's *"one hundred and
fifty (150) days"*. It is now per unit: 1,100 days, 120 months, 10 years.

### The anchor — all four differ from the filing date

Every one of the four states its own execution date on its cover, and **not one
matches the filing date**:

| Deal | agreement dated | filed | gap | period | outside date |
|---|---|---|---:|---|---|
| ATKR | 2026-08-02 | 2026-08-03 | 1 day | 12 months | **2027-08-02** |
| ALOT | 2026-06-16 | 2026-06-17 | 1 day | 150 days | **2026-11-13** |
| HZO | 2026-08-09 | 2026-08-10 | 1 day | 9 months | **2027-08-09** |
| RAMP | 2026-05-16 | 2026-05-18 | **2 days** | 12 months | **2027-05-16** |

Using the filing date would have moved every one of these deadlines. That is a
small error in days and a real one in kind: the module's whole claim is that the
date comes from the agreement, and a deadline computed off the wrong day is the
invented number it exists to avoid. Where no agreement date can be read,
`_relative_deadline` returns nothing rather than falling back — tested.

### The extension provisos

| Deal | classification | what the agreement says |
|---|---|---|
| ATKR | automatic | proviso extends on failure of the regulatory conditions; names no further date, so the base stands and the deal is marked extendable |
| ALOT | **elective** | a party must act, so the base date governs — the conservative reading the module already applies to dated elective clauses |
| RAMP | automatic | same shape as ATKR |
| HZO | automatic | *"the Outside Date shall automatically be extended by an additional three months"* — and the reported 2027-08-09 already includes it |

**HZO is understated and I want to flag it rather than bury it.** Its proviso
continues: *"the Outside Date may be so extended on no more than two occasions
… (for a maximum Outside Date that is fifteen months …)"*. Two automatic
three-month extensions off a nine-month base gives a true outer deadline of
**2027-11-09**, three months later than what is reported. The module compounds
consecutive automatic periods but found only one occurrence here, because the
count lives in a separate proviso clause rather than in a second extension
sentence.

The error is in the safe direction — the module's stated preference is that
overstating time remaining is the more dangerous mistake — but it is an error.
Reading *"no more than two occasions"* and the stated *"maximum … fifteen
months"* is the fix, and it is a further pattern, so it is recorded here rather
than made.

## The feed reaches 19 of 19

Every live deal now carries an outside date:

```
AES  2027-06-01  ALOT 2026-11-13  APGE 2027-06-18  ATKR 2027-08-02
BOW  2027-04-02  BWMN 2027-05-10  BZH  2027-05-06  CBZ  2027-07-28
CZR  2027-11-27  DSGR 2026-12-31  GBCS 2026-08-31  GBTG 2027-02-02
GSAT 2028-04-13  HZO  2027-08-09  NATH 2026-10-20  OGN  2027-01-26
PAYO 2027-06-12  RAMP 2027-05-16  SLAB 2028-02-04
```

Three of the four new ones come from the period reading; BOW's came free with
the document-type fix, since its agreement was unreadable before that and states
a dated deadline. Four sources are now in use: dated clauses, dated automatic
extensions, period-stated extensions off a dated base (APGE, HZO), and periods
from the agreement date (ATKR, ALOT, RAMP).

ALOT is the one to watch: **2026-11-13, 73 days out**, on a deal whose spread is
0.03% and which looks all but closed. GBCS remains the nearest at 2026-08-31,
which has now passed — worth checking what happened to it.

`test_outside_date.py` gains 11 checks; `test_formulas.py` is at 218.

---

# GBCS lost its deadline on the day the deadline arrived

2026-08-31.

## The cause

One bound, serving two anchors that need different rules:

```python
anchor = announced_date or now
months_out = (d - anchor).days / 30.4
if not (0 < months_out < 42):
    continue
```

Anchored on the **announcement**, `0` is the right floor: a deadline before the
agreement existed is impossible and the candidate is a misread. Anchored on
**today** — which is what `or now` does whenever the announcement date is
missing — `0` means something entirely different. It rejects every date that has
been reached.

GBCS's deadline is 2026-08-31. Today is 2026-08-31. `months_out` was 0, `0 < 0`
is false, the only candidate was discarded, and `extract_outside_date` returned
`None` — no date, no `passed`, no `days_remaining`, no meaning text. The module
has a `passed` branch and past-deadline prose written for exactly this state and
never reached it.

**Why the fallback fired at all.** `filed` arrives as `NaN` on cached rows —
CLAUDE.md already records this, and the call site guards it with
`announced_date=_filed if isinstance(_filed, str) else None`. That guard turns a
missing date into `None`, which is correct in itself, and then `or now` quietly
converts "we do not know when this was announced" into "reject anything not in
the future". Two reasonable-looking lines composing into a data-destroying one.

## The fix

`_plausible(months_out, anchored_on_announcement)` splits the two cases:

| anchor | floor | ceiling | reasoning |
|---|---:|---:|---|
| announcement or agreement date | `0` | 42 months | a deadline before signing is impossible |
| today (no anchor known) | **−24 months** | 42 months | a passed deadline is a state, not a misread |

A deal whose deadline passed two years ago has left the feed by other means; one
whose deadline passed last week is precisely what a holder needs to see.

The call site also stopped depending on `filed`. The agreement states its own
date on its cover and the text is already in hand, so
`extract_agreement_date(_txt)` is passed as a second anchor — GBCS's agreement is
dated 2026-06-18, and with that the plausibility floor is a real one whether or
not `filed` survived the cache.

## GBCS, confirmed

All three anchor paths now resolve identically:

```
date            2026-08-31
passed          True
days_remaining  -1
source          not-consummated-by clause
quote           "shall not have occurred on or before August 31, 2026"
meaning         "This deadline has passed. Either company can now walk away
                 without paying a break fee, so the deal is being kept alive by
                 agreement rather than by contract."
```

Feed re-read: **19 of 19 outside dates, one of them passed.** GBCS is the one,
and it is now visible as passed rather than absent.

That matters beyond the field. GBCS carries score 82 and risk Very Low on the
day its contractual deadline expired, with a 41% modeled drawdown and a $400,000
reverse fee at 2.0%. The score cannot see the deadline — `score_deal` takes no
time input at all, which QA D3 recorded — so the field disappearing was the only
signal left, and it disappeared.

## The same exposure elsewhere — checked, and confined to this field

Every other date-bounded check is anchored on the **announcement**, never on
today, so a value that has merely passed stays:

| Check | bound | past-date exposure |
|---|---|---|
| `validate_close_date` | before announcement / >1,260 days after | **none** — verified: `Q1 2026` on a 2026-01-05 announcement is kept |
| `cap_expected_close` | caps at the outside date | **none** — caps to a passed date without discarding |
| `days_to_close` | none | returns a negative number |
| `annualized_spread` | `days <= 0` | suppresses the **derived figure** only; `close_date` itself survives |
| `_relative_deadline` / `_period` | magnitude per unit | not time-relative |
| `close_date_from_proxy` | skips proxies filed before the announcement | correct — a proxy predating the deal is a different deal's |

`annualized_spread` is the one worth being explicit about, because it looks like
the same shape and is not: refusing to annualize a passed date is right — the
figure would be meaningless — and it deletes nothing. The close date, its
`days_to_close`, and the passed state all remain readable.

So the defect was specific to `outside_date`, and specific to its fallback
anchor. It was reachable on any deal whose `filed` did not survive the cache,
and it destroyed the field's most important state rather than degrading it.

`test_outside_date.py` gains 13 checks covering all three anchor paths, the
`passed` flag, the negative `days_remaining`, the meaning text, and the four
plausibility corners.

---

# The data integrity sweep

2026-08-31. `integrity.py`, run at the end of every scan. **A report, not a
gate** — nothing it prints blocks a deal, changes a value, or fails a scan.

## Why it is a report

Nine real defects were found in the feed this week. **Seven were silent**:
nothing crashed, nothing logged, and every value looked like a number a
merger-arb screen would print. Each was found by someone looking.

The distinction that shapes the design: a test suite asserts what must be true
of *code*. This asserts what is usually true of *data*, which is a weaker and
more useful claim — it flags the unusual and leaves the judgement to a reader. A
finding is a question, and some will have good answers.

It runs on `results` rather than on the cache read-back, because `_filing_text`
is still attached at that point and three of the ten checks need the filing.

## The ten checks

| # | Check | Caught this week |
|---|---|---|
| 1 | `tx_value` against shares × deal price | CBZ at 20x its equity value |
| 2 | spread in band, and consistent with its own `cp`/`dp`/blended | sp_pct off the headline while blended governed |
| 3 | close date after announcement, at quarter granularity | BWMN, ATKR, GSAT |
| 4 | outside date after the agreement date, and whether it has **passed** | GBCS |
| 5 | break price against current and deal price | AES, and now BZH |
| 6 | `deal_type` against consideration language; `acquirer_type` against its acquirer | GSAT |
| 7 | acquirer name appearing in the filing | the enrichment gap |
| 8 | structured field contradicting itself | GSAT's pricing |
| 9 | provenance label disagreeing with the record | `tx_value_source` |
| 10 | missing a field ≥85% of the feed carries | the dropped-write shape |

Each reuses the validator the scan already enforces rather than restating the
rule — `tx_value_plausible`, `validate_close_date`, `two_state_applies`,
`get_acquirer_type`, `validate_enriched_acquirer`, `blended_governs`,
`pricing_integrity_failures`. A sweep whose rules disagree with the pipeline's
is worse than no sweep.

**One deliberate inversion.** A *passed* outside date is reported, and it is not
an error — it is the single most important state that field holds. The report
says so in those terms: *"either party may now walk without a break fee"*.

## What it flags on the current feed

**Four questions across 19 deals.** All four are real; none was previously
surfaced by anything.

```
[Integrity] 4 question(s) across 4 of 19 deal(s) — reported, nothing blocked

  BZH
      break_price    33.46 vs current 33.18 and deal 33.5: the modeled break
                     price is at or above the current price, so there is no
                     downside left for the model to price
  CBZ
      acquirer_type  'Unknown' stored, but 'Grant Thornton Advisors LLC' reads
                     as 'Strategic'
  DSGR
      acquirer_type  'Unknown' stored, but 'LKCM Headwater Investments, LLC'
                     reads as 'Strategic'
  GSAT
      close_date     '2027': too coarse: '2027' names a year with no quarter or
                     half, which is a fragment rather than guidance
```

**BZH is new — a second instance of the AES break-price shape.** Its modeled
break of $33.46 sits above its $33.18 current price, so its two-state
probability is already gated and its position-size row shows a gain where a loss
belongs. Nothing had reported it. AES took a week and a manual audit to find;
BZH took one scan.

**CBZ and DSGR are a new instance of an old shape.** Both carry
`acquirer_type: Unknown` while naming a real acquirer. `Unknown` is what
`get_acquirer_type` returns for `Undisclosed`, and both were `Undisclosed` at
detection — the enrichment pass filled the acquirer in and never recomputed the
type. Same defect as `close_date` not recomputing `days_to_close`, one field
over, and the fourth appearance of the enrichment-ordering shape in CLAUDE.md.

**GSAT** is the known bare year, which clears on the next scan now that
`validate_close_date` refuses it.

## What it does not flag, and why that took a correction

The first run produced **24 findings, 20 of them false**. Every deal without a
`pricing` or `direction` object was reported as "present but empty — the shape a
dropped write leaves behind". They were empty because `/api/deals` runs every
structured field through `parse_structured`, which turns an absent value into
`{}`. The check was reading an artifact of the serialisation layer as evidence
of data loss.

That is precisely the failure mode a report like this dies of: twenty lines of
noise and nobody reads the four that matter. Emptiness is now the ubiquity
check's job — a field is worth asking about when **most of the feed has it and
this deal does not** — and the structured-field check looks only for
self-contradiction: barriers passed with no blended price, an outside date
naming no date, a commitment naming no terms.

The ubiquity threshold is 0.85 rather than 0.90 because the feed is small: at
nineteen deals, 17 of 19 is 89.5% and would slip under a 0.90 bar — which is
exactly the case worth catching. The finding prints the ratio, so a reader can
discount it.

`test_integrity.py` covers all nine defect shapes plus the false-positive
regression, 21 checks.

---

# Following the sweep's first findings

2026-09-01. The sweep flagged four things on its first run. This is what each
turned out to be.

## GBCS — the deadline passed, and the deal is alive

The outside date now renders in production: `2026-08-31, passed=True,
days_remaining=-2`. The fix works.

What happened at the deadline is answerable from EDGAR, and it is the best
possible validation of the meaning text. **Black Pearl filed an SC TO-T/A on
2026-08-31 — the outside date itself:**

> "BLACK PEARL EXTENDS TENDER OFFER FOR ALL OUTSTANDING SHARES OF SELECTIS
> HEALTH, INC."

That is the sixth amendment since 2026-08-03, roughly weekly. The stock closed
5.45 on the deadline against a 5.75 offer — holding, not collapsing.

The module's past-deadline prose says: *"Either company can now walk away
without paying a break fee, so the deal is being kept alive by agreement rather
than by contract."* That is exactly what the filing record shows. The deadline
passing was real and the parties chose to extend anyway.

**And the product still cannot see any of it.** GBCS reads score 82, risk Very
Low, two days past its contractual deadline, with six tender-offer extensions on
file. `score_deal` takes no time input at all (QA D3), and nothing reads
SC TO-T/A amendments. This is the milestone detection the roadmap calls its
biggest unlock (§12), and GBCS is a clean worked example of what it would catch:
seven filings, each one a dated event, none of them read.

## CBZ and DSGR — fixed. The enrichment-ordering shape, a fourth time

Both carried `acquirer_type: Unknown` while naming a real acquirer. `Unknown` is
what `get_acquirer_type` correctly returns for `Undisclosed`, and both were
`Undisclosed` at detection. The enrichment pass then filled the acquirer in and
never recomputed the type.

Same defect as `close_date` not recomputing `days_to_close`, one field over. The
enrichment pass now recomputes `acquirer_type` whenever it writes `acquirer`, and
logs the transition:

```
[Enrich] CBZ acquirer: Grant Thornton Advisors LLC (acquirer_type Unknown -> Strategic)
```

CBZ and DSGR both become `Strategic` on the next scan. This is the **fourth**
appearance of a field written after its consumers have run, and the pattern is
now explicit enough to state as a rule: *any field derived from another must be
recomputed wherever the source is written, not only where it is first set.*

## BZH — a decision, and not the shape AES was

The sweep flagged `break_price 33.46` against a `33.18` current price. The
instinct is that this is a second AES. **It is not**, and the price series says
so plainly:

```
2026-04-05  19.88      2026-07-05  28.07
2026-05-03  20.63      2026-07-26  33.19
2026-06-07  25.96      2026-08-02  32.10
2026-06-28  29.20      2026-08-06  33.46   <- stored break price
                       2026-08-07  ANNOUNCEMENT
2026-08-09  33.18      2026-08-23  33.13
2026-08-16  33.10      2026-08-30  33.22
```

AES ran up 23% in four weeks and then **fell 17.8% on the announcement** — the
signature of speculation disappointed. BZH climbed steadily for four months and
**did not move on the announcement at all**, then traded flat at the deal price.
Those are opposite shapes.

The filing explains why, and it is the finding worth keeping:

> "Beazer shareholders will receive $33.50 in cash for each share … representing
> an implied purchase price-to-book multiple of **0.8x**."

**The press release states no premium anywhere.** $33.50 against a $33.46
pre-announcement close is a premium of **0.1%**, and the deal values Beazer
*below book*. A merger at essentially zero premium is unusual enough to be the
headline fact about this deal, and the product currently shows none of it.

**What I have not done, and why.** No hand-verified unaffected price. AES had
one because its series proved contamination — a flat range, a sharp spike, a
collapse on announcement. BZH's 68% climb over four months could be deal
anticipation or could be a homebuilder re-rating, and the price series cannot
separate them. That is the conclusion the AES sweep already reached for the feed
at large, and inventing a number here would be the error that finding exists to
prevent. Unlike AMPS and VOXX, this filing offers no unaffected-price reference
to anchor on.

Two options, both requiring your judgement:

- **Leave it.** The two-state model is already gated, so no false probability is
  published. The cost is that BZH's downside reads as `+0.8%` — a gain — in the
  position-size table, which the sign fix renders honestly but which is still
  built on a break price nobody believes.
- **Hand-verify against the sale process.** Beazer's proxy, when it appears, will
  likely state when the process began. The unaffected price is the price before
  that date, and that is a filing fact rather than a price-shape inference.

## One check the sweep should probably gain

BZH would have been caught earlier by a rule the sweep does not have: **deal
price barely above the pre-announcement price**. A merger at a 0.1% premium is
either a real no-premium deal, a wrong `dp`, or a contaminated break price — all
three worth a question. It generalises, it needs no new data, and it is one line.

Not added, because the sweep was specified as "the things that have caught real
errors this week" and this would be extending it on my own judgement. Offered.

---

# The premium — checked, and shown

2026-09-01.

## 1 · The sweep gains a premium check

A deal price at or barely above the pre-announcement price, threshold 5%. Three
different things produce that shape and all three are worth a question: a
genuine no-premium deal, a wrong `dp`, or a break price that absorbed the run-up
it was supposed to exclude.

**Across the feed it flags one deal: BZH at 0.1%.** The separation is as clean
as the `tx_value` ratio calibration was — the next-lowest real premium is CZR at
7.7%, half as far again from the bar:

```
BZH   0.1%  THIN      CBZ   17.8%      HZO   48.5%
CZR   7.7%            GSAT  23.5%      APGE  49.5%
AES   9.1%            OGN   24.7%      BWMN  57.9%
PAYO  9.6%            DSGR  27.4%      GBTG  60.2%
BOW  11.1%            RAMP  29.8%      SLAB  69.1%
NATH 11.1%            ATKR  30.7%      ALOT  73.8%
                                       GBCS  79.7%
```

Nothing else in the sweep would have caught BZH. Its spread, close date and
transaction value are all unremarkable; only the relationship between the deal
price and the break price is odd, and no existing check looked at it.

## 2 · The premium is on the deal page, with what it means

`deal_premium()` produces `{value, basis, reference, thin, caveat}` during the
scan, where `_filing_text` is still attached.

**A stated premium wins.** `extract_stated_premium` reads the filing's own
figure and, importantly, the reference attached to it — *"a premium of
approximately 42% to the closing price on March 3, 2026"* yields both the 42%
and the date the buyer treated as unaffected. That is a filing fact, where our
break price is a lookup that AUDIT #8 shows is not a model at all. Where no
premium is stated, it computes against the modeled break price and **says so**:

```
BZH   +0.1%  computed
      "against the modeled break price of $33.46 (historical) —
       the filing states no premium"
      "The buyer is paying at or barely above market."
```

**§30C is carried with the number, not left to the reader.** Every rendering
of the premium is followed by:

> Premium measures standalone downside and how motivated holders are to vote
> yes. It is not evidence the deal will close, and says nothing about buyer
> commitment, termination rights or regulatory risk.

It sits beside Gross Spread in the metric row, which is where the context
belongs — a 0.32% spread reads very differently at a 60% premium than at 0.1%.

### One §30C violation removed on the way

The existing "Deal Premium" row painted itself **teal at 25% or above**:

```js
c: (premium!==null && premium>=25 ? '#5fe0c9' : '#e2d8c0')
```

Teal is the colour this product uses for a good outcome. That is precisely the
"premium size means safety" inference §30C says to audit out, expressed in CSS
rather than in prose. The premium now has no colour scale at all. Thinness is
called out in words, because "the buyer is paying at or barely above market" is
a fact about downside, not a verdict about closing.

**A second, larger one is left alone and flagged.** `score_deal_premium` awards
+8 for a premium of 50% or more, sliding to **−5 below 5%** — premium size
feeding the risk score directly. BZH's 0.1% costs it five points on a 153-point
scale, which is §30C's exact complaint. Changing score weights is §9/§30 work
and touching them here would layer a correction on six unvalidated factors, so
it is recorded rather than made.

## What BZH now shows, and what it still does not

The deal page now says a buyer is paying 0.1% over market for a company valued
at 0.8x book, that the figure is computed rather than stated because the filing
states no premium, and that this measures downside rather than likelihood.

**Its break price is untouched, as instructed.** The tape cannot separate deal
anticipation from a homebuilder re-rating over BZH's four-month, 68% climb, and
the filing offers no unaffected-price reference to anchor on — unlike AMPS and
VOXX, where the premium statement supplied one. Revisit when Beazer's proxy
appears: a merger proxy's background-of-the-merger section dates the start of
the process, and the price before that date is a filing-anchored unaffected
price rather than a price-shape inference.

## The rest of the sweep, this run

```
[Integrity] 4 question(s) across 3 of 19 deal(s)

  BZH   break_price   33.46 vs current 33.19 and deal 33.5 — no downside left to price
        premium       0.1% (computed) — at or barely above market
  GBCS  outside_date  2026-08-31 has PASSED (2 days ago)
  GSAT  close_date    '2027' — a year with no quarter or half
```

CBZ and DSGR have cleared. Both now read `acquirer_type: Strategic` in
production — not because the fix deployed, but because this scan had their
acquirers cached and known at construction, so the type computed correctly on
the normal path. The fix still matters for the case that produced the defect:
an acquirer arriving mid-scan from enrichment.

`test_integrity.py` is at 36 checks.

---

# Which date drives the annualized figure — diagnosis

2026-09-01, against the live feed (fetched 16:04). **No code changed.**

## 1 · Missing spreads and annualized figures

**Category 3 is empty. There is no wiring gap.** Every missing `ann` has a
correct reason, and no deal is missing `sp_pct`.

| Deal | `sp_pct` | `ann` | `dtc` | Why |
|---|---:|---:|---:|---|
| AES | 1.59 | 2.75 | 211 | — |
| ALOT | 0.03 | **—** | 29 | **below the 30-day floor** |
| APGE | 0.02 | **—** | 29 | **below the 30-day floor** |
| ATKR | 1.41 | **—** | — | **no close date** (TBD) |
| BOW | 1.27 | **—** | — | **no close date** (TBD) |
| BWMN | 0.93 | **—** | — | **no close date** (TBD) |
| BZH | 0.92 | 2.78 | 121 | — |
| CBZ | 1.04 | 3.14 | 121 | — |
| CZR | 4.45 | 3.59 | 452 | — |
| DSGR | 0.65 | **—** | — | **no close date** (TBD) |
| GBCS | 5.50 | **—** | −1 | **close date passed** |
| GBTG | 0.37 | 1.12 | 121 | — |
| GSAT | 4.84 | 3.63 | 486 | — |
| HZO | 1.62 | **—** | — | **no close date** (TBD) |
| NATH | 4.20 | 31.29 | 49 | — |
| OGN | 1.67 | 2.89 | 211 | — |
| PAYO | 4.08 | 5.24 | 284 | — |
| RAMP | 1.97 | 5.94 | 121 | — |
| SLAB | 5.55 | 6.71 | 302 | — |

```
no close date          5    correct, the em-dash stays
close date passed      1    correct
below the 30-day floor 2    correct
close date but no ann  0    <- the category that would have been a bug
sp_pct missing         0
annualizing            11
```

ALOT and APGE both sit at 29 days — one day under the floor. That is the floor
doing its job rather than a near-miss worth tuning: at 29 days the multiplier is
12.6x, and ALOT's 0.03% spread would print as 0.38%.

## 2 · Which date produced the horizon

**Ten of fourteen use the stated expected close. Four use the outside date.**
Not most, which is the first thing worth saying.

| Deal | `ann` shown | horizon | source |
|---|---:|---:|---|
| AES | 2.75% | 211d | stated expected close |
| BZH | 2.78% | 121d | stated expected close |
| CBZ | 3.14% | 121d | stated expected close |
| **CZR** | **3.59%** | **452d** | **outside date (capped)** |
| **GBCS** | — | **−1d** | **outside date (capped)** |
| GBTG | 1.12% | 121d | stated expected close |
| GSAT | 3.63% | 486d | stated expected close |
| **NATH** | **31.29%** | **49d** | **outside date (capped)** |
| OGN | 2.89% | 211d | stated expected close |
| **PAYO** | **5.24%** | **284d** | **outside date (capped)** |
| RAMP | 5.94% | 121d | stated expected close |
| SLAB | 6.71% | 302d | stated expected close |
| ALOT | — | 29d | stated expected close |
| APGE | — | 29d | stated expected close |

### The scale of the distortion — one deal, not the feed

The cap binds only where guidance resolves *past* an automatic or fixed
deadline. Comparing what each capped deal shows against what its own guidance
would give:

| Deal | to guidance | to outside date (shown) | inflation |
|---|---:|---:|---:|
| **NATH** | **12.67%** (121d) | **31.29%** (49d) | **2.5x** |
| PAYO | 4.93% (302d) | 5.24% (284d) | 1.06x |
| CZR | 3.34% (486d) | 3.59% (452d) | 1.07x |
| GBCS | — | — (passed) | n/a |

**NATH is the only material case.** Its guidance is "H2 2026" — a six-month
window — and its deadline of 20 October falls early inside it, so the cap cuts
121 days to 49 and the annualized figure runs from 12.67% to 31.29%. CZR and
PAYO are within 7%, because their deadlines sit only a few weeks before their
guidance ends.

So the concern is right in kind and much narrower in degree: **the systematic
overstatement is one deal wide**, and it is one deal wide because the
end-of-period convention only diverges badly from the deadline when the guided
period is very wide.

### One thing the diagnosis confirms is working

OGN's outside date (2027-01-26, 147 days) is **earlier** than its guidance (211
days) and it is **not** capped, because that deadline is *elective* — a party
must act to reach it. That was the rule chosen when the cap was built, and it is
holding: OGN annualizes at 2.89% against guidance, not at 4.15% against a
deadline nobody is obliged to hit.

### And one framing correction

Annualizing to the outside date does **not** systematically overstate. For 8 of
the 12 deals carrying both figures, the *guidance* number is the higher one,
because the deadline usually falls **later** than the guided period ends:

```
guidance higher   AES  BZH  CBZ  GBTG  GSAT  RAMP  SLAB   (and APGE, ALOT)
outside higher    CZR  NATH  OGN  PAYO
```

RAMP is the sharpest: 5.94% to its stated 31 December close, 2.80% to its 2027
deadline. So "annualize to the deadline" is not a conservative choice — it is
sometimes conservative, sometimes not, and which it is varies per deal. That is
itself an argument against picking either one.

## 3 · What I would change

**Show both figures. I am for it, with one constraint on the labels.**

The case for is what the table above shows: the two numbers diverge by more than
2x on RAMP, SLAB and NATH, and which is larger flips between deals. A single
number cannot carry that, and choosing which to show is exactly where the NATH
artifact came from — a horizon picked for being knowable rather than right,
which is the GBCS 2,222% shape one step less extreme.

**The constraint: neither may be called "expected".** The guidance figure is
computed off a period *end* — "H2 2026" becomes 31 December — so it is already a
bound, not an expectation. Labelling it "to expected close" beside "to outside
date" would imply one is a forecast and the other a limit, when both are limits.
They should read as what they are:

```
Annualized    +12.67%  by guidance (H2 2026)
              +31.29%  by the 20 Oct 2026 deadline
```

**The case against, which I do not think wins.** Two precise-looking numbers
invite a reader to take the flattering one, and §31 is specifically about false
precision. A skimmer sees NATH's 31%. But that risk exists today in worse form —
the feed currently shows *only* the 31%, with nothing to compare it against.
Two bounds with their dates attached is strictly more honest than one bound with
its basis hidden.

**What I would not do:** stop capping the close date. The cap is correct for the
*displayed* close date — a deal genuinely cannot close after a deadline it
cannot pass — and NATH showing "expected close 31 December" against a 20 October
deadline was the impossibility it was built to remove. The fix is to stop
feeding the capped date into the annualization, not to stop capping.

**Ordering, if you want it in stages.** Showing both figures makes the capping
question moot for the annualized number, so it subsumes the smaller fix rather
than competing with it. If only one change is wanted, it is that one.

---

# Two bounds on the annualized return

2026-09-01. Implemented as diagnosed.

## A correction to the record, first

The premise that annualizing to the deadline **systematically** overstates was
wrong, and it is worth stating plainly because the fix would have been different
if it were right. For 8 of the 12 deals carrying both figures the **guidance**
number is the higher one, because a deadline usually falls *later* than the
guided period ends. RAMP is 5.94% to its stated 31 December close and 2.80% to
its 2027 deadline — the deadline figure is less than half.

Which bound is larger flips per deal, and that is the strongest argument for
showing both. Neither is reliably the conservative one, so "pick the safe one"
was never available as an answer.

## What changed

`annualized_bounds(deal)` returns `{guidance, deadline, basis}`, each slot
carrying `value`, `days` and `date`.

**The guidance bound reads the raw `close_date`, never the capped one.** The cap
remains, and it still governs the *displayed* close date — NATH showing an
expected close of 31 December against a 20 October deadline was the
impossibility it was built to remove, and the page now renders
`Oct 20, 2026 (capped at the deadline)`. What the cap no longer does is drive
the annualized figure, because a capped date asserts the deal closes *on* its
deadline, which is the least likely single outcome rather than the expected one.

**Neither bound is called "expected".** They read `to guidance` and
`to deadline`. Guidance resolves to a period *end* — "H2 2026" becomes 31
December — so it is a bound; the outside date is the day either party may walk,
which is also a bound. Naming either a forecast would imply precision the
product does not have.

**§31 is answered in the presentation, not by choosing.** Both figures render at
identical size and colour, neither highlighted, in the same row, with the
horizon in days beside each:

```
Annualized   +12.67%  to guidance · 121d
             +31.29%  to deadline · 49d
```

The 31.29% stops looking like a better deal the moment the 49 is next to it. A
reader who wants the larger number has to read the shorter horizon to get it.

Where only one bound exists it is shown alone and named — `+1.59% to deadline ·
335d`. The missing one is never synthesised. The 30-day floor applies per bound,
so ALOT's 29-day guidance is suppressed while its 73-day deadline bound stands.

The ticker and the dashboard have one slot each; they take the guidance bound
where it exists, the deadline bound otherwise, and **always name which**, so a
lone figure is never unlabelled.

## Before and after, every deal

Computed 2026-09-01 against the live feed.

| Deal | before | to guidance | to deadline | basis |
|---|---:|---:|---:|---|
| AES | 2.70 | 2.70% (211d) | 2.09% (273d) | both |
| ALOT | — | — | 0.15% (73d) | **deadline** |
| APGE | — | — | 0.03% (290d) | **deadline** |
| ATKR | — | — | 1.59% (335d) | **deadline** |
| BOW | — | — | 1.99% (213d) | **deadline** |
| BWMN | — | — | 1.37% (251d) | **deadline** |
| BZH | 2.71 | 2.71% (121d) | 1.33% (247d) | both |
| CBZ | 3.26 | 3.26% (121d) | 1.19% (330d) | both |
| CZR | 3.62 | 3.36% (486d) | 3.62% (452d) | both |
| DSGR | — | — | 2.59% (121d) | **deadline** |
| GBCS | — | — | — | none — both dates passed |
| GBTG | 1.27 | 1.27% (121d) | 1.00% (154d) | both |
| GSAT | 3.44 | 3.44% (486d) | 2.83% (590d) | both |
| HZO | — | — | 1.80% (342d) | **deadline** |
| **NATH** | **32.78** | **13.27% (121d)** | **32.78% (49d)** | both |
| OGN | 3.01 | 3.01% (211d) | 4.32% (147d) | both |
| PAYO | 5.44 | 5.11% (302d) | 5.44% (284d) | both |
| RAMP | 5.43 | 5.43% (121d) | 2.56% (257d) | both |
| SLAB | 6.55 | 6.55% (302d) | 3.80% (521d) | both |

**11 with both bounds, 7 with a deadline bound only, 1 with neither.**

**Seven deals gain a figure they did not have.** ATKR, BOW, BWMN, DSGR and HZO
state no close date, so they showed an em-dash; each has a readable contractual
deadline and now carries an honest bound against it. ALOT and APGE were
suppressed by the 30-day floor on guidance and now show their deadline bound.
This is the second dividend of reaching 19 of 19 outside dates.

GBCS shows neither, correctly: its guidance resolved to a date that has passed
and its deadline expired on 31 August.

### NATH, as asked

At the spread the diagnosis table used (4.20):

```
to guidance   +12.67%   121d   2026-12-31
to deadline   +31.29%    49d   2026-10-20
```

Confirmed against the exact figures. The live feed reads 13.27% / 32.78% because
the spread has since moved to 4.40 — the same two bounds, repriced.

The 31.29% no longer stands alone. It is still there, still the larger number,
and now sits beside the 121-day figure and its own 49-day horizon, so a reader
can see it is a deadline case rather than a return expectation.

## What did not change

`sp_pct`, the break price, the close-date cap on display, and the 30-day floor.
Only the annualized figure's inputs and presentation moved.

`test_formulas.py` is at 231 checks, 13 of them new: NATH's two bounds and their
horizons, the cap not reaching the guidance bound, RAMP and NATH proving the
larger bound flips, single-bound cases in both directions, neither-available,
and the floor applying per bound.

---

# The deadline is visible, and the deferred list is in one place

2026-09-01. Last work before §30.

## 1 · The outside date was never rendered

The instruction was to make the passed state prominent. Checking the template
first turned up something larger: **`outside_date` appears nowhere in the UI at
all.** Nineteen of nineteen deals carry one, each quote-backed, each with a
`passed` flag, an extension type and written meaning text — and none of it
reached the page. Seven turns of extraction work, invisible.

So this is not "make it prominent", it is "render it". `_daDeadline(deal)` now
draws a block under the metric row in three states:

```
GBCS   CONTRACTUAL DEADLINE PASSED       red, filled
       Aug 31, 2026 · 2 days ago · no extension clause
       "This deadline has passed. Either company can now walk away without
        paying a break fee, so the deal is being kept alive by agreement
        rather than by contract."
       > shall not have occurred on or before August 31, 2026

NATH   CONTRACTUAL DEADLINE APPROACHING  amber, ≤60 days
       Oct 20, 2026 · 49 days remaining · extends automatically

GSAT   CONTRACTUAL DEADLINE             neutral
       Apr 13, 2028 · 590 days remaining · extends automatically
```

GBCS's meaning text is not a hypothetical. Black Pearl filed its sixth tender
extension on 31 August — the deadline itself — so "kept alive by agreement
rather than by contract" is a description of what the filing record shows.

**And an empty annualized field now says why it is empty.** Both bounds absent
because both dates passed reads differently from both bounds absent because no
date was ever stated, and the two looked identical:

```
GBCS   not annualizable · the deadline has passed
ATKR   no stated close date
```

A deal past its contractual deadline no longer looks like a deal with 300 days
of runway. The score still says Very Low, which §9 owns — but the page now
carries the fact beside it rather than leaving the score to speak alone.

## 2 · The §30C conflict, documented where it lives

`score_deal_premium` carries a docstring naming what it is: §30C in scoring
form, paying +8 for a premium of 50% or more and charging −5 below 5%, which is
a claim that a bigger premium means a safer deal. The live cost is named too —
BZH −5 for being a genuine no-premium deal — along with why it is not fixed in
isolation. **The weights are unchanged.**

## 3 · The four deferred §9 corrections, collected

ROADMAP.md §9 now lists them together rather than leaving them scattered:

| # | Correction | Live cost today |
|---|---|---|
| 1 | premium band treats size as safety | **BZH −5** |
| 2 | `deal_type` pays +10 All Cash vs +5 PE | **GSAT −5**, typed PE with Amazon buying |
| 3 | the score has no time input at all | **GBCS 92, Very Low, two days past its deadline** |
| 4 | spread double-counted — 39% of the range, then the risk gate | structural, AUDIT #10 |

**This is the fourth, so by the rule agreed, §9 moves up the order.** Items 1–3
each leave a specific wrong number on a specific deal right now.

One correction to my own earlier report: GBCS scores **92**, not 82. It has
risen since, which makes the point sharper rather than softer.

## What else in the feed is known wrong and deferred

Everything below is a value currently displayed that we know is not right, with
the section that owns it. Verified against the live feed today, not recalled.

**Specific to one deal**

| Deal | Value | Why it is wrong | Owner |
|---|---|---|---|
| BZH | `break_price` 33.46 vs `cp` 33.20 | above the current price, so no downside is left to price; probability correctly gated, position table shows a gain | §4, revisit on Beazer's proxy |
| GSAT | `deal_type` Private Equity | Amazon is the acquirer; also costs 5 score points | §9 item 2 |
| HZO | `outside_date` 2027-08-09 | the proviso allows **two** automatic three-month extensions to a stated 15-month maximum, so the true outer deadline is 2027-11-09 | outside_date |
| GBCS | `score` 92 / Very Low | two days past its deadline | §9 item 3 |
| BZH | `score` −5 from the premium band | genuine no-premium deal | §9 item 1 |

**Across the feed**

| Field | State | Why it is wrong | Owner |
|---|---|---|---|
| `break_price` | 18 of 19 `historical` | a pre-announcement close lookup rendered as "Modeled downside case"; the word models nothing | §4, AUDIT #8 |
| `financing_signal` | 10 of 19 `unknown` | read from the press release while `check_financing` reads the agreement and is not consulted | §30A, AUDIT #16 |
| `reg_tags` | all 19 | size-and-sector priors computed at detection, never regulatory status — a cleared deal and one facing a second request tag identically | §12, QA C3 |
| `tx_value` | 14 `regex_enterprise`, 4 `equity_calc_approx` | enterprise and equity value under one label, so the RTF percentage is not comparable across deals | AUDIT #15 |
| `cp` | all 19 | a daily close with no as-of date attached, labelled "current" | §8, AUDIT #1 |

**Not on this list, and worth saying why.** The bare-year close dates, the
stale `acquirer_type`, the capped annualization, the missing outside dates and
the dropped enrichment readings were all on it a week ago and are now fixed. The
list above is what remains, and every entry has a section that owns it rather
than sitting unassigned.

Nothing here is a surprise to the sweep either: `integrity.py` flags BZH's break
price and premium, and GBCS's passed deadline, on every scan. The rest are
systemic rather than per-deal, which is why they read as roadmap items and not
as findings.


---

# The last plain bug, and a sweep for invisible fields

2026-09-01. Final work before §30.

## 1 · HZO was one of three, not one

HZO's agreement reads nine months, then "the Outside Date shall automatically
be extended by an additional three months", then — the part that was never
read — "provided, that the Outside Date may be so extended on **no more than
two occasions** pursuant to this sentence (for a **maximum Outside Date that is
fifteen months** from the date of this Agreement)".

`_duration_extension` compounded *textual occurrences* of a period. The
agreement states its extension once and permits it twice, so one occurrence was
found and applied once: 9 + 3 = 12 months. The contract states the answer
outright and nothing read it.

Sweeping the other three period-from-signing deals as asked found **two more of
the same family**, each missed by a different gap:

| Deal | What the agreement says | Read as | Actually |
|---|---|---:|---:|
| HZO | +3 months, **two occasions**, max **fifteen months** | 2027-08-09 | **2027-11-09** |
| ATKR | extended **to** 15 months, then again **to** 18 months | 2027-08-02 | **2028-02-02** |
| RAMP | "extended **for all purposes hereunder** by a period of three (3) months" | 2027-05-16 | **2027-08-16** |
| ALOT | elective, one occasion, 30 days | 2026-11-13 | 2026-11-13 — correct |

Three distinct causes:

1. **Permitted repeats were never counted.** `_repeats` now reads "no more than
   two occasions", and `_stated_maximum` reads the agreement's own outer bound
   — but only when anchored to the agreement date, because an unanchored
   maximum names no base to count from. Both give fifteen months for HZO, which
   is the cross-check.
2. **`_DURATION` required "extended by" adjacently.** RAMP puts five words of
   boilerplate in between and the entire clause was invisible. The filler
   allowed is lowercase letters and spaces only, so it cannot cross a comma into
   an unrelated period.
3. **An extension can be a destination, not an increment.** ATKR runs "to the
   first Business Day that is fifteen (15) months after the date of this
   Agreement", then "again to ... eighteen (18) months". `_ABS_EXTENSION` reads
   these and counts them **from signing**; adding eighteen months to the base
   date would have reported 2029.

Among automatic mechanisms the latest date governs, for the same reason a dated
automatic extension governs over the base it replaces. Elective is untouched:
someone must act, so the base still stands and the option is reported beside it.

**Verified by re-reading all nineteen filings against production: 3 moved, 16
unchanged, 0 skipped.** Eight new regression tests, including three that assert
an unrelated "Maximum Premium" or "maximum levels" is not read as a deadline.
All six suites pass.

One process note. My first pass called RAMP unchanged — on a document fetched
with a CIK I had guessed rather than looked up. EDGAR served *something* at that
path and the extractor returned null, which contradicted the sweep and is the
only reason I caught it. Same error shape as BOW and DSGR earlier. The correct
CIK is 0000733269, and RAMP was understated like the other two.

## 2 · What else is computed, stored, and rendered nowhere

The outside date was extracted, validated and invisible for seven turns. Asking
what else is in that state: of **42 fields on a live deal record, 13 appear
nowhere in the template.**

**A. Accumulated history nobody can see** — the closest match to the outside
date's shape, and the largest finding.

| Field | Populated | What it is |
|---|---|---|
| `spread_history` | 19/19 | every scan's spread and price, a growing time series |
| `score_history` | 19/19 | every scan's score and risk band |
| `sp_pct_at_detection` | 19/19 | the spread when the deal was first found |
| `score_at_detection` | 19/19 | the score when it was first found |
| `risk_at_detection` | 19/19 | the risk band when it was first found |

Every one is on all nineteen deals and grows on every scan. Together they answer
"is this deal better or worse than when we found it", which the page cannot
currently ask. The `*_at_detection` trio is what CLAUDE.md records as the
**detection-value freeze** — a bug found, fought and fixed, and the result has
never been shown to anyone.

**B. Provenance labels** — `break_price_method` (19/19), `tx_value_source`
(19/19), `acquirer_source` (3/19), `close_date_source` (1/19). §7 groundwork,
not implemented here as instructed. Worth one observation: the page renders
"Modeled downside case" while `break_price_method` says `historical` on 18 of
19. The field that would correct that label is already on the record.

**C. The headline gap** — `sp_pct_headline` (1/19, GSAT) is the pre-blended
spread, kept deliberately "so the gap stays auditable". It is auditable in the
JSON and invisible on the page, which is where the gap would matter.

**D. Correctly invisible** — `accession`, `agreement_read` (EDGAR bookkeeping)
and `ann_basis` (internal to the bounds renderer). No action.

Three further fields are referenced exactly once and are fine: `acquirer_type`,
`break_downside`, `close_date_capped_to`.

**No change was made to any of this.** It is an inventory, as asked.

## 3 · Nothing is left before §30

The deferred list is now entirely sectioned, with no unassigned remainder:

| Item | Owner |
|---|---|
| the four scoring corrections | §9 — moved up, four accumulated |
| `break_price` as a lookup labelled "modeled" | §4 and §20 |
| `financing_signal` read from the press release | §30A |
| `reg_tags` as priors, `tx_value` basis mixing, `cp` staleness | §20 |

HZO was the only plain bug on it and it is fixed — along with the two the sweep
turned up beside it. **There is no pre-work left.**


---

# §20 and §9: labels that match their sources, and a score that can be read

2026-09-01. Done together, because the score was wrong partly because it
consumed fields that claimed to be measurements and were not.

## §20 · Fact, model, inference, forecast

`provenance.py` classifies every displayed value and the page renders the class
as a badge with the reason in its tooltip. The rule that makes it more than
decoration: **a field is classified by where its value actually came from, not
by where it is displayed.** All five live mismatches flattered the value.

| Field | Was | Is | What changed |
|---|---|---|---|
| `break_price` | "Modeled downside case" | **FACT** | it is a lookup of the pre-announcement close on 18 of 19 deals. The price is a fact; that the stock returns to it on a break is the inference. The card now says which is which. |
| `financing_signal` | press-release keyword scan | **FACT** when read from the agreement, **INFERENCE** otherwise | the agreement reading now supersedes the press release, and the label says which one spoke |
| `reg_tags` | agency names implying a docket | **INFERENCE** | the panel states they are the expected review path from deal size and sector, **not filed regulatory status** |
| `tx_value` | one label over two quantities | **FACT** or **MODEL** per deal | 14 filed enterprise values, 4 computed equity values, now distinguishable |
| `cp` | "Current Price" | **FACT**, "Last Close" | a daily close is a fact about yesterday, not a live quote |

### The financing scan was inverted on four deals

The phrase "financing condition" appears in the sentence that grants one and in
the sentence that denies one, and the old scan matched the substring in both.
Two live filings say the exact opposite of what they were scored:

```
HZO   "The obligations of Parent and Merger Sub to consummate the Merger are
       NOT subject to any financing condition."          -> scored contingent, -10
DSGR  "The availability of financing is NOT a condition to the obligations of
       Parent ... to consummate the Merger."             -> scored contingent, -10
```

CZR and GBTG were stored `contingent` on filings that read `committed` too. The
scan is now negation-aware, and every one of the four re-reads as `committed`
against its own filing — verified individually, not assumed. Worth **+15 points
each** on the next scan.

`check_financing` had been parsing the agreement's financing condition all
along and its verdict was never consumed. `financing_from_commitment` now uses
it, and an UNKNOWN verdict deliberately carries no information rather than
overwriting the weaker reading with silence.

## §9 · Explanation with evidence, not eight weighted sub-scores

Eight weighted categories cannot be validated by 39 deals with 4 failures, so
`explain.py` returns each category as **evidence and a verdict in words, with no
number**. Two rules hold it honest, and both were written because the first
draft broke them:

1. **No verdict without evidence.** GBCS rendered "Contractual protection:
   weak" citing nothing — the exact failure this section exists to prevent.
2. **No claim of absence while citing something.** SLAB rendered "Financing:
   strong" whose only supporting line read *"no financing language found"*.
   A term whose meaning is a statement that nothing was found is not evidence,
   and a fifth verdict state — `evidence, no verdict` — now separates "we read
   the clause and it is silent" from "we found nothing".

Across 19 deals × 8 categories: **zero verdict/evidence contradictions**, 42
rows carrying no evidence and saying so plainly.

### The four deferred corrections

**1. The premium band no longer scores.** `score_deal_premium` returns 0 for
every deal. The bands are described in the docstring rather than kept in code,
because the objection is not that they were mistuned — it is that premium size
has no bearing on whether a deal closes. A tuned version of a wrong input is
still a wrong input. The premium is still computed, still shown, and now appears
in the Market row as evidence about *valuation and standalone downside*, which is
what it measures.

**2. The buyer's identity no longer scores.** `score_consideration` replaces the
`deal_type` band, which paid +10 for All Cash and +5 for Private Equity and so
charged five points for the identity of the buyer — a charge **GSAT** was
carrying with Amazon as its acquirer. What is scored now is whether the payout
moves: a stock leg re-prices daily with the acquirer's shares (+4) and cash does
not (+8). That is a fact about the deal rather than a guess about the buyer.

**3. The score can see time.** `score_deadline` is worth 0 to -25, and a passed
deadline is additionally a hard **override** in `get_risk` rather than a band,
because it is not a matter of degree: past the outside date either party may walk
without paying a break fee, so the contract has stopped protecting the position.
**GBCS moves 92/Very Low → 74/High.** This is the correction that mattered most.

**4. Spread is counted once.** Its share of the score is halved — the bands go
from ±(25..35) to ±(12..18) — and `get_risk` no longer takes a spread argument
at all. The band was largely the spread wearing a different name, which is why
five other factors could barely move it.

Scale restated: 50 -18 +0 -15 -20 -10 -25 = **-38** at worst, 50 +12 +8 +10 +5
+10 = **95** at best, both stated in the code beside the bands so a change to any
band that is not reflected there shows up as a shifted scale.

### Before and after, every deal

"Before" is recomputed with the old bands, so this is like-for-like rather than
a comparison against a production feed that differs in other ways.

| Deal | before | after | Δ | what moved it |
|---|---|---|---:|---|
| AES | 73 / Low | 75 / **Very Low** | +2 | consideration |
| ALOT | 88 / Very Low | 77 / Very Low | -11 | premium +8 removed; deadline -3; financing |
| APGE | 76 / Very Low | 66 / **Low** | -10 | premium +6 removed; financing |
| ATKR | 80 / Very Low | 80 / Very Low | 0 | premium +4 removed, consideration -2 |
| BOW | 78 / Very Low | 80 / Very Low | +2 | consideration |
| BWMN | 83 / Very Low | 73 / **Low** | -10 | premium +8 removed; financing |
| **BZH** | 81 / Very Low | **88** / Very Low | **+7** | **premium -5 removed** |
| CBZ | 79 / Very Low | 80 / Very Low | +1 | premium +2 removed |
| CZR | 62 / Low | 65 / Low | +3 | consideration |
| DSGR | 74 / Low | 73 / Low | -1 | premium +4 removed |
| **GBCS** | **92 / Very Low** | **74 / High** | **-18** | **deadline -25**; premium +8 removed |
| GBTG | 72 / Low | 68 / Low | -4 | premium +8 removed |
| **GSAT** | 65 / Low | **71** / Low | **+6** | **buyer type no longer scored** |
| HZO | 75 / Very Low | 73 / **Low** | -2 | premium +6 removed |
| NATH | 85 / Very Low | 89 / Very Low | +4 | deadline -3, consideration |
| OGN | 73 / Low | 74 / Low | +1 | premium +2 removed |
| PAYO | 74 / Low | 79 / **Very Low** | +5 | consideration |
| RAMP | 81 / Very Low | 81 / Very Low | 0 | premium +4 removed, consideration -2 |
| SLAB | 74 / Low | 76 / **Very Low** | +2 | premium +8 removed |

**17 of 19 deals moved; 8 changed risk band.** Three deals whose agreements read
WEAK on financing (ALOT, APGE, BWMN) fell because the agreement reading now
supersedes a press release that knew nothing — they went down for a reason that
is quoted from the contract.

Landing on the next scan, once the negation fix re-reads the press releases:

```
CZR   contingent -> committed    65 / Low  ->  80 / Very Low   (+15)
DSGR  contingent -> committed    73 / Low  ->  88 / Very Low   (+15)
GBTG  contingent -> committed    68 / Low  ->  83 / Very Low   (+15)
HZO   contingent -> committed    73 / Low  ->  88 / Very Low   (+15)
```

### The recurring bug, guarded again

The outside date and the agreement's financing verdict both arrive in the
agreement pass, *after* the score has been computed. Rebuilding the deal dict
without recomputing is the fourth-instance pattern in CLAUDE.md, so the score and
band are now explicitly recomputed after that pass, and the scan prints every
deal whose score moved as a result.

## What was deliberately NOT done

- **No sub-score carries a number.** Not one. Where a category has evidence but
  no defensible weight, the evidence is shown and the number is absent.
- **Four categories — Legal, Shareholder, and often Financing and Regulatory —
  return "insufficient evidence" rather than a neutral-looking score.** A
  neutral number is indistinguishable from a measured one.
- **The regulatory weights were not retuned.** They are unvalidated like the
  rest; retuning them without evidence would be the mistake this section is
  about. They are unchanged and now labelled INFERENCE.
- **BZH's break price was left alone**, as instructed.
- **`deal_type` was not rewritten in the data.** It is no longer consumed by the
  score, which was the live defect; correcting the stored label is §7 work.
- **Probability was not touched.** It is labelled FORECAST and belongs to §31.

Seven suites pass, including `test_provenance.py` — 46 new checks covering both
sections, each built from the live deal or the exact filing sentence that
exposed the defect.


---

# Guidance and the deadline are different claims, and the page now says so

2026-09-01.

## The contradiction, confirmed

NATH displayed **Oct 20, 2026** beside **~120 days**. October 20 is 49 days out.

The cause is what was suspected, and it is two lines apart in the template:

```js
var dtc      = _daDaysToClose(deal.close_date);          // UNCAPPED guidance
var closeEst = _daFmtCloseDate(deal.close_date, deal);   // substitutes the CAP
```

Both fed the same metric cell, so the date shown and the day count shown were
measured from dates ten weeks apart.

**GBCS was worse than NATH.** It displayed **Aug 31, 2026** — three days in the
**past** — beside **~27 days**, because the cap replaced a future guidance date
with an expired deadline while the day count kept counting to the guidance.
Capping the display did not merely collapse the gap; on a deal past its deadline
it inverted the meaning.

### Which deals had it

Swept across all nineteen. The contradiction needs both a parseable guidance
date and a capped date, which is two deals:

| Deal | guidance | its days | displayed | its days | gap |
|---|---|---:|---|---:|---:|
| **NATH** | H2 2026 → Dec 31 | 120 | Oct 20, 2026 | 48 | **+72 days** |
| **GBCS** | Q3 2026 → Sep 30 | 28 | Aug 31, 2026 | **−2** | **+30 days** |

Two more carried a milder form of the same defect: **CZR** and **PAYO** have a
capped date but guidance that resolves to no date ("mid-to-late 2027",
"mid-2027"), so the page showed a date the company never guided to with no day
count beside it at all.

A note on the sweep, because the numbers moved between two runs an hour apart:
a scan was **in progress** during the second, so only 9 of 19 deals had been
rebuilt and GBCS and CZR briefly read `outside_date: None` with no
`agreement_read`. That is a partially-rebuilt feed, not a regression. The table
above is from the complete snapshot.

## The decision: show both, uncapped

Option one, as you leaned. The cap is removed from the displayed close date
entirely, and both dates are shown with a day count each measures from its own
date.

The argument is stronger than "the gap carries meaning", though it does. **The
cap existed because the outside date was invisible on the page.** A guidance
date sitting past its own deadline looked like an error with no explanation
beside it, so the cap hid it. The deadline has been rendered since two turns ago
— its own block, quote-backed, with the days remaining — so the workaround has
lost the condition that justified it. Keeping it now would mean suppressing one
of two facts that are both on the page anyway.

And GBCS settles it independently: a cap that can print a past date as a close
estimate is not a safer display, it is a wrong one.

## The relabelling

"Days to Close" implied a prediction the product does not make, and named
neither concept. The metrics cell is now **Timing**, and two labelled rows sit
under the strip:

```
GUIDANCE   Dec 31, 2026 · 120 days    what the company said it expects
DEADLINE   Oct 20, 2026 · 48 days     when either party may walk away

Guidance is the company's stated expectation and carries no contractual force.
The deadline is a contractual right — past it, either party may walk away
without paying a break fee. They are different claims, and the gap between them
is not an error.
```

Verified in-browser on four shapes, each internally consistent:

| Deal | guidance | deadline | the shape it tests |
|---|---|---|---|
| NATH | Dec 31, 2026 · 120 days | Oct 20, 2026 · 48 days | the reported case |
| GBCS | Sep 30, 2026 · 28 days | Aug 31, 2026 · **2 days ago** | a deadline already passed |
| PAYO | Jun 30, 2027 · 301 days | Jun 12, 2027 · 283 days | guidance past the deadline, uncapped |
| SLAB | Jun 30, 2027 · 301 days | Feb 4, 2028 · 520 days | the ordinary case, deadline later |

SLAB matters as a control: it has no cap and never had the contradiction, and it
gets both rows anyway. The rows are for every deal, not a special case bolted on
for the broken ones.

One smaller relabelling for consistency: the annualized fallback read
`— · 28d to close` and now reads `to guidance`, since that is the date it counted
to.

## What did not change

The cap itself. `close_date_capped_to` is still computed and still stored — it
is the honest record that guidance runs past the deadline, and the integrity
sweep can still use it. What changed is that it no longer overwrites a displayed
date whose day count came from somewhere else.

Six new checks in `test_provenance.py`, asserting against the template source
rather than a rendered page, because the template is where this regressed:
`_daFmtCloseDate` must not reference `close_date_capped_to`, each row must
compute days from its own date, and "Days to Close" must stay gone.
