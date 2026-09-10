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

---

## Field-by-field verification — feed targets a credit member would open (2026-09-10)

Beyond the three hand-read targets. Each row: extracted | filing | match. "Reconciles
but wrong" = the tranche total bridges to delta 0 yet a specific field is off —
the errors reconciliation cannot catch.

### CZR — Caesars, 10-K 0001590895-26-000011, Note 9 "Long-Term Debt" ($ in millions)

12 tranches, bridges to **delta 0** (net $11,792 / face $11,905). Table is
Final Maturity · Rates · Face Value · Book Value.

| field | extracted | filing | match |
|---|---|---|---|
| every tranche face | 160 / 637 / 386 / 2,031 / 2,849 / 2,000 / 1,500 / 1,200 / 1,100 / 40 / 2 | same, verbatim from Face Value column | ✓ |
| every tranche net | 160 / 636 / 381 / 2,002 / 2,820 / 1,986 / 1,486 / 1,192 / 1,087 / 40 / 2 | same, Book Value column | ✓ |
| rates (notes) | 7.00 / 6.50 / 4.625 / 6.00 fixed; SID bonds 4.30 | table Rates column | ✓ |
| rates (term loans / revolver) | Adjusted Term SOFR + 2.25% / Base + 1.25%, leverage step-downs | prose, verbatim | ✓ |
| CVA Delayed Draw Term Loan rate | "Term SOFR plus an applicable margin" (vague) | footnote gives the specific margin schedule | **thin — margin not pulled** |
| maturities | month/day added from prose (e.g. 2028-01-31, 2030-02-15) | table gives year only; prose confirms | ✓ (spot-check dates) |
| seniority | "Secured / Unsecured Debt (per table heading)"; notes "rank equally with first-priority lien / senior unsecured obligations" | table sub-headers + prose | ✓ |
| CEI Senior Notes due 2027 | shown as a **$0 tranche**, 8.125%, redeemed 2025-07-08 | table row is all "N/A / — / —"; 8.125% & redemption are in prose | cosmetic — a dead $0 row |
| **change of control** | **null on all 12** | 101% put confirmed — EX-10.1 (7.00%/2030) §4.08: "repurchase … at 101% of the principal amount" | **MISS (parser)** |

CoC miss cause: CZR's 10-K lists each indenture as "Indenture (4.625% CEI Senior
Notes due 2029) … **Previously filed on Form 8-K filed on** September 27, 2021" —
no "incorporated by reference to Exhibit N". `_parse_indenture_refs` requires that
phrasing, so it parses **0 refs** and never looks. The puts are real and standard.

### OGN — Organon, 10-K 0001628280-26-011125, Note 12 ($ in millions)

10 tranches, bridges to **delta 0** ($8,644 total principal, one −$81 adjustment).

| field | extracted | filing | match |
|---|---|---|---|
| every tranche face | 1,543 / 843 / 2,100 / 1,470 / 1,582 / 500 / 500 / 179 / 0 / 8 | same, verbatim from the table | ✓ |
| net per tranche | null (table shows principal only + one aggregate adj) | matches table structure | ✓ |
| term-loan rates | Term SOFR + 2.25% (floor 0.50%); EURIBOR + 2.75% (floor 0.00%) | prose after Amendment No. 3, verbatim | ✓ |
| note coupons | 4.125 / 2.875 / 5.125 / 6.750 / 7.875 fixed | table | ✓ |
| maturities | year only (2028 / 2031 / 2034) | footnote gives year only ("due 2028") | ✓ (faithful; dates are in the indentures, not the footnote) |
| seniority | secured / unsecured per tranche; **7.875% → null** | prose: "7.875% **senior unsecured** notes due 2034" | 7.875% seniority **MISS** (in prose, not pulled) |
| CoC 4.125% / 5.125% / 6.750% | 101% put, right indentures (EX-10.6 / 10.7 / EX-4.1) | confirmed | ✓ |
| **CoC 2.875% euro notes** | **null** | **101% put — EX-10.5** §"Change of Control Offer … equal to 101% of the aggregate principal amount" | **WRONG** |
| **CoC 7.875% notes** | **null** ("no matching indenture reference") | **101% put — EX-4.3** ("INDENTURE Dated as of May 17, 2024 … Upon Change of Control … offer to purchase") | **WRONG** |

CoC miss causes: (1) the 2.875% euro indenture reference line is longer than
`_parse_indenture_refs`' ~480-char window (extra parties — Elavon, UK Branch), so
the "Exhibit 10.5" token is truncated and the parser falls through to a shorter
later row → matches **First Supplemental Indenture EX-10.8 (8 KB)** instead of the
base **EX-10.5 (584 KB)**. (2) The 7.875% (EX-4.3, same May-2024 8-K as the
6.750%) row isn't picked up at all.

### GSAT — Globalstar, 10-K 0001366868-26-000012, Note 7 ($ in thousands)

3 "tranches", all Customer funding/repayment agreements (not notes or loans).
Bridges to **delta 0** (principal $410,022 + $73,766 = carrying $483,788).

