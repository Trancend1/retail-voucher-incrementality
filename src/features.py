"""Panel and campaign-timeline builders on the Dunnhumby raw CSVs.

Conventions
-----------
- Raw CSV columns are UPPER_CASE; every returned table is snake_case.
- Money metrics use net spend (DL-001); return rows are never dropped, only
  flagged (DL-002). The binding metric definitions live in
  docs/decision-log.md (DL-001..DL-005).
- Verified reference numbers (row counts, campaign facts) are recorded in
  AGENTS.md section 2 and locked by tests/test_panel.py. If the raw data is
  ever replaced, re-verify there first — do not relax the tests silently.
"""

from __future__ import annotations

from pathlib import Path

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

PathLike = str | Path

# DL-001: net = amount paid after loyalty, manufacturer-coupon and
# coupon-match discounts (all three stored as negative values).
NET_SPEND_SQL = "(SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC)"

# Verified data facts the builders rely on (AGENTS.md section 2).
LAST_OBSERVED_DAY = 711  # last DAY present in transaction_data
N_WEEKS = 102  # WEEK_NO spans 1..102
N_COMMODITIES = 308  # distinct COMMODITY_DESC in product.csv

# Campaign roles for DiD eligibility (AGENTS.md section 2.1).
BACKBONE_CAMPAIGNS = (8, 13, 18)  # large TypeA campaigns, main estimands
EXCLUDED_FROM_MAIN_ESTIMATION = (15,)  # 161-day window overlapping 12 campaigns

# Below this many treated households a campaign cannot stand on its own as a
# DiD estimate (R7/R8) and is reported only as part of an aggregate.
MIN_INDEPENDENT_DID_TREATED = 100
# Minimum cell size that may be reported as its own estimate (R8).
MIN_REPORTABLE_N = 30


def _query_df(sql: str, params: list[PathLike]) -> pd.DataFrame:
    """Parameterised single-statement DuckDB query -> pandas frame."""
    con = duckdb.connect()
    try:
        return con.execute(sql, [str(p) for p in params]).df()
    finally:
        con.close()


def _query_one(sql: str, params: list[PathLike]) -> dict:
    """Single-row DuckDB query -> dict keyed by the result column names."""
    con = duckdb.connect()
    try:
        cur = con.execute(sql, [str(p) for p in params])
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    finally:
        con.close()
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Day -> week bridge and campaign timeline
# ---------------------------------------------------------------------------


def read_day_week_pairs(csv_path: PathLike = TRANSACTION_CSV) -> pd.DataFrame:
    """Distinct (week_no, day) pairs from transactions, aggregated in DuckDB."""
    return _query_df(
        "SELECT WEEK_NO AS week_no, DAY AS day FROM read_csv_auto(?) GROUP BY WEEK_NO, DAY",
        [csv_path],
    )


def build_day_week_bridge(pairs: pd.DataFrame) -> pd.DataFrame:
    """Observed min/max day per week: columns week_no, min_day, max_day.

    Fails fast if weeks are not contiguous 1..N or the day intervals are not
    adjacent — either would make the bridge unusable for mapping campaigns.
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
    """Week containing `day`; days beyond the observed data clamp to the last
    observed week (only truncated campaigns reach that branch)."""
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
    """campaign_desc normalized to campaign_id, type, start_day, end_day."""
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
    """campaign_table normalized to type, household_key, campaign_id."""
    treated = pd.read_csv(csv_path).rename(
        columns={"DESCRIPTION": "type", "CAMPAIGN": "campaign_id"}
    )
    treated["type"] = treated["type"].str.removeprefix("Type")
    return treated


def build_campaign_timeline(
    campaign_desc: pd.DataFrame,
    campaign_table: pd.DataFrame,
    bridge: pd.DataFrame,
) -> pd.DataFrame:
    """Campaign timeline with the Phase 0-1 quality-gate columns.

    - overlaps_with / n_overlaps: campaigns whose [start_day, end_day]
      interval intersects this campaign's (inclusive; symmetric by design),
      as a comma-separated id list plus a count.
    - start_week/end_week via the observed day->week bridge; end days beyond
      LAST_OBSERVED_DAY clamp to the last observed week.
    - truncated_flag: end_day beyond the observed data.
    - n_treated: households targeted by the campaign.
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


# ---------------------------------------------------------------------------
# Spend sanity
# ---------------------------------------------------------------------------


def spend_sanity(csv_path: PathLike = TRANSACTION_CSV) -> dict:
    """Row-level net-spend stats: return-row counts (DL-002 confirmation),
    net distribution, and the promo_share denominator-valid row count."""
    sql = f"""
        SELECT
            COUNT(*) AS n_rows,
            SUM(CASE WHEN SALES_VALUE <= 0 THEN 1 ELSE 0 END) AS n_sales_value_le0,
            SUM(CASE WHEN {NET_SPEND_SQL} < 0 THEN 1 ELSE 0 END) AS n_net_lt0,
            SUM(CASE WHEN SALES_VALUE > 0 THEN 1 ELSE 0 END) AS n_denominator_valid,
            SUM({NET_SPEND_SQL}) AS net_sum,
            MIN({NET_SPEND_SQL}) AS net_min,
            MEDIAN({NET_SPEND_SQL}) AS net_p50,
            QUANTILE_CONT({NET_SPEND_SQL}, 0.99) AS net_p99,
            MAX({NET_SPEND_SQL}) AS net_max
        FROM read_csv_auto(?)
    """
    return _query_one(sql, [csv_path])


