"""Pytest bootstrap and shared session fixtures (real data, built once per run)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from src.clv import (
    CALIBRATION_END_WEEK,
    build_summary,
    fit_bg_nbd,
    fit_gamma_gamma,
    evaluate_holdout,
)
from src.features import (
    build_campaign_timeline,
    build_day_week_bridge,
    build_hh_category,
    build_hh_week,
    build_rfm,
    classify_campaign_eligibility,
    compute_control_pool,
    load_campaign_desc,
    load_campaign_treated,
    product_join_coverage,
    read_day_week_pairs,
    read_households,
    spend_sanity,
)


@pytest.fixture(scope="session")
def bridge():
    return build_day_week_bridge(read_day_week_pairs())


@pytest.fixture(scope="session")
def timeline(bridge):
    return build_campaign_timeline(load_campaign_desc(), load_campaign_treated(), bridge)


@pytest.fixture(scope="session")
def sanity():
    return spend_sanity()


@pytest.fixture(scope="session")
def hh_week():
    return build_hh_week()


@pytest.fixture(scope="session")
def hh_category():
    return build_hh_category()


@pytest.fixture(scope="session")
def households():
    return read_households()


@pytest.fixture(scope="session")
def eligible_timeline(timeline, households):
    return classify_campaign_eligibility(
        compute_control_pool(load_campaign_treated(), timeline, households)
    )


# --- Phase 2 (CLV) ---


@pytest.fixture(scope="session")
def rfm_full(hh_week):
    return build_rfm(hh_week, 102)


@pytest.fixture(scope="session")
def summary_cal(hh_week):
    return build_summary(hh_week, CALIBRATION_END_WEEK)


@pytest.fixture(scope="session")
def bgf_cal(summary_cal):
    return fit_bg_nbd(summary_cal)


@pytest.fixture(scope="session")
def ggf_cal(summary_cal):
    return fit_gamma_gamma(summary_cal)


@pytest.fixture(scope="session")
def holdout_metrics(hh_week, bgf_cal, ggf_cal, summary_cal):
    metrics, _ = evaluate_holdout(hh_week, bgf_cal, ggf_cal, summary_cal)
    return metrics
