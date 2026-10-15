# -*- coding: utf-8 -*-
"""Owner -- Revisi Detail Halaman Garansi.

Tiga informasi tambahan di detail garansi yang SUDAH ADA:

1. Identitas Unit: Merek HP, Model HP, IMEI -- dari data unit servis
   sebelumnya. Tidak boleh membuat input baru atau menduplikasi data.
2. Riwayat Klaim Garansi: tanggal klaim, keluhan pelanggan, hasil pemeriksaan
   atau keputusan klaim, tindakan perbaikan. Dari riwayat yang benar-benar
   tersimpan. Kalau belum ada klaim: "Belum ada riwayat klaim garansi."
3. Teknisi yang menangani: dari penugasan teknisi pada transaksi terkait.

Batasan yang dijaga test:
  - informasi garansi lama tidak hilang;
  - alur bisnis, aturan garansi, dan struktur database tidak berubah;
  - data yang tidak tersedia ditampilkan jujur, tidak dikarang.
"""
from datetime import date, datetime, timedelta

import pytest


def _pelanggan(db):
    """Satu pelanggan dipakai bersama seluruh test di file ini."""
    import models as m

    c = db.query(m.Customer).filter(m.Customer.name == "Pelanggan Garansi").first()
    if c is None:
        c = m.Customer(name="Pelanggan Garansi", phone="08001234",
                       created_at=datetime.now())
        db.add(c)
        db.commit()
        db.expire_all()
    return c


@pytest.fixture()
def db():
    from database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    # `StaticPool` WAJIB untuk SQLite in-memory: tanpa itu tiap koneksi
    # mendapat database yang berbeda, sehingga `create_all` menulis ke satu DB
    # dan query membaca DB lain -> "no such table".
    # `create_all` hanya membuat tabel untuk model yang SUDAH di-import saat
    # dipanggil. Import dulu, kalau tidak metadata-nya kosong dan hasilnya
    # "no such table".
    import models  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    assert "customers" in Base.metadata.tables, "metadata harus terisi"
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def _unit(db, kode="W-1", **kw):
    """Unit CASH + LUNAS + periodenya sudah DITUTUP.

    `warranty_summary` hanya menampilkan unit yang pembayarannya LUNAS dan
    periode kasnya sudah CLOSED (garansi menunggu Tutup Kas), jadi test harus
    menyiapkan keduanya supaya unitnya benar-benar muncul.
    """
    import models as m
    from money import to_decimal

    c = _pelanggan(db)
    o = m.ServiceOrder(
        no_servis=kode, customer_id=c.id, device="Samsung A31", status="CASH",
        unit_status="DIAMBIL", service_date=date.today(),
        taken_at=datetime.now(), final_price=500000, estimate=500000,
        repair_plan="Ganti LCD", warranty_months=3,
        lunas_at=datetime.now() - timedelta(days=1, hours=12),
        created_at=datetime.now(),
        **kw)
    db.add(o)
    db.flush()
    # Pelunasan penuh supaya terbaca LUNAS lewat journal payments.
    db.add(m.Payment(service_order_id=o.id, kind="PELUNASAN",
                     amount=to_decimal(500000), method="CASH",
                     created_at=datetime.now()))
    # Periode kas yang sudah ditutup, memuat momen pelunasan.
    db.add(m.KasPeriod(start_at=datetime.now() - timedelta(days=2),
                       end_at=datetime.now() - timedelta(days=1),
                       status="CLOSED"))
    db.commit()
    db.expire_all()
    return db.query(m.ServiceOrder).filter(m.ServiceOrder.id == o.id).one()


def _klaim(db, order, tanggal=None, **kw):
    import models as m

    defaults = dict(complaint="Layar pecah", inspection_result="Segel utuh",
                    action_needed="Ganti LCD", decision="DITERIMA",
                    claim_status="MASUK", technician="Reza",
                    warranty_days=90, created_at=datetime.now())
    defaults.update(kw)
    c = m.WarrantyClaim(
        claim_no="CLM-" + str(order.id) + "-" + str((tanggal or date.today()).isoformat()),
        service_order_id=order.id, customer_id=order.customer_id,
        claim_date=tanggal or date.today(), **defaults)
    db.add(c)
    db.commit()
    db.expire_all()
    return db.query(m.WarrantyClaim).filter(m.WarrantyClaim.id == c.id).one()


# ───────────────── (1) Identitas unit ─────────────────
def test_identitas_unit_dari_servis_sebelumnya(db):
    from routers.claims import warranty_summary

    _unit(db, brand="Samsung", model="SM-A315F", imei="352099001761481")
    data = warranty_summary(db)
    assert data["items"], "unit harus masuk daftar garansi"
    g = data["items"][0]
    assert g["brand"] == "Samsung"
    assert g["model"] == "SM-A315F"
    assert g["imei"] == "352099001761481"