| field | extracted | filing | match |
|---|---|---|---|
| principal / carrying, each row | 221,625 → 307,670 · 182,147 → 169,983 · 6,250 → 6,135 | verbatim from the Principal / Carrying Value columns | ✓ |
| **net > face on "2024 Debt Repayment"** | net $307,670 vs face $221,625 (+$86,045) | **correct** — a real premium/accretion from the Apple-funded retirement of the old 13% notes, not a bug | ✓ |
| 2023 Funding Agreement capacity | $252,000 | prose ("up to $252 million") | ✓ |
| rates | 2021 "no interest"; 2023/2024 "fees at an undisclosed fixed rate" | footnote states no numeric rate for 2023/2024 | ✓ (faithful) |
| seniority | first-priority lien over substantially all assets | verbatim | ✓ |
| CoC | null | bilateral agreements, no indenture; not in the located section | acceptable |

Faithful read of an exotic structure. A credit member should read these as bespoke
Customer arrangements, not marketable debt.

### AVNS — Avanos, 10-K 0001606498-26-000004, Note 10 "Debt" ($ in millions)

1 term loan + 1 undrawn revolver. Bridges to **delta 0**.

| field | extracted | filing | match |
|---|---|---|---|
| Term Loan Facility face | $100.8 | table | ✓ |
| rate | 5.79% WAIR; SOFR + 1.50–2.00% by leverage; 5.6% effective | verbatim | ✓ |
| maturity | 2027-06-24 | "will mature on June 24, 2027" | ✓ |
| seniority | senior secured, first-priority lien | verbatim | ✓ |
| undrawn revolver | $0 drawn / $375.0M / $4.1M LCs | verbatim | ✓ |
| CoC | null | no indenture; standard credit-agreement negative covenants only | correct |

Clean.

---

## Coverage check 1 — null / incomplete where debt actually exists

| target | verdict | detail |
|---|---|---|
| **ALOT** | **MISS** | Has a Credit Agreement — "Term Loan" $9.5M + "Term A-2 Loan" $9.6M + a revolver. `_HEAD_PAT` finds **zero** candidates: ALOT titles the note **"Note 8—Credit Agreement and Debt Facilities"**, which leads with "Credit Agreement"; the patterns key on Debt / Borrowings / Long-Term Debt / Credit Facilities, not "Credit Agreement". |
| **GBTG** | **MISS** | Has a **$1,386M senior secured term loan** (net $1,367M, matures July 2031) + $51M other borrowings; total debt net $1,418M. The FS note "(13) Long-term Debt" is at char 504,056, but `_score_heading` picked an earlier MD&A cross-reference ("see note 13 - Long-term Debt") and fed the model MD&A prose → "no tranche-level disclosure". |
| **AES** | **WRONG FOOTNOTE** | Landed on **Schedule I** ("2. Debt — Senior and Unsecured Notes and Loans Payable", 3,831 chars) — the Parent-Company-only condensed schedule. Reported total "Subtotal $5,984M" ≈ AES's $6.0B *recourse* debt, with 10 notes and no label that it excludes the **$23.2B of non-recourse project debt** disclosed elsewhere. The consolidated debt footnote (split "Recourse Debt" / "Non-Recourse Debt") was not located. A credit analyst reads AES's debt as ~$29B, not $6B. |
| PAYO | null SAFE | No term loan, notes, or drawn facility anywhere. Only "debt-like" balance-sheet lines are Skuad/PayEco acquisition earnout & deferred-payment liabilities. Genuinely debt-free. |
| APGE | null SAFE | Biotech, recent IPO. No debt on the balance sheet or in any footnote. |
| CPRX | null SAFE | Cash-rich pharma, term loan repaid in prior years. No current debt. |

## Coverage check 2 — OGN euro notes

**The put exists.** Read EX-10.5 directly (the base 2.875% Senior Secured Notes
indenture, 584 KB): *"the Issuers shall make an offer to purchase all of the Notes
… (a 'Change of Control Offer') at a price in cash … equal to 101% of the
aggregate principal amount thereof plus accrued and unpaid interest."* Same clause
in EX-4.3 for the 7.875%. So OGN carries the 101% put on **all five** note series,
not three. The locator needs: (a) window widened from ~480 to ≥900 chars so a long
reference line doesn't truncate before the exhibit token; (b) a base
"Indenture Dated as of …" preferred over a "Supplemental Indenture" on a coupon
match. `_parse_indenture_refs` also needs a second phrasing — "… Previously filed
on Form 8-K filed on <date>" (no exhibit number) — to reach CZR's indentures.

**Not applied — verification only.** Fixes to make before display: (1) widen the
indenture-reference parser (window + phrasing + supplemental de-prioritisation) —
recovers OGN ×2 and CZR ×4+ CoC puts; (2) `_HEAD_PAT` to accept "Credit
Agreement …" as a debt-note heading — recovers ALOT; (3) `_score_heading` to
reject MD&A cross-reference context ("see note NN") — recovers GBTG; (4) skip
Schedule I / Parent-Company condensed debt schedules, or label them recourse-only
— fixes AES.
