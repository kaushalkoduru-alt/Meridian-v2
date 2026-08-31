"""
OUTSIDE DATE — the deadline written into the merger agreement

Past this date either party can walk away without paying a break fee. It is the
hardest deadline in the contract and no screen shows it.

WHY IT MATTERS

  It is a clock on capital. A 6% spread with fourteen months to run is a much
  worse trade than the same 6% with three months left, and a feed showing only
  the spread cannot tell them apart.

  It is when a deal gets dangerous. Deals that stall into the outside date get
  renegotiated, repriced, or abandoned. Reaching it without regulatory clearance
  is the loudest warning available, and it is knowable months ahead.

  Extensions are themselves a signal. When parties push the date back, something
  has gone wrong -- Vacasa amended twice inside three weeks in March 2026.

  And it pairs with the termination fee already extracted. WBD's $7bn regulatory
  fee becomes payable at the outside date if antitrust has not cleared. Neither
  number tells that story alone.

NAMING

  Agreements call it the End Date, the Outside Date, or the Termination Date,
  and often define it with automatic extensions: "provided that if the
  Regulatory Conditions have not been satisfied, the End Date shall be
  automatically extended to [LATER DATE]". Where extensions exist the LATEST
  date is the real deadline, since the earlier one passes without consequence.
"""

import re
from datetime import datetime, timedelta

# Written-out dates dominate in agreements. Numeric formats appear in exhibits
# and amendments.
_MONTH = (r'January|February|March|April|May|June|July|August|September|'
          r'October|November|December')
_DATE_WORDS = rf'({_MONTH})\s+(\d{{1,2}}),?\s+(\d{{4}})'
_DATE_SLASH = r'(\d{1,2})/(\d{1,2})/(\d{4})'

# Deadline prepositions, longest first so the compound forms win over the bare
# 'before'/'prior to' they contain. Both compounds appear in filings: WBD
# writes "on or before March 4, 2027", others "on or prior to".
_PREP = (r'(?:on\s+or\s+prior\s+to|on\s+or\s+before|no\s+later\s+than|'
         r'prior\s+to|before|by)')

# Agreements put a cutoff time between the preposition and the date, and every
# form of it appeared in these twelve: "11:59 p.m. (New York City time) on",
# "5:00 p.m. New York City time on", "11:59 p.m., New York City time, on".
# Optional, so the plain "prior to March 15, 2027" shape still matches.
_TIME = r'(?:\d{1,2}:\d{2}\s*[ap]\.?m\.?[^\n]{0,45}?\bon\s+)?'

# Ordered by how strongly each phrasing indicates the operative deadline.
# A definition beats a passing mention, since agreements reference the term
# dozens of times after defining it once.
PATTERNS = [
    (rf'[""\s]*(?:End|Outside|Termination)\s+Date[""\s]*\s*(?:means|shall\s+mean)\s*'
     rf'[^\n]{{0,80}}?{_DATE_WORDS}', "End Date definition"),
    (rf'(?:the\s+)?(?:End|Outside|Termination)\s+Date[^\n]{{0,60}}?'
     rf'\(\s*(?:the\s+)?[""\s]*(?:End|Outside|Termination)\s+Date[""\s]*\s*\)[^\n]{{0,60}}?{_DATE_WORDS}',
     "End Date parenthetical"),
    # The subject is separated from the conditional by an enumerator in real
    # agreements: WBD reads "if: (i) the Effective Time shall not have
    # occurred". Requiring 'if the' adjacently missed it. The gap stays short
    # so this cannot reach across a sentence.
    (rf'(?:if|unless)\b[^\n]{{0,15}}?the\s+(?:Closing|Merger|Effective\s+Time)[^\n]{{0,120}}?'
     rf'{_PREP}\s+{_TIME}{_DATE_WORDS}',
     "closing deadline clause"),
    # 'shall not HAVE occurred' is the ordinary voice and the auxiliary was not
    # allowed for, so the clause naming WBD's deadline did not match.
    (rf'(?:has|shall|will|would)\s+not\s+(?:have\s+)?(?:been\s+)?'
     rf'(?:occurred|consummated|closed|become\s+effective)[^\n]{{0,100}}?'
     rf'{_PREP}\s+{_TIME}{_DATE_WORDS}',
     "not-consummated-by clause"),
    (rf'[""\s]*(?:End|Outside|Termination)\s+Date[""\s]*[^\n]{{0,60}}?{_DATE_SLASH}',
     "End Date, numeric"),
]

