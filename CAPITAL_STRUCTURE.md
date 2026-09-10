# Capital structure — the target's debt, tranche by tranche

A customer feature, not a roadmap item. A credit club sources ideas from the
feed; a member reads a deal to decide whether there is a bond or a loan worth
trading. The first question is always the same: what is outstanding, at what
rate, maturing when, and what happens to it if the merger closes. A wrong debt
figure here does not shade a score — it loses that user. Hand-verified accuracy
over coverage.

**Not wired into the feed or the display.** Built, run against three hand-read
targets, reported for review. `capital_structure.py` + `test_capital_structure.py`.

---

## What it extracts, from the target's most recent 10-K debt footnote

Per tranche:

- **instrument type** — term loan, senior notes, revolver, junior subordinated,
  convertible
- **face amount** — what is owed, gross of issuance costs. Net captured
  separately where the filing splits them (BZH's junior subs: $100.8M face vs
  $78.5M net).
- **revolvers: amount drawn, not capacity.** BZH's revolver is $0 drawn on $365M
  — reporting the capacity is wrong by $365M. Drawn is the debt figure; capacity
  is secondary context.
- **rate** — a fixed coupon (`5.875%`) or a floating formula (`SOFR + 1.40%,
  5.175% at last measurement`), verbatim. Never forced to one number.
- **maturity date**
- **stated seniority** where the filing gives it. Captured, not modelled into a
  waterfall.

**Change-of-control treatment — the differentiator.** For each tranche, what the
filing says happens to it in the merger:

