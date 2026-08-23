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
                             third_party_fee_names,
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

# ── the four shapes the WBD fixture did not cover ────────────────────────────
# Every string below is lifted verbatim from the EX-2.1 named beside it, curly
# quotes and internal spacing intact. The spacing is the point: stripping HTML
# leaves (the " Parent Termination Fee ") with spaces inside the quotes, and a
# pattern anchored tight to the quote character reads right past it. WBD happens
# to print (the "Regulatory Termination Fee") without the spaces, so a fixture
# written from WBD alone confirmed the pattern instead of testing it, and five
# live agreements came back blank behind a passing suite.
print("\nSHAPES FROM FIVE MORE AGREEMENTS")
print("-" * 78)

# SLAB — accession 0001193125-26-036712, d62897dex21.htm
# "a fee equal to $X", amount before a spaced-quote label.
SLAB = (
    "being incapable of being satisfied by the Termination Date, then Parent shall "
    "pay to the Company a fee equal to $499,000,000 (the \u201c Parent Termination "
    "Fee \u201d) by wire transfer of immediately available funds to an account or "
    "accounts designated in writing by Parent. "
    "\u201c Company Termination Fee \u201d means an amount equal to $259,000,000."
)
fees = extract_termination_fees(SLAB, deal_value=7_500_000_000)
check("SLAB: 'a fee equal to $X' before a spaced-quote label",
      fees.get('reverse_fee'), 499_000_000)
check("SLAB: company fee from the definition shape",
      fees.get('company_fee'), 259_000_000)
check("SLAB: asymmetry", fees.get('asymmetry'), 1.93)

# GBTG — accession 0001140361-26-023154, ef20072315_ex2-1.htm
# "a termination fee of $X", the word 'termination' sitting inside the lead-in.
GBTG = (
    "or Section 8.1(i) ( Parent Failure to Close ), then Parent shall promptly (and "
    "in any event within three (3) Business Days after such termination) pay the "
    "Company a termination fee of $270,000,000 (the \u201c Parent Termination Fee "
    "\u201d) by wire transfer of immediately available funds to an account or "
    "accounts designated in writing by the Company."
)
fees = extract_termination_fees(GBTG, deal_value=None)
check("GBTG: 'a termination fee of $X' before a spaced-quote label",
      fees.get('reverse_fee'), 270_000_000)

# APGE — accession 0001140361-26-027877, ef20076505_ex2-1.htm
# The exact WBD shape, 'a fee of $X in cash (the ...)', but spaced quotes. This
# is the case that proves the fixture was the problem and not the phrasing.
APGE = (
    "( Regulatory Approvals ) to be satisfied, then Parent shall pay, or cause to be "
    "paid, by wire transfer of immediately available funds to the Company a fee of "
    "$381,273,716 in cash (the \u201c Reverse Termination Fee \u201d) no later than "
    "two (2) business days after the date of the termination of this Agreement."
)
fees = extract_termination_fees(APGE, deal_value=None)
check("APGE: WBD's own shape with spaces inside the quotes",
      fees.get('reverse_fee'), 381_273_716)

# AES — accession 0001206774-26-001385, d100078dex21.htm
# A two-tier acquirer fee under a compound name, stated as a definition. The
# bare "Parent Termination Fee" here has no amount of its own -- it is defined
# as the other two -- so a label-near-an-amount scan must not win over the
# definition that does carry a figure.
AES = (
    "\u201c Company Termination Fee \u201d means an amount in cash equal to "
    "$320,651,487. \u201c Parent General Termination Fee \u201d means an amount in "
    "cash equal to $587,861,060. \u201c Parent Regulatory Termination Fee \u201d "
    "means an amount in cash equal to $100,000,000. \u201c Parent Termination Fee "
    "\u201d means the Parent General Termination Fee and the Parent Regulatory "
    "Termination Fee."
)
fees = extract_termination_fees(AES, deal_value=None)
check("AES: compound name, definition shape, general fee is the headline",
      fees.get('reverse_fee'), 587_861_060)
check("AES: company fee read from the same shape",
      fees.get('company_fee'), 320_651_487)
check("AES: 'General' is not mistaken for an outside party",
      'General' in (fees.get('third_party_fees_ignored') or []), False,
      "Netflix is a third party; Parent General is this deal's own fee")

