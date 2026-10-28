"""P2-05 — FINANCIAL CORE Project B (Financial SSOT sebagai target).

Implementasi rumus Owner:
    OMZET       = total penjualan unit CASH + LUNAS pada periode kas berjalan.
                  DP BUKAN Omzet.
    MODAL       = Modal Part + Modal Jasa + Modal Lain-lain (3 komponen terpisah)
    LABA KOTOR  = OMZET - TOTAL MODAL
    BEBAN       = Gaji + Operasional (kategori lain tidak masuk Beban)
    LABA BERSIH = OMZET - TOTAL MODAL - TOTAL BEBAN

ATURAN OWNER YANG MENAUNGI RUMUS INI
    "Laba Kotor = Omzet - Total Modal"
    "Laba Bersih = Omzet - Total Modal - Total Beban"

    Semua angka TUMBUL dari transaksi servis. Transaksi kas manual TIDAK
    ikut masuk laba, di mana pun: bukan Omzet, bukan Modal, bukan Beban, dan
    bukan Tambahan. Ia murni pergerakan uang di laci -- dicatat di ledger kas,
    tapi tidak mengubah berapa hasil usaha pada periode itu.

    Akibatnya `tambahan` tidak lagi menjadi suku di rumus laba mana pun.
    Nilainya tetap dihitung dan diekspos hanya sebagai informasi (angka kas
    manual periode berjalan), bukan sebagai pembentuk laba.

FIN-MIRROR-1 (Beban permanen):
    Proyek A `app.py:983-984,1017` memakai `SUM(nilai) FROM beban` TANPA filter
    tanggal, dipotong dari siklus mana pun setiap hari. Di sini dibekukan:
    beban `recurring=True` dibekukan ke SETIAP periode.

FIN-MIRROR-2 (Gate Omzet = CASH):
    Proyek A `app.py:1715` - `laba_final = h_jual - m_part - m_jasa - m_lain
    if stat == 'Cash' else 0`. A hanya bergantung pada status Cash; tidak ada
    syarat pelunasan penuh. Digunakan di sini sebagai gate cohort Omzet,
    ditambah syarat LUNAS sesuai aturan Owner.

FIN-MIRROR-4 (Transaksi kas manual) -- TIDAK DIMIRROR ke laba:
    Proyek A punya dua rumus laba yang bertentangan; A-1
    (`app.py:369-376`) memasukkan transaksi kas manual ke laba, A-2
    (`app.py:1004-1019`) tidak. Versi ini memakai A-2 karena Owner menetapkan
    Omzet dan laba harus murni dari hasil servis. Modul ini sengaja tidak
    mengikuti A-1.

FIN-MIRROR-3 (sisa pembuluan Distribution) TIDAK dimirror - lihat distribution.py.

Aturan Owner yang tetap dipertahankan:
- Q5/Q19/SSOT-3: ketiga modal adalah komponen terpisah; tidak digabung, tidak
  boleh dihitung dua kali (Laba Kotor hanya alias antara, bukan pengurangan kedua).
- SSOT-4/OD-001: Beban dibebankan SEKALI per periode kas (snapshot beku, idempotent).
- SSOT-5: Laba Bersih tanpa double calculation -- murni Omzet - Modal - Beban.

Modul ini TIDAK menghitung distribusi secara final (P2-07) dan TIDAK menutup kas (P2-08).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from models import ExpensePeriod, Payment, ServiceOrder
from money import ZERO, to_decimal
from statusflow import cash_moment, kewajiban, payment_summary


def _log(pesan):
    """Catat pesan ke logger.

    Dulu fungsi ini tidak pernah ada di modul ini padahal dipanggil di jalur
    error `_bayar_beban_langsung`. Akibatnya kalau pembayaran Beban gagal,
    baris `_log(...)` justru melempar NameError -- jadi error aslinya hilang
    dan justru membuat financial core ikut ikut exception.
    """
    import logging
    logging.getLogger("bosssf.finance").warning(pesan)

# Kategori beban yang Recognized Owner (SSOT-4). Kategori lain TIDAK masuk Beban.
BEBAN_KATEGORI = ("gaji", "operasional")


def period_key(db: Session, start: datetime, end: datetime) -> str:
    """Kunci unik periode kas.

    Owner: "pakai periode, karena selama pengujian dalam satu hari bisa berkali-
    kali tutup kas."

    Versi lama memakai `start.strftime("%Y-%m-%d")`, sehingga dua KasPeriod yang
    sama-sama jatuh di tanggal yang sama menghasilkan kunci yang SAMA. Akibatnya
    penanda idempotensi Beban (`ref_id`) bentrok: periode kedua dianggap sudah
    membayar Beban padahal periode pertama yang membayarnya. Itu membuat Beban
    periode kedua tidak pernah keluar dari Laci.

    Sekarang kunci diambil dari `kas_periods.id`, jadi unik sewenang-wenang.
    Kalau KasPeriod belum ada (mis. dipanggil sebelum periode dibuat), dipakai
    stempel waktu penuh yang juga unik.
    """
    pid = _kas_period_id_untuk(db, start)
    if pid is not None:
        return "kas_period:%d" % pid
    return "waktu:%s" % start.strftime("%Y-%m-%d %H:%M:%S")


def legacy_period_key(start: datetime) -> str:
    """Kunci versi lama (tanggal). Hanya untuk MEMBACA data historis."""
    return start.strftime("%Y-%m-%d")


def _semua_kunci(db: Session, start: datetime, end: datetime) -> list:
    """Kunci beku yang boleh dibaca untuk satu periode.

    Kunci baru (berbasis `kas_periods.id`) selalu dipakai. Kunci versi lama
    (tanggal) HANYA ikut dibaca untuk periode yang sudah CLOSED, supaya periode
    tertutup tidak dibekukan ulang -- hasilnya menjadi Beban ganda.

    Untuk periode yang masih OPEN, kunci lama TIDAK boleh dipakai: baris lamanya
    milik periode lain yang kebetulan jatuh di tanggal sama, dan membacanya
    membuat periode ini terlihat "sudah beku" padahal belum. Persis itulah bug
    yang membuat Beban periode berjalan tidak pernah keluar dari Laci.
    """
    kunci = [period_key(db, start, end)]
    row = _kas_period_untuk(db, start)
    if row is not None and (row.status or "").strip().upper() == "CLOSED":
        lama = legacy_period_key(start)
        if lama not in kunci:
            kunci.append(lama)
    return kunci


def modal_sudah_diisi(order) -> bool:
    """True kalau unit punya minimal satu komponen modal yang bernilai > 0.

    Ini yang membedakan "unit BELUM diisi modalnya" dari "unit tidak punya
    modal sama sekali". Owner sudah memberi jalan keluar untuk kasus kedua:
    centang "Tanpa Modal (sengaja 0)" -- penanda `tanpa_modal`. Tanpa centang,
    keduanya tidak bisa dibedakan dan unit tanpa modal tidak akan pernah masuk
    Omzet.
    """
    return (to_decimal(getattr(order, "part_cost", 0) or 0)
            + to_decimal(getattr(order, "modal_jasa", 0) or 0)
            + to_decimal(getattr(order, "modal_lainnya", 0) or 0)) > ZERO


def modal_ditandai_sengaja_nol(order) -> bool:
    """True kalau Owner menandai unit ini memang tanpa modal."""
    return bool(getattr(order, "tanpa_modal", False))


def boleh_masuk_omzet(order) -> bool:
    """Gerbang kohort Omzet: modal terisi, ATAU Owner menandainya tanpa modal.

    Unit modal-kosong yang TIDAK ditandai tidak masuk Omzet sama sekali -- jadi
    tidak menambah Omzet, Laba Kotor, maupun distribution, dan tetap muncul di
    peringatan keras Tutup Kas sampai Modal-nya diisi.
    """
    if modal_sudah_diisi(order):
        return True
    return modal_ditandai_sengaja_nol(order)


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
    # ATURAN OWNER (FIN-MIRROR-6): "Omzet = nilai transaksi yang SUDAH LUNAS."
    # Sebelumnya gerbang ini hanya `status == 'CASH'`, jadi unit yang sudah
    # diambil pelanggan tapi pelunasannya belum masuk ikut dihitung sebagai omzet.
    # Akibatnya omzet lebih besar dari uang yang benar-benar diterima, laba kotor
    # ikut membesar, dan distribusi bisa keluar dari uang yang belum masuk --
    # persis kasus order dengan obligasi Rp 400.000 tapi dibayar Rp 0.
    #
    # Catatan: `status == 'CASH'` TIDAK otomatis berarti LUNAS. Pelunasan ditulis
    # terpisah di tabel `payments` dan bisa bolong (mis. harga diubah setelah
    # unit diambil, atau pelunasan dicatatmanual kemudian).
    #
    # Payment Ledger dikumpulkan SEKALI di depan supaya tidak jadi query N+1.
    dari_payment = {}
    for pid, sid in (db.query(Payment.id, Payment.service_order_id).all()):
        dari_payment.setdefault(sid, []).append(pid)
    cache_payment = {}
    for o in orders:
        ids = dari_payment.get(o.id) or []
        pays = cache_payment.get(o.id)
        if pays is None:
            pays = (db.query(Payment).filter(Payment.id.in_(ids)).all()
                    if ids else [])
            cache_payment[o.id] = pays

    cohort = []
    for o in orders:
        if (getattr(o, "status", "") or "") != "CASH":
            continue
        # ATURAN OWNER: unit CASH yang Modalnya belum diisi (Part/Jasa/Lain
        # semuanya 0) BELUM dianggap transaksi sungguhan -- jadi tidak masuk
        # Omzet/Transaksi sama sekali. Kalau belum sempat mengisi modal,
        # Harga Final masuk ke Laci tapi tidak ada biaya tercatat, sehingga
        # seluruh harga dianggap laba; itu bisa membuat CTO tercapai lebih awal
        # dan memicu distribution dari uang yang sebenarnya bukan keuntungan.
        # Order seperti itu sengaja DITAMPILKAN di peringatan keras Tutup Kas
        # supaya modalnya sempat diisi sebelum periode ditutup.
        #
        # Jalur keluar: Owner menandai unit sebagai "Tanpa Modal (sengaja 0)"
        # lewat kolom `tanpa_modal`. Unit bertanda itu tetap dihitung sebagai
        # transaksi, hanya tidak menambah biaya (memang tidak ada).
        if not boleh_masuk_omzet(o):
            continue
        if (payment_summary(o, cache_payment.get(o.id) or []).get("payment_status")
                or "") != "LUNAS":
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
    """Net transaksi kas manual pada periode (jurnal `sumber = MANUAL`).

    PENTING: nilai ini INFORMASI SAJA. Ia TIDAK dipakai di rumus laba mana pun.

    Owner menetapkan:
        LABA KOTOR  = OMSET - TOTAL MODAL
        LABA BERSIH = LABA KOTOR - TOTAL BEBAN

    Proyek A punya dua rumus yang bertentangan; A-1 (`app.py:372-376`) memasukkan
    transaksi kas manual ke laba, A-2 (`app.py:1004-1019`) tidak. Versi ini
    memakai A-2. Fungsi ini tetap dipertahankan hanya supaya angka kas manual
    periode bisa ditampilkan dan diaudit.

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

    key = period_key(db, start, end)
    existing = (db.query(ExpensePeriod)
                .filter(ExpensePeriod.periode.in_(_semua_kunci(db, start, end)))
                .all())
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


