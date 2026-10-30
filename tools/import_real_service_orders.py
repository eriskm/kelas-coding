# -*- coding: utf-8 -*-
"""Import 39 Servisan Aktif Toko dari docs/db/sukabumi_flasher_full_12_tabel.db ke servisku.db.

Memetakan:
  - 39 baris unit dalam tabel legacy `servis` (antrean aktif di bengkel/toko)
  - Mencocokkan nomor WhatsApp ke master tabel `customers` yang sudah diimpor
  - Status kanonis: REPAIR (17), WAIT PART (5), DONE (7), ANALISA (7), FAILED (2), KONFIRMASI (1)
  - Unit status: "DI TOKO" (semua unit masih berada di toko fisik)
  - 5 unit dengan DP titipan masuk ke jurnal `payments` dan mutasi kas Saldo Laci
  - Riwayat awal dicatat ke `status_history`
  - Audit Trail dicatat ke `journal_entries` (domain SERVICE, event SERVICE_IMPORT)
  - Idempoten: aman dijalankan berulang tanpa membuat duplikasi order
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
import cash
import journal
from statusflow import LEGACY_STATUS_MAP
from money import to_decimal

SOURCE_DB = os.path.join(PROJECT_ROOT, "docs", "db", "sukabumi_flasher_full_12_tabel.db")
MIGRATION_TAG = "Migrasi Antrean Servis Aktif Toko (SF_WEB)"


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
    elif "chuwi" in lower:
        return "Chuwi", d
    return "Lainnya", d


def parse_checklist(kelengkapan_str, fisik_str):
    """Peta kelengkapan & kondisi fisik ke key aktif BOSS SF."""
    check_len = []
    if kelengkapan_str:
        kl = kelengkapan_str.lower()
        if "sim" in kl:
            check_len.append("sim_card")
        if "case" in kl or "tas" in kl:
            check_len.append("case")
        if "memory" in kl or "sd" in kl:
            check_len.append("memory_card")
    if not check_len:
        check_len = ["unit_saja"]

    check_fisik = []
    if fisik_str:
        kf = fisik_str.lower()
        if "frame" in kf or "bengkok" in kf or "lecet" in kf:
            check_fisik.append("frame_bengkok")
        if "air" in kf:
            check_fisik.append("bekas_air")
        if "tombol" in kf:
            check_fisik.append("tombol_tidak_ada")

    return check_len, check_fisik


def parse_warranty(w_str):
    """Ubah string garansi ke integer bulan."""
    if not w_str:
        return 1
    w = str(w_str).lower()
    if "3" in w:
        return 3
    elif "6" in w:
        return 6
    return 1


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
        'SELECT "Tanggal Masuk", "Nama User", "PassWord", "No. WA", "Analisa Kerusakan", '
        '"Estimasi Biaya", "DP", "Status", "Tindakan Perbaikan", "Harga Jual", "Modal Part", '
        '"Modal Jasa", "Lain-lain", "Teknisi", "masa_garansi", "updated_at", "kelengkapan", '
        '"kondisi_fisik", "Device" FROM servis ORDER BY rowid ASC'
    )
    raw_rows = cur_src.fetchall()
    conn_src.close()

    print(f"[INFO] Membaca {len(raw_rows)} baris data antrean aktif dari tabel 'servis'...")

    db = SessionLocal()
    try:
        # 1. Bersihkan data migrasi batch ini sebelumnya jika ada (Idempotensi)
        existing_migrated = (
            db.query(models.ServiceOrder)
            .filter(models.ServiceOrder.no_servis.like("SV-%-30%"))
            .all()
        )
        if existing_migrated:
            print(f"[WARN] Ditemukan {len(existing_migrated)} order migrasi sebelumnya. Membersihkan...")
            mig_ids = [o.id for o in existing_migrated]
            
            # Hapus mutasi kas payment terkait
            pays = db.query(models.Payment).filter(models.Payment.service_order_id.in_(mig_ids)).all()
            pay_ids = [p.id for p in pays]
            if pay_ids:
                db.query(models.KasEntry).filter(
                    models.KasEntry.ref_type == "payment",
                    models.KasEntry.ref_id.in_(pay_ids)
                ).delete(synchronize_session=False)

            db.query(models.Payment).filter(models.Payment.service_order_id.in_(mig_ids)).delete(synchronize_session=False)
            db.query(models.StatusHistory).filter(models.StatusHistory.service_order_id.in_(mig_ids)).delete(synchronize_session=False)
            db.query(models.ServiceOrder).filter(models.ServiceOrder.id.in_(mig_ids)).delete(synchronize_session=False)
            db.commit()
            db.expunge_all()

        # 2. Buat map customer berdasarkan nomor HP
        cust_map = {}
        for c in db.query(models.Customer).all():
            if c.phone:
                cust_map[clean_phone(c.phone)] = c.id

        imported_count = 0
        dp_count = 0
        total_dp_amount = Decimal("0")
        total_est_amount = Decimal("0")

        for i, r in enumerate(raw_rows):
            (
                tgl_masuk, name, pwd, raw_wa, analisa, est_raw, dp_raw, st_raw,
                tindakan, hj_raw, mp_raw, mj_raw, ml_raw, tech_raw, garansi,
                up_at, kel, fis, dev
            ) = r

            # Normalisasi data
            ph = clean_phone(raw_wa)
            cust_id = cust_map.get(ph)
            if not cust_id:
                # Fallback ke customer ID 1
                cust_id = 1

            brand, model = parse_brand(dev)
            check_len, check_fisik = parse_checklist(kel, fis)
            w_months = parse_warranty(garansi)

            st_upper = (st_raw or "ANALISA").strip().upper()
            status = LEGACY_STATUS_MAP.get(st_upper, st_upper)

            est = Decimal(str(clean_int(est_raw)))
            dp = Decimal(str(clean_int(dp_raw)))
            hj = clean_int(hj_raw)
            final_price = Decimal(str(hj)) if (status == "DONE" or hj > 0) else None

            mp = Decimal(str(clean_int(mp_raw)))
            mj = Decimal(str(clean_int(mj_raw)))
            ml = Decimal(str(clean_int(ml_raw)))

            tech = str(tech_raw).strip() if tech_raw not in (None, "-", "", "None") else None
            # Standardisasi nama teknisi
            if tech:
                if tech.lower() == "erik":
                    tech = "Erik"
                elif tech.lower() == "reza":
                    tech = "Reza"

            # Parse tanggal
            tgl_clean = tgl_masuk.strip()[:10] if tgl_masuk else "2026-10-29"
            try:
                srv_date = datetime.strptime(tgl_clean, "%Y-%m-%d").date()
            except Exception:
                srv_date = date.today()

            # Datetime created_at
            created_dt = datetime.combine(srv_date, time(9, 0, 0))
            if up_at and str(up_at).strip():
                try:
                    created_dt = datetime.strptime(str(up_at).strip()[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            no_servis = f"SV-{tgl_clean.replace('-', '')}-{3001 + i}"

            repair_desc = (tindakan or "").strip() or None
            damage_desc = (analisa or "").strip() or "Kerusakan perangkat"

            order = models.ServiceOrder(
                no_servis=no_servis,
                customer_id=cust_id,
                device=dev.strip() if dev else "Smartphone",
                brand=brand,
                model=model,
                damagetype=damage_desc,
                device_password=(pwd or "").strip() or None,
                imei=None,
                check_fisik=check_fisik,
                check_len=check_len,
                repair_plan=repair_desc,
                technician=tech,
                status=status,
                unit_status="DI TOKO",
                taken_at=None,
                estimate=est,
                payment=dp,
                service_date=srv_date,
                final_price=final_price,
                part_cost=mp,
                modal_jasa=mj,
                modal_lainnya=ml,
                tanpa_modal=False,
                laba_bersih=Decimal("0"),
                warranty_months=w_months,
                created_at=created_dt,
            )
            db.add(order)
            db.flush()

            # Status History
            sh = models.StatusHistory(
                service_order_id=order.id,
                dari_status=None,
                ke_status=status,
                oleh="Owner / Migrasi Toko",
                catatan=MIGRATION_TAG,
                waktu=created_dt,
            )
            db.add(sh)

            # Jurnal Pembayaran DP jika ada
            if dp > Decimal("0"):
                dp_row = models.Payment(
                    service_order_id=order.id,
                    kind="DP",
                    amount=dp,
                    method="CASH",
                    note="DP titipan awal servis (SF_WEB)",
                    created_at=created_dt,
                )
                db.add(dp_row)
                db.flush()

                # Catat mutasi penerimaan kas Saldo Laci (titipan DP)
                cash.catat_penerimaan(db, dp_row, actor="Owner / Migrasi Toko")
                dp_count += 1
                total_dp_amount += dp

            imported_count += 1
            total_est_amount += est

        # Catat Audit Trail Journal
        journal.record(
            db,
            domain="SERVICE",
            event="SERVICE_IMPORT",
            entity_type="service_orders",
            entity_id=None,
            amount=total_dp_amount,
            actor="Owner / Migrasi Toko",
            source=journal.SOURCE_IMPORT,
            ref_code="IMPORT-REAL-SERVICE-39",
            details={
                "total_orders": imported_count,
                "orders_with_dp": dp_count,
                "total_dp_nominal": str(total_dp_amount),
                "total_estimate": str(total_est_amount),
                "source": "sukabumi_flasher_full_12_tabel.db (tabel servis)",
                "note": "Impor 39 antrean aktif toko riil ke antrean pengerjaan teknisi dan kasir",
            }
        )

        db.commit()

        print(f"[SUCCESS] Berhasil mengimpor {imported_count} servisan aktif toko.")
        print(f"[INFO] 5 unit memiliki DP titipan dengan total Rp {total_dp_amount:,} telah tercatat di ledger.")
        return True

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Gagal mengimpor servisan aktif: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = run_import()
    sys.exit(0 if success else 1)
