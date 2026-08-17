"""
Tests for blended pricing.

Two things under test:
  1. The math is right on real deals with known answers.
  2. Each barrier actually fires when it should. A barrier that never blocks
     anything is decoration.

GSAT numbers are hand-verified from 8-K 0001140361-26-014528.
"""
import sys
from datetime import datetime, timedelta
sys.path.insert(0, '/home/claude/pricing')
from deal_pricing import (compute_blended, run_barriers, classify_structure,
                          failure_tally, BARRIER_NAMES,
                          B_LEG_PARITY, B_COMPLETENESS, B_PREMIUM, B_FIELD_SANITY,
                          B_TICKER_IN_DOC, B_DETERMINISM, B_PRICE_FRESH,
                          B_DIVERGENCE, B_MOVEMENT, B_QUOTE_MATCH)

NOW = datetime.utcnow()
FRESH = NOW - timedelta(hours=2)

GSAT_TERMS = {
    'cash': 90.00,
    'ratio': 0.3210,
    'acquirer_ticker': 'AMZN',
    'cash_cap': 0.40,
    'collar_high': 90.00,
}
GSAT_FILING = ("Under the terms of the merger agreement, Globalstar stockholders will "
               "elect to receive for each share either (i) $90.00 in cash or (ii) 0.3210 "
               "shares of Amazon (NASDAQ: AMZN) common stock with a value capped at "
               "$90.00 per share. This consideration is subject to a proration mechanism "
               "that caps aggregate cash elections to a maximum of 40% of total "
               "Globalstar shares.")

print("blended pricing")
print("=" * 80)
ok = True


def check(label, condition, detail=""):
    global ok
    ok &= condition
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if detail:
        print(f"        {detail}")


# ── the math ──────────────────────────────────────────────────────────────────
print("\nMATH")
print("-" * 80)

# AMZN at 274.48: stock leg 0.3210 * 274.48 = 88.11, under the 90 cap
# blended = 0.40*90.00 + 0.60*88.11 = 88.87
b, why = compute_blended(GSAT_TERMS, 274.48)
check("GSAT at AMZN $274.48 blends to ~$88.87",
      b is not None and abs(b - 88.87) < 0.02, f"got ${b:.2f} — {why}" if b else "no value")

# AMZN at 350: stock leg would be 112.34 but the collar caps it at 90.00
# blended = 0.40*90 + 0.60*90 = 90.00
b, _ = compute_blended(GSAT_TERMS, 350.00)
check("GSAT collar caps the stock leg when AMZN runs up",
      b is not None and abs(b - 90.00) < 0.02, f"got ${b:.2f}" if b else "no value")

# AMZN at 200: stock leg 64.20, no cap applies
# blended = 0.40*90 + 0.60*64.20 = 74.52
b, _ = compute_blended(GSAT_TERMS, 200.00)
check("GSAT blends DOWN when AMZN falls — the case the headline hides",
      b is not None and abs(b - 74.52) < 0.02,
      f"got ${b:.2f}, headline still says $90.00" if b else "no value")

# plain cash
b, _ = compute_blended({'cash': 61.00}, None)
check("plain cash deal returns the cash price",
      b is not None and abs(b - 61.00) < 0.01, f"got ${b}" if b else "no value")

# fixed cash and stock, both legs
b, _ = compute_blended({'cash': 2.75, 'ratio': 0.0295, 'acquirer_ticker': 'CSGP'}, 93.00)
check("cash + stock adds both legs",
      b is not None and abs(b - (2.75 + 0.0295*93.00)) < 0.01, f"got ${b:.2f}" if b else "no value")

check("structure classification: capped election",
      classify_structure(GSAT_TERMS) == 'ELECTION_CAPPED',
      f"got {classify_structure(GSAT_TERMS)}")


# ── the barriers ──────────────────────────────────────────────────────────────
print("\nBARRIERS — the clean case")
print("-" * 80)

blended, why, res = run_barriers(
    GSAT_TERMS, headline_price=90.00, target_price=83.40, acquirer_price=274.48,
    acquirer_price_time=FRESH, filing_text=GSAT_FILING, filing_quote=GSAT_FILING)
failed = [r for r in res if not r.passed]
check("GSAT passes all thirteen", blended is not None,
      f"blended ${blended:.2f}" if blended else
      "blocked by: " + "; ".join(f"[{r.barrier}] {r.detail}" for r in failed))

