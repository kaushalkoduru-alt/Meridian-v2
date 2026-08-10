"""
test_extract_acquirer.py -- validates improved acquirer extraction before pushing to main.py.
Run locally: py test_extract_acquirer.py
No network calls needed.
"""
import re

LEAD_JUNK = re.compile(
    r'^(?:'
    r'(?:under|pursuant to|as part of|in connection with|in accordance with)'
    r'\s+(?:the\s+)?(?:terms\s+of\s+)?(?:the\s+)?(?:agreement|merger agreement|transaction|deal)[,\s]+'
    r'|'
    r'(?:transaction highlights?|press release|news release|for immediate release)\s+'
    r'|'
    r'(?:(?:january|february|march|april|may|june|july|august|september|october|november|december)'
    r'\s+\d{1,2},?\s*\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4})\s*'
    r')',
    re.IGNORECASE
)

def clean_candidate(m):
    """Strip leading clause junk and date contamination from a raw regex match."""
    # First strip leading dates (handles run-together like "April 8, 2026Catalyst")
    m = re.sub(
        r'^(?:(?:january|february|march|april|may|june|july|august|september|'
        r'october|november|december)\s+\d{1,2},?\s*\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4})',
        '', m, flags=re.IGNORECASE).strip().lstrip(',. ')
    # Then strip leading clause introductions
    m = LEAD_JUNK.sub('', m).strip().lstrip(',. ')
    return m

