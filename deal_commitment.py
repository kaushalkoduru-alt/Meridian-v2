"""
COMMITMENT TERMS — how hard is this buyer contractually bound to close?

The 39-deal dataset found that three of four broken deals died on regulatory
grounds, not financing. The merger agreement says, in advance, who is obligated
to fight a regulator and who can walk. None of it appears on any screen,
because reading a 300,000-character agreement is expensive and almost nobody
does it.

FOUR TERMS

  Reverse termination fee   What the acquirer pays to walk away. The single
                            best commitment signal that exists. Compared
                            against the target's break fee it gives an
                            asymmetry: who wants this more.

  Antitrust efforts         "Hell or high water" obliges the acquirer to divest
                            whatever regulators demand. "Reasonable best
                            efforts" lets them walk when it gets expensive.
                            Close to determinative on a contested deal.

  Financing condition       Its ABSENCE is the good outcome. "Not subject to a
                            financing condition" means the buyer cannot blame
                            credit markets.

  Specific performance      Can the target force the acquirer to close, or only
                            sue for damages afterward? A deal where damages are
                            the sole remedy is a deal the buyer can buy its way
                            out of.

WHERE THESE LIVE

  In the merger agreement, filed as EX-2.1, not in the press release. That is a
  different document from the one deal_flags.py reads and it runs hundreds of
  thousands of characters. The caller must fetch it separately.

CONSERVATIVE BY DESIGN

  Same rule as the structure flags: a wrong reading is worse than no reading.
  Telling someone a deal has hell-or-high-water protection when it does not is
  the kind of error that costs money. Ambiguous language returns UNKNOWN.
"""

import re

# ── verdict values ────────────────────────────────────────────────────────────
STRONG   = "STRONG"    # the term favours the deal closing
WEAK     = "WEAK"      # the term gives the acquirer room to walk
UNKNOWN  = "UNKNOWN"   # language not found, or too ambiguous to call

# ── antitrust efforts ─────────────────────────────────────────────────────────
# Ordered strongest to weakest. The first match wins, so an agreement that
# contains both a hell-or-high-water clause and a burdensome-condition carve-out
# is caught by the carve-out check below rather than by ordering alone.
HOHW_PATTERNS = [
    (r'hell\s+or\s+high\s+water', "hell or high water"),
    (r'take\s+any\s+and\s+all\s+actions?\s+necessary[^\n]{0,200}?(?:obtain|clearance|approval)',
     "any and all actions necessary to obtain clearance"),
    (r'shall\s+(?:be\s+required\s+to\s+)?(?:divest|sell|dispose\s+of|hold\s+separate)[^\n]{0,200}?'
     r'(?:as\s+may\s+be\s+required|necessary\s+to\s+obtain)',
     "obliged to divest as required"),
    (r'whatever\s+actions?\s+(?:are|may\s+be)\s+necessary', "whatever actions necessary"),
]

# A carve-out limits an otherwise strong efforts covenant. Their presence turns
# a hell-or-high-water reading into a qualified one.
CARVEOUT_PATTERNS = [
    (r'[Bb]urdensome\s+[Cc]ondition', "Burdensome Condition carve-out"),
    (r'shall\s+not\s+be\s+required\s+to[^\n]{0,160}?(?:divest|sell|dispose|hold\s+separate)',
     "not required to divest"),
    (r'[Mm]aterial\s+[Aa]dverse\s+[Ee]ffect[^\n]{0,120}?(?:divest|remedy|condition)',
     "divestiture capped at a material adverse effect"),
    (r'in\s+no\s+event\s+shall[^\n]{0,160}?(?:divest|dispose|hold\s+separate)',
     "explicit ceiling on divestiture"),
]

WEAK_EFFORTS_PATTERNS = [
    (r'commercially\s+reasonable\s+efforts', "commercially reasonable efforts"),
    (r'reasonable\s+best\s+efforts', "reasonable best efforts"),
]

