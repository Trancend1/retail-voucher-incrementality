"""Campaign effect: IPW-weighted difference-in-differences per campaign.

Every estimate here is observational - treatment was assigned by the
retailer, not randomized - and is only valid under the unconfoundedness
assumption (R1). Design knobs are locked in docs/decision-log.md
(DL-010, DL-011); spend figures are net (DL-001) in nominal USD.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.features import (
    BACKBONE_CAMPAIGNS,
    DATA_DIR,
    MIN_REPORTABLE_N,
    RANDOM_STATE,
)

# DL-010 knobs.
PRE_WEEKS = 8
PS_TRIM = (0.05, 0.95)
N_BOOTSTRAP = 1000
SMD_TARGET = 0.1
ELIGIBLE_FLAGS = ("layak", "layak — utama")

# R3: margin is an assumption, never a single number.
MARGIN_LEVELS = (0.15, 0.25, 0.35)

# Propensity features, pre-window only (R5).
PRE_FEATURES = [
    "spend_weekly_pre",
    "active_weeks_pre",
    "promo_share_mean_pre",
    "breadth_mean_pre",
    "recency_pre_end",
]


def load_coupon_redempt(csv_path=DATA_DIR / "coupon_redempt.csv") -> pd.DataFrame:
    """coupon_redempt normalized - an outcome, never a treatment (R10)."""
    df = pd.read_csv(csv_path)
    return df.rename(
        columns={"DAY": "day", "COUPON_UPC": "coupon_upc", "CAMPAIGN": "campaign_id"}
    )


def build_campaign_design(
    timeline_row, hh_campaign: pd.DataFrame, panel: pd.DataFrame, all_households=None
) -> pd.DataFrame:
    """Treated/control assignment plus pre/post aggregates for one campaign.

    Control = households never targeted by this campaign nor by any campaign
    whose window overlaps it - the same definition as the foundation-phase
    control pool. Pre window = PRE_WEEKS weeks before start_week; post =
    the campaign window. All spend figures are weekly averages (window
    length normalised).
    """
    cid = int(timeline_row.campaign_id)
    start, end = int(timeline_row.start_week), int(timeline_row.end_week)
    pre_lo, pre_hi = start - PRE_WEEKS, start - 1
    mid = pre_lo + PRE_WEEKS // 2

    treated = set(hh_campaign.loc[hh_campaign["campaign_id"] == cid, "household_key"])
    excluded = set(treated)
    for other in str(timeline_row.overlaps_with).split(","):
        if other:
            excluded |= set(
                hh_campaign.loc[hh_campaign["campaign_id"] == int(other), "household_key"]
            )
    pool = (
        np.sort(panel["household_key"].unique())
        if all_households is None
        else np.asarray(all_households)
    )
    control = set(int(h) for h in pool) - excluded

    ids = np.array(sorted(treated | control), dtype=int)
    idx = pd.Index(ids, name="household_key")
    win = panel[panel["household_key"].isin(ids)]

    def weekly_mean(lo: int, hi: int) -> np.ndarray:
        sub = win[(win["week_no"] >= lo) & (win["week_no"] <= hi)]
        sums = sub.groupby("household_key")["net_spend"].sum()
        return (sums.reindex(idx).fillna(0.0) / (hi - lo + 1)).to_numpy()

    pre = win[(win["week_no"] >= pre_lo) & (win["week_no"] <= pre_hi)]
    pre_agg = (
        pre.groupby("household_key")
        .agg(
            active_weeks=("has_purchase", "sum"),
            promo_share_mean=("promo_share", "mean"),
            breadth_mean=("category_breadth", "mean"),
        )
        .reindex(idx)
    )
    coupon_post = (
        win[(win["week_no"] >= start) & (win["week_no"] <= end)]
        .groupby("household_key")["abs_coupon_disc_sum"]
        .sum()
        .reindex(idx)
        .fillna(0.0)
        .to_numpy()
    )
    rec = (
        panel.loc[panel["week_no"] == pre_hi, ["household_key", "recency_weeks"]]
        .set_index("household_key")["recency_weeks"]
        .reindex(idx)
    )

    return pd.DataFrame(
        {
            "household_key": ids,
            "treated": np.isin(ids, sorted(treated)).astype(int),
            "spend_weekly_pre": weekly_mean(pre_lo, pre_hi),
            "spend_weekly_pre_early": weekly_mean(pre_lo, mid - 1),
            "spend_weekly_pre_late": weekly_mean(mid, pre_hi),
            "spend_weekly_post": weekly_mean(start, end),
            "active_weeks_pre": pre_agg["active_weeks"].fillna(0).to_numpy(),
            "promo_share_mean_pre": pre_agg["promo_share_mean"].fillna(0).to_numpy(),
            "breadth_mean_pre": pre_agg["breadth_mean"].fillna(0).to_numpy(),
            # households with no purchase before the pre window ends get the
            # window length as recency (most conservative in-window value)
            "recency_pre_end": rec.fillna(PRE_WEEKS).astype(float).to_numpy(),
            "coupon_post": coupon_post,
        }
    )


def fit_propensity(design: pd.DataFrame) -> pd.DataFrame:
    """Logistic propensity + ATT weights (treated 1, control e/(1-e)).

    Rows with e outside PS_TRIM are flagged ps_keep=False; the caller drops
    them and reports the trimmed share and effective n.
    """
    X = design[PRE_FEATURES].to_numpy(dtype=float)
    y = design["treated"].to_numpy(dtype=int)
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    pipe.fit(X, y)
    e = pipe.predict_proba(X)[:, 1]

    out = design.copy()
    out["ps"] = e
    out["ps_keep"] = (e >= PS_TRIM[0]) & (e <= PS_TRIM[1])
    out["att_weight"] = np.where(y == 1, 1.0, e / (1.0 - e))
    return out


def _weighted_did(pre: np.ndarray, post: np.ndarray, treat: np.ndarray, w: np.ndarray) -> float:
    def m(x: np.ndarray, ww: np.ndarray) -> float:
        return float((x * ww).sum() / ww.sum())

    t = treat == 1
    return m(post[t], w[t]) - m(pre[t], w[t]) - (m(post[~t], w[~t]) - m(pre[~t], w[~t]))


def _bootstrap_did(
    pre: np.ndarray, post: np.ndarray, y: np.ndarray, w: np.ndarray, n_bootstrap: int, seed: int
) -> dict:
    """ATT plus household-level bootstrap CI; weights held fixed."""
    att = _weighted_did(pre, post, y, w)
    t = y == 1
    pre_t = float((pre[t] * w[t]).sum() / w[t].sum())
    rng = np.random.default_rng(seed)
    n = len(y)
    atts = np.empty(n_bootstrap)
    lifts = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        i = rng.integers(0, n, n)
        atts[b] = _weighted_did(pre[i], post[i], y[i], w[i])
        pt = (pre[i][t[i]] * w[i][t[i]]).sum() / w[i][t[i]].sum()
        lifts[b] = atts[b] / pt * 100 if pt > 0 else np.nan
    lo, hi = np.percentile(atts, [2.5, 97.5])
    llo, lhi = np.nanpercentile(lifts, [2.5, 97.5])
    return {
        "att": att,
        "att_ci_low": float(lo),
        "att_ci_high": float(hi),
        "pre_treated_weekly": pre_t,
        "lift_pct": att / pre_t * 100 if pre_t > 0 else np.nan,
        "lift_ci_low": float(llo),
        "lift_ci_high": float(lhi),
    }


def estimate_att_bootstrap(design: pd.DataFrame, n_bootstrap=N_BOOTSTRAP, seed=RANDOM_STATE) -> dict:
    return _bootstrap_did(
        design["spend_weekly_pre"].to_numpy(float),
        design["spend_weekly_post"].to_numpy(float),
        design["treated"].to_numpy(int),
        design["att_weight"].to_numpy(float),
        n_bootstrap,
        seed,
    )


def placebo_pre_trend(design: pd.DataFrame, n_bootstrap=N_BOOTSTRAP, seed=RANDOM_STATE) -> dict:
    """DiD on the pre window split in half - should be indistinguishable
    from zero; a CI excluding 0 flags a pre-trend problem (R7)."""
    return _bootstrap_did(
        design["spend_weekly_pre_early"].to_numpy(float),
        design["spend_weekly_pre_late"].to_numpy(float),
        design["treated"].to_numpy(int),
        design["att_weight"].to_numpy(float),
        n_bootstrap,
        seed,
    )


def smd_table(design: pd.DataFrame) -> pd.DataFrame:
    """Standardised mean differences per pre-feature, before vs after IPW."""
    y = design["treated"].to_numpy(int)
    w = design["att_weight"].to_numpy(float)
    t = y == 1
    rows = []
    for col in PRE_FEATURES:
        x = design[col].to_numpy(float)
        smd_before = (x[t].mean() - x[~t].mean()) / np.sqrt((x[t].var(ddof=1) + x[~t].var(ddof=1)) / 2)
        m1 = np.average(x[t], weights=w[t])
        m0 = np.average(x[~t], weights=w[~t])
        v1 = np.average((x[t] - m1) ** 2, weights=w[t])
        v0 = np.average((x[~t] - m0) ** 2, weights=w[~t])
        smd_after = (m1 - m0) / np.sqrt((v1 + v0) / 2) if (v1 + v0) > 0 else np.nan
        rows.append({"feature": col, "smd_before": float(smd_before), "smd_after": float(smd_after)})
    return pd.DataFrame(rows)


def event_study_means(timeline_row, design: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Weekly weighted mean spend per group around the campaign start."""
    start, end = int(timeline_row.start_week), int(timeline_row.end_week)
    info = design[["household_key", "treated", "att_weight"]]
    win = panel[
        panel["household_key"].isin(design["household_key"])
        & (panel["week_no"] >= start - PRE_WEEKS)
        & (panel["week_no"] <= end)
    ].merge(info, on="household_key", validate="m:1")

    rows = []
    for wk in range(start - PRE_WEEKS, end + 1):
        sub = win[win["week_no"] == wk]
        for grp, g in sub.groupby("treated"):
            wgt = g["att_weight"].to_numpy(float)
            rows.append(
                {
                    "event_week": wk - start,
                    "group": "treated" if grp == 1 else "control",
                    "mean_weekly_spend": float((g["net_spend"].to_numpy(float) * wgt).sum() / wgt.sum()),
                    "n": int(len(g)),
                }
            )
    return pd.DataFrame(rows)


