"""Seed database. Mode operasi: JANGAN pernah membuat akun otomatis.

Data contoh (demo) TIDAK lagi diisi otomatis — diisi hanya bila env
SUKABUMI_DEMO_SEED=1, agar database produksi tidak kemasukan data dummy
saat server dijalankan via jalankan.bat.

`ensure_admin()` dulu membuat akun `superadmin` dengan passcode default yang
tertulis di source code, setiap kali username itu tidak ada. Itu pintu belakang:

  - begitu username `superadmin` diganti/dihapus, server start berikutnya akan
    MEMBUAT ULANG akun itu dengan passcode yang diketahui siapa pun yang
    membaca source code;
  - sejak SUPER ADMIN dipisah dari ADMIN (OD-LOCK-10), akun tersebut otomatis
    mendapat ROLE_CONFIG, yaitu wewenang penuh.

Sekarang fungsi ini hanya MENGECEK, tidak pernah membuat. Akun pertama dibuat
lewat `python bootstrap_superadmin.py`, yang passcode-nya diketik sendiri dan
tidak pernah dicetak.
"""
import os
import secrets
from datetime import datetime, date, timedelta

from database import SessionLocal, Base, engine
from models import Customer, ServiceOrder, Payment, User
from routers.auth import hash_passcode

#: Hanya untuk pesan peringatan. TIDAK lagi dipakai sebagai passcode.
SUPERADMIN_USERNAME = "superadmin"


def ensure_admin():
    """Cek apakah sudah ada akun admin. TIDAK pernah membuat akun baru.

    Mengembalikan (ada, canonical_role) supaya pemanggil bisa memberi
    peringatan yang berguna.
    """
    import authority as auth_mod

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for u in db.query(User).all():
            if auth_mod.canonical_role(u) in (auth_mod.ROLE_SUPERADMIN,
                                               auth_mod.ROLE_ADMIN):
                return True, auth_mod.canonical_role(u)
        return False, None
    finally:
        db.close()


def seed():
    ensure_admin()
    if os.environ.get("SUKABUMI_DEMO_SEED") != "1":
        print("Mode operasi: data contoh tidak diisi (set SUKABUMI_DEMO_SEED=1 untuk demo).")
        return
    db = SessionLocal()

    if db.query(Customer).count() > 0:
        print("Database sudah berisi data, skip seeding.")
        db.close()
        return

    customers = [
        Customer(name="Ahmad Fauzi", phone="081234567890", email="ahmad@mail.com"),
        Customer(name="Siti Nurhaliza", phone="085678901234"),
        Customer(name="Rudi Hartono", phone="087890123456"),
        Customer(name="Maya Sari", phone="082345678901"),
        Customer(name="Dedi Kurniawan", phone="083456789012"),
        Customer(name="Rina Wati", phone="084567890123"),
        Customer(name="Hendra Gunawan", phone="085678901235"),
        Customer(name="Putri Rahayu", phone="086789012345"),
        Customer(name="Fajar Nugroho", phone="087890123457"),
        Customer(name="Lestari Dewi", phone="088901234567"),
    ]
    db.add_all(customers)
    db.commit()
    for c in customers:
        db.refresh(c)

    technicians = ["Budi", "Andi", "Rizky", "Dedi"]

    orders_data = [
        # (no, cid, device, brand, model, damage, status, est, pay)
        ("SV-20260901-001", 0, "Samsung Galaxy A54", "Samsung", "A54", "Layar Pecah", "REPAIR", 450000, 0),
        ("SV-20260901-002", 1, "iPhone 14 Pro", "Apple", "14 Pro", "Baterai", "WAIT PART", 1200000, 0),
        ("SV-20260901-003", 2, "Xiaomi Redmi Note 12", "Xiaomi", "Note 12", "Charging", "REPAIR", 350000, 0),
        ("SV-20260901-004", 3, "OPPO Reno 8", "OPPO", "Reno 8", "Speaker", "DONE", 500000, 500000),
        ("SV-20260901-005", 4, "Samsung Galaxy S23", "Samsung", "S23", "Layar Pecah", "CASH", 800000, 800000),
        ("SV-20260901-006", 5, "Vivo V27", "Vivo", "V27", "Kamera", "DITERIMA", 0, 0),
        ("SV-20260901-007", 6, "iPhone 13", "Apple", "13", "Baterai", "ANALISA", 0, 0),
        ("SV-20260901-008", 7, "Realme C55", "Realme", "C55", "Charging", "KONFIRMASI", 280000, 0),
        ("SV-20260901-009", 8, "Samsung Galaxy A34", "Samsung", "A34", "Layar Pecah", "REPAIR", 400000, 0),
        ("SV-20260901-010", 9, "Xiaomi Poco X5", "Xiaomi", "Poco X5", "Baterai", "DONE", 320000, 320000),
        ("SV-20260901-011", 0, "OPPO A78", "OPPO", "A78", "Speaker", "REPAIR", 300000, 0),
        ("SV-20260901-012", 3, "iPhone 15", "Apple", "15", "Layar Pecah", "DONE", 1500000, 1500000),
    ]

    orders = []
    for i, (no, cid, device, brand, model, damage, status, est, pay) in enumerate(orders_data):
        order = ServiceOrder(
            no_servis=no,
            customer_id=customers[cid].id,
            device=device,
            brand=brand,
            model=model,
            damagetype=damage,
            technician=technicians[i % len(technicians)],
            status=status,
            estimate=est,
            payment=pay,
            service_date=date.today(),
            created_at=datetime.now() - timedelta(hours=24 - i),
        )
        orders.append(order)
    db.add_all(orders)
    db.commit()

    for o in orders:
        db.refresh(o)

    # Payment Ledger untuk order DONE (belum terealisasi) dan CASH (sudah lunas).
    paid = [(no, amt, status) for no, _, _, _, _, _, status, _, amt in orders_data
            if status in ("DONE", "CASH") and amt > 0]
    for no, amt, status in paid:
        order = next(o for o in orders if o.no_servis == no)
        db.add(Payment(service_order_id=order.id, kind="PELUNASAN", amount=amt, method="CASH",
                       note="Pelunasan (seed demo)"))
        if status == "CASH":
            # CASH = transaksi terealisasi: unit sudah diambil.
            order.unit_status = "DIAMBIL"
            order.taken_at = datetime.now()
    db.commit()

    db.close()
    print(f"Seed selesai: {len(customers)} customer, {len(orders)} service order.")


if __name__ == "__main__":
    seed()
