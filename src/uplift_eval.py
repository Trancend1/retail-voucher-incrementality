"""Uplift evaluation: curves, AUUC, decile table with bootstrap CI, baselines.

Shared by Stage 1 (randomized, X5) and Stage 2 (observational, Dunnhumby).
All functions are outcome-agnostic (binary or continuous y) and take
w in {0, 1} with 1 = treated.

Curve definitions (clients sorted by score descending, prefix k):
- uplift curve gain(k) = (Yt(k)/Nt(k) - Yc(k)/Nc(k)) * k
  = cumulative incremental outcome vs targeting a random k. At k = N the gain
  equals ATE * N.
- qini curve q(k) = Yt(k) - Yc(k) * Nt(k)/Nc(k).
- AUUC = trapezoid area under the uplift curve over the fraction-targeted grid
  [0, 1]; the random-targeting baseline is the straight line from (0, 0) to
  (1, ATE * N), area 0.5 * ATE * N. "skill" = AUUC - random area; negative
  skill means the ranking is worse than random.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RANDOM_STATE = 42
MIN_N_CELL = 30  # R8: cells below this are reported but not claimed


def _sorted_prefix_sums(y, w, score, sample_weight=None):
    order = np.argsort(-np.asarray(score, float), kind="stable")
    y = np.asarray(y, float)[order]
    w = np.asarray(w, int)[order]
    sw = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)[order]
    yt = np.cumsum(y * w * sw)
    wt = np.cumsum(w * sw)
    yc = np.cumsum(y * (1 - w) * sw)
    wc = np.cumsum((1 - w) * sw)
    k = np.arange(1, len(y) + 1)
    return k, yt, wt, yc, wc


def uplift_curve(y, w, score, sample_weight=None):
    """Return (fraction_targeted, cumulative incremental outcome) arrays.

    With sample_weight, arm means at each prefix are weighted (e.g. overlap
    weights on an observational evaluation); the fraction axis stays a client
    count, and `k` in the gain formula remains the number of clients targeted.
    """
    k, yt, wt, yc, wc = _sorted_prefix_sums(y, w, score, sample_weight)
    valid = (wt > 0) & (wc > 0)
    gain = np.where(valid, (yt / np.maximum(wt, 1e-12) - yc / np.maximum(wc, 1e-12)) * k, np.nan)
    frac = k / len(y)
    return frac[valid], gain[valid]


def qini_curve(y, w, score):
    """Return (fraction_targeted, cumulative qini gain) arrays."""
    k, yt, nt, yc, nc = _sorted_prefix_sums(y, w, score)
    valid = (nt > 0) & (nc > 0)
    q = np.where(valid, yt - yc * nt / np.maximum(nc, 1), np.nan)
    frac = k / len(y)
    return frac[valid], q[valid]


def ate(y, w, sample_weight=None) -> float:
    y, w = np.asarray(y, float), np.asarray(w, int)
    sw = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
    t, c = w == 1, w == 0
    return float((y[t] * sw[t]).sum() / sw[t].sum() - (y[c] * sw[c]).sum() / sw[c].sum())


def auuc(y, w, score, sample_weight=None) -> float:
    frac, gain = uplift_curve(y, w, score, sample_weight)
    return float(np.trapezoid(gain, frac))


def auuc_summary(y, w, score, sample_weight=None) -> dict:
    """AUUC vs the random-targeting line, per-client normalized skill included."""
    y, w = np.asarray(y, float), np.asarray(w, int)
    n = len(y)
    value = auuc(y, w, score, sample_weight)
    random_area = 0.5 * ate(y, w, sample_weight) * n
    return {
        "n": int(n),
        "auuc": value,
        "auuc_random": random_area,
        "skill": value - random_area,
        "skill_per_client": (value - random_area) / n,
    }


def qini_auc(y, w, score) -> float:
    frac, q = qini_curve(y, w, score)
    return float(np.trapezoid(q, frac))


def uplift_deciles(
    y, w, score, n_deciles: int = 10, n_boot: int = 1000, random_state: int = RANDOM_STATE,
    sample_weight=None,
) -> pd.DataFrame:
    """Observed uplift per score-decile (1 = highest score) with bootstrap CI.

    Rows carry n, n_treated, n_control so small cells are visible; uplift/CI are
    NaN where the cell or either arm falls below MIN_N_CELL (reported, not
    claimed). Point estimates are weighted when sample_weight is given (arm
    sizes for the n-gate stay unweighted counts). CI = percentile bootstrap
    over resampled clients within decile.
    """
    y = np.asarray(y, float)
    w = np.asarray(w, int)
    score = np.asarray(score, float)
    sw = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
    n = len(y)
    ranks = pd.Series(score).rank(ascending=False, method="first")
    decile = ((ranks - 1) * n_deciles // n + 1).astype(int)

    def _wdiff(yv, wv, sv):
        t, c = wv == 1, wv == 0
        return (yv[t] * sv[t]).sum() / sv[t].sum() - (yv[c] * sv[c]).sum() / sv[c].sum()

    rng = np.random.default_rng(random_state)
    rows = []
    for d in range(1, n_deciles + 1):
        mask = (decile == d).to_numpy()
        yd, wd, sd = y[mask], w[mask], sw[mask]
        n_d, n_t, n_c = len(yd), int(wd.sum()), int((wd == 0).sum())
        row = {
            "decile": d,
            "n": n_d,
            "n_treated": n_t,
            "n_control": n_c,
            "uplift": np.nan,
            "ci_low": np.nan,
            "ci_high": np.nan,
        }
        if min(n_t, n_c) >= MIN_N_CELL:
            row["uplift"] = float(_wdiff(yd, wd, sd))
            boots = np.empty(n_boot)
            for b in range(n_boot):
                idx = rng.integers(0, n_d, n_d)
                yb, wb, sb = yd[idx], wd[idx], sd[idx]
                if (wb == 1).sum() == 0 or (wb == 0).sum() == 0:
                    boots[b] = np.nan
                else:
                    boots[b] = _wdiff(yb, wb, sb)
            lo, hi = np.nanpercentile(boots, [2.5, 97.5])
            row["ci_low"], row["ci_high"] = float(lo), float(hi)
        rows.append(row)
    return pd.DataFrame(rows)


def ate_bootstrap(y, w, n_boot: int = 1000, random_state: int = RANDOM_STATE, sample_weight=None) -> dict:
    """Random-targeting baseline: overall (optionally weighted) ATE with percentile bootstrap CI."""
    y, w = np.asarray(y, float), np.asarray(w, int)
    sw = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
    rng = np.random.default_rng(random_state)
    n = len(y)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        boots[b] = ate(y[idx], w[idx], sw[idx])
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return {"ate": ate(y, w, sw), "ci_low": float(lo), "ci_high": float(hi), "n": int(n)}


def standardized_mean_diff(x, w) -> float:
    """SMD of one covariate between treated and control (pooled-SD convention)."""
    x, w = np.asarray(x, float), np.asarray(w, int)
    x1, x0 = x[w == 1], x[w == 0]
    pooled = np.sqrt((x1.var(ddof=1) + x0.var(ddof=1)) / 2)
    if pooled == 0:
        return 0.0
    return float((x1.mean() - x0.mean()) / pooled)
