"""Star schema invariants (Phase 8 / DL-020).

PK uniqueness, referential integrity, and row counts against the processed
parquets. The CSV export lives in data/processed/star/ (gitignored) and is
rebuilt via `python -m src.starschema`.
"""

from pathlib import Path

import pandas as pd
import pytest

from src.features import PROCESSED_DIR
from src.starschema import DIM_TABLES, STAR_DIR, build_star, load_tables

STAR_CSVS = [STAR_DIR / f"{t}.csv" for t in DIM_TABLES]


@pytest.fixture(scope="session")
def star():
    return build_star(load_tables())


def test_primary_keys_unique(star):
    assert star["dim_household"]["household_key"].is_unique
    assert star["dim_campaign"]["campaign_id"].is_unique
    assert star["dim_category"]["commodity_id"].is_unique
    assert star["dim_week"]["week_no"].is_unique
    # fact grain: no duplicate (household, week/campaign/category)
    assert not star["fact_hh_week"].duplicated(["household_key", "week_no"]).any()
    assert not star["fact_hh_campaign"].duplicated(["household_key", "campaign_id"]).any()
    assert not star["fact_hh_category"].duplicated(["household_key", "commodity_id"]).any()


def test_referential_integrity(star):
    hh = set(star["dim_household"]["household_key"])
    camp = set(star["dim_campaign"]["campaign_id"])
    cat = set(star["dim_category"]["commodity_id"])
    week = set(star["dim_week"]["week_no"])
    assert set(star["fact_hh_week"]["household_key"]) <= hh
    assert set(star["fact_hh_week"]["week_no"]) <= week
    assert set(star["fact_hh_campaign"]["household_key"]) <= hh
    assert set(star["fact_hh_campaign"]["campaign_id"]) <= camp
    assert set(star["fact_hh_category"]["household_key"]) <= hh
    assert set(star["fact_hh_category"]["commodity_id"]) <= cat


def test_row_counts_match_sources(star):
    assert len(star["dim_household"]) == 2_500
    assert len(star["dim_campaign"]) == 30
    assert len(star["dim_category"]) == 308
    assert len(star["dim_week"]) == 102
    assert len(star["fact_hh_week"]) == 255_000
    assert len(star["fact_hh_campaign"]) == 14_090
    assert len(star["fact_hh_category"]) == 288_690
    assert len(star["scenario_roi"]) == 10


def test_key_columns_and_flags(star):
    # segment is present for every household (page-2 deep dive depends on it)
    assert star["dim_household"]["segment"].notna().all()
    assert star["dim_household"]["clv_decile"].between(1, 10).all()
    # reliability flag + reason stay visible in the campaign dim (R7)
    dc = star["dim_campaign"]
    assert dc["reliability_flag"].notna().all()
    assert dc.loc[dc["reliability_flag"].str.startswith("tidak reliable"), "reliability_reason"].notna().all()
    assert dc["estimated"].sum() == 20
    # operator category flagged for exclusion from recommendations (2.4)
    op = star["dim_category"].loc[star["dim_category"]["is_operator_category"] == 1]
    assert op["commodity_desc"].tolist() == ["COUPON/MISC ITEMS"]
    # uplift decile for top-k slicers: 1..10, top-2 decile covers ~20% per campaign
    fc = star["fact_hh_campaign"]
    assert fc["uplift_decile"].between(1, 10).all()
    top2 = fc[fc["uplift_decile"] <= 2]
    assert len(top2) == 2_822
    assert fc[["score_x", "score_rfm", "delta", "att_weight"]].notna().all().all()


def test_csv_exports_exist_and_match(tmp_path):
    if not all(p.exists() for p in STAR_CSVS):
        pytest.skip("star CSVs not exported yet")
    dim = pd.read_csv(STAR_DIR / "dim_campaign.csv")
    assert len(dim) == 30
    fact = pd.read_csv(STAR_DIR / "fact_hh_week.csv")
    assert len(fact) == 255_000
    roi = pd.read_csv(STAR_DIR / "scenario_roi.csv")
    assert set(roi["campaign_set"]) == {"all", "layak"}
