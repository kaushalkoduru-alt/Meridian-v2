"""Milestone extractor: hedged/forward-looking text must yield nothing; real
assertions must yield the right typed, dated event. Real-filing ground truth
(NATH, IMXI) is run by hand: see milestone_events.py docstring."""
from milestone_events import extract_events

def ev(t, fd="2026-01-10"):
    return [(e["type"], e["regulator"], e["date"]) for e in extract_events(t, fd)]

def test_positive():
    assert ev("CFIUS Clearance was obtained on September 17, 2026.") == [("cfius_clearance", "CFIUS", "2026-09-17")]
    assert ev("At 11:59 p.m. Eastern Time on October 6, 2025, the waiting period under the HSR Act with respect to the Merger expired.") == [("hsr_expired", "HSR (FTC/DOJ)", "2025-10-06")]
    assert ev("The parties made the filings required under the HSR Act on January 23, 2026, and the waiting period expired on February 23, 2026.") == [("hsr_expired", "HSR (FTC/DOJ)", "2026-02-23")]

def test_dfpi_uses_letter_date_not_context_date():
    r = ev("Also on August 13, 2026, the California Department of Financial Protection and Innovation (the \"DFPI\") sent a letter suspending the approval extension previously granted on July 31, 2026 for the pending acquisition of IMXI.")
    assert r == [("approval_suspended", "California DFPI", "2026-08-13")]

def test_hedged_or_conditional_yields_nothing():
    for t in ["The Merger cannot be completed until the waiting period under the HSR Act has expired or been terminated.",
              "We may receive a second request from the FTC, which could delay the Merger.",
              "If CFIUS Clearance was obtained after the outside date, either party may terminate.",
              "The parties expect the waiting period under the HSR Act to expire in the third quarter.",
              "“CFIUS Clearance” means the parties have received written notice from CFIUS that the Merger is not a covered transaction."]:
        assert ev(t) == [], t

def test_second_request_only_when_issued():
    assert ev("On March 3, 2026, the Company received a Second Request from the FTC in connection with the Merger.")[0][0] == "second_request"
