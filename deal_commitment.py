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

# ── fee formatting ────────────────────────────────────────────────────────────
# One divisor cannot span these fees. They run from GBCS's $400,000 to WBD's
# $7,000,000,000 — four orders of magnitude — and dividing everything by a
# million rendered the small one as "$0M" and the large one as "$7000M". Both
# are wrong in the way that matters: one erases a fee that exists, the other
# reads as a typo and costs the number its credibility.
def format_fee(amount):
    """A fee as a reader would write it. None passes through."""
    if amount is None:
        return None
    a = float(amount)
    # Under a million, the exact dollars. Rounding here is what produced "$0M",
    # and a small fee is precisely the case where the digits carry the point.
    if a < 1_000_000:
        return f"${a:,.0f}"
    # Millions, whole. The second test catches the boundary: $999,999,999 is
    # under a billion but rounds to 1000M, which is the "$7000M" shape again.
    if a < 1e9 and round(a / 1e6) < 1000:
        return f"${a / 1e6:.0f}M"
    return f"${a / 1e9:.1f}B"


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
    # AES splits the acquirer's fee in two: a "Parent General Termination Fee"
    # of $587,861,060 for an ordinary walk and a "Parent Regulatory Termination
    # Fee" of $100,000,000 for an antitrust failure, with "Parent Termination
    # Fee" defined as the pair. The general fee is the headline number, so it is
    # named ahead of the bare "Parent Termination Fee" it would otherwise lose to.
    r'[Pp]arent\s+[Gg]eneral\s+[Tt]ermination\s+[Ff]ee',
    r'[Pp]arent\s+[Tt]ermination\s+[Ff]ee',
    r'[Bb]uyer\s+[Tt]ermination\s+[Ff]ee',
    r'[Pp]urchaser\s+[Tt]ermination\s+[Ff]ee',
    r'[Rr]egulatory\s+[Tt]ermination\s+[Ff]ee',
    r'[Aa]ntitrust\s+[Tt]ermination\s+[Ff]ee',
)
# Fee names that mean "the target pays to walk".
# APGE names the target's fee with no qualifier at all: a fee of $381,273,716 in
# cash (the " Termination Fee "). The bare name is a substring of every qualified
# one, so it is admitted under two restrictions. The lookbehind refuses a match
# preceded by a word -- "Parent Termination Fee", "Netflix Termination Fee" --
# which is the substring collision the first version of this module hit. And it
# is listed in QUALIFIED_ONLY_NAMES below, which keeps it out of the loose
# label-near-an-amount tier where that lookbehind would be the only thing
# standing between it and the acquirer's figure.
_BARE_FEE_NAME = r'(?<![A-Za-z]\s)[Tt]ermination\s+[Ff]ee'

TARGET_FEE_NAMES = (
    r'[Cc]ompany\s+[Tt]ermination\s+[Ff]ee',
    r'[Tt]arget\s+[Tt]ermination\s+[Ff]ee',
    _BARE_FEE_NAME,
)

# Names too generic for the loose tier: definition and parenthetical shapes only,
# both of which anchor on a quote or a "(the" and cannot drift.
QUALIFIED_ONLY_NAMES = frozenset({_BARE_FEE_NAME})

_AMOUNT = r'\$\s*([\d,]+(?:\.\d+)?)\s*(million|billion)?'


# Stripping HTML leaves the curly quotes around a defined term separated from the
# term itself: SLAB, GBTG and APGE all read (the " Parent Termination Fee ") with
# spaces inside the quotes, where WBD reads (the "Regulatory Termination Fee")
# without them. Anchoring tight to the quote character passed the WBD fixture and
# missed three live agreements.
_QUOTE = r'[\u201c\u201d"\']'


