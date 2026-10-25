# MODEL_MANIFEST — Power BI build guide (Phase 8, DL-020)

Panduan membangun `retail-voucher.pbix` dari star schema yang dibangun agent.
Semua angka di CSV berasal dari parquet fase analisis yang sama dengan
notebook dan dashboard HTML — angka dijamin identik; tugas Anda murni
perakitan visual. Estimasi usaha: ±2–4 jam pertama kali.

- Sumber data: `data/processed/star/*.csv` (8 file; dibangun ulang dengan `python -m src.starschema`)
- Referensi visual: [`outputs/dashboard.html`](../outputs/dashboard.html) (buka di browser; 4 halaman dengan angka identik)
- Label wajib di semua halaman: **"observational — di bawah asumsi unconfoundedness"** (efek campaign/uplift), **"proxy dalam satu retailer"** (whitespace), **margin = parameter asumsi**. Frasa dompet-lintas-ritel yang dilarang (lihat aturan R2 di AGENTS.md) tidak boleh muncul di teks visual mana pun.

## 1. Impor

Get Data → **Text/CSV**, satu per satu (urutan bebas; jangan gabungkan file):

| File | Baris | Kolom kunci | Catatan tipe |
|---|---|---|---|
| `dim_household.csv` | 2.500 | `household_key` (int, PK) | `segment` 1–3; `clv_decile` 1–10 |
| `dim_campaign.csv` | 30 | `campaign_id` (int, PK) | `estimated` TRUE/FALSE; `att*`/`lift_pct` kosong untuk campaign tak terestimasi — biarkan blank |
| `dim_category.csv` | 308 | `commodity_id` (int, PK) | grain komoditas; `department` sebagai atribut; `is_operator_category=1` → jangan direkomendasikan |
| `dim_week.csv` | 102 | `week_no` (int, PK) | |
| `fact_hh_week.csv` | 255.000 | `household_key`, `week_no` | |
| `fact_hh_campaign.csv` | 14.090 | `household_key`, `campaign_id` | hanya 8 campaign akhir held-out (populasi evaluasi uplift); `uplift_decile` 1=teratas per campaign |
| `fact_hh_category.csv` | 288.690 | `household_key`, `commodity_id` | |
| `scenario_roi.csv` | 10 | `scenario` + `campaign_set` | tabel mandiri (tanpa relasi) untuk halaman 4 |

Centang **"Use first row as headers"**; Power BI biasanya mendeteksi tipe dengan benar — pastikan `household_key`/`campaign_id`/`week_no`/`commodity_id` = Whole Number, `net_spend`/`delta`/`score_*`/`att*` = Decimal, `estimated`/`has_purchase` = True/False.

## 2. Model relasi

Manage relationships (semua **Many-to-One, single direction**, aktifkan "Assume referential integrity" — sudah diverifikasi 100% oleh test):

| Dari (many) | Ke (one) |
|---|---|
| `fact_hh_week[household_key]` | `dim_household[household_key]` |
| `fact_hh_week[week_no]` | `dim_week[week_no]` |
| `fact_hh_campaign[household_key]` | `dim_household[household_key]` |
| `fact_hh_campaign[campaign_id]` | `dim_campaign[campaign_id]` |
| `fact_hh_category[household_key]` | `dim_household[household_key]` |
| `fact_hh_category[commodity_id]` | `dim_category[commodity_id]` |

`scenario_roi` sengaja tanpa relasi (tabel ringkasan).

## 3. Measures DAX (salin-tempel ke tabel terkait)

```dax
-- dim_household
Total Member = DISTINCTCOUNT(fact_hh_week[household_key])
Total Net Spend (USD) = SUM(fact_hh_week[net_spend])
Avg Promo Share = AVERAGE(fact_hh_week[promo_share])
Active Weeks per Member = AVERAGEX(VALUES(fact_hh_week[household_key]), CALCULATE(SUM(fact_hh_week[has_purchase])))

-- fact_hh_campaign: uplift Δ observasional (bobot overlap), unit USD/minggu
Uplift Δ (USD/mgg) =
VAR wt = SUMX(FILTER(fact_hh_campaign, fact_hh_campaign[treated] = 1), fact_hh_campaign[att_weight])
VAR wc = SUMX(FILTER(fact_hh_campaign, fact_hh_campaign[treated] = 0), fact_hh_campaign[att_weight])
VAR yt = SUMX(FILTER(fact_hh_campaign, fact_hh_campaign[treated] = 1), fact_hh_campaign[delta] * fact_hh_campaign[att_weight])
VAR yc = SUMX(FILTER(fact_hh_campaign, fact_hh_campaign[treated] = 0), fact_hh_campaign[delta] * fact_hh_campaign[att_weight])
RETURN DIVIDE(yt, wt) - DIVIDE(yc, wc)
```

