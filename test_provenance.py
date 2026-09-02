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

print()
print("=" * 78)
print("financing — ONE pattern list, and the agreement wins")
print("=" * 78)

import re as _re
import deal_commitment as DC
from main import _FIN_NO_CONDITION, _FIN_HAS_CONDITION

# The duplicate list is why the negation fix reached the press-release scan and
# never reached the agreement reading. There is one list now, and this asserts
# main.py derives from it rather than restating it.
check("main.py's denial patterns come from deal_commitment",
      _FIN_NO_CONDITION, [p for p, _l in DC.NO_FINANCING_COND],
      'a duplicated pattern list is a guarantee this recurs')
check("and so do the assertion patterns",
      _FIN_HAS_CONDITION, [p for p, _l in DC.HAS_FINANCING_COND])

_cf = lambda t: DC.check_financing(t)[0]

# ATKR: the sentence that returned "no financing language found".
check("ATKR: 'obtaining of the Financing is not a condition to Closing'",
      _cf('Buyer acknowledges that the obtaining of the Financing is not a '
          'condition to Closing.'), 'STRONG',
      'the agreement reading was blind to what the press-release scan could read')

# BWMN and GBTG: a section heading that DENIES a condition, in title case.
check("a title-case 'No Financing Condition' heading is a denial",
      _cf('(e) No Financing Condition. Parent acknowledges its obligations.'),
      'STRONG',
      'lowercase denial patterns vs [Ff]inancing [Cc]ondition read it as WEAK')

# APGE: the denial names two conditions at once.
check("APGE: 'not subject to a diligence or financing condition'",
      _cf('the Merger is not subject to a diligence or financing condition'),
      'STRONG')

# ALOT: a condition on a rival bid is not a condition on this deal.
check("a financing condition inside a Takeover Proposal test is not ours",
      _cf('the anticipated timing, conditions (including any financing '
          'condition or the reliability of any debt or equity funding '
          'commitments) and prospects for completion of such Takeover Proposal'),
      'UNKNOWN',
      'ALOT was charged 10 points for an offer that does not exist')

# The genuine article still reads WEAK, and genuine silence still reads UNKNOWN.
check("a real financing condition is still WEAK",
      _cf('The Offer is subject to a financing condition.'), 'WEAK')
check("a commitment letter with no conditionality language stays UNKNOWN",
      _cf('Parent has entered into a Debt Commitment Letter with the Lenders.'),
      'UNKNOWN',
      'AES, CBZ and GBCS are genuinely silent -- flipping them would be worse '
      'than the bug')

# Precedence, confirmed rather than assumed.
check("the agreement outranks the press release when they disagree",
      financing_from_commitment(
          {'terms': [{'term': 'Financing condition', 'verdict': 'STRONG'}]})[0],
      'committed')
check("and is still named as the source when they AGREE",
      financing_from_commitment(
          {'terms': [{'term': 'Financing condition', 'verdict': 'STRONG'}]})[1],
      'agreement',
      'skipping the source on agreement badged a contractual fact as INFERENCE')

print()
print("=" * 78)
print("financing — three tiers, and a symmetric gate")
print("=" * 78)

from main import (financing_evidence_scores, scoring_financing_signal,
                  is_press_release_url, get_filing_links)
from deal_commitment import financing_condition_state

check("the 8-K body outranks the press release",
      P.SOURCE_RANK['filed_disclosure'] > P.SOURCE_RANK['press_release'], True,
      'a filed Item 1.01 disclosure is not marketing copy')
check("and the agreement outranks both",
      P.SOURCE_RANK['agreement'] > P.SOURCE_RANK['filed_disclosure'], True)
check("a filed disclosure is INFERENCE, not FACT",
      P.classify('financing_signal',
                 {'financing_source': 'filed_disclosure'})[0], P.INFERENCE,
      'it describes the instrument; it is not the instrument')

# The gate is symmetric. That is the point of it.
_read = {'agreement_read': '0001-26-1'}
check("agreement read + silent: a press-release REWARD does not score",
      scoring_financing_signal(dict(_read, financing_signal='committed',
                                    financing_source='press_release')),
      'unknown')
check("agreement read + silent: a press-release PENALTY does not score either",
      scoring_financing_signal(dict(_read, financing_signal='contingent',
                                    financing_source='press_release')),
      'unknown',
      'barring only the penalty would be a bullish thumb on the scale')
check("agreement read + silent: the 8-K body does not score",
      financing_evidence_scores(dict(_read, financing_source='filed_disclosure')),
      False)
check("no agreement read: the best weaker document DOES score",
      scoring_financing_signal({'financing_signal': 'contingent',
                                'financing_source': 'filed_disclosure'}),
      'contingent',
      'it is then the best evidence there is, not a summary of something better')
check("the agreement always scores",
      financing_evidence_scores(dict(_read, financing_source='agreement')), True)

# Silence is our limit, never a finding about the deal.
check("silence is described as an absence of evidence",
      'not evidence the condition is absent' in P.FINANCING_SILENCE, True,
      'four pattern defects in two sessions each produced confident silence')

# One guarded answer, shared. The patterns were consolidated and the guards
# were not, so this read a Superior Proposal clause as a financing condition.
_rival = ('the anticipated timing, conditions (including any financing '
          'condition or the reliability of any debt or equity funding '
          'commitments) and prospects for completion of such Takeover Proposal')
