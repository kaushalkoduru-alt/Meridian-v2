"""
Section 9: explainable risk, not eight weighted sub-scores.

The original prompt asked for eight weighted categories. It also asked for no
fake precision. Those conflict, and the data settles it: 39 verified deals with
4 failures cannot validate the six factors the score already has, let alone
eight. A number per category would fit noise harder and in more detail, and it
would read as a measurement because it is written as one.

So each category returns EVIDENCE and a verdict in words. Where there is no
evidence it says so, in the category's own row, rather than defaulting to a
neutral-looking score a reader cannot distinguish from a measured one.

"Regulatory: weak antitrust covenant, $7B reverse termination fee" --
not "Regulatory: 68".

Two rules hold this honest:

  1. **No verdict without evidence.** A category with nothing behind it returns
     'insufficient evidence' and shows no verdict at all. GBCS briefly rendered
     "Contractual protection: weak" with an empty evidence list, which is the
     precise failure this section exists to prevent -- a judgement that looks
     measured and cites nothing.
  2. **Every row is labelled with its provenance**, so a covenant quoted from
     the agreement is never mistaken for a prior computed from deal size.

Nothing here feeds the score. This is the explanation of a position, not a
second scoring engine wearing different clothes.
"""

import json

import provenance as P

STRONG = 'strong'
WEAK = 'weak'
NEUTRAL = 'mixed'
NONE = 'insufficient evidence'
# Evidence exists but does not settle the question. Distinct from NONE, because
# "we found the clause and it is silent" and "we found nothing" are different
# things to tell a reader, and collapsing them hides which one happened.
OPEN = 'evidence, no verdict'

# A term whose 'meaning' is a statement that nothing was found is NOT evidence.
# SLAB rendered "Financing: strong" whose single supporting line read "no
# financing language found" -- a verdict contradicting its own citation.
_NON_EVIDENCE = ('no financing language found', 'no text', 'not found',
                 'no language found', 'nothing found')

CATEGORIES = ['Contractual protection', 'Financing', 'Regulatory', 'Timing',
              'Consideration', 'Legal', 'Shareholder', 'Market']


def _terms(commitment):
    if isinstance(commitment, str):
        try:
            commitment = json.loads(commitment)
        except Exception:
            return []
    if not isinstance(commitment, dict):
        return []
    return commitment.get('terms') or []


def _find(commitment, *needles):
    for t in _terms(commitment):
        name = str(t.get('term', '')).lower()
        if any(nd in name for nd in needles):
            return t
    return None


def _ev(term):
    """
    The evidence for one agreement term as {text, quote}.

    The meaning and the quoted language are returned SEPARATELY rather than
    concatenated, so the page can show the claim and keep the filing language
    one click away. Concatenating them forced every consumer to render the
    whole thing or none of it, which is how five quote blocks ended up stacked
    down one page.

    An evidence item is either a plain string or this dict; both are truthy and
    `_row` treats them the same.
    """
    if not term or not term.get('meaning'):
        return None
    m = str(term['meaning'])
    if any(nd in m.lower() for nd in _NON_EVIDENCE):
        return None
    return {'text': m, 'quote': term.get('quote') or None}


def _verdict(*terms):
    """A verdict only from terms that actually said something."""
    vs = [str(t.get('verdict', '')).upper() for t in terms if t]
    vs = [v for v in vs if v in ('STRONG', 'WEAK')]
    if not vs:
        return None
    if 'WEAK' in vs and 'STRONG' in vs:
        return NEUTRAL
    return STRONG if 'STRONG' in vs else WEAK


def _row(cat, verdict, evidence, prov):
    # Rule 1, enforced in one place rather than trusted to each branch.
    evidence = [e for e in evidence if e]
    if not evidence:
        verdict = NONE          # rule 1: no verdict without evidence
    elif not verdict:
        verdict = OPEN          # and no 'nothing found' while citing something
    return {'category': cat, 'verdict': verdict or NONE,
            'evidence': evidence, 'provenance': prov,
            'provenance_label': P.CLASSES[prov][0]}


