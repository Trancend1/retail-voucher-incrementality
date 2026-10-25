# Project agent rules

## Source of Truth map

| Topik | SOT | Kalau bertentangan |
|---|---|---|
| Requirement & desain analisis | [`the-complete-journey.md`](the-complete-journey.md) | Spec menang — perbaiki file yang menyimpang, jangan menyimpang diam-diam |
| Framing bisnis, limitation publik, dokumentasi proyek (struktur repo, deliverable, setup env) | [`README.md`](README.md) | — |
| Keputusan formal yang mengikat semua phase | [`docs/decision-log.md`](docs/decision-log.md) | Perubahan hanya lewat entri baru, bukan edit diam-diam |
| Fakta data terverifikasi, jebakan, aturan kerja, quality gate, **status fase (§9)** | File ini | Angka yang tidak tercatat di §2 = belum terverifikasi — verifikasi dari data sebelum dipakai/dikutip |

Konteks singkat: analisis efektivitas voucher/campaign retail di panel Dunnhumby Complete Journey (±2.500 household, 102 minggu), methodology transfer ke use case member loyalty ritel Indonesia. Alur: RFM/CLV → category penetration gap → campaign effect (DiD) → segmentasi → uplift (2 tahap) → simulasi ROI voucher.

Non-goal (jangan dikerjakan, jangan dijanjikan): klaim kausal final, prediksi churn production-grade, rekomendasi per SKU, klaim perilaku member Super Indo.

Bahasa: dokumen dan narasi deliverable dalam Bahasa Indonesia; nama variabel, kolom, dan komentar kode dalam Inggris.

---

## 1. Aturan keras

Aturan bernomor supaya bisa dirujuk di review dan commit message.

| ID | Aturan |
|---|---|
| **R1** | Treatment Dunnhumby **tidak** randomized. Semua lift/uplift diberi label `observational — di bawah asumsi unconfoundedness`. Jangan pernah menulis "voucher menyebabkan" tanpa kualifikasi itu. |
| **R2** | Dilarang memakai frasa "share of wallet" di output. Yang dihitung adalah **category penetration gap** dan harus dilabeli `proxy dalam satu retailer`. |
| **R3** | Margin per kategori adalah **asumsi**, bukan data. Selalu tampil sebagai parameter eksplisit + sensitivitas 15/25/35%. Jangan hardcode satu angka di narasi. |
| **R4** | CLV selalu dilabeli horizon-nya (`CLV 52 minggu`). Jangan menulis "lifetime value". |
| **R5** | Fitur hanya dari window **pre-treatment**, dengan cutoff per campaign (`DAY < START_DAY`). Dilarang memakai agregat full-period untuk fitur model. Ini leakage, dan sulit dideteksi setelah hasilnya bagus. |
| **R6** | Untuk Dunnhumby: **jangan random split**. Split by campaign time (train campaign awal → test campaign akhir) + `GroupKFold` by `household_key`. |
| **R7** | Campaign yang pre-trend jelek / overlap tipis **ditandai `tidak reliable`**, tidak dibuang diam-diam. Tampilkan di tabel dengan flag dan alasan. |
| **R8** | Setiap estimasi menyertakan `n` dan CI (bootstrap untuk metrik non-standar). n < 30 → jangan dilaporkan sebagai sel/decile/segmen. |
| **R9** | Kalau model kalah dari baseline naif (BG/NBD vs rata-rata historis; uplift model vs random targeting), **tulis apa adanya**. Jangan tuning sampai menang lalu sembunyikan percobaan sebelumnya. |
| **R10** | `coupon_redempt` adalah **outcome**, bukan treatment. Treatment = keanggotaan di `campaign_table`. |
| **R11** | Raw data tidak pernah di-commit (695 MB `causal_data.csv`; X5 ±740 MB). Turunan besar → `data/processed/*.parquet` (juga di-gitignore); yang di-commit hanya kode, notebook ter-render, dan artefak kecil di `outputs/`. |
| **R12** | Jangan mengubah angka/simpulan di README agar enak dibaca. Limitation yang belum terselesaikan tetap di README. |

---

## 2. Fakta data terverifikasi