def extract_acquirer(clean_text, target_name=''):
    text = clean_text[:15000]
    for g in [
        r'News\s*Release\s*', r'Press\s*Release\s*', r'For\s*Immediate\s*Release\s*',
        r'Document\w*\s*(?:News\s*)?Release\w*\s*', r'\bDocument\b\s*',
        r'Announces\s+Definitive\s+Agreement\s+', r'Announces\s+Agreement\s+',
    ]:
        text = re.sub(g, ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()

    patterns = [
        r'to\s+be\s+acquired\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s+at|\s*,|\s*\.|\s+pursuant)',
        r'will\s+be\s+acquired\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s+at|\s*,|\s*\.)',
        r'(?:^|[\.\,]\s*)acquired\s+by\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)(?:\s+for|\s+in|\s+at|\s*,|\s*\.)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:has\s+agreed\s+to\s+acquire|agreed\s+to\s+acquire|agrees\s+to\s+acquire)',
        r'(?:that|whereby)\s+([A-Z][A-Za-z0-9\s&\.\-\']{2,40}?)\s+will\s+acquire\b',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+to\s+acquire\s+(?:all\s+)?(?:of\s+)?(?:the\s+)?[A-Z][a-z]',
        r'(?:^|[\.]\s+)([A-Z][A-Za-z0-9\s&,\.\-\']{3,40}?)\s+will\s+acquire\b',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+today\s+announced\s+(?:it\s+has\s+agreed|a\s+definitive|an\s+agreement)',
        r'\bby\s+([A-Z][A-Za-z0-9\s&,\.\-\']+?)\s+(?:for\s+\$|in\s+a\s+|in\s+an\s+)',
        r'([A-Z][A-Za-z0-9\s&,\.\-\']+?(?:Inc|Corp|LLC|Ltd|Company|Group|Partners|Capital|Holdings|Management|Foods|Entertainment|Pharmaceuticals|Financial|Technologies|Solutions|Services|Systems))\s+(?:has\s+agreed|will\s+acquire|agreed|to\s+acquire|announced)',
    ]

    BAD_PHRASES = [
        'pursuant', 'stockholder', 'common stock', 'the company', 'which', 'upon',
        'each', 'document', 'exhibit', 'form 8', 'the board', 'the transaction',
        'forward', 'investor', 'this agreement', 'subject to', 'following', 'certain',
        'may not be', 'consummated', 'cannot be', 'will not be', 'is not', 'are not',
        'buyer', 'parent', 'merger sub', 'acquisition sub', 'bidder', 'offeror',
        'purchaser', 'wholly-owned', 'wholly owned', 'a subsidiary', 'subsidiary',
        'under the terms', 'as part of', 'in connection', 'transaction highlights',
    ]

    STOP_WORDS = {'inc', 'corp', 'ltd', 'llc', 'the', 'and', 'of', 'co', 'group',
                  'holdings', 'plc', 'company', 'famous', 'entertainment'}
    target_words = set(target_name.lower().split()) - STOP_WORDS if target_name else set()

    candidates = []
    for pat in patterns:
        for m in re.findall(pat, text, re.IGNORECASE):
            if not isinstance(m, str):
                continue
            m = m.strip().rstrip(',.')
            m = re.sub(r'\s+', ' ', m)
            m = re.sub(
                r'\s+(?:has|have|will|today|hereby|announces|announced|entered|'
                r'agrees|agreed|intends|to\s+acquire|to\s+be)\s*$',
                '', m, flags=re.IGNORECASE).strip()
            m = re.sub(r',?\s*(?:Inc|Corp|Ltd|LLC)\.?\s*$', '', m).strip()
            # Strip leading clause junk and date contamination
            m = clean_candidate(m)
            if not (2 < len(m) < 60):
                continue
            if any(b in m.lower() for b in BAD_PHRASES):
                continue
            if not m[0].isupper():
                continue
            if m.upper() == m and len(m) > 5:
                continue
            if len(m.split()) > 7:
                continue
            # Same-entity rejection
            if target_words:
                cand_words = set(m.lower().split()) - STOP_WORDS
                overlap = len(target_words & cand_words)
                if overlap >= 2 or (overlap >= 1 and len(target_words) <= 2):
                    continue
            candidates.append(m)

    if not candidates:
        return 'Undisclosed'
    multi_word = [c for c in candidates if len(c.split()) > 1]
    if multi_word:
        return min(multi_word, key=len)
    return min(candidates, key=len)


tests = [
    # Original 7
    ("Smithfield to acquire Nathan's (present infinitive)",
     "Smithfield Foods to acquire all of Nathan's Famous' issued and outstanding shares for $102.00 per share.",
     "Nathan's Famous", "Smithfield Foods"),
    ("Caesars to be acquired by Fertitta (passive)",
     "Caesars Entertainment, Inc. has entered into a definitive agreement to be acquired by Fertitta Entertainment for $31.00 per share in cash.",
     "Caesars Entertainment", "Fertitta Entertainment"),
    ("Generic 'will be acquired by'",
     "The Company entered into an Agreement and Plan of Merger pursuant to which it will be acquired by Blackstone Capital Partners in an all-cash transaction.",
     "The Company", "Blackstone Capital Partners"),
    ("Target name first, acquirer second",
     "Nathan's Famous, Inc. announced today that Smithfield Foods will acquire all of Nathan's Famous' outstanding shares for $102.00 per share.",
     "Nathan's Famous", "Smithfield Foods"),
    ("Active past: acquirer has agreed to acquire",
     "Long Lake Management has agreed to acquire Global Business Travel Group for $9.50 per share.",
     "Global Business Travel Group", "Long Lake Management"),
    ("No acquirer -- returns Undisclosed",
     "The Company has entered into a definitive merger agreement. The transaction is subject to customary closing conditions.",
     "The Company", "Undisclosed"),
    ("Consortium: will be acquired by",
     "The AES Corporation announced that it will be acquired by Global Infrastructure Partners and EQT for $15.00 per share.",
     "AES Corporation", "Global Infrastructure Partners"),
    # New failure cases from production
    ("WBD: section header before name",
     "Transaction Highlights Paramount will acquire Warner Bros. Discovery for $31.00 per share.",
     "Warner Bros. Discovery", "Paramount"),
    ("PAYO: lead-in clause before name",
     "Under the terms of the agreement, Nuvei will acquire Payoneer for $7.40 per share.",
     "Payoneer", "Nuvei"),
    ("GSAT: lead-in clause before name",
     "As part of the agreement, Amazon will acquire Globalstar for $1.20 per share.",
     "Globalstar", "Amazon"),
    ("CLST: date run-together, target should be rejected",
     "April 8, 2026Catalyst Bancorp, Inc. entered into a definitive agreement to be acquired by Siemens for $14.00 per share.",
     "Catalyst Bancorp", "Siemens"),
    ("AVNS: full multi-word name must not be truncated",
     "American Industrial Partners to acquire Avanos Medical for $14.50 per share in an all-cash deal.",
     "Avanos Medical", "American Industrial Partners"),
]

print(f"{'Test':<48} {'got':<32} {'expected':<32} result")
print("-" * 120)
all_pass = True
for label, text, target, expected in tests:
    got = extract_acquirer(text, target_name=target)
    if expected == 'Undisclosed':
        ok = got == 'Undisclosed'
    else:
        ok = got != 'Undisclosed' and expected.lower() in got.lower()
    if not ok:
        all_pass = False
    print(f"{label:<48} {got:<32} {expected:<32} {'OK' if ok else 'FAIL'}")

print()
print("All 12 passed." if all_pass else "FAILURES above -- do not push to main.py.")