"""
DATA INTEGRITY SWEEP — everything a human would question, named out loud

WHY THIS EXISTS

  Nine real defects were found in the feed over one week. Seven of them were
  silent: nothing crashed, nothing logged, and every value looked like a number
  a merger-arb screen would print.

    GSAT      blended pricing computed, barriers passed, never persisted
    19 deals  commitment and outside-date readings dropped by a failed write
    CBZ       tx_value 60.0 on a $2.98B company, labelled regex_enterprise
    GSAT      acquirer_type Private Equity, acquirer Amazon
    BWMN      close_date Q2 2026 on a deal announced six weeks later
    ATKR      close_date from "fiscal 2026" in a document with no guidance
    GBCS      outside date discarded on the day the deadline arrived

  Each was found by someone looking, not by the system saying anything. This
  sweep is the system saying something.

WHAT IT IS NOT

  Not a gate. Nothing here blocks a deal, changes a value, or fails a scan. It
  reads the feed after it is written and prints what it would question, with the
  deal and the value attached, so the output reads like a QA pass rather than a
  pass/fail. A finding is a question, and some will have good answers.

  Not a test suite either. Tests assert what must be true of code. This asserts
  what is usually true of DATA, which is a weaker and more useful claim: it
  flags the unusual and leaves the judgement to a reader.
"""

import re
from collections import namedtuple
from datetime import datetime, date

Finding = namedtuple('Finding', 'ticker check detail')

# A field present on this share of the feed is expected on all of it.
#
# 0.85 rather than 0.90 because the feed is small: at nineteen deals, 17 of 19
# is 89.5% and would slip under a 0.90 bar, which is exactly the case worth
# catching -- two deals missing an outside date the other seventeen have. The
# finding prints the ratio either way, so a reader can discount it.
UBIQUITY_THRESHOLD = 0.85

# Structured fields worth checking for self-contradiction. Emptiness alone is
# NOT a finding here: /api/deals runs every one of these through
# parse_structured, which turns an absent value into {}, so "present but empty"
# describes most of the feed most of the time and would drown the report. Which
# deals ought to have a populated one is the ubiquity check's job.
STRUCTURED_FIELDS = ('pricing', 'commitment', 'outside_date', 'direction', 'gate')


def _populated(v):
    """Whether a field carries anything. {} and [] are absence, not presence."""
    if v is None or v == '' or v == 'TBD':
        return False
    if isinstance(v, (dict, list, tuple, set)) and not v:
        return False
    try:
        f = float(v)
        if f != f:                       # NaN
            return False
    except (TypeError, ValueError):
        pass
    return True


def _num(v):
    try:
        f = float(v)
        return None if f != f else f          # NaN is not a number here
    except (TypeError, ValueError):
        return None


