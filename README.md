# Retail Voucher Incrementality — Dari RFM ke Voucher Efficiency

> *"RFM bilang siapa yang belanja banyak. Uplift bilang siapa yang berubah karena voucher. Dan saya tunjukkan kapan angka uplift itu layak dipercaya."*

Analisis efektivitas voucher pada panel belanja Dunnhumby Complete Journey — 2.500 member, 102 minggu, 2,6 juta baris transaksi — diposisikan sebagai **methodology transfer** ke program member loyalty ritel Indonesia, bukan klaim tentang perilaku pelanggannya. Yang dijual proyek ini bukan angka uplift-nya, melainkan kejujuran soal kapan angka itu layak dipercaya: setiap output menyertakan asumsi yang membuatnya valid dan bukti seberapa kuat asumsi itu bertahan pada data.

## Pertanyaan bisnis

1. Siapa member bernilai tinggi, dan siapa yang mulai turun?
2. Seberapa promo-dependent tiap segmen?
3. Campaign mana yang beneran menaikkan spend, dan berapa incremental margin per $1 voucher?
4. Member mana yang paling responsif, dan berapa efisiensi budget jika voucher hanya ke top decile?
5. Kategori mana yang jadi whitespace per segmen?

**Bukan tujuan proyek:** klaim kausal final, prediksi churn production-grade, rekomendasi per SKU, atau klaim perilaku member Super Indo.

## Status

| Phase | Isi | Status |
|---|---|---|
| 0–1 | Panel `hh_week` + timeline campaign + kelayakan DiD | ✅ selesai, 5/5 gate |
| 2 | RFM + CLV 52 minggu + uji vs baseline naif | ✅ selesai — model kalah dari naif, ditulis apa adanya |
| 3 | Penetration gap per cohort + whitespace per member | ✅ selesai — berlabel `proxy dalam satu retailer` |
| 4 | Campaign DiD + event study + covariate balance | ✅ selesai — 14/30 lolos semua gate (dua placebo); backbone 8 & 13 signifikan BH (+9,8% / +15,2%); pooled $3,8–4,9/minggu; seleksi win-back terkondisikan |
| 5 | Segmentasi K-means + stabilitas ARI | ✅ selesai — 3 segmen efektif (k=5 core-fit + konsolidasi); ARI 0,646; churn threshold gap p95=5 mgg dari data |
| 6 | Uplift dua tahap (randomized + observational) | ✅ selesai — Stage 1 X5 randomized (decile-1 +12,0 pp ≈ 3× ATE); Stage 2 observational Dunnhumby: X-learner decile-1 **+$14,7/mgg [9,7; 20,2]** ≈ 2,3× ATE acak, gain@20% +$11,32/member vs RFM naif +$8,08, placebo lolos; T-learner tidak konsisten & decile tengah tidak monoton — diungkap; semua berlabel observational |
| 7 | Simulasi ROI voucher (3 skenario + sensitivitas) | ✅ selesai — pada 8 campaign held-out: **uplift top-2 decile $232 incremental spend per $1 voucher [124; 402]** (batas ketat) ≈ 2,6× blanket, 3,8× RFM top-2; urutan stabil di batas konservatif ($31,7 vs $12,3 vs $9,8) dan subset lolos-gate; margin 25% + batas konservatif → +$6,93 margin per $1, break-even ≤8,1%; margin = parameter 15/25/35%; biaya dari `COUPON_DISC` observasi; observational |
| 8 | Dashboard 4 halaman + playbook + slide re-run | sebagian — dashboard hal. 1–3 ✅ ([outputs/dashboard.html](outputs/dashboard.html), HTML self-contained); hal. 4 + playbook + slide + Excel setelah Phase 7 |

**Cut line MVP: tercapai (2026-10-25).** Phase 0–5 tuntas + dashboard halaman 1–3 + README final. Dashboard MVP: [outputs/dashboard.html](outputs/dashboard.html) — Member Overview, Segment Deep Dive, Campaign Lift; satu file self-contained (tanpa dependensi eksternal), flag reliabilitas campaign tampil beserta alasannya, dibangun deterministik dari parquet analisis dan dikunci suite test. Phase 6–7 (uplift, ROI) adalah lapisan pembeda berikutnya, lalu Phase 8 penuh (halaman 4 + playbook + slide + Excel + star schema).

## Asumsi utama

Setiap angka di proyek ini lahir di bawah asumsi berikut, dan labelnya menempel ke mana pun angka itu dibawa.