def _kas_period_untuk(db: Session, start: datetime):
    """Baris `KasPeriod` yang dimulai pada `start`, atau None."""
    try:
        from models import KasPeriod
        return (db.query(KasPeriod)
                .filter(KasPeriod.start_at == start)
                .order_by(KasPeriod.id.desc()).first())
    except Exception:  # noqa: BLE001
        return None


def _kas_period_id_untuk(db: Session, start: datetime):
    """Id KasPeriod yang dimulai pada `start`, atau None.

    Dipakai agar rincian Hutang Beban menyertakan periode asalnya, sesuai
    OD-LOCK-06: rincian per periode, termasuk nilai awal, pembayaran atau
    cover yang sudah dilakukan, dan sisa kewajiban.
    """
    row = _kas_period_untuk(db, start)
    return row.id if row is not None else None


def _bayar_beban_langsung(db: Session, start: datetime, end: datetime,
                          key: str, total_beban, laba_kotor=None) -> dict:
    """OD-LOCK-06 — bayar Beban periode: Laci → Kas Aset → Hutang Beban.

    Import `beban_bayar` di dalam fungsi (lazy) karena modul itu mengimpor
    `expense_debt`, yang sendiri mengimpor modul ini. Import di level modul akan
    menghasilkan circular import.

    Kegagalan dicatat, tidak boleh menggagalkan perhitungan keuangan yang sedang
    berjalan -- tapi TIDAK boleh hilang tanpa jejak, jadi pesannya ditulis ke
    logger dan pembayaran akan dicoba lagi pada pemicu berikutnya (fungsinya
    sendiri idempoten).
    """
    try:
        import beban_bayar
        return beban_bayar.bayar_beban_periode(
            db, start, end, key, total_beban, oleh="beban-otomatis",
            kas_period_id=_kas_period_id_untuk(db, start),
            laba_kotor=laba_kotor)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _log("[beban] pembayaran otomatis periode %s GAGAL: %s" % (key, exc))
        return {"error": str(exc), "dibayar": False}


