# -*- coding: utf-8 -*-
"""P2-08 — Orkestrasi Tutup Kas (OD-013, SSOT-1/6/7, Q7, Q14).

Tanggung jawab modul ini (TANPA redesign Buku Kas):
- (a) periode tetap 16:00 → 16:00;
- (b) Laba Bersih authoritative dari financial core (P2-05);
- (c) distribusi formed saat Tutup Kas (P2-07), idempotent per periode;
- (d) eksekusi cash-out 70% dari Laci sebagai SATU entri kas (bukan dobel);
- (e) Laci disetel ke uang fisik bila Admin Declare hitungan fisik
    (penyesuaian lewat entri 'Saldo Awal' yang sudah ada di Buku Kas B);
- (f) Kas Aset TIDAK pernah di-reset (SSOT-7);
- (g) satu transaksi: TIDAK ada commit di dalam modul; pemanggil (router) yang
    commit/rollback → kegagalan di tengah tidak meninggalkan data setengah jadi.

Yang SENGAJA tidak ada di sini: Hutang Beban carry-forward (P2-11), arsip/hard
delete (Q14 — periode closed tetap tersimpan & dibaca lewat filter presentasi).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import cash
import distribution as distribution_mod
import notifications as notif_mod
import journal
from money import ZERO, quantize, to_decimal
from routers.dashboard import batas_periode
from finance import period_key

KATEGORI_CASH_OUT = "Distribusi Laba"
MARKER_CASH_OUT = "Cash-out distribusi 70%%"

EVENT_CASH_OUT = "DISTRIBUSI_CASH_OUT"


def next_period_bounds(now: datetime, period_hour: int = 16) -> tuple:
    """Periode berikutnya: mulai `now`, berakhir 16:00 berikutnya (Q7/SSOT-1)."""
    end = now.replace(hour=period_hour, minute=0, second=0, microsecond=0)
    if end <= now:
        end += timedelta(days=1)
    return now, end


def _entry_id(entry):
    """Ambil `id` dari hasil mutasi yang bisa berupa dict atau objek ORM.

    P2-15 B-1: `catat_cash_out()` mengembalikan dict saat mutasi baru dibuat,
    tetapi mengembalikan baris `KasEntry` saat cash-out sudah pernah dieksekusi
    (jalur idempoten). Memanggil `.get()` pada objek ORM memicu AttributeError.
    """
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get("id")
    return getattr(entry, "id", None)


def catat_cash_out(db: Session, dist_row, oleh: str = None):
    """Eksekusi 70% cash-out sebagai pengurang SALDO LACI (v4 #4). Idempotent.

    Mengembalikan {'created', 'nominal', 'entry'} agar bentuknya stabil.
    """
    if dist_row is None:
        return {"created": False, "nominal": ZERO, "entry": None}
    if dist_row.cash_out_entry_id:
        from models import KasEntry
        row = db.query(KasEntry).filter(KasEntry.id == dist_row.cash_out_entry_id).first()
        return {"created": False, "entry": row,
                "nominal": to_decimal(getattr(row, "nominal", 0))}

    nominal = quantize(to_decimal(dist_row.cash_out))
    if nominal <= ZERO:
        return {"created": False, "nominal": ZERO, "entry": None}

    entry = cash.catat_cash_out(
        db, nominal, "%s periode %s" % (MARKER_CASH_OUT, dist_row.periode),
        ref_type="distribusi", ref_id=dist_row.id, actor=oleh)
    dist_row.cash_out_entry_id = entry["id"]
    journal.record(
        db, journal.DOMAIN_FINANCE, EVENT_CASH_OUT,
        entity_type="kas_entry", entity_id=entry["id"], amount=entry["nominal"],
        actor=oleh, ref_type="distribusi", ref_code=str(dist_row.id),
        details={"porsi": "70%", "periode": dist_row.periode,
                 "sumber": entry["sumber"], "layer": entry["layer"]})
    db.flush()
    return {"created": True, "nominal": entry["nominal"], "entry": entry}


def rekonsiliasi_periode(db: Session, dist_row, cash_counted, oleh: str = None):
    """Rekonsiliasi Laci vs hitungan fisik (v4 #7).

    `cash_counted` TIDAK menyuntik opening. Selisih dicatat sebagai **penyesuaian
    Laci eksplisit** + journal.
    """
    return cash.rekonsiliasi_laci(
        db, cash_counted, actor=oleh,
        ref_type="periode", ref_id=(dist_row.periode if dist_row is not None else None))


BE_REF_TYPE = "beban_periode"


def selesaikan_periode(db: Session, period, fin: dict, oleh: str = None) -> dict:
    """TUTUP KAS = menyelesaikan kewajiban kas periode ini (FIN-MIRROR-7).

    Aturan Owner, urutan dan persis:
        1. Ambil transaksi yang memenuhi kriteria pengakuan omzet (CASH + LUNAS).
        2. Modal Part & Modal Jasa dikeluarkan dari Kas Perputaran.
        3. Beban periode dikeluarkan dari Kas Perputaran.
        4. Seluruh Laba Bersih dikeluarkan: 70% cash-out, 30% pindah ke Kas Aset.
        5. Kalau Laba Kotor tidak menutup Beban -> defisit, bukan distribusi paksa.

    Karena pelunasan = modal + beban + laba_bersih dan laba_bersih seluruhnya
    keluar (70% + 30%), maka secara matematis:

        Laci_akhir = Laci_awal + pelunasan - modal - beban - laba_bersih
                  = Laci_awal

    Jadi kalau Laci_awal 0, Laci AKAN kembali ke 0. Syaratnya: ketiga arus itu
    benar-benar tercatat. Fungsi ini yang memastikan semuanya tercatat --
    tanpa membuat jurnal fiktif, tanpa memakai DP titipan, dan tanpa memaksa
    distribusi yang tidak tersedia.

    Yang boleh TIDAK tercatat:
      - modal yang tidak bisa dig deeperkan karena Laci kosong -> jadi defisit;
      - beban yang tidak cukup bayarnya -> jadi defisit (Kas Aset + Hutang Beban).
    """
    from models import KasEntry
    start, end = batas_periode(period)
    key = period_key(db, start, end)
    out = {"modal_selisih": ZERO, "beban_dibayar": ZERO, "beban_sisa": ZERO,
           "distribusi": None, "defisit": None}

    # ---- (1) Modal: catat selisih yang belum masuk ledger ------------------
    # `catat_modal` idempoten per komponen, jadi modal yang diisi SESUDAH CASH
    # tidak pernah masuk ledger. Yang terlewat dicatat di sini, per order.
    for o in finance_cohort(db, start, end):
        for mut in cash.catat_modal_selisih(db, o, actor=oleh):
            out["modal_selisih"] += abs(to_decimal(mut["nominal"]))

    # ---- (2) Beban periode dibayar dari Kas Perputaran ---------------------
    # OD-LOCK-06: pembayaran memakai MESIN YANG SAMA dengan pemicu beku
    # (`beban_bayar.bayar_beban_periode`), jadi Tutup Kas hanya membayar SISA
    # yang belum dibayar -- tidak pernah mengulang yang sudah dibayar saat
    # periode dibekukan. Satu penanda idempotensi untuk semua jalur.
    total_beban = quantize(to_decimal(fin.get("total_beban") or 0))
    import beban_bayar as be_bayar
    be = be_bayar.bayar_beban_periode(
        db, start, end, key, total_beban, oleh=oleh,
        kas_period_id=getattr(period, "id", None),
        laba_kotor=to_decimal(fin.get("laba_kotor") or 0))
    out["beban_dibayar"] = quantize(to_decimal(be.get("dari_laci") or 0)
                                    + to_decimal(be.get("dari_kas_aset") or 0))
    out["beban_sisa"] = quantize(max(to_decimal(be.get("kekurangan") or 0),
                                     to_decimal(be.get("hutang") or 0)))
    out["beban_dari_kas_aset"] = quantize(to_decimal(be.get("dari_kas_aset") or 0))
    out["beban_detail"] = be

    # ---- (3) Distribusi 10/30/30/30 atas Laba Bersih ----------------------
    # Hanya kalau Laba Bersih > 0. Distribution sudah otomatis terjadi saat CTO
    # tercapai; di sini cukup memanggil gatekeeper yang sama supaya top-up-nya
    # tertangkap kalau ada laba baru setelahnya.
    laba = to_decimal(fin.get("laba_bersih") or 0)
    res = distribution_mod.pastikan_otomatis(
        db, period.start_at.date().isoformat(), laba,
        cto_tercapai=bool(fin.get("cto_tercapai")),
        kas_period_id=period.id, oleh=oleh)
    out["distribusi"] = res
    db.flush()

    # ---- (4) OD-LOCK-11.5: pindahkan 30% Hak Kas Aset Laci -> Saldo Aset -----
    # Distribution terbentuk lebih awal (saat CTO tercapai) dan 70%-nya langsung
    # keluar dari Laci. Menurut Owner, 30% Hak Kas Aset TIDAK ikut waktu itu:
    # ia baru pindah posisi ke Saldo Aset di Tutup Kas ini.
    #
    # Idempotent: `pindahkan_hak_kas_aset` memindah hanya sisa yang belum
    # berpindah, jadi dipanggil lagi (mis. rekap) tidak menggeser uang dua kali.
    try:
        _row_dist = res.get("distribution") if isinstance(res, dict) else None
        if _row_dist is None:
            _row_dist = distribution_mod.sudah_ada(
                db, period.start_at.date().isoformat(), kas_period_id=period.id)
        out["hak_kas_aset"] = distribution_mod.pindahkan_hak_kas_aset(
            db, _row_dist, oleh=oleh)
    except Exception as _exc:  # noqa: BLE001
        # Gagal memindahkan Hak Kas Aset TIDAK boleh menggagalkan Tutup Kas:
        # 70% sudah keluar, dan sisa periode harus tetap bisa diselesaikan.
        out["hak_kas_aset"] = {"created": False, "error": str(_exc)}
    return out


def finance_cohort(db: Session, start, end):
    """Kohort Omzet periode ini (CASH + LUNAS + modal terisi)."""
    import finance as finance_mod
    return finance_mod.settled_orders(db, start, end)


def tutup_periode(db: Session, period, counted=None, oleh: str = None,
                  compute_finance=None, period_hour: int = 16):
    """Tutup satu periode kas. TANPA commit — pemanggil yang melakukan transaksi.

    Urutan (SEMUA dalam satu transaksi, rollback bila gagal di tengah):
      1. Laba Bersih authoritative dari financial core (P2-05).
      2. Selesaikan kewajiban kas periode: modal yang terlewat, bayar Beban
         periode, jalankan/pertahankan distribusi 10/30/30/30 (lihat
         `selesaikan_periode`). Inilah yang membuat Saldo Kas Perputaran kembali
         ke titik awal -- tidak lewat jurnal fiktif, tapi karena semua uang yang
         masuk memang ikut keluar sebagai modal, beban, atau bagi hasil.
      3. Kalau Laba Kotor tidak menutup Beban -> proses defisit (Kas Aset +
         Hutang Beban). TIDAK memaksa distribusi, TIDAK memakai DP titipan.
      4. Set Laci = uang fisik bila ada Declare (idempotent per periode).
      5. Snapshot periode (TIDAK menghapus apa pun — Q14).
      6. Tutup periode & buka periode baru 16:00 → 16:00.
    """
    from models import KasPeriod

    if (period.status or "").strip().upper() == "CLOSED":
        raise PeriodAlreadyClosed(period)

    fin = compute_finance(db, *batas_periode(period))
    periode_key = period.start_at.date().isoformat()

# ── PENYELESAIAN KAS PERIODE (FIN-MIRROR-7) ──────────────────────────────
    # Dipanggil SEBELUM Declare/rekonsiliasi, supaya angka `counted` dibandingkan
    # dengan saldo yang sudah benar-benar menyelesaikan kewajiban periode.
    #
    # Yang dilakukan: modal yang terlewat dicatat, Beban periode dibayar dari
    # Laci, dan distribusi 10/30/30/30 dipastikan terbentuk sesuai Laba Bersih.
    # Setelah itu Laci secara matematis kembali ke titik awal, karena:
    #     pelunasan = modal + beban + laba_bersih, dan laba_bersih keluar 100%
    #     (70% cash-out + 30% ke Kas Aset).
    #
    # Distribution TIDAK lagi "dibentuk diam-diam" seperti versi sebelumnya:
    # `pastikan_otomatis` sudah idempoten per periode dan HANYA menambah selisih
    # laba baru. Kalau periode defisit, gatekeeper menolak karena Laba Bersih
    # tidak positif -- jadi tidak ada distribusi paksa.
    settle = selesaikan_periode(db, period, fin, oleh=oleh)
    dist_row = settle["distribusi"].get("distribution")
    dist = dict(settle["distribusi"])
    dist.setdefault("created", False)
    dist.setdefault("alokasi", (distribution_mod.alokasi_dari(dist_row)
                                if dist_row is not None else {}))
    dist.setdefault("periode", dist_row.periode if dist_row is not None else periode_key)

    # ── DEFISIT: Laba Kotor tidak menutup Beban ───────────────────────────
    # Aturan Owner: JANGAN memaksa distribusi, JANGAN memakai DP titipan, JANGAN
    # ── DEFISIT / HUTANG BEBAN ───────────────────────────────────────────
    # OD-LOCK-12 (Owner, 2026-10-15) — ATURAN INI BERUBAH TOTAL.
    #
    # DULU: Tutup Kas otomatis memanggil `proses_defisit` begitu Laba Bersih
    # <= 0, sehingga SETIAP tutup kas yang concluded minus langsung menambah
    # Hutang Beban. Akibatnya satu periode kosong pun menambah 605.000 hutang,
    # berulang, dan saldo Hutang tumbuh tanpa henti.
    #
    # SEKARANG: Tutup Kas TIDAK membuat Hutang Beban sama sekali. Ia hanya
    # MENGUKUR dan menampilkan nilai minus di akhir Kondisi Kas Operasional.
    # Yang memutuskan besaran Hutang Beban adalah ADMIN, secara manual, satu
    # kali per periode, lewat `POST /api/kas/hutang-beban/catat`
    # (`expense_debt.catat_hutang_manual`).
    #
    # Angka yang ditawarkan ke Admin = `fin["kondisi_kas_akhir"]`, yaitu nilai
    # SALDO baris paling bawah tabel "Kondisi Kas Operasional" di halaman
    # Keuangan (dihitung satu sumber di `dashboard._kondisi_kas_akhir`).
    import expense_debt as debt_mod
    _kka = to_decimal(fin.get("kondisi_kas_akhir") or 0)
    defisit = {
        "otomatis": False,
        "kondisi_kas_akhir": str(_kka),
        "minus": str(-_kka) if _kka < ZERO else "0",
        "perlu_input_manual": bool(_kka < ZERO),
        "sudah_tercatat": bool(debt_mod.sudah_diproses(
            db, period_key(db, period.start_at, period.end_at))),
        "endpoint": "POST /api/kas/hutang-beban/catat",
        "catatan": ("Hutang Beban tidak lagi otomatis. Kalau nilai minus di "
                    "akhir Kondisi Kas Operasional, Admin yang menginput "
                    "sendiri satu kali saat Tutup Kas."),
    }
    db.flush()

    laci_adjust = rekonsiliasi_periode(db, dist_row, counted, oleh=oleh)

    # P2-15 B-2: "Selisih Laci" memakai basis LEDGER (uang fisik vs Saldo Laci),
    # sama persis dengan selisih yang benar-benar dicatat sebagai penyesuaian.
    # Sebelumnya memakai `fin["saldo"]` (akrual Buku Kas) sehingga angkanya
    # berbeda jauh dan menyesatkan di snapshot/UI.
    selisih = (laci_adjust.get("selisih") if counted is not None else None)

    snapshot = {
        "period": {"id": period.id, "start_at": period.start_at.isoformat(),
                   "end_at": period.end_at.isoformat()},
        "finance": fin,
        "cash_counted": counted,
        "selisih": (None if selisih is None else str(selisih)),
        "selisih_basis": "LEDGER LACI (counted vs Saldo Laci)",
        "distribusi": {
            "terbentuk": bool(dist.get("created")),
            "sudah_ada": not bool(dist.get("created")),
            "periode": dist.get("periode") or periode_key,
            "periode_key": (dist_row.periode if dist_row is not None else periode_key),
            # Distribusi kini terbentuk OTOMATIS saat CTO tercapai, bukan di sini.
            "trigger": dist.get("trigger") or "CTO tercapai",
            "rasio": ["10%", "30%", "30%", "30%"],
            "alokasi": {k: str(v) for k, v in (dist.get("alokasi") or {}).items()},
            "alasan_tidak_terbentuk": dist.get("alasan"),
        },
        # Jejak eksekusi uang (audit, tanpa hard delete).
        "distribusi_uang": {
            "cash_out": str(dist.get("cash_out") or 0),
            "hak_kas_aset": str((dist.get("alokasi") or {}).get("kas_aset", 0)),
            "kas_aset_setelah": str(cash.saldo_kas_aset(db)),
        },
        # FIN-MIRROR-7: jejak penyelesaian kewajiban kas periode ini.
        "penyelesaian": {
            "modal_selisih_tercatat": str(settle["modal_selisih"]),
            "beban_periode": str(fin.get("total_beban") or 0),
            "beban_dibayar_dari_laci": str(settle["beban_dibayar"]),
            "beban_belum_terbayar": str(settle["beban_sisa"]),
            "defisit": defisit,
            "laci_setelah_penyelesaian": str(cash.saldo_laci(db)),
            "catatan": "Pelunasan = Modal + Beban + Laba Bersih; Laba Bersih "
                       "keluar 100% (70% cash-out + 30% Kas Aset). Karena itu "
                       "Laci kembali ke titik awal tanpa jurnal fiktif.",
        },
        "rekonsiliasi": {"selisih": (None if laci_adjust.get("selisih") is None
                                    else str(laci_adjust["selisih"])),
                         "penyesuaian": bool(laci_adjust.get("penyesuaian")),
                         "entry_id": ((laci_adjust.get("penyesuaian") or {}).get("id")),
                         "catatan": "cash_counted = hasil hitung fisik; tidak menyuntik opening."},
        "saldo": {
            # v4: Saldo Laci (Kas Aset Kecil), Saldo Aset (Kas Aset Besar), Master Kas.
            "kas_perputaran_laci_awal": str(cash.opening_layer(db, cash.LAYER_LACI)),
            "kas_perputaran_laci": str(cash.saldo_laci(db)),
            "kas_aset": str(cash.saldo_kas_aset(db)),
            "master_kas": str(cash.master_kas(db)),
        },
    }

    now = datetime.now()
    period.status = "CLOSED"
    period.closed_at = now
    period.closed_by = oleh
    # Periode berjalan sampai DITUTUP: end_at diisi waktu penutupan yang
    # sebenarnya, bukan nilai placeholder 16:00 yang bisa sudah basi kalau
    # periode telat ditutup.
    period.end_at = now
    import json

    from money import json_default
    period.snapshot = json.dumps(snapshot, default=json_default)

    new_start, new_end = next_period_bounds(now, period_hour)
    new_period = KasPeriod(start_at=new_start, end_at=new_end, status="OPEN")
    db.add(new_period)
    db.flush()
    db.refresh(new_period)

    # P2-13: laporan tutup kas & buka kas (dalam transaksi yang sama; anti-duplikat).
    _dist_total = ZERO
    try:
        _dist_total = to_decimal((snapshot.get("distribusi") or {}).get("alokasi", {}).get("total", 0))
    except Exception:  # noqa: BLE001
        _dist_total = ZERO
    # Kunci WAJIB "omset" (bukan "omzet"): `notifications.format_pesan` membacanya
    # dengan nama itu. Dulu ditulis "omzet" sehingga Omzet di laporan Tutup Kas
    # selalu keluar Rp 0 padahal snapshot-nya benar.
    notif_mod.kirim(db, notif_mod.EVENT_LAPORAN_TUTUP_KAS, ref_type="periode",
                    ref_code=periode_key,
                    data={"periode": periode_key, "omset": fin.get("omset"),
                          "total_beban": fin.get("total_beban"),
                          "laba_bersih": fin.get("laba_bersih"),
                          "distribusi": _dist_total,
                          "kas_aset": snapshot["saldo"]["kas_aset"]},
                    actor=oleh)
    notif_mod.kirim(db, notif_mod.EVENT_LAPORAN_BUKA_KAS, ref_type="periode",
                    ref_code=new_period.start_at.date().isoformat(),
                    data={"periode": new_period.start_at.date().isoformat(),
                          "distribusi": _dist_total,
                          "kas_aset": snapshot["saldo"]["kas_aset"],
                          "laci": snapshot["saldo"]["kas_perputaran_laci_awal"]},
                    actor=oleh)

    return {"ok": True, "closed_period_id": period.id, "snapshot": snapshot,
            "distribusi": snapshot["distribusi"],
            "distribusi_uang": snapshot["distribusi_uang"],
            "rekonsiliasi": snapshot["rekonsiliasi"],
            "saldo": snapshot["saldo"],
            "new_period": {"id": new_period.id,
                           "start_at": new_period.start_at.isoformat(),
                           "end_at": new_period.end_at.isoformat()}}


class PeriodAlreadyClosed(Exception):
    """Periode sudah ditutup — eksekusi kedua harus ditolak (VR-017)."""

    def __init__(self, period):
        self.period_id = getattr(period, "id", None)
        self.closed_at = getattr(period, "closed_at", None)
        super().__init__("Periode #%s sudah ditutup" % self.period_id)