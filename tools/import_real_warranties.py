# -*- coding: utf-8 -*-
"""Import 182 Data Garansi Riil Toko dari database legacy ke servisku.db.

Memetakan:
  - 182 catatan garansi dari `arsip_garansi` yang terhubung ke `arsip_pelanggan`
  - 178 garansi aktif + 4 garansi jatuh tempo hari ini (30 Oktober 2026)
  - Mencocokkan nomor WhatsApp ke master tabel `customers`
  - Menyimpan transaksi servis selesai (status=CASH, unit_status=DIAMBIL, warranty_months=1 atau 3)
  - Jurnal pelunasan `payments` (agar status pembayaran valid LUNAS)
  - Riwayat tercatat di `status_history`
  - Periode arsip tertutup (id=1, Mei-Okt 2026) agar masuk ke /api/claims/warranty-summary
  - Jejak audit dicatat ke `journal_entries` (domain WARRANTY, event WARRANTY_IMPORT)
  - Idempoten: aman dijalankan berulang kali tanpa membuat duplikasi
"""
import os
import sys
import re
import sqlite3
from datetime import datetime, date, time
from decimal import Decimal

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
os.chdir(PROJECT_ROOT)

from database import SessionLocal
import models
import journal
from money import to_decimal

PRIMARY_DB = os.path.join(PROJECT_ROOT, "docs", "db", "sukabumi_flasher_full_12_tabel.db")
BACKUP_DB = r"D:\BACKUP_DB_LAMA_SUKABUMI_FLASHER\sukabumi_flasher_full_12_tabel.db"
SOURCE_DB = PRIMARY_DB if os.path.exists(PRIMARY_DB) else BACKUP_DB

MIGRATION_TAG = "Migrasi Data Garansi Toko (SF_WEB)"


def clean_phone(p):
    """Normalisasi nomor telepon ke format standar 08..."""
    if not p:
        return ""
    s = str(p).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return ""
    if digits.startswith("62"):
        digits = "0" + digits[2:]
    elif digits.startswith("8"):
        digits = "0" + digits
    return digits


def parse_brand(device_str):
    """Ekstraksi brand dan model dari nama device."""
    d = (device_str or "").strip()
    lower = d.lower()
    if "infinix" in lower:
        return "Infinix", d
    elif "redmi" in lower or "poco" in lower or "xiaomi" in lower:
        return "Xiaomi", d
    elif "samsung" in lower:
        return "Samsung", d
    elif "iphone" in lower or "apple" in lower:
        return "Apple", d
    elif "vivo" in lower:
        return "Vivo", d
    elif "oppo" in lower:
        return "Oppo", d
    elif "realme" in lower:
        return "Realme", d
    elif "tecno" in lower:
        return "Tecno", d
    elif "asus" in lower:
        return "Asus", d
    elif "sony" in lower:
        return "Sony", d
    elif "google" in lower or "pixel" in lower:
        return "Google", d
    elif "chuwi" in lower:
        return "Chuwi", d
    return "Lainnya", d


def clean_int(val):
    if val is None:
        return 0
    try:
        s = str(val).strip()
        if not s or s == "None":
            return 0
        return int(float(s))
    except Exception:
        return 0