# ── financing ─────────────────────────────────────────────────────────────────
NO_FINANCING_COND = [
    (r'not\s+(?:subject\s+to|conditioned\s+(?:up)?on)\s+(?:any\s+|the\s+receipt\s+of\s+)?'
     r'(?:financing|funding)', "not subject to a financing condition"),
    (r'no\s+financing\s+condition', "no financing condition"),
    (r'obligations?[^\n]{0,120}?(?:are|is)\s+not\s+(?:subject\s+to|contingent)[^\n]{0,60}?financing',
     "obligations not contingent on financing"),
]
HAS_FINANCING_COND = [
    (r'subject\s+to[^\n]{0,80}?(?:the\s+)?(?:receipt|availability)\s+of\s+(?:the\s+)?financing',
     "subject to receipt of financing"),
    (r'[Ff]inancing\s+[Cc]ondition(?!\s+(?:has|shall)\s+been\s+(?:satisfied|waived))',
     "a financing condition exists"),
]
COMMITMENT_LETTERS = [
    (r'[Dd]ebt\s+[Cc]ommitment\s+[Ll]etter', "debt commitment letter"),
    (r'[Ee]quity\s+[Cc]ommitment\s+[Ll]etter', "equity commitment letter"),
    (r'committed\s+(?:debt\s+)?financing', "committed financing"),
]

# ── specific performance ──────────────────────────────────────────────────────
SPECIFIC_PERF_YES = [
    (r'entitled\s+to[^\n]{0,120}?specific\s+performance', "entitled to specific performance"),
    (r'specific\s+performance[^\n]{0,140}?(?:to\s+)?(?:enforce|cause\s+the\s+[Cc]losing)',
     "specific performance to compel closing"),
    (r'right\s+to\s+seek\s+specific\s+performance', "right to seek specific performance"),
]
SPECIFIC_PERF_LIMITED = [
    (r'sole\s+and\s+exclusive\s+remedy[^\n]{0,200}?(?:[Tt]ermination\s+[Ff]ee|monetary\s+damages)',
     "termination fee is the sole and exclusive remedy"),
    (r'shall\s+not\s+be\s+entitled\s+to[^\n]{0,120}?specific\s+performance',
     "not entitled to specific performance"),
    (r'monetary\s+damages[^\n]{0,120}?sole\s+remedy', "monetary damages are the sole remedy"),
]

# ── termination fees ──────────────────────────────────────────────────────────
# Naming and word order both vary more than they first appear, and the WBD /
# Paramount agreement broke three assumptions at once:
#
#   1. The acquirer's fee is not always a "reverse" fee. Paramount's is the
#      "Regulatory Termination Fee", payable if the deal dies on antitrust
#      grounds. That convention shows up in deals with serious regulatory risk,
#      which is exactly the population where the fee carries the most signal.
#
#   2. The amount often precedes the defined term: "a fee of $3,000,000,000 in
#      cash (the 'Company Termination Fee')". Patterns that expect
#      label-then-amount walk straight past it.
#
#   3. Not every termination fee in an agreement belongs to this deal. WBD's
#      contains a $2.8bn "Netflix Termination Fee" -- Paramount paying Netflix
#      so Warner can break a DIFFERENT merger agreement. It says nothing about
#      commitment here, and reporting it would be confidently wrong.

# Fee names that mean "the acquirer pays to walk".
ACQUIRER_FEE_NAMES = (
    r'[Rr]everse\s+[Tt]ermination\s+[Ff]ee',
    r'[Pp]arent\s+[Tt]ermination\s+[Ff]ee',
    r'[Bb]uyer\s+[Tt]ermination\s+[Ff]ee',
    r'[Rr]egulatory\s+[Tt]ermination\s+[Ff]ee',
    r'[Aa]ntitrust\s+[Tt]ermination\s+[Ff]ee',
)
# Fee names that mean "the target pays to walk".
TARGET_FEE_NAMES = (
    r'[Cc]ompany\s+[Tt]ermination\s+[Ff]ee',
    r'[Tt]arget\s+[Tt]ermination\s+[Ff]ee',
)

_AMOUNT = r'\$\s*([\d,]+(?:\.\d+)?)\s*(million|billion)?'


def _fee_patterns(names):
    """Both word orders, for each name in the group."""
    pats = []
    for n in names:
        pats.append(rf'{n}[^\n]{{0,200}}?{_AMOUNT}')      # label then amount
        pats.append(rf'{_AMOUNT}[^\n]{{0,120}}?\(\s*(?:the\s+)?[\u201c"\']?{n}')  # amount then label
    return pats


REVERSE_FEE_PATTERNS = _fee_patterns(ACQUIRER_FEE_NAMES)
COMPANY_FEE_PATTERNS = _fee_patterns(TARGET_FEE_NAMES)