# The two kinds of extension move the deadline differently, and conflating them
# misreports the date a holder is trading against.
#
# AUTOMATIC: the date moves on its own when a condition fails, so the outer date
# is the real deadline and the base passes without consequence.
#
# ELECTIVE: someone must affirmatively act. The BASE date is the real deadline,
# because it passes WITH consequence unless a party elects. Reporting the outer
# date there tells a holder they have months more than they may.
AUTOMATIC_EXTENSION_MARKERS = [
    r'automatically\s+(?:be\s+)?(?:further\s+)?extended',
    r'shall\s+(?:be\s+)?automatically\s+(?:be\s+)?extended',
    r'shall\s+be\s+(?:further\s+)?extended',
    r'shall\s+be\s+deemed\s+extended',
    # HTML stripping drops page numbers into the middle of the phrase: PAYO
    # reads "shall, automatically 65 and without any required action from
    # either party, be extended". Bounded and sentence-local so it cannot
    # reach into an unrelated clause.
    r'automatically[^.]{0,80}?\bbe\s+extended',
]
ELECTIVE_EXTENSION_MARKERS = [
    r'elect\s+to\s+extend',
    r'may\s+be\s+extended',
    r'extended\s+at\s+the\s+(?:option|election)\s+of',
    r'may,?\s*by\s+written\s+notice[^.]{0,80}?\bextend\b',
]

# Kept for callers that only ask whether any extension exists.
EXTENSION_MARKERS = AUTOMATIC_EXTENSION_MARKERS + ELECTIVE_EXTENSION_MARKERS


# ── DEADLINES DEFINED AS A PERIOD FROM SIGNING ───────────────────────────────
#
# Four of nineteen live agreements never state a calendar date at all. They
# define the deadline as a period measured from the day the agreement was
# signed, and every PATTERNS entry above terminates in a date, so the module
# read nothing and correctly declined to guess:
#
#   ATKR  "the first Business Day that is twelve (12) months after the date of
#          this Agreement (the 'End Date')"
#   ALOT  "the date that is one hundred and fifty (150) days after the date of
#          this Agreement (the 'Outside Date')"
#   RAMP  "the date that is twelve (12) months after the date hereof (the
#          'Outside Date')"
#   HZO   "the date which is nine months following the date of this Agreement
#          ... the 'Outside Date'"
#
# Distinct from APGE, which has a DATED base extended by a period. Here the
# period IS the definition and there is no base to extend.
#
# The anchor is the agreement's own stated date, never the filing date. Those
# differ for all four — by a day for ATKR, ALOT and HZO and by two for RAMP —
# and a deadline computed off the wrong day is exactly the invented number this
# module exists to avoid. Where no agreement date can be read, nothing is
# returned.

_AGREEMENT_DATE = rf'dated\s+as\s+of\s+{_DATE_WORDS}'

# "twelve (12) months", "one hundred and fifty (150) days", and HZO's bare
# "nine months" with no numeral at all. The numeral wins when present; the words
# carry it when not.
_RELATIVE_DEADLINE = (
    rf'(?:has|shall|will|would)\s+not\s+(?:have\s+)?(?:been\s+)?'
    rf'(?:occurred|consummated|closed|become\s+effective)[^.]{{0,140}}?'
    rf'{_PREP}\s+(?:the\s+)?'
    # "the first Business Day that is", "the date that is", "the date which is"
    rf'(?:(?:first|last)\s+Business\s+Day\s+(?:that\s+|which\s+)?is\s+|'
    rf'date\s+(?:that|which)\s+is\s+)?'
    rf'(?:([A-Za-z][A-Za-z\s\-]{{2,28}}?)\s+)?'
    rf'(?:\(\s*(\d{{1,3}})\s*\)\s*)?'
    rf'(month|day|year)s?\s+(?:after|following|from)\s+'
    rf'the\s+date\s+(?:of\s+this\s+Agreement|hereof)'
)


