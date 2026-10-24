"""Data-quality assertions for Phase 0-1 step L1 (docs/sprint-p1.md section 7).

Checkpoint numbers come from verified facts in AGENTS.md section 2/3.1
(verified 2026-10-23). If any of these tests fail after a data refresh,
re-verify AGENTS.md section 2 first — do not relax the test silently.
"""

import pytest

from src.features import (
    LAST_OBSERVED_DAY,
    build_campaign_timeline,
    build_day_week_bridge,
    load_campaign_desc,
    load_campaign_treated,
    read_day_week_pairs,
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


@pytest.fixture(scope="session")
def bridge():
    return build_day_week_bridge(read_day_week_pairs())


@pytest.fixture(scope="session")
def timeline(bridge):
    return build_campaign_timeline(load_campaign_desc(), load_campaign_treated(), bridge)


def test_bridge_covers_102_contiguous_weeks_ending_at_711(bridge):
    assert bridge["week_no"].tolist() == list(range(1, 103))
    assert int(bridge["min_day"].iloc[0]) == 1
    assert int(bridge["max_day"].iloc[-1]) == LAST_OBSERVED_DAY


def test_bridge_matches_known_irregular_week_boundaries(bridge):
    # AGENTS.md section 3 trap 3: week 1 = days 1-5, week 2 = days 6-12.
    assert bridge.iloc[0][["min_day", "max_day"]].tolist() == [1, 5]
    assert bridge.iloc[1][["min_day", "max_day"]].tolist() == [6, 12]


def test_timeline_shape_and_columns(timeline):
    assert len(timeline) == 30
    assert set(timeline.columns) == EXPECTED_COLUMNS
    assert set(timeline["type"]) == {"A", "B", "C"}


def test_type_mix_matches_verified_counts(timeline):
    # Read from the full campaign_desc.csv on 2026-10-24: A=5, B=19, C=6.
    counts = timeline["type"].value_counts().to_dict()
    assert counts == {"B": 19, "A": 5, "C": 6}


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
    # Verified against the observed WEEK_NO column (L1, 2026-10-24): day 224
    # falls in week 33. The old note "minggu 32" in AGENTS.md section 2 came
    # from the naive floor((DAY-1)/7)+1 formula (trap 3.3) and was corrected.
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