def test_identitas_unit_kosong_tidak_dikarang(db):
    """Tidak ada nilai --> backend kirim null, UI yang jujur menampilkannya."""
    from routers.claims import warranty_summary

    _unit(db, brand=None, model=None, imei=None)
    g = warranty_summary(db)["items"][0]
    assert g["brand"] is None
    assert g["model"] is None
    assert not g["imei"]


def test_tidak_ada_kolom_baru_untuk_data_ini():
    """Data harus dari kolom yang SUDAH ada, bukan kolom baru."""
    import models as m

    kolom = set(c.name for c in m.ServiceOrder.__table__.columns)
    for perlu in ("brand", "model", "imei", "technician"):
        assert perlu in kolom, "kolom %s harus sudah ada" % perlu


def test_field_baru_adalah_penambahan_saja():
    """API lama harus tetap utuh (tidak ada yang dihapus/berubah)."""
    src = open(r"D:\PRAKTEK MJPRO\backend\routers\claims.py",
               encoding="utf-8").read()
    for lama in ('"service_order_id": o.id', '"no": o.no_servis',
                 '"nama": nm', '"phone": ph,', '"device": o.device',
                 '"mulai": mulai.isoformat()', '"akhir": akhir.isoformat()',
                 '"damage": o.damagetype', '"plan": o.repair_plan'):
        assert lama in src, "field lama hilang: %s" % lama


# ───────────────── (3) Teknisi ─────────────────
def test_teknisi_dari_penugasan_servis(db):
    from routers.claims import warranty_summary

    _unit(db, technician="Reza")
    assert warranty_summary(db)["items"][0]["teknisi"] == "Reza"


def test_teknisi_kosong_tidak_dikarang(db):
    from routers.claims import warranty_summary

    _unit(db, technician=None)
    assert warranty_summary(db)["items"][0]["teknisi"] is None


# ───────────────── (2) Riwayat klaim ─────────────────
def test_tidak_ada_klaim_menghasilkan_daftar_kosong(db):
    from routers.claims import warranty_summary

    _unit(db)
    g = warranty_summary(db)["items"][0]
    assert g["riwayat_klaim"] == [], "tidak boleh ada riwayat fiktif"


def test_riwayat_klaim_memuat_yang_diminta(db):
    from routers.claims import warranty_summary

    o = _unit(db, technician="Reza")
    _klaim(db, o, tanggal=date(2026, 3, 1))
    riwayat = warranty_summary(db)["items"][0]["riwayat_klaim"]
    assert len(riwayat) == 1
    r = riwayat[0]
    for kunci in ("tanggal", "keluhan", "hasil_pemeriksaan", "keputusan",
                  "tindakan"):
        assert kunci in r, "riwayat klaim kurang kolom: %s" % kunci
    assert r["keluhan"] == "Layar pecah"
    assert r["hasil_pemeriksaan"] == "Segel utuh"
    assert r["keputusan"] == "DITERIMA"
    assert r["tindakan"] == "Ganti LCD"


def test_riwayat_klaim_berurutan_terbaru(db):
    from routers.claims import warranty_summary

    o = _unit(db)
    _klaim(db, o, tanggal=date(2026, 1, 5), complaint="Keluhan lama")
    _klaim(db, o, tanggal=date(2026, 6, 5), complaint="Keluhan baru")
    riwayat = warranty_summary(db)["items"][0]["riwayat_klaim"]
    assert len(riwayat) == 2
    assert riwayat[0]["tanggal"] == "2026-06-05", "terbaru harus di atas"
    assert riwayat[1]["tanggal"] == "2026-01-05"


def test_riwayat_klaim_tidak_mencampur_unit_lain(db):
    """Klaim unit lain tidak boleh bocor ke garansi ini."""
    from routers.claims import warranty_summary

    o1 = _unit(db, kode="W-1")
    o2 = _unit(db, kode="W-2")
    _klaim(db, o2, complaint="Keluhan unit lain")
    g1 = next(x for x in warranty_summary(db)["items"] if x["no"] == "W-1")
    assert g1["riwayat_klaim"] == []


def test_klaim_yang_sudah_tersimpan_masih_utuh(db):
    """Menambah riwayat TIDAK boleh mengubah data klaim aslinya."""
    import models as m

    o = _unit(db)
    c = _klaim(db, o, complaint="Asli")
    from routers.claims import warranty_summary

    warranty_summary(db)
    db.expire_all()
    again = db.query(m.WarrantyClaim).filter(m.WarrantyClaim.id == c.id).one()
    assert again.complaint == "Asli"