print("\nBARRIERS — each must fire when it should")
print("-" * 80)

def fires(barrier, label, **kw):
    base = dict(terms=dict(GSAT_TERMS), headline_price=90.00, target_price=83.40,
                acquirer_price=274.48, acquirer_price_time=FRESH,
                filing_text=GSAT_FILING, filing_quote=GSAT_FILING)
    base.update(kw)
    b, _, r = run_barriers(**base)
    hit = next((x for x in r if x.barrier == barrier), None)
    good = hit is not None and not hit.passed and b is None
    check(label, good, hit.detail if hit else "barrier not present in results")

# The filing says "subject to proration", so the caller hints CAPPED. Without
# the hint, a dropped cap would silently reclassify as an uncapped election and
# compute a higher number with no complaint.
fires(B_COMPLETENESS, "10 · capped election with the cap dropped in extraction",
      terms={'cash': 90.00, 'ratio': 0.3210, 'acquirer_ticker': 'AMZN',
             'collar_high': 90.00, 'structure_hint': 'ELECTION_CAPPED'})

fires(B_FIELD_SANITY, "2 · impossible cash cap of 150%",
      terms=dict(GSAT_TERMS, cash_cap=1.5))

fires(B_LEG_PARITY, "3 · ratio off by 3x makes the legs disagree",
      terms=dict(GSAT_TERMS, ratio=1.0))

fires(B_TICKER_IN_DOC, "12 · acquirer ticker absent from the filing",
      terms=dict(GSAT_TERMS, acquirer_ticker='TSLA'))

fires(B_QUOTE_MATCH, "6 · cash figure absent from the quote",
      terms=dict(GSAT_TERMS, cash=77.77))

# Six calendar days back lands several closed sessions behind regardless of
# which weekday the suite runs on, so this exercises session counting rather
# than the elapsed-hours measure it replaced.
fires(B_PRICE_FRESH, "9 · acquirer price several sessions stale",
      acquirer_price_time=NOW - timedelta(days=6))

fires(B_DETERMINISM, "7 · two extractions disagree",
      second_extraction=dict(GSAT_TERMS, cash=85.00))

fires(B_PREMIUM, "11 · blended contradicts the premium the filing states",
      stated_premium=0.60, unaffected_price=70.00)

fires(B_MOVEMENT, "13 · blended jumps while the acquirer sits still",
      previous_blended=40.00, previous_acquirer_price=274.00)

# divergence: a ratio that produces a plausible-looking but far-off blend
fires(B_DIVERGENCE, "5 · blended lands far from the headline",
      terms=dict(GSAT_TERMS, cash=90.00, ratio=0.0100, cash_cap=0.05))


# ── premium check on a real known answer ──────────────────────────────────────
print("\nBARRIER 11 — the strongest check, against a real stated premium")
print("-" * 80)
# ATSG: $22.50 cash, release stated 29.3% premium to the Nov 1 close of $17.40
b, _, r = run_barriers(
    {'cash': 22.50}, headline_price=22.50, target_price=17.40, acquirer_price=None,
    filing_text="Stonepeak will acquire ATSG for $22.50 per share, a premium of "
                "approximately 29.3% over the November 1 closing price.",
    filing_quote="$22.50 per share, a premium of approximately 29.3%",
    stated_premium=0.293, unaffected_price=17.40)
hit = next(x for x in r if x.barrier == B_PREMIUM)
check("ATSG blended reproduces its stated 29.3% premium", hit.passed, hit.detail)


# ── the tally that drives loosening decisions ─────────────────────────────────
print("\nFAILURE TALLY")
print("-" * 80)
runs = []
for terms in (GSAT_TERMS, dict(GSAT_TERMS, ratio=1.0), dict(GSAT_TERMS, cash_cap=1.5)):
    _, _, r = run_barriers(terms, 90.00, 83.40, 274.48, FRESH, GSAT_FILING, GSAT_FILING)
    runs.append(r)
tally = failure_tally(runs)
for bid, n in tally.items():
    print(f"  barrier {bid:>2} blocked {n}x — {BARRIER_NAMES[bid]}")
check("tally records which barriers blocked", len(tally) > 0, f"{tally}")

print("\n" + "=" * 80)
print("ALL PASS" if ok else "SOMETHING FAILED — do not wire in until every barrier fires correctly")