def extract_agreement_date(agreement_text):
    """
    The date the agreement states for itself, as a datetime, or None.

    Read from the first stretch of the document, where the execution date sits
    on the cover: "AGREEMENT AND PLAN OF MERGER ... Dated as of August 2, 2026".
    Bounded to the opening because "dated as of" recurs throughout an agreement
    in unrelated contexts -- schedules, exhibits, prior agreements.
    """
    if not agreement_text:
        return None
    head = re.sub(r'\s+', ' ', agreement_text[:8000])
    m = re.search(_AGREEMENT_DATE, head, re.IGNORECASE)
    return _to_date(m.groups()) if m else None


def _relative_deadline(flat, agreement_date):
    """
    A deadline stated as a period from signing, resolved against the agreement's
    own date. Returns (date, quote) or None.

    Returns None without an agreement date rather than falling back to anything
    else: the whole value of this reading is that the anchor is the signing day,
    and an anchor off by two days is a deadline off by two days.
    """
    if not agreement_date:
        return None
    m = re.search(_RELATIVE_DEADLINE, flat, re.IGNORECASE)
    if not m:
        return None
    period = _period(m.group(1), m.group(2), m.group(3))
    if not period:
        return None
    n, unit = period
    # A merger deadline is months, not decades. 36 months is generous against a
    # feed whose longest dated deadline is 24 months out.
    if unit == 'month' and n > 36:
        return None
    if unit == 'day' and n > 1100:
        return None
    return _apply_period(agreement_date, n, unit), m.group(0)[:260]


# How far from the anchor a date may sit and still be a deadline rather than a
# parse artifact.
#
# The two cases are not the same, and collapsing them cost GBCS its outside
# date on the very day the deadline arrived. Anchored on the ANNOUNCEMENT, a
# deadline before signing is impossible and 0 is the right floor. Anchored on
# TODAY -- which happens whenever the announcement date is missing, and `filed`
# arrives as NaN on cached rows -- a date in the past is not evidence of
# anything except that the deadline has been reached, which is the single most
# important state this field can hold: past it, either party can walk away
# without paying a break fee.
#
# So the floor is 0 with a real anchor and -24 months without one. A deal whose
# deadline passed two years ago is long gone from the feed by other means; a
# deal whose deadline passed last week is exactly what a holder needs to see.
_MAX_MONTHS_OUT = 42
_MAX_MONTHS_PAST_WITHOUT_ANCHOR = -24


def _plausible(months_out, anchored_on_announcement):
    """Whether a candidate date is a deadline rather than a misread."""
    floor = 0 if anchored_on_announcement else _MAX_MONTHS_PAST_WITHOUT_ANCHOR
    return floor < months_out < _MAX_MONTHS_OUT


def _classify_extension(window):
    """
    Which kind of extension governs the date at the end of this window.

    Agreements carry both kinds: OGN's "shall automatically be extended" is a
    litigation stay that names no calendar date, while the clause that names
    April 26, 2027 is elective. So the cue NEAREST the date decides, not the
    presence of either phrase somewhere in a 400,000 character document.
    """
    auto = max([m.start() for pat in AUTOMATIC_EXTENSION_MARKERS
                for m in re.finditer(pat, window, re.IGNORECASE)] or [-1])
    elec = max([m.start() for pat in ELECTIVE_EXTENSION_MARKERS
                for m in re.finditer(pat, window, re.IGNORECASE)] or [-1])
    if auto < 0 and elec < 0:
        return None
    # Ties and bare 'extend' fall to elective, which reports the EARLIER date.
    # Overstating the time remaining is the more dangerous error.
    return 'automatic' if auto > elec else 'elective'


