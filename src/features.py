"""Panel & timeline builders — Phase 0-1 (docs/sprint-p1.md, step L1).

All functions are deterministic (no randomness). Inputs are raw CSVs with
UPPER_CASE columns; outputs are processed tables in snake_case (AGENTS.md
conventions). Metric definitions that bind all phases live in
docs/decision-log.md (DL-001..DL-005); reference facts in AGENTS.md section 2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import duckdb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
TRANSACTION_CSV = DATA_DIR / "transaction_data.csv"
CAMPAIGN_DESC_CSV = DATA_DIR / "campaign_desc.csv"
CAMPAIGN_TABLE_CSV = DATA_DIR / "campaign_table.csv"
PRODUCT_CSV = DATA_DIR / "product.csv"

# Verified: WEEK_NO spans 1..102 (AGENTS.md section 2). The balanced panel
# uses this fixed grid; zero-activity weeks are real information (tenure,
# recency), not missing data.
N_WEEKS = 102

# Backbone TypeA campaigns for the main DiD estimation (AGENTS.md section 2.1).
BACKBONE_CAMPAIGNS = (8, 13, 18)
# Campaign 15: TypeC, 161 days, overlaps 12 other campaigns, swallows ~23
# weeks -> kept out of the main estimation (AGENTS.md section 2.1).
EXCLUDED_FROM_MAIN_ESTIMATION = (15,)

# Last DAY observed in transaction_data (AGENTS.md section 2). Campaign
# windows ending after this day cannot be mapped to an observed week, so the
# end week is clamped to the last observed week and truncated_flag is set.
LAST_OBSERVED_DAY = 711

PathLike = Union[str, Path]


def read_day_week_pairs(csv_path: PathLike = TRANSACTION_CSV) -> pd.DataFrame:
    """Distinct (week_no, day) pairs from transactions, pushed down to DuckDB.

    The day->week bridge MUST be built from observed WEEK_NO, never from
    floor((DAY-1)/7)+1 — that formula only matches ~73% of rows because
    retailer weeks do not always have 7 days (AGENTS.md section 3, trap 3).
    """
    query = "SELECT WEEK_NO, DAY FROM read_csv_auto(?) GROUP BY WEEK_NO, DAY"
    con = duckdb.connect()
    try:
        pairs = con.execute(query, [str(csv_path)]).df()
    finally:
        con.close()
    return pairs.rename(columns={"WEEK_NO": "week_no", "DAY": "day"})


def build_day_week_bridge(pairs: pd.DataFrame) -> pd.DataFrame:
    """Min/max observed day per week: columns week_no, min_day, max_day.

    Fails fast (AssertionError) if weeks are not contiguous 1..N or if the
    day intervals are not adjacent — both would make the bridge unusable.
    """
    bridge = (
        pairs.groupby("week_no")["day"]
        .agg(["min", "max"])
        .rename(columns={"min": "min_day", "max": "max_day"})
        .sort_index()
        .reset_index()
    )
    weeks = bridge["week_no"].tolist()
    if weeks != list(range(1, len(bridge) + 1)):
        raise AssertionError(f"weeks must be contiguous 1..{len(bridge)}, got {weeks[:10]}")
    if int(bridge["min_day"].iloc[0]) != 1:
        raise AssertionError("bridge must start at day 1")
    gaps = bridge["min_day"].to_numpy()[1:] - bridge["max_day"].to_numpy()[:-1]
    if not (gaps == 1).all():
        raise AssertionError("day intervals must be adjacent (no gap/overlap between weeks)")
    return bridge


def map_day_to_week(bridge: pd.DataFrame, day: int, clamp_to_data: bool = True) -> int:
    """Week containing `day`, via the observed bridge.

    Days beyond the last observed day clamp to the last observed week (only
    truncated campaigns; flagged separately via truncated_flag).
    """
    last_day = int(bridge["max_day"].max())
    if day > last_day:
        if not clamp_to_data:
            raise ValueError(f"day {day} is beyond observed data (max {last_day})")
        return int(bridge["week_no"].iloc[-1])
    hit = bridge[(bridge["min_day"] <= day) & (bridge["max_day"] >= day)]
    if len(hit) != 1:
        raise ValueError(f"day {day} is not covered by the bridge")
    return int(hit["week_no"].iloc[0])


def load_campaign_desc(csv_path: PathLike = CAMPAIGN_DESC_CSV) -> pd.DataFrame:
    """campaign_desc normalized: campaign_id, type, start_day, end_day."""
    desc = pd.read_csv(csv_path).rename(
        columns={
            "DESCRIPTION": "type",
            "CAMPAIGN": "campaign_id",
            "START_DAY": "start_day",
            "END_DAY": "end_day",
        }
    )
    desc["type"] = desc["type"].str.removeprefix("Type")  # 'TypeA' -> 'A'
    if desc["campaign_id"].duplicated().any():
        raise AssertionError("campaign_desc must have unique campaign_id")
    return desc


def load_campaign_treated(csv_path: PathLike = CAMPAIGN_TABLE_CSV) -> pd.DataFrame:
    """campaign_table normalized: type, household_key, campaign_id."""
    treated = pd.read_csv(csv_path).rename(
        columns={"DESCRIPTION": "type", "household_key": "household_key", "CAMPAIGN": "campaign_id"}
    )
    treated["type"] = treated["type"].str.removeprefix("Type")  # 'TypeA' -> 'A'
    return treated


def build_campaign_timeline(
    campaign_desc: pd.DataFrame,
    campaign_table: pd.DataFrame,
    bridge: pd.DataFrame,
) -> pd.DataFrame:
    """Campaign timeline with the Phase 0-1 quality-gate columns.

    - overlaps_with: comma-separated campaign ids whose [start_day, end_day]
      interval intersects this campaign's (inclusive; symmetric by design).
    - start_week/end_week via the observed day->week bridge; an end day beyond
      LAST_OBSERVED_DAY clamps to the last observed week.
    - truncated_flag: end_day > LAST_OBSERVED_DAY.
    - n_treated: households per campaign in campaign_table.
    """
    desc = campaign_desc.sort_values("campaign_id").reset_index(drop=True)
    unknown = set(campaign_table["campaign_id"]) - set(desc["campaign_id"])
    if unknown:
        raise AssertionError(f"campaign_table references unknown campaigns: {sorted(unknown)}")
    n_treated = campaign_table.groupby("campaign_id")["household_key"].size()

    rows = []
    for r in desc.itertuples():
        overlapping = desc[
            (desc["campaign_id"] != r.campaign_id)
            & (desc["start_day"] <= r.end_day)
            & (desc["end_day"] >= r.start_day)
        ]
        rows.append(
            {
                "campaign_id": int(r.campaign_id),
                "type": r.type,
                "start_day": int(r.start_day),
                "end_day": int(r.end_day),
                "start_week": map_day_to_week(bridge, int(r.start_day)),
                "end_week": map_day_to_week(bridge, int(r.end_day)),
                "n_treated": int(n_treated.get(r.campaign_id, 0)),
                "overlaps_with": ",".join(str(c) for c in sorted(overlapping["campaign_id"].tolist())),
                "n_overlaps": int(len(overlapping)),
                "truncated_flag": bool(r.end_day > LAST_OBSERVED_DAY),
            }
        )
    return pd.DataFrame(rows)


def save_parquet(df: pd.DataFrame, out_path: PathLike) -> Path:
    """Write a processed artifact (data/processed is gitignored, rule R11)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out