Diperiksa langsung dari CSV/parquet; setiap fase menambah subseksi. Kalau data diganti, **verifikasi ulang** — angka di bawah tidak otomatis berlaku. Angka yang tidak tercatat di sini = belum terverifikasi.

| Tabel | Baris | Catatan terverifikasi |
|---|---|---|
| `transaction_data.csv` | 2.595.732 | 2.500 household, 276.484 basket, 582 store. `WEEK_NO` 1–102, `DAY` 1–711. |
| `campaign_desc.csv` | 30 campaign | `START_DAY` 224–659, `END_DAY` 264–719. Durasi 32–161 hari (median 37,5). Hari 224 = **minggu 33** via jembatan DAY→WEEK (jangan derive dari `DAY` — lihat §3.3). |
| `campaign_table.csv` | 7.208 | 1.584 household unik, tanpa duplikat. Treated per campaign: **12–1.133**. |
| `coupon_redempt.csv` | 2.318 | 434 household. **100%** redemption dalam window campaign dan **100%** redeemer ada di `campaign_table` campaign tersebut. |
| `coupon.csv` | 124.548 | Peta `COUPON_UPC → PRODUCT_ID` per campaign. |
| `hh_demographic.csv` | 801 | Hanya 32% household → profil segmen saja, bukan fitur wajib. |
| `product.csv` | 92.353 | 44 `DEPARTMENT`, 308 `COMMODITY_DESC`. |
| `causal_data.csv` | 695 MB | `PRODUCT_ID × STORE_ID × WEEK_NO`, `display` + `mailer`. Opsional; jangan load penuh ke memori. |

### 2.1 Skala treatment per campaign (krusial untuk Phase 4)

- **Layak jadi campaign utama DiD:** 8 (1.076 hh), 13 (1.077), 18 (1.133) — semuanya `TypeA`, redemption tinggi (158/196/214 hh).
- **Menengah (100–500 treated):** 5 (166), 7 (198), 9 (176), 10 (123), 11 (214), 12 (170), 14 (224), 16 (188), 17 (202), 19 (130), 20 (244), 22 (276), 23 (183), 25 (187), 26 (332), 29 (118), 30 (361). CI per campaign lebar — laporkan dengan CI.
- **Terlalu kecil untuk DiD mandiri (< 100):** 1 (13), 2 (48), 3 (12), 4 (81), 6 (65), 15 (17), 21 (65), 27 (12), 28 (17). Batas: 24 (100).
- **Tumpang tindih parah:** 74 pasangan campaign beririsan. `21`/`22` window identik (624–656). `15` (`TypeC`, 161 hari) beririsan dengan 12 campaign → **dikecualikan dari estimasi utama**. `24` terpotong akhir data (berakhir DAY 719, data berhenti 711).

Implikasi: control group harus didefinisikan per campaign ("tidak ditarget campaign ini **dan** tidak ditarget campaign lain yang window-nya beririsan"). Kalau dilanggar, estimasi bias ke arah nol.

### 2.2 Phase 0–1 — panel & timeline (2026-10-24)

- Panel `hh_week`: 255.000 baris, unik; total `net_spend` $6.608.940,89 — konsisten agregat level baris (DL-001).
- Retur (DL-002): 18.850 baris `SALES_VALUE<=0`, 80.890 baris `net<0`; 43.478 household-minggu ber-flag `has_return`.
- `promo_share` (DL-004): p50 0,15 / p90 0,37 / p99 0,78 — ekor > 1 dilaporkan, tidak dipangkas.
- Coverage join `product.csv`: **100%** (92.339 dari 92.353 produk bertransaksi).
- Control pool (exclude overlap): 8=1.359, 13=1.374, 18=1.251; kelayakan: 17 `layak`, 3 `layak — utama`, 9 `tidak reliable`, 1 `excluded` (15).

### 2.3 Phase 2 — CLV (2026-10-25)

- Populasi validasi 2.498 (2 terlambat, dikecualikan & dilaporkan); kuintil RFM seimbang 500/kuintil.
- BG/NBD kalibrasi: penalizer 0; full: ConvergenceError → penalizer 0,01. 3 household frequency=0 ditangani cabang closed-form di `src/clv.py`.
- Gamma-Gamma: **asumsi independensi F–M dilanggar** — Spearman ρ=0,429 (p≈1,8e-112) → limitation `clv_52w`.
- CLV 52 minggu (USD, net, n=2.500): p10=315 | p50=1.050 | p90=3.135 | p99=6.364.
- **R9: model kalah dari baseline naif** di holdout 26 minggu — MAE 322,2 vs 307,6 (95% CI selisih +8,6 s.d. +20,5); RMSE 488,5 vs 476,3. Konsekuensi: `clv_52w` deskriptor berlabel; targeting tetap di atas RFM/historis.

