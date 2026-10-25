"""Dashboard bundle invariants — numbers pinned to the verified registry (AGENTS.md section 2).

The MVP dashboard is a static self-contained HTML built from the processed
parquets (decision DL-016). Every figure it shows must match what the
notebooks produced, so a rebuild over drifted data fails here instead of in
front of a reader. Rendering is deterministic: the committed
outputs/dashboard.html must equal a fresh build byte for byte.
"""

import re
from pathlib import Path

import pytest

from src.dashboard import OPERATOR_CATEGORY, OUTPUT_HTML, build, build_bundle, pooled_meta

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def bundle():
    return build_bundle()


@pytest.fixture(scope="session")
def doc():
    return build()


# --- page 1: member overview ------------------------------------------------------


def test_overview_kpis_match_registry(bundle):
    """Panel facts (AGENTS.md 2.2) and CLV percentiles (2.3)."""
    k = bundle["overview"]["kpis"]
    assert k["n_members"] == 2500
    assert k["n_weeks"] == 102
    assert k["total_net_spend"] == pytest.approx(6_608_940.89, abs=1.0)
    assert k["median_promo_share"] == pytest.approx(0.15, abs=0.005)
    # churn flags derive from per-segment rates; 366 members = 14.6% (2.6)
    assert k["churn_flagged_n"] == pytest.approx(366, abs=1)
    assert k["churn_flagged_pct"] == pytest.approx(14.6, abs=0.1)
    values = bundle["overview"]["clv_percentiles"]["values"]
    for got, want in zip(values, [315, 1050, 3135, 6364]):
        assert got == pytest.approx(want, abs=2)


def test_overview_weekly_shape(bundle):
    weekly = bundle["overview"]["weekly"]
    assert len(weekly["week"]) == 102
    assert max(weekly["week"]) == 102
    assert max(weekly["active"]) <= 2500
    assert sum(weekly["spend"]) == pytest.approx(6_608_940.89, abs=5.0)


# --- page 2: segment deep dive ----------------------------------------------------


def test_segments_match_registry(bundle):
    """Segment table facts (AGENTS.md 2.6)."""
    t = {r["segment"]: r for r in bundle["segments"]["table"]}
    assert sorted(t) == [1, 2, 3]
    assert [t[i]["n"] for i in (1, 2, 3)] == [1099, 972, 429]
    assert t[2]["promo_dependence"] == pytest.approx(0.232, abs=0.005)
    assert max(r["promo_dependence"] for r in t.values()) == t[2]["promo_dependence"]
    assert t[3]["churn_risk_pct"] == pytest.approx(39.2, abs=0.1)
    assert t[2]["whitespace_utama"] == "BEERS/ALES"
    # one deterministic action per segment, non-empty
    assert all(r["satu_aksi"] for r in t.values())


def test_heatmap_excludes_operator_category(bundle):
    """The operator category must not appear in whitespace visuals (2.4)."""
    heat = bundle["segments"]["heatmap"]
    assert OPERATOR_CATEGORY not in heat["categories"]
    assert len(heat["categories"]) == 12
    assert len(heat["segments"]) == 3
    assert all(v is not None for row in heat["values"] for v in row)


# --- page 3: campaign lift --------------------------------------------------------


def test_campaign_counts_and_flags_match_registry(bundle):
    """20 estimated, 14 pass all gates, 6 flagged far pre-trend (AGENTS.md 2.5)."""
    ca = bundle["campaigns"]
    assert ca["n_estimated"] == 20
    assert ca["n_layak"] == 14
    rows = {r["campaign_id"]: r for r in ca["rows"]}
    flagged = {
        cid for cid, r in rows.items() if r["estimated"] and "tidak reliable" in r["reliability_flag"]
    }
    assert flagged == {7, 10, 17, 18, 25, 26}
    bh = {cid for cid, r in rows.items() if r.get("significance", "").startswith("signifikan")}
    assert bh == {8, 12, 13, 14, 16, 18, 20, 22, 23}
    # every row carries a visible flag AND reason (no silent drops)
    assert all(r["reliability_flag"] and r["reliability_reason"] for r in rows.values())
    assert len(rows) == 30


def test_backbone_estimates_match_registry(bundle):
    """Backbone ATTs and redemption counts (AGENTS.md 2.1 / 2.5)."""
    bb = {r["campaign_id"]: r for r in bundle["campaigns"]["backbone"]}
    assert set(bb) == {8, 13, 18}
    assert bb[8]["att"] == pytest.approx(2.67, abs=0.01)
    assert (bb[8]["att_ci_low"], bb[8]["att_ci_high"]) == pytest.approx((0.69, 4.51), abs=0.01)
    assert bb[13]["att"] == pytest.approx(4.12, abs=0.01)
    assert bb[18]["att"] == pytest.approx(4.29, abs=0.01)
    rows = {r["campaign_id"]: r for r in bundle["campaigns"]["rows"]}
    for cid, redeemers in [(8, 158), (13, 196), (18, 214)]:
        assert rows[cid]["n_redeemers"] == redeemers