# ---------------------------------------------------------------------------
# L2 — spend sanity (DL-001 / DL-002 confirmation)
# ---------------------------------------------------------------------------


def spend_sanity(csv_path: PathLike = TRANSACTION_CSV) -> dict:
    """Row-level spend sanity stats, pushed down to DuckDB.

    Confirms the DL-001 definition (net = SALES_VALUE + all discounts) and the
    DL-002 return policy inputs: counts of rows with SALES_VALUE <= 0 and
    rows with net < 0, plus the net distribution and the promo_share
    denominator-valid row count (DL-004).
    """
    query = """
        SELECT
            COUNT(*) AS n_rows,
            SUM(CASE WHEN SALES_VALUE <= 0 THEN 1 ELSE 0 END) AS n_sales_value_le0,
            SUM(CASE WHEN SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC < 0
                     THEN 1 ELSE 0 END) AS n_net_lt0,
            SUM(CASE WHEN SALES_VALUE > 0 THEN 1 ELSE 0 END) AS n_denominator_valid,
            SUM(SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) AS net_sum,
            MIN(SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) AS net_min,
            MEDIAN(SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) AS net_p50,
            QUANTILE_CONT(SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC, 0.99) AS net_p99,
            MAX(SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) AS net_max
        FROM read_csv_auto(?)
    """
    con = duckdb.connect()
    try:
        row = con.execute(query, [str(csv_path)]).fetchone()
    finally:
        con.close()
    keys = [
        "n_rows",
        "n_sales_value_le0",
        "n_net_lt0",
        "n_denominator_valid",
        "net_sum",
        "net_min",
        "net_p50",
        "net_p99",
        "net_max",
    ]
    return dict(zip(keys, row))