check("the rival-bid guard applies to the press-release classifier too",
      extract_financing_signal(_rival), 'unknown')
check("and the shared state function is what both call",
      financing_condition_state(_rival)[0], None)
check("a real condition still reaches both",
      (extract_financing_signal('The Offer is subject to a financing condition.'),
       financing_condition_state('The Offer is subject to a financing condition.')[0]),
      ('contingent', 'exists'))

check("an EX-99 exhibit is recognised as the press release",
      is_press_release_url('/Archives/edgar/data/8146/x/d100857dex991.htm'), True)
check("an 8-K body is not",
      is_press_release_url('/Archives/edgar/data/8146/x/d100857d8k.htm'), False)

print()
print("=" * 78)
print("evidence — the quote is separable from the claim")
print("=" * 78)

_QD = {'ticker': 'T', 'sp_pct': 1.0, 'dp': 10.0, 'deal_type': 'All Cash',
       'commitment': {'terms': [
           {'term': 'Reverse termination fee', 'verdict': 'WEAK',
            'meaning': 'the acquirer pays $400,000 to walk away',
            'quote': '$400,000 (the Purchaser Termination Fee)'}]}}
_qrows = X.explain_deal(_QD)
_cp = next(r for r in _qrows if r['category'] == 'Contractual protection')
check("an agreement term's evidence is {text, quote}",
      isinstance(_cp['evidence'][0], dict), True,
      'concatenating them forced the page to show all of it or none')
check("the claim is carried separately from the words",
      _cp['evidence'][0]['text'], 'the acquirer pays $400,000 to walk away')
check("and the quote is still there, not dropped",
      _cp['evidence'][0]['quote'].startswith('$400,000'), True,
      '§44 requires a path from any claim to the filing language')

# The template is where this renders, so the template is where it is asserted.
_T = io.open(r'templates/index.html', encoding='utf-8').read()
check("quote body text is the warm off-white used for body copy",
      "color:#e8e0d0; font-style:normal;'" in _T.replace('  ', ' ')
      or 'color:#e8e0d0' in _T[_T.index('details.da-q blockquote'):
                               _T.index('details.da-q blockquote') + 400], True,
      'it was #8f8772 and #9a9079 — dimmer than the labels around it')
check("every quote renders through the one shared component",
      _T.count('function _daQuote(') , 1)
check("exactly one blockquote is emitted, by the shared component",
      _T.count("'<blockquote"), 1,
      'five sections rendered their own; all five call _daQuote now')
check("and it is inside _daQuote",
      _T.index("'<blockquote") > _T.index('function _daQuote(')
      and _T.index("'<blockquote") < _T.index('function _daQuoteToggleAll'), True)
check("quotes are collapsed by default, not removed",
      'details class="da-q"' in _T, True)
check("and one control opens all of them",
      'function _daQuoteToggleAll' in _T, True,
      'auditing a deal through six separate disclosures would be worse')
check("the unevidenced denominator is still all eight categories",
      "have+' of '+total+' categories carry evidence" in _T, True,
      'filtering the rows must not shrink the count it reports')

print()
print("=" * 78)
print("verification — a skipped check is not a passed check")
print("=" * 78)

import verification as V

_OK = {'direction': {'verdict': 'TARGET'}, 'gate': {'verdict': 'VERIFIED'},
       'agreement_read': '0001-26-1'}
check("a deal that passed both enforcing checks is verified",
      V.verification_state(_OK)['verified'], True)
check("a verified deal shows no banner",
      V.verification_state(_OK)['headline'], None)

# The exact shape BCRX, GPRE and PACK reached the live feed in.
_SKIPPED = {'ticker': 'BCRX', 'direction': {}, 'gate': None}
_vs = V.verification_state(_SKIPPED)
check("both checks skipped is NOT verified", _vs['verified'], False,
      'they sat in the feed with a score and a risk band')
check("and the page says skipped, not failed",
      'SKIPPED, NOT PASSED' in _vs['headline'], True)
check("naming which checks did not run", sorted(_vs['skipped']),
      ['direction', 'gate'])
check("a failed check reads differently from a skipped one",
      'FAILED' in V.verification_state(
          {'direction': {'verdict': 'ACQUIRER'},
           'gate': {'verdict': 'VERIFIED'}})['headline'], True)

# A cached row round-trips its verdicts through the CSV as bare strings.
check("verdicts cached as strings still read as passed",
      V.verification_state({'direction': 'TARGET', 'gate': 'VERIFIED',
                            'agreement_read': 'a'})['verified'], True,
      'a bare .get(verdict) on a string crashed this block once before')

# An unread agreement is reported but is not an enforcing check.
_NOAGR = dict(_OK); _NOAGR.pop('agreement_read')
check("an unread agreement does not by itself make a deal unverified",
      V.verification_state(_NOAGR)['verified'], True)
check("but it is still reported",
      next(c['state'] for c in V.verification_state(_NOAGR)['checks']
           if c['name'] == 'agreement'), V.SKIPPED)

_T = io.open(r'templates/index.html', encoding='utf-8').read()
check("the banner renders above the numbers it qualifies",
      _T.index('id="da-verification"') < _T.index('id="da-premium-note"'), True)

print("=" * 78)
print("ALL PASS" if ok else "SOMETHING FAILED")