# A fee named after neither party belongs to some other transaction.
THIRD_PARTY_FEE = re.compile(
    r'\b([A-Z][A-Za-z]+)\s+[Tt]ermination\s+[Ff]ee')
KNOWN_FEE_WORDS = {'reverse', 'parent', 'buyer', 'regulatory', 'antitrust',
                   'company', 'target', 'the', 'a', 'such', 'applicable'}


def _to_dollars(amount, unit):
    """'500' + 'million' -> 500_000_000. Bare numbers with commas pass through."""
    try:
        n = float(str(amount).replace(",", ""))
    except (TypeError, ValueError):
        return None
    u = (unit or "").lower()
    if "billion" in u:
        return n * 1_000_000_000
    if "million" in u:
        return n * 1_000_000
    return n


def _first_match(text, patterns):
    """Returns (label, matched_text) for the first pattern that hits."""
    for pat, label in patterns:
        m = re.search(pat, text)
        if m:
            return label, m.group(0)[:180]
    return None, None


def check_antitrust_efforts(text):
    """
    How hard the acquirer is bound to fight for regulatory clearance.

    A hell-or-high-water clause with a burdensome-condition carve-out is not
    hell or high water. The carve-out is checked FIRST for exactly that reason:
    reporting the strong reading on a qualified clause is the expensive error.
    """
    if not text:
        return UNKNOWN, "no text", None

    flat = re.sub(r'\s+', ' ', text)

    hohw_label, hohw_text = _first_match(flat, HOHW_PATTERNS)
    carve_label, carve_text = _first_match(flat, CARVEOUT_PATTERNS)
    weak_label, weak_text = _first_match(flat, WEAK_EFFORTS_PATTERNS)

    if hohw_label and carve_label:
        return WEAK, (f"efforts covenant reads '{hohw_label}' but is limited by a "
                      f"{carve_label}, so the obligation has a ceiling"), carve_text
    if hohw_label:
        return STRONG, (f"'{hohw_label}' — the acquirer is obliged to take whatever "
                        f"remedial action regulators demand"), hohw_text
    if weak_label:
        return WEAK, (f"'{weak_label}' — the acquirer may walk when clearance gets "
                      f"expensive"), weak_text
    return UNKNOWN, "no antitrust efforts language found", None


def check_financing(text):
    """
    Absence of a financing condition is the good outcome. Committed letters
    strengthen an already-unconditioned obligation but do not substitute for one.
    """
    if not text:
        return UNKNOWN, "no text", None

    flat = re.sub(r'\s+', ' ', text)

    no_label, no_text = _first_match(flat, NO_FINANCING_COND)
    yes_label, yes_text = _first_match(flat, HAS_FINANCING_COND)
    letter_label, letter_text = _first_match(flat, COMMITMENT_LETTERS)

    if no_label:
        extra = f", backed by a {letter_label}" if letter_label else ""
        return STRONG, (f"{no_label}{extra} — the buyer cannot blame credit "
                        f"markets"), no_text
    if yes_label:
        return WEAK, (f"{yes_label} — the buyer's obligation depends on funding "
                      f"it has not yet drawn"), yes_text
    if letter_label:
        return UNKNOWN, (f"a {letter_label} exists but the agreement does not say "
                         f"whether closing is conditioned on financing"), letter_text
    return UNKNOWN, "no financing language found", None


def check_specific_performance(text):
    """
    Whether the target can compel closing in court, or is left suing for money.
    A limitation clause outranks a grant, since agreements routinely grant the
    right and then cap it two paragraphs later.
    """
    if not text:
        return UNKNOWN, "no text", None

    flat = re.sub(r'\s+', ' ', text)

    limited_label, limited_text = _first_match(flat, SPECIFIC_PERF_LIMITED)
    yes_label, yes_text = _first_match(flat, SPECIFIC_PERF_YES)

    if limited_label:
        return WEAK, (f"{limited_label} — the target cannot compel closing, only "
                      f"collect"), limited_text
    if yes_label:
        return STRONG, (f"{yes_label} — the target can ask a court to force the "
                        f"deal to close"), yes_text
    return UNKNOWN, "no specific performance language found", None


