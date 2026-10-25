"""Static self-contained MVP dashboard (pages 1-3) built from processed parquets.

Format decision (decision log DL-016): the MVP dashboard ships as a single
HTML file with inline SVG charts so it can be committed, diffed and opened
offline; a .pbix cannot be produced or validated headless, so Power BI plus
the star schema stay planned for the full Phase 8. All numbers come from
``data/processed/*.parquet`` — the same artifacts the notebooks render — and
tests/test_dashboard.py pins them to the verified registry (AGENTS.md section 2).

Run from the repo root:  python -m src.dashboard  ->  outputs/dashboard.html
"""

from __future__ import annotations

import html
import io
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
PROCESSED = REPO / "data" / "processed"
OUTPUT_HTML = REPO / "outputs" / "dashboard.html"

Z95 = 1.959963984540054

# Segment names verified in AGENTS.md section 2.6 (id -> label).
SEGMENT_NAMES = {1: "Mesin pertumbuhan", 2: "Promo-dependent", 3: "Rentan hilang"}
SEGMENT_COLORS = {1: "#0f766e", 2: "#6d28d9", 3: "#d97706"}

# Operator category excluded from whitespace recommendations (AGENTS.md section 2.4).
OPERATOR_CATEGORY = "COUPON/MISC ITEMS"

BACKBONE_CAMPAIGNS = [8, 13, 18]
HEATMAP_TOP_CATEGORIES = 12

