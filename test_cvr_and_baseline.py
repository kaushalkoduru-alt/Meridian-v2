"""CVR spread handling and the detection-record baseline (SSTI, 2026-09-29)."""
from datetime import datetime
import copy

from cvr_spread import spread_not_meaningful, cvr_terms
from detection_baseline import rebaseline_detection, session_close_after

CTX = ("99.1 SoundThinking to be Acquired by Transom Capital Group SoundThinking shareholders to receive $8.00 per share in cash, "
       "plus one non-transferable contingent value right (CVR) for up to an additional $3.00 per share Upfront cash consideration")

def ssti(cp=8.43):
    return {"ticker": "SSTI", "cp": cp, "dp": 8.0,
            "flags": [{"flag": "CVR", "trigger": "contingent value right", "context": CTX},
                      {"flag": "CONTROLLING_HOLDER", "context": "x"}]}

# ── CVR ──────────────────────────────────────────────────────────────────────
def test_cvr_deal_above_cash_is_not_meaningful():
    d = ssti()
    assert spread_not_meaningful(d)
    t = cvr_terms(d)
    assert t["max_per_share"] == 3.0 and t["total_max"] == 11.0 and t["cash"] == 8.0
    assert t["spread_to_max_pct"] == round((11.0 - 8.43) / 8.43 * 100, 2)
    assert "up to an additional $3.00 per share" in t["quote"]

def test_cvr_deal_below_cash_keeps_its_spread():
    assert not spread_not_meaningful(ssti(cp=7.5))      # a real gap to cash is still a real spread

def test_no_cvr_flag_no_change():
    d = ssti(); d["flags"] = [{"flag": "GO_SHOP"}]
    assert not spread_not_meaningful(d) and cvr_terms(d) is None

def test_flags_that_arrive_as_a_repr_string():
    d = ssti(); d["flags"] = repr(d["flags"])
    assert spread_not_meaningful(d) and cvr_terms(d)["max_per_share"] == 3.0

def test_no_maximum_stated_means_none_is_shown():
    d = ssti(); d["flags"] = [{"flag": "CVR", "context": "holders also receive a contingent value right"}]
    t = cvr_terms(d)
    assert t["max_per_share"] is None and t["total_max"] is None

def test_score_gives_the_spread_factor_nothing_when_not_meaningful():
    import main as M
    kw = dict(days_since_filed=2, deal_type="Tender Offer", reg_tags=[], break_price=5.47, deal_price=8.0,
              financing_signal="committed", outside_date=None, blended=None, closing_signal=False)
    neg = M.score_deal(-5.04, **kw); nm = M.score_deal(None, **kw)
    assert nm > neg                                      # the -13 penalty is gone
    assert nm < M.score_deal(1.0, **kw)                  # and no tight-spread bonus is granted either
    assert M.get_risk(nm, None, False, break_downside=-35.11, spread_pct=None) in ("Low", "Very Low")

# ── session close ────────────────────────────────────────────────────────────
def test_session_close():
    assert session_close_after(datetime(2026, 9, 29, 11, 33)) == datetime(2026, 9, 29, 20, 0)   # EDT, pre-market
    assert session_close_after(datetime(2026, 9, 29, 21, 30)) == datetime(2026, 9, 30, 20, 0)   # after the close
    assert session_close_after(datetime(2026, 10, 2, 21, 0)) == datetime(2026, 10, 5, 20, 0)    # Friday evening -> Monday
    assert session_close_after(datetime(2026, 12, 1, 12, 0)) == datetime(2026, 12, 1, 21, 0)    # EST

# ── detection baseline ───────────────────────────────────────────────────────
def hist():
    rows = [("2026-09-29T12:14:58Z", 46.25, 5.47, 77, "High"), ("2026-09-29T13:14:44Z", 46.25, 5.47, 77, "High"),
            ("2026-09-29T17:15:07Z", -2.68, 8.22, 74, "Low"), ("2026-09-29T19:18:14Z", -2.97, 8.24, 74, "Low"),
            ("2026-09-29T20:16:02Z", -2.9, 8.23, 73, "Low"), ("2026-09-30T14:00:00Z", -4.1, 8.34, 74, "Low")]
    return ([{"t": t, "sp": sp, "cp": cp} for t, sp, cp, sc, r in rows],
            [{"t": t, "sc": sc, "risk": r} for t, sp, cp, sc, r in rows])

def deal():
    sh, sch = hist()
    return {"ticker": "SSTI", "filed": "2026-09-29", "accession": "x", "sp_pct": -5.04, "score": 74, "risk": "Low",
            "sp_pct_at_detection": 46.25, "score_at_detection": 77, "risk_at_detection": "High",
            "spread_history": sh, "score_history": sch}

ACCEPTED = lambda d: datetime(2026, 9, 29, 11, 33)
NOW = datetime(2026, 10, 1, 14, 0)

def test_ssti_detection_is_rebased_to_the_first_post_close_snapshot():
    d = deal()
    msg = rebaseline_detection(d, ACCEPTED, NOW)
    assert msg and "SSTI" in msg
    assert (d["sp_pct_at_detection"], d["score_at_detection"], d["risk_at_detection"]) == (-2.9, 73, "Low")
    assert "first close after the announcement" in d["detection_basis"]
    assert [bool(s.get("prov")) for s in d["spread_history"]] == [True, True, True, True, False, False]
    assert [bool(s.get("prov")) for s in d["score_history"]] == [True, True, True, True, False, False]

def test_rebase_is_idempotent():
    d = deal(); rebaseline_detection(d, ACCEPTED, NOW)
    snap = copy.deepcopy(d)
    assert rebaseline_detection(d, ACCEPTED, NOW) is None
    assert d == snap

def test_still_provisional_before_the_first_close_tracks_current_values():
    d = deal(); d["spread_history"] = d["spread_history"][:4]; d["score_history"] = d["score_history"][:4]
    rebaseline_detection(d, ACCEPTED, datetime(2026, 9, 29, 19, 30))
    assert (d["sp_pct_at_detection"], d["risk_at_detection"]) == (-5.04, "Low")      # current, not the 46.25 premium
    assert d["detection_basis"].startswith("provisional")

def test_a_deal_first_seen_after_the_close_is_left_alone():
    d = deal(); d["spread_history"] = d["spread_history"][4:]; d["score_history"] = d["score_history"][4:]
    d["sp_pct_at_detection"], d["score_at_detection"], d["risk_at_detection"] = -2.9, 73, "Low"
    assert rebaseline_detection(d, ACCEPTED, NOW) is None
    assert "detection_basis" not in d

def test_announcement_after_the_close_waits_for_the_next_session():
    d = deal()
    rebaseline_detection(d, lambda x: datetime(2026, 9, 29, 21, 30), NOW)    # accepted 17:30 ET
    # first valid close is 30 Sept 20:00Z and no snapshot exists at/after it yet
    assert d["detection_basis"].startswith("provisional")
    assert (d["sp_pct_at_detection"], d["risk_at_detection"]) == (-5.04, "Low")

def test_old_deals_are_never_touched():
    d = deal(); d["filed"] = "2026-08-01"
    assert rebaseline_detection(d, ACCEPTED, NOW) is None
    assert d["sp_pct_at_detection"] == 46.25

def test_unknown_acceptance_assumes_the_filing_date_close():
    d = deal()
    rebaseline_detection(d, lambda x: None, NOW)
    assert d["sp_pct_at_detection"] == -2.9