def _fee_patterns(names):
    """
    Three shapes per name, most specific first.

    The tiers are built separately and concatenated so precedence runs by SHAPE
    rather than by name: a definition anywhere in the agreement outranks a loose
    label-near-an-amount scan for any other name. That ordering is what stops
    AES's "Parent Termination Fee" -- defined as the sum of two other fees, with
    no amount of its own -- from sweeping up whatever figure sits within 200
    characters of it.
    """
    defn, amount_first, label_first = [], [], []
    for n in names:
        # 1. The definition: " Parent General Termination Fee " means an amount
        #    in cash equal to $587,861,060.   (AES)
        defn.append(
            rf'{_QUOTE}?\s*{n}\s*{_QUOTE}?\s*means\s+'
            rf'(?:an\s+amount\s+)?(?:in\s+cash\s+)?(?:equal\s+to\s+)?{_AMOUNT}')
        # 2. Amount, then the defined term in parentheses: a fee equal to
        #    $499,000,000 (the " Parent Termination Fee ")   (SLAB, GBTG, APGE, WBD)
        #    GBCS opens the parenthesis with a back-reference instead of going
        #    straight to the article -- an amount equal to $400,000 (such amount,
        #    the " Purchaser Termination Fee ") -- so a short lead-in is allowed,
        #    bounded by [^)] so it cannot wander past the parenthetical it is in.
        #    The gap may hold neither a period nor another dollar sign: an amount
        #    and the parenthetical that names it belong to one clause. A plain
        #    120-character window let GBCS's reverse pattern begin at the
        #    COMPANY's $400,000, jump the sentence boundary, and finish inside
        #    the Purchaser parenthetical -- a right number under a wrong span,
        #    which then swallowed the company fee's own definition as an overlap.
        amount_first.append(
            rf'{_AMOUNT}[^\n$.]{{0,60}}?\(\s*(?:[^)$.]{{0,40}}?\s*the\s+)?'
            rf'{_QUOTE}?\s*{n}')
        # 3. Label, then an amount nearby: a Reverse Termination Fee of $500
        #    million. The loosest of the three, so it runs last -- and generic
        #    names sit it out entirely.
        if n not in QUALIFIED_ONLY_NAMES:
            label_first.append(rf'{n}[^\n]{{0,200}}?{_AMOUNT}')
    return defn + amount_first + label_first


REVERSE_FEE_PATTERNS = _fee_patterns(ACQUIRER_FEE_NAMES)
COMPANY_FEE_PATTERNS = _fee_patterns(TARGET_FEE_NAMES)

# A fee named after neither party belongs to some other transaction.
THIRD_PARTY_FEE = re.compile(
    r'\b([A-Z][A-Za-z]+)\s+[Tt]ermination\s+[Ff]ee')
# 'general' belongs here for the same reason as 'regulatory': AES's "Parent
# General Termination Fee" is this deal's own fee under a compound name, and
# reading "General" as an outside party suppressed the entire AES fee pair.
# The structural words are here because an agreement's table of defined terms
# collapses into one line when the HTML is stripped, putting one row's section
# reference immediately before the next row's label: "... Supporting Stockholders
# Recitals Surviving Corporation Recitals Termination Fee 7.3(a)(iii)(B) ..." in
# APGE's. "Recitals" is not a party to anything.
KNOWN_FEE_WORDS = {'reverse', 'parent', 'buyer', 'regulatory', 'antitrust',
                   'company', 'target', 'general', 'purchaser',
                   'the', 'a', 'such', 'applicable',
                   'recitals', 'article', 'section', 'schedule', 'exhibit', 'annex',
                   'preamble', 'appendix'}

# A bare section reference -- 7.3(a)(iii), 3.17(b) -- as it appears in an index
# row, where nothing but numbering separates one defined term from the next.
_SECTION_REF = re.compile(r'\b\d+\.\d+(?:\([A-Za-z0-9]+\))*')
# Four or more capitalised words running together is a column of defined terms,
# not a sentence.
_TERM_RUN = re.compile(r'(?:\b[A-Z][A-Za-z]+\s+){4,}')
# Any of these means the window is prose, whatever else it contains. The Netflix
# fee sits in a real sentence -- "Buyer ... shall pay or cause to be paid
# $2,800,000,000" -- and prose is what separates it from an index row.
_PROSE = re.compile(
    r'\b(?:shall|will|means|meaning|pay|paid|payable|terminated?|'
    r'is|are|was|were|be|been|has|have|had|may|must|agrees?|received?|'
    r'constitutes?|occurs?|equal|entitled|obligated)\b', re.I)


