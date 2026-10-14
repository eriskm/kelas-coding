# -*- coding: utf-8 -*-
"""OD-LOCK-06 (Owner, LOCKED) — Pembayaran Beban Gaji & Operasional.

Aturan yang ditegakkan modul ini:

    Kewajiban Beban periode
        1. dibayar dari saldo LACI yang tersedia
        2. kekurangannya ditutup dari KAS ASET (benar-benar mengurangi saldo,
           dicatat di jurnal kas -- BUKAN sekadar mencatat angka cover)
        3. bila Kas Aset juga tidak cukup, dipakai SELURUH saldo yang ada
        4. sisa yang belum terbayar menjadi HUTANG BEBAN, lengkap dengan
           rincian dan periode asalnya
        5. Hutang Beban terakumulasi dan TIDAK hilang saat periode berganti

Pembayaran dilakukan LANGSUNG ketika kewajiban periode sudah ditentukan --
tidak menunggu Tutup Kas. Tutup Kas tetap aman karena membaca penanda yang sama
(`ref_type='beban_periode'`, `ref_id=<periode>`), sehingga tidak membayar atau
memotong dua kali.

ATURAN LAIN YANG TIDAK DIUBAH:
- MODAL tetap keluar saat CASH (OD-LOCK-01).
- Distribusi 10/30/30/30 tidak tersentuh (OD-LOCK-02).
- Refund klaim garansi tetap MANUAL dari Kas Aset (OD-LOCK-05) -- jalur ini
  hanya untuk Beban Gaji & Operasional, tidak untuk refund garansi.
- Beban tetap dibekukan SEKALI per periode kas (FR-01 / OD-001).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

import cash
import journal
from money import ZERO, quantize, to_decimal

#: Import di dalam fungsi (lazy) supaya tidak circular:
#: finance -> beban_bayar -> expense_debt -> finance.
from expense_debt import TIPE_HUTANG, saldo_hutang

#: Penanda idempotensi. SAMA dengan yang dipakai Tutup Kas
#: (`closing.BE_REF_TYPE`) supaya keduanya saling mengenali -- ini yang
#: mencegah pembayaran ganda.
BE_REF_TYPE = "beban_periode"

KATEGORI_BEBAN_ASET = "Penutupan Beban dari Kas Aset"

EVENT_BEBAN_DIBayar = "BEBAN_PERIODE_DIPBAYAR"


def _total_dibayar(db: Session, periode: str) -> Decimal:
    """Berapa Beban periode ini yang SUDAH dibayar ke Laci (lewat apa pun).

    Entri Beban selalu bertipe "Keluar", jadi dijumlahkan sebagai NILAI ABSOLUT.
    """
    from models import KasEntry
    total = ZERO
    for k in (db.query(KasEntry)
              .filter(KasEntry.layer == cash.LAYER_LACI,
                      KasEntry.sumber == cash.SUMBER_BEBAN,
                      KasEntry.ref_type == BE_REF_TYPE,
                      KasEntry.ref_id == periode).all()):
        n = abs(to_decimal(k.nominal))
        if (k.jenis or "").strip().lower() == "keluar":
            total += n
        else:
            total -= n
    return quantize(total)


def bayar_beban_periode(db: Session, start, end, periode_key: str,
                        total_beban, oleh: str = None,
                        kas_period_id=None, laba_kotor=None) -> dict:
    """OD-LOCK-06: bayar kewajiban Beban satu periode. IDEMPOTEN.

    Urutan dana (persis aturan Owner):
        Laci  ->  Kas Aset (dipindah sungguhan)  ->  Hutang Beban

    Tidak pernah membuat saldo Laci negatif: `dari_laci` dibatasi saldo Laci.
    Tidak pernah mengklaim hutang sudah dibayar: yang tersisa SELALU dicatat
    sebagai Hutang Beban.
    """
    total_beban = quantize(to_decimal(total_beban))
    sudah = _total_dibayar(db, periode_key)
    sisa_kewajiban = quantize(total_beban - sudah)

    out = {"periode": periode_key, "total_beban": total_beban,
           "sudah_dibayar": sudah, "dari_laci": ZERO, "dari_kas_aset": ZERO,
           "hutang": ZERO, "dibayar": False, "hutang_row": None}

    if sisa_kewajiban <= ZERO:
        out["hutang"] = ZERO
        return out

    # -- (1) Laci ------------------------------------------------------------
    saldo_laci = cash.saldo_laci(db)
    dari_laci = quantize(min(sisa_kewajiban, saldo_laci)) if saldo_laci > ZERO else ZERO

    # -- (2)+(3) Kas Aset menutup kekurangan --------------------------------
    sisa2 = quantize(sisa_kewajiban - dari_laci)
    dari_aset = ZERO
    if sisa2 > ZERO:
        saldo_aset = cash.saldo_kas_aset(db)
        dari_aset = (quantize(min(sisa2, saldo_aset))
                     if saldo_aset > ZERO else ZERO)

    # Uang Kas Aset DIBERIKAN ke Laci sungguhan supaya bisa membayar Beban,
    # dan tercatat sebagai pasangan transfer pada ledger kas.
    if dari_aset > ZERO:
        cash.transfer(db, dari_aset, cash.LAYER_ASET, cash.LAYER_LACI,
                      "Penutupan Beban periode %s dari Kas Aset" % periode_key,
                      actor=oleh, ref_type=BE_REF_TYPE, ref_id=periode_key,
                      check_saldo=True, sumber=cash.SUMBER_HUTANG_BEBAN,
                      idempoten=True)

    total_dibayar = quantize(dari_laci + dari_aset)

    # -- (2) satu baris kas untuk seluruh pembayaran -------------------------
    if total_dibayar > ZERO:
        cash.catat_mutasi(
            db, cash.LAYER_LACI, "Keluar", cash.KATEGORI[cash.SUMBER_BEBAN],
            "Pembayaran Beban periode %s" % periode_key, total_dibayar,
            sumber=cash.SUMBER_BEBAN, ref_type=BE_REF_TYPE,
            ref_id=periode_key, oleh=oleh, check_saldo=False)

    # -- (4)+(5) sisa jadi Hutang Beban -------------------------------------
    hutang = quantize(total_beban - (sudah + total_dibayar))
    out.update({"dari_laci": dari_laci, "dari_kas_aset": dari_aset,
                "hutang": hutang, "dibayar": total_dibayar > ZERO})

    if hutang > ZERO:
        from models import ExpenseDebtEntry, ExpenseDebtPeriod

        hutang_awal = quantize(saldo_hutang(db))
        # `expense_debt_periods.periode` UNIQUE: satu periode satu baris
        # rincian. Pembayaran lanjutan (mis. Kas Aset baru masuk belakangan)
        # MEMPERBARUI baris itu, bukan menambah baris baru.
        row = (db.query(ExpenseDebtPeriod)
               .filter(ExpenseDebtPeriod.periode == periode_key).first())
        if row is None:
            row = ExpenseDebtPeriod(
                periode=periode_key, kas_period_id=kas_period_id,
                beban=total_beban, laba_kotor=quantize(to_decimal(laba_kotor)),
                defisit=hutang, cover_kas_aset=dari_aset, hutang_baru=hutang,
                hutang_awal=hutang_awal,
                hutang_akhir=quantize(hutang_awal + hutang), oleh=oleh)
            db.add(row)
            db.flush()
            entry = ExpenseDebtEntry(
                tipe=TIPE_HUTANG, nominal=hutang,
                saldo_setelah=quantize(hutang_awal + hutang),
                periode=periode_key, expense_debt_period_id=row.id,
                kas_entry_id=None, oleh=oleh)
            db.add(entry)
            out["hutang_row"] = row
        else:
            # Pembayaran lanjutan: hutang yang tersisa tinggal yang dikurangi.
            hutang_berkurang = quantize(row.defisit - hutang)
            row.defisit = hutang
            row.cover_kas_aset = quantize(to_decimal(row.cover_kas_aset) + dari_aset)
            row.hutang_baru = hutang
            row.hutang_akhir = quantize(to_decimal(row.hutang_akhir) - hutang_berkurang)
            row.hutang_awal = hutang_awal
            out["hutang_row"] = row

    journal.record(
        db, journal.DOMAIN_FINANCE, EVENT_BEBAN_DIBayar,
        entity_type="kas_entry", entity_id=None,
        amount=total_dibayar, actor=oleh,
        ref_type="periode", ref_code=periode_key,
        details={"total_beban": str(total_beban),
                 "sudah_dibayar_sebelum": str(sudah),
                 "dari_laci": str(dari_laci),
                 "dari_kas_aset": str(dari_aset),
                 "hutang_beban": str(hutang),
                 "hutang_akhir": str(quantize(saldo_hutang(db) + hutang))})
    db.flush()
    return out


def sisa_kewajiban_beban(db: Session, start, end, periode_key: str,
                          total_beban) -> Decimal:
    """Berapa Beban periode ini yang belum terbayar. Untuk ringkasan/laporan."""
    return quantize(to_decimal(total_beban) - _total_dibayar(db, periode_key))