def test_pooled_matches_registry(bundle):
    """Meta-analysis over the 14 gate-passing campaigns (AGENTS.md 2.5)."""
    p = bundle["campaigns"]["pooled"]
    assert p["k"] == 14
    assert p["fe"] == pytest.approx(3.83, abs=0.01)
    assert (p["fe_ci_low"], p["fe_ci_high"]) == pytest.approx((2.89, 4.77), abs=0.01)
    assert p["re"] == pytest.approx(4.87, abs=0.01)
    assert (p["re_ci_low"], p["re_ci_high"]) == pytest.approx((3.06, 6.68), abs=0.01)
    assert p["i2_pct"] == pytest.approx(66, abs=1.0)


def test_pooled_meta_homogeneous_case():
    """Identical estimates must give zero heterogeneity and pooled == estimate."""
    p = pooled_meta([1.0, 1.0, 1.0], [0.0, 0.0, 0.0], [2.0, 2.0, 2.0])
    assert p["fe"] == pytest.approx(1.0)
    assert p["re"] == pytest.approx(1.0)
    assert p["i2_pct"] == pytest.approx(0.0, abs=1e-9)
    assert p["tau2"] == pytest.approx(0.0, abs=1e-9)


# --- page 4: voucher efficiency ----------------------------------------------------


def test_voucher_page_matches_registry(bundle):
    """Scenario numbers pinned to the Phase 7 registry (AGENTS.md 2.10)."""
    scen = {s["scenario"]: s for s in bundle["voucher"]["scenarios"]}
    assert set(scen) == {
        "blanket", "uplift top-2 decile", "uplift top-4 decile",
        "RFM top-2 decile", "RFM top-4 decile",
    }
    assert scen["uplift top-2 decile"]["inc_per_dollar_tight"] == pytest.approx(232.2, abs=0.5)
    assert scen["blanket"]["inc_per_dollar_tight"] == pytest.approx(90.4, abs=0.5)
    assert scen["RFM top-2 decile"]["inc_per_dollar_tight"] == pytest.approx(61.7, abs=0.5)
    assert scen["uplift top-2 decile"]["inc_per_dollar_all"] == pytest.approx(31.7, abs=0.3)
    assert scen["blanket"]["inc_per_dollar_all"] == pytest.approx(12.3, abs=0.3)
    layak = {s["scenario"]: s for s in bundle["voucher"]["scenarios_layak"]}
    assert layak["uplift top-2 decile"]["inc_per_dollar_tight"] == pytest.approx(516.9, abs=1.0)
    # directional lock: uplift beats blanket and RFM under both bounds
    for col in ("inc_per_dollar_tight", "inc_per_dollar_all"):
        up = scen["uplift top-2 decile"][col]
        assert up > scen["blanket"][col] and up > scen["RFM top-2 decile"][col]


def test_whatif_grid_invariants(bundle):
    """Grid must come from the exact Phase 7 machinery and close at frac=1."""
    wi = bundle["voucher"]["whatif"]
    assert wi["fracs"][0] == 0.05 and wi["fracs"][-1] == 1.0
    assert wi["fracs"] == sorted(wi["fracs"])
    scen = {s["scenario"]: s for s in bundle["voucher"]["scenarios"]}
    for label in ("uplift", "rfm"):
        pts = wi["grid"][label]
        assert len(pts) == 20
        ns = [p["n"] for p in pts]
        assert ns == sorted(ns)  # audience grows with fraction
        for p in pts:
            assert p["cost_all"] >= p["cost_tight"] > 0
            assert p["incr"] > 0
        # full coverage == blanket, regardless of score used for selection
        assert pts[-1]["n"] == scen["blanket"]["n_targeted"]
        assert pts[-1]["incr"] == pytest.approx(scen["blanket"]["incr_spend_total"], rel=0.001)
        assert pts[-1]["cost_tight"] == pytest.approx(scen["blanket"]["cost_tight"], rel=0.001)


# --- HTML deliverable --------------------------------------------------------------


def test_html_required_labels(doc):
    """Compliance labels must be visible in the markup (R1/R2/R3/R4 spirit)."""
    low = doc.lower()
    for label in [
        "observational — di bawah asumsi unconfoundedness",
        "proxy dalam satu retailer",
        "clv 52 minggu",
        "parameter asumsi",
        "break-even",
    ]:
        assert label in low, f"missing label: {label}"
    assert doc.count("<section") == 4
    assert doc.count('class="tab') == 4
    assert "Voucher Efficiency" in doc


def test_html_is_self_contained(doc):
    """No external resources: the file must render offline."""
    ext = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)', doc)
    assert ext == []


def test_committed_dashboard_is_current():
    """The committed artifact must equal a fresh deterministic build."""
    if not OUTPUT_HTML.exists():
        pytest.skip("outputs/dashboard.html not built yet")
    committed = OUTPUT_HTML.read_text(encoding="utf-8")
    assert committed == build()


def test_banned_phrase_absent_from_dashboard(doc):
    pattern = re.compile("share" + r"\s+of\s+" + "wallet", re.IGNORECASE)
    assert pattern.search(doc) is None
