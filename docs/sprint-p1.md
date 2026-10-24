# Sprint P1 — Phase 0–1: Panel & Timeline Campaign

**Status:** disetujui user 2026-10-24 — siap eksekusi, **belum mulai**.
**Lingkup:** Phase 0–1 sesuai spec §"Phase 0-1" dan quality gate AGENTS.md §7. Tidak ada model di sprint ini — murni struktur, definisi, dan kualitas data.
**Dokumen terkait:** [spec](../the-complete-journey.md) (requirement) · [AGENTS.md](../AGENTS.md) (aturan R1–R12, fakta terverifikasi §2, jebakan §3) · [decision-log](decision-log.md) (DL-001..005).

---

## 1. Tujuan sprint

Menjawab dua pertanyaan yang menggantungkan semua fase di bawahnya:

1. **Apakah data cukup bersih dan terdefinisi untuk dipanelkan?** — definisi spend & retur terkonfirmasi numerik, jembatan hari→minggu benar, `promo_share` wajar.
2. **Campaign mana yang punya control group cukup untuk DiD (Phase 4) dan uplift (Phase 6)?** — daftar layak/tidak layak beserta alasan, berbasis `n_control_pool` per campaign.

Semua phase berikutnya (CLV, penetration gap, DiD, segmentasi, uplift, ROI) makan dari panel yang dibangun di sini.

## 2. Definition of done (quality gate AGENTS.md §7)

| # | Gate | Dituntaskan di langkah |
|---|---|---|
| 1 | Tabel timeline 30 campaign: `campaign_id, type, start_day, end_day, start_week, end_week, n_treated, overlaps_with, truncated_flag` | L1 (+L6 untuk `n_control_pool`) |
| 2 | Panel `hh_week` unik per `(household_key, week_no)` — assert; rentang minggu 1–102; 2.500 household | L3, dijaga test L7 |
| 3 | `promo_share` dengan `abs()`, tidak ada nilai negatif | L3 (DL-004), dijaga test L7 |
| 4 | Kebijakan retur/baris negatif tertulis + jumlah baris terdampak dilaporkan | DL-002 (sudah ada) + angka aktual L2 + README L9 |
| 5 | Daftar campaign layak/tidak layak untuk DiD + alasan | L6, tampil di notebook L8 |

## 3. Keputusan yang mengikat sprint ini

| ID | Keputusan | Status |
|---|---|---|
| DL-001 | `net_spend = SALES_VALUE + RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC` | berlaku; sanity check numerik di L2 |
| DL-002 | Retur/baris negatif tidak di-drop — agregasi net | berlaku; kuantifikasi di L2 |
| DL-004 | `promo_share = (\|RETAIL_DISC\| + \|COUPON_DISC\|) / SALES_VALUE`, penyebut dihitung hanya bila `SALES_VALUE > 0`; baris penyebut ≤ 0 (±18.850) dikecualikan konsisten dari pembilang & penyebut, share-nya wajib dilaporkan; sanity: p99 ≤ 1 | **dikunci di L0** (disetujui user 2026-10-24) |
| DL-005 | `recency_weeks = week_no − last_active_week_no`; 0 di minggu aktif; `NA` sebelum transaksi pertama household; varian hari tidak dibangun | **dikunci di L0** (disetujui user 2026-10-24) |

Catatan lingkup yang ikut dikunci: `QUANTITY` & `TRANS_TIME` tidak masuk panel (dicatat di data quality notes); panel **balanced** 2.500 × 102 dengan baris nol eksplisit (zero-activity = informasi tenure/recency, bukan data hilang).

## 4. Input & batas lingkup

**Dipakai:** `transaction_data.csv` (2.595.732 baris), `campaign_desc.csv` (30), `campaign_table.csv` (7.208), `product.csv` (92.353, untuk `category_breadth`), `coupon_redempt.csv` (2.318, hanya invariant test). Skema kolom terverifikasi 2026-10-24.

**Tidak dipakai sprint ini:** `causal_data.csv` (opsional, Phase 4+), `coupon.csv` (Phase 4/7), `hh_demographic.csv` (profil segmen Phase 5). Tidak ada tanggal kalender di data mana pun — waktu hanya `DAY` (1–711) dan `WEEK_NO` (1–102) relatif.

Angka checkpoint di bawah mengacu fakta terverifikasi AGENTS.md §2 (2026-10-23); kalau §2 diverifikasi ulang karena data berganti, angka checkpoint mengikuti SOT itu.

## 5. Artefak output