def beban_frozen(db: Session, start: datetime, end: datetime,
                 commit: bool = False, laba_kotor=None) -> dict:
    """Baca beban beku periode; bekukan lebih dulu bila belum ada."""
    key = period_key(db, start, end)
    kunci = _semua_kunci(db, start, end)
    rows = db.query(ExpensePeriod).filter(ExpensePeriod.periode.in_(kunci)).all()
    baru_beku = not rows
    if baru_beku:
        freeze_expenses_for_period(db, start, end, commit=False)
        rows = (db.query(ExpensePeriod)
                .filter(ExpensePeriod.periode.in_(kunci)).all())
    gaji = ZERO
    operasional = ZERO
    for r in rows:
        kategori = (r.kategori or "").strip().lower()
        if kategori == "gaji":
            gaji += to_decimal(r.nilai)
        elif kategori == "operasional":
            operasional += to_decimal(r.nilai)
    # OD-LOCK-06 (Owner, LOCKED): Beban dibayar LANGSUNG begitu kewajiban
    # periode sudah ditentukan -- tidak menunggu Tutup Kas.
    # Dipanggil HANYA saat periode baru saja dibekukan, supaya pembacaan
    # berikutnya tidak memutar pembayaran berulang (fungsinya sendiri sudah
    # idempoten lewat ref_type/ref_id yang sama dengan Tutup Kas).
    if baru_beku:
        _bayar_beban_langsung(db, start, end, key, gaji + operasional,
                              laba_kotor=laba_kotor)
    if commit:
        db.commit()
    return {"periode": key, "gaji": gaji, "operasional": operasional,
            "total": gaji + operasional}


