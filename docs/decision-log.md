# Decision Log — retail-voucher-incrementality

Keputusan formal yang mengikat semua phase. Aturan main:

- Satu entri per keputusan, bernomor `DL-xxx`, tidak pernah diedit isinya setelah berlaku (koreksi typo boleh).
- Keputusan **tidak diubah diam-diam**. Kalau harus berubah: tulis entri baru yang menandai entri lama `superseded`, lengkap dengan alasan dan dampaknya ke angka yang sudah dipublikasikan.
- Aturan umbrella (R1–R12) ada di [`AGENTS.md`](../AGENTS.md); log ini mencatat keputusan spesifik di bawahnya. Spec ([`the-complete-journey.md`](../the-complete-journey.md)) tetap sumber kebenaran requirement.

| ID | Keputusan | Status | Tanggal |
|---|---|---|---|
| DL-001 | Definisi spend = `net_spend` (SALES_VALUE + seluruh diskon) | berlaku — sanity check numerik di Phase 1 | 2026-10-24 |
| DL-002 | Retur/baris negatif: agregasi net, tidak di-drop | berlaku — kuantifikasi di Phase 1 | 2026-10-24 |
| DL-003 | Dataset Stage 1 uplift: X5 utama + Hillstrom fallback; akses terverifikasi | berlaku | 2026-10-24 |
| DL-004 | `promo_share` = Σ(\|RETAIL_DISC\|+\|COUPON_DISC\|) / Σ `SALES_VALUE`, hanya baris `SALES_VALUE > 0` | berlaku — sanity check di L3 sprint-p1 | 2026-10-24 |
| DL-005 | `recency_weeks` = minggu sejak minggu aktif terakhir; `NA` pra-transaksi pertama | berlaku | 2026-10-24 |

---

## DL-001 — Definisi spend: `net_spend`

**Keputusan.** Spend di seluruh phase (panel, RFM/CLV, DiD, uplift, ROI simulasi) memakai satu definisi, dihitung per baris transaksi:

```
net_spend = SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC
```

Ketiga kolom diskon bertanda negatif di data mentah (AGENTS.md §3.1), jadi ini adalah nilai bersih setelah diskon kartu loyalty, kupon manufacturer, dan matching kupon retailer.

**Alasan.**

1. Rekomendasi eksplisit AGENTS.md §3.9: `SALES_VALUE` sendiri bukan "uang yang dibayar" tanpa kebijakan diskon; pilih satu definisi dan pakai konsisten.
2. `net` adalah basis yang benar untuk incremental margin di Phase 7: voucher cost (dari `COUPON_DISC` observed) dan spend outcome harus diukur pada basis yang sama.
3. Konsisten dengan DL-002 (retur): agregasi net otomatis net-of-returns.

**Konsekuensi.** Kolom dinamai `net_spend` di semua tabel processed. `promo_share` tetap dihitung dengan `abs()` pada diskon sesuai AGENTS.md §3.1.

**Validasi Phase 1 (wajib; mengonfirmasi, bukan mengubah definisi).** Laporkan di notebook 01 dan tempel hasilnya sebagai komentar di entri ini: distribusi `net_spend` (min / p50 / p99), jumlah & share baris `net_spend < 0`, dan perbandingan level agregat vs `SALES_VALUE`. Definisi hanya boleh berubah lewat entri baru + update README + catatan dampak.

---

## DL-002 — Kebijakan retur & baris negatif: agregasi net, tidak di-drop

**Keputusan.** Baris retur/adjustment **tidak di-drop**. Semua baris masuk agregasi dengan nilainya apa adanya; baris bernilai negatif mengurangi spend periode tersebut.

**Alasan.**

1. AGENTS.md §3.2 mewajibkan kebijakan eksplisit dan melarang drop diam-diam (±3,1% baris terdampak — drop mengubah level spend).
2. Konsisten dengan DL-001: net aggregation netral terhadap retur, tanpa keputusan baris-per-baris yang arbitrer.
3. Kebijakan alternatif (flag retur terpisah) tetap bisa ditambahkan **di atas** agregasi net bila analisis butuh (mis. kolom `has_return`), tanpa mengubah kebijakan ini.

**Kuantifikasi Phase 1 (wajib).** Jumlah & share baris `SALES_VALUE <= 0` (terverifikasi 2026-10-23: 18.850 baris) dan `net_spend < 0` (terverifikasi: 80.890 baris, ±3,1%) dilaporkan di notebook 01 + README.

