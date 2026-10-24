"""Data-quality assertions for the Phase 0-1 panel and timeline.

The hardcoded numbers below are verified facts recorded in AGENTS.md
section 2 (subsection 2.2 for phase results). If the raw data is ever
replaced, some of these tests will fail by design: re-verify the facts in
AGENTS.md first, then update the expected values — never relax or skip a
test silently.
"""

import numpy as np
import pandas as pd
import pytest

from src.features import (
    LAST_OBSERVED_DAY,
    N_COMMODITIES,
    build_hh_campaign,
    load_campaign_desc,
    load_campaign_treated,
    product_join_coverage,
)

EXPECTED_COLUMNS = {
    "campaign_id",
    "type",
    "start_day",
    "end_day",
    "start_week",
    "end_week",
    "n_treated",
    "overlaps_with",
    "n_overlaps",
    "truncated_flag",
}

# Session fixtures (bridge, timeline, sanity, hh_week, hh_category,
# households, eligible_timeline) are shared from conftest.py.


# --- day-week bridge -------------------------------------------------------


def test_bridge_covers_102_contiguous_weeks_ending_at_711(bridge):
    assert bridge["week_no"].tolist() == list(range(1, 103))
    assert int(bridge["min_day"].iloc[0]) == 1
    assert int(bridge["max_day"].iloc[-1]) == LAST_OBSERVED_DAY


def test_bridge_matches_known_irregular_week_boundaries(bridge):
    # Week 1 covers days 1-5 and week 2 days 6-12: retailer weeks are not
    # always 7 days, hence the bridge instead of deriving week from day.
    assert bridge.iloc[0][["min_day", "max_day"]].tolist() == [1, 5]
    assert bridge.iloc[1][["min_day", "max_day"]].tolist() == [6, 12]


# --- campaign timeline -----------------------------------------------------


def test_timeline_shape_and_columns(timeline):
    assert len(timeline) == 30
    assert set(timeline.columns) == EXPECTED_COLUMNS
    assert set(timeline["type"]) == {"A", "B", "C"}


def test_type_mix_matches_verified_counts(timeline):
    assert timeline["type"].value_counts().to_dict() == {"B": 19, "A": 5, "C": 6}


def test_overlap_pairs_total_74(timeline):
    # 74 unordered overlapping pairs -> 148 directed counts.
    assert int(timeline["n_overlaps"].sum()) == 148


def test_campaign15_overlaps_12_others(timeline):
    row = timeline.loc[timeline["campaign_id"] == 15].iloc[0]
    assert row["n_overlaps"] == 12


def test_campaign21_22_identical_windows_and_mutual_overlap(timeline):
    r21 = timeline.loc[timeline["campaign_id"] == 21].iloc[0]
    r22 = timeline.loc[timeline["campaign_id"] == 22].iloc[0]
    assert (r21["start_day"], r21["end_day"]) == (624, 656)
    assert (r22["start_day"], r22["end_day"]) == (624, 656)
    assert "22" in str(r21["overlaps_with"]).split(",")
    assert "21" in str(r22["overlaps_with"]).split(",")


def test_only_campaign24_truncated(bridge, timeline):
    assert timeline.loc[timeline["truncated_flag"], "campaign_id"].tolist() == [24]
    row = timeline.loc[timeline["campaign_id"] == 24].iloc[0]
    assert row["end_day"] == 719
    assert row["end_week"] == int(bridge["week_no"].iloc[-1])  # clamped


def test_n_treated_range_backbone_and_total(timeline):
    treated = timeline.set_index("campaign_id")["n_treated"]
    assert int(treated.min()) == 12
    assert int(treated.max()) == 1133
    assert int(treated[8]) == 1076
    assert int(treated[13]) == 1077
    assert int(treated[18]) == 1133
    assert int(timeline["n_treated"].sum()) == 7208


def test_earliest_campaign_starts_week_33(timeline):
    # Day 224 falls in week 33 per the observed WEEK_NO column; the old
    # "week 32" note came from the naive floor((DAY-1)/7)+1 formula.
    assert int(timeline["start_week"].min()) == 33
    row = timeline.loc[timeline["campaign_id"] == 26].iloc[0]
    assert (row["start_day"], row["start_week"]) == (224, 33)


def test_overlaps_symmetric(timeline):
    overlap_sets = {
        int(r.campaign_id): {int(c) for c in str(r.overlaps_with).split(",") if c}
        for r in timeline.itertuples()
    }
    for a, partners in overlap_sets.items():
        for b in partners:
            assert a in overlap_sets[b], f"asymmetric overlap: {a} lists {b} but not vice versa"


def test_campaign_table_type_consistent_with_desc():
    desc = load_campaign_desc()
    treated = load_campaign_treated()
    merged = treated.merge(desc[["campaign_id", "type"]], on="campaign_id", suffixes=("_tbl", "_desc"))
    assert len(merged) == len(treated) == 7208  # every row matched a known campaign
    assert (merged["type_tbl"] == merged["type_desc"]).all()


# --- spend sanity ----------------------------------------------------------


