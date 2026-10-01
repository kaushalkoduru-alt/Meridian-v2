"""
Risk breakdown: the single risk band, un-compressed into five dimensions.

The critique was that one band does not say enough. The answer is not a smarter
number; it is to show the facts the band was built from. Every line here is read
off something already extracted (milestone timeline, commitment terms, outside
date, pricing, flags, break price) and carries its source. Nothing here feeds the
score, the band, or either enforcing gate, and there are no weights.

Each dimension gets a qualitative read -- elevated / moderate / limited -- from a
rule stated next to the dimension, or 'not enough evidence'. The reads are
deliberately coarse. They are not sub-scores: they cannot be summed, and a
dimension with nothing behind it says so rather than defaulting to a neutral read
a reader could mistake for a measured one (the GBCS lesson in explain.py).

EVERY CUT-OFF BELOW IS A PRIOR, NOT A FINDING. The PRIOR_* constants and the
count rules in contractual()/structure() are rules of thumb chosen by hand. None
has been fitted or checked against outcomes, and there are too few resolved
deals to do so. They decide only which of three coarse words a dimension gets;
the evidence lines are the content. Headlines therefore never quote a cut-off
("close to the deadline", not "under 60 days"), and each dimension carries a
`basis` sentence naming the rule of thumb it used, which the page shows.

This module also replaces the old "Why This Risk Band" panel (explain.py). What
that panel carried and this one did not is merged in: financing and the MAC
clause as contractual evidence, the shareholder vote as timing evidence, spread
and premium under downside. Its 'Shareholder' category had nothing extracted
behind it and is gone rather than carried as a permanent empty row.

Limits stated on the page rather than hidden:
  * The full list of approvals a deal requires is not extracted. The regulatory
    dimension reports what filings say HAPPENED, and never infers that anything
    not mentioned is complete.
  * Premium is the filing's stated figure when there is one, otherwise computed
    against the modeled break price, exactly as the deal page shows it, and is
    labelled which.
"""
import json
import re
from datetime import date, datetime

ELEVATED = 'elevated'
MODERATE = 'moderate'
LIMITED = 'limited'
NONE = 'not enough evidence'

# PRIORS, NOT FINDINGS (see the module docstring). Hand-chosen; unvalidated.
PRIOR_SEVERE_DOWNSIDE_PCT = -30.0   # mirrors main.SEVERE_DOWNSIDE_PCT, itself "one
                                    # day's book, not a statistically fit boundary"
PRIOR_MODEST_DOWNSIDE_PCT = -10.0   # ours, with nothing behind it
PRIOR_NEAR_DEADLINE_DAYS = 60       # "close enough to matter"; carried over from explain.py
PRIOR_RUNWAY_DAYS = 180             # "plenty of runway"; ours
PRIOR_STRUCTURE_ELEVATED_AT = 3     # stacked contingent features; ours

_CLEARS_ANTITRUST = ('hsr_expired', 'agency_review_closed')
_REGULATORY_TYPES = ('hsr_expired', 'agency_review_closed', 'cfius_clearance',
                     'reg_approval', 'second_request', 'approval_suspended',
                     'regulatory_delay', 'hsr_refiled')
_UNRESOLVED_CANDIDATES = ('second_request', 'approval_suspended', 'regulatory_delay')


