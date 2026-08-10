"""
FULL-DOCUMENT MERGER PRICE EXTRACTION

extract_targeted_section() takes a 2,500-3,000 character window it believes
holds the merger consideration. When that window lands wrong, the price is
missed even though it is plainly in the document. Amazon/iRobot failed this
way twice in the same filing:

    press release   "Amazon will acquire iRobot for $61 per share in an
                     all-cash transaction valued at approximately $1.7 billion"
    merger agmt     "shall be converted into the right to receive $61.00 per
                     Share in cash, without interest (the 'Merger Consideration')"

Both unambiguous. Both outside the window.

This searches the WHOLE document for merger-consideration phrasing, ordered
most-specific first, and returns the first confident match. Merger agreements
are boilerplate documents -- "converted into the right to receive $X per share
in cash, without interest" is close to universal -- which is what makes
full-text patterns viable here where they were not for direction detection.

Used as a FALLBACK. The existing extractor runs first; this catches what it
drops.
"""

import re

# Ordered most-specific to least. Specific patterns carry their own proof that
# the number is merger consideration; the loose ones at the bottom only run
# when nothing better matched.
PATTERNS = [
    # merger agreement boilerplate -- the strongest signal there is
    (r'converted\s+into\s+the\s+right\s+to\s+receive[^.]{0,120}?\$\s*([\d,]+\.?\d*)\s*(?:per|for\s+each)\s+[Ss]hare',
     'converted-into-right-to-receive'),
    (r'right\s+to\s+receive\s+\$\s*([\d,]+\.?\d*)\s*(?:per|for\s+each)\s+[Ss]hare[^.]{0,40}?in\s+cash',
     'right-to-receive-per-share-cash'),
    (r'\$\s*([\d,]+\.?\d*)\s*per\s+[Ss]hare\s+in\s+cash,?\s+without\s+interest',
     'per-share-cash-without-interest'),

    # press-release phrasing
    (r'acquire[^.]{0,80}?for\s+\$\s*([\d,]+\.?\d*)\s*per\s+share',
     'acquire-for-per-share'),
    (r'\$\s*([\d,]+\.?\d*)\s*per\s+share\s+in\s+(?:an\s+)?all[- ]cash',
     'per-share-all-cash'),
    (r'\$\s*([\d,]+\.?\d*)\s*(?:in\s+)?cash\s+per\s+share',
     'cash-per-share'),
    (r'\$\s*([\d,]+\.?\d*)\s*per\s+share\s+in\s+cash',
     'per-share-in-cash'),

    # tender offers
    (r'(?:offer|purchase)\s+price\s+of\s+\$\s*([\d,]+\.?\d*)\s*(?:net\s+)?per\s+share',
     'offer-price-per-share'),
    (r'\$\s*([\d,]+\.?\d*)\s*net\s+per\s+share',
     'net-per-share'),

    # named consideration
    (r'[Mm]erger\s+[Cc]onsideration[^.]{0,60}?\$\s*([\d,]+\.?\d*)\s*per\s+share',
     'merger-consideration-per-share'),
    (r'\$\s*([\d,]+\.?\d*)\s*per\s+share[^.]{0,60}?\(the\s+"?Merger\s+Consideration',
     'per-share-named-merger-consideration'),
]

# A per-share equity price outside this band is almost never real merger
# consideration -- it is a par value, an aggregate figure, or a typo.
MIN_PRICE = 0.10
MAX_PRICE = 2000.0


def extract_merger_price_fulltext(text, current_price=None, max_spread_pct=60.0):
    """
    Returns (price, pattern_label) or (None, reason).

    current_price, when supplied, is a sanity check rather than a filter: a
    "merger price" implying a spread far outside the plausible band is a
    mis-extraction, not an opportunity. Same arithmetic that caught FMNB at
    +91.91% and RKLB at -7.85%.
    """
    if not text:
        return None, 'no text'

    flat = re.sub(r'\s+', ' ', text)

    for pattern, label in PATTERNS:
        for m in re.finditer(pattern, flat, re.IGNORECASE):
            raw = m.group(1).replace(',', '')
            try:
                price = float(raw)
            except ValueError:
                continue
            if not (MIN_PRICE <= price <= MAX_PRICE):
                continue
            if current_price and current_price > 0:
                spread = ((price - current_price) / current_price) * 100
                if not (-15.0 <= spread <= max_spread_pct):
                    # plausible-looking number, implausible spread: keep looking
                    continue
            return round(price, 2), label

    return None, 'no merger-consideration phrasing matched'


def extract_with_fallback(section_text, full_text, existing_extractor,
                          current_price=None):
    """
    Existing extractor first, full-document search second.

    Order matters: the targeted section is higher-precision when it lands
    correctly, so it keeps priority. This only runs when it returns nothing.
    """
    try:
        price = existing_extractor(section_text)
        if price:
            return price, 'targeted-section'
    except Exception:
        pass
    price, label = extract_merger_price_fulltext(full_text, current_price)
    if price:
        return price, f'fulltext:{label}'
    return None, label