plt.rcParams.update(
    {
        "svg.fonttype": "none",
        "svg.hashsalt": "dashboard",
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)

FLAG_COLORS = {
    "layak": "#0f766e",
    "flagged": "#d97706",
    "excluded": "#9ca3af",
}


# --- formatting -----------------------------------------------------------------


def fmt_id(x, dec: int = 0) -> str:
    """Indonesian number format: dot thousands, comma decimals."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{float(x):,.{dec}f}"
    return s.replace(",", "\x01").replace(".", ",").replace("\x01", ".")


def fmt_usd(x, dec: int = 0) -> str:
    return f"${fmt_id(x, dec)}"


def fmt_pct(x, dec: int = 1) -> str:
    return f"{fmt_id(x, dec)}%"


def _r(x, dec: int = 2):
    """Round for the bundle, keeping NaN as None so the JSON stays clean."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), dec)


# --- data bundle ----------------------------------------------------------------


def pooled_meta(att, ci_low, ci_high) -> dict:
    """Inverse-variance fixed-effect + DerSimonian-Laird random-effects meta-analysis.

    Reproduces the verified pooled estimates over the 14 gate-passing campaigns
    (AGENTS.md section 2.5): FE $3.83 [2.89; 4.77], RE $4.87 [3.06; 6.68], I2 66%.
    """
    att = np.asarray(att, dtype=float)
    se = (np.asarray(ci_high, dtype=float) - np.asarray(ci_low, dtype=float)) / (2 * Z95)
    w = 1.0 / se**2
    fe = float((w * att).sum() / w.sum())
    se_fe = float(1.0 / math.sqrt(w.sum()))
    k = len(att)
    q = float((w * (att - fe) ** 2).sum())
    c = float(w.sum() - (w**2).sum() / w.sum())
    tau2 = max(0.0, (q - (k - 1)) / c) if c > 0 else 0.0
    wr = 1.0 / (se**2 + tau2)
    re = float((wr * att).sum() / wr.sum())
    se_re = float(1.0 / math.sqrt(wr.sum()))
    i2 = max(0.0, (q - (k - 1)) / q) * 100 if q > 0 else 0.0
    return {
        "k": k,
        "fe": fe,
        "fe_ci_low": fe - Z95 * se_fe,
        "fe_ci_high": fe + Z95 * se_fe,
        "re": re,
        "re_ci_low": re - Z95 * se_re,
        "re_ci_high": re + Z95 * se_re,
        "i2_pct": i2,
        "tau2": tau2,
    }


def _flag_color(flag: str | None) -> str:
    if not flag:
        return FLAG_COLORS["excluded"]
    if flag.startswith("layak"):
        return FLAG_COLORS["layak"]
    return FLAG_COLORS["flagged"]


def build_bundle(processed_dir: Path = PROCESSED) -> dict:
    """Assemble every number the dashboard shows, from processed parquets only."""
    hh_week = pd.read_parquet(processed_dir / "hh_week.parquet")
    hh_clv = pd.read_parquet(processed_dir / "hh_clv.parquet")
    seg_summary = pd.read_parquet(processed_dir / "segment_summary.parquet")
    whitespace = pd.read_parquet(processed_dir / "hh_whitespace.parquet")
    did = pd.read_parquet(processed_dir / "campaign_did_results.parquet")

    # --- page 1: member overview -------------------------------------------------
    weekly = hh_week.groupby("week_no", as_index=False).agg(
        active=("has_purchase", "sum"), spend=("net_spend", "sum")
    )
    spend_member = hh_clv["total_net_spend"]
    counts, edges = np.histogram(spend_member, bins=np.logspace(0, 4.1, 32))
    promo_active = hh_week.loc[hh_week["has_purchase"], "promo_share"].dropna()
    churn_flagged = float((seg_summary["n"] * seg_summary["churn_risk_pct"] / 100).sum())
    overview = {
        "kpis": {
            "n_members": int(hh_clv.shape[0]),
            "n_weeks": int(hh_week["week_no"].max()),
            "total_net_spend": float(spend_member.sum()),
            "median_total_spend": float(spend_member.median()),
            "median_weeks_active": float(hh_clv["frequency"].median()),
            "median_promo_share": float(promo_active.median()),
            "churn_flagged_n": churn_flagged,
            "churn_flagged_pct": churn_flagged / len(hh_clv) * 100,
        },
        "weekly": {
            "week": weekly["week_no"].tolist(),
            "active": weekly["active"].tolist(),
            "spend": [round(float(v), 0) for v in weekly["spend"]],
        },
        "spend_hist": {
            "bin_left": [round(float(v), 2) for v in edges[:-1]],
            "bin_right": [round(float(v), 2) for v in edges[1:]],
            "counts": [int(v) for v in counts],
        },
        "clv_percentiles": {
            "labels": ["p10", "p50", "p90", "p99"],
            "values": [
                _r(v, 0) for v in hh_clv["clv_52w"].quantile([0.10, 0.50, 0.90, 0.99])
            ],
        },
        "segment_mix": [
            {
                "segment": int(row.segment),
                "name": SEGMENT_NAMES[int(row.segment)],
                "n": int(row.n),
            }
            for row in seg_summary.itertuples()
        ],
    }

    # --- page 2: segment deep dive ------------------------------------------------
    segments_hh = pd.read_parquet(processed_dir / "segments.parquet")[["household_key", "segment"]]
    ws = whitespace.merge(segments_hh, on="household_key", how="left")
    ws = ws[ws["commodity_desc"] != OPERATOR_CATEGORY]
    top_cats = (
        ws.groupby("commodity_desc")["expected_spend"].sum().nlargest(HEATMAP_TOP_CATEGORIES)
    )
    heat = ws[ws["commodity_desc"].isin(top_cats.index)]
    heat_matrix = (
        heat.pivot_table(index="commodity_desc", columns="segment", values="expected_spend", aggfunc="mean")
        .reindex(top_cats.index)
    )
    seg_names_ordered = [SEGMENT_NAMES[int(s)] for s in sorted(heat_matrix.columns)]
    segments = {
        "table": [
            {
                "segment": int(row.segment),
                "name": SEGMENT_NAMES[int(row.segment)],
                "n": int(row.n),
                "share_pct": _r(row.share_pct, 1),
                "mean_total_spend": _r(row.mean_total_spend, 0),
                "mean_weekly_spend_active": _r(row.mean_weekly_spend_active, 1),
                "promo_dependence": _r(row.promo_dependence, 3),
                "churn_risk_pct": _r(row.churn_risk_pct, 1),
                "spend_dropping_pct": _r(row.spend_dropping_pct, 1),
                "whitespace_utama": str(row.whitespace_utama),
                "whitespace_per_member_usd": _r(row.whitespace_per_member_usd, 0),
                "satu_aksi": str(row.satu_aksi),
            }
            for row in seg_summary.itertuples()
        ],
        "heatmap": {
            "categories": list(heat_matrix.index),
            "segments": seg_names_ordered,
            "values": [[_r(v, 0) for v in row] for row in heat_matrix.values],
            "excluded": OPERATOR_CATEGORY,
        },
    }

    # --- page 3: campaign lift ----------------------------------------------------
    est = did[did["estimated"]].copy()
    layak = est[est["reliability_flag"].str.startswith("layak")]
    pooled = pooled_meta(layak["att"], layak["att_ci_low"], layak["att_ci_high"])

    campaigns_rows = []
    for row in did.sort_values("campaign_id").itertuples():
        campaigns_rows.append(
            {
                "campaign_id": int(row.campaign_id),
                "type": str(row.type),
                "start_week": int(row.start_week),
                "end_week": int(row.end_week),
                "n_treated": int(row.n_treated),
                "n_control": int(row.n_control),
                "att": _r(getattr(row, "att"), 2),
                "att_ci_low": _r(getattr(row, "att_ci_low"), 2),
                "att_ci_high": _r(getattr(row, "att_ci_high"), 2),
                "lift_pct": _r(getattr(row, "lift_pct"), 1),
                "lift_ci_low": _r(getattr(row, "lift_ci_low"), 1),
                "lift_ci_high": _r(getattr(row, "lift_ci_high"), 1),
                "n_redeemers": _r(getattr(row, "n_redeemers"), 0),
                "redemption_rate": _r(getattr(row, "redemption_rate"), 3),
                "inc_spend_per_dollar": _r(getattr(row, "inc_spend_per_dollar"), 2),
                "inc_spend_per_dollar_allcoupons": _r(
                    getattr(row, "inc_spend_per_dollar_allcoupons"), 2
                ),
                "significance": str(getattr(row, "significance")) if row.estimated else "—",
                "reliability_flag": str(row.reliability_flag),
                "reliability_reason": str(row.reliability_reason),
                "estimated": bool(row.estimated),
            }
        )
    campaigns = {
        "rows": campaigns_rows,
        "forest": [
            {
                "campaign_id": int(r.campaign_id),
                "type": str(r.type),
                "att": _r(r.att, 3),
                "ci_low": _r(r.att_ci_low, 3),
                "ci_high": _r(r.att_ci_high, 3),
                "flag": str(r.reliability_flag),
            }
            for r in est.sort_values("campaign_id").itertuples()
        ],
        "pooled": {key: _r(val, 3) for key, val in pooled.items()},
        "backbone": [
            {
                "campaign_id": int(r.campaign_id),
                "att": _r(r.att, 2),
                "att_ci_low": _r(r.att_ci_low, 2),
                "att_ci_high": _r(r.att_ci_high, 2),
                "lift_pct": _r(r.lift_pct, 1),
                "inc_per_dollar": _r(r.inc_spend_per_dollar, 2),
                "breakeven_margin_pct": _r(100.0 / r.inc_spend_per_dollar if r.inc_spend_per_dollar else float("nan"), 0),
                "margin15": _r(r.margin15_per_dollar, 2),
                "margin25": _r(r.margin25_per_dollar, 2),
                "margin35": _r(r.margin35_per_dollar, 2),
                "inc_per_dollar_allcoupons": _r(r.inc_spend_per_dollar_allcoupons, 2),
                "flag": str(r.reliability_flag),
            }
            for r in did[did["campaign_id"].isin(BACKBONE_CAMPAIGNS)]
            .sort_values("campaign_id")
            .itertuples()
        ],
        "n_estimated": int(len(est)),
        "n_layak": int(len(layak)),
    }

    return {"overview": overview, "segments": segments, "campaigns": campaigns}


# --- charts (inline SVG) ----------------------------------------------------------


def _svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", metadata={"Date": None})
    plt.close(fig)
    return buf.getvalue()


def _chart_weekly(bundle: dict) -> dict:
    wk = bundle["overview"]["weekly"]
    out = {}
    fig, ax = plt.subplots(figsize=(6.6, 2.3))
    ax.plot(wk["week"], wk["active"], color="#0f766e", lw=1.4)
    ax.set_title(f"Member aktif per minggu (n={len(wk['week'])} minggu, 2.500 member)")
    ax.set_xlabel("minggu ke-")
    ax.set_ylabel("member aktif")
    ax.set_ylim(0, max(wk["active"]) * 1.1)
    out["active"] = _svg(fig)

    fig, ax = plt.subplots(figsize=(6.6, 2.3))
    ax.plot(wk["week"], wk["spend"], color="#334155", lw=1.4)
    ax.set_title(f"Belanja net seluruh member per minggu (USD, n=2.500 member)")
    ax.set_xlabel("minggu ke-")
    ax.set_ylabel("USD / minggu")
    out["spend"] = _svg(fig)
    return out


def _chart_hist(bundle: dict) -> str:
    h = bundle["overview"]["spend_hist"]
    left, right, counts = np.array(h["bin_left"]), np.array(h["bin_right"]), np.array(h["counts"])
    fig, ax = plt.subplots(figsize=(4.4, 2.6))
    ax.bar(left, counts, width=right - left, align="edge", color="#0f766e", alpha=0.85)
    ax.set_xscale("log")
    ax.set_title("Distribusi total belanja net per member (skala log)")
    ax.set_xlabel("total belanja net 102 minggu (USD, sumbu log)")
    ax.set_ylabel("jumlah member")
    return _svg(fig)


def _chart_clv(bundle: dict) -> str:
    c = bundle["overview"]["clv_percentiles"]
    fig, ax = plt.subplots(figsize=(4.4, 2.6))
    bars = ax.bar(c["labels"], c["values"], color=["#bae6fd", "#7dd3fc", "#38bdf8", "#0284c7"])
    for b, v in zip(bars, c["values"]):
        ax.annotate(fmt_usd(v), (b.get_x() + b.get_width() / 2, v), ha="center", va="bottom", fontsize=8)
    ax.set_title("CLV 52 minggu (USD) — deskriptor berlabel")
    ax.set_ylabel("USD")
    ax.set_ylim(0, max(c["values"]) * 1.15)
    return _svg(fig)


def _chart_segment_bars(bundle: dict) -> dict:
    t = bundle["segments"]["table"]
    names = [r["name"] for r in t]
    colors = [SEGMENT_COLORS[r["segment"]] for r in t]
    out = {}

    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    ax.barh(names[::-1], [r["mean_total_spend"] for r in t][::-1], color=colors[::-1])
    ax.set_title("Belanja net per member (USD, 102 minggu)")
    ax.set_xlabel("USD / member")
    out["spend"] = _svg(fig)

    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    ax.barh(names[::-1], [r["promo_dependence"] for r in t][::-1], color=colors[::-1])
    ax.set_title("Ketergantungan promo (median promo_share)")
    ax.set_xlabel("proporsi belanja ber-promo")
    out["promo"] = _svg(fig)

    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    y = np.arange(len(t))[::-1]
    ax.barh(y + 0.2, [r["churn_risk_pct"] for r in t], height=0.38, color="#d97706", label="churn risk")
    ax.barh(y - 0.2, [r["spend_dropping_pct"] for r in t], height=0.38, color="#fbbf24", label="spend turun")
    ax.set_yticks(y, names)
    ax.set_title("Risiko churn & spend turun (%)")
    ax.set_xlabel("% member")
    ax.legend(fontsize=7, loc="lower right")
    out["churn"] = _svg(fig)
    return out


def _chart_heatmap(bundle: dict) -> str:
    hm = bundle["segments"]["heatmap"]
    values = np.array([[np.nan if v is None else v for v in row] for row in hm["values"]])
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    im = ax.imshow(values, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(hm["segments"])), hm["segments"])
    ax.set_yticks(range(len(hm["categories"])), hm["categories"], fontsize=8)
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            v = values[i, j]
            ax.text(j, i, fmt_usd(v) if v == v else "—", ha="center", va="center", fontsize=7)
    ax.set_title(
        f"Whitespace kategori per segmen — expected spend cohort per member (USD, "
        f"top {len(hm['categories'])} kategori, proxy dalam satu retailer)"
    )
    fig.colorbar(im, ax=ax, label="USD / member")
    return _svg(fig)


