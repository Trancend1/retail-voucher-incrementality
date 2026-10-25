# Project agent rules

## Source of Truth map

| Topik | SOT | Kalau bertentangan |
|---|---|---|
| Requirement & desain analisis | [`the-complete-journey.md`](the-complete-journey.md) | Spec menang — perbaiki file yang menyimpang, jangan menyimpang diam-diam |
| Framing bisnis, status phase, limitation publik, struktur repo, setup env | [`README.md`](README.md) | — |
| Keputusan formal yang mengikat semua phase | [`docs/decision-log.md`](docs/decision-log.md) | Perubahan hanya lewat entri baru, bukan edit diam-diam |
| Fakta data terverifikasi, jebakan, aturan kerja, quality gate | File ini | Angka yang tidak tercatat di §2 = belum terverifikasi — verifikasi dari data sebelum dipakai/dikutip |

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
| **R11** | Raw data tidak pernah di-commit (695 MB `causal_data.csv`). Turunan besar → `data/processed/*.parquet` (juga di-gitignore); yang di-commit hanya kode, notebook ter-render, dan artefak kecil di `outputs/`. |
| **R12** | Jangan mengubah angka/simpulan di README agar enak dibaca. Limitation yang belum terselesaikan tetap di README. |

---

## 2. Fakta data terverifikasi

Diperiksa langsung dari CSV di `data/` pada 2026-10-23 (pandas 3.0.3). Kalau data diganti, **verifikasi ulang** — angka di bawah tidak otomatis berlaku.

| Tabel | Baris | Catatan terverifikasi |
|---|---|---|
| `transaction_data.csv` | 2.595.732 | 2.500 household, 276.484 basket, 582 store. `WEEK_NO` 1–102, `DAY` 1–711. |
| `campaign_desc.csv` | 30 campaign | `START_DAY` 224–659, `END_DAY` 264–719. Durasi 32–161 hari (median 37,5). Campaign 26 mulai hari 224 (**minggu 33** via jembatan DAY→WEEK, terverifikasi L1 sprint-p1 2026-10-24; catatan lama "minggu 32" berasal dari rumus naive — lihat §3.3). |
| `campaign_table.csv` | 7.208 | 1.584 household unik, tanpa duplikat. Treated per campaign: **12–1.133**. |
| `coupon_redempt.csv` | 2.318 | 434 household. **100%** redemption ada di dalam window campaign dan **100%** redeemers ada di `campaign_table` untuk campaign tersebut. |
| `coupon.csv` | 124.548 | Peta `COUPON_UPC → PRODUCT_ID` per campaign. |
| `hh_demographic.csv` | 801 | Hanya 32% household punya demografi → profil segmen saja, bukan fitur wajib. |
| `product.csv` | 92.353 | 44 `DEPARTMENT`, 308 `COMMODITY_DESC`. |
| `causal_data.csv` | 695 MB | `PRODUCT_ID × STORE_ID × WEEK_NO`, `display` + `mailer`. Opsional; jangan load penuh ke memori. |

### 2.1 Skala treatment per campaign (krusial untuk Phase 4)

- **Layak jadi campaign utama DiD:** 8 (1.076 hh), 13 (1.077), 18 (1.133) — semuanya `TypeA`, redemption tinggi (158/196/214 hh). Ini tulang punggung analisis.
- **Menengah (100–500 treated):** 5 (166), 7 (198), 9 (176), 10 (123), 11 (214), 12 (170), 14 (224), 16 (188), 17 (202), 19 (130), 20 (244), 22 (276), 23 (183), 25 (187), 26 (332), 29 (118), 30 (361). Layak, tapi CI per campaign akan lebar — laporkan dengan CI.
- **Terlalu kecil untuk DiD mandiri (< 100):** 1 (13), 2 (48), 3 (12), 4 (81), 6 (65), 15 (17), 21 (65), 27 (12), 28 (17). Batas: 24 (100). Laporkan sebagai agregat atau tandai tidak reliable.
- **Tumpang tindih parah:** 74 pasangan campaign beririsan waktunya. `21` dan `22` punya window identik (624–656). Campaign `15` (`TypeC`, 161 hari) beririsan dengan 12 campaign lain dan menelan hampir 23 minggu → **keluarkan dari estimasi utama** atau batasi window.
- **Terpotong data:** campaign `24` berakhir `DAY 719` sementara data berhenti `711` → window tidak lengkap.