def settled_part_sales(db: Session, start: datetime, end: datetime) -> list:
    """Cohort penjualan part langsung pada periode kas [start, end)."""
    try:
        from models import PartSale
        return (
            db.query(PartSale)
            .filter(PartSale.created_at >= start, PartSale.created_at < end)
            .all()
        )
    except Exception:
        return []


def compute_finance_core(db: Session, start: datetime, end: datetime,
                         freeze: bool = False) -> dict:
    """SSOT financial core. Mengembalikan primitive untuk P2-05/P2-07/P2-08."""
    cohort = settled_orders(db, start, end)
    omset_servis = ZERO
    modal_part_servis = ZERO
    modal_jasa = ZERO
    modal_lain = ZERO
    for o in cohort:
        omset_servis += kewajiban(o)
        modal_part_servis += to_decimal(getattr(o, "part_cost", 0))
        modal_jasa += to_decimal(getattr(o, "modal_jasa", 0))
        modal_lain += to_decimal(getattr(o, "modal_lainnya", 0))

    # Penjualan part langsung (POS Kasir)
    part_sales = settled_part_sales(db, start, end)
    omset_part = sum((to_decimal(s.total_omzet) for s in part_sales), ZERO)
    modal_part_sales = sum((to_decimal(s.total_modal) for s in part_sales), ZERO)

    total_omset = omset_servis + omset_part
    total_modal_part = modal_part_servis + modal_part_sales
    total_modal = total_modal_part + modal_jasa + modal_lain

    # Transaksi kas manual dicatat di ledger, tapi TIDAK masuk rumus laba.
    tambahan = tambahan_kas(db, start, end)

    # Laba Kotor: TOTAL OMSET (Servis + Part Langsung) - TOTAL MODAL
    laba_kotor = total_omset - total_modal

    beban = beban_frozen(db, start, end, commit=False, laba_kotor=laba_kotor)
    total_beban = beban["gaji"] + beban["operasional"]

    laba_bersih = laba_kotor - total_beban

    return {
        "periode": period_key(db, start, end),
        "omset": total_omset,
        "omset_servis": omset_servis,
        "omset_part": omset_part,
        "n_settled": len(cohort),
        "n_part_sales": len(part_sales),
        "modal_part": total_modal_part,
        "modal_part_servis": modal_part_servis,
        "modal_part_sales": modal_part_sales,
        "modal_jasa": modal_jasa,
        "modal_lainnya": modal_lain,
        "total_modal": total_modal,
        "tambahan": tambahan,
        "beban_gaji": beban["gaji"],
        "beban_operasional": beban["operasional"],
        "total_beban": total_beban,
        "laba_kotor": laba_kotor,
        "laba_bersih": laba_bersih,
        "laba_per_order": None,
    }