# Not every extension names a date. APGE's agreement reads "the End Date shall
# be automatically extended by six (6) months" and never states the resulting
# day, so the dated sweep below found nothing to classify and the deal was
# reported as carrying a FIXED deadline -- on an agreement that extends itself
# automatically. That is the same error the dated path exists to prevent, in the
# one shape the dated path cannot see.
#
# The numeral in parentheses is what gets trusted when present: filings write
# the period twice, "six (6) months", and the digits do not depend on a word
# list being complete.
_NUMBER_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
    'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
    'fifteen': 15, 'eighteen': 18, 'twenty': 20, 'twenty-four': 24,
    'thirty': 30, 'sixty': 60, 'ninety': 90,
}

# 'by a period of six (6) months' and 'by six (6) months' both appear, as does
# the bare numeral. Anchored on 'extended' so a stray duration elsewhere in the
# sentence cannot be read as an extension.
_DURATION = (r'extended\s+(?:by\s+)?(?:an?\s+(?:additional\s+)?'
             r'(?:period\s+of\s+)?)?(?:([A-Za-z][A-Za-z\-]{2,11})\s*)?'
             r'(?:\(\s*(\d{1,3})\s*\)\s*)?(month|day|year)s?\b')


# The plausible size of a period depends on its unit, and a single bound cannot
# serve both. 120 was written for months and silently rejected ALOT's deadline,
# which its agreement states as "one hundred and fifty (150) days".
_PERIOD_MAX = {'day': 1100, 'month': 120, 'year': 10}


def _period(word, numeral, unit):
    """The three regex groups -> (count, unit), or None when unreadable."""
    n = int(numeral) if numeral else _NUMBER_WORDS.get((word or '').lower())
    unit = (unit or '').lower()
    # A period larger than this for its unit is a misread, not a deadline.
    if not n or n > _PERIOD_MAX.get(unit, 120):
        return None
    return n, unit


def _apply_period(d, n, unit):
    """
    Add a period to a date the way a contract counts it.

    Calendar months, not 30.44-day approximations: "extended by six (6) months"
    off December 18 lands on June 18, and a day-count lands on the 19th. One day
    is the difference between a deadline that has passed and one that has not.
    """
    if unit == 'day':
        return d + timedelta(days=n)
    months = n * 12 if unit == 'year' else n
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    # The 31st of a month the extension lands short of clamps to that month's
    # end, which is how these clauses are read.
    day = min(d.day, _MONTH_LENGTHS[month] +
              (1 if month == 2 and year % 4 == 0 and
               (year % 100 != 0 or year % 400 == 0) else 0))
    return datetime(year, month, day)


_MONTH_LENGTHS = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _duration_extension(window, base_date):
    """
    The extension in this window that states a PERIOD rather than a date,
    applied to the base date. Returns (date, kind, quote) or None.

    Consecutive AUTOMATIC periods compound -- an agreement that extends by six
    months and then, on the same failed condition, by six more has a real outer
    deadline a year out. An ELECTIVE period does not compound onto them: once
    somebody has to act, the automatic clock has stopped, and the date reported
    as the deadline must be the last one that arrives without anyone acting.
    """
    auto_months, auto_span = [], None
    elective = elective_span = None
    for m in re.finditer(_DURATION, window, re.IGNORECASE):
        p = _period(*m.groups())
        if not p:
            continue
        # Everything up to this clause, so the nearest preceding cue decides.
        kind = _classify_extension(window[:m.end()]) or 'elective'
        # The clause is quoted from its own sentence, not from the base date's
        # -- a computed deadline has to show the words that compute it.
        span = window[max(0, m.start() - 170):m.end() + 60]
        if kind == 'automatic':
            auto_months.append(p)
            if auto_span is None:
                auto_span = span
        elif elective is None:
            elective, elective_span = p, span

    if auto_months:
        d = base_date
        for n, unit in auto_months:
            d = _apply_period(d, n, unit)
        return d, 'automatic', auto_span
    if elective:
        return _apply_period(base_date, *elective), 'elective', elective_span
    return None


