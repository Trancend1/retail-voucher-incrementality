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


def _sorted_prefix_sums(y, w, score):
    order = np.argsort(-np.asarray(score, float), kind="stable")
    y = np.asarray(y, float)[order]
    w = np.asarray(w, int)[order]
    yt = np.cumsum(y * w)
    nt = np.cumsum(w)
    yc = np.cumsum(y * (1 - w))
    nc = np.cumsum(1 - w)
    k = np.arange(1, len(y) + 1)
    return k, yt, nt, yc, nc


def uplift_curve(y, w, score):
    """Return (fraction_targeted, cumulative incremental outcome) arrays."""
    k, yt, nt, yc, nc = _sorted_prefix_sums(y, w, score)
    valid = (nt > 0) & (nc > 0)
    gain = np.where(valid, (yt / np.maximum(nt, 1) - yc / np.maximum(nc, 1)) * k, np.nan)
    frac = k / len(y)
    frac = frac[valid]
    return frac, gain[valid]


def qini_curve(y, w, score):
    """Return (fraction_targeted, cumulative qini gain) arrays."""
    k, yt, nt, yc, nc = _sorted_prefix_sums(y, w, score)
    valid = (nt > 0) & (nc > 0)
    q = np.where(valid, yt - yc * nt / np.maximum(nc, 1), np.nan)
    frac = k / len(y)
    return frac[valid], q[valid]


def ate(y, w) -> float:
    y, w = np.asarray(y, float), np.asarray(w, int)
    return float(y[w == 1].mean() - y[w == 0].mean())


def auuc(y, w, score) -> float:
    frac, gain = uplift_curve(y, w, score)
    return float(np.trapezoid(gain, frac))


def auuc_summary(y, w, score) -> dict:
    """AUUC vs the random-targeting line, per-client normalized skill included."""
    y, w = np.asarray(y, float), np.asarray(w, int)
    n = len(y)
    value = auuc(y, w, score)
    random_area = 0.5 * ate(y, w) * n
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
    y, w, score, n_deciles: int = 10, n_boot: int = 1000, random_state: int = RANDOM_STATE
) -> pd.DataFrame:
    """Observed uplift per score-decile (1 = highest score) with bootstrap CI.

    Rows carry n, n_treated, n_control so small cells are visible; uplift/CI are
    NaN where the cell or either arm falls below MIN_N_CELL (reported, not
    claimed). CI = percentile bootstrap over resampled clients within decile.
    """
    y = np.asarray(y, float)
    w = np.asarray(w, int)
    score = np.asarray(score, float)
    n = len(y)
    ranks = pd.Series(score).rank(ascending=False, method="first")
    decile = ((ranks - 1) * n_deciles // n + 1).astype(int)

    rng = np.random.default_rng(random_state)
    rows = []
    for d in range(1, n_deciles + 1):
        mask = (decile == d).to_numpy()
        yd, wd = y[mask], w[mask]
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
            row["uplift"] = float(yd[wd == 1].mean() - yd[wd == 0].mean())
            boots = np.empty(n_boot)
            for b in range(n_boot):
                idx = rng.integers(0, n_d, n_d)
                yb, wb = yd[idx], wd[idx]
                t, c = wb == 1, wb == 0
                if t.sum() == 0 or c.sum() == 0:
                    boots[b] = np.nan
                else:
                    boots[b] = yb[t].mean() - yb[c].mean()
            lo, hi = np.nanpercentile(boots, [2.5, 97.5])
            row["ci_low"], row["ci_high"] = float(lo), float(hi)
        rows.append(row)
    return pd.DataFrame(rows)


def ate_bootstrap(y, w, n_boot: int = 1000, random_state: int = RANDOM_STATE) -> dict:
    """Random-targeting baseline: overall ATE with percentile bootstrap CI."""
    y, w = np.asarray(y, float), np.asarray(w, int)
    rng = np.random.default_rng(random_state)
    n = len(y)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        yb, wb = y[idx], w[idx]
        boots[b] = yb[wb == 1].mean() - yb[wb == 0].mean()
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return {"ate": ate(y, w), "ci_low": float(lo), "ci_high": float(hi), "n": int(n)}


def standardized_mean_diff(x, w) -> float:
    """SMD of one covariate between treated and control (pooled-SD convention)."""
    x, w = np.asarray(x, float), np.asarray(w, int)
    x1, x0 = x[w == 1], x[w == 0]
    pooled = np.sqrt((x1.var(ddof=1) + x0.var(ddof=1)) / 2)
    if pooled == 0:
        return 0.0
    return float((x1.mean() - x0.mean()) / pooled)