- "Buyer shall pay all outstanding obligations" → paid off at close, gone (NATH)
- "may be terminated upon a change of control" → likely refinanced (CBZ)
- a change-of-control put / the tranche survives → tradeable, the credit
  opportunity (BZH's indentured senior notes)

This is what tells a member whether there is anything to work with. A target
whose debt all evaporates at close is a pass; one with surviving public notes is
where they dig.

---

## The reconciliation barrier

The premium cross-check equivalent: an independent number in the same filing
that proves the extraction. The footnote states a total. The extracted tranches,
plus the filing's own adjustment lines, must bridge to it:

```
sum(tranche principal, or drawn for revolvers) + sum(adjustments) == stated net total
```

where adjustments are the filing's own subtractions — unamortized issuance
costs, discount, junior-sub accretion. If the bridge does not close within
tolerance, a tranche (or an adjustment line) was missed, and the output is
**"capital structure incomplete"** — never a partial table.

A second, independent check: where the filing also states an aggregate principal
(e.g. the maturities-table total), the sum of tranche face amounts is checked
against it.

## The refuse case

Foreign filers, recent IPOs, PE-owned targets: no usable 10-K debt footnote.
Where it cannot be found or read, the output is **"capital structure not
disclosed"** — never an empty or guessed table. A blank is honest; a wrong
tranche is not. The module also refuses ("unavailable") when no model layer is
wired in, rather than falling back to regex.

## Method

LLM extraction against the located footnote — this is table and prose reading,
the thing regex fails at. `capital_structure.py` locates the debt note by
heading and dollar-table density, feeds ~10–20k characters to the model with a
strict JSON schema, then does the reconciliation arithmetic in Python. The model
layer is injected the same way `deal_direction` / `deal_commitment` take theirs
(`llm_fn`), and `find_target_10k` falls back from a Part III 10-K/A to the last
original 10-K that carries financial statements (NATH's most recent filing is
exactly this case).

---

## Ground truth — the three hand-read targets

The extraction must reproduce these before it runs on anything else.

### CBZ — CBIZ, Inc.
10-K/A `0000944148-26-000094`, Note 10 "Debt and Financing Arrangements", as of
2025-12-31. One credit agreement (the 2024 Credit Facilities), two tranches:

| tranche | face | net | rate | maturity |
|---|---|---|---|---|
| Term Loan | $1,330,000 (curr. $70,000 + LT $1,260,000) | $1,319,647 | base rate or Term SOFR + margin; blended 6.56% (2025), range 3.54%–6.84% | Nov 1, 2029 |
| Revolving Credit Facility | drawn $142,400 on $600,000 commitment | — | same | Nov 1, 2029 |

Change of control: "in the event of a defined change in control, the 2024 Credit
Facilities may be terminated" → likely refinanced.
Bridge: net $1,455,924 (ST $66,372 + LT $1,389,552); gross $1,472,400 less
$16,476 issuance costs.

### BZH — Beazer Homes USA, Inc.
10-K `0000915840-25-000075`, Note 7 "Borrowings", as of 2025-09-30. Five
tranches:

| tranche | face | net | rate | maturity |
|---|---|---|---|---|
| 5.875% Senior Notes (2027 Notes) | $357,255 | — | 5.875% fixed | Oct 2027 |
| 7.250% Senior Notes (2029 Notes) | $350,000 | — | 7.250% fixed | Oct 2029 |
| 7.500% Senior Notes (2031 Notes) | $250,000 | — | 7.500% fixed | Mar 2031 |
| Junior Subordinated Notes | $100,773 ($100.8M) | $78,470 | floating, wtd-avg 7.02%; $25.8M at 3-mo SOFR + 2.71%, $75M restructured (SOFR, 4.25% floor / 9.25% cap) | Jul 2036 |
| Senior Unsecured Revolving Credit Facility | $0 drawn on $365,000 | — | — | Mar 2028 |

(3 senior notes less $6,611 issuance costs → Total Senior Notes, net $950,644.)
Seniority: Senior Notes rank senior to subordinated indebtedness, effectively
subordinated to future secured debt; Junior Subs subordinated to the Unsecured
Facility and the Senior Notes.
Change of control: **the 10-K debt footnote does not state it.** The
senior-notes change-of-control repurchase offer lives in the indentures (EX-4),
not here — see "Known limitation" below.
Bridge: "Total debt, net $1,029,114"; gross $1,058,028 less $6,611 issuance
costs less $22,303 accretion.

### NATH — Nathan's Famous, Inc.
10-K `0001437749-26-019923`, Note J "Long-Term Debt", as of 2026-03-29. One
tranche:

| tranche | face | rate | maturity |
|---|---|---|---|
| SOFR Term Loan | $48,400 | SOFR-based, effective 5.175% at period end | FY2030 (final payment) |

Change of control: "the Buyer at the Effective Time shall pay all outstanding
obligations under the Credit Facility" (Smithfield merger) → gone at close.
Bridge: "Total debt, net of debt issuance costs $48,143" (face $48,400 less $257
issuance costs); face total also stated $48,400.

---

## Run

```bash
python test_capital_structure.py            # ANTHROPIC_API_KEY from env
python test_capital_structure.py sk-ant-... # or key as arg 1
```

## Results against the three targets — run 2026-09-09 (claude-sonnet-5)

All three reconcile to the filing's stated total with **delta 0**, and where a
face total is also stated, that cross-check is delta 0 too.

### CBZ — status OK. 2 debt tranches + 1 undrawn facility (hand-read: 2)

| tranche | figure | rate | maturity | change of control |
|---|---|---|---|---|
| Term Loan | face $1,330,000 (net ~$1,320,000) | Base Rate or Term SOFR + spread (1.375%–2.50% over SOFR); blended 6.56%, range 3.54%–6.84% | 2029-11-01 | "the 2024 Credit Facilities may be terminated" |
| Revolving Credit Facility | drawn **$142,400** / capacity $600,000 | same | 2029-11-01 | same |

Undrawn capacity (not debt): Other line of credit (CBIZ Benefits / Huntington),
$0 drawn on $20,000, matures 2026-07-30.

Bridge: $1,330,000 + $142,400 − $3,628 − $6,495 − $6,353 = **$1,455,924** =
Total short-term debt $66,372 + Total long-term debt $1,389,552. The footnote has
no single combined total; the module summed the two subtotals and recorded that.

### BZH — status OK. 4 debt tranches + 1 undrawn facility (hand-read: 5, the hard case)

| tranche | face | net | rate | maturity | seniority |
|---|---|---|---|---|---|
| 5.875% Senior Notes (2027) | $357,255 | — | 5.875% fixed | 2027-10 | senior unsecured; senior to subordinated, effectively subordinated to future secured |
| 7.250% Senior Notes (2029) | $350,000 | — | 7.250% fixed | 2029-10 | same |
| 7.500% Senior Notes (2031) | $250,000 | — | 7.500% fixed | 2031-03 | same |
| Junior Subordinated Notes | $100,773 ($100.8M) | $78,470 | floating, wtd-avg 7.02%; $75M restructured (4.25% floor / 9.25% cap), $25.8M at 3-mo SOFR + 2.71% | 2036-07 | subordinated to the Unsecured Facility and the Senior Notes |

Undrawn capacity (not debt): Senior Unsecured Revolving Credit Facility, $0 drawn
on $365,000 ($41.4M letters of credit), matures 2028-03-15.

Bridge: $357,255 + $350,000 + $250,000 + $100,773 − $6,611 (issuance costs)
− $22,303 (junior-sub accretion) = **$1,029,114** = "Total debt, net" (delta 0;
a run that reads the junior-sub face as "$100.8M" from prose lands at delta 27,
inside tolerance). Face cross-check: tranche face sum $1,058,028 = the
future-maturities table total.

**Change of control: the three senior notes carry a change-of-control put at
101% of principal** — read from each note's own indenture (EX-4.1 of the 8-Ks
filed 2017-10-10, 2019-09-24, 2024-03-18). The put is the holder's option, so
the notes survive the merger: tradeable, the credit opportunity. The junior
subs and the revolver stay "not stated". (Before the refinement below this field
was blank for BZH — the debt footnote is silent on it.)

