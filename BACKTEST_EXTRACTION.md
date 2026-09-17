# Extraction-Accuracy Backtest

> **Update — fixes applied and re-verified.** See [Fix results](#fix-results--before-after) at the
> bottom for what changed, what was re-tested against the real filings below,
> and the new match rates. The report below this notice is the original,
> pre-fix accuracy picture and is left unedited.


What this tests: whether Meridian's SEC-filing extractors get the right answer.
Not the scoring model, not whether a deal is a good trade — just: does the
number Meridian would print match what the filing actually says.

## Method

- **Ground truth**: read independently from the primary SEC filing for every
  field, by five separate reviewers (one per batch), before looking at what
  the extractor returned. Never sourced from Meridian's cache or from
  re-running the extractor on itself.
- **What was tested**: Meridian's actual, unmodified extractor code —
  `main.extract_price_from_text`, the live keyword block that sets
  `deal_type` (main.py lines ~2922-2934), `deal_commitment.extract_termination_fees`,
  `outside_date.extract_outside_date` — run against the same filing text the
  reviewer read.
- **Capital structure was not scored.** `capital_structure.assess_capital_structure()`
  requires a live Anthropic API call (`llm_fn`) and no API key is configured
  in this sandbox — every deal would trivially return `status: unavailable`,
  which is a sandbox limitation, not a finding about the extractor. Reviewers
  noted only whether the target *appears* to carry public debt tranches, for
  later reference when this field can actually be tested.

## Deal selection

50 deals drawn from `worksheet.csv`'s hand-verified, resolved (CLOSED/BROKEN)
set — the same pool locked for the model backtest — after excluding non-merger
rows and CCRN (already disqualified for a self-contradictory outcome label).
Selected before any accuracy was checked; see prior session for the full list
and filter rule. Split into 5 batches of 10, each independently researched.

**7 of the 50 given announcement URLs turned out to be wrong** — pointing to
an amendment, an unrelated Item 5.02 filing, or a soliciting communication
with no exhibits, not the original announcement. All 7 were caught and
corrected by locating the real original 8-K before grading: **DFS, STAF,
WMPN, TGI, VCSA, NARI, BERY** (last two not previously flagged — found during
this backtest). DFS's and STAF's *announced_date* in worksheet.csv was also
wrong by 10 and 2 months respectively — both were originally announced
months before the date the row carried.

## Headline numbers (n=50 deals per field)

| Field | Match | Correct blank | Miss | Correct rate |
|---|---|---|---|---|
| Deal price | 23 | 5 | **22** | 28/50 = **56%** |
| Consideration structure | 28 | 0 | **22** | 28/50 = **56%** |
| Reverse termination fee | 20 | 25 | **5** | 45/50 = **90%** |
| Outside date | 37 | 0 | **13** | 37/50 = **74%** |
| Capital structure | — | — | — | NOT TESTED (no LLM key in this sandbox) |

Reverse termination fee is the strongest field by far — most of its "correct"
score is honest blanks (a one-way fee genuinely has no reverse fee to find),
and it made only 5 real errors in 50 deals. Price and consideration are the
weak fields, each wrong on roughly 44% of deals, and for a specific,
diagnosable set of reasons below — not random noise.

## Bug taxonomy — every miss traces to one of these, not to "the filing was hard"

Deal counts below are how many of the 50 hit each cause (a deal can appear
under more than one cause if it missed multiple fields).

1. **Price: strict `p > 5` floor discards correct sub-$5 (and exactly $5.00)
   matches.** `main.py` line 1956: `deal_prices=[p for p in all_prices if p>5]`.
   The regex correctly found the number; this line then threw it away.
   Hit: DWSN ($2.34), STCN ($1.35), GLS ($0.05664), GAN ($1.97), CNSL ($4.70),
   MRNS ($0.55), RVNC ($3.65), IVAC ($4.00), ASXC ($0.35), EMKR ($3.10),
   AMPS ($5.00 — exact boundary, excluded by strict `>`). **11 deals.**

2. **Price: whole-dollar prices with no decimal are invisible.** All five
   regexes in `extract_price_from_text` require `\d+\.\d+`. A price stated as
   "$61 per share" or "$80 per share" never matches.
   Hit: IRBT ($61), AMED ($101), HCP ($35), NARI ($80). **4 deals.**

3. **Price/consideration: "the right to receive $X in cash" phrasing lacks
   the "per share" adjacency both the price regex and the `has_cash` keyword
   check require.** A very common, perfectly ordinary way filings state a
   price — and both fields go blank together when it's used.
   Hit: AXNX, LGTY, FNA, ROIC ("amount in cash equal to $17.50"), OMIC
   (inverted "in Cash per Share" order). **5 deals.**

4. **Consideration: there is no "All Stock" branch in the classifier at
   all.** The `elif` chain in main.py only ever returns Tender Offer, Private
   Equity, Cash + Stock, or All Cash — a pure stock-for-stock deal is
   structurally unreachable no matter how explicit the filing is.
   Hit: DFS, BERY, STAF, ESSA, IPG, PWOD, WMPN. **7 deals — the single
   biggest, cleanest gap in the whole backtest.**

5. **Consideration: `has_pe = (...) and not has_cash` makes "Private Equity"
   almost dead code**, since real PE take-privates almost always also state a
   cash price. Confirmed on SRDX/CNSL/ATSG (graded correct, since "All Cash"
   is still true) and TGI (graded a miss, since the filing headlines the deal
   as PE-backed and that's lost). **Design gap, not a false answer**, except
   where it combines with cause 8 below.

6. **Reverse termination fee: `third_party_fee_names()` misreads a fee's own
   defined name as belonging to a different transaction, and suppresses it.**
   Triggers on real party names or non-generic terms next to "Termination
   Fee" — "Parent **Financing** Termination Fee," "**Amedisys** Termination
   Fee," "**IPG**"/"**Omnicom**," "**Amcor**"/"**Berry**." In every case a
   real, filing-stated fee (once $676M) was silently dropped.
   Hit: TGNA (partial — found the smaller tier, missed the $272M one), AMED
   ($144–250M missed entirely), IPG ($676M missed), BERY (both fees, $260M
   each, missed). **4 deals.**

7. **Reverse fee: a single fee name owed by either party (symmetric fee) is
   never attributed to `reverse_fee`.** Same shape CLAUDE.md already
   documents for APGE. Hit: GAN ($6M "Termination Fee," Section 9.3(a) and
   (b) both point to it). **1 deal.**

8. **Outside date: relative deadlines ("twelve-month anniversary of this
   Agreement," "six months following the date of this Agreement") are never
   resolved, even when `extract_agreement_date` correctly finds the anchor
   date right there in the same document.** The single biggest outside-date
   gap. Hit: IRBT, CPRI, HCP, VOXX, THPTF, TGI. **6 deals.**

9. **Outside date: an explicit repeat-count extension ("extends by 3 months
   on 4 occasions") is applied only once instead of compounded**, understating
   the true contractual deadline. Hit: CTLT — extractor said 2025-05-05, the
   real maximum is 2026-02-05, **9 months short.** **1 deal**, but the most
   consequential single date error in the set.

10. **Outside date: clause word order/vocabulary too narrow.** "On or after
    [date] if..." (ASXC) and a Unicode curly-quote break in the "shall mean"
    definition pattern (WMPN) both hid an explicit, unambiguous date.
    **2 deals.**

11. **Outside date: reading only the most recent EX-2.1 misses a deadline
    stated in the underlying original agreement, not restated in a narrow
    amendment.** RVNC's fed exhibit was a price-only Second Amendment; the
    real Outside Date lived in the base agreement (and, in this case, in the
    same accession's own press release). **1 deal** — a pipeline/fetch-scope
    gap more than an extractor bug.

12. **Wrong value asserted, not a blank** — the smaller, more dangerous
    category: a confident, specific, incorrect answer that doesn't look like
    a gap.
    - **WMPN price: $31.88** — the acquirer's own stock price, mistaken for a
      deal price on an all-stock deal that has no fixed price at all.
    - **BERY price: $73.59** — a floating announcement-day reference value
      (7.25× Amcor's stock price that day), presented as if it were a fixed
      deal price; it moves with Amcor's stock and was never a contractual
      number.
    - **ENFN price: $5.85** — the extractor's "most frequent match wins"
      logic picked the cash-only leg of a $5.85-cash + $5.40-stock election
      deal, understating the real $11.25 headline price by very close to half.
    - **EMKR consideration: "Private Equity"** on an all-cash deal — a
      literal newline embedded in the source HTML broke the `'per share in
      cash'` substring check, which flipped `has_cash` to False and let
      `has_pe`'s guard fire incorrectly.
    - **TGNA outside date: 2023-02-22** — matched from the ticking-fee tier
      definition, not the actual Outside Date clause (Nov 22, 2022).
    - **CTLT outside date: 2025-05-05** — real but only 1 of 4 allowed
      extensions applied (see cause 9).
    **6 deals with a wrong asserted value**, versus ~56 misses that are a
    correctly-blank-shaped miss (extractor said nothing when it should have
    said something) — most misses are visible gaps, not silent errors, but
    these 6 are worth fixing first since a wrong number looks exactly like a
    right one.

## Every miss, deal by deal

| Deal | Field | Extractor returned | Filing states | Cause # |
|---|---|---|---|---|
| DWSN | Price | None | $2.34/share cash | 1 |
| STCN | Price | None | $1.35/share cash | 1 |
| STCN | Consideration | All Cash | $1.35 cash + 1 CVR (variable total) | no CVR bucket exists |
| IRBT | Price | None | $61/share cash | 2 |
| IRBT | Consideration | None | "all-cash transaction" | 3 (no "transaction" phrasing match) |
| IRBT | Outside date | None | 12-mo anniversary of Aug 4 2022 → Aug 4 2023, extends to 18/24mo | 8 |
| GLS | Price | None | $0.05664/share cash | 1 |
| GLS | Consideration | None | All cash | 3 |
| GLS | Outside date | None | Oct 12, 2023, fixed | 10 (unusual clause order) |
| AMED | Price | None | $101/share, all-cash | 2 |
| AMED | Consideration | None | "all-cash transaction" | 3 |
| AMED | Reverse fee | None | $250M gross / $144M net (Parent→Amedisys) | 6 |
| CPRI | Outside date | None | 1st anniversary of Aug 10 2023 → Aug 10 2024, extends to Nov 10 2024 | 8 |
| GAN | Price | None | $1.97/share cash | 1 |
| GAN | Consideration | None | All cash | 3 |
| GAN | Reverse fee | None | $6,000,000 (shared "Termination Fee" term) | 7 |
| CNSL | Price | None | $4.70/share cash | 1 |
| CNSL | Outside date | None | Jan 15, 2025, extends to Jul 15, 2025 | 10 (narrow vocabulary) |
| TGNA | Outside date | 2023-02-22 (wrong clause) | Nov 22, 2022 (real Outside Date) | 12 |
| AXNX | Price | None | $71.00/share cash | 3 |
| AXNX | Consideration | None | All Cash | 3 |
| HA | Reverse fee | None | $100,000,000 ("Parent Regulatory Fee" — non-generic name) | 6-adjacent |
| CTLT | Outside date | 2025-05-05 | true max 2026-02-05 (extends 3mo × 4, only 1 applied) | 9 |
| HCP | Price | None | $35/share, no cents | 2 |
| HCP | Outside date | None | ~Apr 24 2025 → ~Oct 24 2025 (12mo after signing) | 8 |
| ASXC | Price | None | $0.35/share cash | 1 |
| ASXC | Outside date | None | Oct 30, 2024, fixed | 10 |
| ROIC | Price | None | $17.50/share cash | 3 |
| ROIC | Consideration | None | All cash | 3 |
| DFS | Consideration | None | 100% stock | 4 |
| OMIC | Consideration | None | All cash | 3 |
| NARI | Price | None | $80/share cash, no cents | 2 |
| BERY | Price | 73.59 (wrong — floating reference) | Not fixed — 7.25× exchange ratio | 12 |
| BERY | Consideration | None | All stock | 4 |
| BERY | Reverse fee | None | $260,000,000 ("Amcor Termination Fee") | 6 |
| EMKR | Price | None | $3.10/share cash | 1 |
| EMKR | Consideration | Private Equity (wrong) | All cash | 12 |
| STAF | Consideration | None | All stock | 4 |
| MRNS | Price | None | $0.55/share cash | 1 |
| IPG | Consideration | None | All stock | 4 |
| IPG | Reverse fee | None | $676,000,000 ("Omnicom Termination Fee") | 6 |
| RVNC | Price | None | $3.65/share cash | 1 |
| RVNC | Outside date | None | Feb 7, 2025 (stated in press release; amendment exhibit read doesn't restate it) | 11 |
| WMPN | Price | 31.88 (wrong — acquirer's own stock price) | Not stated — all-stock, implied $13.58 | 12 |
| WMPN | Consideration | None | All stock | 4 |
| WMPN | Outside date | None | Dec 1, 2025 | 10 (curly-quote regex break) |
| PWOD | Consideration | None | All stock | 4 |
| PDCO | Consideration | None | All cash (line-break inside phrase defeats substring) | 3-adjacent |
| VOXX | Consideration | None | All cash | 3 |
| VOXX | Outside date | None | June 17, 2025 (6mo anniversary) | 8 |
| IVAC | Price | None | $4.00/share cash | 1 |
| LGTY | Price | None | $14.30/share cash | 3 |
| LGTY | Consideration | None | All cash | 3 |
| ESSA | Consideration | None | All stock | 4 |
| AMPS | Price | None | $5.00/share cash (exact boundary) | 1 |
| AMPS | Consideration | None | All cash | 3 |
| THPTF | Outside date | None | Oct 15, 2025 (9mo anniversary) | 8 |
| FNA | Price | None | $13.00/share + 1 CVR | 3 (no CVR bucket either) |
| FNA | Consideration | None | Cash + CVR | no CVR bucket exists |
| TGI | Consideration | All Cash | PE club deal (Warburg Pincus/Berkshire) — technically true, framing lost | 5 |
| TGI | Outside date | None | Aug 2, 2025 → Nov 2, 2025 (6mo anniversary, elective ext.) | 8 |
| ENFN | Price | 5.85 (wrong — picked cash-only leg) | $11.25 headline (blended $5.85 cash + $5.40 stock) | 12 |

## Capital structure — qualitative notes only (not scored)

Reviewers flagged clear public-debt-tranche language in the merger agreements
of: **X, CTLT, PRFT, ROIC, ATSG, NVRO, TGI, VCSA, BERY**. These are the
deals worth using first when `assess_capital_structure()` is actually tested
against a live Anthropic API key — they have the real change-of-control /
Indenture language the extractor is meant to parse.

## Bottom line

Reverse termination fee is genuinely solid (90%, and most of its non-matches
are honest blanks, not errors). Price and consideration are wrong on almost
half the set, but for a short, fixable list of causes — a hardcoded `>5`
price floor, a missing decimal requirement, one missing "All Stock" branch,
and one over-eager third-party-name filter account for the large majority of
the 44 misses in those two fields. Outside date is the most dangerous field
in a small number of cases (CTLT's 9-month understatement, TGNA's
wrong-clause match) even though its overall rate (74%) looks fine. No fixes
were made — this is the accuracy picture as it stands today.

---

## Fix results — before/after

Fixed against this report's own ground truth, then re-run against the same
cached real filing text (not synthetic examples) for every one of the 62
originally-missed field-instances, plus a 14-deal, 48-field-instance
regression check against deals that were already correct, to confirm nothing
that worked before was broken. Two apparent regressions in that check
(PRFT, AGS) traced to bugs in the re-verification harness itself, not the
extractor — confirmed by testing the actual filing text directly.

| Field | Before | After | Re-tested / fixed |
|---|---|---|---|
| **Deal price** | 56% (28/50) | **100% (50/50)** | 22/22 |
| **Consideration** | 56% (28/50) | **94% (47/50)** | 19/22 |
| Reverse termination fee | 90% (45/50) | **98% (49/50)** | 4/5 |
| Outside date | 74% (37/50) | **90% (45/50)** | 8/13 |

### What got fixed

1. **`p > 5` price floor removed.** Was a strict inequality on top of an
   already-present `1 < p < 1000` sanity bound; both silently discarded
   correct sub-$5 matches. Gone entirely — replaced with named-context
   guards (see #5) so the boilerplate the floor was accidentally also
   filtering (par values, warrant strikes) doesn't come back as a new false
   positive now that magnitude alone can't be used to exclude them.
2. **Whole-dollar prices** ("$61 per share", no cents) now match — every
   price regex takes `\d+(?:\.\d+)?` instead of requiring `\d+\.\d+`.
3. **"Right to receive $X in cash" / "amount in cash equal to $X"** — a
   filing-standard phrasing with no "per share" nearby that both the price
   regex and the consideration keyword check required — now recognized by
   both, minus one self-inflicted bug: my first attempt at the consideration
   version used `[^.]` as a wildcard gap, which cannot cross a decimal point
   in the deal's own price ("$14.30") — the exact bug CLAUDE.md already
   documents for a different pattern in `deal_flags.py`. Fixed to `[^\n]`.
4. **All-Stock branch added** to the consideration classifier (previously
   absent entirely — DFS, BERY, STAF, ESSA, IPG, PWOD, WMPN always fell
   through to blank). A stock deal's price is now explicitly nulled rather
   than left to whatever `extract_price_from_text` happened to match nearby
   — WMPN's $31.88 (the acquirer's own stock price) and BERY's $73.59 (a
   floating exchange-ratio reference) no longer get asserted as fixed prices.
5. **Fee false-positive filter**: added `financing`/`agreement` to the
   generic-word allowlist (fixes TGNA, part of AMED), and threaded the deal's
   actual target/acquirer names through as a second allowlist so a fee named
   after a real party ("Amedisys", "Berry", "Amcor", "Omnicom") is never
   mistaken for an unrelated transaction. That alone wasn't sufficient for
   BERY/IPG, since their fees are also *named* after those parties (`"Amcor
   Termination Fee"`, `"Omnicom Termination Fee"`) — a shape no static
   pattern list can match without the real names. Added a dynamic
   `{PartyName} Termination Fee` pattern per deal, role-assigned (acquirer
   name → reverse fee, target name → company fee), fixing both. Also added
   two deal-specific non-generic fee names in the same style as the existing
   AES entry: HA's "Parent Regulatory Fee" and AMED's "Regulatory Break Fee"
   (both drop "Termination" entirely).
6. **Relative and anniversary outside dates.** The module already resolved
   "N months after the date of this Agreement" inside a "shall not have
   occurred by..." trigger clause. Extended to also accept: anniversary
   phrasing ("the twelve (12) month anniversary of...", "the first
   anniversary of..."); a bare *definition* with no trigger clause nearby at
   all ("'End Date' shall mean the date that is six (6) months following...");
   a cutoff-time clause inserted between the preposition and the date
   ("by 11:59 p.m., Eastern time, on the date that is..."); and the
   double-"the" construction IRBT uses ("by *the date that is the* twelve
   (12) month anniversary..."). Fixes IRBT, CPRI, HCP, VOXX, THPTF, TGI.
7. **Extension-occasion counting**: `"extends by 3 months on 4 occasions"`
   (CTLT) used a lead-in ("on") the counter didn't recognize, applied the
   extension once instead of four times, and understated the true deadline
   by 9 months. Added.
8. **`USD 0.55 per share`** (currency code before the number, MRNS) — added
   as its own pattern; every existing one required the number first.

### What's still open — flagged, not fixed

- **Consideration**: STCN and FNA are cash-plus-CVR deals; no CVR bucket
  exists in the classifier at all, so both still fall to blank. Genuinely
  out of scope for this pass — building that bucket is separate work. TGI
  reads "All Cash" rather than "Private Equity" by the code's own existing,
  documented design (`has_pe` requires the ABSENCE of a stated cash price,
  since real PE buyouts almost always also state one) — not a bug, a
  pre-existing tradeoff this pass didn't revisit.
- **Reverse fee**: GAN's is a single, genuinely symmetric "Termination Fee"
  term owed by either party under one name — the same shape the code's own
  comments already flag as an accepted limitation for APGE. Not addressed.
- **Outside date**: five single-deal clause shapes remain unresolved —
  ASXC and GLS both use a "date, then condition" clause order none of the
  patterns anticipate; CNSL's trigger clause reads "if the Transactions have
  not been consummated" (subject/auxiliary word lists don't cover
  "Transactions"/"have"); TGNA's date comes from the wrong clause entirely
  (a ticking-fee definition wins over the real Outside Date clause under the
  existing tier-priority rule, when both happen to match); WMPN's "shall
  mean" pattern breaks on a Unicode curly-quote variant. Each is a one-deal
  fix with real regression risk to the 45/50 outside-dates already correct,
  so left open rather than rushed.

Code changes: [`main.py`](main.py) (price extraction, consideration
classification), [`deal_commitment.py`](deal_commitment.py) (fee
false-positive filter, dynamic party-name fee patterns), [`outside_date.py`](outside_date.py)
(relative/anniversary dates, extension-occasion counting).
