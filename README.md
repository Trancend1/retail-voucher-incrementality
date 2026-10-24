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
| 4 | Campaign DiD + event study + covariate balance | belum mulai |
| 5 | Segmentasi K-means + stabilitas ARI | belum mulai |
| 6 | Uplift dua tahap (randomized + observational) | belum mulai — akses data Stage 1 terverifikasi |
| 7 | Simulasi ROI voucher (3 skenario + sensitivitas) | belum mulai |
| 8 | Dashboard 4 halaman + playbook + slide re-run | belum mulai |

**Cut line MVP:** Phase 4–5 + dashboard halaman 1–3 + README; Phase 6–7 adalah lapisan pembeda setelah MVP stabil.

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

## Hasil sejauh ini

**Fondasi — panel & kelayakan campaign.** Panel 255.000 baris (2.500 member × 102 minggu) dibangun dengan menghindari jebakan yang paling sering menggagalkan analisis panel ritel: minggu retailer yang tidak seragam (minggu 1 hanya 5 hari, sehingga hari 224 jatuh di minggu 33 — bukan 32 hasil rumus naive), diskon yang tersimpan sebagai nilai negatif, dan 3,1% baris retur yang tetap masuk agregasi alih-alih dibuang diam-diam. Dari 30 campaign, 20 layak dianalisis efeknya — 3 backbone TypeA (1.076–1.133 treated, control pool 1.251–1.374) dan 17 menengah dengan CI lebar; 9 ditandai `tidak reliable` (terlalu kecil/terpotong), 1 dikecualikan.

**Nilai member — RFM & CLV 52 minggu.** RFM kuintil terbukti baseline yang kuat. BG/NBD + Gamma-Gamma justru kalah dari rata-rata historis tiap member saat diuji pada 26 minggu holdout — MAE 322 vs 308 (95% CI selisih +8,6 s.d. +20,5) — karena belanja grocery yang hampir periodik sudah menangkap hampir semua sinyal. Konsekuensinya dipegang konsisten: `clv_52w` hanya deskriptor berlabel asumsi, dan keputusan targeting tetap berdiri di atas RFM serta historis. Asumsi independensi Gamma-Gamma juga terbukti dilanggar (ρ = 0,43) dan menempel sebagai batasan pada `clv_52w`.

**Whitespace kategori — proxy satu retailer.** Membandingkan tiap member dengan cohort semirip (tercile spend × tercile ragam; 7 dari 9 sel grid terisi, n terkecil 127) menghasilkan top-10 kategori kandidat per member, terurut potensi spend; hampir separuh entrinya kategori yang belum pernah dibeli. Pola lintas member masuk akal — daging, bir, minuman, popok — dengan satu jebakan interpretasi yang ditandai: COUPON/MISC ITEMS adalah kategori operator dan selayaknya dikecualikan dari rekomendasi produk.

## Data

Dunnhumby *The Complete Journey*: 8 CSV mentah di `data/` (terbesar `causal_data.csv`, 695 MB, opsional) — tidak pernah di-commit. Seluruh angka faktual di README ini dihitung ulang langsung dari CSV dan dikunci sebagai 40 test di `tests/`; registri fakta terverifikasi ada di [AGENTS.md](AGENTS.md) §2, definisi metrik yang mengikat di [decision log](docs/decision-log.md). Turunan analisis hidup sebagai 7 parquet di `data/processed/` (panel mingguan, timeline campaign, RFM/CLV, kategori, whitespace, benchmark cohort).

## Struktur repo

```
.
  data/               # CSV mentah (gitignored) + data/processed/*.parquet (gitignored)
  docs/               # decision log + rencana sprint (lokal, di-gitignore)
  notebooks/          # 01_panel, 02_clv, 03_penetration_gap — ter-render; logika di src/
  src/                # features.py, clv.py, cohorts.py (did.py, uplift_eval.py, simulate.py menyusul)
  tests/              # assertion kualitas data & invariant hasil
  conftest.py         # session fixtures dari data asli (dibangun sekali per run)
  powerbi/ outputs/   # Phase 8
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
