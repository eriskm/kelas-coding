# -*- coding: utf-8 -*-
"""P2-11 — Modul Hutang Beban (TERPISAH dari Buku Kas — SSOT-8, Q8, Q18).

Alur yang dijaga (LOCKED):
    Defisit terhadap Beban periode
        → Kas Aset menutup (sepenuhnya yang bisa)
            → jika masih kurang → Hutang Beban (carry forward sampai diselesaikan)

Aturan implementasi (ID-06 — structure detail, bukan business rule baru):
- Modul & tabel TERPISAH dari Buku Kas. Tidak ada baris hutang di `kas_entries`
  sebagai Buku Kas: efek uang memakai `cash.catat_mutasi(layer=KAS_ASET)` yang
  P2-06 memang tempatkan di layer terpisah.
- **Kas Perputaran (Laci) tidak pernah disentuh** (SSOT-7).
- **Formula Financial Core tidak diubah** — `compute_finance_core` hanya dibaca,
  tidak dimodifikasi. Laba Bersih tetap negatif bila defisit.
- **Tidak membuat baris `expenses`** → tidak ada double-count expense (SSOT-4).
- Hutang **tidak pernah menjadi Omzet/Laba**.
- Idempotent per periode (satu proses defisit = satu baris `expense_debt_periods`).
- Tanpa `commit` di modul: pemanggil (router) yang mengatur transaksi.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

import cash
import finance
import journal
from money import ZERO, quantize, to_decimal

TIPE_HUTANG = "HUTANG"
TIPE_PELUNASAN = "PELUNASAN"

KATEGORI_COVER = "Penutup Defisit Beban"
KATEGORI_LUNAS = "Pelunasan Hutang Beban"

EVENT_DEFSIT = "BEBAN_DEFISIT_DIPROCESS"
EVENT_PELUNASAN = "HUTANG_BEBAN_DIPELUNASAN"


class DebtError(ValueError):
    """Syarat proses/pelunasan hutang tidak terpenuhi."""


def hitung_defisit(db: Session, start, end) -> dict:
    """Defisit Beban periode = Beban yang tidak tertutup Laba Kotor.

    Membaca financial core (P2-05) TANPA mengubahnya. Beban = total_beban beku;
    Laba Kotor dibaca apa adanya dari core, TIDAK dihitung ulang di sini --
    satu-satunya tempat hitungnya adalah `finance.compute_finance_core`.
    """
    core = finance.compute_finance_core(db, start, end)
    laba_kotor = quantize(to_decimal(core["laba_kotor"]))
    beban = quantize(to_decimal(core["total_beban"]))
    defisit = quantize(beban - laba_kotor) if beban > laba_kotor else ZERO
    return {"periode": core["periode"], "omset": core["omset"],
            "total_modal": core["total_modal"], "laba_kotor": laba_kotor,
            "beban": beban, "defisit": defisit,
            "laba_bersih": core["laba_bersih"]}


def saldo_hutang(db: Session) -> Decimal:
    """Saldo Hutang Beban outstanding (HUTANG − PELUNASAN)."""
    from models import ExpenseDebtEntry
    total = ZERO
    for e in db.query(ExpenseDebtEntry).all():
        n = quantize(to_decimal(e.nominal))
        total += n if e.tipe == TIPE_HUTANG else -n
    return quantize(total)


def sudah_diproses(db: Session, periode: str):
    from models import ExpenseDebtPeriod
    return (db.query(ExpenseDebtPeriod)
            .filter(ExpenseDebtPeriod.periode == periode).first())


def proses_defisit(db: Session, start, end, kas_period_id=None, oleh: str = None):
    """Proses defisit satu periode: Kas Aset menutup dulu, sisanya jadi Hutang.

    IDEMPOTENT per periode. Tidak membuat Expense, tidak menyentuh Laci,
    tidak mengubah Financial Core. Tidak commit.
    """
    from models import ExpenseDebtEntry, ExpenseDebtPeriod

    hit = hitung_defisit(db, start, end)
    periode = hit["periode"]
    existing = sudah_diproses(db, periode)
    if existing is not None:
        return {"created": False, "periode_row": existing, "hitung": hit,
                "kas_aset_mutation": None}

    defisit = hit["defisit"]
    hutang_awal = saldo_hutang(db)
    cover = ZERO
    mutasi = None
    if defisit > ZERO:
        # v4 #8: sumber dana = SALDO ASET BESAR; proses TIDAK otomatis mengurangi
        # saldo posisi. Penutupan dilakukan manual Admin (kas/aset/keluar).
        saldo_aset = cash.saldo_kas_aset(db)
        cover = min(saldo_aset, defisit) if saldo_aset > ZERO else ZERO
    hutang_baru = quantize(defisit - cover)
    hutang_akhir = quantize(hutang_awal + hutang_baru)

    row = ExpenseDebtPeriod(
        periode=periode, kas_period_id=kas_period_id,
        beban=hit["beban"], laba_kotor=hit["laba_kotor"], defisit=defisit,
        cover_kas_aset=cover, hutang_baru=hutang_baru,
        hutang_awal=hutang_awal, hutang_akhir=hutang_akhir, oleh=oleh)
    db.add(row)
    db.flush()

    if hutang_baru > ZERO:
        entry = ExpenseDebtEntry(tipe=TIPE_HUTANG, nominal=hutang_baru,
                                 saldo_setelah=hutang_akhir, periode=periode,
                                 expense_debt_period_id=row.id,
                                 kas_entry_id=None, oleh=oleh)
        db.add(entry)

    journal.record(db, journal.DOMAIN_FINANCE, EVENT_DEFSIT,
                   entity_type="expense_debt_period", entity_id=row.id,
                   amount=defisit, actor=oleh, ref_type="periode", ref_code=periode,
                   details={"defisit": str(defisit), "cover_kas_aset_besar": str(cover),
                            "hutang_baru": str(hutang_baru),
                            "hutang_awal": str(hutang_awal),
                            "hutang_akhir": str(hutang_akhir),
                            "sumber_dana": "SALDO_ASET_BESAR",
                            "pengeluaran_aktual": "MANUAL oleh Admin (POST /api/kas/aset/keluar)"})
    db.flush()
    db.refresh(row)
    return {"created": True, "periode_row": row, "hitung": hit,
            "kas_aset_mutation": mutasi}



def catat_hutang_manual(db: Session, periode_key: str, nominal,
                       kas_period_id=None, oleh: str = None,
                       kondisi_kas_akhir=None, catatan: str = None) -> dict:
    """OD-LOCK-12 (Owner): Admin mencatat Hutang Beban secara MANUAL.

    Berbeda total dengan `proses_defisit` versi lama:

      - TIDAK ada pemicu otomatis. Ini hanya jalan kalau Admin memanggilnya.
      - Besarnya TIDAK dihitung dari `Beban - Laba Kotor`. Besarnya adalah
        nilai yang di-input Admin, yangynch diasumsikan sama dengan nilai
        minus di akhir tabel "Kondisi Kas Operasional".
      - SATU KALI per periode. `expense_debt_periods.periode` UNIQUE jadi
        penaganya, dan pengecekan di bawah memberi pesan 400 yang jelas.

    Nominal tidak boleh melebihi nilai minus yang diukur, karena itu berarti
    Admin salah baca angka. Nominal lebih kecil tetap boleh (Admin boleh
    mencatat sebagian).

    `catatan` disimpan ke journal, bukan ke baris periode: tabel
    `expense_debt_periods` tidak punya kolom teks dan sengaja tidak ditambah
    supaya tidak perlu migrasi skema produksi.
    """
    from models import ExpenseDebtEntry, ExpenseDebtPeriod

    n = quantize(to_decimal(nominal))
    if n <= ZERO:
        raise DebtError("Nominal Hutang Beban harus lebih besar dari nol")

    existing = sudah_diproses(db, periode_key)
    if existing is not None:
        raise DebtError(
            "Hutang Beban untuk periode ini sudah tercatat (%s). "
            "Satu periode hanya boleh satu kali pencatatan." % periode_key)

    if kondisi_kas_akhir is not None:
        batas = -quantize(to_decimal(kondisi_kas_akhir))
        if batas <= ZERO:
            raise DebtError(
                "Kondisi Kas Operasional periode ini tidak minus, jadi tidak "
                "ada Hutang Beban yang perlu dicatat.")
        if n > batas:
            raise DebtError(
                "Nominal %s lebih besar dari nilai minus Conditions Kas "
                "Operasional (%s)." % (n, batas))

    hutang_awal = quantize(saldo_hutang(db))
    hutang_akhir = quantize(hutang_awal + n)
    row = ExpenseDebtPeriod(
        periode=periode_key, kas_period_id=kas_period_id,
        beban=ZERO, laba_kotor=ZERO,
        defisit=n, cover_kas_aset=ZERO, hutang_baru=n,
        hutang_awal=hutang_awal, hutang_akhir=hutang_akhir,
        oleh=oleh)
    db.add(row)
    db.flush()
    entry = ExpenseDebtEntry(
        tipe=TIPE_HUTANG, nominal=n, saldo_setelah=hutang_akhir,
        periode=periode_key, expense_debt_period_id=row.id,
        kas_entry_id=None, oleh=oleh)
    db.add(entry)
    db.flush()
    journal.record(
        db, journal.DOMAIN_FINANCE, EVENT_DEFSIT,
        entity_type="expense_debt_period", entity_id=row.id,
        amount=n, actor=oleh, ref_type="periode", ref_code=periode_key,
        details={"hutang_baru": str(n), "hutang_awal": str(hutang_awal),
                 "hutang_akhir": str(hutang_akhir),
                 "kondisi_kas_akhir": (None if kondisi_kas_akhir is None
                                       else str(kondisi_kas_akhir)),
                 "sumber": "input manual Admin saat Tutup Kas (OD-LOCK-12)",
                 "catatan": catatan})
    return {"periode_row": row, "entry": entry, "hutang_baru": n,
            "hutang_awal": hutang_awal, "hutang_akhir": hutang_akhir}

def precheck_hutang(db: Session) -> dict:
    """Pre-check pelunasan (read-only): saldo hutang & saldo Kas Aset."""
    hutang = saldo_hutang(db)
    aset = cash.saldo_kas_aset(db)
    return {"saldo_hutang": hutang, "saldo_kas_aset": aset,
            "sumber_dana": cash.LAYER_ASET,
            "bisa_lunas": bool(hutang > ZERO and aset > ZERO),
            "catatan": "Hutang Beban terpisah dari Buku Kas; dana dari SALDO ASET BESAR "
                       "(pengeluaran aktual dicatat manual Admin)."}


def lunas_hutang(db: Session, nominal=None, periode=None, oleh: str = None):
    """Pelunasan Hutang Beban dari Kas Aset (+ pre-check). IDEMPOTENT terhadap sisa.

    Tidak commit — pemanggil yang mengatur transaksi.
    """
    from models import ExpenseDebtEntry

    outstanding = saldo_hutang(db)
    if outstanding <= ZERO:
        raise DebtError("Tidak ada Hutang Beban outstanding untuk dilunasi")
    n = quantize(to_decimal(nominal)) if nominal is not None else outstanding
    if n <= ZERO:
        raise DebtError("Nominal pelunasan harus lebih besar dari nol")
    if n > outstanding:
        raise DebtError("Nominal pelunasan %s melebihi sisa Hutang Beban %s"
                        % (n, outstanding))
    cukup, saldo_aset, kurang = cash.cukup_kas_aset(db, n)
    if not cukup:
        raise DebtError("Saldo Kas Aset tidak cukup untuk pelunasan %s (kurang %s)"
                        % (n, kurang))

    # v4 #8: pelunasan dicatat sebagai penyelesaian hutang; pengeluaran aktual dari
    # SALDO ASET BESAR dicatat manual Admin.
    saldo_baru = quantize(outstanding - n)
    entry = ExpenseDebtEntry(tipe=TIPE_PELUNASAN, nominal=n, saldo_setelah=saldo_baru,
                             periode=periode, kas_entry_id=None, oleh=oleh)
    db.add(entry)

    journal.record(db, journal.DOMAIN_FINANCE, EVENT_PELUNASAN,
                   entity_type="expense_debt_entry", entity_id=entry.id, amount=n,
                   actor=oleh, ref_type="kas_aset", ref_code=cash.LAYER_ASET,
                   details={"nominal": str(n), "saldo_hutang_setelah": str(saldo_baru),
                            "sumber_dana": "SALDO_ASET_BESAR",
                            "pengeluaran_aktual": "MANUAL oleh Admin (POST /api/kas/aset/keluar)"})
    db.flush()
    db.refresh(entry)
    return {"entry": entry, "kas_aset_mutation": None,
            "saldo_hutang": saldo_baru, "saldo_kas_aset_setelah": cash.saldo_kas_aset(db)}


def ringkasan(db: Session) -> dict:
    """Status Hutang Beban (read-only) — termasuk carry-forward antar periode."""
    from models import ExpenseDebtEntry, ExpenseDebtPeriod

    hutang = saldo_hutang(db)
    periods = (db.query(ExpenseDebtPeriod)
               .order_by(ExpenseDebtPeriod.periode.desc()).all())
    return {
        "saldo_hutang": hutang,
        "saldo_kas_aset": cash.saldo_kas_aset(db),
        "terbawa": next((p.hutang_awal for p in periods
                         if quantize(to_decimal(p.hutang_baru)) > ZERO), ZERO) if periods else ZERO,
        "periode": [{"periode": p.periode, "beban": p.beban, "laba_kotor": p.laba_kotor,
                     "defisit": p.defisit, "cover_kas_aset": p.cover_kas_aset,
                     "hutang_baru": p.hutang_baru, "hutang_awal": p.hutang_awal,
                     "hutang_akhir": p.hutang_akhir, "created_at": p.created_at,
                     "oleh": p.oleh} for p in periods],
        "ledger": [{"id": e.id, "tipe": e.tipe, "nominal": e.nominal,
                    "saldo_setelah": e.saldo_setelah, "periode": e.periode,
                    "kas_entry_id": e.kas_entry_id, "created_at": e.created_at,
                    "oleh": e.oleh}
                   for e in db.query(ExpenseDebtEntry).order_by(ExpenseDebtEntry.id).all()],
        "catatan": "Hutang Beban terpisah dari Buku Kas (SSOT-8); dana dari Kas Aset.",
    }