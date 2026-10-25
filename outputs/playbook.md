# Playbook Targeting Voucher — 1 Halaman

> Basis angka: panel Dunnhumby Complete Journey (2.500 member, 102 minggu). Semua efek **observational — di bawah asumsi unconfoundedness**; angka membawa CI dan tidak boleh dibaca sebagai janji hasil. Margin adalah **parameter asumsi** (15/25/35%), bukan data.

## 1. Aturan targeting

1. **Prioritas utama: top-2 decile skor uplift** (X-learner), bukan blanket dan bukan RFM. Bukti: pada 8 campaign akhir held-out, top-2 decile menghasilkan **$232 incremental spend per $1 voucher (95% CI 124–402; batas atribusi ketat)** vs blanket $90 dan RFM top-2 $62; pada batas konservatif urutan sama ($31,7 vs $12,3 vs $9,8). **RFM tidak dipakai sebagai proxy respons** — audiens high-spend justru membakar kupon terbanyak dengan incremental terkecil.
2. Decile dihitung **dalam campaign** (1 = tertinggi); list siap pakai per member ada di `outputs/targeting_sample.xlsx` (kolom `include_flag`, tingkat 20% populasi ter-skorku).
3. Jangan menarget di luar top-4 decile tanpa alasan segmen (efek decile 5–10 tidak terbedakan dari nol pada data ini).

## 2. Offer matrix per segmen

| Segmen | Ukuran | Karakter | Offer |
|---|---|---|---|
| **Rentan hilang** | 429 · churn 39% | gap belanja > p95 (5 minggu) | **Aktivasi ulang**: kontak win-back + voucher kecil pada kategori whitespace-nya |
| **Promo-dependent** | 972 · promo 0,23 · churn 17% | responsif diskon, margin rapuh | **Benefit non-diskon** (poin/pengalaman) untuk decile atas — **jangan menambah diskon** |
| **Mesin pertumbuhan** | 1.099 · spend $4.386 · churn 2,6% | stabil, bernilai tinggi | **Whitespace push** (BEEF dll.) tanpa insentif diskon tambahan; voucher hanya pada top-2 decile |
| Top-2 decile (semua segmen) | 20% populasi | responsif skor uplift | Voucher kategori whitespace, patuh cap |

## 3. Guardrail budget

- **Cap voucher**: maksimal **$18 per member per window campaign** (p90 biaya kupon terobservasi per member treated pada campaign held-out — data-anchored, lihat sheet asumsi xlsx).
- **Stop rule**: hentikan & evaluasi bila **incremental margin per $1 voucher < 1** — pada margin 25% (baseline) itu terjadi bila incremental spend per $1 turun di bawah $8 (≈ level blanket batas konservatif).
- Ekonomi acuan (margin 25%, batas konservatif): top-2 decile **+$6,9 margin per $1** (break-even margin 3,2%); blanket +$2,1 (break-even 8,1%). Angka batas ketat jauh lebih tinggi — baca sebagai rentang atribusi, bukan angka tunggal.

## 4. Desain holdout (wajib sebelum eksekusi)

- Sisihkan **10% member acak** (stratified per segmen) sebagai holdout — **tidak menerima treatment**; flag disimpan permanen.
- Setelah window: bandingkan spend holdout vs target (uplift aktual) → kalibrasi skor; holdout adalah satu-satunya jawaban atas label observational di atas.
- Ukuran minimum per sel pelaporan: n ≥ 30; decile dengan n < 30 tidak diklaim.

## 5. Cadence evaluasi

| Ritme | Aktivitas |
|---|---|
| Per campaign (pasca-window) | placebo pre-trend (dalam + jauh), covariate balance (|SMD| < 0,1), uplift per decile + CI, realisasi per-$1 vs simulasi |
| Kuartalan | re-fit skor uplift (split waktu campaign + grouping household), refresh list targeting & segmen |
| Tahunan | review ulang definisi (net spend, ambang churn p95, batas biaya) dan nilai cap/stop-rule |

## 6. Larangan & label

- Frasa terlarang (dompet lintas ritel) tidak dipakai di output mana pun; whitespace kategori = **proxy dalam satu retailer**.
- Tidak ada klaim "voucher menyebabkan" tanpa kualifikasi observational; tidak ada angka margin tunggal.
- CLV selalu `CLV 52 minggu` dan berstatus deskriptor (model kalah dari baseline naif).
