"""Phase 7: voucher ROI simulation on the held-out campaigns (observational).

The simulation rehearses targeting on the eight test campaigns that the uplift
models never saw: pick an audience per campaign (blanket, top-k decile by
uplift score, top-k by RFM spend), then estimate - from what actually happened
under those campaigns - the incremental spend the audience would generate and
the voucher cost it would burn. Everything remains observational (R1);
margins are explicit parameters, never data (R3); voucher cost comes from
observed COUPON_DISC under two attribution bounds (DL-013).

Core identities per campaign c and audience S_c:
    uplift_c      = overlap-weighted treated-minus-control mean of delta ($/week)
    incremental_c = uplift_c * n_weeks(c) * |S_c|                      ($, window)
    cost_c        = (sum cost among treated in S_c / n_treated(S_c)) * |S_c|
The cost-per-targeted extrapolation uses observed treated households as the
only source of real redemption behaviour. Per-campaign ratios equal the
Phase 4 column inc_spend_per_dollar when S_c is the full audience (blanket) -
used as a cross-check by tests and the notebook.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.did import COUPON_CSV, TRANSACTION_CSV
from src.features import PROCESSED_DIR, RANDOM_STATE

MARGIN_LEVELS = (0.15, 0.25, 0.35)
N_BOOTSTRAP = 1000
COST_CACHE = PROCESSED_DIR / "roi_costs.parquet"
SCENARIOS = [
    ("blanket", None, None),
    ("uplift top-2 decile", "score_x", 0.20),
    ("uplift top-4 decile", "score_x", 0.40),
    ("RFM top-2 decile", "score_rfm", 0.20),
    ("RFM top-4 decile", "score_rfm", 0.40),
]


def tight_costs_by_household(campaign_windows: dict, cache: Path = COST_CACHE) -> pd.DataFrame:
    """Tight voucher cost (DL-013): |COUPON_DISC| on products in each
    campaign's own coupon list, per treated household, during the window.
    Cached to roi_costs.parquet (grain household x campaign) because the join
    scans the full transaction CSV once per campaign."""
    if cache.exists():
        return pd.read_parquet(cache)
    frames = []
    con = duckdb.connect()
    try:
        for cid, (ws, we) in campaign_windows.items():
            q = """
                SELECT t.household_key AS household_key, ? AS campaign_id,
                       SUM(ABS(t.COUPON_DISC)) AS cost_tight
                FROM read_csv_auto(?) t
                JOIN read_csv_auto(?) c ON t.PRODUCT_ID = c.PRODUCT_ID AND c.CAMPAIGN = ?
                WHERE t.WEEK_NO BETWEEN ? AND ? AND t.COUPON_DISC < 0
                GROUP BY t.household_key
            """
            frames.append(
                con.execute(q, [int(cid), str(TRANSACTION_CSV), str(COUPON_CSV), int(cid), int(ws), int(we)]).df()
            )
    finally:
        con.close()
    out = pd.concat(frames, ignore_index=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out


def load_roi_inputs() -> pd.DataFrame:
    """Held-out campaign rows with both cost bounds attached per household."""
    scores = pd.read_parquet(PROCESSED_DIR / "uplift_scores.parquet")
    panel = pd.read_parquet(PROCESSED_DIR / "hh_week.parquet")
    timeline = pd.read_parquet(PROCESSED_DIR / "campaign_timeline.parquet")
    tl = timeline.set_index("campaign_id")

    windows = {
        int(cid): (int(r.start_week), int(r.end_week))
        for cid, r in tl.loc[tl.index.isin(scores["campaign_id"].unique())].iterrows()
    }
    # conservative bound: every coupon redeemed during the window (panel-based)
    parts = []
    for cid, (ws, we) in windows.items():
        sub = panel[
            panel["week_no"].between(ws, we)
        ].groupby("household_key")["abs_coupon_disc_sum"].sum().rename("cost_all").reset_index()
        sub["campaign_id"] = cid
        parts.append(sub)
    costs_all = pd.concat(parts, ignore_index=True)

    df = scores.merge(costs_all, on=["household_key", "campaign_id"], how="left", validate="1:1")
    df["cost_all"] = df["cost_all"].fillna(0.0)
    tight = tight_costs_by_household(windows)[["household_key", "campaign_id", "cost_tight"]]
    df = df.merge(tight, on=["household_key", "campaign_id"], how="left", validate="1:1")
    df["cost_tight"] = df["cost_tight"].fillna(0.0)
    df["n_weeks_window"] = df["campaign_id"].map({c: w[1] - w[0] + 1 for c, w in windows.items()})
    return df


def select_mask(df: pd.DataFrame, score_col: str | None, frac: float | None) -> np.ndarray:
    """Audience selection per campaign: top-`frac` rows by score within each
    campaign (rank-based, deterministic); blanket when score_col is None."""
    if score_col is None:
        return np.ones(len(df), dtype=bool)
    ranks = df.groupby("campaign_id")[score_col].rank(ascending=False, method="first")
    n = df.groupby("campaign_id")[score_col].transform("size")
    return (ranks <= np.ceil(n * frac)).to_numpy()


def _ratios(incr: float, cost: float) -> dict:
    if not (incr > 0 and cost > 0):
        return {k: np.nan for k in (
            "inc_per_dollar_tight", "inc_per_dollar_all",
            "margin15_per_dollar_tight", "margin25_per_dollar_tight", "margin35_per_dollar_tight",
            "breakeven_margin_tight",
        )}
    out = {
        "inc_per_dollar_tight": incr / cost,
        "breakeven_margin_tight": cost / incr,
    }
    for m in MARGIN_LEVELS:
        out[f"margin{int(m * 100)}_per_dollar_tight"] = m * incr / cost - 1.0
    return out


def scenario_core(df: pd.DataFrame, mask: np.ndarray, mult: np.ndarray | None = None) -> dict:
    """Point metrics for one audience, pooled over campaigns.

    `mult` is a row multiplicity used by the bootstrap (cluster resampling of
    households): every metric then treats a household drawn twice as two
    audience members with identical behaviour.
    """
    if mult is None:
        mult = np.ones(len(df))
    sub = df[mask]
    y = sub["delta"].to_numpy(float)
    w = sub["treated"].to_numpy(int)
    sw = sub["att_weight"].to_numpy(float) * mult[mask]
    weeks = sub["n_weeks_window"].to_numpy(float)
    cost_t = sub["cost_tight"].to_numpy(float)
    cost_a = sub["cost_all"].to_numpy(float)
    m_ = mult[mask]

    codes = sub["_camp_code"].to_numpy()
    ncamp = codes.max() + 1 if len(codes) else 0

    def _group_sum(v):
        return np.bincount(codes, weights=v, minlength=ncamp)

    n_c = _group_sum(np.ones(len(sub)))
    yt_c = _group_sum(y * w * sw)
    wt_c = _group_sum(w * sw)
    yc_c = _group_sum(y * (1 - w) * sw)
    wc_c = _group_sum((1 - w) * sw)
    treated_c = _group_sum(w * m_)
    costt_treated_c = _group_sum(cost_t * w * m_)
    costa_treated_c = _group_sum(cost_a * w * m_)

    weeks_c = np.zeros(ncamp)
    for i in range(ncamp):
        weeks_c[i] = weeks[codes == i][0]

    valid = (wt_c > 0) & (wc_c > 0) & (treated_c > 0)
    uplift_c = np.where(valid, yt_c / np.maximum(wt_c, 1e-12) - yc_c / np.maximum(wc_c, 1e-12), np.nan)
    with np.errstate(invalid="ignore"):
        n_eff = np.where(valid, n_c, 0.0)
        incr_c = uplift_c * weeks_c * n_eff
        cost_t_c = (costt_treated_c / np.maximum(treated_c, 1e-12)) * n_eff
        cost_a_c = (costa_treated_c / np.maximum(treated_c, 1e-12)) * n_eff
    incr = float(np.nansum(incr_c[valid]))
    cost_tight = float(np.nansum(cost_t_c[valid]))
    cost_all = float(np.nansum(cost_a_c[valid]))
    audience_weeks = float((weeks_c * n_eff)[valid].sum())
    return {
        "n_targeted": float(n_eff.sum()),
        "n_campaigns": int(valid.sum()),
        "uplift_per_member_week": incr / audience_weeks if audience_weeks > 0 else np.nan,
        "incr_spend_total": incr,
        "cost_tight": cost_tight,
        "cost_all": cost_all,
        **_ratios(incr, cost_tight),
        "inc_per_dollar_all": incr / cost_all if (incr > 0 and cost_all > 0) else np.nan,
    }


def simulate(df: pd.DataFrame, n_bootstrap: int = N_BOOTSTRAP, seed: int = RANDOM_STATE,
             campaign_set: str = "all") -> pd.DataFrame:
    """Scenario table with cluster-bootstrap CIs (households resampled with
    replacement; audience membership held fixed)."""
    if campaign_set == "layak":
        df = df[df["reliability_flag"].str.startswith("layak")].reset_index(drop=True)
    df = df.copy()
    df["_camp_code"] = pd.factorize(df["campaign_id"])[0]

    masks = {name: select_mask(df, col, frac) for name, col, frac in SCENARIOS}
    hh_codes = pd.factorize(df["household_key"])[0]
    n_hh = hh_codes.max() + 1
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_hh, (n_bootstrap, n_hh))  # shared across scenarios
    rows = []
    for name, _col, _frac in SCENARIOS:
        point = scenario_core(df, masks[name])
        point["scenario"] = name
        point["campaign_set"] = campaign_set
        boot = {k: np.empty(n_bootstrap) for k in
                ("inc_per_dollar_tight", "margin25_per_dollar_tight", "breakeven_margin_tight")}
        for b in range(n_bootstrap):
            hh_mult = np.bincount(draws[b], minlength=n_hh)
            mult = hh_mult[hh_codes].astype(float)
            core = scenario_core(df, masks[name], mult=mult)
            for k in boot:
                boot[k][b] = core[k]
        for k in boot:
            if n_bootstrap > 0:
                lo, hi = np.nanpercentile(boot[k], [2.5, 97.5])
                point[f"{k}_ci_low"], point[f"{k}_ci_high"] = float(lo), float(hi)
            else:
                point[f"{k}_ci_low"] = point[f"{k}_ci_high"] = np.nan
        rows.append(point)
    cols = ["campaign_set", "scenario", "n_targeted", "n_campaigns",
            "uplift_per_member_week", "incr_spend_total", "cost_tight", "cost_all",
            "inc_per_dollar_tight", "inc_per_dollar_tight_ci_low", "inc_per_dollar_tight_ci_high",
            "inc_per_dollar_all",
            "margin15_per_dollar_tight", "margin25_per_dollar_tight",
            "margin25_per_dollar_tight_ci_low", "margin25_per_dollar_tight_ci_high",
            "margin35_per_dollar_tight", "breakeven_margin_tight",
            "breakeven_margin_tight_ci_low", "breakeven_margin_tight_ci_high"]
    return pd.DataFrame(rows)[cols]
