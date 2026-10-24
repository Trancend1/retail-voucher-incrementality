"""Phase 3 (penetration gap) assertions.

Verified results live in AGENTS.md section 2.4. Everything here is a proxy
within one retailer (R2); the banned-phrase test keeps deliverable text
honest. If numbers move after a data refresh, re-verify AGENTS.md first.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.cohorts import (
    DEFICIT_RATIO,
    MIN_BUYER_RATE,
    TOP_N_PER_HOUSEHOLD,
    build_cohorts,
    household_shares,
)

REPO = Path(__file__).resolve().parent.parent

# Verified: the 3x3 grid has one naturally empty cell (S1xB3 - low spend
# with very broad category mix does not occur) and one tiny cell (S3xB1,
# four high-spend / low-breadth households) that merges into S2xB1;
# 7 cohorts remain, smallest n = 127.
EXPECTED_MERGE_LOG = ["S3xB1 (n=4) merged into S2xB1"]


# --- cohorts -----------------------------------------------------------------


def test_cohorts_reportable_and_deterministic(hh_category, cohorts):
    sizes = cohorts.groupby("cohort")["household_key"].size()
    assert len(sizes) == 7
    assert int(sizes.min()) == 127
    assert int(sizes.sum()) == 2_500
    assert cohorts["household_key"].nunique() == 2_500

    _, merge_log = build_cohorts(hh_category)
    assert merge_log == EXPECTED_MERGE_LOG

    again, _ = build_cohorts(hh_category)
    pd.testing.assert_frame_equal(
        again.sort_values("household_key").reset_index(drop=True),
        cohorts.sort_values("household_key").reset_index(drop=True),
    )


def test_cohort_ordering_sanity(cohorts):
    spend_means = cohorts.groupby("spend_tercile")["total_net_spend"].mean()
    assert spend_means.is_monotonic_increasing
    breadth_means = cohorts.groupby("breadth_tercile")["n_commodities"].mean()
    assert breadth_means.is_monotonic_increasing


# --- shares & benchmarks -------------------------------------------------------


def test_household_shares_sum_to_one(hh_category):
    sums = household_shares(hh_category).groupby("household_key")["hh_share"].sum()
    assert sums.size == 2_500
    assert ((sums - 1.0).abs() < 1e-9).all()


def test_benchmark_structure(cohort_benchmarks):
    bench = cohort_benchmarks
    assert not bench.duplicated(["cohort", "commodity_desc"]).any()
    assert bench["buyer_rate"].between(0, 1).all()
    assert (bench["n_buyers"] <= bench["n_cohort"]).all()
    assert (bench["n_cohort"] >= 127).all()
    assert np.isfinite(bench["median_share"]).all()


# --- whitespace ---------------------------------------------------------------


def test_whitespace_definition_holds_everywhere(whitespace):
    ws = whitespace
    qualifies = ws["is_zero_buyer"] | (
        ws["hh_share"] < DEFICIT_RATIO * ws["cohort_median_share"]
    )
    assert qualifies.all()
    assert (ws["is_zero_buyer"] == (ws["hh_share"] == 0)).all()
    assert (ws["buyer_rate"] >= MIN_BUYER_RATE).all()
    assert (ws["cohort_median_share"] > 0).all()
    calc = ws["cohort_median_share"] * ws["hh_total_spend"]
    assert ((calc - ws["expected_spend"]).abs() < 1e-9).all()


def test_whitespace_topn_coverage_and_order(whitespace):
    ws = whitespace
    counts = ws.groupby("household_key").size()
    assert counts.size == 2_500  # every household has candidates
    assert int(counts.max()) == TOP_N_PER_HOUSEHOLD  # cap filled for everyone
    assert ws.groupby("household_key")["expected_spend"].apply(
        lambda s: s.is_monotonic_decreasing
    ).all()
    assert not ws.duplicated(["household_key", "commodity_desc"]).any()
    assert len(ws) == 25_000
    # Verified: about half the whitespace entries are never-bought categories
    assert ws["is_zero_buyer"].mean() == pytest.approx(0.488, abs=0.01)


# --- R2: banned phrase ----------------------------------------------------------


def test_banned_phrase_absent_from_deliverables():
    """The banned wallet-phrase must not appear in deliverable-facing text."""
    pattern = re.compile("share" + r"\s+of\s+" + "wallet", re.IGNORECASE)
    targets = [REPO / "README.md"]
    targets += sorted((REPO / "notebooks").glob("*.ipynb"))
    targets += sorted((REPO / "src").glob("*.py"))
    offenders = [
        str(t.relative_to(REPO))
        for t in targets
        if t.exists() and pattern.search(t.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"banned phrase found in: {offenders}"