### 2.4 Phase 3 — penetration gap (2026-10-25)

- Cohort (DL-008): 7 dari 9 sel grid terisi (S1xB3 kosong alami; S3xB1 n=4 dimerge); n terkecil 127, total 2.500.
- Kandidat per cohort (buyer-rate ≥ 30%, median > 0): 81–211 dari 308 komoditas.
- Whitespace (DL-009): 25.000 baris = top-10 × 2.500 member; zero-buyer 48,8%; `expected_spend` p50 $18,5 / p99 $268 / max $1.281.
- Top whitespace global: COUPON/MISC ITEMS (n=1.233 — **kategori operator, dikecualikan dari rekomendasi**), lalu BEEF, BEERS/ALES, SOFT DRINKS, DIAPERS & DISPOSABLES.

### 2.5 Phase 4 — campaign DiD (2026-10-25)

- Design: `n_control` per campaign == control pool fondasi (20/20); redemption 8/13/18 == 158/196/214.
- **DL-014 (temuan kunci): seleksi win-back + mean reversion.** Propensity level-saja membuat placebo jauh gagal 15/20; mengondisikan `spend_trend_pre` + `spend_dip_level` menutupnya. Gate reliabilitas = dua placebo + balance + n.
- Backbone final (overlap weights, fitur diperluas): 8 $2,67 [0,69; 4,51] +9,8% — lolos semua gate; 13 $4,12 [2,20; 6,14] +15,2% — lolos; 18 $4,29 [2,41; 6,05] +18,1% — **gagal placebo jauh → flagged**. Estimasi turun ±30% vs tanpa pengondisian (spesifikasi-sensitif, diungkap).
- Lolos semua gate: **14 campaign** {5,8,9,11,12,13,14,16,19,20,22,23,29,30}; flagged pre-trend jauh: {7,10,17,18,25,26}; balance 20/20 (SMD max 0,005).
- Signifikansi BH q<0,05: {8,12,13,14,16,18,20,22,23} (18 tetap flagged).
- Pooled (meta, k=14): FE $3,83 [2,89; 4,77]; RE $4,87 [3,06; 6,68]; I² 66%.
- Ekonomi dua batas (DL-013): 8: $3,55/$1 (break-even 28%), 13: $3,31 (30%), 18: $2,52 (40%, flagged); margin35 positif hanya 8 & 13; batas konservatif negatif semua (konvensi mingguan — rekonsiliasi dengan §2.10 via ×n_minggu).
- Konsekuensi: headline = 8 & 13 + pooled; semua observasional (R1); angka dibaca sebagai rentang spesifikasi.

### 2.6 Phase 5 — segmentasi (2026-10-25)

- Fitur: RFM log + `promo_share_mean` + share 44 department; 2.500 member, share menjumlah 1,0 persis.
- Outlier (amendemen DL-015): top-1% spender dikecualikan dari fitting, di-assign ke centroid terdekat; klaster < 30 dikonsolidasikan. Winsorisasi p1/p99 pernah dicoba dan **ditolak** (tie di cap → mikro-klaster artefak).
- k final = 5 (core-fit) → **3 segmen efektif** setelah konsolidasi; alasan: ARI lintas seed paling rapat (median 0,646); silhouette rendah di semua k (0,02–0,07) — struktur lembut, diungkap.
- Segmen: 1) mesin pertumbuhan n=1.099 (spend $4.386, promo 0,16, churn 2,6%); 2) promo-dependent n=972 (spend $1.431, promo 0,23 tertinggi, churn 17,4%); 3) rentan hilang n=429 (spend $927, churn 39,2%, dropping 19,1%).
- Churn dari data: gap p95 = **5 minggu** (14,6% member ter-flag); rasio H2/H1 p10 = 0,419 (10,0% dropping).
- Whitespace utama (operator dikecualikan): seg1 BEEF ($441/member), seg2 BEERS/ALES, seg3 BEEF.

