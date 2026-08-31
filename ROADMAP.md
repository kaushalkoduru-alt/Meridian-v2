# Meridian — product audit roadmap

Source: the 29-section product prompt, Aug 2026.

## How this file works

A box gets checked when the section is **completely** done. Not "mostly", not
"done except one edge case". If anything is left, it stays open with a note
saying what.

The reason is the same one that governs the rest of this codebase: a half-done
thing marked finished is worse than an open one, because nobody goes back to
look. Three separate caching bugs in this project survived for weeks because
something looked done and wasn't.

Sections are grouped by whether they get built **now**, **later**, or **not
until there are users**. That last group is not a judgment on the ideas. It is
a judgment on sequence.

---

## NOW — correctness and trust (P0)

These fix things that are wrong on the live site today. Every one of them is
about a number being misleading, not about a feature being missing.

- [x] **§2 · Audit every formula**
  Current price, deal price, gross spread, annualized spread, days to close,
  expected close, outside date, break price, market-implied probability, risk
  score, regulatory risk, RTF, target fee, fee multiple, transaction value,
  financing status, antitrust obligation, specific performance, position sizing.
  For each: is it mathematically correct, is it financially meaningful, what
  does it assume, can it mislead, what should replace it.
  *Deliverable: a written audit, one entry per metric. Not code.*
  **Done — [AUDIT.md](AUDIT.md).** All 19 metrics have an entry answering all
  five questions. Verdicts: 6 BROKEN, 6 MISLEADING, 7 SOUND. Four of the twelve
  defects trace to the break price being an unvalidated price lookup that
  everything downstream treats as a modeled floor, which confirms the §3/§4
  sequencing. Four more are independent of §4 and cost hours: the position
  size table's hardcoded minus sign (#19), the probability clamp that turns
  AES's sign error into 99.9% beside a red "Distressed" label (#9), the
  `VERIFIED_TX_VALUES` override that only applies when extraction failed (#15),
  and the close-date parser that reads "late 2026 or early 2027" as 31 March
  2026 (#5). Extraction accuracy per deal was scoped to §25, not audited here.

- [ ] **§3 · Fix the break price / probability problem**
  The current implied probability is `(current − break) / (deal − break)`.
  Every deal carries `break_price_method: "historical"`, meaning the break price
  is just the unaffected price. Two live deals show what that costs, and they
  fail in different ways.

  WBD trades at $28.90 against a $28.80 modeled break. The denominator,
  deal − break, is $2.20 and perfectly healthy. It is the NUMERATOR,
  current − break, that collapses to $0.10 — so the formula reports a 4.5%
  chance of closing on a deal trading 7% below terms. Fixing this means
  looking at how close the current price sits to the modeled break, not at
  the spread between deal and break.

  AES is worse, and is not a precision problem at all. Its modeled break of
  $16.87 sits ABOVE both the current price ($14.73) and the deal price
  ($15.00), so both halves of the fraction go negative, the signs cancel, and
  the formula returns 114.4% — a probability over one, printed to the live
  site. No improvement to the break-price model catches this, because a
  better break price can still land above the current price on a deal the
  market has marked down. It needs an explicit guard: when the current price
  is at or below the modeled break, the two-state model does not apply and
  there is no probability to print.

  Must distinguish: unaffected price, modeled break price, observed current
  price, deal consideration, downside to break, probability of close.
  Where the two-state model does not apply, say so instead of printing a number.
  *This is the single most important item in the document.*

- [ ] **§20 · Separate fact from model from inference from forecast**
  FACT: "the agreement provides a $7B regulatory termination fee."
  MODEL: "estimated break price $28.80."
  INFERENCE: "contractual protection appears strong."
  FORECAST: "estimated probability of close 82%."
  Distinct visual treatment for each. A PM must never mistake an extracted
  contractual fact for a model estimate.
  *Closest to what this product already does well, and the cheapest to finish.*

- [ ] **§25 · QA report on the 12 live deals**
  Not generic infrastructure — go through the actual feed and find questionable
  break prices, questionable probabilities, questionable risk scores, stale
  data, missing contract terms, missing sources, wrong formulas, edge cases.
  *Same discipline as the 39-deal hand verification, pointed at production.*
  **Report written — [QA.md](QA.md).** All twelve deals have an entry covering
  all nine checks. 20 findings: 7 FORMULA, 6 COVERAGE, 7 DATA.
  **Box stays open.** Three findings need a decision before anything can be
  built on them — what replaces AES's break price, whether expected close is a
  point or an interval (four deals now show a close after their own contractual
  deadline, which is an artifact of the end-of-period convention rather than
  four data errors), and whether GBCS is four days from closing or from lapsing.
  One check could not be completed: ALOT is the only deal whose agreement yields
  no outside date, and whether that is the agreement or the extractor needs the
  exhibit read by hand.
  Highest-value item found: outside dates are readable for 11 of 12 deals but
  cached for only 4, because the production agreement markers were never
  cleared. Second: `EDGAR_QUERIES` hardcodes `enddt=2026-07-24`, so no deal
  announced in the last 34 days can be detected at all.
  §2's #19 (the position-size sign error) was fixed alongside this report; it is
  a §25 item, and §2 stays checked on its own deliverable.

---

## NOW — high value, moderate effort (P1)

- [ ] **§4 · Break-price engine**
  Replace "unaffected price" with a framework: unaffected price, recent
  unaffected range, sector movement, company developments, standalone value,
  termination fee economics, cash burn, litigation and transaction costs,
  regulatory remedies, financing, alternative outcomes.
  Base / bull / bear breaks, but only where the data supports scenarios.
  Label it a model estimate, never a floor.
  *Scoped: implement base break properly first. Bull/bear only where real
  inputs exist, not as three guesses wearing a range.*

- [ ] **§8 · Data freshness**
  LAST VERIFIED and LAST UPDATED per critical field, and a LIVE / RECENT /
  STALE / NEEDS REVIEW state. Prevents stale information from silently becoming
  investment information.
  *Cheap, and it directly serves the trust layer.*

- [ ] **§19 · Confidence levels**
  HIGH / MEDIUM / LOW on every analytical conclusion, based on source quality,
  freshness, completeness, ambiguity of the agreement language, and model
  uncertainty. "Break price $28.80, confidence MEDIUM, unclear standalone
  valuation" beats presenting it as fact.

---

## NOW — expand what already exists

- [ ] **§6 · Deepen the merger agreement extraction**
  Built: RTF with asymmetry, antitrust efforts covenant, financing condition,
  specific performance. 11 of 12 deals carry a fee.
  Missing: RTF trigger conditions and when payable, regulatory vs financing vs
  other RTF, target fee triggers (superior proposal, fiduciary out), specific
  performance exceptions and caps, financing outs, full termination rights by
  party, and a section number for each classification.

- [ ] **§7 · Source and auditability**
  Built: the filing quote under every commitment reading and structure flag.
  Missing: section numbers (§7.03(b)), a "view evidence" interaction that goes
  from classification to reasoning to the agreement section to the language,
  and source provenance on the non-contractual fields.

- [ ] **§13 · Deal clock**
  Built: outside date with automatic/elective extension classification, days
  since announcement.
  Missing: days to expected close, expected close vs outside date, regulatory
  clock status, TIME AT RISK, annualized return after a realistic delay.
  *A 10% spread closing in 30 days is a different trade from 10% in 300.*

- [ ] **§23 · Deal screener**
  Built: the dashboard with risk grouping and V3 sorting.
  Missing: the full column set (probability, confidence, next catalyst,
  regulatory stage, RTF multiple, downside), plus sorting and filtering.

---

## MODIFIED — build it differently than the prompt asks

- [ ] **§9 · Risk score, explainable but not falsely precise**
  The prompt asks for eight weighted sub-scores. It also says "do not create
  fake precision." Those conflict, and the data settles it: 39 verified deals
  with 4 failures could not validate the six factors V3 already has. Eight
  weighted categories would fit noise harder, in more detail.
  **Build instead:** the same categories as *explanation* — regulatory, legal,
  financing, timing, shareholder, MAC, contractual protection, market — each
  showing the evidence behind it, without a number that implies it was
  measured. "Regulatory: weak antitrust covenant, $7B RTF" not "Regulatory: 68".
  Where evidence is insufficient, say so.

---

## LATER — blocked on something that does not exist yet

- [ ] **§5 · Deal outcome tree**
  Close / break / renegotiation / remedy / superior bid, each with a price,
  probability, expected P&L, trigger, confidence.
  *Blocked on §4. And the probabilities cannot be honest until the dataset is
  much larger than 39 deals with 4 breaks.*

- [ ] **§10 · Why the spread exists**
  Rank the reasons: regulatory, litigation, financing, timing, shareholder,
  political, technicals, competing bid, break-price uncertainty, structure.
  *Blocked on §4 and §9. Attributing a spread requires first knowing the
  spread is measured correctly.*

- [ ] **§11 · What changes my thesis**
  Bull and bear catalysts with expected date, importance, status, expected
  impact.
  *Blocked on milestone detection.*

- [ ] **§12 · Catalyst timeline**
  Announcement → HSR → second request → agency decision → shareholder vote →
  court → expected close → outside date.
  *Blocked on milestone detection. This is the biggest single unlock in the
  document: HSR expiration, second requests, and vote scheduling are all
  detectable from filings, and they feed §11, §16, and §17.*

- [ ] **§14 · Scenario position sizing**
  Expand the size table to show P&L under each break scenario, expected P&L,
  annualized expected return, and keep maximum theoretical loss, modeled loss,
  and expected loss distinct.
  *Blocked on §4 and §5.*

- [ ] **§16 · Today's attention / morning workflow**
  What changed since yesterday, what needs attention now.
  *Blocked on milestone detection and on history that only starts accumulating
  from the detection-freeze fix onward.*

- [ ] **§21 · PM view**
  What matters, what protects you, what breaks the thesis, next catalyst, key
  question.
  *This is a synthesis of §4, §9, §10, §11, §12. Cannot be honest before they
  exist.*

---

## NOT UNTIL THERE ARE USERS

Not bad ideas. All three are workflow features for funds, and the product has
no users. Building them now is more surface area aimed at a customer who has
not been found.

- [ ] **§15 · Portfolio dashboard**
  Capital deployed, weighted spread, exposure, concentration, deals by stage.
  *Assumes someone holds positions. Nobody does.*

- [ ] **§17 · Alerts**
  Spread moves, regulatory action, outside date approaching, filing changes.
  *Assumes someone to alert. Also mostly blocked on milestone detection.*

- [ ] **§18 · Deal comparison**
  Side by side with transparent reasoning about which is more attractive.
  *Real value, but it compares numbers that §2 and §3 have not yet made
  trustworthy. Building it now would compare two wrong break prices.*

---

## NOT TASKS — standing rules and framing

These need no checkbox. They govern everything above.

- **§1 · Product objective.** The fifteen questions every deal should answer.
  Use as the test for whether a feature earns its place.
- **§22 · UI/UX.** Dark, institutional, terminal-like, information-dense.
  Preserve it. No consumer-app aesthetics, no decorative charts.
- **§24 · Do not overbuild.** Every feature must answer "would a merger-arb
  analyst actually use this?"
- **§26 · Trust layer.** Where did this come from, when was it updated, what
  assumes it, how confident are we, what would change it. Expressed through
  §7, §8, §19, §20 rather than as its own build.
- **§27 · Do not destroy existing functionality.** Inspect before modifying.
  Three enforcing gates and five extraction modules are live.
- **§28 · Implementation plan.** This file.
- **§29 · Final standard.** Triage, then underwrite, then indispensable.
  And: be brutally honest, fix invalid formulas, remove false precision.

---

## Sequence

1. §2 audit — everything else depends on knowing what is wrong
2. §25 QA on the 12 live deals — the audit made concrete
3. §3 break price and probability — the worst live error
4. §4 break-price engine — what §3 needs to be correct
5. §20 fact vs model — cheap, high trust
6. §8 freshness and §19 confidence — cheap, high trust
7. §9 explainable risk, §6 §7 §13 §23 expansions
8. Milestone detection — unlocks §11, §12, §16, §17
9. Everything deferred

## Progress

- §2 · Audit every formula — [AUDIT.md](AUDIT.md)

---

# Part two — sections 30 to 45

Added Aug 2026. Same rule: a box is checked only when the section is
completely done.

Several of these sharpen things Part One treated loosely, and three of them
name defects the audit found independently. Where that happens it is noted,
because a section already half-addressed by accident still has to be finished
deliberately.

---

## NOW — correctness and trust (P0)

- [ ] **§30 · Critical modeling corrections**

  **A. All-cash does not mean financing secured.** An all-cash deal can still
  run on debt, bridge, credit facilities, equity, or asset sales. Separate
  CONSIDERATION STRUCTURE (cash / stock / mixed / CVR / tender) from FINANCING
  CERTAINTY (no financing required / fully committed / debt committed / equity
  commitment / condition present / subject to conditions / insufficient
  evidence). Never infer the second from the first.
  *Partly exposed already: `check_financing` reads the agreement properly, but
  `score_deal` uses the weaker press-release scan, and `financing_signal` has
  no source label at all.*

  **B. Private equity does not mean financing risk.** Judge the actual
  structure — equity and debt commitment letters, financing conditions, limited
  guarantee, specific performance, reverse termination fee, debt-market
  dependency, fund capacity. Not the buyer's category.
  *Related defect already fixed: `get_acquirer_type` returned Private Equity
  unconditionally when `deal_type` said so, which put Amazon in the PE bucket.
  The stereotype was structural, not just editorial.*

  **C. A large premium is not evidence a deal will close.** Audit any logic
  treating premium size as safety. Premium is useful for standalone downside,
  valuation, break-price work, and shareholder incentives. It says nothing on
  its own about buyer commitment, termination rights, probability, or
  regulatory risk. If kept, state what it actually measures.

- [ ] **§31 · Probability terminology and false precision**
  Four distinct concepts, each labelled as itself: two-outcome implied
  probability (with its assumptions disclosed), scenario-weighted model
  probability (labelled a Meridian estimate), analyst-assessed probability
  (labelled judgment), and market signal (spread as evidence of uncertainty,
  not as a probability). Prefer High/Medium/Low or a range over 76.43% where
  the uncertainty does not justify precision.
  Where current price sits below the modeled break, print the reason rather
  than a number.
  *Companion to §3. §3 fixes the mathematics; this fixes what the product
  claims about it. Partly done — the clamp is deleted and the model refuses to
  print when it does not apply.*

- [ ] **§32 · Spread is a signal, not a probability**
  Remove any copy or logic implying spread predicts outcome, and any rigid
  bucket (0-5% safe, 25%+ near-certain break) not supported by evidence.
  *The 39-deal dataset already settles this: break rate below the median spread
  was 10.5%, at or above 10.0%, and the bucket rates were non-monotonic. The
  product's own data says spread did not predict breaking in that sample. Any
  surviving language claiming otherwise contradicts the methodology page.*

- [ ] **§43 · Remove cool but misleading features**
  Anything that produces a confident number it cannot defend gets removed or
  relabelled. Prefer "insufficient evidence" over an unsupported figure, and
  "model estimate, medium confidence" over "true break price: $28.80".
  *Four instances already found and fixed: the probability clamp turning 114%
  into a confident 99.9%, the annualized figure that was the spread times a
  constant, the fabricated close dates, and `tx_value_source` reading
  `regex_enterprise` over a model's number. This section is the sweep for the
  rest.*

---

## NOW — P1

- [ ] **§33 · Methodology page audit**
  Read it as a skeptical PM, a quant, and an M&A lawyer. Find every claim that
  overstates confidence, implies causation, leans on a weak sample, presents an
  assumption as fact, or generalizes too far. It should say plainly what is
  fact, what is estimate, what is assumed, and what the limits are.
  *The backtest paragraph already does this well. The rest of the page has not
  been held to the same standard.*

- [ ] **§34 · Data quality gates**
  A completeness framework per deal — economics, contractual terms, regulatory,
  break price, financing — with mandatory validation before a deal can present
  as fully analyzed. No high-confidence probability where break-price
  confidence is low, financing is missing, or regulatory status is stale.
  Not gamification: it should reflect actual required fields.
  *The provenance inventory is the input. Four fields already carry real
  validation; the rest do not.*

- [ ] **§35 · Research status per deal**
  RAW / IN REVIEW / VERIFIED / MONITORED / STALE / ARCHIVED.
  Not every deal should look equally trustworthy, and right now they all do.
  *Pairs with §8 freshness and §34.*

- [ ] **§36 · Positioning audit**
  Remove any framing as a cheaper Bloomberg or any price comparison implying
  feature equivalence. Compete on specialization, contractual intelligence,
  underwriting workflow, source transparency. Focus over breadth.
  *Cheap. Mostly copy.*

- [ ] **§37 · Landing page shows the product**
  One deal, one screen: economics, downside, contractual intelligence, why the
  spread exists, and a real agreement excerpt as source evidence. A visitor
  should understand the value in seconds rather than reading feature
  descriptions.
  *Higher priority than its number suggests. The differentiator is currently
  invisible until someone clicks into a deal page.*

---

## LATER — blocked

- [ ] **§40 · Daily workflow and morning brief**
  What changed overnight, which spreads moved, which deals have catalysts
  today, which regulatory developments landed, which outside dates approach,
  which positions changed risk, which deals need deeper research.
  *Same block as §16: milestone detection, plus history that only starts
  accumulating from the detection-freeze fix onward.*

---

## NOT UNTIL THERE ARE USERS

- [ ] **§38 · User segmentation and pricing**
  Individual, professional, team. The section says it itself: do not finalize
  pricing without user interviews. Architecture can be designed for it; pricing
  cannot be set from a desk.

- [ ] **§41 · Product-market-fit instrumentation**
  Which deals get opened, which modules get used, time per deal, repeat visits,
  most-clicked sources, features ignored.
  *Worth building the moment there is a first user, and worth nothing before
  then. The argument for building early is that data accumulates — but with no
  traffic there is nothing to accumulate.*

---

## NOT TASKS — evaluation lenses

- **§39 · What manual work does this replace?** Reading a 200-page agreement,
  checking DOJ and FTC sites, maintaining a spreadsheet, calculating scenario
  returns, remembering what changed yesterday. The goal is eliminating
  repetitive research, not providing information.
- **§42 · Professional trust test.** Accuracy, sourceability, freshness,
  methodology, uncertainty, consistency, actionability. A feature failing these
  gets improved or removed before it can be called institutional-grade.
- **§44 · Traceability chain.** Primary sources → structured facts →
  transparent interpretation → scenario modeling → risk and return → catalyst
  monitoring → daily workflow. Every layer links back to the one above. A PM
  must be able to go from "why is this risk HIGH" down to the agreement
  section and the actual language.
- **§45 · Execution priority.** P0 trust and correctness, P1 differentiation,
  P2 daily workflow, P3 commercialization, P4 polish. P4 must not displace P0.

---

## Revised sequence

§45 reorders Part One. Merged priority:

1. **§2 audit** — done as a document, findings still open
2. **§25 QA** — twelve deals covered, eight new ones arrived
3. **§3 + §31** — break price and probability, mathematics and language together
4. **§4** — the break-price engine §3 needs
5. **§30** — the three modeling corrections, all P0 and all cheap
6. **§32 + §33 + §36** — spread language, methodology, positioning. Copy work,
   one pass
7. **§43** — the sweep for remaining false precision
8. **§20 + §8 + §19 + §34 + §35** — the trust layer, which §44 says must exist
   before anything above it can be relied on
9. **§6 §7 §13 §23 §37** — expansions and the landing page demonstration
10. **Milestone detection** — unlocks §11, §12, §16, §17, §40
11. Everything deferred

## Progress

1 of 34 complete.