def snapshot_laba_bersih(db: Session, start: datetime, end: datetime) -> Decimal:
    """Primitive snapshot Laba Bersih untuk dipakai Tutup Kas (P2-08)."""
    return compute_finance_core(db, start, end)["laba_bersih"]


def order_sisa(order) -> Decimal | None:
    """Sisa per unit: Harga Final - (Modal Part + Jasa + Lain-lain).

    Berbeda dari Laba Kotor periode, angka ini milik SATU unit, jadi
    tidak ada alokasi Beban - Beban itu per periode kas dan tidak bisa
    dibelah ke satu baris tabel.

    Gate (keputusan Owner): hanya tampil kalau unit sudah CASH **dan**
    Modal-nya sudah diisi. `boleh_masuk_omzet()` dipakai langsung supaya
    gerbangnya tidak diduplikasi di tempat lain.

    `None` berarti "belum boleh dihitung" - sengaja BUKAN `0`. Unit yang
    belum CASH atau modalnya belum diisi harus tampil berbeda dari unit
    yang benar-benar zeroes.

    Catatan: `statusflow.order_profit` tidak dipakai di sini karena gate
   -nya cuma CASH tanpa syarat modal terisi. Order CASH yang modalnya
    kosong akan terlihat " untung penuh" di sana - persis jebakan yang
    `settled_orders` sudah mendokumentasikan.
    """
    if (getattr(order, "status", "") or "") != "CASH":
        return None
    if not boleh_masuk_omzet(order):
        return None
    return (kewajiban(order)
            - to_decimal(getattr(order, "part_cost", 0) or 0)
            - to_decimal(getattr(order, "modal_jasa", 0) or 0)
            - to_decimal(getattr(order, "modal_lainnya", 0) or 0))


__all__ = [
    "BEBAN_KATEGORI",
    "beban_frozen",
    "compute_finance_core",
    "freeze_expenses_for_period",
    "period_key",
    "settled_orders",
    "settled_part_sales",
    "snapshot_laba_bersih",
]