### 2.7 Dashboard — fakta permanen (2026-10-25; keadaan saat ini lihat §2.11)

- `outputs/dashboard.html` dibangun `python -m src.dashboard`, **deterministik** — test `test_committed_dashboard_is_current` memaksa committed == rebuild; regenerasi wajib lewat modul, bukan edit manual.
- Pooled meta-analysis **direproduksi dari parquet** oleh `pooled_meta()` (inverse-variance FE + DerSimonian-Laird RE) — cocok §2.5 persis; dikunci test.
- Pelajaran QA visual: gunakan audit DOM + screenshot **viewport**; screenshot fullPage browser menghasilkan artefak tiling — bukan bukti.

### 2.8 Phase 6 Stage 1 — uplift randomized X5 (2026-10-25)

- Data (`sklift.fetch_x5`, cache `data/external/`): train **200.039 client** (populasi 400.162), treatment 49,98%, target biner; raw ATE **+3,32 pp** (0,6365 vs 0,6033). `purchases` 45.786.568 baris, window 2018-11-21 s.d. 2019-03-18 (117 hari) — seluruhnya pra-campaign by design → bebas leakage.
- Fitur (`src/x5.py`, cache `x5_client_features.parquet`, 16 kolom, tanpa NaN): agregat RFM histori + kartu (usia clip 14–100 + flag outlier 0,44%, gender U 46,4%/F 36,8%/M 16,8%, tenure, jeda redeem −1 utk 17,7% non-redeemer).
- Randomization terverifikasi: **max |SMD| 0,0234** (`has_redeem`); lainnya ≤ 0,0086.
- Holdout 50.010: ATE **+3,81 pp [2,87; 4,65]**. **T-learner AUUC skill +344** (0,688 pp/client; Qini 647); **X-learner +293** (0,585; 621). Decile-1: T **+12,0 pp [9,3; 14,5]** (≈3× ATE), X +13,1 [10,3; 15,9]; decile 8–10 ≈ 0.
- R9: model menang dari acak; margin moderat (0,6–0,7 pp/client) & decile tengah X tidak monoton — diungkap.

### 2.9 Phase 6 Stage 2 — uplift observational Dunnhumby (2026-10-25)

- Panel household×campaign (`src/uplift_obs.py`): **37.976 baris** / 20 campaign terestimasi; treated 6.778 (17,9%). Fitur 9 kolom pre-window (7 DiD + `n_campaigns_before`/`redemption_rate_before` per-campaign/`tenure_weeks`; 43 baris tenure<0 dibiarkan & dilaporkan). Outcome Δ = spend net mingguan window − pre-8-mgg.
- **Split waktu ketat** (R6): 12 train (s.d. minggu 77) vs 8 test (mulai minggu 81: 5 `layak` + 3 `flagged`, R7). Fit hanya pada 9 campaign train lolos gate (17.733 baris); dummy campaign vocab tetap (campaign test = kolom nol).
- Test (n=14.090, bobot overlap): **ATE acak +$6,31/mgg [4,80; 7,68]**; subset layak (n=8.021): +$8,26 [5,87; 10,57].
- **X-learner unggul**: decile-1 **+$14,66/mgg [9,66; 20,22]** (≈2,3× ATE); AUUC skill +8.820 (+$0,626/member); gain@20% +$11,32/member — vs RFM naif +$0,370/+$8,08 dan T-learner +$0,096 (T tidak konsisten: layak-only −$0,112). Decile tengah X tidak monoton; decile-10 tinggi — diungkap.
- Korelasi skor X vs RFM **−0,31** (komplementer — margin penargetan vs high-spend); decile 9–10 RFM n_treated 12–20 → NaN (R8).
- **OOF train (GroupKFold household): X hanya +$0,042/member** — angka test dibaca indikatif (spesifikasi-sensitif).
- **Placebo lolos** (treatment dipermutasi per campaign, outcome Δ pre, pipeline di-refit): ATE +$1,71 [−0,39; 3,61] memuat 0; decile-1 CI memuat 0.
- Artefak: `uplift_scores.parquet` (14.090 × 14; skor T/X/RFM + ps + bobot + flag + segmen) & `uplift_eval_results.parquet`.