_MONTHS = {m.lower(): i for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'], start=1)}


def _to_date(groups):
    """Both formats collapse to a date, or None when the parse fails."""
    try:
        if groups[0].lower() in _MONTHS:                 # written out
            return datetime(int(groups[2]), _MONTHS[groups[0].lower()], int(groups[1]))
        return datetime(int(groups[2]), int(groups[0]), int(groups[1]))  # numeric
    except (ValueError, KeyError, IndexError, AttributeError):
        return None


def extract_outside_date(agreement_text, announced_date=None, now=None,
                         agreement_date=None):
    """
    Returns a dict, or None when no date could be read.

    Plausibility is bounded by the announcement: a merger deadline sits months
    to a couple of years after signing, so a date before the announcement or a
    decade after it is a parse artifact rather than a deadline. Without an
    announcement date the window is anchored on today instead.
    """
    if not agreement_text:
        return None

    now = now or datetime.utcnow()
    flat = re.sub(r'\s+', ' ', agreement_text)

    # Whether the anchor is the announcement or merely today decides what
    # counts as implausible, so the two cases cannot share one bound.
    # The agreement's own date beats the filing date, and either beats today.
    anchor = announced_date or agreement_date or now
    anchored_on_announcement = (announced_date is not None
                                or agreement_date is not None)
    if isinstance(anchor, str):
        try:
            anchor = datetime.strptime(anchor[:10], "%Y-%m-%d")
        except ValueError:
            anchor, anchored_on_announcement = now, False

    has_extension = any(re.search(p, flat, re.IGNORECASE) for p in EXTENSION_MARKERS)

    found = []
    for pattern, label in PATTERNS:
        for m in re.finditer(pattern, flat, re.IGNORECASE):
            d = _to_date(m.groups())
            if not d:
                continue
            months_out = (d - anchor).days / 30.4
            if not _plausible(months_out, anchored_on_announcement):
                continue
            found.append({
                'date': d,
                'label': label,
                'quote': m.group(0)[:220],
                'position': m.start(),
            })
        # Stopping at the first productive tier is right when the date is fixed:
        # a definition outranks the dozens of later references to the same term.
        # It is wrong when the agreement extends automatically, because the
        # extension date lives in a different clause and a later tier. Reporting
        # the earlier date there would name a deadline that passes with no
        # consequence, which is worse than reporting none.
        if found and not has_extension:
            break

    if not found:
        # No dated base anywhere. The deadline may still be defined as a period
        # from signing, which is a shape the tiers above cannot express.
        _agd = agreement_date or extract_agreement_date(agreement_text)
        _rel = _relative_deadline(flat, _agd)
        if not _rel:
            return None
        _rdate, _rquote = _rel
        found = [{'date': _rdate, 'label': 'period from the agreement date',
                  'quote': _rquote, 'position': flat.find(_rquote[:60])
                  if _rquote else 0}]

    # An extension clause states its date in prose near the definition, not in
    # its own tier, so sweep for any plausible date the tiers did not reach.
    if has_extension:
        for m in re.finditer(_DATE_WORDS, flat, re.IGNORECASE):
            d = _to_date(m.groups())
            if not d:
                continue
            months_out = (d - anchor).days / 30.4
            if not _plausible(months_out, anchored_on_announcement):
                continue
            # Wider than the cue search needs, so the nearest extension verb
            # is inside it and can be classified.
            window = flat[max(0, m.start() - 320):m.start()]
            if re.search(r'extend', window, re.IGNORECASE):
                kind = _classify_extension(window) or 'elective'
                found.append({
                    'date': d,
                    'label': kind + " extension",
                    'kind': kind,
                    'quote': flat[max(0, m.start() - 160):m.end() + 40],
                    'position': m.start(),
                })

    # found[0] came from the strongest productive tier: the BASE deadline,
    # the date the agreement states before any extension is applied.
    base = found[0]
    _auto = [f for f in found if f.get('kind') == 'automatic']
    _elec = [f for f in found if f.get('kind') == 'elective'
             and f['date'] > base['date']]

    if _auto:
        # Moves on its own when a condition fails, so the outer date is the
        # real deadline and the base passes without consequence.
        chosen = max([base] + _auto, key=lambda f: f['date'])
        extension_type = 'automatic'
        elective_date = None
    elif _elec:
        # Someone must affirmatively act, so the BASE date is the real
        # deadline. The option is reported alongside it, never in place of
        # it -- reporting the outer date tells a holder they have months
        # more than they may.
        chosen = base
        extension_type = 'elective'
        elective_date = max(_elec, key=lambda f: f['date'])['date']
    else:
        # No DATED extension clause. Two different situations hide here and
        # they must not be answered the same way.
        #
        # The first states the extension as a PERIOD: APGE reads "the End Date
        # shall be automatically extended by six (6) months" and never names
        # the resulting day. That deadline is real, automatic, and computable
        # from the base date the agreement itself states -- and reading it as
        # no extension at all reported a fixed deadline on an agreement that
        # moves its own, the exact error the dated path exists to prevent.
        #
        # The second names no period either -- AES's "as such date may be
        # extended" -- where nothing is computable and only the kind is known.
        chosen = base
        elective_date = None
        # Forward-weighted, because the proviso follows the End Date it
        # extends. APGE's sits about 1,100 characters past the definition, well
        # outside the symmetric window that had to classify the AES case.
        _near = flat[max(0, base['position'] - 600):base['position'] + 2500]
        _dur = _duration_extension(_near, base['date'])
        if _dur:
            _dur_date, extension_type, _dur_quote = _dur
            if extension_type == 'automatic':
                # Arrives without anyone acting, so the computed outer date is
                # the deadline for the same reason a dated one is.
                chosen = dict(base, date=_dur_date, quote=_dur_quote,
                              label='automatic extension, stated as a period')
            else:
                # Someone must elect, so the base date still governs and the
                # option is reported beside it, never in place of it.
                elective_date = _dur_date
        else:
            extension_type = (_classify_extension(_near)
                              if re.search(r'extend', _near, re.IGNORECASE) else None)

    days_left = (chosen['date'] - now).days
    return {
        'date': chosen['date'].strftime('%Y-%m-%d'),
        # %-d is glibc-only and raises on Windows; build the day by hand.
        'display': '{} {}, {}'.format(chosen['date'].strftime('%B'),
                                      chosen['date'].day, chosen['date'].year),
        'days_remaining': days_left,
        'passed': days_left < 0,
        'extendable': extension_type is not None,
        'extension_type': extension_type,
        'extension_date': (elective_date.strftime('%Y-%m-%d')
                           if elective_date else None),
        'source': chosen['label'],
        'quote': chosen['quote'],
        'candidates_found': len(found),
        'meaning': _meaning(days_left, extension_type, elective_date),
    }


def _meaning(days_left, extension_type, elective_date=None):
    """Plain language, written for someone who has never seen the term."""
    if days_left < 0:
        return ("This deadline has passed. Either company can now walk away "
                "without paying a break fee, so the deal is being kept alive by "
                "agreement rather than by contract.")

    base = ("If the merger has not closed by this date, either company can walk "
            "away without paying a break fee. Deals that reach it are usually "
            "renegotiated, extended, or abandoned.")

    if days_left < 90:
        base += (" With under three months left, an extension or a decision is "
                 "close.")
    if extension_type == 'automatic':
        base += (" This agreement extends the date automatically if regulatory "
                 "clearance is still outstanding, and the date above is that "
                 "outer deadline. An extension is itself a sign something has "
                 "gone wrong.")
    elif extension_type == 'elective':
        when = ('{} {}, {}'.format(elective_date.strftime('%B'),
                                   elective_date.day, elective_date.year)
                if elective_date else 'a later date')
        base += (" Either party may elect to extend this to " + when + ", but "
                 "the deadline above applies unless one of them does.")
    return base