| Asumi | Konsekuensi |
|---|---|
| Treatment campaign dipilih retailer, bukan diacak | Semua lift/uplift berlabel `observational — di bawah asumsi unconfoundedness`; tidak pernah ditulis "voucher menyebabkan" |
| Margin per kategori tidak ada di data | Selalu parameter eksplisit + sensitivitas 15/25/35%, tidak pernah satu angka tunggal |
| Horizon data ±2 tahun | Selalu `CLV 52 minggu`, tidak pernah "lifetime value" |
| Hanya satu retailer | Yang dihitung penetration gap — `proxy dalam satu retailer`; total dompet lintas retailer tidak diklaim |
| Spend = net (`SALES_VALUE` + seluruh diskon) | Satu definisi untuk semua fase ([decision log](docs/decision-log.md)) |
| Retur tidak dibuang | Masuk agregasi net apa adanya; minggu terdampak ber-flag `has_return` |

## Limitation

Yang berikut belum terselesaikan dan sengaja tetap ditampilkan:

- Treatment tidak acak: estimasi efek hanya valid di bawah asumsi unconfoundedness — propensity, overlap, dan placebo test mengurangi risikonya, bukan menghapus.
- Tidak ada tanggal kirim per member (timing hanya level-campaign), tidak ada data margin, tidak ada transaksi non-member. Tiga hal ini tidak "diakali" dengan proxy tak berlabel.
- 74 pasang campaign beririsan waktunya: campaign 15 (161 hari) dikecualikan dari estimasi utama, 21/22 berwindow identik, 24 terpotong akhir data — control group tiap campaign dihitung mengecualikan campaign yang beririsan.
- Demografi hanya tersedia untuk 32% member → dipakai untuk profil segmen, bukan fitur model.
- Nominal USD era 2010-an; untuk transfer ke konteks Indonesia pakai rasio unitless.
- 2.500 member membuat uplift per decile berisik: CI selalu tampil, sel dengan n < 30 tidak dilaporkan.
- Efek campaign terverifikasi untuk 14 campaign; seleksi win-back membuat estimasi spesifikasi-sensitif (±30%) dan sisa bias mean-reversion tak bisa dikecualikan; campaign 18 ditandai (gagal placebo jauh meski signifikan); biaya voucher dua batas (atribusi ketat vs semua kupon), keduanya proxy.
- Segmen bersifat deskriptif dengan struktur lembut (silhouette rendah; bukti kelayakannya stabilitas ARI 0,646, bukan ketajaman klaster); share kategori komposisional tanpa transformasi log-ratio; aksi segmen adalah kandidat uji, bukan klaim kausal.
- Hasil uplift Stage 1 berasal dari panel eksternal (X5 RetailHero, ritel Rusia): validasi metode pada eksperimen acak, bukan angka bisnis Dunnhumby — targetnya biner (jumlah belanja naik), fiturnya metadata kartu + agregat histori, dan propensity konstan hanya sah karena penugasan memang diacak. Skill ranking moderat (0,6–0,7 pp per client) dan decile tengah X-learner tidak monoton; urutan di bawah decile atas tidak dibaca halus.
- Uplift Stage 2 bersifat observational (di bawah asumsi unconfoundedness): keunggulan X-learner atas RFM/random muncul di campaign akhir held-out, tetapi validasi silang sisi train hanya memberi margin tipis (+$0,04/member) — angka decile atas dibaca indikatif dengan CI; decile tengah tidak monoton; T-learner tidak konsisten antar subset; decile dengan n < 30 tidak diklaim.
- Simulasi ROI memakai konvensi horizon window (belanja incremental sepanjang window vs biaya total window) — berbeda dari kolom ekonomi fase DiD yang mingguan; relasinya eksak (× panjang window) dan terekonsiliasi 0,0% di 8 campaign. Batas atribusi ketat meledak untuk campaign TypeB kecil (daftar kupon tipis → biaya mendekati nol), sehingga kesimpulan dibaca dari urutan yang stabil di kedua batas; biaya per-targeted diekstrapolasi dari treated terobservasi; CI top-decile lebar. Angka ROI adalah latihan "seandainya efek kausal", bukan janji hasil — keputusan produksi memerlukan holdout eksperimen.

## Hasil sejauh ini

**Fondasi — panel & kelayakan campaign.** Panel 255.000 baris (2.500 member × 102 minggu) dibangun dengan menghindari jebakan yang paling sering menggagalkan analisis panel ritel: minggu retailer yang tidak seragam (minggu 1 hanya 5 hari, sehingga hari 224 jatuh di minggu 33 — bukan 32 hasil rumus naive), diskon yang tersimpan sebagai nilai negatif, dan 3,1% baris retur yang tetap masuk agregasi alih-alih dibuang diam-diam. Dari 30 campaign, 20 layak dianalisis efeknya — 3 backbone TypeA (1.076–1.133 treated, control pool 1.251–1.374) dan 17 menengah dengan CI lebar; 9 ditandai `tidak reliable` (terlalu kecil/terpotong), 1 dikecualikan.