def _chart_forest(bundle: dict) -> str:
    fr = bundle["campaigns"]["forest"]
    pooled = bundle["campaigns"]["pooled"]
    n = len(fr)
    fig, ax = plt.subplots(figsize=(7.4, 0.34 * n + 1.5))
    y = np.arange(n)[::-1]
    labels = [f"{r['campaign_id']} · Type{r['type']}" for r in fr]
    for yi, r in zip(y, fr):
        color = _flag_color(r["flag"])
        ax.plot([r["ci_low"], r["ci_high"]], [yi, yi], color=color, lw=1.6)
        ax.plot(r["att"], yi, "o", color=color, ms=4.5)
    ax.axvline(0, color="#94a3b8", lw=0.9, ls="-")
    ax.axvline(pooled["fe"], color="#0f766e", lw=1.2, ls="--", label=f"pooled FE ${fmt_id(pooled['fe'], 2)}")
    ax.axvline(pooled["re"], color="#0369a1", lw=1.2, ls=":", label=f"pooled RE ${fmt_id(pooled['re'], 2)}")
    ax.set_yticks(y, labels, fontsize=8)
    ax.set_xlabel("ATT belanja net per minggu (USD, 95% CI)")
    ax.set_title(
        f"Efek campaign per minggu — {bundle['campaigns']['n_estimated']} campaign terestimasi, "
        f"{bundle['campaigns']['n_layak']} lolos semua gate (observasional)"
    )
    ax.legend(fontsize=8, loc="lower right")
    return _svg(fig)


