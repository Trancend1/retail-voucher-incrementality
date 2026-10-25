"""X5 RetailHero dataset loading and pre-campaign feature build (Stage 1 uplift).

The dataset arrives via scikit-uplift's fetch_x5 into data/external/ (gitignored):
clients.csv.gz, purchases.csv.gz (670 MB, 45.8 M rows), uplift_train.csv.gz.
All purchases in the file happened BEFORE the promo campaign by design of the
competition — the binary target (purchase count increased post-campaign) was
measured on a hidden post-period — so aggregating the full purchase history is
leakage-free for treatment-effect modeling.

History window (verified 2026-10-25): 2018-11-21 .. 2019-03-18; train table
200,039 clients; treatment ~50/50; raw ATE +3.32 pp (0.6365 vs 0.6033).

The client-level feature table is cached to
data/processed/x5_client_features.parquet so tests and the notebook reuse it
without re-scanning 45.8 M rows.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
EXTERNAL = REPO / "data" / "external"
PROCESSED = REPO / "data" / "processed"
FEATURE_PARQUET = PROCESSED / "x5_client_features.parquet"

# Verified X5 facts used as invariants by tests (see module docstring).
N_TRAIN = 200_039
TREATMENT_SHARE = 0.4998
ATE_RAW = 0.0332
HISTORY_MIN = "2018-11-21"
HISTORY_MAX = "2019-03-18"

AGE_MIN, AGE_MAX = 14, 100


def load_raw_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the labeled train table and the client card metadata."""
    train = pd.read_csv(EXTERNAL / "uplift_train.csv.gz")
    clients = pd.read_csv(
        EXTERNAL / "clients.csv.gz",
        parse_dates=["first_issue_date", "first_redeem_date"],
    )
    return train, clients


def aggregate_purchases() -> pd.DataFrame:
    """One DuckDB pass over 45.8 M purchase lines -> client-level RFM-style aggregates.

    purchase_sum repeats on every line of a transaction, so it is collapsed with
    MAX at transaction grain before summing to the client.
    """
    con = duckdb.connect()
    tx = con.execute(
        """
        WITH tx AS (
            SELECT client_id, transaction_id,
                   ANY_VALUE(transaction_datetime) AS dt,
                   MAX(purchase_sum) AS purchase_sum,
                   COUNT(*) AS n_lines,
                   ANY_VALUE(store_id) AS store_id
            FROM read_csv_auto(?)
            GROUP BY client_id, transaction_id
        ),
        bounds AS (SELECT MAX(dt) AS max_dt FROM tx)
        SELECT client_id,
               COUNT(*) AS n_transactions,
               SUM(purchase_sum) AS total_spend,
               SUM(purchase_sum) / COUNT(*) AS avg_basket,
               AVG(n_lines) AS avg_lines_per_tx,
               COUNT(DISTINCT store_id) AS n_stores,
               DATE_DIFF('day', MAX(dt), bounds.max_dt) AS recency_days,
               DATE_DIFF('day', MIN(dt), bounds.max_dt) AS history_span_days
        FROM tx CROSS JOIN bounds
        GROUP BY client_id, bounds.max_dt
        ORDER BY client_id
        """,
        [str(EXTERNAL / "purchases.csv.gz")],
    ).df()
    con.close()
    return tx


def build_client_features() -> pd.DataFrame:
    """Join train labels, card metadata, and purchase aggregates into one feature table."""
    train, clients = load_raw_tables()
    tx = aggregate_purchases()

    df = train.merge(clients, on="client_id", how="left").merge(tx, on="client_id", how="left")
    if df.shape[0] != N_TRAIN:
        raise ValueError(f"expected {N_TRAIN} rows after joins, got {df.shape[0]}")

    history_end = pd.Timestamp(HISTORY_MAX)
    df["age_clean"] = df["age"].clip(AGE_MIN, AGE_MAX)
    df["age_outlier"] = ((df["age"] < AGE_MIN) | (df["age"] > AGE_MAX)).astype(int)
    df["gender"] = df["gender"].fillna("U")
    df["issue_tenure_days"] = (
        (history_end - df["first_issue_date"]).dt.total_seconds() / 86_400
    ).round(1)
    df["has_redeem"] = df["first_redeem_date"].notna().astype(int)
    df["redeem_delay_days"] = (
        (df["first_redeem_date"] - df["first_issue_date"]).dt.total_seconds() / 86_400
    ).round(1)
    df["redeem_delay_days"] = df["redeem_delay_days"].fillna(-1.0)

    cols = [
        "client_id", "treatment_flg", "target",
        "n_transactions", "total_spend", "avg_basket", "avg_lines_per_tx",
        "n_stores", "recency_days", "history_span_days",
        "age_clean", "age_outlier", "gender",
        "issue_tenure_days", "has_redeem", "redeem_delay_days",
    ]
    return df[cols]


def load_x5_features() -> pd.DataFrame:
    """Return the client feature table, building and caching it on first call."""
    if FEATURE_PARQUET.exists():
        return pd.read_parquet(FEATURE_PARQUET)
    df = build_client_features()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_parquet(FEATURE_PARQUET, index=False)
    return df


FEATURE_COLUMNS = [
    "n_transactions", "total_spend", "avg_basket", "avg_lines_per_tx",
    "n_stores", "recency_days", "history_span_days",
    "age_clean", "age_outlier", "issue_tenure_days", "has_redeem",
    "redeem_delay_days",
]


def design_matrix(df: pd.DataFrame) -> np.ndarray:
    """Numeric design matrix: features above plus gender one-hot (F/M/U)."""
    parts = [df[FEATURE_COLUMNS].to_numpy(dtype=float)]
    for level in ("F", "M", "U"):
        parts.append((df["gender"] == level).to_numpy(dtype=float)[:, None])
    return np.hstack(parts)