# ---------------------------------------------------------------------------
# L3 — balanced hh_week panel (DL-001, DL-002, DL-004, DL-005)
# ---------------------------------------------------------------------------

_HH_WEEK_AGG_SQL = """
SELECT
    household_key,
    WEEK_NO,
    SUM(SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) AS net_spend,
    COUNT(DISTINCT BASKET_ID) AS n_baskets,
    COUNT(DISTINCT PRODUCT_ID) AS n_products,
    SUM(SALES_VALUE) AS sales_value_sum,
    SUM(ABS(RETAIL_DISC)) AS abs_retail_disc_sum,
    SUM(ABS(COUPON_DISC)) AS abs_coupon_disc_sum,
    SUM(CASE WHEN SALES_VALUE > 0 THEN SALES_VALUE ELSE 0 END) AS promo_denominator,
    SUM(CASE WHEN SALES_VALUE > 0 THEN ABS(RETAIL_DISC) + ABS(COUPON_DISC) ELSE 0 END) AS promo_numerator,
    SUM(CASE WHEN SALES_VALUE <= 0
              OR (SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) < 0
             THEN 1 ELSE 0 END) AS n_suspect_rows
FROM read_csv_auto(?)
GROUP BY household_key, WEEK_NO
"""

_HH_WEEK_BREADTH_SQL = """
SELECT
    t.household_key,
    t.WEEK_NO AS week_no,
    COUNT(DISTINCT p.COMMODITY_DESC) AS category_breadth
FROM read_csv_auto(?) t
JOIN read_csv_auto(?) p ON t.PRODUCT_ID = p.PRODUCT_ID
GROUP BY t.household_key, t.WEEK_NO
"""


def aggregate_hh_week(csv_path: PathLike = TRANSACTION_CSV) -> pd.DataFrame:
    """Per household-week transaction aggregates (DuckDB pushdown)."""
    con = duckdb.connect()
    try:
        agg = con.execute(_HH_WEEK_AGG_SQL, [str(csv_path)]).df()
    finally:
        con.close()
    return agg.rename(columns={"WEEK_NO": "week_no"})


def aggregate_hh_breadth(
    txn_csv: PathLike = TRANSACTION_CSV, product_csv: PathLike = PRODUCT_CSV
) -> pd.DataFrame:
    """Distinct COMMODITY_DESC per household-week (inner join: unmatched
    products never fake a category; coverage reported separately)."""
    con = duckdb.connect()
    try:
        breadth = con.execute(_HH_WEEK_BREADTH_SQL, [str(txn_csv), str(product_csv)]).df()
    finally:
        con.close()
    return breadth


