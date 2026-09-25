"""Hit de-duplication: the preferred hit per ticker is exactly what it always was,
and the hits that used to be thrown away now follow as fallbacks. No network.
Run:  python test_dedup.py
"""
import os
import random
import sys

sys.path.insert(0, os.getcwd())
import main
from main import dedupe_hits, _hit_rank, _hit_date

fails = []


def check(name, cond):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


def hit(tk, acc, date, items=None, form='8-K'):
    return {'_id': acc, '_source': {'display_names': [f'{tk} Corp  ({tk})  (CIK 0000000001)'],
                                    'adsh': acc, 'form': form, 'file_date': date,
                                    'items': items or []}}


def old_dedupe(all_hits):
    """The algorithm this replaced, verbatim: replace the kept hit when the new one
    ranks higher, or ranks equal and is strictly later."""
    seen_pre, kept = {}, []
    for i, h in enumerate(all_hits):
        key = main._hit_ticker_key(h, i)
        if key not in seen_pre:
            seen_pre[key] = len(kept)
            kept.append(h)
        else:
            idx = seen_pre[key]
            ks, ns = kept[idx]['_source'], h['_source']
            nr, kr = _hit_rank(ns), _hit_rank(ks)
            if nr > kr or (nr == kr and _hit_date(ns) > _hit_date(ks)):
                kept[idx] = h
    return kept


# 1. the preferred hits are identical to the old algorithm on random inputs
random.seed(7)
FORMS = [('8-K', ['1.01', '9.01']), ('8-K', ['7.01']), ('8-K', ['1.01', '2.01']), ('8-K', ['8.01']),
         ('DEFM14A', []), ('8-K', ['1.01', '5.01']), ('SC TO-T', [])]
DATES = ['2026-02-09', '2026-03-02', '2026-03-19', '2026-04-13', '', 'bad']
same = True
for trial in range(3000):
    hs = []
    for n in range(random.randint(1, 14)):
        f, it = random.choice(FORMS)
        hs.append(hit(random.choice('ABCDE'), f'acc{trial}-{n}', random.choice(DATES), it, f))
    pref, _ = dedupe_hits(hs, log=lambda *_: None)
    if [h['_id'] for h in pref] != [h['_id'] for h in old_dedupe(hs)]:
        same = False
        break
check("3,000 random hit sets: the preferred hit per ticker matches the old algorithm exactly", same)

# 2. AES: the Mar 19 financing amendment outranks the Mar 2 announcement, as before,
# but the announcement is no longer discarded
aes = [hit('AES', '0001193125-26-084157', '2026-03-02', ['1.01', '5.02', '7.01', '9.01']),
       hit('AES', '0001193125-26-116111', '2026-03-19', ['1.01', '9.01']),
       hit('AES', '0001193125-26-272726', '2026-06-16', ['1.01', '2.03', '9.01'])]
pref, fb = dedupe_hits(aes, log=lambda *_: None)
check("AES: the latest 1.01 filing is still the preferred hit", [h['_id'] for h in pref] == ['0001193125-26-272726'])
check("AES: the Mar 19 amendment and the Mar 2 announcement follow as fallbacks, newest first",
      [h['_id'] for h in fb] == ['0001193125-26-116111', '0001193125-26-084157'])

# 3. WBD: a later superseding agreement is preferred over the earlier amendment
wbd = [hit('WBD', 'jan', '2026-01-08', ['1.01']), hit('WBD', 'feb', '2026-02-20', ['1.01'])]
pref, fb = dedupe_hits(wbd, log=lambda *_: None)
check("WBD: the later superseding agreement is preferred", [h['_id'] for h in pref] == ['feb'])

# 4. GBCS: a closing 8-K (1.01 with 2.01/5.01) never outranks and is never a fallback
gbcs = [hit('GBCS', 'merger', '2026-06-12', ['1.01']), hit('GBCS', 'closing', '2026-09-02', ['1.01', '2.01', '5.01'])]
pref, fb = dedupe_hits(gbcs, log=lambda *_: None)
check("GBCS: the merger agreement stays preferred over a closing 8-K", [h['_id'] for h in pref] == ['merger'])
check("GBCS: the closing 8-K is not offered as a fallback", fb == [])

# 5. filings that cannot be a deal document are not fallbacks
junk = [hit('X', 'good', '2026-03-01', ['1.01']), hit('X', 'fd', '2026-04-01', ['7.01']),
        hit('X', 'earn', '2026-05-01', ['2.02'])]
pref, fb = dedupe_hits(junk, log=lambda *_: None)
check("a 7.01 or 2.02 filing is neither preferred nor a fallback", [h['_id'] for h in pref] == ['good'] and fb == [])

# 6. a proxy that lost can still be a fallback (Path B resolves it to the announcement)
px = [hit('P', 'a', '2026-06-01', ['1.01']), hit('P', 'proxy', '2026-05-01', [], 'DEFM14A')]
pref, fb = dedupe_hits(px, log=lambda *_: None)
check("a losing proxy is kept as a fallback", [h['_id'] for h in fb] == ['proxy'])

# 7. nothing is lost or duplicated
allids = [h['_id'] for h in aes]
pref, fb = dedupe_hits(aes, log=lambda *_: None)
check("every input hit is either preferred or a fallback exactly once",
      sorted(h['_id'] for h in pref + fb) == sorted(allids))

# 8. an undated hit sorts last, never first
und = [hit('U', 'undated', '', ['1.01']), hit('U', 'dated', '2026-01-01', ['1.01'])]
pref, fb = dedupe_hits(und, log=lambda *_: None)
check("an undated hit does not outrank a dated one", [h['_id'] for h in pref] == ['dated'])

print('\n%d failure(s)' % len(fails))
sys.exit(1 if fails else 0)
