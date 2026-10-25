"""ROI simulation invariants (Phase 7).

The core cross-check: for the blanket audience the per-campaign incremental
spend per $1 (tight) must equal the Phase 4 DiD column inc_spend_per_dollar
multiplied by the campaign window length - Phase 4 ratios are weekly-level
over window-total cost, the simulation is window-consistent (DL-019). The
identity was verified to hold exactly (0.0% on all eight held-out campaigns).
"""

import numpy as np
import pandas as pd
import pytest

from src.features import PROCESSED_DIR
from src.simulate import MARGIN_LEVELS, SCENARIOS, load_roi_inputs, scenario_core, select_mask, simulate

ROI_PARQUET = PROCESSED_DIR / "roi_scenarios.parquet"


@pytest.fixture(scope="session")
def roi():
    return load_roi_inputs()


def test_blanket_matches_did_column_times_weeks(roi):
    """Window-horizon identity vs Phase 4 (exact by construction)."""
    did = pd.read_parquet(PROCESSED_DIR / "campaign_did_results.parquet").set_index("campaign_id")
    for cid, g in roi.groupby("campaign_id"):
        core = scenario_core(g.assign(_camp_code=0), select_mask(g, None, None))
        expected = float(did.loc[cid, "inc_spend_per_dollar"]) * g["n_weeks_window"].iloc[0]
        assert core["inc_per_dollar_tight"] == pytest.approx(expected, rel=1e-6), cid


def test_selection_sizes_and_per_campaign_share(roi):
    for name, col, frac in SCENARIOS:
        mask = select_mask(roi, col, frac)
        if col is None:
            assert mask.all()
            continue
        assert mask.sum() == pytest.approx(len(roi) * frac, abs=len(roi["campaign_id"].unique()))
        # every campaign contributes its own top slice (+1 row for rounding)
        per_campaign = roi[mask].groupby("campaign_id").size()
        sizes = roi.groupby("campaign_id").size()
        assert (per_campaign >= np.floor(sizes * frac)).all()
        assert (per_campaign <= np.ceil(sizes * frac)).all()


def test_arithmetic_identities_and_cost_bounds(roi):
    tbl = simulate(roi, n_bootstrap=0)  # point estimates only (no CI needed)
    # bootstrap with 0 draws must still return the point rows
    assert len(tbl) == len(SCENARIOS)
    for row in tbl.itertuples():
        assert row.cost_all >= row.cost_tight >= 0
        r = row.inc_per_dollar_tight
        assert row.breakeven_margin_tight == pytest.approx(1.0 / r, rel=1e-9)
        for m in MARGIN_LEVELS:
            col = f"margin{int(m * 100)}_per_dollar_tight"
            assert getattr(row, col) == pytest.approx(m * r - 1.0, rel=1e-9)


def test_uplift_targeting_beats_blanket_and_rfm(roi):
    """Directional lock of the verified finding (AGENTS.md 2.10): uplift
    top-2 per-$1 (tight) beats both blanket and RFM top-2."""
    tbl = simulate(roi, n_bootstrap=0).set_index("scenario")
    up2 = tbl.loc["uplift top-2 decile", "inc_per_dollar_tight"]
    assert up2 > tbl.loc["blanket", "inc_per_dollar_tight"]
    assert up2 > tbl.loc["RFM top-2 decile", "inc_per_dollar_tight"]
    # ordering holds under the conservative all-coupons bound too
    assert (
        tbl.loc["uplift top-2 decile", "inc_per_dollar_all"]
        > tbl.loc["blanket", "inc_per_dollar_all"]
    )


def test_scenarios_parquet_structure():
    if not ROI_PARQUET.exists():
        pytest.skip("roi_scenarios.parquet not built yet")
    tbl = pd.read_parquet(ROI_PARQUET)
    assert set(tbl["campaign_set"]) == {"all", "layak"}
    assert tbl.groupby("campaign_set").size().eq(5).all()
    key = ["n_targeted", "incr_spend_total", "cost_tight", "cost_all",
           "inc_per_dollar_tight", "margin25_per_dollar_tight", "breakeven_margin_tight"]
    assert tbl[key].notna().all().all()
    for col in ("inc_per_dollar_tight", "margin25_per_dollar_tight", "breakeven_margin_tight"):
        lo, hi = f"{col}_ci_low", f"{col}_ci_high"
        assert (tbl[lo] <= tbl[col]).all() and (tbl[col] <= tbl[hi]).all()
