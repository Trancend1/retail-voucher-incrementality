"""Phase 4 (campaign DiD) assertions.

Every estimate here is observational (R1) - treatment was assigned by the
retailer. Verified numbers live in AGENTS.md section 2.5; the redemption
anchors come from section 2.1. If numbers move after a data refresh,
re-verify AGENTS.md first - never relax a test silently.
"""

import numpy as np
import pytest

from src.did import ELIGIBLE_FLAGS, SMD_TARGET, build_campaign_design, build_campaign_results

# Verified (locked, deterministic seeds; DL-012 overlap weights, DL-013 tight
# voucher cost, DL-014 extended propensity + two-placebo gate):
BACKBONE_ATT = {8: 2.67, 13: 4.12, 18: 4.29}
BACKBONE_ATT_CI = {8: (0.69, 4.51), 13: (2.20, 6.14), 18: (2.41, 6.05)}
BACKBONE_RATIO = {8: 3.549, 13: 3.309, 18: 2.522}
BACKBONE_IPW_SENSITIVITY = {8: 3.58, 13: 3.70, 18: 5.86}
BACKBONE_REDEEMERS = {8: 158, 13: 196, 18: 214}
FINAL_LAYAK = {5, 8, 9, 11, 12, 13, 14, 16, 19, 20, 22, 23, 29, 30}
FAR_PRETREND_FAILED = {7, 10, 17, 18, 25, 26}
FLAG_COUNTS = {
    "layak (observasional)": 12,
    "tidak reliable": 9,
    "tidak reliable — pre-trend jauh": 6,
    "layak — utama (observasional)": 2,
    "excluded": 1,
}
POOLED_FE = (3.83, 2.89, 4.77)
POOLED_RE = (4.87, 3.06, 6.68)


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
        # ATT-IPW sensitivity (same features, different weighting) agrees
        assert row["att_ipw_sensitivity"] == pytest.approx(BACKBONE_IPW_SENSITIVITY[cid], abs=0.02)
    # overlap weighting balances every eligible campaign (DL-012)
    assert (est["smd_max_after"] < SMD_TARGET).all()
    # two-placebo gate (DL-014): campaign 8 now passes both; campaign 18 is
    # the honesty guard - BH-significant estimate but far-window placebo
    # failure keeps it flagged (significance is not identification)
    assert est.loc[8, "pre_trend_ok"] and est.loc[8, "far_pre_trend_ok"]
    assert not est.loc[18, "far_pre_trend_ok"]
    assert est.loc[18, "significance"] == "signifikan positif (BH q<0,05)"


def test_flags_and_failures(did_outputs):
    results, _ = did_outputs
    layak = set(results.loc[results["reliability_flag"].str.startswith("layak"), "campaign_id"])
    assert layak == FINAL_LAYAK
    assert set(_est(did_outputs).loc[lambda d: ~d["far_pre_trend_ok"]].index) == FAR_PRETREND_FAILED
    assert _est(did_outputs)["pre_trend_ok"].all()  # in-window placebo passes everywhere
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
    # Verified pattern (DL-014 estimates): campaigns 8 and 13 break even only
    # at 35% margin; 18 (far-window flagged) stays negative even there; the
    # all-coupons bound is negative everywhere.
    assert est.loc[8, "margin25_per_dollar"] < 0 < est.loc[8, "margin35_per_dollar"]
    assert est.loc[13, "margin25_per_dollar"] < 0 < est.loc[13, "margin35_per_dollar"]
    assert est.loc[18, "margin35_per_dollar"] < 0
    assert (est.loc[[8, 13, 18], "margin35_per_dollar_allcoupons"] < 0).all()


def test_pooled_effect_meta_analysis(did_outputs):
    from src.did import pooled_effect

    pe = pooled_effect(did_outputs[0])
    assert pe["k"] == 14
    assert pe["att_fe"] == pytest.approx(POOLED_FE[0], abs=0.05)
    assert (pe["att_fe_ci_low"], pe["att_fe_ci_high"]) == pytest.approx(POOLED_FE[1:], abs=0.1)
    assert pe["att_re"] == pytest.approx(POOLED_RE[0], abs=0.05)
    assert pe["att_re"] > pe["att_fe"]  # heterogeneity tilts the average up
    assert pe["i_squared"] == pytest.approx(0.66, abs=0.02)  # substantial heterogeneity


def test_multiplicity_bh(did_outputs):
    est = _est(did_outputs)
    # Benjamini-Hochberg never leaves p_bh below the raw p-value
    assert (est["p_bh"] >= est["p_value"] - 1e-12).all()
    assert (est["p_bh"] <= 1.0).all()
    assert set(est.loc[est["significance"].str.startswith("signifikan")].index) == {
        8, 12, 13, 14, 16, 18, 20, 22, 23,
    }


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