def test_spend_sanity_confirms_DL001_DL002_counts(sanity):
    assert sanity["n_rows"] == 2_595_732
    assert sanity["n_sales_value_le0"] == 18_850
    assert sanity["n_net_lt0"] == 80_890
    assert sanity["net_min"] < 0  # return rows exist as negative net (kept, not dropped)


# --- hh_week panel ---------------------------------------------------------


def test_panel_balanced_2500_by_102_unique(hh_week):
    assert len(hh_week) == 255_000
    assert not hh_week.duplicated(["household_key", "week_no"]).any()
    assert hh_week["household_key"].nunique() == 2_500
    assert hh_week["week_no"].min() == 1 and hh_week["week_no"].max() == 102
    assert (hh_week.groupby("household_key")["week_no"].nunique() == 102).all()


def test_panel_net_conserved_vs_row_level(hh_week, sanity):
    # Panel net_spend must equal the row-level net total (DL-001 consistency).
    assert hh_week["net_spend"].sum() == pytest.approx(sanity["net_sum"], rel=1e-6)


def test_panel_promo_share_dl004(hh_week):
    ps = hh_week["promo_share"]
    assert ps.min(skipna=True) >= 0
    # NA exactly when the week has no valid-denominator row (DL-004)
    assert ps.isna().equals(~(hh_week["promo_denominator"] > 0))
    # DL-004 sanity bound: p99 <= 1 (the thin >1 tail is documented, not capped)
    assert ps.quantile(0.99) <= 1.0


def test_panel_recency_dl005(hh_week):
    active = hh_week[hh_week["has_purchase"]]
    assert (active["recency_weeks"] == 0).all()
    # NA exactly on weeks before the household's first purchase
    first = active.groupby("household_key")["week_no"].min()
    merged = hh_week.merge(first.rename("first_week"), on="household_key")
    pre_first = merged["week_no"] < merged["first_week"]
    assert merged.loc[pre_first, "recency_weeks"].isna().all()
    assert merged.loc[~pre_first, "recency_weeks"].notna().all()
    # Independent brute-force recheck on a deterministic sample (seed 42)
    rng = np.random.default_rng(42)
    for hh in rng.choice(merged["household_key"].unique(), size=10, replace=False):
        sub = merged[merged["household_key"] == hh]
        weeks_active = sorted(sub.loc[sub["has_purchase"], "week_no"])
        for row in sub.itertuples():
            if int(row.week_no) < weeks_active[0]:
                assert pd.isna(row.recency_weeks)
            else:
                last = max(a for a in weeks_active if a <= int(row.week_no))
                assert int(row.recency_weeks) == int(row.week_no) - last


def test_panel_return_flag_dl002(hh_week):
    # Suspect weeks are flagged; the underlying rows stay in the aggregation.
    assert int(hh_week["has_return"].sum()) == 43_478
    assert (hh_week.loc[hh_week["has_return"], "n_suspect_rows"] > 0).all()


# --- product coverage and hh_category --------------------------------------


def test_product_join_coverage_is_complete():
    cov = product_join_coverage()
    assert cov["n_txn_rows"] == 2_595_732
    assert cov["n_unmatched_rows"] == 0
    assert cov["row_coverage"] == 1.0


def test_hh_category_grain_and_total(hh_category, sanity):
    assert not hh_category.duplicated(["household_key", "commodity_desc"]).any()
    assert hh_category["commodity_desc"].nunique() == N_COMMODITIES
    assert hh_category["net_spend"].sum() == pytest.approx(sanity["net_sum"], rel=1e-6)


# --- treatment map ---------------------------------------------------------


def test_hh_campaign_map(timeline):
    hh_c = build_hh_campaign(load_campaign_treated(), timeline)
    assert len(hh_c) == 7_208
    assert not hh_c.duplicated(["household_key", "campaign_id"]).any()
    assert (hh_c["n_weeks_window"] >= 1).all()
    assert bool(hh_c["truncated_flag"].sum())  # campaign 24 rows carry the flag


# --- control pool and eligibility ------------------------------------------


def test_control_pool_bounds_and_backbone(eligible_timeline):
    tl = eligible_timeline
    assert (tl["n_control_pool"] <= 2_500 - tl["n_treated"]).all()
    backbone = tl.set_index("campaign_id").loc[[8, 13, 18], "n_control_pool"]
    assert (backbone > 1_000).all()  # verified: 1359 / 1374 / 1251


def test_eligibility_flags_match_verified_structure(eligible_timeline):
    tl = eligible_timeline.set_index("campaign_id")
    assert tl.loc[15, "reliability_flag"] == "excluded"
    assert tl.loc[24, "reliability_flag"] == "tidak reliable"
    assert (tl.loc[[8, 13, 18], "reliability_flag"] == "layak — utama").all()
    small = set(tl.index[tl["n_treated"] < 100])
    assert small == {1, 2, 3, 4, 6, 15, 21, 27, 28}
    assert (tl.loc[list(small - {15}), "reliability_flag"] == "tidak reliable").all()
    counts = eligible_timeline["reliability_flag"].value_counts().to_dict()
    assert counts == {"layak": 17, "tidak reliable": 9, "layak — utama": 3, "excluded": 1}
