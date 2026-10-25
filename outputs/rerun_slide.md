# Slide Re-run — Dengan Data My Super Indo

> Tujuan slide: menunjukkan apa yang bisa langsung dijalankan ulang dengan data member loyalty ritel Indonesia, dan data apa yang **harus disediakan** karena tidak ada di panel sumber. Semua definisi di bawah mengikat re-run; menggantinya diam-diam mengubah hasil.

## 1. Mapping data

| Dunnhumby (dipakai proyek ini) | Kebutuhan di My Super Indo | Status |
|---|---|---|
| `household_key` | `member_id` dari scan kartu loyalty | langsung mapping |
| `transaction_data` | transaksi POS terikat member (line-item) | langsung mapping |
| `COUPON_DISC` (per baris, negatif) | nilai diskon voucher/promo per baris transaksi | wajib per baris — bila hanya per basket, batas biaya "atribusi ketat" tidak bisa direplikasi |
| `RETAIL_DISC`, `COUPON_MATCH_DISC` | diskon kartu & matching retailer per baris | diperlukan untuk definisi `net_spend` |
| `WEEK_NO` (join, **bukan** turunan tanggal) | minggu retailer resmi (batas minggu tidak selalu 7 hari) | wajib ada sebagai kolom; derive dari tanggal = salah |
| `campaign_table` (siapa dikirimi campaign apa) | **send log campaign**: member × campaign × tanggal kirim + offer | tanggal kirim per member **tidak ada** di Dunnhumby — punya Anda berarti lebih baik |
| `campaign_desc` | kalender campaign (window mulai–selesai, tipe) | langsung mapping |
| `coupon_redempt` + `coupon` | log redemption + daftar produk per kupon/campaign | langsung mapping |
| `product` (hierarki DEPARTMENT → COMMODITY) | master produk dengan hierarki kategori | minimal 2 level |
| `hh_demographic` (hanya 32% member) | profil member (opsional, untuk profil segmen saja) | opsional |
| **(tidak ada)** | **margin/cost per kategori atau SKU** | **wajib disediakan** — di proyek ini margin hanya parameter asumsi 15/25/35% |
| **(tidak ada)** | **holdout flag acak 10%** untuk campaign berikutnya | **wajib dibuat sebelum kirim** — ini satu-satunya jalan keluar dari label observational |
| **(tidak ada)** | **transaksi non-member** | opsional; dipakai untuk cek coverage member vs total belanja toko |

## 2. Yang harus dijaga saat re-run (definisi terkunci)

1. **Spend = `net_spend`** = `SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC` (diskon tersimpan negatif; retur tidak dibuang, masuk agregasi net).
2. **Minggu = kolom minggu retailer**, bukan `floor(tanggal/7)` — di panel ini rumus naive meleset 27% baris.
3. **Control per campaign** = tidak ditarget campaign itu **dan** tidak ditarget campaign lain yang window-nya beririsan (74 pasang campaign Dunnhumby beririsan; abaikan ini → estimasi bias ke nol).
4. **Fitur model hanya pra-campaign** (`DAY < START_DAY`), termasuk trajektori & dip spend pra-campaign — pola targeting win-back ada di ritel mana pun.
5. **Biaya voucher dua batas**: atribusi ketat (kupon produk dalam daftar campaign) sebagai rasio utama; semua kupon sebagai batas konservatif.
6. **Ambang churn dari data** (gap inter-purchase > p95, di sini 5 minggu), bukan angka bulat; decile dengan n < 30 tidak dilaporkan.
7. **Split evaluasi mengikuti waktu campaign** + grouping member — jangan random split pada data observasional.
8. Horizon ROI = window campaign (incr × panjang window vs biaya total window).

## 3. Yang tidak bisa dijanjikan re-run

- Besaran angka (lift %, per-$1, CLV) milik panel ini dan nominal USD 2010-an — yang dibawa ke konteks lain adalah **rasio unitless & metode**, bukan angkanya; perilaku member Super Indo bukan klaim proyek ini.
- Klaim kausal — selama penargetan dipilih operator, semuanya tetap *observational — di bawah asumsi unconfoundedness*; hanya holdout 10% yang mengubah status itu.