### 2.10 Phase 7 — simulasi ROI (2026-10-25)

- Input: 8 campaign held-out + biaya dua batas per (household, campaign): **ketat** (join daftar kupon; cache `roi_costs.parquet`) & **semua kupon** (panel). Biaya terobservasi: ketat $2.775 / semua $15.162.
- **Konvensi horizon window (DL-019)**: incr = uplift $/mgg × n_minggu × audiens vs biaya total window. Validasi eksak vs kolom DiD mingguan (×n_minggu): 0,0% di 8/8 (dikunci test rel 1e-6).
- Hasil (all-8, ketat, CI cluster-bootstrap 1.000 by household): **uplift top-2 decile $232,19/$1 [124,13; 402,03]** — 2,6× blanket $90,36 [62,25; 121,84], 3,8× RFM top-2 $61,71; top-4 $185,18; RFM top-4 $94,71. **Bound semua-kupon**: 31,73 / 12,32 / 9,79 / 23,22 / 14,27 — urutan stabil di kedua batas & subset layak (top-2 layak-only $516,89 [209,92; 1.320,97]).
- **RFM top-2 < blanket (ketat)**: audiens high-spend membakar kupon terbanyak ($2.071 vs $954) dengan incremental lebih kecil ($127,8rb vs $221,6rb).
- Ekonomi margin (R3): margin 25% + konservatif → top-2 **+$6,93 per $1** (blanket +$2,08); break-even: ketat ≤1,1%, konservatif top-2 3,2% / blanket 8,1% — positif di semua level margin yang diuji, **observational (R1)**.
- Artefak: `roi_scenarios.parquet` (10 baris: {all, layak} × 5 skenario).

### 2.11 Phase 8 — dashboard 4 halaman + star schema (2026-10-25)

- **Dashboard 4 halaman** (`outputs/dashboard.html`, 162 KB, self-contained): hal. 4 *Voucher Efficiency* = KPI dua batas + chart per skenario + tabel sensitivitas + **widget what-if** (proporsi 5–100%, margin 5–40%, skor uplift/RFM; grid precomputed 20 titik × 2 skor dari `scenario_core` Phase 7 — widget tidak mungkin beda dari `roi_scenarios`; interaksi terverifikasi cocok §2.10).
- **Star schema** (`src/starschema.py` → `data/processed/star/`, 8 CSV, rebuild `python -m src.starschema`): dim household 2.500 (segmen + clv_decile) / campaign 30 (+ hasil DiD + flag & alasan) / category 308 (komoditas + department + flag operator) / week 102; fact hh_week 255.000 / hh_campaign 14.090 (+ `uplift_decile` per campaign) / hh_category 288.690; `scenario_roi` 10. **PK unik + FK 100% + row count dikunci test.**
- **`powerbi/MODEL_MANIFEST.md`** (committed): panduan build `.pbix` — impor, 6 relasi, DAX siap tempel, layout 4 halaman, what-if, checklist QA, refresh.
- Keputusan: DL-020.

### 2.12 Phase 8 — targeting xlsx + playbook + slide (2026-10-25)

- **`outputs/targeting_sample.xlsx`** (`src/targeting.py`, committed, deterministik — test committed == rebuild): sheet *output* **2.498 member** (skor X-learner campaign held-out terbaru; 2 member tak pernah masuk pool), kolom persis spec §4.4; sheet *asumsi* 11 baris. `include_flag` = top-2 decile → **503 (20,1%)**; voucher cap **$18** (p90 biaya kupon terobservasi per treated); offer matrix deterministik; whitespace tanpa NaN, operator dikecualikan.
- **`outputs/playbook.md`**: aturan targeting, offer matrix 3 segmen + top-2, guardrail (cap $18; **stop rule incremental margin per $1 < 1**), **holdout 10% stratified**, cadence per-campaign/kuartalan/tahunan.
- **`outputs/rerun_slide.md`**: mapping 13 baris (3 "(tidak ada)": margin, holdout flag, transaksi non-member) + 8 definisi terkunci re-run.
- Ronde audit pasca-p8b: 3 flaw ditemukan & diperbaiki (struktur README, kutipan frasa terlarang di manifest — scan R2 kini mencakup `outputs/*.md` + `powerbi/*.md`, pembulatan xlsx).
- Keputusan: DL-021.

