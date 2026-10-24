# Retail Voucher Incrementality — Dari RFM ke Voucher Efficiency

**Hook:** *"RFM bilang siapa yang belanja banyak. Uplift bilang siapa yang berubah karena voucher. Dan saya tunjukkan kapan angka uplift itu layak dipercaya."*

Analisis efektivitas voucher/campaign retail di panel **Dunnhumby Complete Journey** (±2.500 household, 102 minggu), diposisikan sebagai **methodology transfer** ke use case member loyalty ritel Indonesia (ala My Super Indo) — bukan klaim tentang perilaku pelanggan Super Indo.

Yang dijual proyek ini bukan angka uplift-nya, tapi **kejujuran soal kapan angka itu layak dipercaya**. Setiap output harus bisa menjawab: *di bawah asumsi apa angka ini valid, dan apa buktinya?*

> **Status (per 2026-10-24): kesiapan repo selesai, analisis belum mulai.** Belum ada angka di repo ini yang berasal dari model. Semua angka faktual di bawah adalah statistik data mentah yang diverifikasi langsung dari CSV pada 2026-10-23.

## Pertanyaan bisnis

1. Siapa member bernilai tinggi, dan siapa yang mulai turun?
2. Seberapa promo-dependent tiap segmen?
3. Campaign mana yang beneran menaikkan spend, dan berapa incremental margin per $1 voucher?
4. Household mana yang paling responsif, dan berapa efisiensi budget kalau voucher hanya ke top decile?
5. Kategori mana yang jadi whitespace per segmen?

**Non-goal:** klaim kausal final, prediksi churn production-grade, rekomendasi per SKU, klaim perilaku member Super Indo.

## Asumsi utama (berlaku untuk semua angka yang akan dihasilkan)

| Asumsi | Konsekuensi pada pelaporan |
|---|---|
| Treatment campaign **tidak randomized** (retailer yang memilih target) | Semua lift/uplift dilabeli `observational — di bawah asumsi unconfoundedness`; tidak pernah ditulis "voucher menyebabkan" |
| Margin per kategori **tidak ada di data** | Selalu tampil sebagai parameter eksplisit + sensitivitas 15/25/35%, tidak pernah satu angka hardcode |
| Horizon CLV pendek (data ±2 tahun) | Selalu ditulis `CLV 52 minggu`, bukan "lifetime value" |
| Hanya satu retailer | Yang dihitung adalah **category penetration gap**, berlabel `proxy dalam satu retailer`; frasa "share of wallet" tidak dipakai |
| Definisi spend = **net** (`SALES_VALUE` + seluruh diskon) | Satu definisi konsisten di semua phase — keputusan formal [DL-001](docs/decision-log.md) |
| Retur/baris negatif **tidak di-drop**, masuk agregasi net | Kebijakan eksplisit [DL-002](docs/decision-log.md), jumlah baris terdampak dilaporkan di Phase 1 |

## Limitation (belum terselesaikan — akan tetap berada di sini)

- Treatment dipilih retailer, bukan acak; estimasi efek valid hanya di bawah asumsi unconfoundedness (propensity, overlap, placebo test dipakai untuk mengurangi — bukan menghapus — risiko ini).
- `campaign_table` tidak punya tanggal kirim per household; timing treatment hanya level-campaign. Efek per household tidak bisa di-align ke tanggal terima.
- 74 pasang campaign beririsan waktunya; campaign `15` (161 hari, menelan ±23 minggu) dikeluarkan dari estimasi utama, `21`/`22` punya window identik, `24` terpotong akhir data. Control group didefinisikan per campaign dan mengeksklusi campaign overlap.
- Tidak ada data margin, tidak ada share of wallet total, tidak ada transaksi non-member. Tiga hal ini tidak "diakali" dengan proxy yang tidak dilabeli.
- Demografi hanya tersedia untuk 32% household → dipakai untuk profil segmen, bukan fitur wajib.
- Nominal USD era 2010-an; untuk slide transfer ke konteks Indonesia cukup pakai rasio unitless, sebut konversi & tahun bila memakai nominal.
- Sampel ±2.500 household: uplift per decile berisik; CI selalu ditampilkan, sel/decile/segmen dengan n < 30 tidak diklaim.

## Data (fakta terverifikasi 2026-10-23)

Sumber: Dunnhumby *The Complete Journey*. Angka diperiksa langsung dari CSV di `data/` — kalau data diganti, verifikasi ulang.