Implikasi: control group harus didefinisikan per campaign ("tidak ditarget campaign ini **dan** tidak ditarget campaign lain yang window-nya beririsan"), bukan sekadar "tidak ada di campaign_table". Kalau aturan ini dilanggar, estimasi akan bias ke arah nol.

### 2.2 Hasil terverifikasi Phase 0–1 (2026-10-24, sprint-p1 L0–L9)

- Panel `hh_week`: 255.000 baris (2.500 household × 102 minggu), unik; total `net_spend` = $6.608.940,89 — konsisten dengan agregat level baris (DL-001).
- Retur terkonfirmasi (DL-002): 18.850 baris `SALES_VALUE<=0`, 80.890 baris `net<0`; 43.478 household-minggu ber-flag `has_return`.
- `promo_share` (DL-004): p50 0,15 / p90 0,37 / p99 0,78 — sanity ≤ 1 lolos; ekor > 1 dilaporkan, tidak dipangkas.
- Coverage join `product.csv`: **100%** baris transaksi (92.339 produk bertransaksi dari 92.353 di master).
- Control pool per campaign (exclude overlap): 8=1.359, 13=1.374, 18=1.251; kelayakan: 17 `layak`, 3 `layak — utama`, 9 `tidak reliable`, 1 `excluded` (15).
- Hari 224 (campaign 26) = minggu 33 via `WEEK_NO` aktual — catatan lama "minggu 32" salah (rumus naive, §3.3).

### 2.3 Hasil terverifikasi Phase 2 — CLV (2026-10-25, sprint-p2)

- Populasi validasi: 2.498 household aktif ≤ minggu 76 (2 terlambat — dikecualikan & dilaporkan); kuintil RFM full-period seimbang tepat 500/kuintil.
- BG/NBD kalibrasi: penalizer 0, r=2,79 / α=5,23 / a=0,02 / b=10,31. Full: ConvergenceError tanpa penalizer → penalizer 0,01 (ladder resmi lifetimes), r=2,28 / α=4,28 / a=0,003 / b=0,51. 3 household 1-minggu-aktif (frequency=0) memicu NaN di lifetimes → ditangani cabang closed-form x=0 di `src/clv.py`.
- Gamma-Gamma full: p=0,18 / q=4,45 / v=947. **Asumsi independensi F–M dilanggar** — Spearman ρ=0,429 (p≈1,8e-112) → limitation pada `clv_52w`.
- CLV 52 minggu (USD, net, n=2.500): p10=315 | p50=1.050 | p90=3.135 | p99=6.364.
- **R9: model kalah dari baseline naif** di holdout 26 minggu — MAE 322,2 vs 307,6 (95% CI selisih +8,6 s.d. +20,5; p_model_worse=1,0); RMSE 488,5 vs 476,3; Spearman 0,773 vs 0,780. Konsekuensi: `clv_52w` hanya deskriptor berlabel; RFM/baseline historis tetap acuan targeting.

### 2.4 Hasil terverifikasi Phase 3 — penetration gap (2026-10-25, sprint-p3)

- Cohort (DL-008): 7 dari 9 sel grid terisi — S1xB3 kosong alami (tidak ada spend-kecil/ragam-luas), S3xB1 (n=4) dimerge ke S2xB1; n terkecil 127, total 2.500.
- Kategori kandidat per cohort (buyer-rate ≥ 30%, median > 0): 81–211 dari 308 komoditas.
- Whitespace (DL-009): 25.000 baris = top-10 × 2.500 member (cap terisi penuh semua member); zero-buyer 48,8%; `expected_spend` p50 $18,5 / p99 $268 / max $1.281.
- Top whitespace global: COUPON/MISC ITEMS (n=1.233 — kategori operator, ditandai untuk dikecualikan dari rekomendasi), lalu BEEF, BEERS/ALES, SOFT DRINKS, DIAPERS & DISPOSABLES.
- R2: frasa terlarang tidak ada di README/notebook/src — dijaki test `test_banned_phrase_absent_from_deliverables`.

### 2.5 Hasil terverifikasi Phase 4 — campaign DiD (2026-10-25, sprint-p4 + 2 ronde investigasi)

