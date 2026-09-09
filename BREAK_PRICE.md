# Break-price engine — design, not code

ROADMAP §4. This is a design for review before anything is built. It answers,
for each of the eleven inputs the section names: can a solo operator get it at
all, where would it come from, and would it be a sourced number or a guess
wearing one. Then it proposes a model shape and a confidence scheme, and says
what validating any of it would actually take.

The governing constraint, carried over from §9 and §30: a tuned wrong input is
still a wrong input, and a scenario built from a guess is worse than one honest
number. The current defect — `break_price_method: "historical"` on 18 of 19
deals, a bare unaffected-price lookup labeled with the confidence of a model —
is exactly that failure shape. This design is not allowed to repeat it under a
better name.

---

## The eleven inputs, one at a time

### 1. Unaffected price
**Obtainable: yes — already built.** Source: **computed**, a pre-announcement
close from Tiingo/yfinance history (`get_break_price`), or a hand-verified
override (`VERIFIED_UNAFFECTED_PRICES`) where the lookback would otherwise catch
a leak. **Honest.** This is the current model in its entirety and stays the
anchor — the fix is what gets built around it, not a replacement for it.

### 2. Recent unaffected range
**Obtainable: yes, cheaply.** Source: **computed** — 30/60/90-day pre-
announcement high/low/mean from the same price history already pulled for #1.
**Honest.** Pure price data, no interpretation. Turns a point estimate into a
band without inventing anything.

### 3. Sector movement
**Obtainable: yes, needs a small build.** Source: **computed** — a sector ETF's
percent change from the announcement date to today (yfinance), applied to the
unaffected price. `SECTOR_ETF_MAP` exists today but is a hand-maintained dict
for a different, older ticker set; it would need to become a generic
`sector → ETF` mapping off `yf.Ticker(t).info['sector']`, which the codebase
already reads for `get_regulatory_risk`. **Honest, but a crude proxy** — eleven
GICS sector ETFs span very different sub-industries, and a name with no sector
on file falls back to SPY, which is a market adjustment, not a sector one. Caps
confidence at MEDIUM, never HIGH, and the fallback must say which happened.

