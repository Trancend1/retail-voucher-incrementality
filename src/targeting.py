"""Targeting list export (Phase 8 / DL-021): outputs/targeting_sample.xlsx.

One row per scored member: the uplift score comes from the member's most
recent held-out campaign row (X-learner, observational), enriched with the
segment, CLV decile (same computation as the star schema), promo dependence,
top whitespace category (operator category excluded), a deterministic offer
rule, a data-anchored voucher cap, and the include flag (top-2 uplift decile
within that campaign - the playbook's default budget rule).

Everything is derived from verified parquets; the xlsx carries an "asumsi"
sheet listing every rule and its source, per the spec.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.features import PROCESSED_DIR

OUTPUT_XLSX = Path(__file__).resolve().parent.parent / "outputs" / "targeting_sample.xlsx"

OPERATOR_CATEGORY = "COUPON/MISC ITEMS"
TOP_K_DECILES = 2  # playbook default: top-2 uplift decile = include

SEGMENT_NAMES = {1: "mesin pertumbuhan", 2: "promo-dependent", 3: "rentan hilang"}

OUTPUT_COLUMNS = [
    "household_key", "segment", "clv_decile", "uplift_score", "uplift_decile",
    "promo_dependence", "top_whitespace_category", "recommended_offer",
    "voucher_cap_usd", "include_flag",
]


def _offer_rule(segment: int, uplift_decile: int) -> str:
    """Deterministic offer matrix (DL-021): priority to reactivation risk, then
    promo-dependence handling, then whitespace push for stable spenders."""
    if segment == 3:
        return "aktivasi ulang: kontak program win-back + voucher kecil nilai kategori whitespace"
    if segment == 2 and uplift_decile <= 4:
        return "uji benefit non-diskon (poin/pengalaman) - jangan menambah diskon"
    if uplift_decile <= TOP_K_DECILES:
        return "voucher kategori whitespace (nilai standar)"
    if segment == 1:
        return "pertahankan: upsell kategori whitespace tanpa insentif diskon tambahan"
    return "tidak ditarget periode ini (di luar top decile, tanpa sinyal risiko)"


def build_targeting_list() -> pd.DataFrame:
    scores = pd.read_parquet(PROCESSED_DIR / "uplift_scores.parquet")
    segments = pd.read_parquet(PROCESSED_DIR / "segments.parquet")
    hh_clv = pd.read_parquet(PROCESSED_DIR / "hh_clv.parquet")
    whitespace = pd.read_parquet(PROCESSED_DIR / "hh_whitespace.parquet")

    # latest held-out campaign per member (most recent start_week row)
    latest = (
        scores.sort_values(["household_key", "start_week", "campaign_id"])
        .groupby("household_key", as_index=False)
        .tail(1)
        .copy()
    )
    # uplift decile within that member's latest campaign (1 = highest score)
    ranks = latest.groupby("campaign_id")["score_x"].rank(ascending=False, method="first")
    sizes = latest.groupby("campaign_id")["score_x"].transform("size")
    latest["uplift_decile"] = ((ranks - 1) * 10 // sizes + 1).astype(int)

    # clv decile - identical computation to the star schema (src/starschema.py)
    clv = hh_clv[["household_key", "clv_52w"]].copy()
    clv["clv_decile"] = pd.qcut(clv["clv_52w"].rank(method="first"), 10, labels=False).astype(int) + 1

    promo = segments.set_index("household_key")["promo_share_mean"]
    top_ws = (
        whitespace[whitespace["commodity_desc"] != OPERATOR_CATEGORY]
        .sort_values(["household_key", "expected_spend"], ascending=[True, False])
        .groupby("household_key", as_index=False)
        .head(1)[["household_key", "commodity_desc"]]
        .rename(columns={"commodity_desc": "top_whitespace_category"})
    )

    # voucher cap: data-anchored guardrail = p90 of observed all-coupon cost per
    # treated member under the held-out campaigns (rounded up to whole dollars)
    treated = scores[scores["treated"] == 1]
    from src.simulate import load_roi_inputs

    roi = load_roi_inputs()
    treated_costs = roi[(roi["treated"] == 1) & (roi["cost_all"] > 0)]["cost_all"]
    voucher_cap = float(np.ceil(treated_costs.quantile(0.90)))

    out = (
        latest[["household_key", "campaign_id", "score_x", "uplift_decile"]]
        .merge(segments[["household_key", "segment"]], on="household_key", validate="1:1")
        .merge(clv[["household_key", "clv_decile"]], on="household_key", validate="1:1")
        .merge(top_ws, on="household_key", how="left", validate="1:1")
    )
    out["promo_dependence"] = out["household_key"].map(promo)
    out["uplift_score"] = out["score_x"].round(3)
    out["recommended_offer"] = [
        _offer_rule(int(s), int(d)) for s, d in zip(out["segment"], out["uplift_decile"])
    ]
    out["voucher_cap_usd"] = voucher_cap
    out["include_flag"] = (out["uplift_decile"] <= TOP_K_DECILES).astype(int)
    out["segment"] = out["segment"].map(SEGMENT_NAMES)
    return out[OUTPUT_COLUMNS].sort_values(
        ["include_flag", "uplift_score"], ascending=[False, False]
    ).reset_index(drop=True)


ASSUMPTIONS = [
    ("Sumber skor uplift", "X-learner observational, campaign akhir held-out terbaru per member (data/processed/uplift_scores.parquet); skor bukan janji kausal - berlabel observational"),
    ("Uplift decile", "decile skor X dalam campaign terbaru member tersebut (1 = tertinggi); bukan decile lintas campaign"),
    ("Segment", "K-means 3 segmen efektif (fase segmentasi); nama segmen dari registri"),
    ("CLV decile", "kuintil-10 clv_52w (kalkulasi identik star schema); CLV = deskriptor berlabel - model kalah dari baseline naif"),
    ("Top whitespace", "kategori expected-spend tertinggi per member, mengecualikan kategori operator COUPON/MISC ITEMS; proxy dalam satu retailer"),
    ("Offer matrix", "aturan deterministik: segmen rentan-hilang > promo-dependent (benefit non-diskon) > top-2 decile (voucher whitespace) > pertahankan"),
    ("Voucher cap", "p90 biaya kupon terobservasi (semua kupon) per member treated pada campaign held-out, dibulatkan ke atas - guardrail data-anchored"),
    ("include_flag", "1 = top-2 uplift decile (aturan budget default playbook); 0 = tidak ditarget"),
    ("Margin (untuk ekonomi)", "parameter asumsi 15/25/35% - bukan data; incremental margin per $1 mengikuti tabel skenario ROI (batas ketat & konservatif)"),
    ("Holdout", "sebelum eksekusi: sisihkan 10% member acak sebagai holdout; bandingkan uplift aktual vs skor"),
    ("Ukuran", "seluruh member ter-skorkan (bukan sampel acak); angka decile/n memakai konvensi fase evaluasi"),
]


def write_xlsx() -> pd.DataFrame:
    """Build the list and write the two-sheet workbook (output + asumsi)."""
    out = build_targeting_list()
    OUTPUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="output", index=False)
        pd.DataFrame(ASSUMPTIONS, columns=["asumsi", "nilai / sumber"]).to_excel(
            writer, sheet_name="asumsi", index=False
        )
    return out


def main() -> None:
    out = write_xlsx()
    print(f"targeting list: {len(out):,} member | include_flag=1: {int(out['include_flag'].sum()):,} ({out['include_flag'].mean():.1%})")
    print(f"written: {OUTPUT_XLSX}")


if __name__ == "__main__":
    main()
