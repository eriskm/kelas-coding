# -*- coding: utf-8 -*-
"""Import 92 Sparepart Riil Toko dari docs/db/sukabumi_flasher_full_12_tabel.db ke servisku.db.

Memetakan:
  - data_sparepart -> Sparepart (master katalog)
  - data_sparepart -> SparepartBatch (lot FIFO batch awal, status=ACTIVE)
  - data_sparepart -> StockMove (jurnal mutasi stok MASUK, append-only)
  - Audit Trail -> journal.record (domain INVENTORY, event MASUK)
"""
import os
import sys
import sqlite3
from datetime import datetime, date
from decimal import Decimal

# Pastikan import modul backend
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database import SessionLocal
import models
import journal
from money import to_decimal

PRIMARY_DB = os.path.join(PROJECT_ROOT, "docs", "db", "sukabumi_flasher_full_12_tabel.db")
BACKUP_DB = r"D:\BACKUP_DB_LAMA_SUKABUMI_FLASHER\sukabumi_flasher_full_12_tabel.db"
SOURCE_DB = PRIMARY_DB if os.path.exists(PRIMARY_DB) else BACKUP_DB

def parse_date(date_str):
    if not date_str:
        return date.today()
    try:
        return datetime.strptime(str(date_str).strip()[:10], "%Y-%m-%d").date()
    except Exception:
        return date.today()

def run_import():
    if not os.path.exists(SOURCE_DB):
        print(f"[ERROR] Source DB tidak ditemukan: {SOURCE_DB}")
        return False

    conn_src = sqlite3.connect(SOURCE_DB)
    c_src = conn_src.cursor()
    raw_rows = c_src.execute(
        "SELECT id_sparepart, kategori, merek, jenis_barang, jenis_device, qty, tanggal_masuk, harga_beli, harga_jual "
        "FROM data_sparepart ORDER BY id_sparepart ASC"
    ).fetchall()
    conn_src.close()

    print(f"[INFO] Membaca {len(raw_rows)} baris data dari data_sparepart...")

    db = SessionLocal()
    try:
        # Cek kondisi eksisting
        existing_count = db.query(models.Sparepart).count()
        if existing_count > 0:
            print(f"[WARN] Tabel spareparts sudah memiliki {existing_count} data.")
            print("[INFO] Membersihkan spareparts dan batches lama sebelum impor riil...")
            db.query(models.StockMove).filter(models.StockMove.keterangan == "Saldo Awal Stok Toko Riil (SF_WEB)").delete(synchronize_session=False)
            db.query(models.SparepartBatch).delete(synchronize_session=False)
            db.query(models.Sparepart).delete(synchronize_session=False)
            db.commit()

        imported_parts = 0
        imported_qty = 0
        total_valuation = Decimal("0")
        total_sales_value = Decimal("0")

        for r in raw_rows:
            id_legacy, kat, mrk, jns, dev, qty, tgl_str, hb, hj = r
            
            tgl = parse_date(tgl_str)
            qty_int = int(qty or 0)
            hb_dec = to_decimal(hb or 0)
            hj_dec = to_decimal(hj or 0)

            kat_clean = (kat or "").strip()
            if kat_clean.lower() == "batre":
                kat_clean = "Baterai"

            # 1. Master Sparepart
            sp = models.Sparepart(
                kategori=kat_clean or None,
                merek=(mrk or "").strip() or None,
                jenis=(jns or "").strip(),
                device=(dev or "").strip() or None,
                qty=qty_int,
                harga_beli=hb_dec,
                harga_jual=hj_dec,
                tanggal=tgl,
                created_at=datetime.combine(tgl, datetime.min.time()) if tgl else datetime.now(),
            )
            db.add(sp)
            db.flush()  # dapatkan sp.id

            # 2. FIFO Lot Batch
            batch = models.SparepartBatch(
                sparepart_id=sp.id,
                supplier=(mrk or "").strip() or "Stok Awal Toko",
                harga_beli=hb_dec,
                harga_jual=hj_dec,
                qty_masuk=qty_int,
                qty_sisa=qty_int,
                tanggal_masuk=tgl,
                status="ACTIVE",
                created_at=datetime.combine(tgl, datetime.min.time()) if tgl else datetime.now(),
            )
            db.add(batch)
            db.flush()

            # 3. Stock Move (Audit Trail MASUK)
            move = models.StockMove(
                sparepart_id=sp.id,
                aksi="MASUK",
                qty=qty_int,
                qty_sebelum=0,
                qty_sesudah=qty_int,
                selisih=qty_int,
                keterangan="Saldo Awal Stok Toko Riil (SF_WEB)",
                oleh="Owner / Migrasi Toko",
                waktu=datetime.combine(tgl, datetime.min.time()) if tgl else datetime.now(),
            )
            db.add(move)
            db.flush()

            # 4. Journal Entry (Audit Log)
            journal.record(
                db,
                domain=journal.DOMAIN_INVENTORY,
                event="MASUK",
                entity_type="stock_move",
                amount=None,
                actor="Owner / Migrasi Toko",
                ref_type="sparepart",
                ref_code=str(sp.id),
                details={
                    "aksi": "MASUK",
                    "qty": qty_int,
                    "qty_sebelum": 0,
                    "qty_sesudah": qty_int,
                    "keterangan": f"Saldo Awal: {sp.kategori} - {sp.jenis} ({sp.merek})",
                    "batch_id": batch.id,
                },
            )

            imported_parts += 1
            imported_qty += qty_int
            total_valuation += (hb_dec * qty_int)
            total_sales_value += (hj_dec * qty_int)

        db.commit()

        print("=" * 60)
        print("[SUKSES] Impor Stok Sparepart Riil Berhasil Diselesaikan!")
        print(f"  - Total Master Sparepart: {imported_parts} jenis")
        print(f"  - Total Kuantitas Fisik: {imported_qty} pcs")
        print(f"  - Total Valuasi Modal (Beli): Rp {total_valuation:,.2f}")
        print(f"  - Total Estimasi Nilai Jual: Rp {total_sales_value:,.2f}")
        print("=" * 60)
        return True

    except Exception as e:
        db.rollback()
        print(f"[FATAL ERROR] Gagal melakukan impor: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    run_import()
