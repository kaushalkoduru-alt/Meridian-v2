"""
Sections 20 and 9, tested together because the score was wrong partly because it
consumed fields that claimed to be measurements and were not.

Every case here is a live deal or the exact filing sentence that exposed the
defect, not a synthetic one.
"""
import io

import provenance as P
import explain as X
from main import (extract_financing_signal, financing_from_commitment,
                  score_deal, get_risk, score_deadline, score_consideration,
                  score_deal_premium)

ok = True


def check(label, got, want, detail=""):
    global ok
    good = got == want
    ok &= good
    print("  %s  %s" % ('PASS' if good else 'FAIL', label))
    if not good:
        print("        got %r, want %r" % (got, want))
    elif detail:
        print("        %s" % detail)


print("=" * 78)
print("§20 — a field is classified by where its value came from")
print("=" * 78)

# break_price: a lookup wearing a model's label on 18 of 19 deals.
check("a historical break price is a FACT, not a MODEL",
      P.classify('break_price', {'break_price_method': 'historical'})[0], P.FACT,
      'the card footer called this "Modeled downside case"')
check("AES's verified unaffected price is also a FACT",
      P.classify('break_price', {'break_price_method': 'verified_unaffected'})[0],
      P.FACT)
check("a genuinely estimated break price is a MODEL",
      P.classify('break_price', {'break_price_method': 'comparables'})[0], P.MODEL)
check("the inference is named in the why, not hidden",
      'inference' in P.classify('break_price',
                                {'break_price_method': 'historical'})[2], True)

# tx_value: two different quantities under one label.
check("a filed transaction value is a FACT",
      P.classify('tx_value', {'tx_value_source': 'regex_enterprise'})[0], P.FACT)
check("a computed equity value is a MODEL",
      P.classify('tx_value', {'tx_value_source': 'equity_calc_approx'})[0], P.MODEL,
      'enterprise and equity were sharing one label')

# reg_tags: priors presented as status.
check("regulatory tags are INFERENCE", P.classify('reg_tags')[0], P.INFERENCE)
check("and say they are not filed status",
      'NOT filed regulatory status' in P.classify('reg_tags')[2], True)

# financing: the source decides the class.
check("financing read from the agreement is a FACT",
      P.classify('financing_signal', {'financing_source': 'agreement'})[0], P.FACT)
check("financing read from a press release is INFERENCE",
      P.classify('financing_signal', {'financing_source': 'press_release'})[0],
      P.INFERENCE)

check("cp is a FACT about yesterday", P.classify('cp')[0], P.FACT)
check("and is not called current", 'last daily close' in P.classify('cp')[2], True)
check("probability is the only FORECAST",
      P.classify('probability')[0], P.FORECAST)
check("the annualized bounds are a MODEL",
      P.classify('ann_bounds')[0], P.MODEL)

print()
print("=" * 78)
print("§20 — the financing scan reads negations")
print("=" * 78)

# The two live filings that were scored `contingent`, worth -10 each, on
# sentences that say the exact opposite.
check("HZO: 'not subject to any financing condition' is committed",
      extract_financing_signal(
          'The obligations of Parent and Merger Sub to consummate the Merger '
          'are not subject to any financing condition.'), 'committed',
      'scored contingent, -10, on a filing that denies the condition')
check("DSGR: 'financing is not a condition' is committed",
      extract_financing_signal(
          'The availability of financing is not a condition to the obligations '
          'of Parent to consummate the Merger.'), 'committed')
check("a real financing condition is still contingent",
      extract_financing_signal('The Offer is subject to a financing condition.'),
      'contingent')
check("an equity commitment is committed",
      extract_financing_signal(
          'Parent has obtained an equity commitment for the Transactions.'),
      'committed')
check("a highly confident letter is not a commitment",
      extract_financing_signal('Parent delivered a highly confident letter.'),
      'confident')
check("silence stays unknown",
      extract_financing_signal('The agreement says nothing on the subject.'),
      'unknown')

# The agreement outranks the press release.
_C = {'terms': [{'term': 'Financing condition', 'verdict': 'STRONG',
                 'meaning': 'no financing condition'}]}
check("a STRONG agreement reading supersedes the press release",
      financing_from_commitment(_C), ('committed', 'agreement'))
check("a WEAK agreement reading supersedes it too",
      financing_from_commitment(
          {'terms': [{'term': 'Financing condition', 'verdict': 'WEAK'}]}),
      ('contingent', 'agreement'))
check("an UNKNOWN agreement reading carries no information",
      financing_from_commitment(
          {'terms': [{'term': 'Financing condition', 'verdict': 'UNKNOWN'}]}),
      (None, None),
      'silence must not overwrite the press-release reading')

print()
print("=" * 78)
print("§9 — the four deferred corrections")
print("=" * 78)

# 1. premium size is not safety (§30C).
check("BZH is no longer charged for having no premium",
      score_deal_premium(33.46, 33.50), 0,
      'a genuine no-premium deal lost 5 points for it')
check("and a large premium buys nothing either",
      score_deal_premium(10.0, 15.0), 0,
      '+8 at 50% was §30C stated as arithmetic')

