# Retail Voucher Incrementality — Dari RFM ke Voucher Efficiency

> *"RFM bilang siapa yang belanja banyak. Uplift bilang siapa yang berubah karena voucher. Dan saya tunjukkan kapan angka uplift itu layak dipercaya."*

Analisis efektivitas voucher pada panel belanja Dunnhumby Complete Journey — 2.500 member, 102 minggu, 2,6 juta baris transaksi — diposisikan sebagai **methodology transfer** ke program member loyalty ritel Indonesia, bukan klaim tentang perilaku pelanggannya. Yang dijual proyek ini bukan angka uplift-nya, melainkan kejujuran soal kapan angka itu layak dipercaya: setiap output menyertakan asumsi yang membuatnya valid, bukti seberapa kuat asumsi itu bertahan pada data, dan batas atribusi biaya yang menjepit kesimpulannya.

## Sekilas hasil

- **Campaign bekerja, tapi tidak semua**: 14 dari 20 campaign terestimasi lolos uji reliabilitas; efek rata-rata **+$3,8–4,9 per minggu per member (95% CI $2,9–4,8 fixed-effect)** — *observasional, di bawah asumsi unconfoundedness*.
- **Model CLV kalah dari rata-rata historis** — ditulis apa adanya: belanja grocery yang hampir periodik sudah menangkap hampir semua sinyal. RFM/historis tetap acuan.
- **Targeting bermasalah bias win-back**: member dipilih justru saat belanjanya turun; tanpa mengondisikan trajektorinya, sebagian "efek" hanyalah pemulihan alami.
- **Member paling responsif ≠ member belanja terbesar**: skor uplift berkorelasi **negatif** dengan RFM — keduanya menemukan populasi berbeda.
- **Ekonomi voucher menang besar di targeting selektif**: top-2 decile skor uplift menghasilkan **$232 incremental spend per $1 voucher (95% CI 124–402, batas ketat)** — 2,6× memberi voucher ke semua orang, 3,8× RFM naif; urutan stabil di dua batas atribusi biaya. Pada margin 25% dan batas biaya paling konservatif tetap positif: **+$6,9 margin per $1**, break-even margin 3,2%.

## Pertanyaan bisnis

1. Siapa member bernilai tinggi, dan siapa yang mulai turun?
2. Seberapa promo-dependent tiap segmen?
3. Campaign mana yang beneran menaikkan spend, dan berapa incremental margin per $1 voucher?
4. Member mana yang paling responsif, dan berapa efisiensi budget jika voucher hanya ke top decile?
5. Kategori mana yang jadi whitespace per segmen?

**Bukan tujuan proyek:** klaim kausal final, prediksi churn production-grade, rekomendasi per SKU, atau klaim perilaku member Super Indo.

## Temuan utama

**Fondasi — panel & kelayakan campaign.** Panel 255.000 baris (2.500 member × 102 minggu) dibangun dengan menghindari jebakan yang paling sering menggagalkan analisis panel ritel: minggu retailer yang tidak seragam (minggu 1 hanya 5 hari, sehingga hari 224 jatuh di minggu 33 — bukan 32 hasil rumus naive), diskon yang tersimpan sebagai nilai negatif, dan 3,1% baris retur yang tetap masuk agregasi alih-alih dibuang diam-diam. Dari 30 campaign, 20 layak dianalisis efeknya — 3 backbone TypeA (1.076–1.133 treated, control pool 1.251–1.374) dan 17 menengah dengan CI lebar; 9 ditandai tidak reliable, 1 dikecualikan.

**Nilai member — RFM & CLV 52 minggu.** RFM kuintil terbukti baseline yang kuat. BG/NBD + Gamma-Gamma justru kalah dari rata-rata historis tiap member pada holdout 26 minggu — MAE 322 vs 308 (95% CI selisih +8,6 s.d. +20,5) — karena belanja grocery hampir periodik. Konsekuensinya dipegang konsisten: `CLV 52 minggu` hanya deskriptor berlabel asumsi; keputusan targeting tetap di atas RFM dan historis. Asumsi independensi Gamma-Gamma juga terbukti dilanggar (Spearman 0,43) dan menempel sebagai batasan.