### 4. Company developments
**Not obtainable, honestly, right now.** In principle: 8-K Items 2.02/8.01 filed
after announcement. In practice: turning "the target filed an 8-K" into a
dollar adjustment to standalone value requires judging materiality, which is
editorial judgment this product doesn't have a mechanical way to make. **Would
be a guess wearing a number.** Can be surfaced as a pointer ("an 8-K was filed
on X — read it") — not as a price input.

### 5. Standalone value
**Not obtainable for a solo operator.** Would need a real comps/DCF engine
against live fundamentals, which does not exist and is a separate large build,
not a quick addition. The obvious shortcut — yfinance analyst price targets —
fails for two reasons: several of the 19 targets are micro-cap with thin or no
analyst coverage, and a post-announcement target price is itself contaminated
by the deal (it is not a standalone read). **Would be a guess wearing a
number.** Left out entirely rather than approximated badly.

### 6. Termination-fee economics
**Obtainable: yes — already built.** Source: **filing** — `extract_termination_
fees` reads the reverse fee (acquirer walks), the company/target fee, and the
asymmetry between them, from the merger agreement. **Honest**, but it answers a
different question than this section needs. A large asymmetric RTF is evidence
the acquirer is discouraged from walking — that bears on the PROBABILITY of a
break, not on WHERE the price lands if one happens. It belongs in the model as
a qualitative caveat, not as a term that moves the break-price number.

### 7. Cash burn
**Not obtainable now.** Would need quarterly cash-flow data pulled from EDGAR's
XBRL frames API and a burn-rate computation — possible in principle, a real
scoped sub-project, and only relevant for a minority of targets (cash-
constrained biotech mainly; APGE, ONCE-type names in the historical set).
**Not attempted.** Flagged as a future, separately-scoped addition, not
approximated.

### 8. Litigation and transaction costs
**Not obtainable.** No litigation database is wired in (PACER, Bloomberg Law,
or similar), and deal-litigation disclosure in 8-Ks/proxies is inconsistent and
not currently extracted. Transaction costs are sometimes disclosed but are
usually immaterial to where a broken deal's stock lands. **Would be a guess
wearing a number.** Left out.

### 9. Regulatory remedies
**Partially obtainable, and what exists today is the wrong shape for this.**
`reg_tags` are already computed — but they are **priors** from deal size and
sector (§30 already documents this: "a cleared deal and one facing a second
request tag identically"). A confirmed remedy — a consent decree, a required
divestiture — would need to be read from a filed 8-K describing the regulatory
outcome, the same way `outside_date` and `commitment` are read today. That
detector does not exist. **Not attempted here.** The existing `reg_tags` stay
what they are: a regulatory-complexity prior shown elsewhere, not a break-price
input, because a prior is not evidence about price.

### 10. Financing
**Obtainable: yes — already built.** Source: **filing**, agreement-first
(`financing_from_commitment`), press-release fallback, both source-labeled and
gated (`scoring_financing_signal`). **Honest.** Same shape as #6: this is
evidence about whether the deal breaks, not about where price lands if it does.
A `contingent` signal is a real, sourced flag that a break here is more likely
to be financing-driven — it does not, on its own, imply a magnitude.

### 11. Alternative outcomes
**Partially obtainable.** Two real signals already exist: `FLAG_GO_SHOP` (a
go-shop window is contractually open — a competing bid is invited) and
`FLAG_REPRICED` (the deal has already been amended once). Both are **filing-
sourced facts**, not speculation. What is not obtainable is a HYPOTHETICAL
alternative price — "if a topping bid emerges, $X" is invention with today's
inputs. **Facts get surfaced (go-shop live, already repriced once); no
hypothetical price gets generated.**

---

## Summary table

| # | Input | Obtainable | Source | Verdict |
|---|-------|-----------|--------|---------|
| 1 | Unaffected price | Yes (built) | Computed | Honest — the anchor |
| 2 | Recent unaffected range | Yes, cheap | Computed | Honest |
| 3 | Sector movement | Yes, small build | Computed | Honest, crude — MEDIUM cap |
| 4 | Company developments | No | — | Guess wearing a number |
| 5 | Standalone value | No | — | Guess wearing a number |
| 6 | Termination-fee economics | Yes (built) | Filing | Honest, but a probability input, not a price input |
| 7 | Cash burn | No, not now | — | Real but unbuilt sub-project |
| 8 | Litigation & tx costs | No | — | Guess wearing a number |
| 9 | Regulatory remedies | Partial | Filing (unbuilt detector) | Existing `reg_tags` are priors, not this |
| 10 | Financing | Yes (built) | Filing | Honest, but a probability input, not a price input |
| 11 | Alternative outcomes | Partial | Filing (flags exist) | Facts only, no hypothetical price |

Four of eleven move the break-PRICE number honestly (1, 2, 3, and 3's range).
Two more (6, 10) are real and sourced but answer "will it break," not "where
does it land" — they stay visible as caveats beside the number, never folded
into it. Two (9, 11) contribute facts, not prices. Four (4, 5, 7, 8) are not
obtainable honestly today and are not approximated.

---

## Model shape

**Base break price** = unaffected price × (1 + sector-index return from
announcement to today), shown with the recent unaffected range (#2) as a band
around it, not a second scenario. This is the only number the model produces by
default, because it is the only one built entirely from #1–#3.

**No bear scenario, by default.** Every input that would justify a defensible
LOWER number — standalone value, cash burn, litigation, a filed regulatory
remedy — is in the "not obtainable" column. Inventing a bear case without one
of those is exactly the failure this design exists to avoid. Where financing is
`contingent`, that prints as a caveat ("a break here is more likely financing-
driven than the base case assumes") — not as a second number, because there is
no honest way to size the discount.

**Bull scenario, only where a real, priced, filed alternative exists.** If
`FLAG_GO_SHOP` is live or a competing bid has actually been filed and priced,
the bull case is that filed number — never an invented "what if" price. Zero of
the current 19 deals carry a live go-shop or a filed competing bid, so zero of
them would show a bull case today. That is the honest count, not a gap to fill.

**Every deal**, regardless of scenario count, shows the qualitative caveats it
has evidence for: termination-fee asymmetry (#6), financing signal (#10),
go-shop/repriced flags (#11), and the existing `reg_tags` prior (#9) — labeled
as what they are, not folded into the price.

---

## Confidence label, by input mix

- **`modeled from unaffected price only — low confidence`**: no sector ETF
  resolves (ticker's sector is unavailable, or it falls back to SPY). This is
  most of the current 19 deals until the sector mapping is built, and stays the
  label for any future deal in the same position.
- **`modeled from unaffected price, sector-adjusted — medium confidence`**: a
  named sector ETF resolves and the recent-range band is shown. This is the
  ceiling this design reaches.
- **No deal reaches HIGH confidence.** HIGH would require a standalone
  valuation this product does not have a way to build honestly (#5). Capping
  the scale rather than grade-inflating into it is the same discipline §9
  applies to the risk score's un-backtested weights.

Every instance is labeled a **MODEL ESTIMATE (§20)** — never a floor, never a
fact — the same footer language the deal page already uses for the premium and
the current break price.

---

## What it would take to validate

Nothing here can be calibrated. The hand-verified dataset is 39 deals with 4
breaks (CLAUDE.md, ROADMAP.md) — nowhere near enough to fit or check a
continuous price model, and a break price has no ground truth to compare
against for the 35 deals that haven't broken at all. The only honest check
available is directional, not a calibration: for the 4 historical breaks, pull
the actual post-break trading price (not currently stored — `historical_deals.
csv` records the outcome date but not the price after it) and see whether
sector-adjusted-unaffected sits closer to it than bare unaffected does. N=4.
That is a sanity check on the sign of the sector adjustment, not evidence the
model is right, and it should be reported as exactly that — the same honesty
the V3 score's methodology page already states about its own weights: analyst-
set, not backtested. This model inherits that sentence unless and until the
break count is large enough to say otherwise, which it is not.

---

## What this explicitly does not do

- Does not produce a bear price from unsupported inputs.
- Does not produce a bull price from anything but a filed, priced alternative.
- Does not fold financing or termination-fee signals into the price number —
  they stay visible captions.
- Does not attempt company developments, standalone value, cash burn, or
  litigation costs. These stay open, named, and out of scope, not silently
  dropped.
- Does not claim a confidence level the inputs don't support, and never reaches
  HIGH.

---

# The comparison, and the decision (2026-09-08)

Run before writing any engine, on the only evidence available: the 4 historical
breaks in the 39-deal set. For each, two estimates computed *as of the
announcement* — bare unaffected price, and unaffected x that sector's index
drift over the deal's life — measured against the actual post-break price.

**N = 4. This is a sanity check, not a backtest**, and the recommendation
carries the same caveat V3's methodology page already states about its weights:
too few events to calibrate anything.

## Inputs

| Deal | Announced | Unaffected | Sector ETF | Broke | Actual post-break | Source of post-break |
|---|---|---|---|---|---|---|
| TGNA | 2022-02-18 | $20.95 | XLC | 2023-05-22 (Standard General terminated) | ~$15.9 | daily closes 5/22–6/5/23 (stockanalysis) |
| IRBT | 2022-08-05 | $49.99 | XLY | 2024-01-29 (Amazon terminated) | ~$11.6 | Yahoo via Wayback, 2024-02-25 |
| CPRI | 2023-08-09 | $34.61 | XLY | 2024-10-24 (FTC injunction; formally 11/14) | ~$20.5 | daily closes 10/25–11/22/24 |
| CCRN | 2024-12-02 | $11.52 | XLV | 2025-12-04 (Aya agreement terminated, 8-K 1.02) | ~$8.0 | daily closes 12/4–12/17/25 |

## Result

| Deal | Sector drift | Bare estimate | error | Sector-adj estimate | error | Which is closer |
|---|---|---|---|---|---|---|
| TGNA | XLC −6.9% | $20.95 | +32% | $19.50 | **+23%** | sector-adj, by ~9pp |
| IRBT | XLY +7.4% | $49.99 | +317% | $53.71 | +348% | bare, by ~31pp |
| CPRI | XLY +19.0% | $34.61 | +69% | $41.19 | +101% | bare, by ~32pp |
| CCRN | XLV +6.5% | $11.52 | +44% | $12.26 | +53% | bare, by ~9pp |

Mean absolute error: **bare 115%, sector-adjusted 131%** (excluding the IRBT
company-collapse outlier: bare 48%, sector-adjusted 59%).

**Sector adjustment loses — worse in 3 of 4, and worse in aggregate.** It helped
only TGNA, the one deal whose sector *fell*; in the three where the sector rose,
it pushed the estimate up and away from a stock that had crashed. This is
exactly the decoupling the section anticipated: a target in a live deal for
12–18 months does not track its sector — it re-rates on its own regulatory
odds, and often its business erodes (IRBT revenue collapse, CCRN staffing
downturn, CPRI luxury slump).

**And both estimates overshoot badly.** Even bare unaffected price sat 32–69%
above the real post-break price in three of four (IRBT, −76%, is its own
category). A stock coming out of a failed deal does not return to its
pre-announcement price — it lands well below. The break price is not the
unaffected price; it is materially under it, by an amount N=4 cannot size.

## Decision — do NOT build the sector-adjusted model

It fails the only test there is. Build instead:

1. **Keep the bare unaffected price as the estimate**, relabelled for what it
   is: a rough anchor, a MODEL estimate (§20), never a floor. The 4 cases say
   it *overstates* a true break, so the label says that too.
2. **Add the recent-unaffected-range band** — 30/60/90-day pre-announcement
   low–high from the same price history. A pure price statistic that
   communicates the uncertainty honestly without inventing a second number.
3. **Flag a contaminated anchor.** Where the last pre-announcement close sits
   >~15% above the 90-day mean, the unaffected price itself carries leak/rumor
   run-up — surface that rather than trusting the point. (This is the AES
   cautionary case: its raw pre-announcement close was $16.87, +18% over the
   90-day mean; someone hand-set `verified_unaffected` to $13.75, at the bottom
   of the 90-day band. The flag would catch the rest automatically.)
4. **Relabel `break_price`** everywhere it shows from "Modeled downside case" /
   "modeled break price" to: *"Unaffected price (pre-announcement) — a rough
   floor estimate, and on the evidence a high one. Model, not a fact."*

### Confidence tiers

Only **one tier is now in use**: `unaffected price only — low`. The design's
`sector-adjusted — medium` tier is not built, and the comparison says it should
not be. HIGH stays impossible — it would need a standalone valuation (#5), which
is not honestly obtainable for a solo operator.

## What each of the 18 live deals would show

Break price = the current unaffected number (unchanged). Band = 30/90-day
pre-announcement close range. Label = low confidence for all; anchor flagged
where the pre-announcement run-up exceeds ~15%.

| Ticker | Break price (unaffected) | 90-day band | 30-day band | Run-up vs 90d mean | Anchor |
|---|---|---|---|---|---|
| SLAB | $136.62 | $116.08–$152.82 | $130.70–$152.82 | +1.0% | clean |
| CZR | $28.78 | $18.95–$29.07 | $25.41–$28.78 | +8.9% | clean |
| GSAT | $72.89 | $54.13–$77.73 | $56.44–$77.73 | +16.8% | **run-up — anchor suspect** |
| PAYO | $6.75 | $4.43–$6.75 | $4.60–$6.75 | +34.5% | **run-up — anchor suspect** |
| NATH | $91.82 | $88.98–$106.89 | $89.86–$97.15 | −4.1% | clean |
| RAMP | $29.66 | $23.22–$30.38 | $25.75–$30.38 | +7.7% | clean |
| OGN | $11.23 | $5.68–$11.23 | $5.68–$11.23 | +48.5% | **run-up — anchor suspect** |
| HZO | $35.68 | $27.66–$37.74 | $32.92–$36.92 | +3.9% | clean |
| ATKR | $72.70 | $68.68–$85.11 | $68.68–$81.66 | −4.4% | clean |
| AES | $13.75 (verified) | $13.00–$16.87 | $13.28–$16.87 | +18.1% raw | hand-set to band floor |
| BOW | $30.59 | $23.28–$32.30 | $27.54–$32.30 | +8.4% | clean |
| BWMN | $27.23 | $25.31–$35.80 | $25.31–$29.60 | −8.8% | clean |
| BZH | $33.46 | $18.03–$34.07 | $27.42–$34.07 | +22.4% | **run-up — anchor suspect** |
| DSGR | $27.48 | $26.58–$28.61 | $26.85–$28.61 | +0.5% | clean |
| CBZ | $46.70 | $28.44–$46.70 | $28.66–$46.70 | +37.4% | **run-up — anchor suspect** |
| GBTG | $5.93 | $4.97–$7.15 | $5.26–$6.20 | +3.7% | clean |
| GBCS | $3.20 | $2.97–$4.58 | $2.97–$3.61 | −14.9% | clean |
| APGE | $90.38 | $66.04–$92.20 | $77.75–$90.90 | +9.1% | clean |

Five of 18 (GSAT, PAYO, OGN, BZH, CBZ) carry a pre-announcement run-up over 15%
— their unaffected anchor is contaminated and the point estimate should not be
trusted without the band. AES is a sixth, already hand-corrected.

**No engine code. No ROADMAP box.** §4 stays open — but the comparison says the
work it needs is a relabel and a price-stat band, not a model.

---

# Shipped (2026-09-08) — the §4 answer was a label, not a model

Sector adjustment lost the comparison and is not built. What shipped:

## 1. `break_price` relabelled — it is optimistic, biased high

The comparison's second finding outranked the first: **both methods overshoot.**
Bare unaffected price sat 32–69% ABOVE the real post-break price in 3 of 4
breaks (IRBT −76%, its own category). A number meant to show how far a holder
falls was telling them they fall less than they would.

So the label is no longer "floor" or "rough estimate". Everywhere `break_price`
shows, it now reads as an **optimistic estimate of where the stock lands if the
deal dies — the real level has historically been lower, so true downside is
likely worse. Low confidence, biased high.** No haircut is applied: N=4 cannot
size one, and a made-up discount is the sector model's error in another form.
The bias is stated, not corrected.

Touched: the break-price box (title "Downside Floor" → "Optimistic Estimate"),
the "If Deal Breaks" card (now "· At Best", downside shown as "at least −X%"),
the dashboard cell ("(opt.)" + tooltip), `provenance.py` (the `why` names the
upward bias and the 4-for-4 evidence), the implied-probability note and its
"break to about $X — an optimistic estimate" line, and three landing-page
disclaimers.

## 2. Pre-announcement range band — `unaffected_band()`

New field `break_price_band` on every deal: 30/60/90-day pre-announcement close
range, the 90-day mean, and the run-up. Computed once per deal (fresh-hit path,
with a `save_cache` backfill for carried deals and a prior-capture so it never
refetches). Shown under the break price as the honest measure of how firm the
point is.

## 3. Contaminated-anchor flag

`anchor: 'run-up'` when the last pre-announcement close sits ≥15% above the
90-day mean — leak or rumour is in the anchor itself. The box then says so and
tells the reader to trust the range, not the point. On the current feed this
fires for **GSAT, PAYO, OGN, BZH, CBZ** (AES is a sixth, already hand-set via
`verified_unaffected` to its band floor).

## 4. Downstream consistency check

| Consumer | Treated `break_price` as a floor? | Now |
|---|---|---|
| "If Deal Breaks" card / `break_downside` | **Yes** — showed it as the definitive fall | "· At Best", "at least −X%", box says "Optimistic Estimate" |
| Implied probability `(cp−bp)/(dp−bp)` | No — an inflated bp pushes implied close odds *down*, the conservative direction | note + "break to about $X — optimistic estimate (§20)" |
| Break-even probability | Same as implied — conservative direction | same flag |
| Net-of-carry return | Does not use `break_price` | unchanged |
| `two_state_applies` gate | No — fires *more* when bp is high, which is the honest outcome | messages unchanged, still accurate |
| `deal_premium` (computed) | No — a secondary display, already caveated under §30C | reference text left; low priority |
| Dashboard "Break Price" cell | Bare number, no qualifier | "(opt.)" + tooltip |

**Nothing downstream still presents `break_price` as a hard floor.** The one
place that did — the box title "Downside Floor" and the definitive downside
figure — is fixed.

## §4 — DONE

The fix §4 needed was never a better model. It was an honest label on a number
the data shows is biased high, plus a price-stat band that carries the
uncertainty. Relabel, band, contaminated-anchor flag, and downstream check are
all shipped. **§4 box checked.**