def build_hh_week(
    txn_csv: PathLike = TRANSACTION_CSV,
    product_csv: PathLike = PRODUCT_CSV,
    n_weeks: int = N_WEEKS,
) -> pd.DataFrame:
    """Balanced panel: one row per (household_key, week_no), weeks 1..n_weeks.

    - net_spend per DL-001; returns stay in via net aggregation (DL-002).
    - promo_share per DL-004: numerator/denominator only over rows with
      SALES_VALUE > 0; weeks without such rows get NA (not 0).
    - recency_weeks per DL-005: 0 on active weeks, NA before the household's
      first purchase.
    """
    agg = aggregate_hh_week(txn_csv)
    breadth = aggregate_hh_breadth(txn_csv, product_csv)
    observed = agg.merge(breadth, on=["household_key", "week_no"], how="left")

    households = np.sort(observed["household_key"].unique())
    grid = pd.MultiIndex.from_product(
        [households, range(1, n_weeks + 1)], names=["household_key", "week_no"]
    ).to_frame(index=False)
    panel = grid.merge(observed, on=["household_key", "week_no"], how="left")

    value_cols = [
        "net_spend",
        "sales_value_sum",
        "abs_retail_disc_sum",
        "abs_coupon_disc_sum",
        "promo_denominator",
        "promo_numerator",
    ]
    count_cols = ["n_baskets", "n_products", "n_suspect_rows"]
    panel[value_cols] = panel[value_cols].fillna(0.0)
    panel[count_cols] = panel[count_cols].fillna(0).astype("int32")
    panel["category_breadth"] = panel["category_breadth"].fillna(0).astype("int32")

    panel["has_purchase"] = panel["n_baskets"] > 0
    panel["has_return"] = panel["n_suspect_rows"] > 0
    panel["promo_share"] = np.where(
        panel["promo_denominator"] > 0,
        panel["promo_numerator"] / panel["promo_denominator"],
        np.nan,
    )

    panel = panel.sort_values(["household_key", "week_no"]).reset_index(drop=True)
    # Weeks increase within a household, so a forward-fill of the active week
    # IS the last active week; leading NaNs (before the first purchase) stay
    # NaN -> recency NA there (DL-005). Note: pandas cummax does NOT carry
    # values over NaN positions, so ffill is the correct primitive here.
    active_week = panel["week_no"].where(panel["has_purchase"])
    last_active = active_week.groupby(panel["household_key"]).ffill()
    panel["recency_weeks"] = (panel["week_no"] - last_active).astype("Int32")

    if panel.duplicated(["household_key", "week_no"]).any():
        raise AssertionError("hh_week must be unique per (household_key, week_no)")
    if panel["promo_share"].min(skipna=True) < 0:
        raise AssertionError("promo_share must never be negative (abs() on discounts)")

    panel = panel[
        [
            "household_key",
            "week_no",
            "net_spend",
            "n_baskets",
            "n_products",
            "category_breadth",
            "has_purchase",
            "has_return",
            "n_suspect_rows",
            "promo_share",
            "promo_numerator",
            "promo_denominator",
            "sales_value_sum",
            "abs_retail_disc_sum",
            "abs_coupon_disc_sum",
            "recency_weeks",
        ]
    ]
    return panel


def read_households(csv_path: PathLike = TRANSACTION_CSV) -> np.ndarray:
    """All household keys observed in transactions (expect 2,500)."""
    con = duckdb.connect()
    try:
        rows = con.execute(
            "SELECT DISTINCT household_key FROM read_csv_auto(?) ORDER BY 1",
            [str(csv_path)],
        ).df()
    finally:
        con.close()
    return rows["household_key"].to_numpy()


# ---------------------------------------------------------------------------
# L4 — hh_category (grain sekunder) + product join coverage
# ---------------------------------------------------------------------------


def build_hh_category(
    txn_csv: PathLike = TRANSACTION_CSV, product_csv: PathLike = PRODUCT_CSV
) -> pd.DataFrame:
    """Long (household_key, commodity_desc) net spend table for Phase 3/5.

    Products without a master row are excluded here (a NULL would fake a
    category); see product_join_coverage for the excluded share.
    """
    query = """
        SELECT
            t.household_key,
            p.COMMODITY_DESC AS commodity_desc,
            SUM(t.SALES_VALUE + t.RETAIL_DISC + t.COUPON_DISC + t.COUPON_MATCH_DISC) AS net_spend,
            COUNT(DISTINCT t.WEEK_NO) AS n_weeks_active
        FROM read_csv_auto(?) t
        JOIN read_csv_auto(?) p ON t.PRODUCT_ID = p.PRODUCT_ID
        GROUP BY t.household_key, p.COMMODITY_DESC
    """
    con = duckdb.connect()
    try:
        df = con.execute(query, [str(txn_csv), str(product_csv)]).df()
    finally:
        con.close()
    return df.sort_values(["household_key", "net_spend"], ascending=[True, False]).reset_index(drop=True)


def product_join_coverage(
    txn_csv: PathLike = TRANSACTION_CSV, product_csv: PathLike = PRODUCT_CSV
) -> dict:
    """Row-level and product-id-level coverage of the product master join.

    Reported (not asserted): if coverage < 100%, category_breadth undercounts
    and that limitation must be documented, not hidden.
    """
    query = """
        SELECT
            COUNT(*) AS n_txn_rows,
            COUNT(*) FILTER (WHERE p.PRODUCT_ID IS NULL) AS n_unmatched_rows,
            COUNT(DISTINCT t.PRODUCT_ID) AS n_distinct_products,
            COUNT(DISTINCT t.PRODUCT_ID) FILTER (WHERE p.PRODUCT_ID IS NULL) AS n_unmatched_products
        FROM read_csv_auto(?) t
        LEFT JOIN read_csv_auto(?) p ON t.PRODUCT_ID = p.PRODUCT_ID
    """
    con = duckdb.connect()
    try:
        row = con.execute(query, [str(txn_csv), str(product_csv)]).fetchone()
    finally:
        con.close()
    out = dict(zip(["n_txn_rows", "n_unmatched_rows", "n_distinct_products", "n_unmatched_products"], row))
    out["row_coverage"] = 1.0 - out["n_unmatched_rows"] / out["n_txn_rows"]
    out["id_coverage"] = 1.0 - out["n_unmatched_products"] / out["n_distinct_products"]
    return out