**Nilai member — RFM & CLV 52 minggu.** RFM kuintil terbukti baseline yang kuat. BG/NBD + Gamma-Gamma justru kalah dari rata-rata historis tiap member saat diuji pada 26 minggu holdout — MAE 322 vs 308 (95% CI selisih +8,6 s.d. +20,5) — karena belanja grocery yang hampir periodik sudah menangkap hampir semua sinyal. Konsekuensinya dipegang konsisten: `clv_52w` hanya deskriptor berlabel asumsi, dan keputusan targeting tetap berdiri di atas RFM serta historis. Asumsi independensi Gamma-Gamma juga terbukti dilanggar (ρ = 0,43) dan menempel sebagai batasan pada `clv_52w`.

**Whitespace kategori — proxy satu retailer.** Membandingkan tiap member dengan cohort semirip (tercile spend × tercile ragam; 7 dari 9 sel grid terisi, n terkecil 127) menghasilkan top-10 kategori kandidat per member, terurut potensi spend; hampir separuh entrinya kategori yang belum pernah dibeli. Pola lintas member masuk akal — daging, bir, minuman, popok — dengan satu jebakan interpretasi yang ditandai: COUPON/MISC ITEMS adalah kategori operator dan selayaknya dikecualikan dari rekomendasi produk.

**Efek campaign voucher — observasional, dengan pelajaran identifikasi.** Investigasi mendalam menemukan bahwa targeting campaign ini bercorak **win-back**: member dipilih saat spend-nya sedang turun, lalu sebagian pemulihannya alami (mean reversion) — tanpa pengondisian, DiD membaca pemulihan itu sebagai efek campaign. Setelah trajektori dan level dip pra-campaign dikontrol, estimasi backbone turun ±30% dan reliabilitas dijaga **dua placebo** (jendela pre berdekatan + jendela jauh yang tak pernah disentuh model). Hasil akhir: 14 dari 20 campaign layak lolos semua gate; backbone yang bersih — campaign 8 (+9,8%) dan 13 (+15,2%) — signifikan setelah koreksi multiplicity BH; campaign 18 signifikan secara aritmetika tapi gagal placebo jauh dan ditandai. Efek rata-rata lintas campaign reliable **$3,83 [2,89–4,77] per minggu** (fixed-effect; random-effects $4,87, I² 66%). Ekonomi voucher dua batas: atribusi ketat memberi $3,3–$3,6 incremental spend per $1 (break-even margin 28–30%) — mendekati impas pada margin grocery tinggi; batas konservatif (semua kupon) tetap negatif.

**Segmentasi member — tiga wajah yang stabil.** K-means pada RFM (log) + ketergantungan promo + bauran 44 department, dengan pemilihan k berdasarkan stabilitas lintas seed dan lintas paruh periode (ARI 0,646) karena silhouette rendah di semua k — struktur segmen memang lembut, dan itu diakui. Tiga segmen efektif yang bertahan: **mesin pertumbuhan** (1.099 member; spend $4.386; churn 2,6%), **promo-dependent** (972; ketergantungan promo 0,23 tertinggi; churn 17%), dan **rentan hilang** (429; churn 39%; belanja terkecil) — masing-masing dengan satu aksi dari aturan tetap (aktivasi ulang / uji benefit non-diskon / dorong whitespace). Ambang churn datang dari distribusi panel (gap > p95 = 5 minggu), bukan angka bulat; top-1% spender ekstrem dikecualikan dari fitting dan ditugaskan ke centroid terdekat (terdokumentasi).

**Uplift dua tahap — mesin divalidasi dulu, lalu dipakai dengan jujur.** Tahap 1 pada eksperimen acak X5 (200 ribu member) membuktikan kurva uplift, decile + CI, dan T/X-learner bekerja: decile teratas T-learner +12,0 pp [9,3–14,5], sekitar 3× efek rata-rata. Tahap 2 membawa mesin yang sama ke panel Dunnhumby yang observasional: split mengikuti waktu campaign (12 awal → 8 akhir), fitur ketat pra-campaign, evaluasi berbobot overlap, dan placebo treatment-palsu yang lolos (CI memuat nol). Hasilnya: decile teratas X-learner **+$14,7/minggu [9,7–20,2]** (≈2,3× efek rata-rata $6,3) dan pada target 20% populasi menghasilkan +$11,3 per member — melampaui RFM naif (+$8,1) — dengan skor yang justru berkorelasi negatif dengan RFM (menemukan member responsif di margin penargetan, bukan yang belanjanya paling besar). Kekalahan & kelemahan ditulis apa adanya: T-learner tidak konsisten antar subset, decile tengah tidak monoton, dan margin di validasi silang sisi train tipis — angka dibaca indikatif, selalu dengan CI, dan selalu berlabel observational.

