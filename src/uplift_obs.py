"""Stage 2: observational uplift on the Dunnhumby panel (household x campaign).

Every number from this module is observational - treatment was assigned by the
retailer, not randomized - and only valid under the unconfoundedness assumption
(R1). The design reuses the Phase 4 machinery so definitions stay identical:
pre-window features and control pools come from src.did (DL-012 overlap
weights, DL-014 trend/dip conditioning), the campaign timeline and flags come
from the processed parquets, and evaluation runs through src.uplift_eval with
overlap weights as sample weights.

Grain: one row per (household, estimated campaign). Outcome is the DiD-style
delta of weekly net spend (window mean minus pre-8-week mean), in USD/week.
Split is by campaign time with a strict week boundary; flagged campaigns stay
in the evaluation output with their flag (R7), while model fitting uses only
gate-passing campaigns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from src import did
from src.features import PROCESSED_DIR
from src.uplift_learners import TLearner, XLearner
from src.uplift_eval import ate_bootstrap, auuc_summary, uplift_deciles

# 60% earliest estimated campaigns as train (12 of 20); the cut is placed so
# that max(train start_week) < min(test start_week) - verified strict.
N_TRAIN_CAMPAIGNS = 12
N_FOLDS = 5

# Pre-window features only (R5): the seven DiD features plus each household's
# campaign history, all computed strictly before the campaign start.
HISTORY_FEATURES = ["n_campaigns_before", "redemption_rate_before", "tenure_weeks"]
UPFIT_FEATURES = did.PRE_FEATURES + HISTORY_FEATURES


def load_stage2_inputs() -> dict:
    """Processed parquets (never recomputed with other definitions) + redemptions."""
    timeline = pd.read_parquet(PROCESSED_DIR / "campaign_timeline.parquet")
    hh_campaign = pd.read_parquet(PROCESSED_DIR / "hh_campaign.parquet")
    panel = pd.read_parquet(PROCESSED_DIR / "hh_week.parquet")
    did_results = pd.read_parquet(PROCESSED_DIR / "campaign_did_results.parquet")
    hh_clv = pd.read_parquet(PROCESSED_DIR / "hh_clv.parquet")[["household_key", "first_active_week"]]
    return {
        "timeline": timeline,
        "hh_campaign": hh_campaign,
        "panel": panel,
        "did_results": did_results,
        "redempt": did.load_coupon_redempt(),
        "hh_clv": hh_clv,
    }


def _history_features(rows: pd.DataFrame, hh_campaign: pd.DataFrame,
                      redempt: pd.DataFrame, hh_clv: pd.DataFrame) -> pd.DataFrame:
    """Campaign history per (household, campaign), strictly before the campaign start.

    hh_campaign already carries each campaign's start_day/start_week (joined at
    the foundation phase), so no timeline join is needed here.
    """
    first_active = hh_clv.set_index("household_key")["first_active_week"]

    out = rows[["household_key", "campaign_id"]].copy()
    start_day_map = hh_campaign.drop_duplicates("campaign_id").set_index("campaign_id")["start_day"]
    start_day = out["campaign_id"].map(start_day_map).to_numpy()
    start_week = rows["campaign_id"].map(
        hh_campaign.drop_duplicates("campaign_id").set_index("campaign_id")["start_week"]
    ).to_numpy()

    n_before = np.empty(len(out))
    red_before = np.empty(len(out))
    hh = out["household_key"].to_numpy()
    tgt_hh = hh_campaign["household_key"].to_numpy()
    tgt_start = hh_campaign["start_day"].to_numpy()
    order = np.argsort(tgt_hh)
    tgt_hh_sorted, tgt_start_sorted = tgt_hh[order], tgt_start[order]
    # one row per (household, campaign): a household may redeem several coupons
    # of the same campaign, but that is still one campaign received
    red_one = redempt.groupby(["household_key", "campaign_id"], as_index=False)["day"].min()
    red_hh = red_one["household_key"].to_numpy()
    red_day = red_one["day"].to_numpy()
    red_order = np.argsort(red_hh)
    red_hh_sorted, red_day_sorted = red_hh[red_order], red_day[red_order]

    for i in range(len(out)):
        lo = np.searchsorted(tgt_hh_sorted, hh[i], "left")
        hi = np.searchsorted(tgt_hh_sorted, hh[i], "right")
        n_before[i] = int((tgt_start_sorted[lo:hi] < start_day[i]).sum())
        lo_r = np.searchsorted(red_hh_sorted, hh[i], "left")
        hi_r = np.searchsorted(red_hh_sorted, hh[i], "right")
        n_red = int((red_day_sorted[lo_r:hi_r] < start_day[i]).sum()) if hi_r > lo_r else 0
        red_before[i] = n_red / n_before[i] if n_before[i] > 0 else 0.0

    out["n_campaigns_before"] = n_before.astype(int)
    out["redemption_rate_before"] = red_before
    out["tenure_weeks"] = start_week - first_active.reindex(pd.Index(hh)).to_numpy()
    return out


def build_uplift_panel(inputs: dict) -> pd.DataFrame:
    """Pooled (household, estimated campaign) design with features, outcome, PS and weights."""
    timeline, hh_campaign, panel = inputs["timeline"], inputs["hh_campaign"], inputs["panel"]
    did_results = inputs["did_results"]
    estimated = did_results.loc[did_results["estimated"], ["campaign_id", "reliability_flag"]]
    flag_map = estimated.set_index("campaign_id")["reliability_flag"]
    pool = np.sort(panel["household_key"].unique())

    frames = []
    for r in timeline.itertuples():
        if int(r.campaign_id) not in flag_map.index:
            continue
        design = did.fit_propensity(did.build_campaign_design(r, hh_campaign, panel, pool))
        keep = ["household_key", "treated", "spend_weekly_pre", "spend_weekly_post",
                "spend_weekly_pre_early", "spend_weekly_pre_late", "ps", "att_weight",
                *did.PRE_FEATURES]
        keep = list(dict.fromkeys(keep))  # PRE_FEATURES already contains spend_weekly_pre
        d = design[keep].copy()
        d["campaign_id"] = int(r.campaign_id)
        d["start_week"] = int(r.start_week)
        d["reliability_flag"] = flag_map.loc[int(r.campaign_id)]
        frames.append(d)
    panel_hc = pd.concat(frames, ignore_index=True)
    panel_hc["delta"] = panel_hc["spend_weekly_post"] - panel_hc["spend_weekly_pre"]
    # placebo outcome: pre-window spend change, untouched by any treatment
    panel_hc["delta_placebo"] = panel_hc["spend_weekly_pre_late"] - panel_hc["spend_weekly_pre_early"]

    hist = _history_features(
        panel_hc, hh_campaign, inputs["redempt"], inputs["hh_clv"]
    )
    panel_hc = panel_hc.merge(hist, on=["household_key", "campaign_id"], validate="1:1")
    return panel_hc


def campaign_time_split(panel: pd.DataFrame, n_train: int = N_TRAIN_CAMPAIGNS) -> dict:
    """Split campaigns by start time; the boundary must be strict in weeks."""
    meta = (
        panel[["campaign_id", "start_week", "reliability_flag"]]
        .drop_duplicates()
        .sort_values(["start_week", "campaign_id"])
        .reset_index(drop=True)
    )
    train_ids = meta["campaign_id"].iloc[:n_train]
    test_ids = meta["campaign_id"].iloc[n_train:]
    max_train = meta["start_week"].iloc[:n_train].max()
    min_test = meta["start_week"].iloc[n_train:].min()
    if max_train >= min_test:
        raise ValueError(f"non-strict time boundary: train max week {max_train} >= test min week {min_test}")
    train_mask = panel["campaign_id"].isin(set(train_ids))
    test_mask = panel["campaign_id"].isin(set(test_ids))
    return {
        "train": panel[train_mask].reset_index(drop=True),
        "test": panel[test_mask].reset_index(drop=True),
        "campaign_meta": meta,
        "boundary": {"train_max_start_week": int(max_train), "test_min_start_week": int(min_test)},
    }


def feature_matrix(panel_hc: pd.DataFrame, campaign_vocab=None):
    """Numeric matrix: pre-window features + one-hot campaign id on a FIXED vocabulary.

    The vocabulary must be supplied at predict time (taken from the fit call):
    held-out campaigns are absent from it, so their rows carry all-zero campaign
    columns - the same information a deployed model would have on a new
    campaign. This keeps train/test column alignment deterministic.
    """
    parts = [panel_hc[UPFIT_FEATURES].to_numpy(dtype=float)]
    if campaign_vocab is None:
        campaign_vocab = sorted(panel_hc["campaign_id"].unique())
    ids = pd.Categorical(panel_hc["campaign_id"], categories=campaign_vocab)
    dummies = pd.get_dummies(pd.Series(ids), prefix="camp", dtype=float)
    parts.append(dummies.to_numpy())
    return np.hstack(parts)


def group_cv_scores(X, y, w, groups, n_folds: int = N_FOLDS, seed: int = 0) -> dict:
    """Out-of-fold T/X scores under GroupKFold by household - one household
    never spans folds, and rows repeat across campaigns only inside a fold."""
    gkf = GroupKFold(n_splits=n_folds)
    score_t = np.full(len(y), np.nan)
    score_x = np.full(len(y), np.nan)
    for tr, te in gkf.split(X, y, groups=groups):
        tl = TLearner().fit(X[tr], y[tr], w[tr])
        xl = XLearner(propensity="logistic").fit(X[tr], y[tr], w[tr])
        score_t[te] = tl.predict(X[te])
        score_x[te] = xl.predict(X[te])
    assert np.isfinite(score_t).all() and np.isfinite(score_x).all()
    return {"score_t": score_t, "score_x": score_x}


def fit_final_models(train: pd.DataFrame) -> dict:
    """Fit T- and X-learner on gate-passing train-period campaigns."""
    fit_rows = train["reliability_flag"].str.startswith("layak")
    d = train[fit_rows]
    vocab = sorted(int(c) for c in d["campaign_id"].unique())
    X = feature_matrix(d, campaign_vocab=vocab)
    return {
        "t": TLearner().fit(X, d["delta"].to_numpy(float), d["treated"].to_numpy(int)),
        "x": XLearner(propensity="logistic").fit(X, d["delta"].to_numpy(float), d["treated"].to_numpy(int)),
        "campaign_vocab": vocab,
        "n_fit": int(fit_rows.sum()),
        "n_fit_campaigns": int(d["campaign_id"].nunique()),
    }


def evaluate_scores(test: pd.DataFrame, scores: dict, n_boot: int = 1000) -> dict:
    """Weighted evaluation on the held-out campaigns: AUUC skill, deciles, ATE."""
    y = test["delta"].to_numpy(float)
    w = test["treated"].to_numpy(int)
    sw = test["att_weight"].to_numpy(float)
    out = {
        "baseline_random": ate_bootstrap(y, w, n_boot=n_boot, sample_weight=sw),
        "by_model": {},
        "deciles": {},
    }
    for name, score in scores.items():
        out["by_model"][name] = auuc_summary(y, w, score, sample_weight=sw)
        out["deciles"][name] = uplift_deciles(
            y, w, score, n_boot=n_boot, sample_weight=sw
        )
    return out


def save_stage2_outputs(test: pd.DataFrame, scores: dict, ev: dict) -> tuple:
    """Write uplift_scores.parquet (grain: household x test campaign) and
    uplift_eval_results.parquet (long-form deciles per score)."""
    out = test[
        ["household_key", "campaign_id", "treated", "delta", "spend_weekly_pre",
         "spend_weekly_post", "ps", "att_weight", "reliability_flag", "start_week"]
    ].copy()
    for name, score in scores.items():
        col = "score_" + name.split(" ")[0].lower()
        out[col] = np.asarray(score, float)
    segments = pd.read_parquet(PROCESSED_DIR / "segments.parquet")[["household_key", "segment"]]
    out = out.merge(segments, on="household_key", how="left", validate="m:1")

    decile_rows = []
    for name, dec in ev["deciles"].items():
        d = dec.copy()
        d.insert(0, "model", name)
        decile_rows.append(d)
    results = pd.concat(decile_rows, ignore_index=True)

    out.to_parquet(PROCESSED_DIR / "uplift_scores.parquet", index=False)
    results.to_parquet(PROCESSED_DIR / "uplift_eval_results.parquet", index=False)
    return out, results


def placebo_permutation(train: pd.DataFrame, test: pd.DataFrame, n_boot: int = 1000,
                        seed: int = 4242) -> dict:
    """Fake treatment in the pre period: permute treated labels within campaign,
    use the pre-window spend change as outcome, and re-run the full pipeline.

    Under a correct pipeline the weighted ATE and every decile must be
    indistinguishable from zero (CIs reported).
    """
    rng = np.random.default_rng(seed)

    def permute_treated(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        perm = np.empty(len(out), dtype=int)
        for _, idx in df.groupby("campaign_id").indices.items():
            perm[idx] = rng.permutation(idx)
        out["treated"] = df["treated"].to_numpy()[perm]
        return out

    tr = permute_treated(train)
    te = permute_treated(test)
    tr_fit = tr[tr["reliability_flag"].str.startswith("layak")]
    vocab = sorted(int(c) for c in tr_fit["campaign_id"].unique())
    X_tr = feature_matrix(tr_fit, campaign_vocab=vocab)
    model = TLearner().fit(X_tr, tr_fit["delta_placebo"].to_numpy(float), tr_fit["treated"].to_numpy(int))
    score = model.predict(feature_matrix(te, campaign_vocab=vocab))

    y = te["delta_placebo"].to_numpy(float)
    w = te["treated"].to_numpy(int)
    sw = te["att_weight"].to_numpy(float)
    return {
        "baseline_random": ate_bootstrap(y, w, n_boot=n_boot, sample_weight=sw),
        "summary": auuc_summary(y, w, score, sample_weight=sw),
        "deciles": uplift_deciles(y, w, score, n_boot=n_boot, sample_weight=sw),
    }