# ALOT — accession 0001193125-26-041199, d100857dex21.htm
# THE CROSS-REFERENCE SHAPE. ALOT's agreement never states the acquirer's fee
# as a figure: it says the Reverse Termination Fee means an amount equal to the
# Termination Fee, and defines THAT term in an alphabetical list 6,451
# characters later. The fixture below is the real span between the two, entire
# and unedited -- every intervening definition the filing carries. The distance
# is the test. A trimmed excerpt would let a proximity scan reach across and
# appear to work, which is how the WBD fixture flattered the pattern that came
# before it; at full length nothing but a real lookup can join the halves.
ALOT = (
    "\u201c Reverse Termination Fee \u201d means an amount equal to the "
    "Termination Fee. \u201c Rhode Island Secretary \u201d has the meaning "
    "set forth in Section 1.03. \u201c RIBCA \u201d has the meaning set "
    "forth in the Recitals. \u201c Sanctioned Country \u201d means any "
    "country or region, or government of any country or region, that is or "
    "was during the applicable period the subject or target of a "
    "comprehensive sanctions or export controls under Trade Compliance Laws"
    " (including Afghanistan, Belarus, Cuba, Iran, Myanmar, North Korea, "
    "Russia, Syria, Venezuela, and following regions of Ukraine: Crimea, "
    "the so-called Donetsk People\u2019s Republic, the so-called Luhansk "
    "People\u2019s Republic, Kherson, and Zaporizhzhia). \u201c Sanctioned "
    "Person \u201d means any Person that is the subject or target of "
    "restrictions under Trade Compliance Laws, including: (i) any Person "
    "listed on any U.S. or non-U.S. sanctions- or export-related restricted"
    " party list, including the List of Specially Designated Nationals and "
    "Blocked Persons and the Entity List; (ii) any Person located, "
    "operating, or ordinarily resident in a Sanctioned Country (iii) any "
    "Person that is, in the aggregate, 50% or greater owned, directly or "
    "indirectly, or otherwise controlled by a Person or Persons described "
    "in clauses (i) or (ii); or (iv) any national of a Sanctioned Country "
    "with whom U.S. Persons are prohibited from dealing. \u201c Sarbanes-"
    "Oxley Act \u201d has the meaning set forth in Section 3.04(a). 77 "
    "\u201c SEC \u201d has the meaning set forth in Section 3.03(c). \u201c"
    " Securities Act \u201d has the meaning set forth in Section 3.04(a). "
    "\u201c Subsidiary \u201d of a Person means any other Person of which "
    "at least a majority of the securities or ownership interests having by"
    " their terms ordinary voting power to elect a majority of the board of"
    " directors or other persons performing similar functions is directly "
    "or indirectly owned or controlled by such Person and/or by one or more"
    " of its Subsidiaries. \u201c Superior Proposal \u201d means a bona "
    "fide written Takeover Proposal that did not result from a breach in "
    "any material respect of Section 5.04 (except that, for purposes of "
    "this definition, each reference in the definition of \u201cTakeover "
    "Proposal\u201d to \u201c15% or more\u201d shall be \u201cmore than "
    "50%\u201d) that the Company Board determines in good faith (after "
    "consultation with its financial advisor and outside legal counsel) is "
    "(a) reasonably likely to be consummated in accordance with its terms, "
    "and (b) if consummated, more favorable to the holders of Company "
    "Common Stock from a financial point of view than the transactions "
    "contemplated by this Agreement; in each case, after taking into "
    "account: (i) all financial considerations; (ii) the identity of the "
    "third party making such Takeover Proposal; (iii) the anticipated "
    "timing, conditions (including any financing condition or the "
    "reliability of any debt or equity funding commitments) and prospects "
    "and likelihood for completion of such Takeover Proposal; (iv) the "
    "other terms and conditions of such Takeover Proposal and the "
    "implications thereof on the Company, including relevant legal, "
    "regulatory, and other aspects of such Takeover Proposal deemed "
    "relevant by the Company Board (including any conditions relating to "
    "financing, stockholder approval, regulatory approvals, or other events"
    " or circumstances beyond the control of the party invoking the "
    "condition); and (v) any revisions to the terms of this Agreement and "
    "the Merger proposed by Parent during the Superior Proposal Notice "
    "Period set forth in Section 5.04(d). \u201c Superior Proposal Notice "
    "Period \u201d has the meaning set forth in Section 5.04(d). \u201c "
    "Surviving Corporation \u201d has the meaning set forth in Section "
    "1.01. \u201c Takeover Proposal \u201d means an inquiry, proposal, or "
    "offer from, or indication of interest in making a proposal or offer "
    "by, any Person or group (other than Parent and its Subsidiaries, "
    "including Merger Sub), relating to any transaction or series of "
    "related transactions (other than the transactions contemplated by this"
    " Agreement), involving any: (a) direct or indirect acquisition of "
    "assets of the Company or its Subsidiaries (including any voting equity"
    " interests of Subsidiaries, but excluding sales of assets in the "
    "ordinary course of business) equal to 15% or more of the fair market "
    "value of the Company\u2019s and its Subsidiaries\u2019 consolidated "
    "assets or to which 15% or more of the Company\u2019s and its "
    "Subsidiaries\u2019 net revenues or net income on a consolidated basis "
    "are attributable; (b) direct or indirect acquisition of 15% or more of"
    " the voting equity interests of the Company or any of its Subsidiaries"
    " whose business constitutes 15% or more of the consolidated net "
    "revenues, net income, or assets of the Company and its Subsidiaries, "
    "taken as a whole; (c) tender offer or exchange offer that if "
    "consummated 78 would result in any Person or group (as defined in "
    "Section 13(d) of the Exchange Act) beneficially owning (within the "
    "meaning of Section 13(d) of the Exchange Act) 15% or more of the "
    "voting power of the Company; (d) merger, consolidation, other business"
    " combination, or similar transaction involving the Company or any of "
    "its Subsidiaries, pursuant to which such Person or group (as defined "
    "in Section 13(d) of the Exchange Act) would own 15% or more of the "
    "consolidated net revenues, net income, or assets of the Company, and "
    "its Subsidiaries, taken as a whole; (e) liquidation, dissolution (or "
    "the adoption of a plan of liquidation or dissolution), or "
    "recapitalization or other significant corporate reorganization of the "
    "Company or one or more of its Subsidiaries which, individually or in "
    "the aggregate, generate or constitute 15% or more of the consolidated "
    "net revenues, net income, or assets of the Company and its "
    "Subsidiaries, taken as a whole; or (f) any combination of the "
    "foregoing. \u201c Tax Returns \u201d shall mean any return, report, "
    "information, filing, document or similar statement filed or required "
    "to be filed with any Governmental Entity with respect to any Tax "
    "(including any attached schedules). \u201c Taxes \u201d means any U.S."
    " federal, state, local or non-U.S. income, gross receipts, property, "
    "sales, use, license, excise, franchise, employment, payroll, premium, "
    "withholding, alternative or added minimum, ad valorem, escheat or "
    "unclaimed property, transfer or excise tax, social security or tax "
    "relating to compensation or benefits provided to employees, or any "
    "other tax, governmental fee or other like assessment or charge in the "
    "nature of a tax, together with any interest or penalty or addition "
    "thereto, whether disputed or not, in each case imposed by any "
    "Governmental Entity. \u201c Termination Fee \u201d means $9,648,000."
)