---

## 3. Jebakan data (baca sebelum menulis query pertama)

1. **Diskon bernilai negatif.** `RETAIL_DISC`, `COUPON_DISC`, `COUPON_MATCH_DISC` negatif (50% baris `RETAIL_DISC` < 0). `promo_share` wajib pakai `abs()`:
   `promo_share = (|RETAIL_DISC| + |COUPON_DISC|) / gross_sales`. Tanpa `abs()`, hasilnya negatif dan tidak masuk akal.
2. **Baris retur/adjusment.** 80.890 baris (±3,1%) punya `SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC < 0`, dan 18.850 baris `SALES_VALUE <= 0`. Kebijakan eksplisit: agregasi net, tidak di-drop — [DL-002](docs/decision-log.md); kuantifikasi wajib muncul di Phase 1 dan README.
3. **`WEEK_NO` bukan turunan `DAY`.** `floor((DAY-1)/7)+1` hanya cocok untuk ±73% baris; minggu retailer punya batas yang tidak selalu 7 hari (minggu 1 = hari 1–5, minggu 2 = hari 6–12). **Join lewat `WEEK_NO`**, jangan derive dari `DAY`.
4. **`campaign_table` tidak punya tanggal kirim.** Hanya `(household, campaign)`. Timing treatment level-campaign, dari `campaign_desc.START_DAY/END_DAY`. Efek per household tidak bisa di-align ke tanggal terima.
5. **Redemption bukan treatment** (R10). Campaign 3, 6, 15, 27 nyaris tanpa redemption (1–2) — masalah ukuran sampel/channel, bukan bukti gagal; jangan simpulkan efektivitas dari redemption rate saja. `TypeA` (8, 13, 18) redemption 158–214 hh, paling bisa dianalisis.
6. **Semua campaign mulai minggu ≥ 33.** Pre-period panjang (±32 minggu) tapi sisa pre-window untuk campaign awal tipis kalau CLV holdout 26 minggu — urutan pemotongan window diputuskan sadar.
7. **Tidak ada data margin, tidak ada dompet lintas ritel, tidak ada transaksi non-member.** Tiga hal ini tidak bisa "diakali" dengan proxy yang tidak dilabeli.
8. **Nominal USD historis.** Jangan bandingkan langsung ke Rp tanpa menyebut konversi & tahun. Untuk slide transfer, cukup bilang "rasio unitless".
9. **`SALES_VALUE` vs net.** Definisi spend formal: `net_spend` — [DL-001](docs/decision-log.md); tidak diubah setelah Phase 1.

---

## 4. Konvensi kode & artefak

Struktur direktori ada di README; tidak diduplikasi di sini. Konvensi yang mengikat:

- **Notebook = presentasi, `src/` = logic.** Fungsi yang dipakai >1 notebook atau butuh test → `src/`. Notebook tidak boleh menyimpan logika yang menentukan angka final.
- Notebook bernomor sesuai urutan phase; nama file stabil.
- Kolom mentah `UPPER_CASE`; layer processed `snake_case`. Jangan campur.
- Semua fungsi random menerima `random_state`/`seed`; default `RANDOM_STATE = 42` di satu tempat.
- Artefak parquet di `data/processed/` bernama sesuai grain — saat ini (16): `hh_week`, `campaign_timeline`, `hh_clv`, `hh_category`, `hh_campaign`, `hh_whitespace`, `cohort_category`, `campaign_did_results`, `campaign_event_study`, `segments`, `segment_summary`, `x5_client_features`, `uplift_scores`, `uplift_eval_results`, `roi_costs`, `roi_scenarios`. Star schema Power BI: 8 CSV di `data/processed/star/` (rebuild `python -m src.starschema`). Data eksternal (X5) di `data/external/` (gitignored).
- Deliverable di `outputs/` — semuanya committed, deterministik, angka dari parquet terverifikasi: `dashboard.html` (4 halaman; regenerasi `python -m src.dashboard`), `targeting_sample.xlsx` (`python -m src.targeting`), `playbook.md`, `rerun_slide.md`.
- Setiap tabel hasil yang masuk dashboard harus punya kolom `n`, `ci_low`, `ci_high` (kalau estimasi) dan `reliability_flag` (kalau campaign).