| Artefak | Isi |
|---|---|
| `src/features.py` | `build_day_week_bridge`, `build_campaign_timeline`, `spend_sanity`, `build_hh_week`, `build_hh_category`, `build_hh_campaign`, `compute_control_pool` |
| `tests/test_panel.py` | 6 grup assertion (lihat §10) |
| `notebooks/01_panel.ipynb` | presentasi ±14 sel, ter-render end-to-end (R11: notebook ter-render di-commit) |
| `data/processed/campaign_timeline.parquet` | 30 campaign + `n_control_pool` (calon `dim_campaign`) — gitignored |
| `data/processed/hh_week.parquet` | 255.000 baris balanced — gitignored |
| `data/processed/hh_category.parquet` | long hh × commodity — gitignored |
| `data/processed/hh_campaign.parquet` | peta treatment tipis 7.208 baris — gitignored |
| README + decision-log + AGENTS.md §9 | status, quality notes, limitation, DL-004/005 + komentar konfirmasi DL-001/002 |

## 6. Urutan eksekusi

```
L0 kunci DL ─> L1 timeline ─> L2 sanity ─> L3 hh_week ─> L4 hh_category
   ─> L5 hh_campaign ─> L6 control pool ─> L7 pytest ─> L8 notebook ─> L9 docs + commit
```

**L0 — Kunci keputusan (docs).** Tulis DL-004 + DL-005 ke decision log. Selesai jika kedua entri masuk berstatus berlaku.

**L1 — Jembatan hari→minggu + timeline 30 campaign** (`src/features.py` + test).
`build_day_week_bridge()`: min/max `DAY` per `WEEK_NO`, assert 102 minggu kontinu. `build_campaign_timeline()`: kolom gate lengkap; `start/end_week` **lewat jembatan** (bukan `floor((DAY-1)/7)+1` — hanya cocok ±73% baris, AGENTS §3.3); overlap = irisan interval `START/END_DAY`; `truncated_flag` = `END_DAY > 711`.