- Design: `n_control` per campaign == control pool fase fondasi (20/20); redemption 8/13/18 == 158/196/214 (cocok §2.1).
- **DL-014 (temuan kunci): seleksi win-back + mean reversion.** Propensity level-saja membuat placebo jauh (−24..−17) gagal 15/20 bertanda negatif; mengondisikan `spend_trend_pre` + `spend_dip_level` menutupnya. Gate reliabilitas = dua placebo + balance + n.
- Backbone final (overlap weights, fitur diperluas): 8 $2,67 [0,69; 4,51] +9,8% — lolos semua gate; 13 $4,12 [2,20; 6,14] +15,2% — lolos; 18 $4,29 [2,41; 6,05] +18,1% — **gagal placebo jauh → flagged**, meski signifikan BH. Estimasi turun ±30% vs tanpa pengondisian — diungkap sebagai spesifikasi-sensitivitas.
- Lolos semua gate: **14 campaign** {5,8,9,11,12,13,14,16,19,20,22,23,29,30}; flagged pre-trend jauh: {7,10,17,18,25,26}; balance 20/20 (SMD max 0,005 backbone).
- Signifikansi BH q<0,05: {8,12,13,14,16,18,20,22,23} (9 campaign; 18 tetap flagged).
- Pooled (meta, k=14): FE $3,83 [2,89; 4,77]; RE $4,87 [3,06; 6,68]; I² 66%.
- Ekonomi dua batas (DL-013): ketat — 8: $3,55/$1 (break-even 28%), 13: $3,31 (30%), 18: $2,52 (40%, flagged); margin35 positif hanya untuk 8 & 13; batas konservatif negatif semua.
- Konsekuensi: headline = 8 & 13 + pooled; semua observasional (R1); angka dibaca sebagai rentang spesifikasi.

### 2.6 Hasil terverifikasi Phase 5 — segmentasi (2026-10-25, sprint-p5)

- Fitur: RFM log + `promo_share_mean` + share 44 department (join langsung produk); 2.500 member, share menjumlah 1,0 persis.
- Outlier (amendemen DL-015): top-1% spender dikecualikan dari fitting, di-assign ke centroid terdekat; klaster < 30 dikonsolidasikan. Winsorisasi p1/p99 pernah dicoba dan **ditolak** — clipping menciptakan tie di cap yang membentuk mikro-klaster artefak (29 anggota menempel di semua k).
- k final = 5 (core-fit) → **3 segmen efektif** setelah konsolidasi; alasan: ARI lintas seed paling rapat (median 0,646, min 0,641); silhouette rendah di semua k (0,02–0,07) — struktur lembut, diungkap.
- Segmen: 1) mesin pertumbuhan n=1.099 (total spend $4.386, promo 0,16, churn 2,6%); 2) promo-dependent n=972 (spend $1.431, promo 0,23 tertinggi, churn 17,4%); 3) rentan hilang n=429 (spend $927, churn 39,2%, dropping 19,1%).
- Churn dari data: gap p95 = **5 minggu** (14,6% member ter-flag); rasio H2/H1 p10 = 0,419 (10,0% dropping).
- Whitespace utama (COUPON/MISC ITEMS dikecualikan, temuan §2.4): seg1 BEEF ($441/member), seg2 BEERS/ALES, seg3 BEEF; aksi deterministik per segmen (aktivasi ulang / benefit non-diskon / dorong whitespace).

### 2.7 Hasil terverifikasi — dashboard MVP halaman 1–3 (2026-10-25, tutup cut line MVP)

- Deliverable: `outputs/dashboard.html` — **satu file HTML self-contained 134 KB** (chart SVG inline, tanpa resource eksternal — diuji; tab Member Overview / Segment Deep Dive / Campaign Lift). Dibangun `python -m src.dashboard` dari parquet fase analisis; **deterministik** (rebuild identik byte-for-byte, dikunci test `test_committed_dashboard_is_current`).
- Format decision: DL-016 (HTML statis; Power BI + star schema tetap Phase 8 penuh). Deviasi format dari spec §4.2 tercatat terbuka.
- Pooled meta-analysis **direproduksi dari parquet** oleh `pooled_meta()` (inverse-variance FE + DerSimonian-Laird RE): FE $3,83 [2,89; 4,77]; RE $4,87 [3,06; 6,68]; I² 66% — cocok §2.5 persis.
- 12 test baru (`tests/test_dashboard.py`) mengunci angka dashboard ke registri §2.2–§2.6 (KPI panel, percentil CLV, ukuran/behavior segmen, flag & ATT backbone, redemption, pooled) + label kepatuhan di markup (observational/unconfoundedness, proxy dalam satu retailer, CLV 52 minggu, margin = parameter asumsi) + frasa terlarang R2 kini juga dipindai di `outputs/*.html`.
- QA visual (browser): DOM 1 header / 3 halaman, tanpa overflow horizontal (scrollW == clientW ≤ viewport), forest plot 20 baris + label terbaca. (Catatan: screenshot fullPage browser menghasilkan artefak tiling — jangan pakai sebagai bukti; audit DOM + screenshot viewport yang dipakai.)

