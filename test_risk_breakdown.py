"""Risk breakdown reads. Pure function, no network."""
from datetime import date
from risk_breakdown import risk_breakdown, _unresolved

T = date(2026, 10, 1)


def ev(typ, d, reg=None, label='x'):
    return {'type': typ, 'date': d, 'regulator': reg, 'label': label, 'adverse': False,
            'form': '8-K', 'accession': 'A', 'quote': 'q', 'url': 'u'}


def dims(deal, events=(), status='ready', closing=False):
    r = risk_breakdown(deal, {'events': list(events), 'notes': []}, status, closing, T)
    return {d['key']: d for d in r['dimensions']}


def test_suspension_not_answered_by_other_regulator():
    e = [ev('approval_suspended', '2026-08-13', 'California DFPI'),
         ev('reg_approval', '2026-08-14', 'NYDFS')]
    assert len(_unresolved(e)) == 1
    e.append(ev('reg_approval', '2026-09-01', 'California DFPI'))
    assert _unresolved(e) == []


def test_regulatory_reads():
    assert dims({}, status='pending')['regulatory']['read'] == 'not enough evidence'
    assert dims({})['regulatory']['read'] == 'not enough evidence'
    assert dims({}, [ev('second_request', '2026-03-16', 'FTC')])['regulatory']['read'] == 'elevated'
    assert dims({}, [ev('hsr_expired', '2026-03-16', 'HSR (FTC/DOJ)')])['regulatory']['read'] == 'limited'
    assert dims({}, [ev('reg_approval', '2026-03-16', 'NYDFS')])['regulatory']['read'] == 'moderate'


def test_no_evidence_no_read():
    d = dims({})
    for k in ('contractual', 'structure', 'timing', 'downside'):
        assert d[k]['read'] == 'not enough evidence' and not d[k]['evidence']


def test_timing():
    od = {'date': '2026-11-10', 'days_remaining': 46, 'passed': False, 'extension_type': 'automatic'}
    assert dims({'outside_date': od})['timing']['read'] == 'elevated'
    od = {'date': '2026-09-01', 'passed': True}
    assert dims({'outside_date': od})['timing']['read'] == 'elevated'
    assert dims({'outside_date': od}, closing=True)['timing']['read'] == 'limited'
    od = {'date': '2027-06-04', 'days_remaining': 263, 'passed': False}
    assert dims({'outside_date': od, 'close_date': 'Q3 2026'})['timing']['read'] == 'moderate'
    assert dims({'outside_date': od, 'close_date': 'Q4 2026'})['timing']['read'] == 'limited'
    assert dims({'outside_date': od}, [ev('outside_date_extended', '2026-05-01')])['timing']['read'] == 'elevated'


def test_downside_and_premium():
    d = dims({'break_price': 9.28, 'break_downside': -19.5, 'cp': 11.53, 'dp': 16.0})['downside']
    assert d['read'] == 'moderate'
    prem = [e['text'] for e in d['evidence'] if 'premium' in e['text'].lower()]
    assert prem and '+72.4%' in prem[0] and 'computed' in prem[0]
    d = dims({'break_price': 9.28, 'break_downside': -19.5, 'cp': 11.53, 'dp': 16.0,
              'premium': {'value': 30.0}})['downside']
    assert any('+30.0%' in e['text'] and 'stated in the filing' in e['text'] for e in d['evidence'])
    d = dims({'break_price': 9.28, 'break_downside': -19.5, 'cp': 11.53})['downside']   # no deal price
    assert not any('premium' in e['text'].lower() for e in d['evidence'])
    assert dims({'break_price': 1, 'break_downside': -35, 'cp': 2})['downside']['read'] == 'elevated'


def test_headlines_quote_no_cutoff():
    od = {'date': '2026-11-10', 'days_remaining': 46, 'passed': False}
    heads = [dims({'outside_date': od, 'break_price': 9, 'break_downside': -19.5, 'cp': 11})[k]['headline']
             for k in ('timing', 'downside')]
    assert not any(ch.isdigit() for h in heads for ch in h)


def test_reads_carry_a_basis_only_when_they_have_a_read():
    d = dims({})
    assert all(x['basis'] is None for x in d.values())
    od = {'date': '2027-06-04', 'days_remaining': 263, 'passed': False}
    assert 'prior' in dims({'outside_date': od})['timing']['basis'].lower()


def test_efforts_middle_rung_reads_moderate():
    c = {'terms': [{'term': 'Antitrust obligation', 'verdict': 'MODERATE', 'meaning': 'm'},
                   {'term': 'Specific performance', 'verdict': 'STRONG', 'meaning': 'm'}]}
    assert dims({'commitment': c})['contractual']['read'] == 'moderate'
    c['terms'][1]['verdict'] = 'WEAK'
    assert dims({'commitment': c})['contractual']['read'] == 'moderate'   # mixed, not elevated


def test_structure_and_contract():
    assert dims({'deal_type': 'All Cash', 'dp': 10})['structure']['read'] == 'limited'
    pr = {'blended': 9.0, 'explanation': 'e'}
    fl = [{'flag': 'ELECTION', 'meaning': 'm'}]
    assert dims({'deal_type': 'Cash + Stock', 'dp': 10, 'pricing': pr, 'flags': fl})['structure']['read'] == 'moderate'
    c = {'terms': [{'term': 'Antitrust obligation', 'verdict': 'WEAK', 'meaning': 'm'},
                   {'term': 'Specific performance', 'verdict': 'WEAK', 'meaning': 'm'}]}
    assert dims({'commitment': c})['contractual']['read'] == 'elevated'
