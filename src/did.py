"""Campaign effect: overlap-weighted difference-in-differences per campaign.

Every estimate here is observational - treatment was assigned by the
retailer, not randomized - and is only valid under the unconfoundedness
assumption (R1). Weighting and voucher-cost conventions are locked in
docs/decision-log.md (DL-010..DL-013); spend figures are net (DL-001) in
nominal USD.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.features import (
    BACKBONE_CAMPAIGNS,
    COUPON_CSV,
    DATA_DIR,
    MIN_REPORTABLE_N,
    RANDOM_STATE,
    TRANSACTION_CSV,
)

PRE_WEEKS = 8
N_BOOTSTRAP = 1000
SMD_TARGET = 0.1
ELIGIBLE_FLAGS = ("layak", "layak — utama")

# DL-012: primary weighting = overlap (ATO). Bounded weights ((1-e) treated,
# e control) need no trimming and balance by construction on the overlap
# population. ATT-IPW with trimming (DL-010) is kept as a sensitivity view.
PS_TRIM = (0.05, 0.95)

# R3: margin is an assumption, never a single number.
MARGIN_LEVELS = (0.15, 0.25, 0.35)

# Propensity features, pre-treatment only (R5). The two DL-014 features
# exist because targeting shows win-back selection: households picked on a
# spend dip that naturally recovers (mean reversion). Conditioning on the
# dip level and the recovery trend removes that confound; the far-window
# placebo (weeks -24..-17, never used in fitting) validates it.
PRE_FEATURES = [
    "spend_weekly_pre",
    "active_weeks_pre",
    "promo_share_mean_pre",
    "breadth_mean_pre",
    "recency_pre_end",
    "spend_trend_pre",  # momentum: late-minus-early half of weeks -8..-1
    "spend_dip_level",  # weekly mean of weeks -12..-9 (the dip level)
]

# Far-window placebo contrast: weeks -24..-21 vs -20..-17 (DL-014 gate).
FAR_WINDOW = ((-24, -21), (-20, -17))


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
            "spend_dip_level": weekly_mean(start - 12, start - 9),
            "spend_weekly_far_early": weekly_mean(start + FAR_WINDOW[0][0], start + FAR_WINDOW[0][1]),
            "spend_weekly_far_late": weekly_mean(start + FAR_WINDOW[1][0], start + FAR_WINDOW[1][1]),
            "active_weeks_pre": pre_agg["active_weeks"].fillna(0).to_numpy(),
            "promo_share_mean_pre": pre_agg["promo_share_mean"].fillna(0).to_numpy(),
            "breadth_mean_pre": pre_agg["breadth_mean"].fillna(0).to_numpy(),
            # households with no purchase before the pre window ends get the
            # window length as recency (most conservative in-window value)
            "recency_pre_end": rec.fillna(PRE_WEEKS).astype(float).to_numpy(),
            "coupon_post": coupon_post,
        }
    ).assign(spend_trend_pre=lambda d: d["spend_weekly_pre_late"] - d["spend_weekly_pre_early"])


def _logistic_ps(design: pd.DataFrame) -> np.ndarray:
    X = design[PRE_FEATURES].to_numpy(dtype=float)
    y = design["treated"].to_numpy(dtype=int)
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    pipe.fit(X, y)
    return pipe.predict_proba(X)[:, 1]


def fit_propensity(design: pd.DataFrame, scheme: str = "overlap") -> pd.DataFrame:
    """Logistic propensity plus analysis weights.

    - "overlap" (DL-012, primary): treated weight (1-e), control weight e.
      Bounded in [0,1], so no trimming; the estimand is the effect on the
      overlap population (members near the targeting margin).
    - "att_ipw" (DL-010, sensitivity): treated 1, control e/(1-e), with rows
      outside PS_TRIM flagged ps_keep=False.
    """
    e = _logistic_ps(design)
    y = design["treated"].to_numpy(dtype=int)
    out = design.copy()
    out["ps"] = e
    if scheme == "overlap":
        out["ps_keep"] = True
        out["att_weight"] = np.where(y == 1, 1.0 - e, e)
    elif scheme == "att_ipw":
        out["ps_keep"] = (e >= PS_TRIM[0]) & (e <= PS_TRIM[1])
        out["att_weight"] = np.where(y == 1, 1.0, e / (1.0 - e))
    else:
        raise ValueError(f"unknown weighting scheme: {scheme}")
    return out


def _weighted_did(pre: np.ndarray, post: np.ndarray, treat: np.ndarray, w: np.ndarray) -> float:
    def m(x: np.ndarray, ww: np.ndarray) -> float:
        return float((x * ww).sum() / ww.sum())

    t = treat == 1
    return m(post[t], w[t]) - m(pre[t], w[t]) - (m(post[~t], w[~t]) - m(pre[~t], w[~t]))


def _bootstrap_did(
    pre: np.ndarray, post: np.ndarray, y: np.ndarray, w: np.ndarray, n_bootstrap: int, seed: int
) -> dict:
    """Effect plus household-level bootstrap CI; weights held fixed.

    Diagnostics show the fixed-weight CI matches a refit-propensity
    bootstrap for overlap weights (bounded weights keep PS uncertainty
    small); recorded in AGENTS.md section 2.5.
    """
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
    p_value = float(min(1.0, 2.0 * min(np.mean(atts <= 0), np.mean(atts >= 0))))
    return {
        "att": att,
        "att_ci_low": float(lo),
        "att_ci_high": float(hi),
        "p_value": p_value,
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


def placebo_far_window(design: pd.DataFrame, n_bootstrap=N_BOOTSTRAP, seed=RANDOM_STATE) -> dict:
    """Held-out identification check (DL-014): DiD on weeks -24..-21 vs
    -20..-17 - a window the propensity model never sees. Passing both this
    and the in-window placebo is what 'pre-trend ok' means."""
    return _bootstrap_did(
        design["spend_weekly_far_early"].to_numpy(float),
        design["spend_weekly_far_late"].to_numpy(float),
        design["treated"].to_numpy(int),
        design["att_weight"].to_numpy(float),
        n_bootstrap,
        seed,
    )


def pooled_effect(results: pd.DataFrame) -> dict:
    """Meta-analysis of the reliable campaigns' ATTs (bootstrap SEs).

    Fixed-effect (inverse-variance) and DerSimonian-Laird random-effects
    estimates plus I-squared heterogeneity. Reported as one headline number
    - still observational (R1)."""
    rel = results[results["estimated"] & results["reliability_flag"].str.startswith("layak")]
    att = rel["att"].to_numpy(float)
    se = ((rel["att_ci_high"] - rel["att_ci_low"]) / (2 * 1.959963984540054)).to_numpy(float)
    w = 1.0 / se**2
    mu_fe = float((w * att).sum() / w.sum())
    se_fe = float(np.sqrt(1.0 / w.sum()))
    k = len(att)
    Q = float((w * (att - mu_fe) ** 2).sum())
    i2 = max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0
    c = w.sum() - (w**2).sum() / w.sum()
    tau2 = max(0.0, (Q - (k - 1)) / c) if c > 0 else 0.0
    wr = 1.0 / (se**2 + tau2)
    mu_re = float((wr * att).sum() / wr.sum())
    se_re = float(np.sqrt(1.0 / wr.sum()))
    return {
        "k": int(k),
        "att_fe": mu_fe,
        "att_fe_ci_low": mu_fe - 1.96 * se_fe,
        "att_fe_ci_high": mu_fe + 1.96 * se_fe,
        "att_re": mu_re,
        "att_re_ci_low": mu_re - 1.96 * se_re,
        "att_re_ci_high": mu_re + 1.96 * se_re,
        "i_squared": float(i2),
    }


def smd_table(design: pd.DataFrame) -> pd.DataFrame:
    """Standardised mean differences per pre-feature, before vs after weighting."""
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


def campaign_item_voucher_cost(
    timeline_row,
    hh_campaign: pd.DataFrame,
    txn_csv=TRANSACTION_CSV,
    coupon_csv=COUPON_CSV,
) -> float:
    """Tight voucher cost (DL-013): |COUPON_DISC| on products in the
    campaign's own coupon list, redeemed by treated households during the
    window. Still a proxy (product-list membership, not coupon identity);
    the all-coupons figure from the panel is the conservative upper bound."""
    cid = int(timeline_row.campaign_id)
    ws, we = int(timeline_row.start_week), int(timeline_row.end_week)
    treated = set(hh_campaign.loc[hh_campaign["campaign_id"] == cid, "household_key"])
    query = """
        SELECT t.household_key, SUM(ABS(t.COUPON_DISC)) AS cost
        FROM read_csv_auto(?) t
        JOIN read_csv_auto(?) c ON t.PRODUCT_ID = c.PRODUCT_ID AND c.CAMPAIGN = ?
        WHERE t.WEEK_NO BETWEEN ? AND ? AND t.COUPON_DISC < 0
        GROUP BY t.household_key
    """
    con = duckdb.connect()
    try:
        hh_cost = con.execute(query, [str(txn_csv), str(coupon_csv), cid, ws, we]).df()
    finally:
        con.close()
    return float(hh_cost.loc[hh_cost["household_key"].isin(treated), "cost"].sum())


def build_campaign_results(
    timeline: pd.DataFrame,
    hh_campaign: pd.DataFrame,
    panel: pd.DataFrame,
    n_bootstrap: int = N_BOOTSTRAP,
    base_seed: int = RANDOM_STATE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Full DiD results for every campaign (30 rows) + event-study table.

    Primary weighting: overlap/ATO on the full sample (DL-012); ATT-IPW
    with trimming is computed as a sensitivity column. Non-eligible
    campaigns keep their foundation-phase flag; eligible ones failing
    placebo / balance / effective-n get a `tidak reliable` flag with the
    reason (R7 - flagged, never dropped).
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

        design = fit_propensity(build_campaign_design(r, hh_campaign, panel, pool))
        with_ipw = fit_propensity(
            build_campaign_design(r, hh_campaign, panel, pool), scheme="att_ipw"
        )
        ps_outside_share = 1.0 - float(with_ipw["ps_keep"].mean())
        d_ipw = with_ipw[with_ipw["ps_keep"]].reset_index(drop=True)

        seed = base_seed + cid
        att = estimate_att_bootstrap(design, n_bootstrap, seed)
        pla = placebo_pre_trend(design, n_bootstrap, seed + 10_000)
        pla_far = placebo_far_window(design, n_bootstrap, seed + 20_000)
        att_ipw = estimate_att_bootstrap(d_ipw, n_bootstrap, seed)
        smd = smd_table(design)
        smd_max_before = float(smd["smd_before"].abs().max())
        smd_max_after = float(smd["smd_after"].abs().max())

        ev = event_study_means(r, design, panel)
        ev.insert(0, "campaign_id", cid)
        event_frames.append(ev)

        n_t = int((design["treated"] == 1).sum())
        n_c = int((design["treated"] == 0).sum())
        cost_tight = campaign_item_voucher_cost(r, hh_campaign)
        cost_all = float(design.loc[design["treated"] == 1, "coupon_post"].sum())
        inc_total = att["att"] * n_t

        def ratios(cost: float) -> dict:
            if cost <= 0:
                ratio = np.nan
                margins = {f"margin{int(m * 100)}_per_dollar": np.nan for m in MARGIN_LEVELS}
            else:
                ratio = inc_total / cost
                margins = {
                    f"margin{int(m * 100)}_per_dollar": (m * inc_total - cost) / cost
                    for m in MARGIN_LEVELS
                }
            return {"ratio": ratio, **margins}

        tight = ratios(cost_tight)
        bound = ratios(cost_all)

        in_ok = bool(pla["att_ci_low"] <= 0 <= pla["att_ci_high"])
        far_ok = bool(pla_far["att_ci_low"] <= 0 <= pla_far["att_ci_high"])
        problems = []
        if not in_ok:
            problems.append("pre-trend")
        if not far_ok:
            problems.append("pre-trend jauh")
        if smd_max_after >= SMD_TARGET:
            problems.append("balance")
        if min(n_t, n_c) < MIN_REPORTABLE_N:
            problems.append("n efektif < 30")
        if problems:
            flag, reason = "tidak reliable — " + " & ".join(problems), "; ".join(problems)
        elif cid in BACKBONE_CAMPAIGNS:
            flag, reason = "layak — utama (observasional)", "lolos placebo (dalam & jauh), balance, n"
        else:
            flag, reason = "layak (observasional)", "lolos placebo (dalam & jauh), balance, n"

        n_red = int(redempt_n.get(cid, 0))
        rows.append(
            {
                **base,
                "estimated": True,
                "weight_scheme": "overlap (ATO)",
                "n_analysis": int(len(design)),
                "n_treated_analysis": n_t,
                "n_control_analysis": n_c,
                "ps_outside_trim_share": ps_outside_share,
                "att_ipw_sensitivity": att_ipw["att"],
                "att_ipw_ci_low_sensitivity": att_ipw["att_ci_low"],
                "att_ipw_ci_high_sensitivity": att_ipw["att_ci_high"],
                "smd_max_before": smd_max_before,
                "smd_max_after": smd_max_after,
                **att,
                "placebo_att": pla["att"],
                "placebo_ci_low": pla["att_ci_low"],
                "placebo_ci_high": pla["att_ci_high"],
                "placebo_far_att": pla_far["att"],
                "placebo_far_ci_low": pla_far["att_ci_low"],
                "placebo_far_ci_high": pla_far["att_ci_high"],
                "pre_trend_ok": in_ok,
                "far_pre_trend_ok": far_ok,
                "n_redeemers": n_red,
                "redemption_rate": n_red / int(r.n_treated),
                "voucher_cost_campaign_items": cost_tight,
                "voucher_cost_all_coupons": cost_all,
                "incremental_spend_total": inc_total,
                "inc_spend_per_dollar": tight["ratio"],
                "margin15_per_dollar": tight[f"margin15_per_dollar"],
                "margin25_per_dollar": tight[f"margin25_per_dollar"],
                "margin35_per_dollar": tight[f"margin35_per_dollar"],
                "inc_spend_per_dollar_allcoupons": bound["ratio"],
                "margin35_per_dollar_allcoupons": bound[f"margin35_per_dollar"],
                "reliability_flag": flag,
                "reliability_reason": reason,
            }
        )

    results = pd.DataFrame(rows)
    # non-estimated rows leave these columns as NaN/object - normalise dtypes
    results["estimated"] = results["estimated"].astype(bool)
    for col in ("pre_trend_ok", "far_pre_trend_ok"):
        if col in results.columns:
            results[col] = results[col].fillna(False).astype(bool)
    # multiplicity: Benjamini-Hochberg across the estimated campaigns
    est_mask = results["estimated"].to_numpy()
    if "p_value" in results.columns and est_mask.any():
        from statsmodels.stats.multitest import multipletests

        p = results.loc[est_mask, "p_value"].to_numpy(float)
        _, p_bh, _, _ = multipletests(p, alpha=0.05, method="fdr_bh")        results.loc[est_mask, "p_bh"] = p_bh
        results.loc[est_mask, "significance"] = np.where(
            (p_bh < 0.05) & (results.loc[est_mask, "att"].to_numpy(float) > 0),
            "signifikan positif (BH q<0,05)",
            "tidak signifikan",
        )
    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
    return results, events