---

### 2.8 Hasil terverifikasi Phase 6 Stage 1 — uplift randomized X5 (2026-10-25, sprint p6a)

- Data (via `sklift.fetch_x5`, cache `data/external/` gitignored): train **200.039 client** (dari populasi 400.162), treatment 49,98%, target biner *belanja bertambah*; raw ATE **+3,32 pp** (0,6365 vs 0,6033). `purchases` 45.786.568 baris, window 2018-11-21 s.d. 2019-03-18 (117 hari) — seluruhnya pra-campaign by design → fitur bebas leakage.
- Fitur (`src/x5.py`, cache `data/processed/x5_client_features.parquet`, 16 kolom, **tanpa NaN**): agregat RFM histori (n transaksi/total spend/avg basket/n toko/recency/span) + kartu (usia clip 14–100 + flag outlier 0,44%, gender **U 46,4%**/F 36,8%/M 16,8%, tenure, jeda redeem −1 utk 17,7% non-redeemer).
- Randomization terverifikasi: **max |SMD| 0,0234** (`has_redeem`); seluruh fitur lain ≤ 0,0086 — jauh di bawah ambang 0,1.
- Holdout 50.010 (split acak 75/25 seed 42 — sah hanya karena randomized): ATE **+3,81 pp [2,87; 4,65]**. **T-learner AUUC skill +344** (0,688 pp per client yang ditarget; Qini 647); **X-learner +293** (0,585; 621) — keduanya mengalahkan targeting acak. Decile-1: T **+12,0 pp [9,3; 14,5]** (≈3× ATE), X +13,1 [10,3; 15,9]; decile 8–10 ≈ 0 (CI memuat 0).
- Kejujuran hasil dicatat: skill per client hanya 0,6–0,7 pp (ranking bukan pengganda efek); decile tengah X-learner tidak monoton — urutan di bawah decile atas tidak dibaca halus.
- R9 untuk Stage 1: **model menang dari baseline acak** — tidak perlu klausul kekalahan, tapi margin moderat diungkap di notebook.

---

### 2.9 Hasil terverifikasi Phase 6 Stage 2 — uplift observational Dunnhumby (2026-10-25, sprint p6b)

- Panel household×campaign (`src/uplift_obs.py`, dari parquet processed): **37.976 baris** / 20 campaign terestimasi; treated 6.778 (17,9%). Fitur 9 kolom pre-window (7 fitur DiD + `n_campaigns_before`/`redemption_rate_before` (distink per campaign, bukan per kupon)/`tenure_weeks`; 43 baris tenure<0 — member belum belanja saat campaign mulai, dibiarkan & dilaporkan). Outcome Δ = spend net mingguan window − pre-8-mgg (USD/mgg).
- **Split waktu ketat** (R6): 12 campaign train (s.d. minggu mulai 77) vs 8 test (mulai minggu 81: 5 `layak` + 3 `flagged` — flagged tetap dievaluasi dengan flag-nya, R7). Model hanya di-fit pada 9 campaign train lolos gate (17.733 baris); dummy campaign memakai vocab tetap (campaign test = kolom nol, seperti deployment di campaign baru).
- Test (n=14.090, bobot overlap): **ATE acak +$6,31/mgg [4,80; 7,68]**; subset lolos gate (n=8.021): +$8,26 [5,87; 10,57].
- **X-learner unggul**: decile-1 **+$14,66/mgg [9,66; 20,22]** (≈2,3× ATE); AUUC skill +8.820 (+$0,626/member); gain@20% +$11,32/member — vs **RFM naif** +$0,370/+$8,08 dan T-learner +$0,096 (T tidak konsisten: layak-only −$0,112). Decile tengah X tidak monoton; decile-10 tinggi (+$8,0) — sebagian skill datang dari ekor, diungkap.
- Korelasi skor X vs RFM **−0,31** (komplementer — X menemukan responsif di populasi margin belanja menengah-kecil); decile 9–10 RFM n_treated 12–20 < 30 → NaN (R8 bekerja).
- **OOF train (GroupKFold by household): X hanya +$0,042/member** — keunggulan besar muncul di campaign akhir; angka test dibaca indikatif (spesifikasi-sensitif), diungkap di notebook.
- **Placebo lolos** (treatment dipermutasi per campaign, outcome Δ pre, seluruh pipeline di-refit): ATE +$1,71 [−0,39; 3,61] memuat 0; decile-1 CI memuat 0; skill −516 (≈0).
- R9: **X menang dari random & RFM pada test** (skill + gain@20%); T kalah/tidak konsisten; margin OOF tipis dilaporkan apa adanya. Semua klaim berlabel observational (R1).
- Artefak: `uplift_scores.parquet` (14.090 × 14; skor T/X/RFM + ps + bobot + flag + segmen) & `uplift_eval_results.parquet` (decile long-form 3 skor × 10).

