# TESTING - BOSS SF

**411 test, semua lulus.**

```powershell
python -m pytest tests -q
```

Hasil terakhir: `411 passed, 22 warnings in 38s`
(Python 3.9.13, pytest, 2026-10-17).

---

## 1. Cara kerja

[`tests/conftest.py`](../tests/conftest.py):

| Aspek | Perilaku |
|---|---|
| Database | **Salinan** `servisku.db` di direktori temp. DB produksi tidak pernah ditulis test. |
| Backend | Disalin ke temp dan diimpor dari sana |
| App | `TestClient` FastAPI |
| Isolasi | Rollback per test, tapi **API call tetap commit** ke salinan |

⚠️ Karena API call melakukan commit, **sandbox DB dibagi antar test dalam satu
file**. Test yang menghapus baris bisa memengaruhi test berikutnya. Kalau
menemukan 404 "Not Found" yang aneh, cek dulu apakah barisnya memang masih
ada.

22 warning itu `LegacyAPIWarning` SQLAlchemy 1.x untuk `Query.get()`. Bukan
error.

---

## 2. Test domain utama

### Aturan terkunci (OD-LOCK)

| File | Cakupan |
|---|---|
| `test_od_lock.py` | Lock dasar: pengakuan pendapatan, periode, DP |
| `test_od_lock_06_beban.py` | Pembayaran Beban, Kas Aset, Hutang Beban |

### Keuangan

| File | Cakupan |
|---|---|
| `test_finance_core.py` | Rumus omzet/modal/laba |
| `test_aturan_modal_omzet.py` | Pemisahan modal dari harga |
| `test_hutang_laba_kotor.py` | Dasar hutang beban |
| `test_laba_kotor_murni.py` | Laba kotor tanpa kontaminasi |
| `test_tanpa_modal.py`, `test_modal_kosong_peringatan.py` | Jalur `tanpa_modal` |
| `test_dp_kelebihan_bayar.py` | DP melebihi estimasi ditolak |
| `test_money_ledger.py` | Presisi fixed-point |

### Kas & periode

| File | Cakupan |
|---|---|
| `test_periode_isolasi.py` | Larangan mencampur periode |
| `test_periode_kas.py` | Identitas periode |
| `test_period_key_unik.py` | `period_key` uniqueness |
| `test_mutasi_kas.py` | Mutasi kas consistency |
| `test_cash_model_v4.py` | Model 2 layer |
| `test_cash_realisasi.py` | Realisasi kas |
| `test_cash_distribution.py` | Distribusi kas |
| `test_fin_mirror.py`, `test_fin_mirror7_tutupkas.py` | Mirror logika financial |
| `test_backup_prune.py` | Mekanisme prune backup |

### Distribusi

| File | Cakupan |
|---|---|
| `test_distribusi_jumlah_alokasi.py` | Jumlah alokasi 10/30/30/30 |
| `test_distribusi_topup.py` | Top-up & top-down |

### DP / Titipan

| File | Cakupan |
|---|---|
| `test_titipan_dp.py` | Perhitungan titipan |
| `test_titipan_dp_kosong.py` | Kasus titipan kosong |
| `test_dp_tidak_di_kondisi_kas.py` | DP tidak masuk kondisi kas |

### Permission & role

| File | Cakupan |
|---|---|
| `test_permission_authority_matrix.py` | 28 aksi x 7 role, alias, anti-eskalasi |
| `test_7_role_authority.py` | Matriks per role |
| `test_role_read_only.py` | PENGELOLA/INVESTOR read-only, audit endpoint tulis |
| `test_role_investor.py` | Role investor |
| `test_rbac_putaran2.py` | Anti-eskalasi, kelola akun |
| `test_akun_nonaktifkan.py` | Nonaktifkan bukan hapus |
| `test_sidebar_role.py` | Menu sesuai role |
| `test_ubah_passcode.py` | Ganti passcode |

### Garansi & refund

