# Dari RFM ke Voucher Efficiency (Retail Analytics)

**Hook:** *"RFM bilang siapa yang belanja banyak. Uplift bilang siapa yang berubah karena voucher. Dan saya tunjukkan kapan angka uplift itu layak dipercaya."*

**Posisi:** methodology transfer dari panel retail AS (Dunnhumby) ke use case member loyalty ala My Super Indo. Bukan klaim tentang perilaku pelanggan Super Indo.

## Catatan desain (hasil review ide awal)

Empat lubang di ide awal dan cara menutupnya:

1. **Treatment Dunnhumby tidak randomized.** Household yang dapat campaign dipilih retailer, jadi uplift di sini hanya valid di bawah asumsi unconfoundedness. Solusi: desain dua tahap (validasi di data randomized, lalu terapkan ke Dunnhumby sebagai observational dengan propensity, overlap check, dan placebo test).
2. **Share of wallet tidak bisa dihitung beneran.** Data hanya satu retailer. Ganti jadi *category penetration gap* dan labeli sebagai proxy.
3. **Incremental margin tidak ada datanya.** Pakai asumsi margin per kategori yang eksplisit, plus sensitivity 15/25/35%. Biaya voucher tersedia dari `COUPON_DISC`.
4. **BG/NBD di grocery canggung.** Belanja grocery hampir periodik. Tampilkan diagnostic (kalibrasi vs holdout, korelasi frequency-monetary, baseline naif), jangan hanya hasil akhir.

## 1. Pertanyaan bisnis

1. Siapa member bernilai tinggi, dan siapa yang mulai turun?
2. Seberapa promo-dependent tiap segmen?
3. Campaign mana yang beneran menaikkan spend, dan berapa incremental margin per $1 voucher?
4. Household mana yang paling responsif, dan berapa efisiensi budget kalau voucher hanya ke top decile?
5. Kategori mana yang jadi whitespace per segmen?

**Non-goal:** klaim kausal final, prediksi churn production-grade, rekomendasi per SKU.

## 2. Data

**Utama:** Dunnhumby Complete Journey (±2.500 household, 102 minggu).

| Tabel | Dipakai untuk |
|---|---|
| `transaction_data` | Panel household-week, spend, frequency, `COUPON_DISC`, `RETAIL_DISC` |
| `product` | Hierarki kategori (`DEPARTMENT`, `COMMODITY_DESC`) |
| `campaign_table` + `campaign_desc` | Treatment (household dikirimi campaign X), tanggal, tipe A/B/C |
| `coupon_redempt` + `coupon` | Redemption (outcome, bukan treatment) |
| `hh_demographic` | Hanya ±800 household yang punya, pakai untuk profil segmen, bukan fitur wajib |
| `causal_data` | Display/mailer per produk-minggu, opsional |

**Stage 1 (validasi metode, data randomized):** X5 RetailHero (ada histori pembelian) atau Hillstrom email sebagai fallback. Cek dulu akses dan ukuran data. Library `scikit-uplift` punya loader untuk keduanya.

**Stack:** Polars/DuckDB untuk panel, `lifetimes` atau `pymc-marketing` untuk CLV, `scikit-uplift` + `causalml`/`econml` untuk uplift, scikit-learn untuk K-means, Power BI untuk dashboard.

## 3. Pipeline analisis

### Phase 0-1: Panel dan fitur
- Grain utama: `household_week`. Grain sekunder: `household_campaign` dan `household_category`.
- Metrik per household-week: spend, jumlah basket, category breadth (jumlah commodity unik), recency, `promo_share = (COUPON_DISC + RETAIL_DISC) / gross_sales`.
- Cek timeline `campaign_desc` dulu. Campaign tidak mulai dari minggu 1, jadi ini menentukan pre-window.
- Aturan wajib: semua fitur dihitung dari window pre-treatment, tiap campaign punya cutoff sendiri.

### Phase 2: Nilai member (RFM + CLV)
- RFM kuintil sebagai baseline deskriptif.
- BG/NBD + Gamma-Gamma pada granularity mingguan.
- Diagnostic yang harus ditampilkan: korelasi frequency vs monetary (asumsi Gamma-Gamma), kalibrasi vs holdout (misal 26 minggu terakhir), dan perbandingan dengan baseline naif (rata-rata historis).
- Kalau BG/NBD kalah dari baseline, tulis apa adanya. Itu poin plus, bukan kelemahan.
- Horizon CLV pendek (data 2 tahun), jadi label "CLV 52 minggu", bukan lifetime.