---

## 3. Jebakan data (baca sebelum menulis query pertama)



1. **Diskon bernilai negatif.** `RETAIL_DISC`, `COUPON_DISC`, `COUPON_MATCH_DISC` negatif (50% baris `RETAIL_DISC` < 0). `promo_share` wajib pakai `abs()`:
   `promo_share = (|RETAIL_DISC| + |COUPON_DISC|) / gross_sales`. Tanpa `abs()`, hasilnya negatif dan tidak masuk akal.
2. **Baris retur/adjusment.** 80.890 baris (±3,1%) punya `SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC < 0`, dan 18.850 baris `SALES_VALUE <= 0`. Kebijakan eksplisit: agregasi net, tidak di-drop — [DL-002](docs/decision-log.md); kuantifikasi wajib muncul di Phase 1 dan README.
3. **`WEEK_NO` bukan turunan `DAY`.** `floor((DAY-1)/7)+1` hanya cocok untuk ±73% baris; minggu retailer punya batas yang tidak selalu 7 hari (minggu 1 = hari 1–5, minggu 2 = hari 6–12). **Join lewat `WEEK_NO`**, jangan derive dari `DAY`.
4. **`campaign_table` tidak punya tanggal kirim.** Hanya `(household, campaign)`. Timing treatment bersifat level-campaign, diambil dari `campaign_desc.START_DAY/END_DAY`. Ini keterbatasan nyata: efek per household tidak bisa di-align ke tanggal terima.
5. **Redemption bukan treatment** (R10). Beberapa campaign hampir tanpa redemption sama sekali (3, 6, 15, 27: 1–2 redemption) — itu masalah ukuran sampel/channel, bukan bukti campaign gagal. Jangan menyimpulkan efektivitas dari redemption rate saja. `TypeA` (8, 13, 18) justru punya redemption 158–214 household dan paling bisa dianalisis.
6. **Semua campaign mulai minggu ≥ 33** (diverifikasi via jembatan DAY→WEEK, L1 sprint-p1 2026-10-24). Artinya pre-period panjang (±32 minggu) tapi kalau CLV holdout 26 minggu, sisa pre-window untuk campaign awal jadi tipis. Urutan pemotongan window harus diputuskan sadar, bukan otomatis.
7. **Tidak ada data margin, tidak ada share of wallet total, tidak ada transaksi non-member.** Tiga hal ini tidak bisa "diakali" dengan proxy yang tidak dilabeli.
8. **Nominal USD historis.** Jangan bandingkan langsung ke Rp tanpa menyebut konversi & tahun. Untuk slide transfer, cukup bilang "rasio unitless".
9. **`SALES_VALUE` vs net.** `SALES_VALUE` tidak otomatis = uang yang dibayar. Definisi spend sudah diputuskan formal: `net_spend` — [DL-001](docs/decision-log.md); tidak diubah setelah Phase 1.

---

## 4. Konvensi kode & artefak

Struktur direktori (target dan aktual) ada di README; struktur target berasal dari spec §4. Tidak diduplikasi di sini. Konvensi yang mengikat:

- **Notebook = presentasi, `src/` = logic.** Kalau sebuah fungsi dipakai di >1 notebook atau butuh test, pindahkan ke `src/`. Notebook tidak boleh menyimpan logika yang menentukan angka final.
- Notebook bernomor sesuai urutan phase; nama file stabil karena dirujuk dari README.
- Kolom mentah `UPPER_CASE`; di layer processed dinormalisasi ke `snake_case` (`household_key`, `week_no`, `net_spend`, ...). Jangan campur dua gaya dalam satu tabel.
- Semua fungsi random menerima `random_state`/`seed`; default `RANDOM_STATE = 42` di satu tempat.
- Artefak antar-phase = parquet di `data/processed/` dengan nama yang menyebut grain — saat ini (14): `hh_week`, `campaign_timeline`, `hh_clv`, `hh_category`, `hh_campaign`, `hh_whitespace`, `cohort_category`, `campaign_did_results`, `campaign_event_study`, `segments`, `segment_summary`, `x5_client_features`, `uplift_scores`, `uplift_eval_results`; bertambah per phase (ROI, dst.). Data eksternal (X5 ±740 MB) hidup di `data/external/` (gitignored), hanya turunan fiturnya yang jadi parquet.
- Deliverable dashboard MVP = `outputs/dashboard.html` (HTML self-contained, dibangun `src/dashboard.py`, deterministik; angka dikunci `tests/test_dashboard.py` — regenerasi wajib `python -m src.dashboard` agar committed == rebuild).
- Setiap tabel hasil yang masuk dashboard harus punya kolom `n`, `ci_low`, `ci_high` (kalau estimasi) dan `reliability_flag` (kalau campaign).

---

## 5. Lingkungan (fakta operasional)

- Python **3.12.7**, venv di **`notebooks/.venv`** (bukan root); kernel Jupyter: **Python (Dunnhumby 3.12)** (`--name dunnhumby`; path kernel diperbarui 2026-10-24 setelah repo pindah direktori).
- Versi terverifikasi di mesin ini (2026-10-23) — core: `pandas 3.0.3`, `numpy 2.4.6`, `duckdb 2.0.0`, `polars 2.0.0`, `pyarrow 26.0.0`, `scipy 1.18.1`, `statsmodels 0.15.0`, `scikit-learn 1.8.0`, `matplotlib 3.9.3`, `seaborn 0.13.2`, `jupyterlab 4.6.4`; modeling: `lifetimes 0.11.3`, `pymc-marketing 1.3.0` (menarik `pymc 6.3.2`), `scikit-uplift 0.5.1`, `econml 0.17.0`. `causalml` **tidak** dipasang — alternatifnya `econml`.
- Test runner: `pytest 9.1.1`, config `pytest.ini`; suite `tests/` = 90 test atas data asli dalam 9 modul (panel, clv, cohorts, did, segments, dashboard, uplift_eval, x5, uplift_obs; session fixtures di `conftest.py`, dibangun sekali per run). Test baru ditulis tiap phase bersama modul `src/` terkait.
- `setuptools` ditahan `<81` karena `lifetimes 0.11.3` masih impor `pkg_resources`.
- Git: branch `main`, remote `origin` = `github.com/Trancend1/retail-voucher-incrementality`.
- File requirements: `requirements.txt` (inti), `requirements-modeling.txt` (Phase 2/6), `requirements-dev.txt` (pytest), `requirements.lock.txt` (freeze persis). **Perintah setup lengkap ada di README — jangan diduplikasi di sini.** Cek sehat: `python -m pip check` → "No broken requirements found."

Jebakan lingkungan:

- `causal_data.csv` 695 MB dan `transaction_data.csv` 142 MB → **pakai DuckDB** (`read_csv_auto` langsung dari CSV, agregasi pushdown) sebelum jatuh ke pandas. pandas 3 masih oke untuk 2,6 juta baris transaksi, tapi jangan untuk `causal_data` penuh.
- pandas 3 aktif dengan copy-on-write; hindari chained assignment (`df[df.a > 0]["b"] = ...`).
- `pymc` di Windows tidak punya `g++` → PyTensor jalan mode Python (lebih lambat). Jangan panik saat melihat warning `g++ not available`; import dan MAP fit sudah diuji jalan. Untuk MCMC panjang, pasang compiler atau turunkan volume sampling.

---

## 6. Alur kerja agent