---

## 5. Lingkungan (fakta operasional)

- Python **3.12.7**, venv di **`notebooks/.venv`** (bukan root); kernel Jupyter: **Python (Dunnhumby 3.12)** (`--name dunnhumby`).
- Versi terverifikasi — core: `pandas 3.0.3`, `numpy 2.4.6`, `duckdb 2.0.0`, `polars 2.0.0`, `pyarrow 26.0.0`, `scipy 1.18.1`, `statsmodels 0.15.0`, `scikit-learn 1.8.0`, `matplotlib 3.9.3`, `seaborn 0.13.2`, `jupyterlab 4.6.4`; modeling: `lifetimes 0.11.3`, `pymc-marketing 1.3.0` (`pymc 6.3.2`), `scikit-uplift 0.5.1`, `econml 0.17.0`. `causalml` **tidak** dipasang — alternatifnya `econml`.
- Test runner: `pytest 9.1.1`, config `pytest.ini`; suite `tests/` = 107 test atas data asli dalam 12 modul (panel, clv, cohorts, did, segments, dashboard, uplift_eval, x5, uplift_obs, simulate, starschema, targeting; session fixtures di `conftest.py`, dibangun sekali per run). Test baru ditulis tiap perubahan bersama modul `src/` terkait.
- `setuptools` ditahan `<81` karena `lifetimes 0.11.3` masih impor `pkg_resources`.
- Git: branch `main`, remote `origin` = `github.com/Trancend1/retail-voucher-incrementality`.
- File requirements: `requirements.txt` (inti), `requirements-modeling.txt` (modeling), `requirements-dev.txt` (pytest), `requirements.lock.txt` (freeze persis). **Perintah setup lengkap ada di README — jangan diduplikasi di sini.** Cek sehat: `python -m pip check` → "No broken requirements found."

Jebakan lingkungan:

- `causal_data.csv` 695 MB dan `transaction_data.csv` 142 MB → **pakai DuckDB** (`read_csv_auto` + agregasi pushdown) sebelum jatuh ke pandas. pandas 3 oke untuk 2,6 juta baris transaksi, bukan untuk `causal_data` penuh.
- pandas 3 copy-on-write; hindari chained assignment (`df[df.a > 0]["b"] = ...`).
- `pymc` di Windows tanpa `g++` → PyTensor mode Python (lebih lambat). Warning `g++ not available` normal; import & MAP fit teruji. Untuk MCMC panjang, pasang compiler atau turunkan volume sampling.

---

## 6. Alur kerja agent

1. **Baca** `AGENTS.md` + `the-complete-journey.md`. Cek `data/` lengkap (8 CSV).
2. **Ikuti urutan fase** (status resmi ada di §9 tabel fase). Daftar campaign layak + control pool tersedia di `data/processed/campaign_timeline.parquet` — jangan dihitung ulang dengan definisi lain.
3. **Kerjakan per phase, bukan per file.** Satu phase = notebook + modul `src/` terkait + artefak parquet + catatan limitation.
4. **Verifikasi sebelum klaim selesai.** Jalankan notebook end-to-end dari kernel bersih + suite test hijau; tempel angka kunci (n, lift, CI) di ringkasan.
5. **Setiap asumsi baru menambah bagian limitation di README.**
6. **Fase 0–8 sisi analisis & artefak tuntas.** Pekerjaan baru = ekstensi/perbaikan — jangan membuka ulang fase selesai tanpa alasan terdokumentasi (entri decision log bila mengubah keputusan).
7. Kalau menemukan bukti rencana di spec tidak feasible, **laporkan dan sesuaikan cakupan** — jangan paksakan estimasi yang tidak reliable.

Saat menjawab user, akhiri dengan pemisahan jelas: **apa yang terverifikasi dari data**, **apa yang masih asumsi**, **apa langkah berikutnya**.

---

## 7. Quality gate per phase

Gate terpenuhi = bukti di §2 + modul test terkait (semua hijau). Fase 0–7 tuntas; detail gate historis ada di `docs/sprint-*.md` (lokal) dan spec §5. Gate yang masih aktif:

### Phase 8 — Deliverable (satu item tersisa)

