"""Phase 4 (campaign DiD) assertions.

Every estimate here is observational (R1) - treatment was assigned by the
retailer. Verified numbers live in AGENTS.md section 2.5; the redemption
anchors come from section 2.1. If numbers move after a data refresh,
re-verify AGENTS.md first - never relax a test silently.
"""

import numpy as np
import pytest

from src.did import ELIGIBLE_FLAGS, SMD_TARGET, build_campaign_design, build_campaign_results

# Verified (locked, deterministic seeds; overlap/ATO primary - DL-012,
# tight voucher cost - DL-013):
BACKBONE_ATT = {8: 3.56, 13: 6.21, 18: 5.84}
BACKBONE_ATT_CI = {8: (1.54, 5.37), 13: (4.29, 8.19), 18: (3.93, 7.67)}
BACKBONE_RATIO = {8: 4.736, 13: 4.993, 18: 3.433}
BACKBONE_IPW_SENSITIVITY = {8: 3.18, 13: 4.76, 18: 6.29}
BACKBONE_REDEEMERS = {8: 158, 13: 196, 18: 214}
FINAL_LAYAK = {5, 7, 9, 10, 12, 13, 16, 17, 18, 19, 20, 22, 23, 25, 26, 29, 30}
PRETREND_FAILED = {8, 11, 14}
FLAG_COUNTS = {
    "layak (observasional)": 15,
    "tidak reliable": 9,
    "tidak reliable — pre-trend": 3,
    "layak — utama (observasional)": 2,
    "excluded": 1,
}


def _est(did_outputs):
    results, _ = did_outputs
    return results[results["estimated"]].set_index("campaign_id")


# --- design -------------------------------------------------------------------


def test_design_matches_foundation_control_pool(timeline, hh_campaign, hh_week):
    row = timeline[timeline["campaign_id"] == 8].iloc[0]
    design = build_campaign_design(row, hh_campaign, hh_week)
    treated = design[design["treated"] == 1]
    control = design[design["treated"] == 0]
    assert len(treated) == 1_076  # == n_treated
    assert len(control) == 1_359  # == n_control_pool (foundation phase)
    assert not (set(treated["household_key"]) & set(control["household_key"]))
    # weekly-average normalisation keeps everything finite
    assert np.isfinite(design[["spend_weekly_pre", "spend_weekly_post"]].to_numpy()).all()


# --- structure ------------------------------------------------------------------


def test_results_structure(did_outputs):
    results, events = did_outputs
    assert len(results) == 30 and results["campaign_id"].nunique() == 30
    assert int(results["estimated"].sum()) == 20
    # non-estimated rows are exactly the non-eligible campaigns
    non_est = results[~results["estimated"]]
    assert set(non_est["reliability_flag_input"]).isdisjoint(ELIGIBLE_FLAGS)
    assert len(events) == 574
    assert set(events["group"].unique()) == {"treated", "control"}
    assert (events["n"] > 0).all()


# --- backbone estimates & diagnostics ---------------------------------------------


def test_backbone_att_and_diagnostics(did_outputs):
    est = _est(did_outputs)
    for cid, att in BACKBONE_ATT.items():
        row = est.loc[cid]
        assert row["att"] == pytest.approx(att, abs=0.02)
        lo, hi = BACKBONE_ATT_CI[cid]
        assert row["att_ci_low"] == pytest.approx(lo, abs=0.05)
        assert row["att_ci_high"] == pytest.approx(hi, abs=0.05)
        assert lo <= att <= hi
        # ATT-IPW sensitivity stays consistent with the overlap estimate
        assert row["att_ipw_sensitivity"] == pytest.approx(BACKBONE_IPW_SENSITIVITY[cid], abs=0.02)
    # overlap weighting balances every eligible campaign (DL-012)
    assert (est["smd_max_after"] < SMD_TARGET).all()
    # backbone placebo: 13 and 18 pass; 8 fails and must be flagged (honesty
    # guard - significance and reliability are separate concepts)
    assert est.loc[13, "pre_trend_ok"] and est.loc[18, "pre_trend_ok"]
    assert not est.loc[8, "pre_trend_ok"]
    assert est.loc[8, "significance"] == "signifikan positif"


def test_flags_and_failures(did_outputs):
    results, _ = did_outputs
    layak = set(results.loc[results["reliability_flag"].str.startswith("layak"), "campaign_id"])
    assert layak == FINAL_LAYAK
    assert set(_est(did_outputs).loc[lambda d: ~d["pre_trend_ok"]].index) == PRETREND_FAILED
    assert results["reliability_flag"].value_counts().to_dict() == FLAG_COUNTS


def test_redeemers_match_verified_counts(did_outputs):
    est = _est(did_outputs)
    for cid, n_red in BACKBONE_REDEEMERS.items():
        row = est.loc[cid]
        assert row["n_redeemers"] == n_red
        assert row["redemption_rate"] == pytest.approx(n_red / row["n_treated"], abs=1e-9)


def test_voucher_economics(did_outputs):
    est = _est(did_outputs)
    for cid, ratio in BACKBONE_RATIO.items():
        row = est.loc[cid]
        # tight attribution (DL-013): campaign-item coupon cost, the primary
        assert row["voucher_cost_campaign_items"] > 0
        assert row["voucher_cost_all_coupons"] > row["voucher_cost_campaign_items"]
        assert row["inc_spend_per_dollar"] == pytest.approx(ratio, abs=0.01)
        assert row["margin15_per_dollar"] < row["margin25_per_dollar"] < row["margin35_per_dollar"]
    # Verified pattern: at 25% margin campaigns 8 and 13 pay back, 18 only
    # at 35%; the all-coupons bound stays negative everywhere.
    assert est.loc[8, "margin25_per_dollar"] > 0 and est.loc[13, "margin25_per_dollar"] > 0
    assert est.loc[18, "margin25_per_dollar"] < 0 < est.loc[18, "margin35_per_dollar"]
    assert (est.loc[[8, 13, 18], "margin35_per_dollar_allcoupons"] < 0).all()


def test_bootstrap_deterministic(eligible_timeline, hh_campaign, hh_week):
    r1, _ = build_campaign_results(eligible_timeline, hh_campaign, hh_week, n_bootstrap=50)
    r2, _ = build_campaign_results(eligible_timeline, hh_campaign, hh_week, n_bootstrap=50)
    a1 = r1[r1["estimated"]].set_index("campaign_id")["att"]
    a2 = r2[r2["estimated"]].set_index("campaign_id")["att"]
    assert a1.equals(a2)


def test_notebook_carries_observational_label():
    from pathlib import Path

    nb = Path(__file__).resolve().parent.parent / "notebooks" / "04_campaign_did.ipynb"
    assert nb.exists(), "notebook 04 must exist"
    text = nb.read_text(encoding="utf-8")
    assert "observasional" in text.lower()