# ---------------------------------------------------------------------------
# Balanced household-week panel
# ---------------------------------------------------------------------------

_HH_WEEK_AGG_SQL = f"""
SELECT
    household_key,
    WEEK_NO,
    SUM({NET_SPEND_SQL}) AS net_spend,
    COUNT(DISTINCT BASKET_ID) AS n_baskets,
    COUNT(DISTINCT PRODUCT_ID) AS n_products,
    SUM(SALES_VALUE) AS sales_value_sum,
    SUM(ABS(RETAIL_DISC)) AS abs_retail_disc_sum,
    SUM(ABS(COUPON_DISC)) AS abs_coupon_disc_sum,
    -- promo_share per DL-004: only rows with SALES_VALUE > 0 count on both
    -- sides of the ratio.
    SUM(CASE WHEN SALES_VALUE > 0 THEN SALES_VALUE ELSE 0 END) AS promo_denominator,
    SUM(CASE WHEN SALES_VALUE > 0 THEN ABS(RETAIL_DISC) + ABS(COUPON_DISC) ELSE 0 END) AS promo_numerator,
    SUM(CASE WHEN SALES_VALUE <= 0 OR {NET_SPEND_SQL} < 0 THEN 1 ELSE 0 END) AS n_suspect_rows
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
    agg = _query_df(_HH_WEEK_AGG_SQL, [csv_path])
    return agg.rename(columns={"WEEK_NO": "week_no"})


def aggregate_hh_breadth(
    txn_csv: PathLike = TRANSACTION_CSV, product_csv: PathLike = PRODUCT_CSV
) -> pd.DataFrame:
    """Distinct COMMODITY_DESC per household-week.

    Inner join on purpose: a product missing from the master must not fake a
    category; product_join_coverage reports how often that happens.
    """
    return _query_df(_HH_WEEK_BREADTH_SQL, [txn_csv, product_csv])


def build_hh_week(
    txn_csv: PathLike = TRANSACTION_CSV,
    product_csv: PathLike = PRODUCT_CSV,
    n_weeks: int = N_WEEKS,
) -> pd.DataFrame:
    """Balanced panel: one row per (household_key, week_no), weeks 1..n_weeks.

    - net_spend per DL-001; return rows stay in the aggregation (DL-002).
    - promo_share per DL-004: NA on weeks with no valid-denominator row.
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
    # Weeks increase within a household, so forward-filling the active week
    # yields the last active week; leading NaNs (before the first purchase)
    # stay NaN. cummax is wrong here: it never carries values past NaN
    # positions, so every inactive week would end up NA.
    active_week = panel["week_no"].where(panel["has_purchase"])
    last_active = active_week.groupby(panel["household_key"]).ffill()
    panel["recency_weeks"] = (panel["week_no"] - last_active).astype("Int32")

    if panel.duplicated(["household_key", "week_no"]).any():
        raise AssertionError("hh_week must be unique per (household_key, week_no)")
    if panel["promo_share"].min(skipna=True) < 0:
        raise AssertionError("promo_share must never be negative (abs() on discounts)")

    return panel[
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


def read_households(csv_path: PathLike = TRANSACTION_CSV) -> np.ndarray:
    """All household keys observed in transactions."""
    return _query_df(
        "SELECT DISTINCT household_key FROM read_csv_auto(?) ORDER BY 1", [csv_path]
    )["household_key"].to_numpy()


# ---------------------------------------------------------------------------
# Household-category table and product-master coverage
# ---------------------------------------------------------------------------


def build_hh_category(
    txn_csv: PathLike = TRANSACTION_CSV, product_csv: PathLike = PRODUCT_CSV
) -> pd.DataFrame:
    """Long (household_key, commodity_desc) net-spend table for downstream
    phases. Products missing from the master are excluded (a NULL would fake
    a category); product_join_coverage reports the excluded share."""
    sql = f"""
        SELECT
            t.household_key,
            p.COMMODITY_DESC AS commodity_desc,
            SUM({NET_SPEND_SQL}) AS net_spend,
            COUNT(DISTINCT t.WEEK_NO) AS n_weeks_active
        FROM read_csv_auto(?) t
        JOIN read_csv_auto(?) p ON t.PRODUCT_ID = p.PRODUCT_ID
        GROUP BY t.household_key, p.COMMODITY_DESC
    """
    hh_cat = _query_df(sql, [txn_csv, product_csv])
    return hh_cat.sort_values(["household_key", "net_spend"], ascending=[True, False]).reset_index(drop=True)


def product_join_coverage(
    txn_csv: PathLike = TRANSACTION_CSV, product_csv: PathLike = PRODUCT_CSV
) -> dict:
    """Row-level and product-id-level coverage of the product-master join.

    Reported, not asserted: if coverage < 100%, category_breadth undercounts
    and that limitation must be documented, not hidden.
    """
    sql = """
        SELECT
            COUNT(*) AS n_txn_rows,
            COUNT(*) FILTER (WHERE p.PRODUCT_ID IS NULL) AS n_unmatched_rows,
            COUNT(DISTINCT t.PRODUCT_ID) AS n_distinct_products,
            COUNT(DISTINCT t.PRODUCT_ID) FILTER (WHERE p.PRODUCT_ID IS NULL) AS n_unmatched_products
        FROM read_csv_auto(?) t
        LEFT JOIN read_csv_auto(?) p ON t.PRODUCT_ID = p.PRODUCT_ID
    """
    out = _query_one(sql, [txn_csv, product_csv])
    out["row_coverage"] = 1.0 - out["n_unmatched_rows"] / out["n_txn_rows"]
    out["id_coverage"] = 1.0 - out["n_unmatched_products"] / out["n_distinct_products"]
    return out


# ---------------------------------------------------------------------------
# Treatment map and DiD control pools
# ---------------------------------------------------------------------------


def build_hh_campaign(campaign_table: pd.DataFrame, timeline: pd.DataFrame) -> pd.DataFrame:
    """(household_key, campaign_id) treatment map joined with window columns.

    Control assignment, matching and IPW belong to the campaign-effect phase
    (src/did.py); this table carries treatment and window facts only.
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


def compute_control_pool(
    campaign_table: pd.DataFrame, timeline: pd.DataFrame, households
) -> pd.DataFrame:
    """Timeline plus n_control_pool: households never targeted by a campaign
    nor by any campaign whose window overlaps it.

    A naive control ("just not in this campaign") is contaminated by
    overlapping campaigns and biases estimates toward zero.
    """
    treated = {
        int(cid): set(g["household_key"])
        for cid, g in campaign_table.groupby("campaign_id")
    }
    all_hh = {int(h) for h in np.asarray(households)}
    pools = {}
    for r in timeline.itertuples():
        excluded = set(treated.get(int(r.campaign_id), set()))
        for other in str(r.overlaps_with).split(","):
            if other:
                excluded |= treated.get(int(other), set())
        pools[int(r.campaign_id)] = len(all_hh - excluded)

    out = timeline.copy()
    out["n_control_pool"] = out["campaign_id"].map(pools).astype("int32")
    return out


def classify_campaign_eligibility(timeline: pd.DataFrame) -> pd.DataFrame:
    """Timeline plus reliability_flag and eligibility_reason (R7: flag, never
    silently drop). Expects compute_control_pool output."""
    out = timeline.copy()
    # Campaigns sharing an exact window with another campaign are called out
    # in their reason string (identical windows cannot be told apart).
    same_window: dict[int, list[int]] = {}
    for a in out.itertuples():
        twins = out.loc[
            (out["campaign_id"] != a.campaign_id)
            & (out["start_day"] == a.start_day)
            & (out["end_day"] == a.end_day),
            "campaign_id",
        ].tolist()
        if twins:
            same_window[int(a.campaign_id)] = [int(t) for t in twins]

    flags: list[str] = []
    reasons: list[str] = []
    for r in out.itertuples():
        cid = int(r.campaign_id)
        if cid in EXCLUDED_FROM_MAIN_ESTIMATION:
            window_days = int(r.end_day) - int(r.start_day) + 1
            reason = f"window {window_days} hari overlap {int(r.n_overlaps)} campaign — di luar estimasi utama"
            flag = "excluded"
        elif r.truncated_flag:
            flag, reason = (
                "tidak reliable",
                f"end_day {int(r.end_day)} > akhir data {LAST_OBSERVED_DAY} — window terpotong",
            )
        elif r.n_treated < MIN_INDEPENDENT_DID_TREATED:
            reason = f"n_treated={int(r.n_treated)} < {MIN_INDEPENDENT_DID_TREATED} — laporkan sebagai agregat"
            if cid in same_window:
                reason += f"; window identik dengan {'/'.join(map(str, same_window[cid]))}"
            flag = "tidak reliable"
        elif r.n_control_pool < MIN_REPORTABLE_N:
            flag, reason = (
                "tidak reliable",
                f"n_control_pool={int(r.n_control_pool)} < {MIN_REPORTABLE_N}",
            )
        elif cid in BACKBONE_CAMPAIGNS:
            flag, reason = "layak — utama", f"backbone TypeA, n_treated={int(r.n_treated)}"
        else:
            flag, reason = "layak", f"menengah, n_treated={int(r.n_treated)} — CI akan lebar"
        flags.append(flag)
        reasons.append(reason)

    out["reliability_flag"] = flags
    out["eligibility_reason"] = reasons
    return out


def save_parquet(df: pd.DataFrame, out_path: PathLike) -> Path:
    """Write a processed artifact (data/processed is gitignored, rule R11)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out