### Phase 3: Category penetration gap (pengganti "share of wallet")
- Definisi: `share_hh(cat) = spend_hh(cat) / spend_hh(total)`, dibandingkan dengan median cohort.
- Cohort = household dengan spend tier dan category breadth mirip (bisa pakai cluster dari Phase 5).
- Whitespace = kategori dengan penetrasi cohort tinggi tapi household ini nol atau jauh di bawah median, diurutkan dengan expected spend cohort.
- Label jelas di notebook dan dashboard: ini proxy dalam satu retailer, bukan share of wallet total.

### Phase 4: Campaign effect (observational, tanpa model ML dulu)
- Unit: per campaign. Treated = ada di `campaign_table` untuk campaign itu. Control = tidak ditarget campaign itu, dan tidak ditarget campaign lain yang overlap window-nya.
- Estimasi: difference-in-differences setelah matching atau IPW pada fitur pre. Outcome: spend mingguan, pre 8 minggu vs window campaign.
- Wajib ada: plot event-study untuk cek parallel pre-trend, overlap propensity, tabel covariate balance (SMD sebelum dan sesudah).
- Output per campaign: lift %, CI, redemption rate, voucher cost, incremental margin per $1 voucher.
- Campaign yang pre-trend-nya jelek atau overlap-nya tipis ditandai "tidak reliable", jangan dibuang diam-diam.

### Phase 5: Segmentasi
- K-means pada RFM (log-transform, standardized) + vektor category share + `promo_share`.
- Pilih k dengan silhouette dan interpretability. Uji stabilitas: fit di periode 1, assign di periode 2, hitung ARI.
- Tiap segmen punya: ukuran, spend, promo dependence, churn risk, whitespace utama, dan satu aksi.
- Definisi churn-risk: gap sejak transaksi terakhir melebihi persentil ke-95 distribusi inter-purchase gap, atau spend turun tajam vs baseline. Threshold dari data, bukan asal.

### Phase 6: Uplift (dua tahap)

**Stage 1 (randomized):** T-learner dan X-learner di X5/Hillstrom. Split biasa valid di sini. Output: Qini/uplift curve, uplift per decile, AUUC. Tujuannya membuktikan pipeline bekerja saat asumsinya terpenuhi.

**Stage 2 (Dunnhumby, observational):**
- Unit: `household x campaign`. Treatment: dikirimi campaign. Outcome: spend di window campaign (kontinu), jadi pakai uplift curve incremental spend, bukan Qini biner.
- Fitur: hanya pre-window (RFM, breadth, promo_share, tenure, jumlah campaign sebelumnya, redemption rate sebelumnya).
- Karena household muncul di banyak campaign: split by campaign time (train di campaign awal, test di campaign akhir) dan `GroupKFold` by household. Jangan random split.
- Koreksi: propensity-weighted evaluasi, plus placebo test (treatment palsu di periode pre, uplift harus ~0).
- Reporting: "uplift di bawah asumsi unconfoundedness", disertai bootstrap CI per decile.

### Phase 7: Simulasi ROI
- Skenario: blanket, top-2 decile, top-4 decile (pada campaign held-out).
- Incremental margin = `margin_assumption x incremental_spend - voucher_cost`. `voucher_cost` dari `COUPON_DISC` observed.
- Sensitivity margin 15/25/35%, bootstrap CI di tiap skenario.
- Output utama: incremental margin per $1 voucher per skenario, dan titik break-even.
- Rasio ini unitless, jadi di slide transfer cukup dilabel ulang ke Rp.

## 4. Deliverable (urutan prioritas)

### 1. Notebook (inti)
Satu repo, notebook bernomor per phase, logic di `src/`.