**Whitespace kategori — proxy satu retailer.** Membandingkan tiap member dengan cohort semirip (tercile spend × tercile ragam; 7 dari 9 sel grid terisi, n terkecil 127) menghasilkan top-10 kategori kandidat per member; hampir separuh entrinya kategori yang belum pernah dibeli. Pola lintas member masuk akal — daging, bir, minuman, popok — dengan satu jebakan yang ditandai: COUPON/MISC ITEMS adalah kategori operator dan dikecualikan dari rekomendasi.

**Efek campaign — observasional, dengan pelajaran identifikasi.** Targeting campaign ini bercorak **win-back**: member dipilih saat spend-nya sedang turun, lalu sebagian pemulihannya alami (mean reversion) — tanpa pengondisian, DiD membaca pemulihan itu sebagai efek campaign. Setelah trajektori dan level dip pra-campaign dikontrol, estimasi backbone turun ±30% dan reliabilitas dijaga dua placebo. Hasil akhir: backbone yang bersih — campaign 8 (+9,8%) dan 13 (+15,2%) — signifikan setelah koreksi multiplicity; campaign 18 signifikan secara aritmetika tapi gagal placebo jauh dan ditandai. Ekonomi voucher dua batas: atribusi ketat memberi $3,3–3,6 incremental spend per $1 (break-even margin 28–30%); batas konservatif negatif pada konvensi mingguan.

**Segmentasi — tiga wajah yang stabil.** K-means pada RFM (log) + ketergantungan promo + bauran 44 department, dengan pemilihan k berdasarkan stabilitas lintas seed dan lintas paruh periode (ARI 0,646) karena silhouette rendah di semua k — struktur segmen memang lembut, dan itu diakui. Tiga segmen efektif yang bertahan: **mesin pertumbuhan** (1.099 member; spend $4.386; churn 2,6%), **promo-dependent** (972; promo 0,23 tertinggi; churn 17%), dan **rentan hilang** (429; churn 39%) — masing-masing dengan satu aksi dari aturan tetap. Ambang churn datang dari distribusi panel (gap > p95 = 5 minggu), bukan angka bulat.

**Uplift dua tahap & ekonomi voucher.** Mesin uplift divalidasi dulu di eksperimen acak X5 (200 ribu member; decile teratas T-learner +12,0 pp [9,3–14,5] ≈ 3× efek rata-rata), lalu dipakai di panel Dunnhumby dengan pengaman penuh: split mengikuti waktu campaign, fitur ketat pra-campaign, evaluasi berbobot overlap, placebo treatment-palsu yang lolos. Hasilnya: decile teratas X-learner **+$14,7/minggu [9,7–20,2]** (≈2,3× efek rata-rata), dan pada simulasi ROI atas 8 campaign akhir yang tak pernah dilihat model, **top-2 decile menghasilkan $232 per $1 voucher (batas ketat; konservatif $31,7)** vs blanket $90/$12,3 dan RFM naif $62/$9,8. RFM justru kalah dari blanket pada batas ketat — audiens high-spend-nya membakar kupon terbanyak dengan incremental terkecil. Kekalahan & kelemahan juga ditulis: T-learner tidak konsisten antar subset, decile tengah tidak monoton, margin di validasi silang sisi train tipis — angka selalu dibaca indikatif dengan CI, dan keputusan produksi memerlukan holdout eksperimen 10%.

## Status fase

| Fase | Isi | Status |
|---|---|---|
| 0–1 | Panel `hh_week` + timeline campaign + kelayakan DiD | ✅ selesai (5/5 gate) |
| 2 | RFM + CLV 52 minggu + uji vs baseline naif | ✅ selesai — model kalah dari naif, ditulis apa adanya |
| 3 | Penetration gap per cohort + whitespace per member | ✅ selesai — berlabel `proxy dalam satu retailer` |
| 4 | Campaign DiD + event study + covariate balance | ✅ selesai — 14/30 lolos semua gate; pooled $3,8–4,9/minggu |
| 5 | Segmentasi K-means + stabilitas ARI | ✅ selesai — 3 segmen efektif; churn threshold dari data |
| 6 | Uplift dua tahap (randomized + observational) | ✅ selesai — Stage 1 X5 + Stage 2 Dunnhumby; placebo lolos |
| 7 | Simulasi ROI voucher (5 skenario + sensitivitas) | ✅ selesai — top-2 decile $232/$1; break-even ≤8,1% |
| 8 | Deliverable | ✅ dashboard 4 halaman, star schema, Excel targeting, playbook, slide re-run; file `.pbix` dirakit terpisah di Power BI Desktop mengikuti [MODEL_MANIFEST.md](powerbi/MODEL_MANIFEST.md) |

