"""CLV 52 minggu via BG/NBD + Gamma-Gamma on the weekly hh_week panel.

Unit conventions and the calibration/holdout split are locked in
docs/decision-log.md (DL-006, DL-007). All spend figures are net (DL-001)
in nominal USD; the horizon is always stated with the metric (R4:
'CLV 52 minggu', never 'lifetime value').
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from lifetimes import BetaGeoFitter, GammaGammaFitter
from lifetimes.utils import ConvergenceError
from scipy import stats
from scipy.special import hyp2f1

from src.features import RANDOM_STATE, build_rfm

# DL-006: validation split and publication horizon.
CALIBRATION_END_WEEK = 76
HOLDOUT_WEEKS = 26
CLV_HORIZON_WEEKS = 52

N_BOOTSTRAP = 1000
# lifetimes' documented remedy when the MLE hits a flat likelihood surface;
# the used coefficient stays visible on the fitted object (penalizer_coef).
_PENALIZER_LADDER = (0.0, 0.01, 0.1)


def _fit_with_fallback(fitter_cls, fit_args):
    """Fit an MLE fitter, stepping up the penalizer on ConvergenceError."""
    last_err: Exception | None = None
    for penalizer in _PENALIZER_LADDER:
        try:
            fitter = fitter_cls(penalizer_coef=penalizer)
            fitter.fit(*fit_args)
            return fitter
        except ConvergenceError as err:  # pragma: no cover - data dependent
            last_err = err
    raise last_err  # type: ignore[misc]


def build_summary(panel: pd.DataFrame, end_week: int) -> pd.DataFrame:
    """Lifetimes summary at weekly grain (DL-007 unit conventions).

    frequency = active weeks after the first; recency = last active week -
    first active week; T = end_week - first active week (exposure);
    monetary = mean net_spend per active week.
    """
    window = panel[(panel["week_no"] <= end_week) & panel["has_purchase"]]
    g = (
        window.groupby("household_key")
        .agg(
            first_active_week=("week_no", "min"),
            last_active_week=("week_no", "max"),
            n_active_weeks=("week_no", "size"),
            total_net_spend=("net_spend", "sum"),
        )
        .reset_index()
    )
    g["frequency"] = g["n_active_weeks"] - 1
    g["recency"] = g["last_active_week"] - g["first_active_week"]
    g["T"] = end_week - g["first_active_week"]
    g["monetary"] = g["total_net_spend"] / g["n_active_weeks"]
    return g[
        [
            "household_key",
            "frequency",
            "recency",
            "T",
            "monetary",
            "n_active_weeks",
            "first_active_week",
            "last_active_week",
            "total_net_spend",
        ]
    ]


def fit_bg_nbd(summary: pd.DataFrame) -> BetaGeoFitter:
    """BG/NBD on (frequency, recency, T)."""
    return _fit_with_fallback(
        BetaGeoFitter,
        (
            summary["frequency"].astype(float),
            summary["recency"].astype(float),
            summary["T"].astype(float),
        ),
    )


def fit_gamma_gamma(summary: pd.DataFrame) -> GammaGammaFitter:
    """Gamma-Gamma on repeat households (frequency > 0, monetary > 0)."""
    pop = summary[(summary["frequency"] > 0) & (summary["monetary"] > 0)]
    return _fit_with_fallback(
        GammaGammaFitter,
        (pop["frequency"].astype(float), pop["monetary"].astype(float)),
    )


def predict_spending(
    bgf: BetaGeoFitter, ggf: GammaGammaFitter, summary: pd.DataFrame, horizon_weeks: int
) -> pd.DataFrame:
    """Expected active weeks and net spend over the next horizon_weeks.

    predicted_purchases is bounded by the horizon: at weekly grain a
    household can be 'active' at most once per week.
    """
    out = summary[["household_key", "frequency", "recency", "T", "monetary"]].copy()
    f = out["frequency"].astype(float)
    r = out["recency"].astype(float)
    t = out["T"].astype(float)
    out["p_alive"] = bgf.conditional_probability_alive(f, r, t)
    out["predicted_purchases"] = bgf.conditional_expected_number_of_purchases_up_to_time(
        horizon_weeks, f, r, t
    )
    # lifetimes' conditional expectation returns NaN for frequency == 0
    # (households seen in a single week ever) with some parameter values; the
    # closed form for x = 0 is stable, so compute those rows directly:
    # E[Y(t)|x=0] = ((a+b-1)/(a-1)) * (1 - ((alpha+T)/(alpha+T+t))^r
    #               * hyp2f1(r, b, a+b-1, t/(alpha+T+t)))
    x0 = out["frequency"] == 0
    if x0.any():
        r_p = float(bgf.params_["r"])
        alpha_p = float(bgf.params_["alpha"])
        a_p = float(bgf.params_["a"])
        b_p = float(bgf.params_["b"])
        t0 = t[x0].to_numpy()
        ratio = (alpha_p + t0) / (alpha_p + t0 + horizon_weeks)
        hyper = hyp2f1(r_p, b_p, a_p + b_p - 1, horizon_weeks / (alpha_p + t0 + horizon_weeks))
        e0 = (a_p + b_p - 1) / (a_p - 1) * (1 - ratio**r_p * hyper)
        out.loc[x0, "predicted_purchases"] = np.clip(e0, 0.0, None)
    out["expected_monetary"] = ggf.conditional_expected_average_profit(
        f, out["monetary"].astype(float)
    )
    out["predicted_spend"] = out["predicted_purchases"] * out["expected_monetary"]
    return out


def frequency_monetary_correlation(summary: pd.DataFrame) -> dict:
    """Spearman correlation between frequency and monetary — the Gamma-Gamma
    independence assumption check (high |rho| -> documented limitation)."""
    rho = stats.spearmanr(summary["frequency"], summary["monetary"])
    return {"spearman_rho": float(rho.statistic), "p_value": float(rho.pvalue)}


def naive_baseline(panel: pd.DataFrame, end_week: int, horizon_weeks: int) -> pd.DataFrame:
    """Per-household historical mean weekly net spend since the first active
    week, extrapolated over the horizon (DL-007: the deliberately strong
    naive comparator)."""
    rfm = build_rfm(panel, end_week)
    weeks_exposed = end_week - rfm["first_active_week"] + 1
    out = rfm[["household_key"]].copy()
    out["naive_predicted_spend"] = (rfm["total_net_spend"] / weeks_exposed) * horizon_weeks
    return out


def evaluate_holdout(
    panel: pd.DataFrame,
    bgf: BetaGeoFitter,
    ggf: GammaGammaFitter,
    summary_cal: pd.DataFrame,
    end_week: int = CALIBRATION_END_WEEK,
    horizon_weeks: int = HOLDOUT_WEEKS,
    n_bootstrap: int = N_BOOTSTRAP,
    seed: int = RANDOM_STATE,
) -> tuple[dict, pd.DataFrame]:
    """Model vs naive baseline on holdout total spend per household.

    Returns (metrics dict, per-household frame for calibration plots). The
    bootstrap CI is for the MAE difference (model - naive); positive values
    mean the model is worse. Whatever the outcome, it gets reported (R9).
    """
    model_pred = predict_spending(bgf, ggf, summary_cal, horizon_weeks)[
        ["household_key", "predicted_spend"]
    ]
    naive = naive_baseline(panel, end_week, horizon_weeks)
    holdout_actual = panel[panel["week_no"] > end_week].groupby("household_key")["net_spend"].sum()

    per_hh = (
        summary_cal[["household_key"]]
        .merge(model_pred, on="household_key", validate="1:1")
        .merge(naive, on="household_key", validate="1:1")
    )
    per_hh["actual_spend"] = per_hh["household_key"].map(holdout_actual).fillna(0.0)

    y = per_hh["actual_spend"].to_numpy()
    m_model = per_hh["predicted_spend"].to_numpy()
    m_naive = per_hh["naive_predicted_spend"].to_numpy()

    def _mae(yhat: np.ndarray) -> float:
        return float(np.mean(np.abs(y - yhat)))

    def _rmse(yhat: np.ndarray) -> float:
        return float(np.sqrt(np.mean((y - yhat) ** 2)))

    metrics = {
        "n_households": int(len(per_hh)),
        "horizon_weeks": int(horizon_weeks),
        "mae_model": _mae(m_model),
        "rmse_model": _rmse(m_model),
        "mae_naive": _mae(m_naive),
        "rmse_naive": _rmse(m_naive),
        "spearman_model_actual": float(stats.spearmanr(m_model, y).statistic),
        "spearman_naive_actual": float(stats.spearmanr(m_naive, y).statistic),
    }

    rng = np.random.default_rng(seed)
    n = len(per_hh)
    point_diff = metrics["mae_model"] - metrics["mae_naive"]
    diffs = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        idx = rng.integers(0, n, n)
        y_b = y[idx]
        diffs[b] = float(np.mean(np.abs(y_b - m_model[idx]))) - float(
            np.mean(np.abs(y_b - m_naive[idx]))
        )
    # Self-check: bootstrap resampling is unbiased for the point statistic, so
    # a large gap here means the resampling itself is misaligned.
    if abs(float(diffs.mean()) - point_diff) > 5.0:
        raise AssertionError(
            f"bootstrap mean diff {diffs.mean():.2f} far from point diff {point_diff:.2f} "
            "- resampling is likely misaligned"
        )
    metrics["mae_diff_p2.5"] = float(np.percentile(diffs, 2.5))
    metrics["mae_diff_p97.5"] = float(np.percentile(diffs, 97.5))
    metrics["p_model_worse"] = float(np.mean(diffs > 0))
    return metrics, per_hh