### NATH — status OK. 1 debt tranche + 1 undrawn facility (hand-read: 1)

| tranche | figure | rate | maturity | change of control |
|---|---|---|---|---|
| SOFR Term Loan | face $48,400 (net $48,143) | Term SOFR + 1.40%; effective 5.175% at 2026-03-29 | 2029-07-10 (FY2030) | Change of Control is an Event of Default; **"Pursuant to the Merger Agreement, the Buyer at the Effective Time shall pay all outstanding obligations under the Credit Facility"** — gone at close |

Undrawn capacity (not debt): Revolving Loan under the same Citibank credit
agreement, $0 drawn on $10,000, matures 2029-07-10.

Bridge: $48,400 − $257 (issuance costs) = **$48,143** = "Total debt, net of debt
issuance costs". Face cross-check: $48,400 = the mandatory-repayment table total,
delta 0.

### Takeaways for review

- **Reconciliation held on all three**, including BZH's five-line table with two
  separate adjustment lines. The bridge is doing its job.
- **$0-drawn ancillary facilities now render as "undrawn capacity", separate
  from and subordinate to the debt tranches** (CBZ's Huntington line, NATH's and
  BZH's revolvers) — capacity context, not a weighted tranche.
- CBZ's Term Loan net (~$1,320,000) is the model's own derivation from the
  table's four issuance-cost lines; face ($1,330,000) is the figure the bridge
  and the customer care about.

---

## Refinements — run 2026-09-09

1. **Change-of-control now extends to the EX-4 indenture for public notes.** The
   module parses the 10-K exhibit index for each note's indenture reference,
   follows it to the source 8-K, locates the "Change of Control" clause (that
   clause only), and reads the put terms. **BZH now shows a change-of-control
   put at 101% of principal on all three senior notes** — 5.875%/2027 (EX-4.1,
   8-K 2017-10-10), 7.250%/2029 (EX-4.1, 8-K 2019-09-24), 7.500%/2031 (EX-4.1,
   8-K 2024-03-18) — the put is the holder's option, so the notes survive: the
   credit opportunity. Junior subs and the revolver stay null. No indenture
   found / no clause → stays null, not guessed.
2. **$0-drawn facilities moved to an "undrawn capacity" list**, separate from
   and subordinate to the debt tranches. Reconciliation unaffected (they carry
   no principal); all three still bridge to delta 0.
3. Face vs net left as-is: reconcile and display on face, net secondary.

## Verification — false positives and a feed run (2026-09-09)

- **Each BZH put is its own read.** Fetched all three indentures directly:
  distinct docs (2017/2019/2024), each naming only its own coupon, each
  stating 101% — the 2024 one worded differently. Not one clause matched thrice.
- **False-positive bug found and fixed.** `_match_ref` fell back to same-year
  matching, so OGN's 7.875%/2034 picked up the 6.750%/2034 indenture's put. Now
  a coupon-named tranche matches only that exact coupon's indenture; a different
  coupon sharing the year forces null, not the sibling's document.
- **Feed run, 12 targets.** Puts asserted only on a coupon-matched indenture with
  a located clause: **BZH ×3, OGN ×3** (4.125/28, 5.125/31, 6.750/34), all 101%,
  all holder-option/survives. Null everywhere uncertain: WBD (maturity buckets,
  no coupons), GBCS (private promissory notes), AES/CZR (no indenture in the
  parsed exhibit index), OGN 7.875% (no ref) and its euro notes (ref matched, no
  clause located — a real put the locator likely missed; null is safe).
- **No put appeared where the chain couldn't prove one.** CBZ/BZH/NATH unchanged.