def run_import():
    if not os.path.exists(SOURCE_DB):
        print(f"[ERROR] Source DB tidak ditemukan: {SOURCE_DB}")
        return False

    conn_src = sqlite3.connect(SOURCE_DB)
    cur_src = conn_src.cursor()
    cur_src.execute(
        """
        SELECT g.id_garansi, g.id_arsip, g.nama_user, g.device, g.tgl_mulai, g.tgl_akhir,
               p.no_wa, p.tindakan, p.harga_jual, p.status_final
        FROM arsip_garansi g
        JOIN arsip_pelanggan p ON g.id_arsip = p.id_arsip
        ORDER BY g.id_garansi ASC
        """
    )
    raw_rows = cur_src.fetchall()
    conn_src.close()

    print(f"[INFO] Membaca {len(raw_rows)} baris data dari arsip_garansi...")

    db = SessionLocal()
    try:
        # 1. Pastikan KasPeriod historis (id=1, Mei - 20 Okt 2026) ada agar order closed ter-cover
        archive_period = db.query(models.KasPeriod).filter(models.KasPeriod.id == 1).first()
        if not archive_period:
            print("[INFO] Membuat KasPeriod arsip historis (id=1) untuk menutup transaksi garansi lampau...")
            archive_period = models.KasPeriod(
                id=1,
                start_at=datetime(2026, 5, 1, 0, 0, 0),
                end_at=datetime(2026, 10, 20, 11, 42, 8),
                status="CLOSED",
            )
            db.add(archive_period)
            db.commit()

        # 2. Pembersihan idempoten: hapus order garansi yang pernah diimpor sebelumnya
        existing_w_orders = (
            db.query(models.ServiceOrder)
            .filter(models.ServiceOrder.no_servis.like("SV-%-W%"))
            .all()
        )
        if existing_w_orders:
            print(f"[WARN] Ditemukan {len(existing_w_orders)} order garansi migrasi sebelumnya. Membersihkan...")
            mig_ids = [o.id for o in existing_w_orders]
            db.query(models.Payment).filter(models.Payment.service_order_id.in_(mig_ids)).delete(synchronize_session=False)
            db.query(models.StatusHistory).filter(models.StatusHistory.service_order_id.in_(mig_ids)).delete(synchronize_session=False)
            db.query(models.ServiceOrder).filter(models.ServiceOrder.id.in_(mig_ids)).delete(synchronize_session=False)
            db.commit()
            db.expunge_all()

        # 3. Buat customer phone map
        cust_map = {}
        for c in db.query(models.Customer).all():
            if c.phone:
                cust_map[clean_phone(c.phone)] = c.id

        imported_count = 0
        active_count = 0
        today_count = 0
        today_dt = date(2026, 10, 30)

        for r in raw_rows:
            (
                gid, id_arsip, name, dev, tgl_mulai_str, tgl_akhir_str,
                raw_wa, tindakan, hj_raw, st_final
            ) = r

            ph = clean_phone(raw_wa)
            cust_id = cust_map.get(ph, 1)

            brand, model = parse_brand(dev)

            # Hitung masa garansi bulan (1 atau 3 bulan)
            try:
                dt_mulai = datetime.strptime(tgl_mulai_str.strip()[:10], "%Y-%m-%d")
                dt_akhir = datetime.strptime(tgl_akhir_str.strip()[:10], "%Y-%m-%d")
                days_diff = (dt_akhir - dt_mulai).days
                w_months = 3 if days_diff > 40 else 1
            except Exception:
                dt_mulai = datetime(2026, 8, 1, 0, 0, 0)
                dt_akhir = datetime(2026, 11, 1, 0, 0, 0)
                w_months = 3

            if dt_akhir.date() == today_dt:
                today_count += 1
            elif dt_akhir.date() > today_dt:
                active_count += 1

            srv_date = dt_mulai.date()
            tgl_code = srv_date.strftime("%Y%m%d")
            no_servis = f"SV-{tgl_code}-W{gid}"

            hj = Decimal(str(clean_int(hj_raw)))
            act_desc = (tindakan or "").strip() or "Servis Perangkat"

            order = models.ServiceOrder(
                no_servis=no_servis,
                customer_id=cust_id,
                device=dev.strip() if dev else "Smartphone",
                brand=brand,
                model=model,
                damagetype=act_desc,
                device_password=None,
                imei=None,
                check_fisik=[],
                check_len=["unit_saja"],
                repair_plan=act_desc,
                technician="Teknisi Toko",
                status="CASH",
                unit_status="DIAMBIL",
                taken_at=datetime.combine(srv_date, time(12, 0, 0)),
                estimate=hj,
                payment=hj,
                service_date=srv_date,
                final_price=hj,
                part_cost=Decimal("0"),
                modal_jasa=Decimal("0"),
                modal_lainnya=Decimal("0"),
                tanpa_modal=True,
                laba_bersih=Decimal("0"),
                lunas_date=srv_date,
                lunas_at=datetime.combine(srv_date, time(12, 0, 0)),
                warranty_months=w_months,
                created_at=datetime.combine(srv_date, time(9, 0, 0)),
            )
            db.add(order)
            db.flush()

            # Status history CASH
            sh = models.StatusHistory(
                service_order_id=order.id,
                dari_status="DONE",
                ke_status="CASH",
                oleh="Owner / Migrasi Toko",
                catatan=MIGRATION_TAG,
                waktu=order.lunas_at,
            )
            db.add(sh)

            # Payment Lunas (tanpa mutasi kas baru karena transaksi lampau sudah ditutup di masanya)
            pay_row = models.Payment(
                service_order_id=order.id,
                kind="PELUNASAN",
                amount=hj,
                method="CASH",
                note="Pelunasan servis transaksi bergaransi (SF_WEB)",
                created_at=order.lunas_at,
            )
            db.add(pay_row)

            imported_count += 1

        # Audit journal
        journal.record(
            db,
            domain="WARRANTY",
            event="WARRANTY_IMPORT",
            entity_type="warranty_claims",
            entity_id=None,
            amount=None,
            actor="Owner / Migrasi Toko",
            source=journal.SOURCE_IMPORT,
            ref_code="IMPORT-REAL-WARRANTY-182",
            details={
                "total_warranties": imported_count,
                "active_warranties": active_count,
                "expiring_today": today_count,
                "source": "arsip_garansi & arsip_pelanggan",
                "note": "Impor 182 data garansi riil toko ke sistem penjaminan dan klaim garansi",
            }
        )

        db.commit()

        print(f"[SUCCESS] Berhasil mengimpor {imported_count} data garansi riil toko.")
        print(f"[INFO] Rincian: {active_count} Garansi Aktif, {today_count} Habis Hari Ini.")
        return True

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Gagal mengimpor data garansi: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = run_import()
    sys.exit(0 if success else 1)
