"""Direction-before-enrichment, paid-call caching, and the small-call wrapper.
No network: requests.post is replaced. Run:  python test_scan_stages.py
"""
import json, os, re, sys, time
sys.path.insert(0, os.getcwd())
os.environ['ANTHROPIC_API_KEY'] = 'test-key'
os.environ.pop('UPSTASH_REDIS_REST_URL', None)
import requests
import main

main.time.sleep = lambda *_: None


class Resp:
    def __init__(self, status, body):
        self.status_code, self._b, self.text = status, body, json.dumps(body)

    def json(self):
        return self._b


def text_resp(t):
    return Resp(200, {'content': [{'type': 'text', 'text': t}]})


fails = []


def check(name, cond):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


# 1. _llm_text finds the text block even when a thinking block comes first
check("_llm_text skips a leading thinking block",
      main._llm_text({'content': [{'type': 'thinking', 'thinking': 'hm'}, {'type': 'text', 'text': 'TARGET'}]}) == 'TARGET')
check("_llm_text returns '' when there is no text block",
      main._llm_text({'content': [{'type': 'thinking', 'thinking': 'hm'}]}) == '')

# 2. small-call wrapper: thinking disabled; a 400 retries once without it and remembers
seen = []


def post_400_on_thinking(url, headers=None, json=None, timeout=None, **kw):
    seen.append('thinking' in json)
    return Resp(400, {'error': 'bad'}) if 'thinking' in json else text_resp('ok')


requests.post = post_400_on_thinking
main._THINKING_OFF_REJECTED = False
r1 = main._post_small_llm('k', 's', 'u', 20, 5)
r2 = main._post_small_llm('k', 's', 'u', 20, 5)
check("first call sends thinking disabled", seen[0] is True)
check("a 400 is retried without thinking and succeeds", r1.status_code == 200 and seen[1] is False)
check("after a rejection the parameter is no longer sent", seen[2] is False and r2.status_code == 200)

seen.clear()
main._THINKING_OFF_REJECTED = False
requests.post = lambda url, headers=None, json=None, timeout=None, **kw: (seen.append(json.get('thinking')), text_resp('ok'))[1]
main._post_small_llm('k', 's', 'u', 20, 5)
check("thinking is sent as {'type': 'disabled'}", seen[0] == {'type': 'disabled'})

# 3. direction stage: all three model verdicts cached; failures are not
ANSWERS = {}
CALLS = []


def dir_post(url, headers=None, json=None, timeout=None, **kw):
    tk = re.search(r'ticker: ([A-Z0-9]+)', json['messages'][0]['content']).group(1)
    CALLS.append(tk)
    a = ANSWERS[tk]
    if a is None:
        return Resp(200, {'content': [{'type': 'thinking', 'thinking': '..'}]})
    return text_resp(a)


requests.post = dir_post


def mk(tk):
    return dict(ticker=tk, company=tk + ' Corp', _filing_text='x', accession='acc-' + tk, sp_pct=5.0,
                dp=None, cp=None, acquirer='Undisclosed', acquirer_type='Unknown', deal_type='All Cash',
                tx_value=None, close_date='TBD', filed='2026-09-01')


ANSWERS.update(T='TARGET', A='ACQUIRER', U='UNCLEAR', F=None)
cache = {'direction': {}, 'enrich': {}}
out = main.run_direction_stage([mk(t) for t in 'TAUF'], 'k', {}, cache)
check("only TARGET survives enforcing", [d['ticker'] for d in out] == ['T'])
check("TARGET, ACQUIRER and UNCLEAR answers are all cached", set(k.split('|')[0] for k in cache['direction']) == {'T', 'A', 'U'})
check("a reply with no text is NOT cached", 'F|acc-F' not in cache['direction'])
CALLS.clear()
main.run_direction_stage([mk(t) for t in 'TAUF'], 'k', {}, cache)
check("second scan re-asks only the unsettled deal", CALLS == ['F'])

# 4. enrichment never runs on a deal direction rejected; negative results are cached
ENR = []


def enr_post(url, headers=None, json=None, timeout=None, **kw):
    u = json['messages'][0]['content']
    tk = re.search(r'\[\[([A-Z0-9]+)\]\]', u).group(1)
    kind = 'acquirer' if 'acquiring company name' in u else 'txcd'
    ENR.append((kind, tk))
    return text_resp('{"acquirer": null}' if kind == 'acquirer' else '{"tx_value": null, "close_date": null}')


requests.post = enr_post
deals = [dict(mk(t), _filing_text=f'[[{t}]] filing') for t in ('N1', 'N2')]
c2 = {'direction': {}, 'enrich': {}}
main.run_enrichment_stage(deals, 'k', c2, sleep=lambda *_: None)
check("first scan asks acquirer and tx/close-date once per deal", len(ENR) == 4)
ENR.clear()
deals = [dict(mk(t), _filing_text=f'[[{t}]] filing') for t in ('N1', 'N2')]
main.run_enrichment_stage(deals, 'k', c2, sleep=lambda *_: None)
check("'checked, nothing found' is cached: second scan makes zero calls", ENR == [])
# same ticker, NEW filing -> asked again
deals = [dict(mk('N1'), accession='acc-new', _filing_text='[[N1]] filing')]
main.run_enrichment_stage(deals, 'k', c2, sleep=lambda *_: None)
check("a changed accession is re-read", len(ENR) == 2)

# 5. a deal that already has every field is not sent to the model at all
ENR.clear()
full = dict(mk('N9'), acquirer='Known Buyer', tx_value=1.2, close_date='Q4 2026', _filing_text='[[N9]] f')
main.run_enrichment_stage([full], 'k', {'direction': {}, 'enrich': {}}, sleep=lambda *_: None)
check("nothing missing -> no call", ENR == [])

print('\n%d failure(s)' % len(fails))
sys.exit(1 if fails else 0)
