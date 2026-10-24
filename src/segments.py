"""Member segmentation: K-means on RFM + promo dependence + category mix.

Descriptive only - segments are never model features, so full-period
features do not violate the pre-treatment rule (cohort-phase precedent).
Definitions are locked in docs/decision-log.md (DL-015); spend figures are
net (DL-001) in nominal USD.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from src.features import (
    NET_SPEND_SQL,
    PRODUCT_CSV,
    RANDOM_STATE,
    TRANSACTION_CSV,
)

# DL-015: stability split and search grid.
P1_WEEKS = (1, 51)
P2_WEEKS = (52, 102)
FULL_WEEKS = (1, 102)
K_RANGE = range(3, 9)
STABILITY_SEEDS = (42, 43, 44, 45, 46)
# Locked after the silhouette/stability probe: k=5 has the tightest
# seed-to-seed stability (ARI 0.641-0.661); after consolidating micro
# clusters (< MIN_REPORTABLE_N) it yields three effective segments.
# See AGENTS.md section 2.6 for the full selection rationale.
K_FINAL = 5

BASE_FEATURES = ("frequency", "monetary", "recency", "promo_share_mean")


def department_shares(
    week_lo: int,
    week_hi: int,
    txn_csv=TRANSACTION_CSV,
    product_csv=PRODUCT_CSV,
) -> pd.DataFrame:
    """Wide household x department spend shares for a week window.

    Shares come straight from the PRODUCT_ID -> DEPARTMENT join, so there is
    no commodity-to-department mapping ambiguity.
    """
    query = f"""
        WITH spend AS (
            SELECT t.household_key, p.DEPARTMENT AS department,
                   SUM({NET_SPEND_SQL}) AS net_spend
            FROM read_csv_auto(?) t
            JOIN read_csv_auto(?) p ON t.PRODUCT_ID = p.PRODUCT_ID
            WHERE t.WEEK_NO BETWEEN ? AND ?
            GROUP BY 1, 2
        )
        SELECT household_key, department,
               net_spend / SUM(net_spend) OVER (PARTITION BY household_key) AS share
        FROM spend
    """
    con = duckdb.connect()
    try:
        long = con.execute(query, [str(txn_csv), str(product_csv), week_lo, week_hi]).df()
    finally:
        con.close()
    wide = long.pivot(index="household_key", columns="department", values="share").fillna(0.0)
    return wide.reset_index()


def build_segment_features(
    panel: pd.DataFrame,
    week_lo: int,
    week_hi: int,
    departments: list[str] | None = None,
    txn_csv=TRANSACTION_CSV,
    product_csv=PRODUCT_CSV,
) -> tuple[pd.DataFrame, list[str]]:
    """Per-household raw features for one window: RFM + promo + dept shares.

    Households with no active week inside the window keep a row (frequency
    0, monetary 0); their recency falls back to the last active week at or
    before the window end.
    """
    win = panel[panel["week_no"].between(week_lo, week_hi)]
    active = win[win["has_purchase"]]
    g = active.groupby("household_key")
    base = pd.DataFrame(
        {
            "frequency": g["week_no"].size(),
            "monetary": g["net_spend"].mean(),
            "promo_share_mean": g["promo_share"].mean(),
        }
    )
    last_in_window = g["week_no"].max()
    last_up_to = (
        panel[panel["has_purchase"] & (panel["week_no"] <= week_hi)]
        .groupby("household_key")["week_no"]
        .max()
    )
    base["recency"] = week_hi - last_up_to.reindex(base.index).fillna(last_in_window)

    all_hh = np.sort(panel["household_key"].unique())
    base = base.reindex(all_hh)
    base["frequency"] = base["frequency"].fillna(0)
    base["monetary"] = base["monetary"].fillna(0.0)
    base["promo_share_mean"] = base["promo_share_mean"].fillna(0.0)
    base = base.reset_index().rename(columns={"index": "household_key"})

    shares = department_shares(week_lo, week_hi, txn_csv, product_csv)
    if departments is None:
        departments = [c for c in shares.columns if c != "household_key"]
    shares = shares.reindex(columns=["household_key"] + list(departments), fill_value=0.0)

    out = base.merge(shares, on="household_key", validate="1:1")
    return out.sort_values("household_key").reset_index(drop=True), list(departments)


def raw_feature_frame(raw: pd.DataFrame, departments: list[str]) -> pd.DataFrame:
    """Transformed (log) feature frame - DL-015 feature set."""
    frame = pd.DataFrame(
        {
            "log_frequency": np.log1p(raw["frequency"]),
            "log_monetary": np.log1p(raw["monetary"].clip(lower=0.0)),
            "log_recency": np.log1p(raw["recency"]),
            "promo_share_mean": raw["promo_share_mean"].fillna(0.0),
        }
    )
    for d in departments:
        frame[f"share_{d}"] = raw[d].to_numpy()
    return frame


def core_mask(raw: pd.DataFrame) -> pd.Series:
    """Core-population mask: households at or below the 99th percentile of
    weekly spend (DL-015 amendment). The excluded top-1% extreme spenders
    still get a segment - assigned to the nearest centroid - they just do
    not pull centroids during fitting. (Winsorising was tried first and
    rejected: clipping ties at the cap created an artificial micro-cluster.)
    """
    return raw["monetary"] <= raw["monetary"].quantile(0.99)


def scale(frame: pd.DataFrame, scaler: StandardScaler | None = None):
    """z-score the feature frame; returns (matrix, fitted scaler)."""
    if scaler is None:
        scaler = StandardScaler().fit(frame.to_numpy(dtype=float))
    return scaler.transform(frame.to_numpy(dtype=float)), scaler


def silhouette_curve(raw: pd.DataFrame, departments: list[str], ks=K_RANGE, seed: int = RANDOM_STATE) -> dict[int, float]:
    """Silhouette on the core population (top-1% spenders excluded)."""
    frame = raw_feature_frame(raw, departments)
    X, _ = scale(frame)
    core = core_mask(raw).to_numpy()
    return {
        int(k): float(
            silhouette_score(
                X[core], KMeans(k, n_init=50, random_state=seed).fit(X[core]).labels_
            )
        )
        for k in ks
    }


def stability_ari(
    raw_p1: pd.DataFrame,
    raw_p2: pd.DataFrame,
    departments: list[str],
    k: int,
    seeds=STABILITY_SEEDS,
) -> list[float]:
    """DL-015 stability: fit on the P1 core, assign all of P2 (in P1's
    scaled space), and compare labels against a model fitted on the P2 core
    (P2's own scaler)."""
    frame1 = raw_feature_frame(raw_p1, departments)
    frame2 = raw_feature_frame(raw_p2, departments)
    X1, scaler1 = scale(frame1)
    X2_own, _ = scale(frame2)
    X2_in_p1, _ = scale(frame2, scaler1)
    core1 = core_mask(raw_p1).to_numpy()
    core2 = core_mask(raw_p2).to_numpy()

    aris = []
    for seed in seeds:
        m1 = KMeans(k, n_init=50, random_state=seed).fit(X1[core1])
        m2 = KMeans(k, n_init=50, random_state=seed).fit(X2_own[core2])
        aris.append(float(adjusted_rand_score(m1.predict(X2_in_p1), m2.predict(X2_own))))
    return aris


def churn_thresholds(panel: pd.DataFrame) -> dict:
    """Data-derived thresholds (DL-015): p95 of the pooled inter-purchase
    gap distribution and p10 of the H2/H1 spend-ratio distribution."""
    active = panel[panel["has_purchase"]]
    gaps = (
        active.sort_values("week_no")
        .groupby("household_key")["week_no"]
        .diff()
        .dropna()
    )
    split = P2_WEEKS[0]
    h1 = panel[panel["week_no"] < split].groupby("household_key")["net_spend"].sum()
    h2 = panel[panel["week_no"] >= split].groupby("household_key")["net_spend"].sum()
    ratio = h2.reindex(h1.index).div(h1.replace(0, np.nan))
    return {
        "gap_p95": float(gaps.quantile(0.95)),
        "ratio_p10": float(ratio.quantile(0.10)),
    }


def churn_flags(panel: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """Per-household churn flag (primary, gap rule) and spend_dropping
    (secondary, ratio rule). Households without H1 spend have no ratio."""
    last = panel[panel["has_purchase"]].groupby("household_key")["week_no"].max()
    current_gap = FULL_WEEKS[1] - last

    split = P2_WEEKS[0]
    h1 = panel[panel["week_no"] < split].groupby("household_key")["net_spend"].sum()
    h2 = panel[panel["week_no"] >= split].groupby("household_key")["net_spend"].sum()
    ratio = h2.reindex(h1.index).div(h1.replace(0, np.nan))

    out = pd.DataFrame(
        {
            "household_key": current_gap.index,
            "current_gap_weeks": current_gap.to_numpy(),
            "churn_risk": (current_gap > thresholds["gap_p95"]).to_numpy(),
            "spend_ratio_h2_h1": ratio.reindex(current_gap.index).to_numpy(),
        }
    )
    out["spend_dropping"] = out["spend_ratio_h2_h1"] < thresholds["ratio_p10"]
    return out.sort_values("household_key").reset_index(drop=True)


def _consolidate_small_clusters(labels: np.ndarray, centroids: np.ndarray, min_n: int) -> np.ndarray:
    """Merge clusters below min_n into the nearest surviving centroid (R8:
    no segment smaller than the reportable cell size is presented)."""
    labels = labels.copy()
    while True:
        sizes = np.bincount(labels, minlength=len(centroids))
        small = np.where((sizes > 0) & (sizes < min_n))[0]
        if len(small) == 0:
            break
        smallest = small[np.argmin(sizes[small])]
        members = np.where(labels == smallest)[0]
        candidates = [c for c in range(len(centroids)) if c != smallest and sizes[c] >= min_n]
        if not candidates:  # nothing to merge into (degenerate k)
            break
        dists = ((centroids[candidates][:, None, :] - centroids[smallest][None, None, :]) ** 2).sum(-1)
        target = candidates[int(np.argmin(dists.ravel()))]
        labels[members] = target
    return labels


def fit_segments(
    raw_full: pd.DataFrame,
    departments: list[str],
    k: int = K_FINAL,
    seed: int = RANDOM_STATE,
    min_n: int = 30,
):
    """Final descriptive model on the full period.

    Fitted on the core population (<= p99 weekly spend); every household,
    extreme spenders included, is assigned to its nearest centroid; clusters
    below min_n are consolidated into the nearest surviving cluster and
    segments are renumbered by size (1 = largest).
    """
    frame = raw_feature_frame(raw_full, departments)
    X, scaler = scale(frame)
    core = core_mask(raw_full).to_numpy()
    model = KMeans(k, n_init=50, random_state=seed).fit(X[core])
    labels = _consolidate_small_clusters(model.predict(X), model.cluster_centers_, min_n)

    # renumber by descending size so segment ids are stable and readable
    order = np.argsort(-np.bincount(labels))
    remap = np.empty(len(order), dtype=int)
    remap[order] = np.arange(1, len(order) + 1)

    segments = raw_full[["household_key"] + list(BASE_FEATURES)].copy()
    segments["segment"] = remap[labels]
    return segments, model, scaler


def build_segment_table(
    segments: pd.DataFrame,
    churn: pd.DataFrame,
    hh_whitespace: pd.DataFrame,
    thresholds: dict,
) -> pd.DataFrame:
    """Gate table: size, spend, promo dependence, churn risk, main
    whitespace, one action - the action follows fixed, documented rules."""
    df = segments.merge(churn, on="household_key", validate="1:1")
    df["total_spend"] = df["monetary"] * df["frequency"]

    ws = (
        hh_whitespace.groupby(["household_key", "commodity_desc"])["expected_spend"]
        .sum()
        .reset_index()
        .merge(df[["household_key", "segment"]], on="household_key", validate="m:1")
    )
    # COUPON/MISC ITEMS is an operator category, not a product - excluded
    # from recommendations per the Phase 3 finding (AGENTS.md section 2.4)
    ws = ws[ws["commodity_desc"] != "COUPON/MISC ITEMS"]
    top_ws = (
        ws.groupby(["segment", "commodity_desc"])["expected_spend"]
        .sum()
        .reset_index()
        .sort_values("expected_spend", ascending=False)
        .drop_duplicates("segment")
        .set_index("segment")
    )
    ws_per_member = ws.groupby(["segment", "household_key"])["expected_spend"].sum().groupby("segment").mean()

    rows = []
    overall_churn = float(df["churn_risk"].mean())
    overall_promo = float(df["promo_share_mean"].mean())
    overall_promo_sd = float(df["promo_share_mean"].std())
    overall_ws = float(ws_per_member.mean())

    for seg, g in df.groupby("segment"):
        n = int(len(g))
        churn_pct = float(g["churn_risk"].mean())
        promo = float(g["promo_share_mean"].mean())
        ws_pm = float(ws_per_member.get(seg, 0.0))
        if churn_pct >= 1.5 * overall_churn:
            action = "Program aktivasi ulang — uji kontak pada member yang gap-nya melewati p95"
        elif promo >= overall_promo + 0.5 * overall_promo_sd:
            action = "Uji migrasi ke benefit non-diskon — ketergantungan promo tinggi"
        elif ws_pm >= overall_ws:
            action = "Dorong kategori whitespace teratas (kandidat, uji coba)"
        else:
            action = "Pertahankan — offer kategori inti + upsell"
        rows.append(
            {
                "segment": int(seg),
                "n": n,
                "share_pct": n / len(df) * 100,
                "mean_weekly_spend_active": float(g["monetary"].mean()),
                "mean_total_spend": float(g["total_spend"].mean()),
                "promo_dependence": promo,
                "churn_risk_pct": churn_pct * 100,
                "spend_dropping_pct": float(g["spend_dropping"].mean()) * 100,
                "whitespace_utama": top_ws.loc[seg, "commodity_desc"] if seg in top_ws.index else "-",
                "whitespace_per_member_usd": ws_pm,
                "satu_aksi": action,
            }
        )
    table = pd.DataFrame(rows).sort_values("segment").reset_index(drop=True)
    table.attrs["thresholds"] = thresholds
    return table
