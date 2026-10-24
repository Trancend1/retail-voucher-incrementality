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
