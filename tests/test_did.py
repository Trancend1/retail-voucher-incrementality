"""Phase 4 (campaign DiD) assertions.

Every estimate here is observational (R1) - treatment was assigned by the
retailer. Verified numbers live in AGENTS.md section 2.5; the redemption
anchors come from section 2.1. If numbers move after a data refresh,
re-verify AGENTS.md first - never relax a test silently.
"""

import numpy as np
import pytest

from src.did import ELIGIBLE_FLAGS, SMD_TARGET, build_campaign_design, build_campaign_results

# Verified (locked, deterministic seeds):
BACKBONE_ATT = {8: 3.18, 13: 4.76, 18: 6.29}
BACKBONE_ATT_CI = {8: (-0.24, 6.44), 13: (1.87, 7.76), 18: (3.32, 9.06)}
BACKBONE_RATIO = {8: 1.312, 13: 1.884, 18: 2.160}
BACKBONE_REDEEMERS = {8: 158, 13: 196, 18: 214}
FINAL_LAYAK = {8, 13, 18, 30}
PRETREND_FAILED = {11, 12, 14}
FLAG_COUNTS = {
    "tidak reliable — balance": 13,
    "tidak reliable": 9,
    "layak — utama (observasional)": 3,
    "tidak reliable — pre-trend & balance": 3,
    "excluded": 1,
    "layak (observasional)": 1,
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
        assert row["pre_trend_ok"]  # placebo CI contains zero
        assert row["smd_max_after"] < SMD_TARGET  # balance target met
        assert row["trim_share"] < 0.2  # healthy overlap for the backbone


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
        assert row["voucher_cost"] > 0
        assert row["inc_spend_per_dollar"] == pytest.approx(ratio, abs=0.01)
        # Verified honest finding: at grocery-like margins (15/25/35%) the
        # incremental margin per $1 voucher stays negative for the backbone.
        assert row["margin15_per_dollar"] < row["margin25_per_dollar"] < row["margin35_per_dollar"]
        assert row["margin35_per_dollar"] < 0


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
