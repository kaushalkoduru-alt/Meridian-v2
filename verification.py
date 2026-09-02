"""
Which enforcing checks actually ran on a deal, and which were skipped.

Meridian has two checks that can remove a deal from the live feed:

  * the **direction check** -- is the filer the TARGET, or the acquirer?
  * the **verification gate** -- does an announcement filing exist with merger
    language in it?

Both fail OPEN, and both are right to:

    if DIRECTION_ENFORCING and anthropic_key:      # never enforce blind
    except Exception as _ge:
        print("[Gate] error (non-fatal, nothing blocked)")

A missing model key would otherwise mark every deal UNCLEAR and empty the feed,
and an exception in the gate would do the same. Failing open is the correct
choice for both.

What was NOT correct is the consequence: a deal admitted because a check was
skipped looked exactly like a deal admitted because it passed. BCRX, GPRE and
PACK entered that way on 2026-09-02 and sat in the live feed with a score, a
risk band and a spread. None was a merger of the filer at all -- BioCryst was
the ACQUIRER, Green Plains' filing was a convertible notes indenture, and
Ranpak's was a warrant issuance to Walmart whose "51% spread" was the gap
between a strike price and the share price.

A skipped check is not a passed check. This module says which happened, and the
page says it out loud.

Nothing here removes a deal. The enforcing checks do that when they run; this
reports on whether they ran.
"""

PASSED = 'passed'
SKIPPED = 'skipped'
FAILED = 'failed'

# Only these two can remove a deal, so only these two decide `verified`.
ENFORCING = ('direction', 'gate')


def _verdict(value):
    """A verdict arrives as a dict from a fresh scan and a string from the CSV."""
    if isinstance(value, dict):
        return value.get('verdict')
    if isinstance(value, str) and value:
        return value
    return None


def _direction(deal):
    v = _verdict(deal.get('direction'))
    if v is None:
        return (SKIPPED, 'the direction check did not run — it is skipped when '
                         'no model key is available, so this deal was never '
                         'tested for whether the filer is the target')
    if 'TARGET' in v and 'ACQUIRER' not in v:
        return PASSED, 'the filer was confirmed as the target, not the acquirer'
    return FAILED, 'the direction check did not return TARGET (%s)' % v


def _gate(deal):
    v = _verdict(deal.get('gate'))
    if v is None:
        return (SKIPPED, 'the verification gate did not run — an error in the '
                         'gate block is non-fatal and blocks nothing, so this '
                         'deal was never matched to an announcement filing')
    if v == 'VERIFIED':
        return PASSED, 'an announcement filing was found carrying merger language'
    return FAILED, 'the gate did not return VERIFIED (%s)' % v


def _agreement(deal):
    if deal.get('agreement_read'):
        return PASSED, 'the merger agreement exhibit was fetched and read'
    return (SKIPPED, 'no merger agreement has been read for this deal, so its '
                     'terms, deadline and fees are unread rather than absent')


def verification_state(deal):
    """
    {'verified', 'checks', 'headline', 'detail'} for one deal.

    `verified` is True only when BOTH enforcing checks passed. The agreement
    reading is reported alongside because a deal with no agreement read has no
    terms behind its numbers, but it is not an enforcing check and does not by
    itself make a deal unverified.
    """
    deal = deal or {}
    checks = []
    for name, fn in (('direction', _direction), ('gate', _gate),
                     ('agreement', _agreement)):
        state, why = fn(deal)
        checks.append({'name': name, 'state': state, 'detail': why})

    enforcing = [c for c in checks if c['name'] in ENFORCING]
    verified = all(c['state'] == PASSED for c in enforcing)
    skipped = [c['name'] for c in enforcing if c['state'] == SKIPPED]
    failed = [c['name'] for c in enforcing if c['state'] == FAILED]

    if verified:
        headline, detail = None, None
    elif failed:
        headline = 'THIS DEAL FAILED A VERIFICATION CHECK'
        detail = ('It is in the feed despite failing %s. Treat every number on '
                  'this page as unconfirmed.' % ' and '.join(failed))
    else:
        headline = 'NOT VERIFIED — A CHECK WAS SKIPPED, NOT PASSED'
        detail = ('This deal entered the feed without %s running. Those checks '
                  'are what confirm the filer is the target and that a real '
                  'merger announcement exists, so nothing on this page has '
                  'been confirmed yet.'
                  % ' or '.join(skipped))
    return {'verified': verified, 'checks': checks,
            'headline': headline, 'detail': detail,
            'skipped': skipped, 'failed': failed}
