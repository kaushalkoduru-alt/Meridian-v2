"""
Section 20: fact, model, inference, forecast.

Every value the product displays is one of four things, and a PM must never
mistake one for another:

  FACT      extracted from a filing and quotable -- the deal price, the reverse
            termination fee, the outside date, the consideration structure
  MODEL     computed by us from stated assumptions -- blended consideration,
            the annualized bounds
  INFERENCE a judgement drawn from facts -- "contractual protection appears
            strong", the regulatory path, the risk band
  FORECAST  an estimate about the future -- probability of close

The rule that makes this more than decoration: **a field is classified by where
its value actually came from, not by where it is displayed.** Five fields were
wearing the wrong label, and in each case the label was the more flattering one.

`break_price` is the clearest. The card footer read "Modeled downside case"
while `break_price_method` reads `historical` on 18 of 19 deals -- it is a
lookup of the pre-announcement close, wearing a model's label. The price itself
is a FACT (a real close on a real day); what is inferred is that the stock would
return to it on a break. Those are two different claims and the card made one.
"""

FACT = 'fact'
MODEL = 'model'
INFERENCE = 'inference'
FORECAST = 'forecast'

CLASSES = {
    FACT:      ('FACT',      'extracted from a filing, quotable'),
    MODEL:     ('MODEL',     'computed by Meridian from stated assumptions'),
    INFERENCE: ('INFERENCE', 'a judgement drawn from the facts'),
    FORECAST:  ('FORECAST',  'an estimate about the future'),
}

# Fields whose class never depends on the deal.
STATIC = {
    'dp':              (FACT, 'offer price, stated in the agreement'),
    'outside_date':    (FACT, 'the deadline stated in the agreement'),
    'commitment':      (FACT, 'termination fees and covenants, quoted'),
    'acquirer':        (FACT, 'named in the filing'),
    'deal_premium':    (MODEL, 'computed against the unaffected price'),
    'blended':         (MODEL, 'cash and stock legs, priced at today’s quote'),
    'ann_bounds':      (MODEL, 'spread projected over a stated horizon'),
    'sp_pct':          (MODEL, 'offer price against the last close'),
    'probability':     (FORECAST, 'an estimate about the future, not a measurement'),
    'score':           (INFERENCE, 'a judgement composed from the factors below'),
    'risk':            (INFERENCE, 'a band derived from the score'),
    'reg_tags':        (INFERENCE, 'the review path expected from deal size and '
                                   'sector — a prior, NOT filed regulatory status'),
    'acquirer_type':   (INFERENCE, 'read from the acquirer’s name'),
}


def classify(field, deal=None):
    """(class, label, why) for one field on one deal."""
    deal = deal or {}
    if field in STATIC:
        cls, why = STATIC[field]
        return cls, CLASSES[cls][0], why

    if field == 'cp':
        # A daily close is a fact about yesterday, not a quote.
        return FACT, 'FACT', 'last daily close, not a live quote'

    if field == 'break_price':
        m = (deal.get('break_price_method') or '').lower()
        if m in ('historical', 'verified_unaffected'):
            # The number is an observed close. Calling it modelled overstates
            # what stands behind it; calling the DOWNSIDE a fact would overstate
            # it in the other direction, which is why the two are split.
            return (FACT, 'FACT',
                    'the pre-announcement close, looked up — that the stock '
                    'returns to it on a break is the inference, not this price')
        return MODEL, 'MODEL', 'estimated from comparable broken deals'

    if field == 'tx_value':
        s = (deal.get('tx_value_source') or '').lower()
        if s.startswith('regex') or s.startswith('verified'):
            return FACT, 'FACT', 'transaction value stated in the filing'
        if s.startswith('equity'):
            return (MODEL, 'MODEL',
                    'equity value computed as offer price × shares '
                    'outstanding — not the enterprise value the filing states')
        return INFERENCE, 'INFERENCE', 'source not recorded'

    if field == 'financing_signal':
        src = (deal.get('financing_source') or '').lower()
        if src == 'agreement':
            return (FACT, 'FACT',
                    'read from the merger agreement’s financing condition')
        if src == 'press_release':
            return (INFERENCE, 'INFERENCE',
                    'inferred from press-release wording, not the agreement')
        return INFERENCE, 'INFERENCE', 'no financing language found'

    if field == 'close_date':
        s = (deal.get('close_date_source') or '').lower()
        if s and not s.startswith('llm'):
            return FACT, 'FACT', 'timing stated in the filing'
        if s.startswith('llm'):
            return INFERENCE, 'INFERENCE', 'read by a model, validated against bounds'
        return INFERENCE, 'INFERENCE', 'no stated close date'

    return INFERENCE, 'INFERENCE', 'source not recorded'


# Fields whose displayed label used to imply a stronger class than the value
# has. Kept as data so the sweep can assert they stay corrected.
CORRECTED = {
    'break_price':      'card footer said "Modeled downside case" on a lookup',
    'financing_signal': 'press-release keyword scan presented as a reading of '
                        'the agreement',
    'reg_tags':         'size-and-sector priors presented as regulatory status',
    'tx_value':         'enterprise and equity values under one label',
    'cp':               'a daily close labelled "current"',
}


def provenance_map(deal):
    """Every classified field on one deal, for the client to render badges."""
    fields = set(STATIC) | set(CORRECTED) | {'close_date'}
    out = {}
    for f in sorted(fields):
        cls, label, why = classify(f, deal)
        out[f] = {'class': cls, 'label': label, 'why': why}
    return out