# ---------------------------------------------------------------------------
# L5 — thin hh_campaign map (grain sekunder)
# ---------------------------------------------------------------------------


def build_hh_campaign(campaign_table: pd.DataFrame, timeline: pd.DataFrame) -> pd.DataFrame:
    """(household_key, campaign_id) treatment map joined with window columns.

    Control assignment / matching / IPW stay in Phase 4 (src/did.py) on
    purpose; this table only carries treatment + window facts.
    """
    window_cols = [
        "campaign_id",
        "type",
        "start_day",
        "end_day",
        "start_week",
        "end_week",
        "truncated_flag",
    ]
    hh_campaign = campaign_table[["household_key", "campaign_id"]].merge(
        timeline[window_cols], on="campaign_id", how="left", validate="m:1"
    )
    if hh_campaign[window_cols].isna().any().any():
        raise AssertionError("every treated row must match a known campaign window")
    hh_campaign["n_weeks_window"] = hh_campaign["end_week"] - hh_campaign["start_week"] + 1
    return hh_campaign.sort_values(["household_key", "campaign_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# L6 — control pool per campaign + DiD eligibility (gate #5)
# ---------------------------------------------------------------------------


def compute_control_pool(
    campaign_table: pd.DataFrame, timeline: pd.DataFrame, households
) -> pd.DataFrame:
    """Timeline + n_control_pool: households never targeted by this campaign
    nor by any campaign whose window overlaps it (AGENTS.md section 2.1).

    Using a naive control ("just not in this campaign") biases estimates
    toward zero; that is exactly what this function prevents.
    """
    treated = {int(cid): set(g["household_key"]) for cid, g in campaign_table.groupby("campaign_id")}
    all_hh = set(int(h) for h in np.asarray(households))
    out = timeline.copy()
    pools = {}
    for r in out.itertuples():
        excluded = set(treated.get(int(r.campaign_id), set()))
        for other in str(r.overlaps_with).split(","):
            if other:
                excluded |= treated.get(int(other), set())
        pools[int(r.campaign_id)] = len(all_hh - excluded)
    out["n_control_pool"] = out["campaign_id"].map(pools).astype("int32")
    return out


def classify_campaign_eligibility(timeline: pd.DataFrame) -> pd.DataFrame:
    """reliability_flag + eligibility_reason per campaign (R7: flag, never
    silently drop). Expects compute_control_pool output."""
    out = timeline.copy()
    flags: list[str] = []
    reasons: list[str] = []
    for r in out.itertuples():
        cid = int(r.campaign_id)
        if cid in EXCLUDED_FROM_MAIN_ESTIMATION:
            flag, reason = "excluded", "window 161 hari overlap 12 campaign, menelan ±23 minggu (AGENTS.md §2.1)"
        elif r.truncated_flag:
            flag, reason = "tidak reliable", "END_DAY 719 > akhir data 711 — window terpotong"
        elif r.n_treated < 100:
            reason = f"n_treated={int(r.n_treated)} < 100 — laporkan sebagai agregat (R7/R8)"
            if cid == 21:
                reason += "; window identik dengan 22"
            flag = "tidak reliable"
        elif r.n_control_pool < 30:
            flag, reason = "tidak reliable", f"n_control_pool={int(r.n_control_pool)} < 30 (R8)"
        elif cid in BACKBONE_CAMPAIGNS:
            flag, reason = "layak — utama", f"backbone TypeA, n_treated={int(r.n_treated)}"
        else:
            flag, reason = "layak", f"menengah, n_treated={int(r.n_treated)} — CI akan lebar"
        flags.append(flag)
        reasons.append(reason)
    out["reliability_flag"] = flags
    out["eligibility_reason"] = reasons
    return out