# --- HTML ------------------------------------------------------------------------


def _table(headers: list[str], rows: list[list[str]], align: str = "") -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="tbl {align}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _kpis(cards: list[tuple[str, str, str]]) -> str:
    items = "".join(
        f'<div class="card"><div class="kpi-label">{html.escape(l)}</div>'
        f'<div class="kpi-value">{v}</div><div class="kpi-sub">{html.escape(s)}</div></div>'
        for l, v, s in cards
    )
    return f'<div class="cards">{items}</div>'


def _note(text: str) -> str:
    return f'<p class="note">{text}</p>'


def render_html(bundle: dict) -> str:
    ov, sg, ca = bundle["overview"], bundle["segments"], bundle["campaigns"]
    k = ov["kpis"]

    weekly_svgs = _chart_weekly(bundle)
    seg_svgs = _chart_segment_bars(bundle)

    # --- page 1 ---
    p1_cards = _kpis(
        [
            ("Member", fmt_id(k["n_members"]), "panel Dunnhumby, 102 minggu"),
            ("Total belanja net", fmt_usd(k["total_net_spend"]), "USD, retur masuk agregasi"),
            ("Median belanja/member", fmt_usd(k["median_total_spend"]), "102 minggu, USD"),
            ("Median minggu aktif", fmt_id(k["median_weeks_active"], 0), f" dari {k['n_weeks']} minggu"),
            ("Median promo_share", fmt_id(k["median_promo_share"], 2), "minggu-member dengan belanja"),
            ("Churn risk (gap > p95)", f"{fmt_id(k['churn_flagged_n'], 0)} ({fmt_pct(k['churn_flagged_pct'])})",
             "ambang 5 minggu dari distribusi data"),
        ]
    )
    seg_mix_rows = [[r["name"], fmt_id(r["n"]), fmt_pct(r["n"] / k["n_members"] * 100)] for r in ov["segment_mix"]]
    page1 = f"""
<h2>Member Overview</h2>
{p1_cards}
<div class="grid2">{_wrap_svg(weekly_svgs["active"])}{_wrap_svg(weekly_svgs["spend"])}</div>
<div class="grid2">
  <div>{_wrap_svg(_chart_hist(bundle))}{_note("Skala log; ekor kanan = member belanja besar (top-1% dikeluarkan dari fitting segmentasi, tetap dilaporkan di sini.")}</div>
  <div>{_wrap_svg(_chart_clv(bundle))}
  {_note("CLV 52 minggu dari BG/NBD + Gamma-Gamma — <b>deskriptor berlabel</b>: model kalah dari baseline rata-rata historis pada holdout 26 minggu (MAE 322 vs 308), jadi keputusan targeting tetap di atas RFM/historis; asumsi independensi frequency–monetary dilanggar (Spearman 0,43).")}</div>
</div>
<h3>Komposisi segmen</h3>
{_table(["Segmen", "n member", "share"], seg_mix_rows)}
{_note("Detail per segmen ada di halaman Segment Deep Dive.")}
"""

    # --- page 2 ---
    seg_rows = [
        [
            f'<span class="dot" style="background:{SEGMENT_COLORS[r["segment"]]}"></span>{html.escape(r["name"])}',
            fmt_id(r["n"]),
            fmt_pct(r["share_pct"]),
            fmt_usd(r["mean_total_spend"]),
            fmt_usd(r["mean_weekly_spend_active"], 1),
            fmt_id(r["promo_dependence"], 3),
            fmt_pct(r["churn_risk_pct"]),
            fmt_pct(r["spend_dropping_pct"]),
            html.escape(r["whitespace_utama"]) + f" ({fmt_usd(r['whitespace_per_member_usd'])}/member)",
            html.escape(r["satu_aksi"]),
        ]
        for r in sg["table"]
    ]
    page2 = f"""
<h2>Segment Deep Dive</h2>
{_note("Segmen dari K-means (k=5 core-fit, konsolidasi klaster &lt;30) atas RFM log + ketergantungan promo + bauran 44 department; stabilitas ARI lintas seed 0,646 — struktur lembut (silhouette rendah), bukan klaster tajam. Aksi = <b>kandidat uji</b>, bukan klaim kausal; churn risk memakai ambang gap &gt; p95 distribusi inter-purchase (5 minggu) dari data, bukan angka bulat.")}
{_table(
    ["Segmen", "n", "share", "belanja/member", "USD/mgg aktif", "promo", "churn", "turun", "whitespace utama", "satu aksi"],
    seg_rows,
)}
<div class="grid3">{_wrap_svg(seg_svgs["spend"])}{_wrap_svg(seg_svgs["promo"])}{_wrap_svg(seg_svgs["churn"])}</div>
<h3>Heatmap whitespace kategori</h3>
{_wrap_svg(_chart_heatmap(bundle))}
{_note(f"Expected spend cohort per member: potensi belanja bila share member menyamai median cohort semirip (tercile spend × tercile ragam) — <b>proxy dalam satu retailer</b>, bukan total dompet lintas retailer. Kategori operator {html.escape(sg['heatmap']['excluded'])} dikecualikan dari visualisasi ini.")}
"""

    # --- page 3 ---
    pooled = ca["pooled"]
    p3_cards = _kpis(
        [
            ("Pooled FE", f"${fmt_id(pooled['fe'], 2)}", f"95% CI [{fmt_id(pooled['fe_ci_low'], 2)}; {fmt_id(pooled['fe_ci_high'], 2)}] · k={pooled['k']}"),
            ("Pooled RE", f"${fmt_id(pooled['re'], 2)}", f"95% CI [{fmt_id(pooled['re_ci_low'], 2)}; {fmt_id(pooled['re_ci_high'], 2)}] · DerSimonian-Laird"),
            ("Heterogenitas", f"I² {fmt_id(pooled['i2_pct'], 0)}%", "efek bervariasi antar campaign"),
            ("Campaign terestimasi", f"{ca['n_estimated']} / 30", f"{ca['n_layak']} lolos semua gate reliabilitas"),
        ]
    )
    bb_rows = [
        [
            str(r["campaign_id"]),
            fmt_id(r["att"], 2) + f" [{fmt_id(r['att_ci_low'], 2)}; {fmt_id(r['att_ci_high'], 2)}]",
            fmt_pct(r["lift_pct"]),
            f"${fmt_id(r['inc_per_dollar'], 2)}",
            fmt_pct(r["breakeven_margin_pct"], 0),
            f"${fmt_id(r['margin15'], 2)} / ${fmt_id(r['margin25'], 2)} / ${fmt_id(r['margin35'], 2)}",
            f"${fmt_id(r['inc_per_dollar_allcoupons'], 2)}",
            ("lolos semua gate" if r["flag"].startswith("layak") else '<span class="warn">flagged — gagal placebo jauh</span>'),
        ]
        for r in ca["backbone"]
    ]
    camp_rows = []
    for r in ca["rows"]:
        if r["estimated"]:
            camp_rows.append(
                [
                    f"<b>{r['campaign_id']}</b>",
                    r["type"],
                    f"{r['start_week']}–{r['end_week']}",
                    fmt_id(r["n_treated"]),
                    fmt_id(r["n_control"]),
                    fmt_id(r["att"], 2) + f" [{fmt_id(r['att_ci_low'], 2)}; {fmt_id(r['att_ci_high'], 2)}]",
                    fmt_pct(r["lift_pct"], 1),
                    fmt_id(r["n_redeemers"], 0) + f" ({fmt_pct((r['redemption_rate'] or 0) * 100, 0)})",
                    f"${fmt_id(r['inc_spend_per_dollar'], 2)}",
                    html.escape(r["significance"]),
                    _flag_cell(r),
                ]
            )
        else:
            camp_rows.append(
                [
                    f"<b>{r['campaign_id']}</b>",
                    r["type"],
                    f"{r['start_week']}–{r['end_week']}",
                    fmt_id(r["n_treated"]),
                    fmt_id(r["n_control"]),
                    "—", "—", "—", "—", "—",
                    _flag_cell(r),
                ]
            )
    page3 = f"""
<h2>Campaign Lift</h2>
{_note("<b>Semua efek bersifat observational — di bawah asumsi unconfoundedness</b> (targeting retailer tidak acak; koreksi propensity + overlap weights + dua placebo mengurangi bias, tidak menghapus). ATT = selisih perubahan belanja net mingguan treated vs control (overlap weights, fitur trajektori + dip pra-campaign; seleksi win-back dikondisikan). Estimasi spesifikasi-sensitif (±30% tanpa pengondisian) — baca sebagai rentang.")}
{p3_cards}
{_wrap_svg(_chart_forest(bundle))}
<h3>Ekonomi voucher — backbone TypeA (margin = parameter asumsi, bukan data)</h3>
{_table(
    ["Campaign", "ATT $/mgg [95% CI]", "lift", "incremental spend / $1 (atribusi ketat)", "break-even margin", "incremental margin / $1 (15/25/35%)", "per $1 (batas konservatif)", "status"],
    bb_rows,
)}
{_note("Atribusi ketat = hanya kupon produk dalam daftar campaign; batas konservatif = semua kupon yang ter-redempt selama window. Margin 15/25/35% adalah parameter asumsi; break-even = margin minimum agar incremental margin ≥ $0. Atribusi ketat mendekati impas pada margin grocery tinggi; batas konservatif negatif semua.")}
<h3>Semua 30 campaign (flag reliabilitas + alasan)</h3>
{_table(
    ["ID", "tipe", "minggu", "n treated", "n control", "ATT $/mgg [95% CI]", "lift", "redempt", "per $1 ketat", "signifikansi", "status & alasan"],
    camp_rows,
)}
{_note("Campaign tanpa estimasi: n treated &lt; 100 (laporkan agregat), overlap parah (15 — excluded), atau window terpotong akhir data (24). Signifikansi = BH q&lt;0,05 atas 20 campaign terestimasi. n &lt; 30 per sel tidak dilaporkan.")}
"""

    body_pages = [("overview", "Member Overview", page1), ("segments", "Segment Deep Dive", page2), ("campaigns", "Campaign Lift", page3)]
    nav = "".join(
        f'<button class="tab{" active" if i == 0 else ""}" data-target="{pid}">{title}</button>'
        for i, (pid, title, _) in enumerate(body_pages)
    )
    sections = "".join(
        f'<section id="{pid}" class="page{" visible" if i == 0 else ""}">{content}</section>'
        for i, (pid, _, content) in enumerate(body_pages)
    )
    # plain token replacement: the shell embeds CSS/JS whose braces must not be
    # interpreted as format placeholders
    return (
        _HTML_SHELL.replace("{css}", _CSS)
        .replace("{js}", _JS)
        .replace("{nav}", nav)
        .replace("{sections}", sections)
    )


