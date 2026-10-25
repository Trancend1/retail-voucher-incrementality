"""Stage 2 observational uplift invariants (household x campaign panel).

Verified facts (AGENTS.md 2.9): 37,976 rows over the 20 estimated campaigns,
treated share 0.1785, strict campaign-time split at week 77 | 81 (12 | 8
campaigns), placebo ATE CI contains 0. The panel is rebuilt from processed
parquets only - the same artifacts the notebook reads.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import GroupKFold

from src.uplift_obs import (
    UPFIT_FEATURES,
    build_uplift_panel,
    campaign_time_split,
    feature_matrix,
    fit_final_models,
    load_stage2_inputs,
    placebo_permutation,
)
from src.features import PROCESSED_DIR

N_PANEL_ROWS = 37_976
TREATED_SHARE = 6_778 / 37_976


@pytest.fixture(scope="session")
def stage2():
    inputs = load_stage2_inputs()
    panel = build_uplift_panel(inputs)
    return {"inputs": inputs, "panel": panel, "split": campaign_time_split(panel)}


def test_panel_invariants(stage2):
    panel = stage2["panel"]
    assert len(panel) == N_PANEL_ROWS
    assert panel["campaign_id"].nunique() == 20
    assert panel["treated"].mean() == pytest.approx(TREATED_SHARE, abs=0.001)
    assert panel[UPFIT_FEATURES].notna().all().all()
    assert panel["redemption_rate_before"].between(0, 1).all()
    # outcome definitions hold row-wise
    assert np.allclose(panel["delta"], panel["spend_weekly_post"] - panel["spend_weekly_pre"])
    assert np.allclose(
        panel["delta_placebo"], panel["spend_weekly_pre_late"] - panel["spend_weekly_pre_early"]
    )
    # tenure is start_week minus first active week; 43 control rows are negative
    # (household not yet shopping at campaign start) - kept, documented
    assert (panel["tenure_weeks"] < 0).sum() == 43


def test_history_features_strictly_pre(stage2):
    """n_campaigns_before must equal a direct recount from hh_campaign."""
    panel, hh_campaign = stage2["panel"], stage2["inputs"]["hh_campaign"]
    row = panel.sample(1, random_state=7).iloc[0]
    start_day = hh_campaign.loc[hh_campaign["campaign_id"] == row["campaign_id"], "start_day"].iloc[0]
    my_targeting = hh_campaign[hh_campaign["household_key"] == row["household_key"]]
    expected = int((my_targeting["start_day"] < start_day).sum())
    assert int(row["n_campaigns_before"]) == expected


def test_split_strict_time_order(stage2):
    split, meta = stage2["split"], None
    assert split["boundary"]["train_max_start_week"] < split["boundary"]["test_min_start_week"]
    train_ids = set(split["train"]["campaign_id"])
    test_ids = set(split["test"]["campaign_id"])
    assert len(train_ids) == 12 and len(test_ids) == 8
    assert train_ids & test_ids == set()
    # test holds a mix of reliability flags (R7: flagged stay visible)
    flags = split["test"].groupby("reliability_flag")["campaign_id"].nunique()
    layak = [f for f in flags.index if f.startswith("layak")]
    flagged = [f for f in flags.index if not f.startswith("layak")]
    assert len(layak) == 1 and flags[layak[0]] == 5
    assert len(flagged) == 1 and flags[flagged[0]] == 3
    assert len(split["test"]) == 14_090


def test_group_cv_folds_disjoint_by_household(stage2):
    """One household never spans GroupKFold folds (R6)."""
    train = stage2["split"]["train"]
    gkf = GroupKFold(n_splits=5)
    groups = train["household_key"].to_numpy()
    seen = {}
    for fold, (_tr, te) in enumerate(gkf.split(train, groups=groups)):
        for hh in np.unique(groups[te]):
            assert seen.setdefault(hh, fold) == fold, f"household {hh} in two folds"


def test_feature_matrix_fixed_vocab(stage2):
    """Held-out campaigns carry all-zero campaign dummies: same width as fit."""
    models = fit_final_models(stage2["split"]["train"])
    vocab = models["campaign_vocab"]
    X_train = feature_matrix(stage2["split"]["train"], campaign_vocab=vocab)
    X_test = feature_matrix(stage2["split"]["test"], campaign_vocab=vocab)
    assert X_train.shape[1] == X_test.shape[1] == len(UPFIT_FEATURES) + len(vocab)
    test_ids = set(stage2["split"]["test"]["campaign_id"])
    assert test_ids & set(vocab) == set()
    # every test row's campaign-dummy block is exactly zero
    assert np.all(X_test[:, len(UPFIT_FEATURES):] == 0)


def test_placebo_ci_contains_zero(stage2):
    """Fake treatment on pre-period outcomes must be indistinguishable from 0."""
    out = placebo_permutation(stage2["split"]["train"], stage2["split"]["test"], n_boot=200)
    base = out["baseline_random"]
    assert base["ci_low"] <= 0 <= base["ci_high"], base
    top = out["deciles"].iloc[0]
    assert top["ci_low"] <= 0 <= top["ci_high"], top


def test_artifacts_when_present():
    """After the notebook runs, the score artifact must match the panel."""
    path = PROCESSED_DIR / "uplift_scores.parquet"
    if not path.exists():
        pytest.skip("uplift_scores.parquet not built yet")
    scores = pd.read_parquet(path)
    assert len(scores) == 14_090
    assert scores[["score_t", "score_x", "score_rfm"]].notna().all().all()
    assert scores["segment"].notna().all()
    assert {"treated", "delta", "ps", "att_weight", "reliability_flag"} <= set(scores.columns)
