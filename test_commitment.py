"""
Commitment terms, tested against merger agreement language.

The case that matters most is the qualified hell-or-high-water clause: an
agreement that grants a strong efforts covenant and then caps it two paragraphs
later. Reading that as STRONG is the expensive error, because it tells someone
a buyer is bound to fight when the buyer has a documented exit.
"""
import sys
sys.path.insert(0, '/home/claude/commit')
from deal_commitment import (check_antitrust_efforts, check_financing,
                             check_specific_performance, extract_termination_fees,
                             assess_commitment, STRONG, WEAK, UNKNOWN)

ok = True
def check(label, got, want, detail=""):
    global ok
    good = got == want
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  {label}")
    print(f"        got {got}, wanted {want}" + (f" | {detail}" if detail else ""))


print("ANTITRUST EFFORTS")
print("-" * 78)

v, why, q = check_antitrust_efforts(
    "Parent shall take any and all actions necessary to obtain all required "
    "regulatory approvals and clearance under the HSR Act, including proffering "
    "and consenting to any divestiture of assets.")
check("plain hell-or-high-water language", v, STRONG, why)

v, why, q = check_antitrust_efforts(
    "Parent shall use its reasonable best efforts to obtain clearance under the "
    "HSR Act as promptly as practicable.")
check("reasonable best efforts", v, WEAK, why)

# THE IMPORTANT ONE
v, why, q = check_antitrust_efforts(
    "Parent shall take any and all actions necessary to obtain clearance under "
    "the HSR Act; provided, however, that in no event shall Parent be required "
    "to divest, hold separate or otherwise dispose of any assets that would "
    "constitute a Burdensome Condition.")
check("hell-or-high-water CAPPED by a burdensome condition", v, WEAK, why)

v, why, q = check_antitrust_efforts(
    "The parties shall cooperate in connection with the transactions "
    "contemplated hereby.")
check("no efforts language at all", v, UNKNOWN, why)


print("\nFINANCING")
print("-" * 78)

v, why, q = check_financing(
    "The obligations of Parent and Merger Sub to consummate the Merger are not "
    "subject to any financing condition. Parent has obtained a Debt Commitment "
    "Letter from the lenders named therein.")
check("no financing condition, with a commitment letter", v, STRONG, why)

v, why, q = check_financing(
    "Closing shall be subject to the receipt of the financing contemplated by "
    "the Commitment Letter.")
check("closing conditioned on receipt of financing", v, WEAK, why)

v, why, q = check_financing(
    "Parent has delivered an Equity Commitment Letter to the Company.")
check("commitment letter but no statement either way", v, UNKNOWN, why)


print("\nSPECIFIC PERFORMANCE")
print("-" * 78)

v, why, q = check_specific_performance(
    "The Company shall be entitled to seek specific performance to enforce "
    "Parent's obligation to cause the Closing to occur.")
check("target can compel closing", v, STRONG, why)

v, why, q = check_specific_performance(
    "The Company shall be entitled to specific performance; provided that upon "
    "termination the payment of the Parent Termination Fee shall be the sole "
    "and exclusive remedy of the Company for monetary damages.")
check("granted then limited to the fee", v, WEAK, why)

v, why, q = check_specific_performance("The parties agree to the foregoing.")
check("no language found", v, UNKNOWN, why)


print("\nTERMINATION FEES")
print("-" * 78)

fees = extract_termination_fees(
    "If this Agreement is terminated under Section 8.1(c), Parent shall pay to "
    "the Company a Reverse Termination Fee of $500 million. If terminated under "
    "Section 8.1(d), the Company shall pay Parent a Company Termination Fee of "
    "$150 million.", deal_value=10_000_000_000)
print(f"        parsed: {fees}")
check("reverse fee parsed", fees.get('reverse_fee'), 500_000_000)
check("company fee parsed", fees.get('company_fee'), 150_000_000)
check("asymmetry computed", fees.get('asymmetry'), 3.33)
check("fee as pct of deal value", fees.get('reverse_fee_pct'), 5.0)


