"""Phase 5 (segmentation) assertions.

Verified results live in AGENTS.md section 2.6. Segments are descriptive
only (never model features); thresholds come from this panel's own
distributions (DL-015). If numbers move after a data refresh, re-verify
AGENTS.md first.
"""

import numpy as np
import pandas as pd
import pytest

import src.segments as seg
from src.features import MIN_REPORTABLE_N

# Verified (locked, deterministic seeds):
EXPECTED_SIZES = {1: 1099, 2: 972, 3: 429}
ARI_MEDIAN = 0.646
GAP_P95 = 5.0
RATIO_P10 = 0.419
CHURN_OVERALL = 0.146  # share of members flagged churn-risk
SEG3_CHURN = 39.16  # the at-risk segment concentrates churn
SEG2_PROMO = 0.23  # the mid segment is the most promo-dependent


# --- features ----------------------------------------------------------------


def test_features_complete_and_shares_sum_to_one(seg_full):
    raw, departments = seg_full
    assert len(raw) == 2_500
    assert len(departments) == 44
    assert not raw.isna().any().any()
    share_cols = [c for c in raw.columns if c not in ("household_key",) and c not in seg.BASE_FEATURES]
    sums = raw[share_cols].sum(axis=1)
    assert ((sums - 1.0).abs() < 1e-9).all()


def test_core_mask_excludes_top_percent(seg_full):
    raw, _ = seg_full
    n_core = int(seg.core_mask(raw).sum())
    assert 2_470 <= n_core <= 2_480  # ~1% extreme spenders excluded from fitting
    assert raw.loc[~seg.core_mask(raw), "monetary"].min() > raw["monetary"].quantile(0.98)


# --- model & stability ---------------------------------------------------------


def test_final_segments_sizes_and_deterministic(seg_full, segments):
    sizes = segments.groupby("segment").size().to_dict()
    assert sizes == EXPECTED_SIZES
    assert min(sizes.values()) >= MIN_REPORTABLE_N  # R8
    raw, departments = seg_full
    again, _, _ = seg.fit_segments(raw, departments)
    pd.testing.assert_frame_equal(segments, again)


def test_stability_ari_locked(seg_full, seg_periods):
    raw, departments = seg_full
    p1, p2 = seg_periods
    aris = seg.stability_ari(p1, p2, departments, seg.K_FINAL)
    assert np.median(aris) == pytest.approx(ARI_MEDIAN, abs=0.01)
    assert min(aris) > 0.60  # seed-robust structure
    assert seg.K_FINAL == 5


# --- churn thresholds from data --------------------------------------------------


def test_churn_thresholds_and_flags(hh_week):
    thresholds = seg.churn_thresholds(hh_week)
    assert thresholds["gap_p95"] == pytest.approx(GAP_P95, abs=0.01)
    assert thresholds["ratio_p10"] == pytest.approx(RATIO_P10, abs=0.005)
    flags = seg.churn_flags(hh_week, thresholds)
    assert len(flags) == 2_500
    assert flags["churn_risk"].mean() == pytest.approx(CHURN_OVERALL, abs=0.005)
    assert flags["spend_dropping"].mean() == pytest.approx(0.10, abs=0.01)


# --- segment table (gate #3) ------------------------------------------------------


def test_segment_table_gate_columns(segment_table):
    t = segment_table
    required = {"segment", "n", "share_pct", "mean_weekly_spend_active", "mean_total_spend",
                "promo_dependence", "churn_risk_pct", "spend_dropping_pct",
                "whitespace_utama", "satu_aksi"}
    assert required.issubset(t.columns)
    assert int(t["n"].sum()) == 2_500
    assert t["satu_aksi"].str.len().gt(0).all()
    assert t["satu_aksi"].nunique() == len(t)  # one distinct action per segment
    # operator category excluded from recommendations (Phase 3 finding)
    assert "COUPON/MISC" not in " ".join(t["whitespace_utama"])


def test_segment_profiles_locked(segment_table):
    t = segment_table.set_index("segment")
    assert t.loc[3, "churn_risk_pct"] == pytest.approx(SEG3_CHURN, abs=0.5)
    assert t.loc[2, "promo_dependence"] == pytest.approx(SEG2_PROMO, abs=0.01)
    assert t.loc[2, "promo_dependence"] == t["promo_dependence"].max()
    assert t.loc[1, "mean_total_spend"] == t["mean_total_spend"].max()