def _looks_like_index_row(window):
    '''
    True when the surrounding text is a table-of-defined-terms row rather than a
    sentence.

    Both signals are required. A section reference alone proves nothing: the
    Netflix fee's own sentence cites Section 8.1(c)(ii), and the WBD clause that
    pays it opens "Section 6.17 Netflix Termination Fee". So the absence of any
    verb carries the decision, and the structural evidence only confirms it.
    '''
    if _PROSE.search(window):
        return False
    return len(_SECTION_REF.findall(window)) >= 2 or bool(_TERM_RUN.search(window))


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

    A name is only reported out of prose. The same detector reading an
    agreement's index of defined terms found a fee owed to "Recitals" -- the
    kind of confident nonsense that costs trust in the readings that are right.
    """
    text = text or ""
    out = set()
    for m in THIRD_PARTY_FEE.finditer(text):
        word = m.group(1)
        if word.lower() in KNOWN_FEE_WORDS:
            continue
        if _looks_like_index_row(text[max(0, m.start() - 160):m.end() + 160]):
            continue
        out.add(word)
    return out


def _resolve_cross_reference(flat, names, foreign=()):
    """
    One hop, and one hop only.

    ALOT's agreement never states the acquirer's fee as a figure. It says
    "Reverse Termination Fee" means an amount equal to the Termination Fee, and
    defines that term 6,451 characters away, in an alphabetical definitions list:
    "Termination Fee" means $9,648,000. Both halves are unambiguous; only the
    join is missing, so the number is read rather than inferred.

    A second hop is refused. Two levels of indirection are rare enough in real
    agreements that the shape is more likely to be a misparse than a definition,
    and a wrong fee is worse than no fee. Because the lookup below requires a
    dollar amount immediately after "means", a referent that is itself another
    reference simply fails to match, and the caller gets nothing.
    """
    for n in names:
        ref = re.search(
            rf'{_QUOTE}?\s*{n}\s*{_QUOTE}?\s*means\s+(?:an\s+amount\s+)?'
            rf'(?:in\s+cash\s+)?equal\s+to\s+the\s+{_QUOTE}?\s*'
            rf'([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){{0,4}})', flat)
        if not ref:
            continue
        term = ref.group(1).strip()
        # A term that refers to itself is a parse artifact, not a definition.
        if re.fullmatch(n, term):
            continue
        # A fee belonging to another transaction stays out, exactly as it does
        # on the direct shapes.
        if any(f in term for f in foreign):
            continue
        loose = r'\s+'.join(re.escape(w) for w in term.split())
        defn = re.search(
            rf'{_QUOTE}?\s*{loose}\s*{_QUOTE}?\s*means\s+(?:an\s+amount\s+)?'
            rf'(?:in\s+cash\s+)?(?:equal\s+to\s+)?{_AMOUNT}', flat)
        if not defn:
            continue
        amt = _amount_from(defn)
        if amt and amt > 100_000:
            return amt, f"{ref.group(0)[:110]} ... {defn.group(0)[:110]}"
    return None, None


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

    def _find(patterns, exclude_span=None):
        """
        Rejects a second reading of the SAME sentence, not a second reading of
        the same number.

        Excluding by amount assumed the two fees always differ. APGE's do not:
        both are $381,273,716, stated in two separate sentences, and dropping the
        target's for matching the acquirer's threw away a real 1.0x asymmetry --
        which is itself a finding, since a buyer and a seller who post identical
        break fees are telling you something about who wanted the deal.
        """
        for pat in patterns:
            for m in re.finditer(pat, flat):
                window = flat[max(0, m.start() - 60):m.end() + 60]
                # A fee belonging to another transaction is not this deal's.
                if any(f in window for f in foreign):
                    continue
                # Overlap, rather than an identical offset: the tiers start at
                # different points within one sentence, so two patterns can read
                # the same fee from spans that begin a few characters apart.
                if exclude_span and not (m.end() <= exclude_span[0]
                                         or m.start() >= exclude_span[1]):
                    continue
                amt = _amount_from(m)
                if amt and amt > 100_000:
                    return amt, m.group(0)[:180], (m.start(), m.end())
        return None, None, None

    amt, txt, span = _find(REVERSE_FEE_PATTERNS)
    if not amt:
        # No figure stated against the name. It may still be defined by
        # reference to a term that does carry one.
        amt, txt = _resolve_cross_reference(flat, ACQUIRER_FEE_NAMES, foreign)
    if amt:
        out['reverse_fee'], out['reverse_fee_text'] = amt, txt
    reverse_span = span

    amt, txt, _ = _find(COMPANY_FEE_PATTERNS, exclude_span=reverse_span)
    if not amt:
        amt, txt = _resolve_cross_reference(flat, TARGET_FEE_NAMES, foreign)
        # The resolver reports no span, so a same-amount result there cannot be
        # told apart from a re-read of the acquirer's fee. Left out.
        if amt == out.get('reverse_fee'):
            amt, txt = None, None
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
        bits = [f"the acquirer pays {format_fee(fees['reverse_fee'])} to walk away"]
        _pct = fees.get('reverse_fee_pct')
        if _pct:
            bits.append(f"{_pct:.1f}% of deal value")
        if fees.get('asymmetry'):
            bits.append(f"{fees['asymmetry']:.1f}x what the target pays")
        # A fee under the threshold is WEAK, not UNKNOWN. Collapsing the two
        # sent GBCS's fee — read at $400,000 and 2.0% of deal value, quoted off
        # the agreement — into the deal page's "could not be read from this
        # agreement" line, which is a false statement about a number the parser
        # had in hand. A small reverse fee is weak commitment, and that is
        # information the reader wants, not an absence of information.
        #
        # UNKNOWN survives only where it is true: a fee found but impossible to
        # size, because the deal value needed to compute the percentage is
        # missing. No fee at all appends no term, so it never reaches here.
        if _pct is None:
            _verdict = UNKNOWN
        else:
            _verdict = STRONG if _pct >= 3 else WEAK
        terms.append({
            'term': 'Reverse termination fee',
            'verdict': _verdict,
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