# ── small helpers ────────────────────────────────────────────────────────────
def _obj(v):
    """A dict from a dict or its JSON/repr round-trip; {} otherwise."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            o = json.loads(v)
            return o if isinstance(o, dict) else {}
        except Exception:
            return {}
    return {}


def _money(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if x >= 1e9:
        return '$%.1fB' % (x / 1e9)
    if x >= 1e6:
        return '$%.0fM' % (x / 1e6)
    return '$%s' % format(round(x), ',')


def _ev(text, source, quote=None, url=None):
    return {'text': text, 'source': source, 'quote': quote or None, 'url': url or None}


def _dim(key, title, read, headline, evidence, gaps=None, basis=None):
    evidence = [e for e in evidence if e]
    if not evidence:
        read = NONE                       # no read without evidence
    if read == NONE and not headline:
        headline = 'Not enough evidence to say.'
    return {'key': key, 'title': title, 'read': read, 'headline': headline,
            'evidence': evidence, 'gaps': [g for g in (gaps or []) if g],
            'basis': basis if read != NONE else None}


def _regs(e):
    return {r.strip() for r in (e.get('regulator') or '').split(';') if r.strip()}


def _ms_source(e):
    return {'text': '%s %s' % (e.get('form', 'filing'), e.get('accession', '')),
            'url': e.get('url')}


def _milestone_ev(text, e):
    src = _ms_source(e)
    return _ev(text, 'milestone · ' + src['text'].strip(), e.get('quote'), src['url'])


# ── REGULATORY ───────────────────────────────────────────────────────────────
def _unresolved(events):
    """Adverse regulatory events with nothing later that answers them. A
    suspension is answered only by a LATER approval from the SAME regulator --
    IMXI's NYDFS approval does not answer California's DFPI suspension."""
    out = []
    for e in events:
        if e.get('type') not in _UNRESOLVED_CANDIDATES:
            continue
        later = [x for x in events if x.get('date', '') > e.get('date', '')]
        answered = False
        for x in later:
            if x['type'] in _CLEARS_ANTITRUST + ('cfius_clearance',) and e['type'] != 'approval_suspended':
                answered = True
            elif x['type'] == 'reg_approval' and (_regs(e) & _regs(x)):
                answered = True
        if not answered:
            out.append(e)
    return out


def regulatory(deal, events, ms_status, ms_notes):
    if ms_status != 'ready':
        return _dim('regulatory', 'Regulatory', NONE,
                    'Filing timeline is still being read.', [],
                    ['The regulatory read comes from the milestone timeline, which '
                     'is built from EDGAR in the background (up to a minute on first open).'])
    ev_all = [e for e in (events or []) if e.get('type') in _REGULATORY_TYPES]
    gaps = ['The full list of approvals this deal requires is not extracted. '
            'Only events reported in filings appear, and an approval not '
            'mentioned is not assumed complete.']
    for n in ms_notes or []:
        if n.startswith('acquirer not scanned'):
            gaps.append("The acquirer's filings were not read (%s), so approvals "
                        "reported only there would not show." % n.split(': ', 1)[-1])
        elif 'could not be read' in n:
            gaps.append('Some filings could not be read, so this may be incomplete.')
    open_ = _unresolved(ev_all)
    open_ids = {id(e) for e in open_}
    lines = []
    for e in sorted(ev_all, key=lambda x: x['date'], reverse=True):
        reg = ' — %s' % e['regulator'] if e.get('regulator') else ''
        if id(e) in open_ids:
            tail = {'second_request': 'no clearance found in the filings read',
                    'approval_suspended': 'no later approval from this regulator found',
                    'regulatory_delay': 'no later resumption found'}[e['type']]
            lines.append(_milestone_ev('%s%s, %s: %s.' % (e['label'], reg, e['date'], tail), e))
        else:
            lines.append(_milestone_ev('%s%s, %s.' % (e['label'], reg, e['date']), e))
    rt = deal.get('reg_tags')
    if isinstance(rt, str):
        try:
            rt = json.loads(rt)
        except Exception:
            rt = []
    if not lines:
        tags = ['%s (%s)' % (t.get('agency', '?'), t.get('level', '?')) for t in (rt or [])]
        if tags:
            lines.append(_ev('Expected review path: %s. This is a prior from deal '
                             'size and sector, not filed regulatory status.' % ', '.join(tags),
                             'prior (deal size / sector)'))
            return _dim('regulatory', 'Regulatory', NONE,
                        'No regulatory events found in filings since announcement; '
                        'status unknown.', [], gaps + [lines[0]['text']])
        return _dim('regulatory', 'Regulatory', NONE,
                    'No regulatory events found in filings since announcement.', [], gaps)
    if open_:
        read = ELEVATED
        head = '%d open: %s.' % (len(open_), '; '.join(
            '%s%s' % (e['label'].lower(), ' (%s)' % e['regulator'] if e.get('regulator') else '')
            for e in open_))
    elif any(e['type'] in _CLEARS_ANTITRUST for e in ev_all):
        read = LIMITED
        head = 'US antitrust review reported closed; nothing adverse outstanding in filings.'
    else:
        read = MODERATE
        head = 'Approvals reported, but no antitrust clearance found in filings.'
    return _dim('regulatory', 'Regulatory', read, head, lines, gaps)


# ── CONTRACTUAL PROTECTION ───────────────────────────────────────────────────
def _term(commitment, *needles):
    for t in (commitment.get('terms') or []):
        if any(n in str(t.get('term', '')).lower() for n in needles):
            return t
    return None


_NON_EVIDENCE = ('no financing language found', 'no text', 'not found',
                 'no language found', 'nothing found')


def _financing_lines(deal, c):
    """Financing as EVIDENCE. It does not enter the read: the read rests on the
    three terms the agreement states outright, and a press-release inference
    must never be tallied beside a contract clause."""
    fin = _term(c, 'financ')
    m = str((fin or {}).get('meaning') or '')
    if m and not any(n in m.lower() for n in _NON_EVIDENCE):
        return [_ev(m[0].upper() + m[1:] + '.', 'merger agreement', fin.get('quote'))]
    sig = deal.get('financing_signal') or 'unknown'
    where = {'filed_disclosure': "the 8-K's own description of the agreement",
             'press_release': 'the press release'}.get(deal.get('financing_source') or 'press_release',
                                                       'the filing')
    line = {'committed': 'describes committed financing, or no financing condition',
            'contingent': 'suggests closing is conditioned on financing not yet drawn',
            'confident': 'a highly confident letter, which is not a commitment'}.get(sig)
    if not line:
        return []
    return [_ev('Financing: %s %s. The agreement itself was read and states nothing this '
                'parser could find, so this is a weaker source and an absence of evidence '
                'in the contract, not proof of its terms.' % (where, line),
                'inference · ' + where)]


def contractual(deal):
    c = _obj(deal.get('commitment'))
    if not c or not deal.get('agreement_read', True):
        return _dim('contractual', 'Contractual protection', NONE,
                    'The merger agreement was not read for this deal.', [])
    anti, spf = _term(c, 'antitrust'), _term(c, 'specific performance')
    rtf = _term(c, 'reverse termination')
    fees = c.get('fees') or {}
    src = 'merger agreement'
    lines = []
    if fees.get('reverse_fee') is not None:
        t = 'Reverse termination fee %s' % _money(fees['reverse_fee'])
        if fees.get('reverse_fee_pct') is not None:
            t += ', %.1f%% of deal value' % fees['reverse_fee_pct']
        if fees.get('asymmetry'):
            t += '; %.1fx the fee the target would pay' % fees['asymmetry']
        lines.append(_ev(t + '.', src, (rtf or {}).get('quote')))
    elif rtf and rtf.get('meaning'):
        lines.append(_ev(rtf['meaning'], src, rtf.get('quote')))
    for tm in (anti, spf):
        if tm and tm.get('meaning'):
            lines.append(_ev(tm['meaning'][0].upper() + tm['meaning'][1:] + '.', src, tm.get('quote')))
    if not lines:
        return _dim('contractual', 'Contractual protection', NONE,
                    'No commitment terms were extracted.', [])
    lines += _financing_lines(deal, c)
    tally = {}
    for t in (anti, spf, rtf):
        v = str((t or {}).get('verdict', '')).upper()
        if v in ('STRONG', 'MODERATE', 'WEAK'):
            tally[v] = tally.get(v, 0) + 1
    weak, mid, strong = tally.get('WEAK', 0), tally.get('MODERATE', 0), tally.get('STRONG', 0)
    # PRIOR: a rule of thumb, not a finding. Only a unanimous set of terms reads
    # as elevated or limited; anything mixed, or resting on the middle rung of
    # the efforts ladder, reads moderate.
    if not (weak or mid or strong):
        read, head = NONE, 'Terms found but none settles buyer commitment.'
    elif weak and not (strong or mid):
        read, head = ELEVATED, 'The terms read leave the buyer room to walk.'
    elif strong and not (weak or mid):
        read, head = LIMITED, 'The terms read bind the buyer to close.'
    else:
        read, head = MODERATE, 'Mixed: some terms bind the buyer, others leave room.'
    return _dim('contractual', 'Contractual protection', read, head, lines, basis=
                'Rule of thumb: only terms that all point the same way read elevated or '
                'limited. The reverse-fee size is shown, not graded.')


# ── DEAL STRUCTURE ───────────────────────────────────────────────────────────
def structure(deal):
    lines, feats = [], 0
    dt = deal.get('deal_type')
    pr = _obj(deal.get('pricing'))
    flags = deal.get('flags') or []
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except Exception:
            flags = []
    names = {f.get('flag') for f in flags if isinstance(f, dict)}
    if not dt and not flags and not pr:
        return _dim('structure', 'Deal structure', NONE, 'Consideration was not read.', [])
    if pr.get('blended') is not None and deal.get('dp'):
        feats += 1
        gap = (float(pr['blended']) / float(deal['dp']) - 1) * 100
        lines.append(_ev('Headline $%.2f; blended value today $%.2f (%+.1f%%). %s. Spread is '
                         'measured off the blended figure.' % (
                             float(deal['dp']), pr['blended'], gap, pr.get('explanation', '').rstrip('.')),
                         'pricing reading · acquirer price %s' % str(pr.get('acquirer_price_at', ''))[:10]))
    elif dt in ('All Cash', 'Tender Offer') and deal.get('dp'):
        lines.append(_ev('All cash at $%.2f per share; the payout does not move with any '
                         'market price.' % float(deal['dp']), 'deal record'))
    elif dt:
        lines.append(_ev('Deal type: %s; no blended pricing available.' % dt, 'deal record'))
    for f in flags:
        if not isinstance(f, dict):
            continue
        if f.get('flag') in ('ELECTION', 'CVR', 'COLLAR'):
            feats += 1
        lines.append(_ev('%s — %s' % (f.get('flag'), f.get('meaning', '')), 'agreement text',
                         f.get('context')))
    if not (names & {'ELECTION', 'CVR', 'COLLAR'}) and pr.get('blended') is None and dt and 'Stock' in dt:
        feats += 1     # a stock leg with no priced reading is still a stock leg
    # PRIOR (not a finding): a count of features that make the payout depend on
    # something other than a fixed cash price. None, some, or several stacked.
    if feats == 0:
        read, head = LIMITED, 'Simple consideration: fixed cash, no contingent component.'
    elif feats < PRIOR_STRUCTURE_ELEVATED_AT:
        read, head = MODERATE, 'Part of the value depends on something other than the cash price.'
    else:
        read, head = ELEVATED, 'Several contingent features stack: what a holder receives is hard to state.'
    return _dim('structure', 'Deal structure', read, head, lines, basis=
                'Rule of thumb: counts features that make the payout depend on more than a '
                'fixed cash price (stock leg, election, CVR, collar). The count is a prior.')


# ── TIMING ───────────────────────────────────────────────────────────────────
def _guidance_passed(close_date, today):
    """True only for a plain 'Qn YYYY' / 'third quarter of YYYY' that has ended."""
    s = re.sub(r'\s+', ' ', str(close_date or '')).lower()
    q = re.search(r'\bq([1-4])\s*(20\d\d)\b', s)
    if not q:
        w = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}
        m = re.search(r'\b(first|second|third|fourth) quarter of (20\d\d)\b', s)
        if not m:
            return False
        q = (str(w[m.group(1)]), m.group(2))
    else:
        q = (q.group(1), q.group(2))
    end_month = int(q[0]) * 3
    ends = date(int(q[1]) + (end_month == 12), end_month % 12 + 1, 1)
    return ends <= today


def timing(deal, events, closing_signal, today=None):
    today = today or date.today()
    od = _obj(deal.get('outside_date'))
    lines, read, head = [], None, None
    if od.get('date'):
        when = od.get('display') or od['date']
        src = 'outside-date reading'
        q = od.get('quote')
        if od.get('passed'):
            if closing_signal:
                lines.append(_ev('The outside date (%s) has passed, but a completion filing is on '
                                 'record: the clock no longer runs against this deal.' % when, src, q))
                read, head = LIMITED, 'Deadline passed because the deal is closing, not stalling.'
            else:
                lines.append(_ev('The outside date (%s) has passed with no completion filing on '
                                 'record. Either party may now walk without paying a break fee.' % when,
                                 src, q))
                read, head = ELEVATED, 'Past the contractual deadline.'
        else:
            n = od.get('days_remaining')
            lines.append(_ev('%s days to the outside date (%s).' % (n, when), src, q))
            et = od.get('extension_type')
            if et == 'automatic':
                lines.append(_ev('The date extends automatically if regulatory conditions are '
                                 'unmet, so it is a floor on the schedule, not a ceiling.', src))
            elif et == 'elective':
                to = od.get('extension_date')
                lines.append(_ev('Either party may elect to extend%s.' % (' to ' + to if to else ''), src))
            elif od.get('extendable') is False:
                lines.append(_ev('Fixed: the agreement gives no extension.', src))
    exts = [e for e in (events or []) if e.get('type') == 'outside_date_extended']
    if exts:
        for e in exts:
            lines.append(_milestone_ev('Outside date extended, %s.' % e['date'], e))
    elif od.get('date'):
        lines.append(_ev('No extension found in the filings read.', 'milestone timeline'))
    for e in sorted((x for x in (events or []) if x.get('type') in
                     ('vote_passed', 'vote_failed', 'vote_held', 'vote_scheduled')),
                    key=lambda x: x['date'], reverse=True)[:1]:
        lines.append(_milestone_ev('%s, %s.' % (e['label'], e['date']), e))
    cd = deal.get('close_date')
    if cd and cd != 'TBD':
        cd1 = re.sub(r'\s+', ' ', str(cd))
        if _guidance_passed(cd1, today):
            lines.append(_ev('Company guidance was "%s"; that window has ended and the deal '
                             'has not closed.' % cd1, 'company guidance'))
            guided_late = True
        else:
            lines.append(_ev('Company guidance: %s.' % cd1, 'company guidance'))
            guided_late = False
    else:
        guided_late = False
    if read is None and od.get('date'):
        n = od.get('days_remaining')
        if exts:
            read, head = ELEVATED, 'The outside date has already been extended.'
        elif n is not None and n <= PRIOR_NEAR_DEADLINE_DAYS:
            read, head = ELEVATED, 'The deadline is close.'
        elif guided_late or (n is not None and n <= PRIOR_RUNWAY_DAYS):
            read = MODERATE
            head = ('Running behind company guidance.' if guided_late
                    else 'The deadline is within a few months.')
        else:
            read, head = LIMITED, 'Plenty of runway, no extension, guidance intact.'
    return _dim('timing', 'Timing', read or NONE, head, lines,
                [] if od.get('date') else ['No outside date could be read from the agreement.'],
                basis='Rule of thumb on days to the deadline, whether it has already moved, '
                      'and whether company guidance has lapsed. The day cut-offs are priors.')


# ── DOWNSIDE ─────────────────────────────────────────────────────────────────
def _premium(deal):
    """(pct, basis_text, source) -- the filing's stated premium when there is one,
    otherwise computed against the modeled break price, exactly as the deal
    page's own _daPremium does. None when neither is available."""
    p = deal.get('premium')
    if isinstance(p, dict) and p.get('value') is not None:
        return float(p['value']), 'stated in the filing', 'filing'
    bp, dp = deal.get('break_price'), deal.get('dp')
    try:
        bp, dp = float(bp), float(dp)
    except (TypeError, ValueError):
        return None
    if not bp > 0:
        return None
    return (dp - bp) / bp * 100, 'computed against the modeled break price', 'computed'