| Tabel | Baris | Catatan kunci |
|---|---|---|
| `transaction_data.csv` | 2.595.732 | 2.500 household, 276.484 basket, `WEEK_NO` 1–102, `DAY` 1–711 |
| `campaign_desc.csv` | 30 campaign | `START_DAY` 224–659; tipe A/B/C |
| `campaign_table.csv` | 7.208 | 1.584 household unik; treated per campaign 12–1.133 |
| `coupon_redempt.csv` | 2.318 | 434 household; 100% redemption di dalam window campaign |
| `coupon.csv` | 124.548 | Peta `COUPON_UPC → PRODUCT_ID` per campaign |
| `hh_demographic.csv` | 801 | Hanya 32% household |
| `product.csv` | 92.353 | 44 department, 308 commodity |
| `causal_data.csv` | 695 MB | Display/mailer; opsional, diproses via DuckDB |

Raw data tidak pernah di-commit (R11); turunan besar hidup di `data/processed/*.parquet` (juga di-gitignore).

Detail lengkap (skala treatment per campaign, jebakan data, fakta verifikasi): [`AGENTS.md`](AGENTS.md) §2–3.

## Milestone & status

| Phase | Isi | Status |
|---|---|---|
| 0–1 | EDA + panel `hh_week` + timeline campaign | belum mulai |
| 2 | RFM + BG/NBD + Gamma-Gamma + diagnostic vs baseline naif | belum mulai |
| 3 | Category penetration gap per cohort | belum mulai |
| 4 | Campaign DiD + event study + balance | belum mulai |
| 5 | Segmentasi K-means + stabilitas ARI | belum mulai |
| 6 | Uplift: Stage 1 (randomized, X5/Hillstrom) + Stage 2 (observational) | belum mulai — akses data Stage 1 [terverifikasi](docs/decision-log.md#dl-003) |
| 7 | Simulasi ROI voucher (3 skenario + sensitivitas) | belum mulai |
| 8 | Dashboard Power BI + playbook + slide re-run + Excel targeting | belum mulai |

**Cut line MVP:** Phase 0–5 + dashboard halaman 1–3 + README. Phase 6–7 adalah lapisan pembeda, dikerjakan setelah MVP stabil. Quality gate per phase: [`AGENTS.md`](AGENTS.md) §7.

## Struktur repo

```
.
  data/                 # CSV mentah (gitignored) + data/processed/*.parquet (gitignored)
  docs/
    decision-log.md     # keputusan formal: DL-001 spend, DL-002 retur, DL-003 dataset Stage 1
  notebooks/            # 01_panel ... 08_roi_sim (dibuat per phase) + .venv (gitignored)
  src/                  # logic yang dipakai notebook (dibuat per phase)
  tests/                # pytest — assertion kualitas data & unit src/ (ditulis per phase)
  powerbi/              # .pbix + export script (Phase 8)
  outputs/              # targeting_sample.xlsx, playbook.md, reuse_slide
  the-complete-journey.md   # SPEC — sumber kebenaran requirement
  AGENTS.md             # aturan operasional, fakta data terverifikasi, jebakan, quality gate
  requirements*.txt     # inti / modeling / dev (pytest) / lock
```

## Setup

Python 3.12.7, venv di `notebooks/.venv` (bukan root). Dari root repo (PowerShell):

```powershell
py -m venv notebooks\.venv
.\notebooks\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-modeling.txt   # opsional: CLV Bayes + uplift
pip install -r requirements-dev.txt        # opsional: pytest
python -m ipykernel install --user --name dunnhumby --display-name "Python (Dunnhumby 3.12)"
```

Cek cepat: `python -m pip check` → "No broken requirements found." Reproduksi persis: `requirements.lock.txt`.

## Dokumen terkait

- [`the-complete-journey.md`](the-complete-journey.md) — spec; sumber kebenaran requirement. Kalau dokumen lain bertentangan dengan spec, spec menang.
- [`AGENTS.md`](AGENTS.md) — aturan kerja bernomor (R1–R12), fakta data terverifikasi, jebakan data, definition of done per phase.
- [`docs/decision-log.md`](docs/decision-log.md) — keputusan formal yang mengikat semua phase.

## Konvensi pelaporan

Tiga label status dipakai konsisten: `terverifikasi (data)`, `asumsi`, `tidak reliable` — angka selalu dilaporkan dengan CI dan `n`, `reliability_flag` campaign tidak disembunyikan. Aturan lengkap: [`AGENTS.md`](AGENTS.md) §8.