## Deliverable

- [outputs/dashboard.html](outputs/dashboard.html) — dashboard 4 halaman (Member Overview, Segment Deep Dive, Campaign Lift, Voucher Efficiency) dalam satu file self-contained; halaman 4 punya **what-if interaktif** (slider margin & proporsi targeting); flag reliabilitas campaign tampil beserta alasannya.
- [outputs/targeting_sample.xlsx](outputs/targeting_sample.xlsx) — list targeting 2.498 member (segmen, decile uplift & CLV, offer, cap voucher, `include_flag`) + sheet asumsi.
- [outputs/playbook.md](outputs/playbook.md) — playbook 1 halaman: aturan targeting, offer matrix per segmen, guardrail budget (cap $18; stop rule incremental margin per $1 < 1), holdout 10%, cadence evaluasi.
- [outputs/rerun_slide.md](outputs/rerun_slide.md) — re-run dengan data My Super Indo: mapping data, 3 data yang wajib disediakan (margin, holdout flag, transaksi non-member), 8 definisi yang mengunci hasil.
- [powerbi/MODEL_MANIFEST.md](powerbi/MODEL_MANIFEST.md) — panduan merakit `.pbix` dari star schema, termasuk measures DAX siap tempel dan checklist QA.

## Asumsi utama

Setiap angka lahir di bawah asumsi berikut, dan labelnya menempel ke mana pun angka itu dibawa.

| Asumsi | Konsekuensi |
|---|---|
| Treatment campaign dipilih retailer, bukan diacak | Semua lift/uplift berlabel `observational — di bawah asumsi unconfoundedness`; tidak pernah ditulis "voucher menyebabkan" |
| Margin per kategori tidak ada di data | Selalu parameter eksplisit + sensitivitas 15/25/35%, tidak pernah satu angka tunggal |
| Horizon data ±2 tahun | Selalu `CLV 52 minggu`, tidak pernah "lifetime value" |
| Hanya satu retailer | Yang dihitung penetration gap — `proxy dalam satu retailer`; total dompet lintas retailer tidak diklaim |
| Spend = net (`SALES_VALUE` + seluruh diskon) | Satu definisi untuk semua fase; retur tidak dibuang |
| Biaya voucher dua batas atribusi | Ketat (kupon daftar campaign) vs konservatif (semua kupon) — kesimpulan hanya diambil bila stabil di keduanya |

## Limitasi

Yang berikut belum terselesaikan dan sengaja tetap ditampilkan:

- Treatment tidak acak: estimasi efek hanya valid di bawah asumsi unconfoundedness — propensity, overlap, dan placebo test mengurangi risikonya, tidak menghapus.
- Tidak ada tanggal kirim per member (timing hanya level-campaign), tidak ada data margin, tidak ada transaksi non-member. Tiga hal ini tidak "diakali" dengan proxy tak berlabel.
- 74 pasang campaign beririsan waktunya: campaign 15 dikecualikan, 21/22 berwindow identik, 24 terpotong akhir data — control group tiap campaign dihitung mengecualikan campaign yang beririsan.
- Demografi hanya 32% member → profil segmen saja, bukan fitur model.
- Nominal USD era 2010-an; untuk transfer ke konteks lain bawa **rasio unitless**, bukan angkanya.
- Segmen deskriptif dengan struktur lembut (silhouette rendah; bukti kelayakannya stabilitas ARI, bukan ketajaman klaster); aksi segmen adalah kandidat uji.
- Uplift observational: keunggulan X-learner muncul di campaign akhir held-out, tetapi validasi silang sisi train hanya memberi margin tipis (+$0,04/member); decile tengah tidak monoton; T-learner tidak konsisten; decile n < 30 tidak diklaim.
- Simulasi ROI memakai horizon window (relasi eksak dengan konvensi mingguan fase DiD = × panjang window); batas ketat meledak untuk campaign TypeB kecil (daftar kupon tipis); biaya per-targeted diekstrapolasi dari treated terobservasi. Angka ROI = latihan "seandainya efek kausal", bukan janji hasil — keputusan produksi memerlukan holdout eksperimen.

