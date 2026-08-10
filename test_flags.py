"""
Test the flag detector against filing language from deals already verified by
hand, so every expected answer is known rather than assumed.

Text is quoted from the actual filings read during the dataset build.

Two failure modes, and they are not equal:
  MISSED   a real structure goes unflagged. The product stays where it is.
  FALSE    a clean deal gets flagged. A trader is told a simple deal is
           complicated, and stops trusting the flags. This is the worse one.
"""
import sys
sys.path.insert(0, '/home/claude/flags')
from deal_flags import detect_flags, flags_summary, price_is_complete
from deal_flags import (FLAG_CVR, FLAG_ELECTION, FLAG_ADJUSTMENT,
                        FLAG_GO_SHOP, FLAG_CONTROLLING, FLAG_REPRICED)

CASES = [
    # ── must flag ────────────────────────────────────────────────────────────
    ("STCN — Steel Partners, cash plus CVR",
     "The holders of Steel Connect's outstanding shares of common stock will receive "
     "US $1.35 per share in cash and one contingent value right (\"CVR\") to receive "
     "their pro rata share of net proceeds, to the extent such net proceeds exceed "
     "$80 million, if Steel Connect's ModusLink subsidiary is sold during the "
     "two-year period following completion of the merger.",
     {FLAG_CVR}),

    ("FNA — Zimmer Biomet, cash plus CVR",
     "each outstanding share of the Company's common stock will automatically be "
     "converted into the right to receive (i) $13.00 in cash, without interest and "
     "(ii) one contractual contingent value right pursuant to the CVR Agreement.",
     {FLAG_CVR}),

    ("ENFN — Clearwater, election structure",
     "each share issued and outstanding immediately prior to the Effective Time will "
     "be converted into the right to receive, at the election of the holder, the Per "
     "Share Mixed Consideration, the Per Share Stock Consideration or the Per Share "
     "Cash Consideration.",
     {FLAG_ELECTION}),

    ("Emclaire — election with proration",
     "holders may elect to receive $40.00 in cash or 2.15 shares of FMNB common "
     "stock per share, subject to proration such that the aggregate consideration "
     "is 70% stock and 30% cash.",
     {FLAG_ELECTION}),

    ("IVAC — Seagate, special dividend at closing",
     "In addition, the Board declared a one-time special dividend of $0.052 per share "
     "payable to stockholders of record immediately prior to the closing of the merger.",
     {FLAG_ADJUSTMENT}),

    ("VCSA — Casago, subject to adjustment",
     "Under the terms of the merger agreement, Vacasa stockholders receive $5.02 per "
     "share in cash upon completion of the proposed transaction, subject to adjustment "
     "as set forth in the merger agreement.",
     {FLAG_ADJUSTMENT}),

    ("PDCO — Patterson, go-shop",
     "The merger agreement includes a 40-day go-shop period during which Patterson and "
     "its representatives had the right to actively solicit and consider alternative "
     "acquisition proposals from third parties.",
     {FLAG_GO_SHOP}),

    ("AZPN — Emerson, controlling holder",
     "Emerson will acquire all outstanding shares of common stock of AspenTech not "
     "already owned by Emerson for $265.00 per share pursuant to an all-cash tender "
     "offer. Emerson currently owns approximately 57% of AspenTech's outstanding shares.",
     {FLAG_CONTROLLING}),

    ("RVNC — Crown Labs, repriced upward",
     "Under the terms of the Second Amendment, Revance's stockholders will receive "
     "$3.65 per share in cash, representing $0.55 or 17% per share more than the prior "
     "offer price.",
     {FLAG_REPRICED}),

    ("STCN full — CVR and controlling holder together",
     "Steel Partners will acquire the remaining common stock of Steel Connect issued "
     "and outstanding immediately prior to the effective time of the merger. Holders "
     "will receive US $1.35 per share in cash and one contingent value right.",
     {FLAG_CVR, FLAG_CONTROLLING}),

    # ── must NOT flag ────────────────────────────────────────────────────────
    ("IRBT — Amazon, plain cash",
     "Amazon will acquire iRobot for $61 per share in an all-cash transaction valued "
     "at approximately $1.7 billion, including iRobot's net debt. Completion of the "
     "transaction is subject to customary closing conditions, including approval by "
     "iRobot's shareholders and regulatory approvals.",
     set()),

    ("JNPR — HPE, plain cash",
     "HPE and Juniper Networks today announced that the companies have entered a "
     "definitive agreement under which HPE will acquire Juniper in an all-cash "
     "transaction for $40.00 per share, representing an equity value of approximately "
     "$14 billion.",
     set()),

    ("AMED — UnitedHealth, plain cash",
     "each share of Amedisys common stock issued and outstanding will be converted "
     "into the right to receive $101 per share in cash, without interest, less any "
     "applicable withholding taxes.",
     set()),

    ("HAYN — Acerinox, plain cash with a premium quote",
     "North American Stainless will acquire all the outstanding shares of Haynes for "
     "$61.00 per share in cash, which represents a premium of approximately 22% to "
     "Haynes' six-month volume-weighted average share price.",
     set()),

    ("boilerplate that must not trip ADJUSTMENT",
     "The Merger Agreement contains customary representations, warranties and "
     "covenants. Payments are subject to applicable withholding taxes and any "
     "adjustment required by law.",
     set()),
]

print("deal structure flags — tested against real filing language")
print("=" * 84)
ok = True
missed = false_pos = 0

for label, text, expected in CASES:
    flags = detect_flags(text)
    got = {f["flag"] for f in flags}
    good = got == expected
    ok &= good
    if not good:
        missed += len(expected - got)
        false_pos += len(got - expected)
    status = "PASS" if good else "FAIL"
    print(f"  {status}  {label}")
    print(f"        flags: {flags_summary(flags) or '(none)':<40} price complete: {price_is_complete(flags)}")
    if not good:
        if expected - got:
            print(f"        MISSED:  {sorted(expected - got)}")
        if got - expected:
            print(f"        FALSE:   {sorted(got - expected)}")
            for f in flags:
                if f["flag"] in (got - expected):
                    print(f"          triggered on '{f['trigger']}' -> ...{f['context'][:90]}...")

print("=" * 84)
print(f"missed flags: {missed}   false positives: {false_pos}")
print()
if ok:
    print("ALL PASS")
else:
    print("A false positive matters more than a miss: it tells a trader a clean")
    print("deal is complicated, and after that the flags stop being believed.")