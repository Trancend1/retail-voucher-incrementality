"""Uplift learners + evaluation on synthetic ground truth (effect known by construction).

Synthetic DGP: y = mu(X) + tau(X)*w + noise with randomized w ~ Bernoulli(0.5).
Because the true tau(x) is known, these tests check the machinery end-to-end:
learners must recover the effect direction, curves must close at ATE*N, and a
random ranking must show ~zero skill. Real-data invariants for X5 live in
tests/test_x5.py.
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from src.uplift_learners import TLearner, XLearner
from src.uplift_eval import (
    MIN_N_CELL,
    ate_bootstrap,
    auuc_summary,
    qini_auc,
    standardized_mean_diff,
    uplift_curve,
    uplift_deciles,
)


def make_synthetic(n=20_000, tau_scale=2.0, noise=0.7, seed=7):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3))
    mu = X[:, 0] + 0.5 * X[:, 1]
    tau = tau_scale * (X[:, 0] + 0.5)
    w = rng.integers(0, 2, n)
    y = mu + tau * w + noise * rng.normal(size=n)
    return X, y, w, tau


@pytest.fixture(scope="module")
def fitted():
    X, y, w, tau = make_synthetic()
    split = 15_000
    tl = TLearner().fit(X[:split], y[:split], w[:split])
    xl = XLearner().fit(X[:split], y[:split], w[:split])
    return {
        "X_test": X[split:],
        "y_test": y[split:],
        "w_test": w[split:],
        "tau_test": tau[split:],
        "pred_t": tl.predict(X[split:]),
        "pred_x": xl.predict(X[split:]),
    }


def test_learners_recover_heterogeneous_effect(fitted):
    """Rank correlation between predicted and true tau must be high on holdout."""
    for pred in (fitted["pred_t"], fitted["pred_x"]):
        rho = spearmanr(pred, fitted["tau_test"]).statistic
        assert rho > 0.9, f"spearman {rho}"


def test_uplift_curve_closes_at_ate_times_n(fitted):
    frac, gain = uplift_curve(fitted["y_test"], fitted["w_test"], fitted["pred_x"])
    y, w = fitted["y_test"], fitted["w_test"]
    expected = (y[w == 1].mean() - y[w == 0].mean()) * len(y)
    assert frac[0] > 0 and frac[-1] == pytest.approx(1.0)
    assert gain[-1] == pytest.approx(expected, rel=1e-9)


def test_auuc_oracle_beats_random_and_inverted_is_negative(fitted):
    y, w, tau = fitted["y_test"], fitted["w_test"], fitted["tau_test"]
    oracle = auuc_summary(y, w, tau)
    inverted = auuc_summary(y, w, -tau)
    model = auuc_summary(y, w, fitted["pred_x"])
    # oracle reaches most of the theoretical headroom; inverting the ranking sinks it
    assert oracle["skill_per_client"] > 0.5 * (tau.mean() * 0.5)
    assert model["skill_per_client"] > 0.5 * oracle["skill_per_client"]
    assert inverted["skill"] < 0


def test_auuc_random_score_near_zero():
    """A meaningless score must not beat random targeting beyond noise."""
    rng = np.random.default_rng(11)
    X, y, w, _tau = make_synthetic(n=20_000, seed=11)
    score = rng.normal(size=len(y))
    s = auuc_summary(y, w, score)
    assert abs(s["skill_per_client"]) < 0.05


def test_decile_table_invariants(fitted):
    d = uplift_deciles(fitted["y_test"], fitted["w_test"], fitted["pred_x"], n_boot=200)
    assert len(d) == 10
    assert d["n"].sum() == len(fitted["y_test"])
    assert d["n"].max() - d["n"].min() <= 1
    assert (d["ci_low"] <= d["uplift"]).all() and (d["uplift"] <= d["ci_high"]).all()
    # strong heterogeneous effect: top decile clearly above bottom decile
    assert d.loc[0, "uplift"] > d.loc[9, "uplift"] + 1.0
    assert (d[["n_treated", "n_control"]].min(axis=1) >= MIN_N_CELL).all()


def test_decile_small_cells_suppressed():
    """Cells under the minimum n must surface as NaN, never as a claim."""
    rng = np.random.default_rng(3)
    n = 100
    score = rng.normal(size=n)
    y = rng.normal(size=n)
    w = rng.integers(0, 2, n)
    d = uplift_deciles(y, w, score, n_deciles=10, n_boot=50)
    assert (d["n"] == 10).all()
    assert d["uplift"].isna().all()
    assert d[["n", "n_treated", "n_control"]].notna().all().all()


def test_ate_bootstrap_contains_point(fitted):
    out = ate_bootstrap(fitted["y_test"], fitted["w_test"], n_boot=300)
    assert out["ci_low"] <= out["ate"] <= out["ci_high"]
    assert out["n"] == len(fitted["y_test"])


def test_qini_auc_positive_for_oracle(fitted):
    assert qini_auc(fitted["y_test"], fitted["w_test"], fitted["tau_test"]) > 0


def test_smd_detects_imbalance():
    rng = np.random.default_rng(5)
    w = rng.integers(0, 2, 10_000)
    balanced = rng.normal(size=10_000)
    shifted = balanced + 1.0 * w
    assert abs(standardized_mean_diff(balanced, w)) < 0.1
    assert standardized_mean_diff(shifted, w) > 0.5


def test_xlearner_propensity_validation():
    with pytest.raises(ValueError):
        XLearner(propensity="bogus")