def explain_deal(deal):
    """A list of category rows. No numbers, no weights, no composite."""
    deal = deal or {}
    c = deal.get('commitment')
    rows = []

    # ---- contractual protection -------------------------------------------
    rtf = _find(c, 'reverse termination', 'reverse fee')
    spf = _find(c, 'specific performance')
    rows.append(_row('Contractual protection', _verdict(rtf, spf),
                     [_ev(rtf), _ev(spf)], P.FACT))

    # ---- financing ---------------------------------------------------------
    fin = _find(c, 'financ')
    sig = deal.get('financing_signal') or 'unknown'
    src = deal.get('financing_source') or 'press_release'
    agreed = _ev(fin)
    v = _verdict(fin)
    if agreed and v:
        # The agreement answered it. Strongest case, and the only FACT case.
        rows.append(_row('Financing', v, [agreed], P.FACT))
    else:
        # The agreement was silent or unread, so whatever a weaker document
        # says is an INFERENCE and is labelled as one. It never inherits the
        # agreement's authority just because a term object existed.
        _where = {'filed_disclosure': 'the 8-K Item 1.01 body — the '
                                      'registrant’s filed description of the '
                                      'agreement',
                  'press_release': 'the press release'}.get(src, 'the filing')
        line = {'committed': '%s describes committed financing, or states '
                             'there is no financing condition',
                'contingent': '%s suggests closing is conditioned on '
                              'financing not yet drawn',
                'confident': 'a highly confident letter, which is not a '
                             'commitment (%s)'}.get(sig)
        if line:
            line = line % _where
        extra = []
        if line and deal.get('agreement_read'):
            # Shown, not scored. And the reason is stated as OUR limit, never
            # as a finding about the deal: four pattern defects in two sessions
            # have each produced confident silence, and a fifth would turn a
            # parser gap into a contractual fact.
            extra.append('the merger agreement was read and states nothing '
                         'this parser could find, so the above is reported '
                         'but does not affect the score — an absence of '
                         'evidence, not evidence the condition is absent')
        rows.append(_row('Financing',
                         {'committed': STRONG, 'contingent': WEAK,
                          'confident': NEUTRAL}.get(sig),
                         [line, agreed] + extra, P.INFERENCE))

    # ---- regulatory --------------------------------------------------------
    # The agreement's antitrust covenant is a FACT and outranks the priors; the
    # priors are still shown, and still say what they are.
    anti = _find(c, 'antitrust', 'regulatory effort', 'efforts')
    rt = deal.get('reg_tags')
    if isinstance(rt, str):
        try:
            rt = json.loads(rt)
        except Exception:
            rt = []
    ev = [_ev(anti)]
    tags = ['%s (%s)' % (t.get('agency', '?'), t.get('level', '?'))
            for t in (rt or [])]
    if tags:
        ev.append('expected review path: %s — a prior from deal size and '
                  'sector, NOT filed regulatory status' % ', '.join(tags))
    rows.append(_row('Regulatory', _verdict(anti), ev,
                     P.FACT if anti else P.INFERENCE))

    # ---- timing ------------------------------------------------------------
    od = deal.get('outside_date') or {}
    ev, v = [], None
    if od.get('date'):
        when = od.get('display') or od.get('date')
        if od.get('passed'):
            ev.append('the contractual deadline passed on %s; either party may '
                      'now walk without paying a break fee' % when)
            v = WEAK
        else:
            d = od.get('days_remaining')
            ev.append('%s days to the contractual deadline (%s)' % (d, when))
            v = WEAK if (d is not None and d <= 60) else NEUTRAL
        if od.get('extension_type') == 'automatic':
            ev.append('extends automatically if regulatory conditions are unmet')
    cd = deal.get('close_date')
    if cd and cd != 'TBD':
        ev.append('company guidance: %s' % cd)
    rows.append(_row('Timing', v, ev, P.FACT))

    # ---- consideration -----------------------------------------------------
    ev, v = [], None
    if deal.get('blended'):
        ev.append('cash and stock; the stock leg re-prices daily with the '
                  'acquirer’s shares, so the payout is not fixed')
        v = NEUTRAL
    elif deal.get('deal_type') in ('All Cash', 'Tender Offer') and deal.get('dp'):
        ev.append('all cash at $%s per share' % deal['dp'])
        v = STRONG
    rows.append(_row('Consideration', v, ev, P.FACT))

    # ---- legal (MAC) -------------------------------------------------------
    mac = _find(c, 'material adverse', 'mac')
    rows.append(_row('Legal', _verdict(mac), [_ev(mac)], P.FACT))

    # ---- shareholder -------------------------------------------------------
    # Nothing is extracted for this yet, and the row says so rather than
    # showing a neutral verdict indistinguishable from a measured one.
    rows.append(_row('Shareholder', None, [], P.INFERENCE))

    # ---- market ------------------------------------------------------------
    ev = []
    if deal.get('sp_pct') is not None:
        ev.append('spread %s%% against the last close' % deal['sp_pct'])
    prem = deal.get('deal_premium')
    if isinstance(prem, dict) and prem.get('pct') is not None:
        ev.append('premium %.1f%% (%s) — measures standalone downside and '
                  'valuation; it is NOT evidence the deal closes'
                  % (prem['pct'], prem.get('basis', 'computed')))
    rows.append(_row('Market', NEUTRAL if ev else None, ev, P.MODEL))

    return rows


def explanation_summary(rows):
    """One line: how much of the picture is actually evidenced."""
    have = sum(1 for r in rows if r['verdict'] != NONE)
    return ('%d of %d categories carry evidence; the other %d are shown as '
            'unevidenced rather than scored' % (have, len(rows), len(rows) - have))