| File | Cakupan |
|---|---|
| `test_garansi_detail.py` | Detail klaim garansi |
| `test_dp_tidak_di_kondisi_kas.py` | Isolasi DP dari kas |

### Operasional

| File | Cakupan |
|---|---|
| `test_domains.py` | Frontend fail-closed |
| `test_migration_idempotent.py` | Migrasi aman dijalankan berulang |
| `test_dropdown_teknisi.py` | Dropdown teknisi |
| `test_notifikasi_badge.py` | Badge notifikasi |
| `test_notifikasi_laporan_kas.py` | Notifikasi laporan kas |
| `test_frontend_fail_closed.py` | UI fail-closed |
| `test_p215_blocker_fix.py` | Perbaikan blocker |

---

## 3. Cakupan yang lemah

[FAKTA] Bagian berikut **tidak punya test khusus**:

| Area | Situasi |
|---|---|
| **Frontend** | Hampir nol test. Yang ada hanya cek statis fail-closed. Tidak ada test DOM/interaksi. |
| **Router `dashboard`, `laporan`** | Tidak ada test langsung.tidak langsung tertutup test keuangan. |
| **`migrate_sqlite_to_postgres.py`** | Tidak ada test. Script-nya sendiri tidak bisa jalan. |
| **Backup** | Hanya test prune. Tidak ada test integrasi backup DB. |
| **Idempotency** | Tidak ada test untuk kasus `IN_PROGRESS` yang menggantung. |
| **Role `INVESTOR`, `ADMIN_SPAREPART`** | Tidak ada akun ini di DB produksi, jadi jalur wewenang mereka belum pernah dieksekusi nyata. |
| **`ROLE_CONFIG`, `AUDIT_READ`** | Action ada di matriks, nol endpoint. |
| **Pengiriman notifikasi** | Tidak ada kode pengiriman, jadi tidak ada yang bisa dites. |

---

## 4. Test yang wajib dijaga

Test ini mengunci aturan bisnis. Kalau gagal, **jangan longgarkan assertion** -
cari akar masalahnya.

| Test | Mengunci |
|---|---|
| `test_od_lock.py` | Pengakuan pendapatan & status final |
| `test_od_lock_06_beban.py` | Beban dibayar sekali |
| `test_periode_isolasi.py` | Larangan mencampur periode |
| `test_permission_authority_matrix.py` | Matriks wewenang tunggal |
| `test_role_read_only.py` | PENGELOLA/INVESTOR read-only |
| `test_migration_idempotent.py` | Migrasi aman berulang |

---

## 5. Menulis test baru

Gunakan test sebagai **pernyataan aturan**, bukan sekadar cek error 500.

```python
def test_dp_tidak_boleh_melebihi_estimasi(client, db):
    """Aturan: DP adalah titipan, tidak boleh melebihi estimasi."""
    # siapkan order dengan estimasi tertentu
    r = client.post("/api/payments", headers=hdr, json={
        "service_order_id": order.id, "kind": "DP", "amount": 999999999,
    })
    assert r.status_code in (400, 422)
```

Docstring harus menyebut **aturan bisnis** yang diuji, supaya test tetap bermakna
walau implementasi berubah.

Untuk perubahan berisiko, tulis test **yang gagal dulu**, buktikan merah, baru
perbaiki.

---

## 6. Validasi lain

```powershell
python -m compileall -q backend            # kompilasi Python
node --check frontend\script.js           # sintaks JS (perlu Node.js)
git status --short
Select-String -Path backend\**\*.py -Pattern 'require_admin'   # harus kosong
```

---

## 7. Menjalankan sebagian

```powershell
# satu file
python -m pytest tests\test_od_lock.py -q

# satu test
python -m pytest tests\test_od_lock.py::test_nama -q

# dengan nama pola
python -m pytest tests -q -k "beban"

# tanpa cache, verbose
python -m pytest tests -q --no-header -v
```