fees = extract_termination_fees(ALOT, deal_value=None)
check("ALOT: one hop across 6,451 characters to the referenced definition",
      fees.get('reverse_fee'), 9_648_000,
      "means an amount equal to the Termination Fee -> means $9,648,000")
check("ALOT: the resolved reading records the chain it followed",
      fees.get('reverse_fee_text') is not None, True)

# A second hop is refused. No agreement in the set actually chains twice, so
# the chain itself is constructed -- but the spacing is not: the three
# definitions are separated by real intervening entries from ALOT's own
# definitions list, at the distance such entries really sit. Packed together
# they would be bridged by the proximity tier and the case would pass without
# testing the resolver at all.
TWO_HOP = (
    "\u201c Reverse Termination Fee \u201d means an amount equal to the "
    "Walk Fee. \u201c Rhode Island Secretary \u201d has the meaning set "
    "forth in Section 1.03. \u201c RIBCA \u201d has the meaning set forth "
    "in the Recitals. \u201c Sanctioned Country \u201d means any country or"
    " region, or government of any country or region, that is or was during"
    " the applicable period the subject or target of a comprehensive "
    "sanctions or export controls under Trade Compliance Laws (including "
    "Afghanistan, Belarus, Cuba, Iran, Myanmar, North Korea, Russia, Syria,"
    " Venezuela, and follo \u201c Walk Fee \u201d means an amount equal to "
    "the Termination Fee. nd the Entity List; (ii) any Person located, "
    "operating, or ordinarily resident in a Sanctioned Country (iii) any "
    "Person that is, in the aggregate, 50% or greater owned, directly or "
    "indirectly, or otherwise controlled by a Person or Persons described "
    "in clauses (i) or (ii); or (iv) any national of a Sanctioned Country "
    "with whom U.S. Persons are prohibited from dealing. \u201c Sarbanes-"
    "Oxley Act \u201d has the meaning set forth in Section 3.04(a). 77 "
    "\u201c SEC \u201d has the m \u201c Termination Fee \u201d means "
    "$9,648,000."
)
fees = extract_termination_fees(TWO_HOP, deal_value=None)
check("a two-hop chain returns nothing rather than resolving",
      fees.get('reverse_fee'), None,
      "one hop only -- two levels of indirection is likelier a misparse")