- [x] Dashboard 4 halaman dengan flag reliability terlihat (`test_dashboard`)
- [x] Star schema 7 tabel + `scenario_roi` (`test_starschema`)
- [x] Playbook 1 halaman: targeting, offer matrix, guardrail, holdout 10%, cadence (`test_targeting`)
- [x] Slide re-run: mapping termasuk baris data yang **tidak ada** (`test_targeting`)
- [x] `targeting_sample.xlsx`: sheet output + sheet asumsi, deterministik (`test_targeting`)
- [x] README: framing, asumsi, limitation di atas fold (`test_cohorts` R2-scan)
- [ ] `.pbix`: dirakit user di Power BI Desktop mengikuti `powerbi/MODEL_MANIFEST.md` → screenshot di-review terhadap checklist manifest §5

---

## 8. Konvensi pelaporan

- Angka selalu dengan konteks: `lift +4,2% (95% CI −0,8% s.d. +9,1%, n_treated=<n>, n_control=<n>)`.
- Tiga label status konsisten: `terverifikasi (data)`, `asumsi`, `tidak reliable`.
- Bahasa: hindari "membuktikan", "menyebabkan", "pasti". Pakai "konsisten dengan", "diestimasi sebesar", "di bawah asumsi".
- Grafik: sumbu bersatuan, judul menyebut filter (campaign, window, n), tanpa dual-axis.
- Tabel dashboard: `reliability_flag` tidak boleh disembunyikan di tooltip; campaign tidak reliable tampil beserta alasannya.

### Gaya penulisan naratif (notebook & deliverable)

- Notebook ditulis untuk **pembaca analisis**, bukan pelacak proyek: tanpa rujukan langkah/sprint/checkpoint/gate, tanpa frasa status progres, tanpa tanggal kecuali bagian dari data. Status & progres hanya hidup di file ini (§9) dan `docs/sprint-*.md` (lokal) — README murni dokumentasi proyek untuk pembaca publik.
- Setiap bagian dibuka dengan *mengapa*; definisi teknis menyusul.
- Istilah teknikal dipertahankan apa adanya (nama kolom, `net`, `promo_share`, BG/NBD, `CLV 52 minggu`, holdout, Spearman, p99). Jargon proses internal — sprint, gate, DL-xxx, Rxx — **tidak muncul** di narasi notebook; rujukan decision log cukup satu kali di pembuka.
- Buang kalimat pengisi dan angka cepat basi — setiap kalimat membawa informasi: angka, asumsi, atau konsekuensi.
- Temuan kunci boleh cetak tebal; angka tetap tunduk aturan konteks (CI, n, satuan).

---

## 9. Status & utang terbuka

**Status per fase (SOT status — README murni dokumentasi publik):**

| Fase | Isi | Status |
|---|---|---|
| 0–1 | Panel + timeline + kelayakan DiD | ✅ (§2.2) |
| 2 | RFM + CLV 52 minggu vs baseline naif | ✅ — model kalah, ditulis apa adanya (§2.3) |
| 3 | Penetration gap + whitespace | ✅ (§2.4) |
| 4 | Campaign DiD | ✅ — pooled $3,8–4,9/mgg (§2.5) |
| 5 | Segmentasi | ✅ — 3 segmen, ARI 0,646 (§2.6) |
| 6 | Uplift dua tahap | ✅ — placebo lolos (§2.8–§2.9) |
| 7 | Simulasi ROI | ✅ — top-2 $232/$1 (§2.10) |
| 8 | Deliverable | 🟡 dashboard 4 hlm + star + xlsx + playbook + slide selesai (§2.11–§2.12); tersisa `.pbix` oleh user |

107/107 test hijau (12 modul), 8 notebook ter-render, `main` sinkron remote.

**Utang terbuka:** satu — `.pbix` (p8c, user, via `powerbi/MODEL_MANIFEST.md`); DAX measure belum pernah dieksekusi di Power BI Desktop (tidak bisa divalidasi headless; agent siap revisi dari pesan error). Dua hal dibiarkan **disengaja**: warning autograd terlihat; `docs/` lokal/di-gitignore.

**Berikutnya:** user merakit `.pbix` → kirim screenshot → agent review terhadap checklist manifest §5 → commit `powerbi/retail-voucher.pbix`. Setelah itu proyek tuntas penuh.