1. **Baca** `AGENTS.md` + `the-complete-journey.md`. Cek `data/` lengkap (8 CSV).
2. **Ikuti urutan fase** (status resmi ada di README milestone). Estimasi efek (DiD, Phase 4) harus tuntas sebelum uplift modeling (Phase 6). Daftar campaign layak + control pool sudah tersedia di `data/processed/campaign_timeline.parquet` — jangan dihitung ulang dengan definisi lain.
3. **Kerjakan per phase, bukan per file.** Satu phase = notebook + modul `src/` terkait + artefak parquet + catatan limitation.
4. **Verifikasi sebelum klaim selesai.** Jalankan notebook end-to-end dari kernel bersih; tempel angka kunci (n, lift, CI) di ringkasan. Jangan menulis "sudah selesai" berdasarkan notebook yang hanya jalan sebagian.
5. **Setiap phase menambah bagian limitation di README** kalau ada asumsi baru.
6. **Hormati cut line MVP:** Phase 0–5 + dashboard halaman 1–3 + README. Phase 6–7 adalah lapisan pembeda, dikerjakan setelah MVP stabil.
7. Kalau menemukan bukti bahwa rencana di spec tidak feasible (mis. control group terlalu kecil untuk campaign tertentu), **laporkan dan sesuaikan cakupan** — jangan paksakan estimasi yang tidak reliable.

Saat menjawab user, akhiri dengan pemisahan jelas: **apa yang terverifikasi dari data**, **apa yang masih asumsi**, **apa langkah berikutnya**.

---

## 7. Quality gate per phase

Definition of done minimum. Gate yang gagal = phase belum selesai, walau notebook sudah "jalan".

### Phase 0–1 — Panel & timeline
- [ ] Tabel timeline 30 campaign: `campaign_id, type, start_day, end_day, start_week, end_week, n_treated, overlaps_with, truncated_flag`
- [ ] Panel `hh_week` unik per `(household_key, week_no)` (assert), rentang 1–102, 2.500 household
- [ ] `promo_share` dengan `abs()`, tidak ada nilai negatif
- [ ] Kebijakan retur/baris negatif tertulis + jumlah baris terdampak dilaporkan
- [ ] Daftar campaign layak/tidak layak untuk DiD beserta alasannya

### Phase 2 — CLV
- [ ] RFM kuintil + distribusi per kuintil
- [ ] BG/NBD + Gamma-Gamma (mingguan), horizon 52 minggu
- [ ] Diagnostic wajib: korelasi frequency–monetary, kalibrasi vs holdout, **perbandingan dengan baseline naif**
- [ ] Kesimpulan menyebut kalau model kalah dari baseline (R9)

### Phase 3 — Penetration gap
- [ ] Definisi cohort eksplisit dan reproducible
- [ ] Tabel whitespace per household/segmen dengan expected spend cohort
- [ ] Label `proxy, satu retailer` muncul di tabel, notebook, dan dashboard (R2)

### Phase 4 — Campaign DiD
- [ ] Treated/control per campaign saling lepas dan control sudah exclude campaign overlap
- [ ] Event-study plot untuk parallel pre-trend
- [ ] Overlap propensity + tabel SMD sebelum/sesudah (target |SMD| < 0,1)
- [ ] Output: lift %, CI, redemption rate, voucher cost, incremental margin per $1
- [ ] `reliability_flag` + alasan untuk campaign yang gagal gate (R7)

### Phase 5 — Segmentasi
- [ ] K-means pada RFM log + category share + promo_share, alasan pemilihan k
- [ ] Uji stabilitas: fit periode 1 → assign periode 2 → ARI dilaporkan
- [ ] Tabel segmen: ukuran, spend, promo dependence, churn risk, whitespace utama, satu aksi
- [ ] Threshold churn-risk berasal dari distribusi inter-purchase gap data ini, bukan angka bulat

### Phase 6 — Uplift
- [ ] Stage 1 (randomized): Qini/uplift curve + AUUC, T-learner vs X-learner
- [ ] Stage 2 (Dunnhumby): split by campaign time + GroupKFold by household (R6)
- [ ] Placebo test: treatment palsu di periode pre → uplift ≈ 0 (laporkan CI-nya)
- [ ] Bootstrap CI per decile; decile dengan n < 30 tidak diklaim (R8)
- [ ] Semua klaim diberi label observational (R1)

### Phase 7 — ROI
- [ ] Tiga skenario (blanket, top-2 decile, top-4 decile) di campaign held-out
- [ ] Sensitivitas margin 15/25/35% + bootstrap CI
- [ ] Incremental margin per $1 voucher + titik break-even
- [ ] Biaya voucher berasal dari `COUPON_DISC` observed, bukan asumsi

