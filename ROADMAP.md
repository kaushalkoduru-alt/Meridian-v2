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

- [ ] **§2 · Audit every formula**
  Current price, deal price, gross spread, annualized spread, days to close,
  expected close, outside date, break price, market-implied probability, risk
  score, regulatory risk, RTF, target fee, fee multiple, transaction value,
  financing status, antitrust obligation, specific performance, position sizing.
  For each: is it mathematically correct, is it financially meaningful, what
  does it assume, can it mislead, what should replace it.
  *Deliverable: a written audit, one entry per metric. Not code.*

- [ ] **§3 · Fix the break price / probability problem**
  The current implied probability is `(current − break) / (deal − break)`.
  Every deal carries `break_price_method: "historical"`, meaning the break price
  is just the unaffected price. WBD sits at $28.83 against a $28.80 modeled
  break, so the denominator is near zero and the probability is meaningless.
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

0 of 22 complete.