def _struct(v, parse_structured):
    """A structured field as a dict, however the cache round-tripped it."""
    try:
        d = parse_structured(v or {})
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def sweep(deals, main):
    """
    Every question worth asking of the current feed.

    `main` is the main module, passed in rather than imported, so this file
    stays importable on its own and the validators keep one definition each --
    a rule that disagrees with the one the scan enforces is worse than no rule.
    """
    out = []
    deals = [d for d in (deals or []) if d.get('ticker')]
    if not deals:
        return out

    # ── field ubiquity, computed across the feed before anything else ───────
    counts = {}
    for d in deals:
        for k, v in d.items():
            if k.startswith('_'):
                continue
            if not _populated(v):
                continue
            counts[k] = counts.get(k, 0) + 1
    ubiquitous = {k for k, n in counts.items() if n / len(deals) >= UBIQUITY_THRESHOLD}

    for d in deals:
        tk = d.get('ticker')
        cp, dp = _num(d.get('cp')), _num(d.get('dp'))
        filed = d.get('filed')
        text = d.get('_filing_text') or ''

        # ── 1 · transaction value against this company, not against a range ─
        tx = _num(d.get('tx_value'))
        if tx is not None and dp:
            ok, why = main.tx_value_plausible(tx, dp, tk)
            if not ok:
                out.append(Finding(tk, 'tx_value', why))

        # ── 2 · the spread, and whether it agrees with its own inputs ───────
        sp = _num(d.get('sp_pct'))
        if sp is not None and not (-3 <= sp <= 60):
            out.append(Finding(tk, 'spread',
                               f'{sp}% is outside the -3%..60% band the scan gate enforces'))
        if sp is not None and cp and dp:
            blended = main.blended_governs(d)
            basis = blended if blended is not None else dp
            expect = round(((basis - cp) / cp) * 100, 2)
            if abs(sp - expect) > 0.1:
                src = 'blended' if blended is not None else 'deal price'
                out.append(Finding(tk, 'spread',
                                   f'sp_pct {sp} does not follow from cp {cp} and '
                                   f'the {src} {basis} (would be {expect})'))

        # ── 3 · the close date, by the same rule the scan applies ───────────
        cd = d.get('close_date')
        if cd and cd != 'TBD':
            ok, why = main.validate_close_date(cd, filed)
            if not ok:
                out.append(Finding(tk, 'close_date', f'{cd!r}: {why}'))

        # ── 4 · the outside date cannot precede the agreement ───────────────
        od = _struct(d.get('outside_date'), main.parse_structured)
        if od.get('date') and filed:
            odd = main.parse_close_date(od['date'])
            fd = main.parse_close_date(filed)
            if odd and fd and odd < fd:
                out.append(Finding(tk, 'outside_date',
                                   f"{od['date']} precedes the {filed} announcement"))
            elif odd and od.get('passed'):
                out.append(Finding(tk, 'outside_date',
                                   f"{od['date']} has PASSED "
                                   f"({abs(od.get('days_remaining') or 0)} days ago) — "
                                   f"either party may now walk without a break fee"))

        # ── 5 · the break price against the two prices that bound it ────────
        bp = _num(d.get('break_price'))
        if bp is not None and cp and dp:
            ok, why = main.two_state_applies(cp, dp, bp)
            if not ok:
                out.append(Finding(tk, 'break_price',
                                   f'{bp} vs current {cp} and deal {dp}: {why}'))

        # ── 5b · a buyer paying nothing over market ─────────────────────────
        # Three different things look like this and all three are worth a
        # question: a genuine no-premium deal, a wrong deal price, or a break
        # price that has absorbed the run-up it was supposed to exclude. BZH is
        # the live case at 0.1%, and none of the other checks would have caught
        # it -- its spread, close date and tx_value are all unremarkable.
        pm = _struct(d.get('premium'), main.parse_structured)
        pv = _num(pm.get('value')) if pm else None
        if pv is None and bp and dp and bp > 0:
            pv = round(((dp - bp) / bp) * 100, 1)          # sweep the feed as it is
        if pv is not None and pv < main.PREMIUM_THIN_PCT:
            basis = pm.get('basis', 'computed') if pm else 'computed'
            out.append(Finding(tk, 'premium',
                               f'{pv}% ({basis}) — the buyer is paying at or barely '
                               f'above market. Either a genuine no-premium deal, a '
                               f'wrong deal price, or a break price that absorbed '
                               f'the run-up'))

        # ── 6 · deal_type against what the filing actually describes ────────
        dt = d.get('deal_type')
        if dt and text:
            low = text.lower()
            if dt == 'Tender Offer' and 'tender offer' not in low:
                out.append(Finding(tk, 'deal_type',
                                   "typed Tender Offer, but the filing never says "
                                   "'tender offer'"))
            if dt == 'All Cash' and 'per share in cash' not in low \
                    and 'per common share in cash' not in low:
                out.append(Finding(tk, 'deal_type',
                                   "typed All Cash, but the filing never says "
                                   "'per share in cash'"))
        # An acquirer type is read from the acquirer; disagreeing with the
        # function that decides it means something wrote it by another route.
        at = d.get('acquirer_type')
        if at and d.get('acquirer'):
            want = main.get_acquirer_type(dt, d.get('acquirer'))
            if at != want:
                out.append(Finding(tk, 'acquirer_type',
                                   f'{at!r} stored, but {d.get("acquirer")!r} reads '
                                   f'as {want!r}'))

        # ── 7 · the acquirer has to appear in the filing it came from ───────
        acq = d.get('acquirer')
        if acq and acq != 'Undisclosed' and text:
            ok, why = main.validate_enriched_acquirer(acq, text, d.get('company', ''))
            if not ok:
                out.append(Finding(tk, 'acquirer', why))

        # ── 8 · a structured field that contradicts itself ─────────────────
        # Emptiness is left to the ubiquity check; what is caught here is a
        # field that is populated and disagrees with its own contents.
        for f in STRUCTURED_FIELDS:
            st = _struct(d.get(f), main.parse_structured)
            if not st:
                continue
            if f == 'pricing' and st.get('all_passed') and st.get('blended') is None:
                out.append(Finding(tk, 'pricing',
                                   'every barrier passed but blended is None'))
            if f == 'outside_date' and not st.get('date'):
                out.append(Finding(tk, 'outside_date',
                                   'populated but names no date'))
            if f == 'commitment' and st.get('terms') is not None and not st['terms']:
                out.append(Finding(tk, 'commitment', 'populated but names no terms'))
        # A deal with a hand-verified structure must carry a blended price.
        # main owns this rule; calling it keeps one definition.
        for _t, _why in main.pricing_integrity_failures([d]):
            out.append(Finding(_t, 'pricing', _why))

        # ── 9 · a provenance label that disagrees with the record ───────────
        for label, field, table, name in (
                ('tx_value_source', 'tx_value', main.VERIFIED_TX_VALUES, 'verified_hardcode'),
                ('break_price_method', 'break_price', main.VERIFIED_UNAFFECTED_PRICES,
                 'verified_unaffected')):
            lab = d.get(label)
            if lab == name and tk not in table:
                out.append(Finding(tk, label,
                                   f'claims {name!r} but {tk} is not in the verified table'))
            if lab and lab != name and tk in table:
                out.append(Finding(tk, label,
                                   f'reads {lab!r} while {tk} IS in the verified table — '
                                   f'the hardcode should have won'))
        if _num(d.get('tx_value')) is not None and not d.get('tx_value_source'):
            out.append(Finding(tk, 'tx_value_source',
                               f'tx_value {d.get("tx_value")} carries no provenance label'))
        if d.get('close_date_source') and d.get('close_date') in (None, '', 'TBD'):
            out.append(Finding(tk, 'close_date_source',
                               f'labelled {d["close_date_source"]!r} with no close date'))

        # ── 10 · missing what almost every other deal has ───────────────────
        for f in sorted(ubiquitous):
            if not _populated(d.get(f)):
                out.append(Finding(tk, f, f'absent, though {counts[f]} of {len(deals)} '
                                          f'deals carry it'))

    return out


def report(findings, deals):
    """(header, lines) for printing. Groups by deal, quietest thing first."""
    n = len(deals or [])
    if not findings:
        return (f"[Integrity] {n} deal(s) swept, nothing to question", [])
    by_deal = {}
    for f in findings:
        by_deal.setdefault(f.ticker, []).append(f)
    lines = []
    for tk in sorted(by_deal):
        lines.append(f"  {tk}")
        for f in by_deal[tk]:
            lines.append(f"      {f.check:20} {f.detail}")
    header = (f"[Integrity] {len(findings)} question(s) across "
              f"{len(by_deal)} of {n} deal(s) — reported, nothing blocked")
    return header, lines
