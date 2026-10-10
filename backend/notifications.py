# -*- coding: utf-8 -*-
"""P2-13 — Notification (WA/Telegram) dengan ANTI-DUPLIKAT (FIX-30) + journal.

Scope P2-13 (roadmap):
  (a) event: unit baru, kas masuk, laporan tutup kas, laporan buka kas;
  (b) anti-duplikat: jendela waktu per `dedup_key` (log-based, ADAPT `milestone_logs` A);
  (c) WA "Selesai" dicatat di journal (OD-019);
  (d) provider/format = ID-10 (implementation detail): provider Telegram seperti A,
      tujuan dari env `NOTIF_PRIVATE_ID`, format teks sederhana.

Yang dijaga:
- **Tidak ada pengiriman ke luar saat provider nonaktif** (default). Notifikasi
  selalu dicatat (outbox + journal) sehingga audit tetap ada tanpa efek jaringan —
  ini juga yang membuat verifikasi tidak pernah mengirim pesan sungguhan.
- **Tidak ada** event milestone CTS/CTO/CTH (Q6: milestone bukan trigger distribusi).
- Tidak ada `commit` di modul: pemanggil (router/domain) yang mengatur transaksi →
  notifikasi ikut commit/rollback bersama perubahan bisnisnya (atomik).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import journal
from money import ZERO, to_decimal

EVENT_UNIT_BARU = "UNIT_BARU"
EVENT_KAS_MASUK = "KAS_MASUK"
EVENT_LAPORAN_TUTUP_KAS = "LAPORAN_TUTUP_KAS"
EVENT_LAPORAN_BUKA_KAS = "LAPORAN_BUKA_KAS"
EVENT_WA_SELESAI = "WA_SELESAI"

EVENTS = (EVENT_UNIT_BARU, EVENT_KAS_MASUK, EVENT_LAPORAN_TUTUP_KAS,
          EVENT_LAPORAN_BUKA_KAS, EVENT_WA_SELESAI)

STATUS_DIANTREKAN = "DIANTREKAN"
STATUS_SKIPPED_DUPLIKAT = "SKIPPED_DUPLIKAT"
STATUS_TERKIRIM = "TERKIRIM"
STATUS_GAGAL = "GAGAL"

JOURNAL_EVENT = "NOTIFIKASI_TERKIRIM"
JOURNAL_EVENT_WA = "WA_SELESAI_DICATAT"

#: Jendela anti-duplikat per event (menit) — implementation detail ID-10.
JENDELA_MENIT = {
    EVENT_UNIT_BARU: 30,
    EVENT_KAS_MASUK: 30,
    EVENT_LAPORAN_TUTUP_KAS: 60,
    EVENT_LAPORAN_BUKA_KAS: 60,
    EVENT_WA_SELESAI: 60,
}

PROVIDER_DEFAULT = "TELEGRAM"

#: Provider eksternal TIDAK aktif secara default (aman untuk production test).
ENV_AKTIF = "NOTIF_PROVIDER_ENABLED"


def provider_aktif() -> bool:
    """True hanya bila Owner mengaktifkan pengiriman eksternal lewat env."""
    return (os.environ.get(ENV_AKTIF, "") or "").strip().lower() in ("1", "true", "yes", "on")


def tujuan_default() -> str:
    return (os.environ.get("NOTIF_PRIVATE_ID", "") or "").strip()


def _rupiah(v) -> str:
    try:
        return "Rp " + "{:,.0f}".format(float(to_decimal(v))).replace(",", ".")
    except Exception:  # noqa: BLE001
        return "Rp 0"


def format_pesan(event: str, data: dict = None) -> str:
    """Format pesan (ID-10). Teks polos — aman untuk semua provider."""
    d = data or {}
    if event == EVENT_UNIT_BARU:
        return ("UNIT BARU MASUK\n"
                "No: %s\nDevice: %s\nPelanggan: %s\nAnalisa: %s\nTindakan: %s"
                % (d.get("no_servis") or "-", d.get("device") or "-",
                   d.get("customer") or "-", d.get("analisa") or "-",
                   d.get("tindakan") or "-"))
    if event == EVENT_KAS_MASUK:
        return ("KAS MASUK (UNIT SELESAI)\n"
                "No: %s\nDevice: %s\nPelanggan: %s\nTeknisi: %s\nHarga: %s"
                % (d.get("no_servis") or "-", d.get("device") or "-",
                   d.get("customer") or "-", d.get("technician") or "-",
                   _rupiah(d.get("harga_jual", 0))))
    if event == EVENT_WA_SELESAI:
        return ("UNIT SELESAI — WA pelanggan (OD-019)\n"
                "No: %s\nDevice: %s\nPelanggan: %s\nNo. WA: %s\nStatus: SELESAI"
                % (d.get("no_servis") or "-", d.get("device") or "-",
                   d.get("customer") or "-", d.get("no_wa") or "-"))
    if event == EVENT_LAPORAN_TUTUP_KAS:
        return ("LAPORAN TUTUP KAS\nPeriode: %s\nOmzet: %s\nBeban: %s\n"
                "Laba Bersih: %s\nDistribusi: %s\nKas Aset: %s"
                % (d.get("periode") or "-", _rupiah(d.get("omset", 0)),
                   _rupiah(d.get("total_beban", 0)), _rupiah(d.get("laba_bersih", 0)),
                   _rupiah(d.get("distribusi", 0)), _rupiah(d.get("kas_aset", 0))))
    if event == EVENT_LAPORAN_BUKA_KAS:
        return ("LAPORAN BUKA KAS\nPeriode: %s (16:00 → 16:00)\n"
                "Distribusi: %s\nKas Aset: %s\nLaci: %s"
                % (d.get("periode") or "-", _rupiah(d.get("distribusi", 0)),
                   _rupiah(d.get("kas_aset", 0)), _rupiah(d.get("laci", 0))))
    return "%s %s" % (event, d or "")


def dedup_key(event: str, ref_type: str, ref_code) -> str:
    return "%s:%s:%s" % (event, ref_type or "-", ref_code or "-")


def sudah_dikirim(db: Session, key: str, window_menit: int, now: datetime = None):
    """Cek anti-duplikat FIX-30: ada notif dengan key sama dalam jendela waktu."""
    from models import Notification
    now = now or datetime.now()
    cutoff = now - timedelta(minutes=max(0, int(window_menit or 0)))
    return (db.query(Notification)
            .filter(Notification.dedup_key == key,
                    Notification.status != STATUS_SKIPPED_DUPLIKAT,
                    Notification.created_at >= cutoff)
            .order_by(Notification.id.desc()).first())


def kirim(db: Session, event: str, ref_type: str = None, ref_code=None,
          data: dict = None, actor: str = None, window_menit: int = None,
          now: datetime = None, force: bool = False) -> dict:
    """Catat notifikasi (outbox + journal) dengan anti-duplikat.

    Returns dict: {'status', 'id', 'dedup_key', 'pesan', 'provider_aktif'}.
    Tidak melakukan commit — konsisten dengan transaksi pemanggil.
    """
    from models import Notification

    if event not in EVENTS:
        raise ValueError("Event notifikasi tidak dikenal: %s" % event)

    key = dedup_key(event, ref_type, ref_code)
    window = window_menit if window_menit is not None else JENDELA_MENIT.get(event, 30)
    now = now or datetime.now()

    if not force:
        dup = sudah_dikirim(db, key, window, now)
        if dup is not None:
            return {"status": STATUS_SKIPPED_DUPLIKAT, "id": None, "dedup_key": key,
                    "pesan": dup.pesan, "provider_aktif": provider_aktif(),
                    "sebelum_id": dup.id}

    pesan = format_pesan(event, data)
    row = Notification(event=event, ref_type=ref_type, ref_code=(str(ref_code) if ref_code is not None else None),
                       dedup_key=key, provider=PROVIDER_DEFAULT,
                       tujuan=tujuan_default(), pesan=pesan,
                       status=(STATUS_DIANTREKAN if not provider_aktif() else STATUS_TERKIRIM),
                       actor=actor)
    db.add(row)
    db.flush()
    db.refresh(row)

    journal.record(db, journal.DOMAIN_SYSTEM, JOURNAL_EVENT,
                   entity_type="notification", entity_id=row.id, amount=None, actor=actor,
                   ref_type=ref_type, ref_code=(str(ref_code) if ref_code is not None else None),
                   details={"event": event, "dedup_key": key,
                            "status": row.status, "provider": PROVIDER_DEFAULT,
                            "provider_aktif": provider_aktif()})
    db.flush()
    return {"status": row.status, "id": row.id, "dedup_key": key, "pesan": pesan,
            "provider_aktif": provider_aktif()}


def catat_wa_selesai(db: Session, order, actor: str = None, now: datetime = None) -> dict:
    """OD-019: status 'Selesai' dicatat di journal (bukan hanya di layar)."""
    customer = getattr(order, "customer", None)
    res = kirim(db, EVENT_WA_SELESAI, ref_type="service_order", ref_code=order.id,
                data={"no_servis": order.no_servis, "device": order.device,
                      "customer": getattr(customer, "name", None),
                      "no_wa": getattr(customer, "no_wa", None) or getattr(customer, "phone", None)},
                actor=actor, now=now)
    # OD-019 dicatat SATU kali per unit; pemanggilan duplikat (anti-duplikat)
    # tidak menambah journal history baru.
    if res.get("status") != STATUS_SKIPPED_DUPLIKAT:
        journal.record(db, journal.DOMAIN_SYSTEM, JOURNAL_EVENT_WA,
                       entity_type="service_order", entity_id=order.id, amount=None,
                       actor=actor, ref_type="NO_SERVIS", ref_code=(order.no_servis or None),
                       details={"event": "WA_SELESAI", "notif_id": res.get("id"),
                                "dedup_key": res.get("dedup_key")})
    db.flush()
    return res


def daftar(db: Session, event: str = None, limit: int = 100):
    """Log notifikasi (read-only)."""
    from models import Notification
    q = db.query(Notification)
    if event:
        q = q.filter(Notification.event == event)
    rows = q.order_by(Notification.id.desc()).limit(max(1, min(500, int(limit or 100)))).all()
    return [{"id": r.id, "event": r.event, "ref_type": r.ref_type, "ref_code": r.ref_code,
             "dedup_key": r.dedup_key, "provider": r.provider, "tujuan": r.tujuan,
             "status": r.status, "actor": r.actor, "created_at": r.created_at,
             "pesan": r.pesan} for r in rows]