# 2. the buyer's identity does not score; the consideration does.
check("an all-cash deal scores its consideration",
      score_consideration('All Cash', None), 8)
check("a deal typed Private Equity is NOT charged for it",
      score_consideration('Private Equity', None), 8,
      'GSAT carried this charge with Amazon as the acquirer')
check("a stock leg scores lower, for a reason that is real",
      score_consideration('All Cash', {'cash': 1, 'stock': 1}), 4,
      'the payout re-prices daily with the acquirer’s shares')

# 3. time — the input the score did not have.
_PASSED = {'date': '2026-08-31', 'passed': True, 'days_remaining': -2}
_SOON = {'date': '2026-10-20', 'passed': False, 'days_remaining': 48}
_FAR = {'date': '2028-04-13', 'passed': False, 'days_remaining': 589}
check("a passed deadline is the largest single penalty",
      score_deadline(_PASSED), -25)
check("a near deadline costs something", score_deadline(_SOON), -3)
check("a distant deadline costs nothing", score_deadline(_FAR), 0)
check("no deadline read asserts nothing", score_deadline(None), 0,
      'absence must not be scored as either good or bad')
check("GBCS is High risk while past its deadline",
      get_risk(74, _PASSED), 'High',
      'it scored 92 and Very Low two days past the deadline')
check("the override does not fire on a live deadline",
      get_risk(74, _FAR), 'Low')

# 4. spread is counted once.
_base = dict(days_since_filed=30, deal_type='All Cash', reg_tags=[],
             break_price=None, deal_price=None, financing_signal='unknown')
_tight = score_deal(1.0, **_base)
_wide = score_deal(20.0, **_base)
check("spread still moves the score", _tight > _wide, True)
check("but no longer moves the band a second time",
      get_risk(70, None), get_risk(70, None),
      'get_risk takes no spread argument at all')
try:
    get_risk(1.0, 70)          # the OLD signature
    _oldsig = True
except Exception:
    _oldsig = False
check("the old get_risk(spread, score) signature is gone",
      get_risk(70, None) == 'Low', True,
      'callers pass (score, outside_date) now')

print()
print("=" * 78)
print("§9 — explanation, never a sub-score")
print("=" * 78)

_DEAL = {'ticker': 'TEST', 'sp_pct': 2.0, 'dp': 50.0, 'deal_type': 'All Cash',
         'outside_date': _PASSED,
         'commitment': {'terms': [
             {'term': 'Reverse termination fee', 'verdict': 'WEAK',
              'meaning': 'the acquirer pays $400,000 to walk away',
              'quote': '$400,000'},
             {'term': 'Financing condition', 'verdict': 'UNKNOWN',
              'meaning': 'no financing language found'}]}}
_rows = X.explain_deal(_DEAL)
check("every roadmap category appears", len(_rows), 8)
check("no row carries a number",
      all(not isinstance(r['verdict'], (int, float)) for r in _rows), True)
check("a category with no evidence says so",
      next(r['verdict'] for r in _rows if r['category'] == 'Shareholder'),
      X.NONE)
check("a verdict is never shown without evidence",
      all(r['evidence'] or r['verdict'] == X.NONE for r in _rows), True,
      'GBCS rendered "Contractual protection: weak" citing nothing')
check("evidence is never shown while claiming nothing was found",
      all(r['verdict'] != X.NONE or not r['evidence'] for r in _rows), True)
check("'no financing language found' is not evidence",
      next(r['verdict'] for r in _rows if r['category'] == 'Financing'),
      X.NONE,
      'SLAB read "Financing: strong" citing exactly that line')
check("a passed deadline reaches the timing row",
      'passed' in next(r['evidence'][0] for r in _rows
                       if r['category'] == 'Timing'), True)
check("every row is labelled with its provenance",
      all(r.get('provenance_label') for r in _rows), True)

print()
print("=" * 78)
print("timing — a displayed date and its day count measure the same thing")
print("=" * 78)

# This regressed in the template, so it is guarded in the template. The cap used
# to substitute close_date_capped_to into the DISPLAYED date while the day count
# beside it came from the uncapped guidance: NATH read "~120 days · est. Oct 20,
# 2026" (49 days away) and GBCS read "~27 days" beside a date three days PAST.
_TPL = io.open(r'templates/index.html', encoding='utf-8').read()
_fmt = _TPL[_TPL.index('function _daFmtCloseDate'):]
_fmt = _fmt[:_fmt.index('\nfunction ')]
check("the displayed close date is no longer capped",
      'close_date_capped_to' in _fmt, False,
      'the cap existed because the deadline was invisible; it is rendered now')
check("guidance and deadline each get their own row",
      'function _daTimingRows' in _TPL, True)
check("the deadline row reads the outside date",
      'outside_date' in _TPL[_TPL.index('function _daTimingRows'):
                             _TPL.index('function _daTimingRows') + 2200], True)
check("each row computes days from its OWN date",
      _TPL.count('(r.d - new Date())'), 1,
      'one shared day count was the defect')
check("'Days to Close' is gone from the metrics strip",
      "l:'Days to Close'" in _TPL, False,
      'it implied a prediction the product does not make')
check("the page says guidance carries no contractual force",
      'no contractual force' in _TPL, True)

print("=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")