def _flag_cell(r: dict) -> str:
    flag, reason = r["reliability_flag"], r["reliability_reason"]
    color = _flag_color(flag)
    return (
        f'<span class="flag" style="color:{color}">{html.escape(flag)}</span>'
        f'<span class="reason">{html.escape(reason)}</span>'
    )


def _wrap_svg(svg: str) -> str:
    return f'<div class="chart">{svg}</div>'


_CSS = """
:root{--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;--bg:#f8fafc}
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;color:var(--ink);background:var(--bg)}
header{padding:20px 28px 12px;background:#fff;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:20px}
.sub{color:var(--mut);font-size:12.5px;margin:6px 0 14px;max-width:980px;line-height:1.5}
nav{display:flex;gap:8px}
.tab{border:1px solid var(--line);background:#fff;border-radius:8px 8px 0 0;padding:8px 16px;font-size:13px;cursor:pointer;color:var(--mut)}
.tab.active{color:var(--ink);font-weight:600;border-bottom:2px solid #0f766e}
.page{display:none;padding:18px 28px 40px;max-width:1180px}
.page.visible{display:block}
h2{font-size:17px;margin:8px 0 4px}
h3{font-size:13.5px;margin:22px 0 8px;color:#334155}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.kpi-label{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.kpi-value{font-size:20px;font-weight:700;margin:2px 0}
.kpi-sub{font-size:11px;color:var(--mut)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:12px 0}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0}
.chart{background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px}
.chart svg{width:100%;height:auto;display:block}
.note{font-size:12px;color:var(--mut);line-height:1.55;margin:8px 2px}
.tbl{border-collapse:collapse;width:100%;font-size:12px;background:#fff;border:1px solid var(--line);border-radius:10px}
.tbl th,.tbl td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.tbl th{background:#f1f5f9;font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#334155}
.tbl tr:last-child td{border-bottom:none}
.flag{display:inline-block;font-weight:600;white-space:nowrap}
.reason{display:block;color:var(--mut);font-size:10.5px;max-width:260px}
.warn{color:#b45309;font-weight:600}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
footer{padding:14px 28px 30px;color:var(--mut);font-size:11.5px;max-width:1180px;line-height:1.6}
"""