def downside(deal):
    bp, bd, cp = deal.get('break_price'), deal.get('break_downside'), deal.get('cp')
    if bp is None or bd is None:
        return _dim('downside', 'Downside', NONE, 'No break price could be anchored.', [],
                    ['The break price needs a clean pre-announcement price.'])
    lines = [_ev('If the deal breaks, the pre-announcement price of $%.2f is the anchor, '
                 '%.1f%% from $%.2f today.' % (bp, bd, cp) if cp else
                 'Break price $%.2f (%.1f%% from today).' % (bp, bd),
                 'price data · %s' % (deal.get('break_price_method') or 'pre-announcement close'))]
    b = _obj(deal.get('break_price_band'))
    if b.get('lo90') is not None and b.get('hi90') is not None:
        lines.append(_ev('The 90 trading days before announcement ranged $%.2f–$%.2f.' % (
            b['lo90'], b['hi90']), 'price data'))
    if deal.get('sp_pct') is not None and cp:
        lines.append(_ev('Gross spread to the deal price is %.1f%% against %.1f%% downside.' % (
            deal['sp_pct'], abs(bd)), 'deal record'))
    pm = _premium(deal)
    if pm:
        lines.append(_ev('Offer premium %+.1f%% (%s). A premium measures standalone '
                         'valuation and how motivated holders are to vote yes; it is not '
                         'evidence the deal closes.' % (pm[0], pm[1]), 'price data'))
    # PRIOR (not a finding): how far the stock could fall, in three coarse bands.
    if bd <= PRIOR_SEVERE_DOWNSIDE_PCT:
        read, head = ELEVATED, "A break would cost a large share of today's price."
    elif bd <= PRIOR_MODEST_DOWNSIDE_PCT:
        read, head = MODERATE, "A break would cost a meaningful share of today's price."
    else:
        read, head = LIMITED, "A break would cost little relative to today's price."
    return _dim('downside', 'Downside', read, head, lines, basis=
                'Rule of thumb on the distance to the break price. The band edges are priors, '
                'and the break price itself is an estimate from pre-announcement trading.')


# ── assembly ─────────────────────────────────────────────────────────────────
def risk_breakdown(deal, timeline=None, ms_status='ready', closing_signal=False, today=None):
    """`timeline` is milestone_events' payload ({events, notes, ...}) or None."""
    deal = deal or {}
    tl = timeline or {}
    events = tl.get('events') or []
    return {'band': deal.get('risk'),
            'dimensions': [
                regulatory(deal, events, ms_status, tl.get('notes')),
                contractual(deal),
                structure(deal),
                timing(deal, events, closing_signal, today),
                downside(deal)]}