# ───────────────── UI ─────────────────
def _html():
    return open(r"D:\PRAKTEK MJPRO\frontend\index.html", encoding="utf-8").read()


def _js():
    return open(r"D:\PRAKTEK MJPRO\frontend\script.js", encoding="utf-8").read()


def test_konten_baru_ada_di_html():
    html = _html()
    for wajib in ("warrantyUnit", "warrantyTeknisi", "warrantyRiwayat"):
        assert wajib in html, "container %s belum ada" % wajib


def test_konten_lama_tetap_ada():
    """Informasi garansi yang sudah ada tidak boleh hilang."""
    html = _html()
    for lama in ("warrantySummary", "warrantyDetail", "warrantyClaim"):
        assert lama in html, "container lama hilang: %s" % lama
    js = _js()
    for teks in ("No. Servis", "Tgl Mulai", "Tgl Akhir",
                 "Kerusakan Sebelumnya", "Rencana Perbaikan", "Nilai Servis"):
        assert teks in js, "baris lama hilang: %s" % teks


def test_label_yang_diminta_ada():
    js = _js()
    assert "Belum ada riwayat klaim garansi." in js, \
        "keterangan untuk garansi tanpa klaim wajib ada"
    for label in ("Merek HP", "Model HP", "IMEI",
                  "Keluhan Pelanggan", "Hasil Pemeriksaan",
                  "Keputusan Klaim", "Tindakan Perbaikan",
                  "Teknisi Penanggung Jawab"):
        assert label in js, "label wajib: %s" % label


def test_tidak_ada_input_baru_untuk_data_baru():
    """Tidak boleh menambah form input baru -- ini tampilan baca saja."""
    html = _html()
    blok = html.split('id="warrantyUnit"')[1][:600]
    assert "<input" not in blok, "Identitas Unit harus baca saja, bukan input"
    blok2 = html.split('id="warrantyTeknisi"')[1][:400]
    assert "<input" not in blok2, "Teknisi harus baca saja"
    blok3 = html.split('id="warrantyRiwayat"')[1][:400]
    assert "<input" not in blok3, "Riwayat klaim harus baca saja"


def test_data_kosong_menampilkan_belum_disi():
    """Nilai kosong harus jujur, bukan string kosong atau angka palsu."""
    js = _js()
    assert "const kosong = 'Belum diisi';" in js, \
        "nilai kosong harus punya keterangan yang jelas"
    assert "(g.brand || '').trim() || kosong" in js
    assert "(g.imei || '').trim() || kosong" in js
    assert "(g.teknisi || '').trim() || kosong" in js


def test_nilai_kosong_disembunyikan_bukan_dikarang():
    js = _js()
    # Catatan teknisi hanya tampil kalau ada isinya.
    assert "${r.catatan_teknisi ?" in js, \
        "catatan kosong tidak boleh jadi baris kosong"


def test_frontend_membaca_field_baru():
    js = _js()
    # Mapping harus pass-through apa adanya: nilai dari backend, bukan
    # ditimpa nilai lain di frontend.
    for pasangan in ("brand: g.brand", "model: g.model", "imei: g.imei",
                     "teknisi: g.teknisi",
                     "riwayat_klaim: Array.isArray(g.riwayat_klaim)"):
        assert pasangan in js, "mapping frontend harus: %s" % pasangan
    # Larangan: jangan pernah diisi nilai tetap di frontend.
    for karangan in ('brand: "', 'model: "', 'imei: "', 'teknisi: "'):
        assert karangan not in js, \
            "field identitas tidak boleh dikarang di frontend: %s" % karangan


def test_tidak_ada_endpoint_baru():
    """Batasan: jangan menambah API kalau tidak diperlukan."""
    src = open(r"D:\PRAKTEK MJPRO\backend\routers\claims.py",
               encoding="utf-8").read()
    sebelum = src.count("@router.get(")
    assert sebelum == 6, \
        "jumlah endpoint GET claims.py tidak boleh berubah, dapat %d" % sebelum


def test_tidak_ada_migrasi_database():
    """Struktur database tidak boleh berubah."""
    import models as m

    kolom_claim = set(c.name for c in m.WarrantyClaim.__table__.columns)
    # Tidak ada kolom baru untuk unit/riwayat.
    untuk_baru = {"brand", "model", "riwayat", "claim_history"}
    assert untuk_baru.isdisjoint(kolom_claim), \
        "WarrantyClaim tidak boleh menambah kolom baru: %s" % (
            untuk_baru & kolom_claim)