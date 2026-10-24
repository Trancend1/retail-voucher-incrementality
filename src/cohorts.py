"""Category penetration gap: cohort benchmarks and per-household whitespace.

Everything here is a proxy within a single retailer - there is no non-member
or competitor transaction data, so these numbers say nothing about spending
outside this retailer (project rule R2). Cohort and whitespace definitions
are locked in docs/decision-log.md (DL-008, DL-009); spend figures are net
(DL-001) in nominal USD.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features import MIN_REPORTABLE_N

# DL-008: cohort safety rail. Cells below this size merge into the nearest
# spend-tier neighbour (same breadth tier); expected to stay unused.
MIN_COHORT_N = MIN_REPORTABLE_N

# DL-009: whitespace knobs.
MIN_BUYER_RATE = 0.30  # category must be bought by >= 30% of the cohort
DEFICIT_RATIO = 0.50  # household share below this x cohort median = deficit
TOP_N_PER_HOUSEHOLD = 10


def household_shares(hh_category: pd.DataFrame) -> pd.DataFrame:
    """Category share of each household's total net spend (long format).

    hh_category only contains bought categories; a missing row means the
    household's share of that category is zero.
    """
    shares = hh_category.merge(
        hh_category.groupby("household_key")["net_spend"].sum().rename("hh_total_spend"),
        on="household_key",
        validate="m:1",
    )
    shares["hh_share"] = shares["net_spend"] / shares["hh_total_spend"]
    return shares[
        ["household_key", "commodity_desc", "net_spend", "hh_total_spend", "hh_share"]
    ]


def _tercile(scores: pd.Series) -> pd.Series:
    """Balanced terciles under heavy ties (first-method ranks -> qcut)."""
    return pd.qcut(scores.rank(method="first"), q=3, labels=[1, 2, 3]).astype("int8")


def build_cohorts(
    hh_category: pd.DataFrame, min_cohort_n: int = MIN_COHORT_N
) -> tuple[pd.DataFrame, list[str]]:
    """Cohorts: spend tercile x breadth tercile over the full period (DL-008).

    Breadth = number of distinct commodities bought. Returns the cohort
    table and a merge_log of cells that fell below min_cohort_n and were
    merged into the nearest spend-tier neighbour (same breadth tier).
    """
    agg = (
        hh_category.groupby("household_key")
        .agg(
            total_net_spend=("net_spend", "sum"),
            n_commodities=("commodity_desc", "nunique"),
        )
        .reset_index()
    )
    if (agg["total_net_spend"] <= 0).any():
        n_bad = int((agg["total_net_spend"] <= 0).sum())
        raise ValueError(
            f"{n_bad} households have non-positive total net spend - "
            "define an explicit policy before cohorting them"
        )
    agg["spend_tercile"] = _tercile(agg["total_net_spend"])
    agg["breadth_tercile"] = _tercile(agg["n_commodities"])
    agg["cohort"] = "S" + agg["spend_tercile"].astype(str) + "xB" + agg["breadth_tercile"].astype(str)

    merge_log: list[str] = []
    sizes = agg.groupby(["breadth_tercile", "spend_tercile"]).size()
    for (b, s), n in sizes.items():
        if n >= min_cohort_n:
            continue
        neighbours = [(b, sn) for sn in (s - 1, s + 1) if (b, sn) in sizes.index]
        if not neighbours:
            raise AssertionError(
                f"cohort S{s}xB{b} (n={n}) has no spend-tier neighbour to merge into"
            )
        # prefer the larger neighbour; break ties toward the higher spend tier
        target = max(neighbours, key=lambda t: (sizes.loc[t], t[1]))[1]
        mask = (agg["breadth_tercile"] == b) & (agg["spend_tercile"] == s)
        agg.loc[mask, "spend_tercile"] = target
        agg.loc[mask, "cohort"] = f"S{target}xB{b}"
        merge_log.append(f"S{s}xB{b} (n={n}) merged into S{target}xB{b}")
    return agg, merge_log


def build_cohort_benchmarks(
    hh_category: pd.DataFrame, cohorts: pd.DataFrame
) -> pd.DataFrame:
    """Cohort x category benchmarks: buyer rate and median share (DL-009).

    The median is computed over cohort members who BUY the category
    (median-over-buyers); a household that never bought it is then compared
    against that median instead of against a median dragged to zero.
    """
    shares = household_shares(hh_category).merge(
        cohorts[["household_key", "cohort"]], on="household_key", validate="m:1"
    )
    bench = (
        shares.groupby(["cohort", "commodity_desc"])
        .agg(
            n_buyers=("household_key", "nunique"),
            median_share=("hh_share", "median"),
        )
        .reset_index()
    )
    bench = bench.merge(
        cohorts.groupby("cohort")["household_key"].size().rename("n_cohort"),
        on="cohort",
        validate="m:1",
    )
    bench["buyer_rate"] = bench["n_buyers"] / bench["n_cohort"]
    return bench.sort_values(["cohort", "median_share"], ascending=[True, False]).reset_index(drop=True)


def build_whitespace(
    hh_category: pd.DataFrame,
    cohorts: pd.DataFrame,
    benchmarks: pd.DataFrame,
    top_n: int = TOP_N_PER_HOUSEHOLD,
) -> pd.DataFrame:
    """Per-household whitespace candidates (DL-009), ranked by expected spend.

    A pair (household, category) qualifies when the category passes the
    cohort filters (buyer rate >= MIN_BUYER_RATE, median share > 0) and the
    household buys nothing of it, or less than DEFICIT_RATIO x the cohort
    median. expected_spend = cohort median share x household total spend -
    the headline number for ranking, always labelled as a proxy within this
    one retailer.
    """
    eligible = benchmarks[
        (benchmarks["buyer_rate"] >= MIN_BUYER_RATE) & (benchmarks["median_share"] > 0)
    ]
    shares = household_shares(hh_category)
    base = cohorts[["household_key", "cohort", "total_net_spend"]].rename(
        columns={"total_net_spend": "hh_total_spend"}
    )

    # many-to-many by design: every household crosses every eligible
    # category of its cohort
    pairs = base.merge(
        eligible[
            [
                "cohort",
                "commodity_desc",
                "median_share",
                "buyer_rate",
                "n_buyers",
                "n_cohort",
            ]
        ],
        on="cohort",
    )
    pairs = pairs.merge(
        shares[["household_key", "commodity_desc", "hh_share"]],
        on=["household_key", "commodity_desc"],
        how="left",
        validate="m:1",
    )
    pairs["hh_share"] = pairs["hh_share"].fillna(0.0)
    pairs["is_zero_buyer"] = pairs["hh_share"] == 0.0

    ws = pairs[
        pairs["is_zero_buyer"] | (pairs["hh_share"] < DEFICIT_RATIO * pairs["median_share"])
    ].copy()
    ws["expected_spend"] = ws["median_share"] * ws["hh_total_spend"]
    ws = ws.rename(columns={"median_share": "cohort_median_share"})
    ws = ws.sort_values(
        ["household_key", "expected_spend", "commodity_desc"],
        ascending=[True, False, True],
    )
    ws = ws.groupby("household_key", group_keys=False).head(top_n)

    result = ws[
        [
            "household_key",
            "cohort",
            "commodity_desc",
            "hh_share",
            "cohort_median_share",
            "is_zero_buyer",
            "expected_spend",
            "hh_total_spend",
            "buyer_rate",
            "n_buyers",
            "n_cohort",
        ]
    ].reset_index(drop=True)
    if result["expected_spend"].isna().any() or not np.isfinite(result["expected_spend"]).all():
        raise AssertionError("expected_spend must be finite everywhere")
    return result