**Ekonomi voucher — dari skor ke keputusan anggaran.** Simulasi ROI mengulang delapan campaign akhir held-out dengan lima skenario targeting dan biaya kupon terobservasi dalam dua batas atribusi. Hasilnya satu kesimpulan yang stabil di kedua batas dan di subset identifikasi bersih: **targeting top-2 decile skor uplift menghasilkan $232 incremental spend per $1 voucher (batas ketat; CI 124–402) — 2,6× memberi voucher ke semua orang dan 3,8× RFM naif**; pada margin grocery 25% dengan batas biaya paling konservatif tetap positif (+$6,9 margin per $1; titik break-even margin 3–8%). RFM naif justru kalah dari blanket pada batas ketat — audiens high-spend-nya membakar kupon terbanyak dengan incremental terkecil. Semuanya observational, margin eksplisit sebagai parameter, dan rekomendasi operasionalnya bukan peluncuran penuh melainkan uji holdout 10% dengan aturan stop bila incremental margin per $1 turun di bawah 1.

## Data

Dunnhumby *The Complete Journey*: 8 CSV mentah di `data/` (terbesar `causal_data.csv`, 695 MB, opsional) — tidak pernah di-commit. Data eksternal Stage 1 uplift (X5 RetailHero, ±740 MB via scikit-uplift) di-cache di `data/external/` — juga tidak di-commit. Seluruh angka faktual di README ini dihitung ulang langsung dari CSV dan dikunci sebagai suite test di `tests/` (10 modul: panel, CLV, cohort, DiD, segment, dashboard, uplift randomized, X5, uplift observational, simulasi ROI); registri fakta terverifikasi ada di [AGENTS.md](AGENTS.md) §2, definisi metrik yang mengikat di [decision log](docs/decision-log.md). Turunan analisis hidup sebagai parquet di `data/processed/` (panel mingguan, timeline campaign, RFM/CLV, kategori, whitespace, benchmark cohort, hasil DiD + event study, segmen + ringkasan segmen, fitur client X5, skor uplift campaign akhir, biaya kupon per household, skenario ROI).

## Struktur repo

```
.
  data/               # CSV mentah (gitignored) + data/processed/*.parquet (gitignored)
  docs/               # decision log + rencana sprint (lokal, di-gitignore)
  notebooks/          # 01_panel … 08_roi_sim — ter-render; logika di src/
  src/                # features, clv, cohorts, did, segments, dashboard, x5, uplift_learners, uplift_eval, uplift_obs, simulate
  tests/              # assertion kualitas data & invariant hasil
  conftest.py         # session fixtures dari data asli (dibangun sekali per run)
  powerbi/            # Phase 8 penuh: .pbix + star schema export
  outputs/            # dashboard.html (MVP) — targeting_sample.xlsx, playbook.md menyusul
```

## Setup

Python 3.12, venv di `notebooks/.venv` (bukan root), dijalankan dari root repo (PowerShell):

```powershell
py -m venv notebooks\.venv
.\notebooks\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-modeling.txt   # CLV Bayes + uplift
pip install -r requirements-dev.txt        # pytest
python -m ipykernel install --user --name dunnhumby --display-name "Python (Dunnhumby 3.12)"
```

Cek sehat: `python -m pip check` → "No broken requirements found." Reproduksi persis: `requirements.lock.txt`. Test: `python -m pytest`.

## Konvensi pelaporan

Tiga label dipakai konsisten — `terverifikasi (data)`, `asumsi`, `tidak reliable` — dan angka selalu dengan konteks: `lift +4,2% (95% CI −0,8% s.d. +9,1%, n_treated=…, n_control=…)`. Aturan lengkap soal bahasa klaim, grafik, dan `reliability_flag`: [AGENTS.md](AGENTS.md) §8.

## Dokumen terkait

- [the-complete-journey.md](the-complete-journey.md) — spec; sumber kebenaran requirement.
- [AGENTS.md](AGENTS.md) — aturan kerja, fakta terverifikasi, jebakan data, quality gate per phase.
- [docs/decision-log.md](docs/decision-log.md) — keputusan formal yang mengikat semua fase.
