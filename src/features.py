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
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
TRANSACTION_CSV = DATA_DIR / "transaction_data.csv"
CAMPAIGN_DESC_CSV = DATA_DIR / "campaign_desc.csv"
CAMPAIGN_TABLE_CSV = DATA_DIR / "campaign_table.csv"

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