## Data

**Dunnhumby *The Complete Journey*** — 8 CSV mentah di `data/` (terbesar `causal_data.csv` 695 MB, opsional), tidak pernah di-commit (`data/` di-gitignore). Panel ini perlu diperoleh mandiri dari sumber resmi Dunnhumby/Kaggle. Untuk Stage 1 uplift, data eksternal **X5 RetailHero** (±740 MB) terunduh otomatis via `scikit-uplift` saat notebook 06 pertama kali dijalankan.

Seluruh angka faktual di README dihitung ulang dari CSV dan **dikunci 107 test** (12 modul: panel, CLV, cohort, DiD, segment, dashboard, uplift randomized, X5, uplift observational, ROI, star schema, targeting). Turunan analisis hidup sebagai 16 parquet di `data/processed/` + star schema 8 CSV untuk Power BI di `data/processed/star/`.

## Struktur repo

```
.
  data/               # CSV mentah (gitignored) + data/processed/*.parquet (gitignored) + star/ (gitignored)
  notebooks/          # 01_panel … 08_roi_sim — ter-render; logika di src/
  src/                # features, clv, cohorts, did, segments, dashboard, x5,
                      # uplift_learners, uplift_eval, uplift_obs, simulate,
                      # starschema, targeting
  tests/              # 107 assertion kualitas data & invariant hasil (12 modul)
  conftest.py         # session fixtures dari data asli (dibangun sekali per run)
  powerbi/            # MODEL_MANIFEST.md — panduan merakit .pbix
  outputs/            # dashboard.html, targeting_sample.xlsx, playbook.md, rerun_slide.md
```

## Memulai

Setup (Windows, PowerShell; Python 3.12, venv di `notebooks/.venv` — dijalankan dari root repo):

```powershell
py -m venv notebooks\.venv
.\notebooks\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-modeling.txt   # CLV Bayes + uplift
pip install -r requirements-dev.txt        # pytest
python -m ipykernel install --user --name dunnhumby --display-name "Python (Dunnhumby 3.12)"
```

Cek sehat: `python -m pip check` → "No broken requirements found." Reproduksi persis: `requirements.lock.txt`.

Reproduksi & regenerasi artefak:

```powershell
python -m pytest                # 107 test atas data asli
python -m src.dashboard         # rebuild outputs/dashboard.html (deterministik)
python -m src.starschema        # rebuild data/processed/star/*.csv (untuk Power BI)
python -m src.targeting         # rebuild outputs/targeting_sample.xlsx
```

Notebook `01`–`08` dieksekusi end-to-end dengan kernel "Python (Dunnhumby 3.12)". Build dashboard dan Excel bersifat deterministik — suite test gagal bila artefak ter-commit berbeda dari hasil rebuild.

## Konvensi pelaporan

Tiga label dipakai konsisten — `terverifikasi (data)`, `asumsi`, `tidak reliable` — dan angka selalu dengan konteks: `lift +4,2% (95% CI −0,8% s.d. +9,1%, n_treated=…, n_control=…)`. Grafik bersatuan, judul menyebut filter (campaign, window, n), tanpa dual-axis; campaign yang tidak reliable ditampilkan beserta alasannya, tidak disembunyikan. Aturan lengkap: [AGENTS.md](AGENTS.md).

## Dokumen terkait

- [the-complete-journey.md](the-complete-journey.md) — spesifikasi requirement & desain analisis.
- [AGENTS.md](AGENTS.md) — aturan kerja, registri fakta terverifikasi, jebakan data, quality gate per fase.
- Decision log (21 keputusan formal yang mengikat metodologi) dan rencana eksekusi — dokumen kerja lokal, tidak di-commit.
