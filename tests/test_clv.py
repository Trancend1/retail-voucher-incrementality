"""Phase 2 (CLV) assertions.

Verified results are recorded in AGENTS.md section 2.3. The R9 finding —
BG/NBD + Gamma-Gamma versus the naive baseline — is data, not an aspiration:
if these numbers move after a data refresh, re-verify AGENTS.md first.
"""

import numpy as np
import pandas as pd
import pytest

from src.clv import (
    CALIBRATION_END_WEEK,
    CLV_HORIZON_WEEKS,
    HOLDOUT_WEEKS,
    build_summary,
    evaluate_holdout,
    fit_bg_nbd,
    fit_gamma_gamma,
    frequency_monetary_correlation,
    predict_spending,
)
from src.features import build_rfm

# Population active by week 76: 2 of 2,500 households start after the
# calibration window and are excluded (reported, not hidden).
CALIBRATION_POPULATION = 2_498


# --- RFM --------------------------------------------------------------------


def test_rfm_anti_leakage(hh_week):
    stub = hh_week.copy()
    stub.loc[stub["week_no"] > CALIBRATION_END_WEEK, ["net_spend", "has_purchase"]] = (0.0, False)
    base = build_rfm(hh_week, CALIBRATION_END_WEEK).reset_index(drop=True)
    other = build_rfm(stub, CALIBRATION_END_WEEK).reset_index(drop=True)
    pd.testing.assert_frame_equal(base, other)


def test_rfm_quintiles_balanced_and_directional(rfm_full):
    sizes = rfm_full["f_quintile"].value_counts().sort_index().tolist()
    assert sizes == [500] * 5  # 2,500 active households, balanced first-rank quintiles
    assert rfm_full.groupby("f_quintile")["frequency"].mean().is_monotonic_increasing
    assert rfm_full.groupby("m_quintile")["monetary"].mean().is_monotonic_increasing
    assert rfm_full.groupby("r_quintile")["recency"].mean().is_monotonic_decreasing


def test_rfm_manual_spot_check(hh_week):
    hh = 1
    manual = hh_week[
        (hh_week["household_key"] == hh)
        & hh_week["has_purchase"]
        & (hh_week["week_no"] <= CALIBRATION_END_WEEK)
    ]
    row = build_rfm(hh_week, CALIBRATION_END_WEEK).set_index("household_key").loc[hh]
    assert row["frequency"] == len(manual)
    assert row["recency"] == CALIBRATION_END_WEEK - manual["week_no"].max()


# --- summary & split ---------------------------------------------------------


def test_summary_invariants(summary_cal):
    s = summary_cal
    assert len(s) == CALIBRATION_POPULATION
    assert (s["frequency"] <= s["T"]).all()
    assert (s["recency"] <= s["T"]).all()
    # lifetimes input rule: no recency without a repeat
    assert ((s["frequency"] == 0) <= (s["recency"] == 0)).all()
    assert (s["monetary"] > 0).all()
    assert int(s["T"].max()) == CALIBRATION_END_WEEK - 1


def test_summary_uses_calibration_window_only(hh_week, summary_cal):
    stub = hh_week.copy()
    stub.loc[stub["week_no"] > CALIBRATION_END_WEEK, "net_spend"] = 999.0
    other = build_summary(stub, CALIBRATION_END_WEEK)
    pd.testing.assert_frame_equal(summary_cal.reset_index(drop=True), other.reset_index(drop=True))


# --- BG/NBD & predictions ----------------------------------------------------


def test_bgnbd_predictions_bounded(bgf_cal, ggf_cal, summary_cal):
    pred = predict_spending(bgf_cal, ggf_cal, summary_cal, HOLDOUT_WEEKS)
    assert len(pred) == len(summary_cal)
    assert (pred["predicted_purchases"] >= 0).all()
    # Weekly grain caps activity at one 'transaction' per week.
    assert float(pred["predicted_purchases"].quantile(0.99)) <= HOLDOUT_WEEKS
    assert pred["p_alive"].between(0, 1).all()


# --- Gamma-Gamma & CLV -------------------------------------------------------


def test_frequency_monetary_correlation_reported(summary_cal):
    rho = frequency_monetary_correlation(summary_cal)["spearman_rho"]
    # Verified ~0.43: the Gamma-Gamma independence assumption is materially
    # violated and documented as a limitation.
    assert 0.30 < rho < 0.60


def test_clv_52w_finite_and_nonnegative(hh_week):
    s_full = build_summary(hh_week, 102)
    pred = predict_spending(fit_bg_nbd(s_full), fit_gamma_gamma(s_full), s_full, CLV_HORIZON_WEEKS)
    assert len(pred) == 2_500
    assert (pred["predicted_spend"] >= 0).all()
    assert np.isfinite(pred["predicted_spend"]).all()


# --- holdout evaluation (R9) --------------------------------------------------


def test_holdout_metrics_locked(holdout_metrics):
    m = holdout_metrics
    assert m["n_households"] == CALIBRATION_POPULATION
    # R9 verdict (verified): the model LOSES to the naive per-household baseline.
    assert m["mae_model"] == pytest.approx(322.19, abs=0.5)
    assert m["mae_naive"] == pytest.approx(307.64, abs=0.5)
    assert m["mae_diff_p2.5"] > 0  # CI excludes zero: the loss is robust
    assert m["p_model_worse"] == 1.0


def test_bootstrap_reproducible(hh_week, bgf_cal, ggf_cal, summary_cal):
    m1, _ = evaluate_holdout(hh_week, bgf_cal, ggf_cal, summary_cal, n_bootstrap=50)
    m2, _ = evaluate_holdout(hh_week, bgf_cal, ggf_cal, summary_cal, n_bootstrap=50)
    assert m1 == m2