Kolom siap-pakai (tanpa measure): `dim_campaign[att]`, `[att_ci_low]`, `[att_ci_high]`, `[lift_pct]`, `[inc_spend_per_dollar]` (batas ketat, konvensi mingguan DiD — kalikan `n_weeks_window`? kolom sudah ada; untuk konvensi window lihat `scenario_roi`), `[reliability_flag]`, `[reliability_reason]`.

## 4. Layout 4 halaman (replikasi `outputs/dashboard.html`)

**Hal. 1 Member Overview** — KPI cards (Total Member 2.500; Total Net Spend $6,61M; median via card manual); line chart *member aktif per minggu* (`fact_hh_week[has_purchase]` sum by `dim_week[week_no]`); histogram belanja per member (import via `dim_household[total_net_spend]`, bin log); bar CLV 52 minggu per decile (`clv_decile`, sum `clv_52w` — label **deskriptor berlabel: kalah dari baseline naif**); komposisi segmen.

**Hal. 2 Segment Deep Dive** — tabel segmen (ukuran, spend/member, promo dependence `dim_household` avg by segment, churn — kolom churn ada di `segment_summary`? tidak di star: gunakan spend/RFM dari `dim_household` + whitespace dari `fact_hh_category`); heatmap `fact_hh_category[net_spend]` by `department` × `segment` — label **proxy dalam satu retailer**; bar chart per segmen.

**Hal. 3 Campaign Lift** — tabel `dim_campaign` (30 baris): `campaign_id, type, minggu, n_treated, n_control_pool, att, att_ci_low/high, lift_pct, inc_spend_per_dollar, significance, reliability_flag, reliability_reason` — **flag + alasan sebagai kolom terlihat, bukan tooltip**; bar-with-error-bar `att` (custom error bar dari `att_ci_low/high`); filter `estimated = TRUE`; catatan pooled FE $3,83 [2,89; 4,77] via card.

**Hal. 4 Voucher Efficiency** — tabel `scenario_roi` (`campaign_set = "all"`): bar `inc_per_dollar_tight` dan `inc_per_dollar_all` per `scenario`; what-if: buat **parameter** Modeling → New parameter: `MarginParam` (5–40%, step 1, default 25) dan slicer `uplift_decile` (1–10, top-k = pilih decile 1..k dari `fact_hh_campaign`); card `Margin per $1 = 0.01 * MarginParam[MarginParam Value] * AVERAGE(scenario_roi[inc_per_dollar_all]) - 1` (ganti rata-rata dengan measure LOOKUPVALUE per skenario terpilih bila ingin presisi); label **margin = parameter asumsi, bukan data**; catatan dua batas + horizon window.

## 5. Checklist QA (gate Phase 8)

- [ ] `reliability_flag` + `reliability_reason` terlihat di hal. 3 (bukan tooltip)
- [ ] Semua sumbu bersatuan; judul menyebut filter (campaign, window, n); tanpa dual-axis
- [ ] Estimasi tampil dengan CI; angka n < 30 tidak ditampilkan sebagai sel
- [ ] Label observational / proxy / parameter asumsi muncul di hal. 2–4
- [ ] Angka spot-check vs `outputs/dashboard.html`: total spend $6.608.941; ATT campaign 8 = $2,67 [0,69; 4,51]; per-$1 top-2 (ketat) = $232
- [ ] Simpan sebagai `powerbi/retail-voucher.pbix` (commit; ukuran ±5–15 MB aman)

## 6. Refresh

Data berubah hanya lewat re-run pipeline: `python -m src.starschema` → di Power BI: **Transform data → Refresh all**. Skema kolom stabil (test menjaga); bila kolom berubah, suite test gagal lebih dulu — jangan sinkron manual.