**L2 — Sanity spend** (`src/features.py` + test ringan).
`spend_sanity()` via DuckDB: distribusi `net` per baris (min/p50/p99), jumlah `SALES_VALUE <= 0`, jumlah `net < 0`. Hasil ditempel sebagai komentar konfirmasi di DL-001 & DL-002 → bahan README (menutup gate #4).

**L3 — Panel `hh_week`** (`src/features.py` + test).
Agregasi DuckDB (`read_csv_auto` + pushdown; pandas hanya untuk agregat): `net_spend`, `n_baskets`, `retail_disc_sum`/`coupon_disc_sum`/`coupon_match_disc_sum`, `category_breadth` (join `product.csv`), `has_return`. Finalisasi pandas: balanced 255.000 baris, `has_purchase`, `promo_share` (guard DL-004), `recency_weeks` (DL-005).

**L4 — `hh_category` + coverage join** (`src/features.py`).
Long `(household_key, commodity_desc)` → `net_spend`, `n_weeks_active` (bahan Phase 3/5). Hitung coverage join `product.csv`; kalau < 100%, breadth undercount dicatat sebagai limitation (tidak dipaksakan bersih).

**L5 — `hh_campaign` tipis** (`src/features.py`).
`(household_key, campaign)` + kolom window dari timeline (type, start/end week, durasi). Perancangan control/matching **tidak** ikut — milik Phase 4 `src/did.py`.

**L6 — Control pool per campaign + daftar kelayakan final** (`src/features.py`).
`compute_control_pool()`: dari 2.500 hh buang treated campaign itu **dan** treated semua campaign yang window-nya beririsan → kolom `n_control_pool` di timeline. Daftar kelayakan: backbone 8/13/18; menengah (17 campaign) dengan CI; <100 treated → `tidak reliable` (R7); 15 dikeluarkan dari estimasi utama; 24 truncated; `n_control_pool < 30` → flag otomatis (R8).

**L7 — Test suite penuh hijau.** `python -m pytest` dari venv `notebooks/.venv`, semua hijau dari keadaan bersih.

**L8 — Notebook `01_panel.ipynb`** (kernel *Python (Dunnhumby 3.12)*, run end-to-end kernel bersih).
Kerangka sel: (1) judul + link spec/AGENTS/DL, (2) load & assertion awal, (3) jembatan hari→minggu, (4) tabel timeline + plot gantt campaign, (5) sanity spend & retur, (6–7) build panel, (8) EDA spend mingguan & hh aktif, (9) distribusi `promo_share`, (10) distribusi `recency`/tenure, (11) coverage join product, (12) control pool + tabel kelayakan, (13) manifest artefak, (14) limitation notes.

**L9 — Docs final + commit + push.** README: status sprint, data quality notes (retur, coverage, `promo_share`), limitation baru bila ada. AGENTS.md §9 diperbarui (kode analisis mulai ada). Commit sesuai §8.

## 7. Checkpoint verifikasi per langkah

| Langkah | Kriteria lolos | Kalau gagal |
|---|---|---|
| L1 | 30 baris; 74 pasang overlap; 15 ↔ 12 campaign; 21≡22 (624–656); hanya 24 truncated; `n_treated` 12–1.133 | **Stop total** — data kemungkinan berganti; verifikasi ulang AGENTS §2 dulu |
| L2 | ≈18.850 baris `SALES_VALUE <= 0`; ≈80.890 baris `net < 0` | **Stop total** — sama seperti L1 |
| L3 | 255.000 baris unik; `promo_share ≥ 0` semua; p99 `promo_share` ≤ 1 | p99 > 1 masif → jangan lanjut; evaluasi `gross_sales` lewat entri DL baru (supersede DL-004), laporkan |
| L4 | Coverage join dilaporkan | < 100% → catat limitation, tetap lanjut |
| L6 | 30 campaign terklasifikasi dengan alasan | `n_control_pool` kecil = **temuan utama sprint**, flag `tidak reliable` (R7) — bukan kegagalan |
| L7 | pytest hijau semua | Perbaiki sebelum lanjut; tidak ada test yang di-skip diam-diam |
| L8 | Notebook jalan penuh dari kernel bersih | Ulangi; angka kunci (n, lift-preview, CI) tertempel di ringkasan |

## 8. Rencana commit

1. `docs: kunci DL-004 (promo_share/gross_sales) + DL-005 (recency) — pra-eksekusi Phase 0-1` (L0)
2. `feat(panel): jembatan hari-minggu + timeline 30 campaign + sanity spend (src, tests)` (L1–L2)
3. `feat(panel): hh_week balanced + hh_category + hh_campaign (src, tests)` (L3–L5)
4. `feat(panel): control pool per campaign + daftar kelayakan DiD` (L6)
5. `docs: notebook 01_panel.ipynb ter-render end-to-end` (L8)
6. `docs: README status + limitation, AGENTS.md §9` (L9)

Parquet `data/processed/` tidak di-commit (gitignored, R11).

## 9. Kebijakan berhenti (jangan paksa)

- Angka sanity tidak cocok §2 → stop, verifikasi ulang data.
- Definisi `gross_sales` terbukti bermasalah → lewat entri DL baru + update README + catat dampak; tidak dipatch diam-diam.
- Control pool campaign besar lebih tipis dari dugaan → temuan sah; campaign ditandai, cakupan Phase 4 disesuaikan dan **dilaporkan** (AGENTS §6.7) — estimasi tidak dipaksakan.
- Model/estimasi apapun di luar lingkup panel = di luar sprint ini.

## 10. Test plan (`tests/test_panel.py`)

1. `hh_week` unik per `(household_key, week_no)`; 2.500 household; minggu 1–102 kontinu.
2. `promo_share ≥ 0` semua baris; tidak NaN pada baris berpenyebut valid.
3. `net_spend` tanpa NaN; jumlah baris retur konsisten dengan angka DL-002 (L2).
4. Timeline 30 baris; `overlaps_with` simetris (A∈B ⇔ B∈A); `truncated_flag` hanya `END_DAY > 711`.
5. Invariant `coupon_redempt`: 100% redemption jatuh dalam window campaign-nya.
6. Coverage join `product.csv` dihitung dan dilaporkan (bukan assert hard 100%).

## 11. Risiko yang sudah diantisipasi

| Risiko | Mitigasi |
|---|---|
| Control pool tipis akibat 74 pasang overlap | Itu pertanyaan inti sprint ini (L6); flag R7, laporan jujur |
| `gross_sales` ambigu setelah cek distribusi | Mekanisme supersede DL-004 (L3 checkpoint) |
| Coverage join `product.csv` < 100% | Limitation eksplisit breadth (L4) |
| Household terlambat aktif (deret nol panjang) | Fitur tenure gratis; konfirmasi visual di EDA (L8) |
| Memory: 142 MB transaksi | DuckDB pushdown; pandas hanya untuk agregat; `causal_data.csv` tidak disentuh |
