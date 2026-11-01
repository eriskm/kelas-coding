"""tools/sync_real_shop_db.py

Sinkronisasi data riil toko dari docs/Real_db/sukabumi_flasher_3_tabel.db ke servisku.db:
1. Menambahkan 11 pelanggan baru dari arsip_pelanggan ke tabel customers.
2. Memasukkan 179 garansi aktif dari arsip_garansi + 3 unit cash 1 Nov (Opsi B: historis settled)
   ke tabel service_orders dan payments di periode tertutup ID 0, sehingga muncul di menu Garansi.
3. Memasukkan 36 unit servis aktif ke tabel service_orders (status REPAIR, ANALISA, WAIT PART, DONE, FAILED, KONFIRMASI).
   Mencatat DP pada 6 unit aktif sebagai titipan customer tanpa mengganggu kas periode #1.
4. Menjaga Periode Kas #1 tetap OPEN dengan omzet Rp 0 dan kas bersih.
"""

import sqlite3
import shutil
from datetime import datetime, date, time
from decimal import Decimal

REAL_DB_PATH = r"D:\PRAKTEK MJPRO\docs\Real_db\sukabumi_flasher_3_tabel.db"
TARGET_DB_PATH = r"D:\PRAKTEK MJPRO\servisku.db"

def sync_data():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"backup-pre-realsync-{timestamp}.db"
    shutil.copyfile(TARGET_DB_PATH, backup_path)
    print(f"[BACKUP] Backup dibuat di: {backup_path}")

    db_real = sqlite3.connect(REAL_DB_PATH)
    db_real.row_factory = sqlite3.Row
    cur_r = db_real.cursor()

    db_target = sqlite3.connect(TARGET_DB_PATH)
    db_target.row_factory = sqlite3.Row
    cur_t = db_target.cursor()

    # 1. Existing Customers Map
    cur_t.execute("SELECT id, name, phone FROM customers")
    existing_cust = {}
    for r in cur_t.fetchall():
        if r["phone"]:
            existing_cust[r["phone"].strip()] = r["id"]
    print(f"[CUSTOMERS] Pelanggan terdaftar awal: {len(existing_cust)}")

    # 2. Sync 11 new customers from arsip_pelanggan
    cur_r.execute("SELECT * FROM arsip_pelanggan")
    arsip_pels = [dict(r) for r in cur_r.fetchall()]
    new_cust_count = 0
    for p in arsip_pels:
        phone = (p.get("no_wa") or "").strip()
        name = (p.get("nama_user") or "").strip() or "Pelanggan"
        if phone and phone not in existing_cust:
            cur_t.execute(
                "INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)",
                (name, phone, "2026-05-01 00:00:00")
            )
            cid = cur_t.lastrowid
            existing_cust[phone] = cid
            new_cust_count += 1
    print(f"[CUSTOMERS] Ditambahkan {new_cust_count} pelanggan baru. Total: {len(existing_cust)}")

    def get_or_create_cust(name, phone):
        phone = (phone or "").strip()
        name = (name or "").strip() or "Pelanggan"
        if phone and phone in existing_cust:
            return existing_cust[phone]
        cur_t.execute(
            "INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)",
            (name, phone if phone else None, "2026-05-01 00:00:00")
        )
        cid = cur_t.lastrowid
        if phone: existing_cust[phone] = cid
        return cid

    # 3. Periode Kas Historis CLOSED (ID: 0)
    cur_t.execute("SELECT id FROM kas_periods WHERE id = 0")
    if not cur_t.fetchone():
        cur_t.execute(
            "INSERT INTO kas_periods (id, start_at, end_at, status, closed_at, created_at) "
            "VALUES (0, '2026-01-01 00:00:00', '2026-10-31 15:59:59', 'CLOSED', '2026-10-31 15:59:59', '2026-01-01 00:00:00')"
        )
        print("[KAS_PERIOD] Dibuat KasPeriod historis CLOSED (ID 0) untuk masa lalu")

    # 4. Insert 179 Garansi Aktif sebagai ServiceOrder Historis Settled
    cur_r.execute("""
    SELECT g.id_garansi, g.id_arsip, g.nama_user, g.device, g.tgl_mulai, g.tgl_akhir,
           p.no_wa, p.tindakan, p.harga_jual, p.status_final
    FROM arsip_garansi g
    JOIN arsip_pelanggan p ON g.id_arsip = p.id_arsip
    ORDER BY g.id_garansi ASC
    """)
    warranties = [dict(r) for r in cur_r.fetchall()]

    inserted_warranties = 0
    for w in warranties:
        cid = get_or_create_cust(w["nama_user"], w["no_wa"])
        tgl_mulai = w["tgl_mulai"]
        tgl_akhir = w["tgl_akhir"]
        tgl_clean = tgl_mulai.replace("-", "")
        no_servis = f"GR-{tgl_clean}-{w['id_garansi']:04d}"

        d1 = datetime.strptime(tgl_mulai, "%Y-%m-%d")
        d2 = datetime.strptime(tgl_akhir, "%Y-%m-%d")
        months = max(1, round((d2 - d1).days / 30.0))

        price = int(w["harga_jual"] or 0)
        lunas_at = f"{tgl_mulai} 12:00:00"
        created_at = f"{tgl_mulai} 10:00:00"

        cur_t.execute("""
        INSERT INTO service_orders (
            no_servis, customer_id, device, damagetype, repair_plan, technician,
            status, unit_status, estimate, payment, service_date, final_price,
            part_cost, modal_jasa, modal_lainnya, laba_bersih, lunas_date, lunas_at,
            warranty_months, created_at, taken_at, tanpa_modal
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            'CASH', 'DIAMBIL', ?, ?, ?, ?,
            0, 0, 0, 0, ?, ?,
            ?, ?, ?, 1
        )
        """, (
            no_servis, cid, w["device"], w["tindakan"] or "Servis", w["tindakan"] or "Perbaikan", "Erik",
            price, price, tgl_mulai, price,
            tgl_mulai, lunas_at,
            months, created_at, lunas_at
        ))
        order_id = cur_t.lastrowid

        cur_t.execute("""
        INSERT INTO payments (service_order_id, kind, amount, method, created_at)
        VALUES (?, 'PELUNASAN', ?, 'CASH', ?)
        """, (order_id, price, lunas_at))

        inserted_warranties += 1
    print(f"[GARANSI] Diimpor {inserted_warranties} unit garansi aktif masa lalu")

    # 5. Insert 3 Cash Units 1 Nov sebagai Historis Settled (Opsi B)
    cur_r.execute("SELECT rowid, * FROM servis WHERE Status = 'Cash'")
    cash_orders = [dict(r) for r in cur_r.fetchall()]
    for s in cash_orders:
        rowid = s["rowid"]
        cid = get_or_create_cust(s["Nama User"], s["No. WA"])
        tgl_m = s["Tanggal Masuk"]
        tgl_clean = tgl_m.replace("-", "")
        no_servis = f"SV-{tgl_clean}-{rowid:04d}"

        w_text = s.get("masa_garansi") or "1 Bulan"
        w_months = 3 if "3" in w_text else 1

        harga_jual = int(s["Harga Jual"] or 0)
        modal_part = int(s["Modal Part"] or 0)
        modal_jasa = int(s["Modal Jasa"] or 0)
        modal_lain = int(s["Lain-lain"] or 0)
        laba_kotor = int(s["Laba Kotor"] or 0)
        tech = s["Teknisi"] if s["Teknisi"] != "-" else "Erik"
        lunas_at = "2026-10-31 15:30:00"

        cur_t.execute("""
        INSERT INTO service_orders (
            no_servis, customer_id, device, damagetype, repair_plan, technician,
            status, unit_status, estimate, payment, service_date, final_price,
            part_cost, modal_jasa, modal_lainnya, laba_bersih, lunas_date, lunas_at,
            warranty_months, created_at, taken_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            'CASH', 'DIAMBIL', ?, ?, ?, ?,
            ?, ?, ?, ?, '2026-10-31', ?,
            ?, ?, ?
        )
        """, (
            no_servis, cid, s["Device"], s["Analisa Kerusakan"], s["Tindakan Perbaikan"] or s["Tindakan"], tech,
            harga_jual, harga_jual, tgl_m, harga_jual,
            modal_part, modal_jasa, modal_lain, laba_kotor, lunas_at,
            w_months, s.get("updated_at") or lunas_at, lunas_at
        ))
        oid = cur_t.lastrowid
        cur_t.execute("""
        INSERT INTO payments (service_order_id, kind, amount, method, created_at)
        VALUES (?, 'PELUNASAN', ?, 'CASH', ?)
        """, (oid, harga_jual, lunas_at))
    print(f"[GARANSI] Diimpor {len(cash_orders)} unit CASH 1 Nov sebagai historis garansi")

    # 6. Insert 36 Active Service Orders
    cur_r.execute("SELECT rowid, * FROM servis WHERE Status != 'Cash'")
    active_orders = [dict(r) for r in cur_r.fetchall()]

    status_mapping = {
        'repair': 'REPAIR',
        'wait part': 'WAIT PART',
        'done': 'DONE',
        'failed': 'FAILED',
        'konfirmasi': 'KONFIRMASI',
        'analisa': 'ANALISA',
    }

    inserted_active = 0
    dp_count = 0
    for s in active_orders:
        rowid = s["rowid"]
        cid = get_or_create_cust(s["Nama User"], s["No. WA"])
        tgl_m = s["Tanggal Masuk"]
        tgl_clean = tgl_m.replace("-", "")
        no_servis = f"SV-{tgl_clean}-{rowid:04d}"

        raw_status = (s["Status"] or "Analisa").strip().lower()
        canon_status = status_mapping.get(raw_status, "ANALISA")

        tech = s["Teknisi"] if s["Teknisi"] and s["Teknisi"].strip() != "-" else None
        est = int(s["Estimasi Biaya"] or 0)

        raw_dp = str(s.get("DP") or "").strip()
        dp_val = int(raw_dp) if raw_dp.isdigit() else 0

        price = int(s["Harga Jual"] or 0)
        modal_part = int(s["Modal Part"] or 0)
        modal_jasa = int(s["Modal Jasa"] or 0)
        modal_lain = int(s["Lain-lain"] or 0)

        w_text = s.get("masa_garansi") or "1 Bulan"
        w_months = 3 if "3" in w_text else 1
        created_at = f"{tgl_m} 10:00:00"

        cur_t.execute("""
        INSERT INTO service_orders (
            no_servis, customer_id, device, damagetype, repair_plan, technician,
            status, unit_status, estimate, payment, service_date, final_price,
            part_cost, modal_jasa, modal_lainnya, laba_bersih,
            warranty_months, created_at, check_len, check_fisik
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, 'DI TOKO', ?, ?, ?, ?,
            ?, ?, ?, 0,
            ?, ?, '[]', '[]'
        )
        """, (
            no_servis, cid, s["Device"], s["Analisa Kerusakan"] or "Servis", s["Tindakan Perbaikan"] or s["Tindakan"], tech,
            canon_status, est, dp_val, tgl_m, price,
            modal_part, modal_jasa, modal_lain,
            w_months, created_at
        ))
        oid = cur_t.lastrowid

        if dp_val > 0:
            cur_t.execute("""
            INSERT INTO payments (service_order_id, kind, amount, method, created_at)
            VALUES (?, 'DP', ?, 'CASH', ?)
            """, (oid, dp_val, f"{tgl_m} 10:05:00"))
            dp_count += 1

        inserted_active += 1

    print(f"[PIPELINE] Diimpor {inserted_active} unit servis aktif toko ({dp_count} unit membawa titipan DP)")

    db_target.commit()
    db_target.close()
    db_real.close()
    print("[SELESAI] Sinkronisasi data riil toko berhasil 100%!")

if __name__ == "__main__":
    sync_data()
