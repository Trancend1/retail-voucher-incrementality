"""X5 RetailHero Stage-1 data invariants (verified facts in src/x5.py docstring).

The client feature table is cached at data/processed/x5_client_features.parquet;
the session fixture (conftest) builds it once from the raw external CSVs if
missing.
"""

import numpy as np
import pytest

from src.uplift_eval import standardized_mean_diff
from src.x5 import (
    ATE_RAW,
    FEATURE_COLUMNS,
    N_TRAIN,
    TREATMENT_SHARE,
    design_matrix,
    load_x5_features,
)


def test_shape_labels_and_raw_ate(x5_features):
    assert x5_features.shape[0] == N_TRAIN
    assert x5_features["client_id"].is_unique
    share = x5_features["treatment_flg"].mean()
    assert share == pytest.approx(TREATMENT_SHARE, abs=0.001)
    g = x5_features.groupby("treatment_flg")["target"].mean()
    ate = g[1] - g[0]
    assert ate == pytest.approx(ATE_RAW, abs=0.0005)
    assert set(x5_features["target"].unique()) <= {0, 1}


def test_features_complete_and_sane(x5_features):
    assert x5_features[FEATURE_COLUMNS].notna().all().all()
    assert (x5_features["n_transactions"] >= 1).all()
    assert (x5_features["total_spend"] > 0).all()
    assert (x5_features["recency_days"] >= 0).all()
    # history window 2018-11-21..2019-03-18 = 117 days
    assert x5_features["history_span_days"].between(1, 117).all()
    assert x5_features["gender"].isin(["F", "M", "U"]).all()


def test_randomization_covariate_balance(x5_features):
    """Randomized assignment, verified: max |SMD| = 0.023 (has_redeem); all other
    features <= 0.009. Threshold 0.05 is well inside the |SMD| < 0.1 convention."""
    w = x5_features["treatment_flg"].to_numpy()
    smds = {}
    for col in FEATURE_COLUMNS:
        smd = standardized_mean_diff(x5_features[col].to_numpy(float), w)
        smds[col] = smd
        assert abs(smd) < 0.05, f"{col} SMD={smd:.3f}"
    assert abs(smds["has_redeem"]) == pytest.approx(0.023, abs=0.002)


def test_design_matrix_shape_and_finiteness(x5_features):
    X = design_matrix(x5_features)
    assert X.shape == (len(x5_features), len(FEATURE_COLUMNS) + 3)
    assert np.isfinite(X).all()