def build_campaign_results(
    timeline: pd.DataFrame,
    hh_campaign: pd.DataFrame,
    panel: pd.DataFrame,
    n_bootstrap: int = N_BOOTSTRAP,
    base_seed: int = RANDOM_STATE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Full DiD results for every campaign (30 rows) + event-study table.

    Non-eligible campaigns keep their foundation-phase flag and get no
    estimate; eligible ones that fail placebo / balance / effective-n get a
    `tidak reliable` flag with the reason (R7 - flagged, never dropped).
    """
    redempt_n = load_coupon_redempt().groupby("campaign_id")["household_key"].nunique()
    pool = np.sort(panel["household_key"].unique())

    rows: list[dict] = []
    event_frames: list[pd.DataFrame] = []
    for r in timeline.itertuples():
        cid = int(r.campaign_id)
        base = {
            "campaign_id": cid,
            "type": r.type,
            "start_week": int(r.start_week),
            "end_week": int(r.end_week),
            "n_weeks_window": int(r.end_week) - int(r.start_week) + 1,
            "n_treated": int(r.n_treated),
            "n_control": int(r.n_control_pool),
            "reliability_flag_input": r.reliability_flag,
            "estimated": False,
        }
        if r.reliability_flag not in ELIGIBLE_FLAGS:
            base.update(
                reliability_flag=r.reliability_flag,
                reliability_reason=r.eligibility_reason,
            )
            rows.append(base)
            continue

        design_full = build_campaign_design(r, hh_campaign, panel, pool)
        with_ps = fit_propensity(design_full)
        d = with_ps[with_ps["ps_keep"]].reset_index(drop=True)

        seed = base_seed + cid
        att = estimate_att_bootstrap(d, n_bootstrap, seed)
        pla = placebo_pre_trend(d, n_bootstrap, seed + 10_000)
        smd = smd_table(d)
        smd_max_before = float(smd["smd_before"].abs().max())
        smd_max_after = float(smd["smd_after"].abs().max())

        ev = event_study_means(r, d, panel)
        ev.insert(0, "campaign_id", cid)
        event_frames.append(ev)

        t = d["treated"] == 1
        n_t = int(t.sum())
        n_c = int((~t).sum())
        voucher_cost = float(d.loc[t, "coupon_post"].sum())
        inc_total = att["att"] * n_t
        has_cost = voucher_cost > 0
        ratio = inc_total / voucher_cost if has_cost else np.nan
        margins = {
            f"margin{int(m * 100)}_per_dollar": (m * inc_total - voucher_cost) / voucher_cost
            if has_cost
            else np.nan
            for m in MARGIN_LEVELS
        }

        problems = []
        if not (pla["att_ci_low"] <= 0 <= pla["att_ci_high"]):
            problems.append("pre-trend")
        if smd_max_after >= SMD_TARGET:
            problems.append("balance")
        if min(n_t, n_c) < MIN_REPORTABLE_N:
            problems.append("n efektif < 30")
        if problems:
            flag, reason = "tidak reliable — " + " & ".join(problems), "; ".join(problems)
        elif cid in BACKBONE_CAMPAIGNS:
            flag, reason = "layak — utama (observasional)", "lolos placebo, balance, n"
        else:
            flag, reason = "layak (observasional)", "lolos placebo, balance, n"

        n_red = int(redempt_n.get(cid, 0))
        rows.append(
            {
                **base,
                "estimated": True,
                "n_analysis": int(len(d)),
                "n_treated_analysis": n_t,
                "n_control_analysis": n_c,
                "trim_share": 1.0 - len(d) / len(design_full),
                "ps_mean_treated": float(d.loc[t, "ps"].mean()),
                "ps_mean_control": float(d.loc[~t, "ps"].mean()),
                "smd_max_before": smd_max_before,
                "smd_max_after": smd_max_after,
                **att,
                "placebo_att": pla["att"],
                "placebo_ci_low": pla["att_ci_low"],
                "placebo_ci_high": pla["att_ci_high"],
                "pre_trend_ok": bool(pla["att_ci_low"] <= 0 <= pla["att_ci_high"]),
                "n_redeemers": n_red,
                "redemption_rate": n_red / int(r.n_treated),
                "voucher_cost": voucher_cost,
                "incremental_spend_total": inc_total,
                "inc_spend_per_dollar": ratio,
                **margins,
                "reliability_flag": flag,
                "reliability_reason": reason,
            }
        )

    results = pd.DataFrame(rows)
    # non-estimated rows leave these columns as NaN/object - normalise dtypes
    results["estimated"] = results["estimated"].astype(bool)
    if "pre_trend_ok" in results.columns:
        results["pre_trend_ok"] = results["pre_trend_ok"].fillna(False).astype(bool)
    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
    return results, events