```
retail-promo-effectiveness/
  data/            # raw (gitignored), processed parquet
  notebooks/       # 01_panel, 02_clv, 03_penetration_gap, 04_campaign_did,
                   # 05_segments, 06_uplift_randomized, 07_uplift_observational, 08_roi_sim
  src/             # features.py, cohorts.py, did.py, uplift_eval.py, simulate.py
  powerbi/         # .pbix + export script
  outputs/         # targeting_sample.xlsx, playbook.md, reuse_slide
  README.md        # business framing, assumptions, limitations di atas fold
```

### 2. Power BI (4 halaman, fokus campaign dan voucher)
- **Member Overview:** active members, spend/household, retention, jumlah churn-risk, segment mix.
- **Segment Deep Dive:** profil segmen, promo dependence, heatmap whitespace kategori.
- **Campaign Lift:** treated vs control per campaign, lift % dengan CI, redemption rate, flag reliability.
- **Voucher Efficiency:** what-if parameter (margin, top-k %), blanket vs targeted, incremental margin per $1.

Data model star schema: `dim_household`, `dim_campaign`, `dim_category`, `dim_week`, `fact_hh_week`, `fact_hh_campaign`, `fact_hh_category`. Hasil model dari Python diekspor ke parquet/CSV, DAX cukup untuk agregasi dan what-if.

### 3. Playbook 1 halaman + slide "re-run dengan data My Super Indo"

Playbook berisi: aturan targeting (uplift decile x segmen), offer matrix per segmen, guardrail budget (cap voucher per household, stop rule bila incremental margin per $1 < 1), desain holdout 10% member, dan cadence evaluasi.

Slide re-run berisi mapping data:

| Dunnhumby | Kebutuhan di My Super Indo |
|---|---|
| `household_key` | member_id dari scan kartu |
| `transaction_data` | transaksi POS terikat member |
| `COUPON_DISC` | nilai diskon voucher/promo per basket |
| `campaign_table` | send log campaign (siapa, kapan, offer apa) |
| `coupon_redempt` | log redemption voucher |
| `product` | master produk dengan hierarki kategori |
| (tidak ada) | margin/cost per kategori atau SKU |
| (tidak ada) | holdout flag acak untuk campaign berikutnya |
| (tidak ada) | transaksi non-member, untuk cek coverage member |

### 4. Excel targeting list (sample saja)
Satu sheet output dari notebook, satu sheet asumsi. Kolom: `household_key`, `segment`, `clv_decile`, `uplift_score`, `uplift_decile`, `promo_dependence`, `top_whitespace_category`, `recommended_offer`, `voucher_cap`, `include_flag`.

## 5. Milestone dan cut line

| Phase | Isi | Definition of done |
|---|---|---|
| 0-1 | EDA + panel + fitur | Panel parquet, timeline campaign terpetakan, data quality notes |
| 2-3 | CLV + penetration gap | Diagnostic kalibrasi, tabel whitespace per cohort |
| 4 | Campaign DiD | Lift per campaign + CI + flag reliability |
| 5 | Segmentasi | Segmen stabil (ARI) + tabel aksi |
| 6 | Uplift 2 tahap | Qini Stage 1, uplift curve Stage 2, placebo test lulus |
| 7 | ROI sim | Tabel skenario + sensitivity + CI |
| 8 | Power BI, playbook, slide, Excel | Dashboard 4 halaman, README final |

**Cut line MVP:** Phase 0-5 + dashboard halaman 1-3 + README. Ini sudah layak untuk portfolio retail analytics. Phase 6-7 (uplift dan ROI) adalah lapisan yang membedakan dari portfolio RFM biasa, jadi kerjakan setelah MVP stabil. Kalau waktu mepet, Phase 6 Stage 2 bisa dipersempit ke DiD + satu T-learner dengan placebo test.

## 6. Risiko yang dicatat di README

- Targeting Dunnhumby tidak acak, jadi semua angka uplift dan lift berlabel "di bawah asumsi".
- Margin adalah asumsi, bukan data.
- Hanya satu retailer, jadi penetrasi kategori adalah proxy.
- Data AS 2010-an, jadi pola promo belum tentu transfer ke Indonesia.
- Sampel ±2.500 household, jadi uplift per decile berisik dan CI harus selalu ditampilkan.

## 7. Titik mulai

Phase 0-1 (EDA + panel + timeline campaign). Hasilnya menentukan campaign mana yang punya control cukup untuk Phase 4 dan 6.
