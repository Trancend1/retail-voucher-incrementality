"""Deliverable artifacts of Phase 8 sprint p8b: targeting xlsx, playbook, rerun slide."""

import re
from pathlib import Path

import pandas as pd
import pytest

from src.features import PROCESSED_DIR
from src.targeting import OUTPUT_COLUMNS, OUTPUT_XLSX, build_targeting_list

REPO = Path(__file__).resolve().parent.parent
PLAYBOOK = REPO / "outputs" / "playbook.md"
RERUN = REPO / "outputs" / "rerun_slide.md"
BANNED = re.compile("share" + r"\s+of\s+" + "wallet", re.IGNORECASE)


@pytest.fixture(scope="session")
def targeting_list():
    return build_targeting_list()


def test_targeting_list_shape_and_rules(targeting_list):
    t = targeting_list
    assert list(t.columns) == OUTPUT_COLUMNS
    # one row per scored member (latest held-out campaign each)
    assert t["household_key"].is_unique
    assert len(t) == 2_498
    # include flag = playbook default budget: top-2 decile within campaign
    assert t["include_flag"].mean() == pytest.approx(0.20, abs=0.01)
    assert t["uplift_decile"].between(1, 10).all()
    assert t["clv_decile"].between(1, 10).all()
    assert t[["uplift_score", "promo_dependence", "recommended_offer"]].notna().all().all()
    assert t["top_whitespace_category"].notna().all()
    assert "COUPON/MISC ITEMS" not in set(t["top_whitespace_category"])
    # voucher cap is the data-anchored p90 guardrail (whole dollars)
    assert t["voucher_cap_usd"].eq(18).all()
    # offer rule honors segment priority
    rentan = t[t["segment"] == "rentan hilang"]
    assert (rentan["recommended_offer"].str.startswith("aktivasi ulang")).all()


def test_xlsx_artifact_structure():
    if not OUTPUT_XLSX.exists():
        pytest.skip("targeting_sample.xlsx not built yet")
    xl = pd.ExcelFile(OUTPUT_XLSX)
    assert xl.sheet_names == ["output", "asumsi"]
    out = xl.parse("output")
    asum = xl.parse("asumsi")
    assert list(out.columns) == OUTPUT_COLUMNS
    assert len(asum) >= 10
    blob = " ".join(asum["asumsi"].tolist() + asum["nilai / sumber"].tolist()).lower()
    assert "observational" in blob and "holdout" in blob and "proxy dalam satu retailer" in blob
    assert BANNED.search(blob) is None


def test_committed_xlsx_is_current():
    """The committed workbook must equal a fresh deterministic build
    (values exact; xlsx stores integers as floats so dtypes are ignored)."""
    if not OUTPUT_XLSX.exists():
        pytest.skip("targeting_sample.xlsx not built yet")
    committed = pd.read_excel(OUTPUT_XLSX, sheet_name="output").reset_index(drop=True)
    fresh = build_targeting_list().reset_index(drop=True)
    pd.testing.assert_frame_equal(fresh, committed, check_dtype=False, check_exact=True)


def test_playbook_required_content():
    text = PLAYBOOK.read_text(encoding="utf-8")
    for needle in [
        "holdout", "10%", "incremental margin per $1 voucher < 1",
        "observational", "parameter asumsi", "top-2 decile",
        "rentan hilang", "promo-dependent", "mesin pertumbuhan",
        "$18", "cap",
    ]:
        assert needle.lower() in text.lower(), needle
    assert BANNED.search(text) is None


def test_rerun_slide_mapping_table():
    text = RERUN.read_text(encoding="utf-8")
    for needle in [
        "member_id", "COUPON_DISC", "holdout flag", "margin/cost",
        "tidak ada)", "net_spend", "p95", "n < 30", "observational",
    ]:
        assert needle.lower() in text.lower(), needle
    assert BANNED.search(text) is None