### Phase 8 — Deliverable
- [ ] Dashboard 4 halaman (Member Overview, Segment Deep Dive, Campaign Lift, Voucher Efficiency) dengan flag reliability terlihat
- [ ] Star schema: `dim_household, dim_campaign, dim_category, dim_week, fact_hh_week, fact_hh_campaign, fact_hh_category`
- [ ] Playbook 1 halaman: aturan targeting, offer matrix, guardrail budget, holdout 10%, cadence evaluasi
- [ ] Slide re-run: tabel mapping Dunnhumby → My Super Indo (termasuk baris data yang **tidak ada**)
- [ ] `targeting_sample.xlsx`: sheet output + sheet asumsi
- [ ] README: framing bisnis, asumsi, limitation **di atas fold**

---

## 8. Konvensi pelaporan

- Angka selalu dengan konteks: `lift +4,2% (95% CI −0,8% s.d. +9,1%, n_treated=<n>, n_control=<n>)`.
- Tiga label status yang dipakai konsisten: `terverifikasi (data)`, `asumsi`, `tidak reliable`.
- Bahasa: hindari "membuktikan", "menyebabkan", "pasti". Pakai "konsisten dengan", "diestimasi sebesar", "di bawah asumsi".
- Grafik: sumbu diberi satuan, judul menyebut filter (campaign, window, n), tidak ada dual-axis.
- Tabel dashboard: `reliability_flag` tidak boleh disembunyikan di tooltip; kalau campaign tidak reliable, tampilkan alasannya.

### Gaya penulisan naratif (notebook & deliverable)

- Notebook ditulis untuk **pembaca analisis**, bukan sebagai pelacak proyek: tanpa rujukan langkah/sprint/checkpoint/gate, tanpa frasa status progres ("selesai", "belum mulai", "menunggu persetujuan"), tanpa tanggal kecuali tanggalnya bagian dari data. Status & progres hanya hidup di README (milestone) dan `docs/sprint-*.md` (lokal).
- Setiap bagian dibuka dengan *mengapa* — pertanyaan atau insight yang memotivasi bagian itu; definisi teknis menyusul setelahnya, bukan dibuka dengan daftar isi atau "pada bagian ini akan dibahas…".
- Istilah teknikal penting dipertahankan apa adanya (nama kolom, `net`, `promo_share`, BG/NBD, `CLV 52 minggu`, holdout, Spearman, p99). Jargon proses internal — nomor langkah, sprint, gate, ID keputusan (DL-xxx), ID aturan (Rxx) — **tidak muncul** di narasi notebook: definisinya ditulis langsung; rujukan ke decision log cukup satu kali di bagian pembuka.
- Buang kalimat statis/pengisi ("seperti telah disebutkan", "selanjutnya kita akan") dan angka yang cepat basi (mis. jumlah test saat ini) — setiap kalimat harus membawa informasi: angka, asumsi, atau konsekuensi.
- Temuan kunci boleh dicetak tebal; angka tetap tunduk pada aturan konteks di atas (CI, n, satuan).

---

## 9. Status & utang terbuka

**Status:** Cut line MVP tercapai (2026-10-25) — Phase 0–5 DoD penuh + dashboard hal. 1–3 + README final (§2.2–§2.7). **Phase 6 selesai dua tahap**: Stage 1 randomized X5 (§2.8) + Stage 2 observational Dunnhumby (§2.9) — X-learner decile-1 +$14,66/mgg [9,66; 20,22] ≈ 2,3× ATE acak, gain@20% +$11,32/member vs RFM +$8,08, placebo lolos. 90/90 test hijau (9 modul), 7 notebook ter-render, `main` sinkron dengan remote. Status resmi per phase: README (SOT status).

**Utang terbuka:** tidak ada yang memblokir. Halaman dashboard 4 (Voucher Efficiency) + what-if menunggu angka Phase 7; Power BI + star schema ditunda ke Phase 8 penuh (DL-016). Dua hal dibiarkan **disengaja**: warning autograd terlihat; `docs/` lokal/di-gitignore.

**Berikutnya:** Phase 7 — simulasi ROI voucher (3 skenario targeting blanket/top-2/top-4 decile pada campaign held-out pakai `uplift_scores.parquet`; voucher cost dua batas DL-013; margin 15/25/35 + bootstrap CI; break-even) — lihat `docs/plan-phase6-7.md` (lokal). Lalu Phase 8 penuh: dashboard hal. 4, star schema + Power BI, playbook, slide re-run, `targeting_sample.xlsx`.