print("\nFULL ASSESSMENT")
print("-" * 78)

strong_deal = (
    "Parent shall take any and all actions necessary to obtain clearance under "
    "the HSR Act, including proffering any divestiture required. The obligations "
    "of Parent to consummate the Merger are not subject to any financing "
    "condition, and Parent has obtained a Debt Commitment Letter. The Company "
    "shall be entitled to seek specific performance to enforce Parent's "
    "obligation to cause the Closing to occur. Parent shall pay a Reverse "
    "Termination Fee of $500 million upon a termination described in Section 8.1(c)."
)
a = assess_commitment(strong_deal, deal_value=10_000_000_000)
print(f"        {a['summary']}")
for t in a['terms']:
    print(f"          {t['term']:<26} {t['verdict']:<8} {t['meaning'][:60]}")
check("strongly committed deal reads 4 of 4", (a['strong_count'], a['resolved_count']), (4, 4))

weak_deal = (
    "Parent shall use commercially reasonable efforts to obtain regulatory "
    "clearance. Closing is subject to the receipt of the financing contemplated "
    "by the Commitment Letter. Payment of the Parent Termination Fee of $40 "
    "million shall be the sole and exclusive remedy of the Company for monetary "
    "damages."
)
a = assess_commitment(weak_deal, deal_value=5_000_000_000)
print()
print(f"        {a['summary']}")
for t in a['terms']:
    print(f"          {t['term']:<26} {t['verdict']:<8} {t['meaning'][:60]}")
check("weakly committed deal reads 0 strong", a['strong_count'], 0)

print("\n" + "=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")


# ── the WBD / Paramount cases ────────────────────────────────────────────────
# Verbatim shapes from that agreement, which broke three assumptions at once.
# Amounts read from EX-2.1 of accession 0001437107-26-000018 (exhibit21.htm):
# a $7,000,000,000 Regulatory Termination Fee, a $3,000,000,000 Company
# Termination Fee, and the $2,800,000,000 paid to Netflix.
print("\nWBD / PARAMOUNT — the cases that broke the first version")
print("-" * 78)

WBD = (
    "Section 6.17 Netflix Termination Fee. Concurrently with the execution of this "
    "Agreement and with the termination of the Netflix Merger Agreement, Buyer, on "
    "behalf of the Company, shall pay or cause to be paid $2,800,000,000 (the "
    "\u201cNetflix Termination Fee\u201d) to Netflix by wire transfer of immediately "
    "available funds in order for the Company to terminate the Netflix Merger "
    "Agreement pursuant to Section 8.1(c)(ii). "
    "Section 8.3 Termination Fees. (a) Company Termination Fee. If this Agreement is "
    "terminated by the Company pursuant to Section 8.1(c)(ii), the Company shall pay "
    "to an account designated in writing by Buyer, a fee of $3,000,000,000 in cash "
    "(the \u201cCompany Termination Fee\u201d), such payment to be made concurrently "
    "with such termination. "
    "(b) Regulatory Termination Fee. If this Agreement is terminated by the Company or "
    "Buyer pursuant to Section 8.1(b)(i), Buyer shall pay to the Company a fee of "
    "$7,000,000,000 in cash (the \u201cRegulatory Termination Fee\u201d)."
)

fees = extract_termination_fees(WBD, deal_value=77_720_000_000)
print(f"        parsed: { {k: v for k, v in fees.items() if not k.endswith('_text')} }")
check("acquirer fee found under the name 'Regulatory Termination Fee'",
      fees.get('reverse_fee'), 7_000_000_000)
check("target fee found with the amount BEFORE the label",
      fees.get('company_fee'), 3_000_000_000)
check("the $2.8bn Netflix fee is excluded as a third-party fee",
      'Netflix' in (fees.get('third_party_fees_ignored') or []), True,
      "a payment to a company outside this deal")
check("neither fee is the Netflix amount",
      2_800_000_000 not in (fees.get('reverse_fee'), fees.get('company_fee')), True)
check("asymmetry computed from the right pair", fees.get('asymmetry'), 2.33)

print("\n" + "=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")