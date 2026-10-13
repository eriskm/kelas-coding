"""P2-05 — FINANCIAL CORE Project B (Financial SSOT sebagai target).

Implementasi rumus Owner, diselaraskan ke Proyek A (FIN-MIRROR):
    OMZET       = total penjualan unit CASH pada periode bisnis (16:00->16:00).
                  DP BUKAN Omzet. Pelunasan penuh BUKAN syarat (FIN-MIRROR-2).
    MODAL       = Modal Part + Modal Jasa + Modal Lain-lain (3 komponen cost terpisah)
    TAMBAHAN    = net transaksi kas manual (FIN-MIRROR-4, rumus A-1)
    BEBAN       = Gaji + Operasional (kategori lain tidak masuk Beban)
    LABA BERSIH = OMZET - MODAL PART - MODAL JASA - MODAL LAIN-LAIN
                  + TAMBAHAN - BEBAN

FIN-MIRROR-1 (Beban permanen):
    Proyek A `app.py:983-984,1017` memakai `SUM(nilai) FROM beban` TANPA filter
    tanggal, dipotong dari siklus mana pun setiap hari. Di sini dibekukan:
    beban `recurring=True` dibekukan ke SETIAP periode.

FIN-MIRROR-2 (Gate Omzet = CASH):
    Proyek A `app.py:1715` - `laba_final = h_jual - m_part - m_jasa - m_lain
    if stat == 'Cash' else 0`. A hanya bergantung pada status Cash; tidak ada
    syarat pelunasan penuh. Digunakan di sini sebagai gate cohort Omzet.

FIN-MIRROR-4 (Transaksi kas manual masuk laba - rumus A-1):
    Proyek A punya DUA rumus laba yang bertentangan. Yang dipakai di sini A-1
    (`app.py:369-376`, `engine/kalkulator.py:15-27`, bot Telegram, milestone):
        laba_kotor  = laba_servis + laba_tambahan
        laba_bersih = laba_kotor + tambahan - beban
    A-2 (`app.py:1004-1019`, basis bagi hasil) TIDAK memakai `tambahan`.
    Perbedaan A-1 vs A-2 HANYA suku `tambahan`; selisih `omset - modal` sama
    karena A menulis `Laba Kotor = Harga Jual - modal` untuk setiap unit Cash.

FIN-MIRROR-3 (sisa pembuluan Distribution) TIDAK dimirror - lihat distribution.py.

Aturan Owner yang tetap dipertahankan:
- Q5/Q19/SSOT-3: ketiga modal adalah komponen terpisah; tidak digabung, tidak
  boleh dihitung dua kali (Laba Kotor hanya alias antara, bukan pengurangan kedua).
- SSOT-4/OD-001: Beban dibebankan SEKALI per periode kas (snapshot beku, idempotent).
- SSOT-5: Laba Bersih tanpa double calculation. Perhatikan: setelah
  FIN-MIRROR-4 jumlahnya 4 pengurang + 1 suku positif (`tambahan`), bukan lagi
  4 pengurang murni.

Modul ini TIDAK menghitung distribusi secara final (P2-07) dan TIDAK menutup kas (P2-08).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from models import ExpensePeriod, ServiceOrder
from money import ZERO, to_decimal
from statusflow import cash_moment, kewajiban, payment_summary

# Kategori beban yang Recognized Owner (SSOT-4). Kategori lain TIDAK masuk Beban.
BEBAN_KATEGORI = ("gaji", "operasional")


def period_key(start: datetime, end: datetime) -> str:
    """Kunci periode kas = tanggal mulai periode (16:00->16:00)."""
    return start.strftime("%Y-%m-%d")


def modal_sudah_diisi(order) -> bool:
    """True kalau unit punya minimal satu komponen modal yang bernilai > 0.

    Ini yang membedakan "unit BELUM diisi modalnya" dari "unit tidak punya
    modal sama sekali". Selama belum ada penanda eksplisit untuk kasus kedua,
    keduanya tidak bisa dibedakan -- dan itu batas yang perlu diketahui Owner.
    """
    return (to_decimal(getattr(order, "part_cost", 0) or 0)
            + to_decimal(getattr(order, "modal_jasa", 0) or 0)
            + to_decimal(getattr(order, "modal_lainnya", 0) or 0)) > ZERO


def settled_orders(db: Session, start: datetime, end: datetime) -> list:
    """Cohort Omzet: unit CASH dengan momen CASH di dalam periode.

    FIN-MIRROR-2 (Proyek A `app.py:1715`): pengakuan laba di Project A murni
    bergantung pada `Status == 'Cash'`; tidak ada syarat pelunasan penuh. A
    menghitung `Harga Jual` begitu unit di-CASH, apa pun status pembayarannya.
    Kohort ini karena itu hanya menyaring status CASH + momen CASH.

    Momen CASH memakai `cash_moment()`: `taken_at` (diisi saat event CASH) lebih
    dulu, supaya order CASH yang belum LUNAS (order itu tidak punya `lunas_at`)
    tetap bisa diatribusikan ke periodenya.

    Proyek A tidak punya dimensi waktu sama sekali - "periode"-nya adalah
    seluruh baris Cash yang masih ada di tabel saat tutup buku, karena A
    mengarsipkan lalu menghapus baris tersebut di tutup buku (`app.py:2526`).
    Batas periode di sini tetap dipertahankan (arsitektur periode B); hanya
    gate-nya yang disamakan ke A.
    """
    orders = db.query(ServiceOrder).all()
    cohort = []
    for o in orders:
        if (getattr(o, "status", "") or "") != "CASH":
            continue
        # ATURAN OWNER: unit CASH yang Modalnya belum diisi (Part/Jasa/Lain
        # semuanya 0) BELUM dianggap transaksi sungguhan -- jadi tidak masuk
        # Omzet/Transaksi sama sekali. kalau belum sempat sempat tidak mengisi modal,
        # Preis Final masuk ke Laci tapi tidak ada biaya tercatat, sehingga
        # seluruh harga dianggap laba; itu bisa membuat CTO tercapai lebih awal
        # dan memicu distribution dari uang yang sebenarnya bukan keuntungan.
        # Order seperti itu sengaja DITAMPILKAN di peringatan keras Tutup Kas
        # supaya modalnya sempat diisi sebelum periode ditutup.
        #
        # CATATAN PENTING: unit yang memang SENGAJA tanpa modal (mis. hanya
        # jasa software, tanpa ganti part) ikut tersaring di sini. Kalau itu
        # sering terjadi, dibutuhkan penanda eksplisit "benar-benar tanpa
        # modal" supaya bisa dibedakan dari "lupa mengisi".
        if not modal_sudah_diisi(o):
            continue
        m = cash_moment(o)
        if m is None:
            continue
        if not (start <= m < end):
            continue
        cohort.append(o)
    return cohort


def _expense_moment(e):
    """Aturan moment beban (SAMA dengan sebelumnya, tidak diubah).

    `created_at` dipakai bila ada; jika tidak, `tanggal` pada pukul 12:00.
    """
    moment = getattr(e, "created_at", None)
    if moment is None:
        tgl = getattr(e, "tanggal", None)
        if tgl is None:
            return None
        return datetime(tgl.year, tgl.month, tgl.day, 12, 0, 0)
    return moment


def _kas_moment(k):
    """Aturan moment entri kas (SAMA dengan `_kas_moment` di routers/dashboard.py).

    `created_at` dipakai bila ada; jika tidak, `tanggal` pada pukul 12:00.
    """
    moment = getattr(k, "created_at", None)
    if moment is not None:
        return moment
    tgl = getattr(k, "tanggal", None)
    if tgl is None:
        return None
    return datetime(tgl.year, tgl.month, tgl.day, 12, 0, 0)


def tambahan_kas(db: Session, start: datetime, end: datetime):
    """FIN-MIRROR-4 - padanan `transaksi_tambahan` Proyek A (A-1).

    Bukti A (`app.py:372-376`, `engine/kalkulator.py:19,27`):
        SELECT SUM(CASE WHEN jenis='Masuk' THEN nominal ELSE -nominal END)
          FROM transaksi_tambahan
         WHERE uraian != 'MODAL KAS KECIL (LACI)'
        ...
        laba_kotor   = laba_servis + laba_tambahan
        laba_bersih  = laba_kotor + tambahan - beban

    Berbeda dengan A-2 (rumus dashboard A), A-1 MEMASUKKAN transaksi kas manual ke
    laba. Bot Telegram dan milestone CTS/CTO/CTH Project A memakai A-1.

    PEMETAAN KE B (presisi):
    - `transaksi_tambahan` A  ->  `kas_entries` dengan `sumber = MANUAL`
      (entri kas yang dibuat manual oleh staf, via endpoint kas B). Hanya itu.
    - Pengecualian `uraian != 'MODAL KAS KECIL (LACI)'` A  ->  `kategori !=
      'Saldo Awal'` B. Keduanya baris yang mewakili float kas fisik awal
      siklus: di A ditandai uraian sentinel, di B ditandai kategori opening.

    Yang SENGAJA TIDAK dihitung (mencegah double count dengan tiga suku lain
    dari `laba_bersih`):
    - `PAYMENT`  -> sudah masuk Omzet.
    - `MODAL`    -> sudah masuk Modal Part/Jasa.
    - `BEBAN`    -> sudah masuk Beban.
    - `CASH_OUT` -> cash-out distribusi; di Project A pembagian hasil hanya
      jadi baris `history_kas` di memori (`app.py:1029-1036`) dan TIDAK pernah
      ditulis ke `transaksi_tambahan`. Menghitungnya di sini akan mengurangi
      laba dua kali.

    Batas periode: A tidak punya dimensi waktu (tabel `transaksi_tambahan`
    di-`DELETE` seluruhnya saat tutup buku, `app.py:2533`), jadi A selalu
    memakai seluruh isi tabel. Di B batas periode tetap dipatuhi agarcash tidak
    dihitung ganda antar siklus.
    """
    from models import KasEntry

    import cash as cash_mod

    total = ZERO
    for k in db.query(KasEntry).filter(
            KasEntry.layer == cash_mod.LAYER_LACI).all():
        sumber = (getattr(k, "sumber", None) or cash_mod.SUMBER_MANUAL)
        if sumber != cash_mod.SUMBER_MANUAL:
            continue
        if (getattr(k, "kategori", None) or "").strip() == cash_mod.SALDO_AWAL_KATEGORI:
            # Baris float kas fisik - padanan uraian 'MODAL KAS KECIL (LACI)' A.
            continue
        m = _kas_moment(k)
        if m is None or not (start <= m < end):
            continue
        n = to_decimal(getattr(k, "nominal", 0))
        if (getattr(k, "jenis", "") or "").strip().lower() == "masuk":
            total += n
        else:
            total -= n
    return total


def freeze_expenses_for_period(db: Session, start: datetime, end: datetime,
                              commit: bool = False) -> dict:
    """Bekukan beban periode ini SEKALI (idempotent, SSOT-4 / OD-001).

    FIN-MIRROR-1 (Proyek A): beban `recurring=True` dibekukan ke SETIAP periode -
    A tidak punya filter tanggal pada `SUM(nilai) FROM beban`, jadi gaji &
    operasional dipotong dari siklus mana pun. Beban `recurring=False` tetap
    diproses seperti sebelumnya: hanya periode di mana moment-nya jatuh.

    Sifat beku (tidak berubah dari sebelumnya, dan itu disengaja):
    - Kalau periode ini SUDAH punya baris beku, fungsi ini tidak melakukan apa
      apa. Laba Bersih periode closed tidak boleh berubah hanya karena sebuah
      beban baru dibuat belakangan - itu melindungi histori produksi.
    - Periode yang belum punya baris beku sama sekali (mis. periode yang belum
      pernah dihitung, atau yang dihitung saat katalog beban belum ada) tetap
      bisa dibekukan di sini, jadi katalog `recurring` ikut terbawa.
    """
    from models import Expense

    key = period_key(start, end)
    existing = db.query(ExpensePeriod).filter(ExpensePeriod.periode == key).all()
    if existing:
        return {"periode": key, "dibekukan": 0, "sudah_ada": len(existing)}

    dibuat = 0
    for e in db.query(Expense).all():
        kategori = (e.kategori or "").strip().lower()
        if kategori not in BEBAN_KATEGORI:
            # SSOT-4: kategori lain bukan Beban -> tidak dibekukan sebagai beban.
            continue
        if not bool(getattr(e, "recurring", True)):
            moment = _expense_moment(e)
            if moment is None:
                continue
            if not (start <= moment < end):
                continue
        db.add(ExpensePeriod(
            periode=key,
            kategori=(e.kategori or "").strip(),
            nama_beban=(e.uraian or e.kategori or "-").strip(),
            nilai=to_decimal(e.nilai),
            dibebankan_pada=datetime.now(),
            expense_id=e.id,
        ))
        dibuat += 1
    db.flush()
    if commit:
        db.commit()
    return {"periode": key, "dibekukan": dibuat, "sudah_ada": 0}


def beban_frozen(db: Session, start: datetime, end: datetime,
                 commit: bool = False) -> dict:
    """Baca beban beku periode; bekukan lebih dulu bila belum ada."""
    key = period_key(start, end)
    rows = db.query(ExpensePeriod).filter(ExpensePeriod.periode == key).all()
    if not rows:
        freeze_expenses_for_period(db, start, end, commit=False)
        rows = db.query(ExpensePeriod).filter(ExpensePeriod.periode == key).all()
    gaji = ZERO
    operasional = ZERO
    for r in rows:
        kategori = (r.kategori or "").strip().lower()
        if kategori == "gaji":
            gaji += to_decimal(r.nilai)
        elif kategori == "operasional":
            operasional += to_decimal(r.nilai)
    if commit:
        db.commit()
    return {"periode": key, "gaji": gaji, "operasional": operasional,
            "total": gaji + operasional}


def compute_finance_core(db: Session, start: datetime, end: datetime,
                         freeze: bool = False) -> dict:
    """SSOT financial core. Mengembalikan primitive untuk P2-05/P2-07/P2-08."""
    cohort = settled_orders(db, start, end)
    omset = ZERO
    modal_part = ZERO
    modal_jasa = ZERO
    modal_lain = ZERO
    for o in cohort:
        # FIN-MIRROR-3: pakai `kewajiban()` (final_price ?? estimate), sama
        # seperti `statusflow.order_profit`. Versi lama memakai operator `or`,
        # sehingga `final_price = 0` diam-diam jatuh ke `estimate` - dua sumber
        # kebenaran untuk angka yang sama. `kewajiban()` memakai null-coalescing,
        # jadi 0 tetap 0.
        omset += kewajiban(o)
        modal_part += to_decimal(getattr(o, "part_cost", 0))
        modal_jasa += to_decimal(getattr(o, "modal_jasa", 0))
        modal_lain += to_decimal(getattr(o, "modal_lainnya", 0))
    total_modal = modal_part + modal_jasa + modal_lain

    # FIN-MIRROR-4: transaksi kas manual masuk laba (rumus A-1 Project A).
    tambahan = tambahan_kas(db, start, end)

    beban = beban_frozen(db, start, end, commit=False)
    total_beban = beban["gaji"] + beban["operasional"]

    # A-1 (app.py:376 + kalkulator.py:27):
    #     laba_kotor  = laba_servis + laba_tambahan
    #     laba_bersih = laba_kotor + tambahan - beban
    laba_bersih = omset - modal_part - modal_jasa - modal_lain + tambahan - total_beban

    return {
        "periode": period_key(start, end),
        "omset": omset,
        "n_settled": len(cohort),
        "modal_part": modal_part,
        "modal_jasa": modal_jasa,
        "modal_lainnya": modal_lain,
        "total_modal": total_modal,
        "tambahan": tambahan,
        "beban_gaji": beban["gaji"],
        "beban_operasional": beban["operasional"],
        "total_beban": total_beban,
        "laba_bersih": laba_bersih,
        "laba_per_order": None,
    }


def snapshot_laba_bersih(db: Session, start: datetime, end: datetime) -> Decimal:
    """Primitive snapshot Laba Bersih untuk dipakai Tutup Kas (P2-08)."""
    return compute_finance_core(db, start, end)["laba_bersih"]


__all__ = [
    "BEBAN_KATEGORI",
    "beban_frozen",
    "compute_finance_core",
    "freeze_expenses_for_period",
    "period_key",
    "settled_orders",
    "snapshot_laba_bersih",
]