"""T-learner and X-learner meta-learners for conditional treatment effects.

Implemented directly on scikit-learn base learners so the estimator behavior is
inspectable and deterministic, and identical code serves Stage 1 (randomized)
and Stage 2 (observational) without pulling a heavy causal-modeling stack.

Conventions: w in {0, 1} (1 = treated), y continuous or binary; all estimators
respect `random_state` (repo default 42).
"""

from __future__ import annotations

import numpy as np
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

RANDOM_STATE = 42


def make_base_learner(random_state: int = RANDOM_STATE) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=200,
        learning_rate=0.08,
        max_depth=None,
        min_samples_leaf=40,
        l2_regularization=1.0,
        random_state=random_state,
    )


class TLearner:
    """Differential response surfaces: tau(x) = mu1(x) - mu0(x)."""

    def __init__(self, base=None):
        self.base = base if base is not None else make_base_learner()

    def fit(self, X, y, w):
        X, y, w = np.asarray(X, float), np.asarray(y, float), np.asarray(w, int)
        self.mu0_ = clone(self.base).fit(X[w == 0], y[w == 0])
        self.mu1_ = clone(self.base).fit(X[w == 1], y[w == 1])
        return self

    def predict(self, X):
        return self.mu1_.predict(np.asarray(X, float)) - self.mu0_.predict(np.asarray(X, float))


class XLearner:
    """Kunzel et al. (2019) X-learner.

    Stage 1: mu0/mu1 response surfaces. Stage 2: imputed effects
    D1 = Y1 - mu0(X1) on treated, D0 = mu1(X0) - Y0 on control, each fitted
    with its own effect model tau1/tau0. Combination
    tau(x) = g(x) * tau0(x) + (1 - g(x)) * tau1(x), with g the propensity.
    Under randomization a constant empirical propensity is the honest choice
    (`propensity="constant"`); a logistic model is available for observational
    use.
    """

    def __init__(self, base=None, propensity: str = "constant"):
        if propensity not in ("constant", "logistic"):
            raise ValueError("propensity must be 'constant' or 'logistic'")
        self.base = base if base is not None else make_base_learner()
        self.propensity = propensity

    def fit(self, X, y, w):
        X, y, w = np.asarray(X, float), np.asarray(y, float), np.asarray(w, int)
        self.mu0_ = clone(self.base).fit(X[w == 0], y[w == 0])
        self.mu1_ = clone(self.base).fit(X[w == 1], y[w == 1])

        X0, y0 = X[w == 0], y[w == 0]
        X1, y1 = X[w == 1], y[w == 1]
        d1 = y1 - self.mu0_.predict(X1)
        d0 = self.mu1_.predict(X0) - y0
        self.tau1_ = clone(self.base).fit(X1, d1)
        self.tau0_ = clone(self.base).fit(X0, d0)

        if self.propensity == "constant":
            self.g_ = float(w.mean())
        else:
            self.ps_ = LogisticRegression(max_iter=1000, C=1.0).fit(X, w)
        return self

    def _g(self, X):
        if self.propensity == "constant":
            return np.full(len(X), self.g_)
        return self.ps_.predict_proba(X)[:, 1]

    def predict(self, X):
        X = np.asarray(X, float)
        g = self._g(X)
        return g * self.tau0_.predict(X) + (1 - g) * self.tau1_.predict(X)
