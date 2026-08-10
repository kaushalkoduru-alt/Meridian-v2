"""
FIRST LOOK AT THE HISTORICAL DATASET

39 hand-verified deals, 2022-2025, every row read against a primary filing.

WHAT THIS IS AND IS NOT
    This is descriptive. With 4 broken deals in the whole set, no slice
    supports a statistical claim -- bucket by spread and you get one or two
    breaks per bucket, where moving a single deal swings the rate by tens of
    percent. So the output reports counts alongside every rate, and says
    plainly where the sample is too thin to lean on.

    A backtest that reported "wide spreads break 3x more often" off four
    observations would be the fabricated backtest wearing better clothes.

Run from meridian-v2:
    python analyze_dataset.py
"""

import csv
import sys
from collections import Counter, defaultdict

WORKSHEET = "worksheet.csv"


def load():
    rows = []
    with open(WORKSHEET, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                sp = float(r.get("spread_at_announcement_pct"))
            except (TypeError, ValueError):
                continue
            outcome = (r.get("outcome") or "").strip().upper()
            if outcome not in ("CLOSED", "BROKEN"):
                continue
            try:
                dp = float(r.get("deal_price"))
            except (TypeError, ValueError):
                dp = None
            try:
                days = int(float(r.get("days_to_resolution")))
            except (TypeError, ValueError):
                days = None
            rows.append({
                "ticker": (r.get("ticker") or "").strip(),
                "spread": sp,
                "outcome": outcome,
                "deal_price": dp,
                "days": days,
                "acquirer": (r.get("acquirer") or "").strip(),
                "notes": (r.get("consideration_notes") or "") + " " + (r.get("notes") or ""),
                "announced": (r.get("announced_date") or "").strip(),
            })
    return rows


def rate_line(label, deals, width=34):
    """A rate is meaningless without its denominator, so always print both."""
    n = len(deals)
    if n == 0:
        return f"  {label:<{width}} no deals"
    broke = sum(1 for d in deals if d["outcome"] == "BROKEN")
    pct = broke / n * 100
    warn = "   (too few to lean on)" if n < 8 else ""
    return f"  {label:<{width}} {broke}/{n} broke = {pct:5.1f}%{warn}"


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main():
    deals = load()
    if not deals:
        print("no usable rows -- need spread_at_announcement_pct and outcome CLOSED/BROKEN")
        return

    n = len(deals)
    broke = [d for d in deals if d["outcome"] == "BROKEN"]
    closed = [d for d in deals if d["outcome"] == "CLOSED"]

    print("=" * 74)
    print("MERIDIAN HISTORICAL DATASET -- FIRST ANALYSIS")
    print("=" * 74)
    print(f"\n{n} resolved deals, 2022-2025, each verified by hand against its filing")
    print(f"  closed  {len(closed)}")
    print(f"  broken  {len(broke)}   ({len(broke)/n*100:.1f}%)")
    print(f"\nBase close rate: {len(closed)/n*100:.1f}%")
    print("  Merger arb's whole premise is that this number is high. It is.")
    print("  With 4 breaks, though, every rate below rests on very few events.")

    # ── spread distribution ───────────────────────────────────────────────
    sps = [d["spread"] for d in deals]
    print("\n" + "-" * 74)
    print("SPREAD AT ANNOUNCEMENT")
    print("-" * 74)
    print(f"  range   {min(sps):.2f}%  to  {max(sps):.2f}%")
    print(f"  median  {median(sps):.2f}%")
    no_ha = [s for s in sps if s < 200]
    print(f"  median excluding the 270% outlier (HA): {median(no_ha):.2f}%")
    print()
    print("  For contrast, the live feed runs roughly 1-20%. This set is far wider")
    print("  because it captures deals AT announcement, before spreads converge.")

    # ── the central question ──────────────────────────────────────────────
    print("\n" + "-" * 74)
    print("DOES A WIDER SPREAD MEAN A HIGHER CHANCE OF BREAKING?")
    print("-" * 74)
    print("  This is the assumption V3 is built on: spread carries the most weight")
    print("  of any factor, and wider is scored worse.\n")

    med = median(sps)
    below = [d for d in deals if d["spread"] < med]
    above = [d for d in deals if d["spread"] >= med]
    print(rate_line(f"below median ({med:.1f}%)", below))
    print(rate_line(f"at or above median", above))

    print()
    BUCKETS = [(-100, 10), (10, 20), (20, 30), (30, 45), (45, 1000)]
    for lo, hi in BUCKETS:
        sel = [d for d in deals if lo <= d["spread"] < hi]
        label = f"{lo:g}% to {hi:g}%" if hi < 1000 else f"{lo:g}%+"
        print(rate_line(label, sel))

    print()
    print("  Where the breaks actually sit:")
    for d in sorted(broke, key=lambda x: x["spread"]):
        print(f"    {d['ticker']:<6} {d['spread']:>7.2f}%   announced {d['announced']}")

    # ── V3's other factors ────────────────────────────────────────────────
    print("\n" + "-" * 74)
    print("OTHER V3 FACTORS")
    print("-" * 74)

    def has(d, *words):
        low = d["notes"].lower()
        return any(w in low for w in words)

    pe = [d for d in deals if has(d, "pe take-private", "private equity", "pe club",
                                  "capital partners", "capital management")]
    strategic = [d for d in deals if d not in pe]
    print("  Acquirer type (classified from the notes, so rough):")
    print(rate_line("    private equity", pe))
    print(rate_line("    strategic / other", strategic))

    squeeze = [d for d in deals if has(d, "controlling-shareholder", "squeeze-out",
                                       "already owned", "special committee")]
    print()
    print("  Controlling shareholder already in place:")
    print(rate_line("    yes", squeeze))
    print(rate_line("    no", [d for d in deals if d not in squeeze]))
    print("    A buyer who already controls the company faces no competing bid,")
    print("    but does face litigation over fairness.")

    # ── time to resolution ────────────────────────────────────────────────
    withdays = [d for d in deals if d["days"] is not None and 0 < d["days"] < 2000]
    if withdays:
        print("\n" + "-" * 74)
        print("TIME TO RESOLUTION")
        print("-" * 74)
        cd = [d["days"] for d in withdays if d["outcome"] == "CLOSED"]
        bd = [d["days"] for d in withdays if d["outcome"] == "BROKEN"]
        if cd:
            print(f"  closed  median {median(cd):.0f} days   (n={len(cd)})")
        if bd:
            print(f"  broken  median {median(bd):.0f} days   (n={len(bd)})")
        print()
        print("  Caveat: many outcome dates are known to be wrong -- detection")
        print("  sometimes caught a later filing rather than the real resolution.")
        print("  Treat these as indicative only.")

    # ── deal size ─────────────────────────────────────────────────────────
    print("\n" + "-" * 74)
    print("DEAL PRICE (a rough proxy for company size)")
    print("-" * 74)
    small = [d for d in deals if d["deal_price"] is not None and d["deal_price"] < 10]
    mid = [d for d in deals if d["deal_price"] is not None and 10 <= d["deal_price"] < 50]
    large = [d for d in deals if d["deal_price"] is not None and d["deal_price"] >= 50]
    print(rate_line("under $10/share", small))
    print(rate_line("$10 to $50/share", mid))
    print(rate_line("$50+/share", large))
    print("  Share price is a poor proxy for market cap. Directional at best.")

    # ── what this does and does not support ───────────────────────────────
    print("\n" + "=" * 74)
    print("WHAT THIS SUPPORTS")
    print("=" * 74)
    b_rate = len(broke) / n * 100
    below_r = sum(1 for d in below if d["outcome"] == "BROKEN") / max(len(below), 1) * 100
    above_r = sum(1 for d in above if d["outcome"] == "BROKEN") / max(len(above), 1) * 100
    print(f"""
  1. The base close rate is {len(closed)/n*100:.0f}%. That is the number any
     probability estimate should start from, and it is now measured rather
     than assumed.

  2. Break rate below the median spread: {below_r:.1f}%. At or above: {above_r:.1f}%.
     The direction matches what V3 assumes. The magnitude rests on
     {len(broke)} broken deals, so it is a hint, not a finding.

  3. Nothing here justifies recalibrating V3's weights. Fitting six factors
     to {n} observations with {len(broke)} failures would fit noise. What the data
     can honestly do right now is set the base rate and confirm the sign
     of the spread relationship.

  4. The set is cash-only by construction. All-stock, mixed, election and
     CVR deals were excluded because Meridian cannot price them. Any claim
     from this data is a claim about all-cash US mergers, nothing wider.
""")


if __name__ == "__main__":
    main()