_JS = """
var tabs=document.querySelectorAll('.tab'),pages=document.querySelectorAll('.page');
tabs.forEach(function(t){t.addEventListener('click',function(){
  tabs.forEach(function(x){x.classList.remove('active')});
  pages.forEach(function(p){p.classList.remove('visible')});
  t.classList.add('active');
  document.getElementById(t.dataset.target).classList.add('visible');
  window.scrollTo({top:0});
});});
"""

_HTML_SHELL = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Retail Voucher Incrementality — Dashboard MVP</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>Retail Voucher Incrementality — Dashboard MVP</h1>
  <p class="sub">Panel Dunnhumby Complete Journey (2.500 member, 102 minggu, USD net). Efek campaign bersifat <b>observational — di bawah asumsi unconfoundedness</b>; whitespace kategori adalah <b>proxy dalam satu retailer</b>; margin adalah parameter asumsi; horizon nilai member selalu <b>CLV 52 minggu</b>. Angka dibangun dari parquet fase analisis dan dikunci suite test.</p>
  <nav>{nav}</nav>
</header>
{sections}
<footer>Sumber: data/processed/*.parquet (hh_week, hh_clv, segments, segment_summary, hh_whitespace, campaign_did_results) — dibangun oleh <code>src/dashboard.py</code>; angka terkunci <code>tests/test_dashboard.py</code>. Estimasi menyertakan n dan 95% CI; sel dengan n &lt; 30 tidak dilaporkan; reliability_flag ditampilkan beserta alasannya, tidak disembunyikan.</footer>
<script>{js}</script>
</body>
</html>
"""


def build() -> str:
    """Build the bundle and render the full HTML document (deterministic)."""
    return render_html(build_bundle())


def main() -> None:
    doc = build()
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(doc, encoding="utf-8")
    print(f"dashboard written: {OUTPUT_HTML} ({OUTPUT_HTML.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