def _amount_from(match):
    """Both pattern shapes put the amount in the first two groups that exist."""
    g = [x for x in match.groups() if x is not None]
    if not g:
        return None
    amount = g[0]
    unit = g[1] if len(g) > 1 and g[1] and g[1].lower() in ('million', 'billion') else None
    return _to_dollars(amount, unit)


def third_party_fee_names(text):
    """
    Fee names belonging to neither party. WBD's agreement carries a $2.8bn
    "Netflix Termination Fee" -- a payment to a company outside this deal
    entirely, and a number that would look authoritative and mean nothing.
    """
    out = set()
    for m in THIRD_PARTY_FEE.finditer(text or ""):
        word = m.group(1)
        if word.lower() not in KNOWN_FEE_WORDS:
            out.add(word)
    return out


def extract_termination_fees(text, deal_value=None):
    """
    Both fees plus the asymmetry between them.

    The acquirer's fee is what walking away costs. Set against the target's fee
    it says who wants this more; set against deal value it says whether the cost
    is real.
    """
    if not text:
        return {}

    flat = re.sub(r'\s+', ' ', text)
    out = {}
    foreign = third_party_fee_names(flat)
    if foreign:
        out['third_party_fees_ignored'] = sorted(foreign)

    def _find(patterns, exclude_amount=None):
        for pat in patterns:
            for m in re.finditer(pat, flat):
                window = flat[max(0, m.start() - 60):m.end() + 60]
                # A fee belonging to another transaction is not this deal's.
                if any(f in window for f in foreign):
                    continue
                amt = _amount_from(m)
                if amt and amt > 100_000 and amt != exclude_amount:
                    return amt, m.group(0)[:180]
        return None, None

    amt, txt = _find(REVERSE_FEE_PATTERNS)
    if amt:
        out['reverse_fee'], out['reverse_fee_text'] = amt, txt

    amt, txt = _find(COMPANY_FEE_PATTERNS, exclude_amount=out.get('reverse_fee'))
    if amt:
        out['company_fee'], out['company_fee_text'] = amt, txt

    rf, cf = out.get('reverse_fee'), out.get('company_fee')
    if rf and cf:
        out['asymmetry'] = round(rf / cf, 2)
    if rf and deal_value:
        out['reverse_fee_pct'] = round(rf / deal_value * 100, 2)
    return out


def assess_commitment(agreement_text, deal_value=None):
    """
    Everything at once. Returns a dict the UI can render directly.

    `strength` is a count of strong terms out of the three that resolve to a
    verdict. Deliberately not a score: three binary readings do not average into
    anything meaningful, and a number would invite exactly the false precision
    the V3 backtest already warned about.
    """
    anti_v, anti_why, anti_q = check_antitrust_efforts(agreement_text)
    fin_v, fin_why, fin_q = check_financing(agreement_text)
    sp_v, sp_why, sp_q = check_specific_performance(agreement_text)
    fees = extract_termination_fees(agreement_text, deal_value)

    terms = [
        {'term': 'Antitrust obligation', 'verdict': anti_v, 'meaning': anti_why, 'quote': anti_q},
        {'term': 'Financing condition', 'verdict': fin_v, 'meaning': fin_why, 'quote': fin_q},
        {'term': 'Specific performance', 'verdict': sp_v, 'meaning': sp_why, 'quote': sp_q},
    ]

    if fees.get('reverse_fee'):
        bits = [f"the acquirer pays ${fees['reverse_fee']/1e6:.0f}M to walk away"]
        if fees.get('reverse_fee_pct'):
            bits.append(f"{fees['reverse_fee_pct']:.1f}% of deal value")
        if fees.get('asymmetry'):
            bits.append(f"{fees['asymmetry']:.1f}x what the target pays")
        terms.append({
            'term': 'Reverse termination fee',
            'verdict': STRONG if (fees.get('reverse_fee_pct') or 0) >= 3 else UNKNOWN,
            'meaning': ", ".join(bits),
            'quote': fees.get('reverse_fee_text'),
        })

    resolved = [t for t in terms if t['verdict'] in (STRONG, WEAK)]
    strong = sum(1 for t in resolved if t['verdict'] == STRONG)

    return {
        'terms': terms,
        'fees': fees,
        'strong_count': strong,
        'resolved_count': len(resolved),
        'summary': (f"{strong} of {len(resolved)} commitment terms favour closing"
                    if resolved else "no commitment terms could be read"),
    }