print("\n" + "=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")

# ── the index of defined terms is not prose ──────────────────────────────────
# Stripping the HTML off an agreement's table of defined terms collapses its
# columns into one line, so one row's section reference lands against the next
# row's label. Read literally it asserts a termination fee owed to a party
# called Recitals. The row below is APGE's, verbatim.
print("\nINDEX ROWS vs REAL THIRD PARTIES")
print("-" * 78)

APGE_INDEX_ROW = (
    "ed Company Voting Stockholder Approval 3.6 Sanctioned Jurisdiction "
    "3.17(b) Sanctioned Person 3.17(b) Share 2.1(a)(i) Superior Proposal "
    "Notice 5.3(d)(i)(A) Supporting Stockholders Recitals Surviving "
    "Corporation Recitals Termination Fee 7.3(a)(iii)(B) Transactions "
    "Recitals Voting Agreement Recitals Written Consent 3.6 A-15 E"
)
check("an index row does not invent a third-party fee owner",
      third_party_fee_names(APGE_INDEX_ROW), set(),
      "no verb anywhere in it, and section references either side")

# The guard has to leave the real case alone. Netflix survives because its fee
# is stated in a sentence, section reference and all.
check("the Netflix fee is still read out of prose",
      third_party_fee_names(WBD), {"Netflix"},
      "Buyer ... shall pay or cause to be paid $2,800,000,000")

print("\n" + "=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")

# ── GBCS: the acquirer under a third name, and two fees one sentence apart ────
# GBCS calls its acquirer the Purchaser. Unlisted, the word read as an outside
# party -- the same failure "General" caused on AES -- and the third-party guard
# then suppressed BOTH of this deal's fees, including the company's own.
#
# The excerpt is also why the amount-to-parenthetical gap forbids a period. Both
# fees here are $400,000 and they sit one sentence apart, so a loose window let
# the acquirer's pattern start at the COMPANY's figure and finish inside the
# Purchaser parenthetical: the right number under the wrong span, which then
# swallowed the company fee as an overlap. Keep the two sentences together.
print("\nGBCS - THE ACQUIRER UNDER A THIRD NAME")
print("-" * 78)

GBCS = (
    "In no event shall payment of more than one Termination Fee be made by "
    "the Company under this Section 9.03(b) . \u201c Termination Fee \u201d"
    " means $400,000. (c) Purchaser shall pay to the Company by wire "
    "transfer of immediately available funds an amount equal to $400,000 "
    "(such amount, the \u201c Purchaser Termination Fee \u201d) within five"
    " (5) Business Days after termination if this Agreement is terminated "
    "by the Company pursuant to Section 9.01(i) or if this Agreement is"
)
fees = extract_termination_fees(GBCS, deal_value=None)
check("GBCS: 'Purchaser' is the acquirer, not a third party",
      third_party_fee_names(GBCS), set())
check("GBCS: acquirer fee, named in a parenthetical with a lead-in",
      fees.get('reverse_fee'), 400_000,
      "an amount equal to $400,000 (such amount, the Purchaser Termination Fee)")
check("GBCS: the company fee one sentence earlier survives",
      fees.get('company_fee'), 400_000,
      "the acquirer's span must not reach back across the period")
check("GBCS: equal fees both ways", fees.get('asymmetry'), 1.0)

print("\n" + "=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")