---

## DL-003 — Dataset Stage 1 uplift: akses terverifikasi; X5 utama, Hillstrom fallback

**Keputusan.** Phase 6 Stage 1 (validasi pipeline uplift di data randomized) **tidak blocked**. Dataset utama: **X5 RetailHero** (punya histori pembelian → fitur pre-treatment, paling dekat konteks Stage 2 Dunnhumby). Fallback/benchmark sekunder: **Hillstrom** (email campaign, sangat kecil dan cepat). Keduanya sesuai preferensi spec §2 ("X5 … atau Hillstrom sebagai fallback").

**Bukti akses (verifikasi 2026-10-24, HTTP `200 OK` pada mirror S3 resmi scikit-uplift):**

| Dataset | File | Ukuran (gzip) | Loader |
|---|---|---|---|
| Hillstrom | `hillstorm_no_indices.csv.gz` | 0,4 MB | `sklift.datasets.fetch_hillstrom` |
| X5 RetailHero | `uplift_train.csv.gz` + `clients.csv.gz` | 1,1 MB + 7,3 MB | `sklift.datasets.fetch_x5` |
| X5 RetailHero | `purchases.csv.gz` | 638,9 MB | `sklift.datasets.fetch_x5` |

**Catatan operasional.**

- `purchases.csv.gz` X5 berukuran ±639 MB — setara `causal_data.csv` Dunnhumby. Unduh sekali, simpan di `data/external/` (sudah ter-cover `.gitignore` lewat `data/`), proses via DuckDB; jangan load penuh ke pandas.
- Semua dataset eksternal tidak pernah di-commit (R11).
- Loader tersedia di venv: `scikit-uplift 0.5.1` (`requirements-modeling.txt`).
- Alternatif quick-win: mulai prototipe pipeline Stage 1 dengan Hillstrom (0,4 MB) untuk memvalidasi kode, lalu jalankan penuh di X5.

---

## DL-004 — Definisi `promo_share` dan `gross_sales`

**Keputusan.** Di panel `hh_week`, `promo_share` dihitung dari agregat baris transaksi minggu tersebut:

```
promo_share = Σ(|RETAIL_DISC| + |COUPON_DISC|) / Σ(SALES_VALUE)
```

atas baris dengan `SALES_VALUE > 0` (penyebut valid). Baris `SALES_VALUE <= 0` (terverifikasi 18.850 baris) dikecualikan secara konsisten dari pembilang **dan** penyebut; share baris yang dikecualikan wajib dilaporkan. Minggu tanpa baris berpenyebut valid → `NA` (bukan 0).

**Alasan.**

1. `SALES_VALUE` diperlakukan sebagai nilai pre-diskon (`gross`) — konsisten dengan DL-001 yang mendefinisikan net = `SALES_VALUE` + seluruh diskon.
2. Pembilang mengikuti rumus spec Phase 0–1 + jebakan AGENTS.md §3.1 (diskon negatif → `abs()` wajib); `COUPON_MATCH_DISC` tidak masuk pembilang, sesuai rumus spec.
3. Rasio dari agregat (weighted) lebih stabil daripada rata-rata rasio per baris dan tidak distorsi baris bernilai kecil.

**Sanity check (wajib di L3 sprint-p1).** Distribusi `promo_share` (p50/p99) dilaporkan di notebook 01; p99 ≤ 1 diharapkan. Kalau terbukti dilanggar masif, definisi `gross_sales` diganti lewat entri baru yang men-supersede entri ini — tidak dipatch diam-diam.

---

## DL-005 — Definisi `recency` panel

**Keputusan.** `recency_weeks = week_no − last_active_week_no` per `(household_key, week_no)`: bernilai `0` pada minggu aktif; `NA` untuk minggu sebelum transaksi pertama household (belum ada referensi). Varian hari tidak dibangun di Phase 0–1.

**Alasan.**

1. Unit minggu konsisten dengan grain panel dan tahan terhadap batas minggu retailer yang tidak beraturan (AGENTS.md §3.3) — menghitung dalam hari menuntut asumsi posisi hari dalam minggu.
2. `NA` pra-transaksi-pertama menjaga household yang terlambat aktif tidak dibaca sebagai "sudah lama tidak belanja" padahal belum pernah belanja; deret nol itu sendiri menjadi fitur tenure.

**Konsekuensi.** Phase 5 (churn risk) boleh menurunkan varian hari dari data mentah bila dibutuhkan, tanpa mengubah definisi ini.
