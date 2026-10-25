"""Star schema build for the Power BI deliverable (Phase 8, DL-020).

Exports 7 star-schema tables plus the ROI scenario table as CSV to
data/processed/star/ (gitignored; rebuilt with `python -m src.starschema`).
Grain decisions:

- dim_category is at COMMODITY level (308 rows) - the grain fact_hh_category
  actually has - with the parent DEPARTMENT attached via product.csv mapping.
- dim_campaign carries the campaign-level DiD/ROI result columns as
  attributes (one row per campaign): practical for visuals, and the
  reliability flag + reason stay visible (R7).
- fact_hh_campaign = the held-out campaign evaluation panel
  (household x campaign, treated + control, uplift scores, weights) with an
  uplift_decile column (1 = highest score_x within campaign) for top-k
  slicers on the Voucher Efficiency page.

All numbers are the verified ones from data/processed parquets - this module
never recomputes an estimate.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.features import DATA_DIR, PROCESSED_DIR

STAR_DIR = PROCESSED_DIR / "star"

# commodity -> department mapping source (raw master, read once, cheap)
PRODUCT_CSV = DATA_DIR / "product.csv"

DIM_TABLES = [
    "dim_household", "dim_campaign", "dim_category", "dim_week",
    "fact_hh_week", "fact_hh_campaign", "fact_hh_category", "scenario_roi",
]


def _commodity_department_map() -> pd.DataFrame:
    con = duckdb.connect()
    try:
        m = con.execute(
            """
            SELECT COMMODITY_DESC AS commodity_desc,
                   ANY_VALUE(DEPARTMENT) AS department,
                   COUNT(DISTINCT PRODUCT_ID) AS n_products
            FROM read_csv_auto(?)
            GROUP BY COMMODITY_DESC
            """,
            [str(PRODUCT_CSV)],
        ).df()
    finally:
        con.close()
    conflicts = m["commodity_desc"].duplicated().sum()
    if conflicts:
        raise ValueError("commodity->department mapping is not unique")
    return m


def build_star(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Assemble the star tables from processed parquets."""
    hh_clv = tables["hh_clv"]
    segments = tables["segments"]
    timeline = tables["campaign_timeline"]
    did = tables["campaign_did_results"]
    hh_week = tables["hh_week"]
    scores = tables["uplift_scores"]
    hh_cat = tables["hh_category"]

    # --- dims ---------------------------------------------------------------
    dim_household = (
        hh_clv[["household_key", "first_active_week", "last_active_week",
                "frequency", "total_net_spend", "r_quintile", "f_quintile",
                "m_quintile", "clv_52w"]]
        .merge(segments[["household_key", "segment"]], on="household_key", validate="1:1")
        .copy()
    )
    dim_household["clv_decile"] = pd.qcut(
        dim_household["clv_52w"].rank(method="first"), 10, labels=False
    ).astype(int) + 1

    # timeline and did both carry reliability columns; keep the DiD versions
    # (same foundation flags, plus per-campaign result reasons for all 30)
    dim_campaign = timeline.drop(columns=["reliability_flag", "eligibility_reason"]).merge(
        did[
            ["campaign_id", "estimated", "reliability_flag", "reliability_reason",
             "att", "att_ci_low", "att_ci_high", "lift_pct", "significance",
             "inc_spend_per_dollar", "inc_spend_per_dollar_allcoupons"]
        ],
        on="campaign_id",
        how="left",
        validate="1:1",
    )
    dim_campaign["estimated"] = dim_campaign["estimated"].fillna(False).astype(bool)
    if dim_campaign["reliability_flag"].isna().any():
        raise ValueError("campaigns missing reliability flag after merge")

    cmap = _commodity_department_map()
    dim_category = hh_cat[["commodity_desc"]].drop_duplicates().merge(
        cmap, on="commodity_desc", how="left", validate="1:1"
    )
    if dim_category["department"].isna().any():
        raise ValueError("unmapped commodity in fact_hh_category")
    dim_category = dim_category.sort_values("commodity_desc").reset_index(drop=True)
    dim_category.insert(0, "commodity_id", np.arange(1, len(dim_category) + 1))
    dim_category["is_operator_category"] = (
        dim_category["commodity_desc"] == "COUPON/MISC ITEMS"
    ).astype(int)

    dim_week = pd.DataFrame(
        {"week_no": np.arange(1, 103),
         "label": [f"minggu {w}" for w in range(1, 103)]}
    )

    # --- facts ---------------------------------------------------------------
    fact_hh_week = hh_week[
        ["household_key", "week_no", "net_spend", "n_baskets", "n_products",
         "category_breadth", "has_purchase", "has_return", "promo_share"]
    ].copy()

    fact_hh_campaign = scores.copy()
    # uplift decile of score_x within campaign (1 = highest) for top-k slicers
    ranks = fact_hh_campaign.groupby("campaign_id")["score_x"].rank(
        ascending=False, method="first"
    )
    sizes = fact_hh_campaign.groupby("campaign_id")["score_x"].transform("size")
    fact_hh_campaign["uplift_decile"] = ((ranks - 1) * 10 // sizes + 1).astype(int)

    fact_hh_category = hh_cat.merge(
        dim_category[["commodity_id", "commodity_desc"]],
        on="commodity_desc",
        how="left",
        validate="m:1",
    )[["household_key", "commodity_id", "net_spend", "n_weeks_active"]].copy()

    scenario_roi = tables["roi_scenarios"].copy()

    return {
        "dim_household": dim_household,
        "dim_campaign": dim_campaign,
        "dim_category": dim_category,
        "dim_week": dim_week,
        "fact_hh_week": fact_hh_week,
        "fact_hh_campaign": fact_hh_campaign,
        "fact_hh_category": fact_hh_category,
        "scenario_roi": scenario_roi,
    }


def load_tables() -> dict[str, pd.DataFrame]:
    names = ["hh_clv", "segments", "campaign_timeline", "campaign_did_results",
             "hh_week", "uplift_scores", "hh_category", "roi_scenarios"]
    return {n: pd.read_parquet(PROCESSED_DIR / f"{n}.parquet") for n in names}


def export_star() -> dict[str, pd.DataFrame]:
    star = build_star(load_tables())
    STAR_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in star.items():
        df.to_csv(STAR_DIR / f"{name}.csv", index=False)
    return star


def main() -> None:
    star = export_star()
    for name, df in star.items():
        print(f"{name:20s} {df.shape[0]:>8,} baris × {df.shape[1]} kolom -> star/{name}.csv")


if __name__ == "__main__":
    main()
