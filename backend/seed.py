"""Seed database. Mode operasi: hanya pastikan superadmin ada (idempotent).

Data contoh (demo) TIDAK lagi diisi otomatis — diisi hanya bila env
SUKABUMI_DEMO_SEED=1, agar database produksi tidak kemasukan data dummy
saat server dijalankan via jalankan.bat.
"""
import os
import secrets
from datetime import datetime, date, timedelta

from database import SessionLocal, Base, engine
from models import Customer, ServiceOrder, Payment, User
from routers.auth import hash_passcode

SUPERADMIN_USERNAME = "superadmin"
SUPERADMIN_PASSCODE = "Admin4100"


def ensure_admin():
    """Pastikan akun superadmin ada. Aman dipanggil tiap startup (idempotent)."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    admin = db.query(User).filter(User.username == SUPERADMIN_USERNAME).first()
    if not admin:
        salt = secrets.token_hex(16)
        db.add(
            User(
                username=SUPERADMIN_USERNAME,
                display_name="Administrator",
                role="SUPERADMIN",
                passcode_hash=hash_passcode(SUPERADMIN_PASSCODE, salt),
                passcode_salt=salt,
                active=1,
            )
        )
        db.commit()
        print("Super admin dibuat.")
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
        ("SV-20260901-001", 0, "Samsung Galaxy A54", "Samsung", "A54", "Layar Pecah", "PERBAIKAN", 450000, 0),
        ("SV-20260901-002", 1, "iPhone 14 Pro", "Apple", "14 Pro", "Baterai", "MENUNGGU SPAREPART", 1200000, 0),
        ("SV-20260901-003", 2, "Xiaomi Redmi Note 12", "Xiaomi", "Note 12", "Charging", "PERBAIKAN", 350000, 0),
        ("SV-20260901-004", 3, "OPPO Reno 8", "OPPO", "Reno 8", "Speaker", "SELESAI", 500000, 500000),
        ("SV-20260901-005", 4, "Samsung Galaxy S23", "Samsung", "S23", "Layar Pecah", "SELESAI", 800000, 800000),
        ("SV-20260901-006", 5, "Vivo V27", "Vivo", "V27", "Kamera", "DITERIMA", 0, 0),
        ("SV-20260901-007", 6, "iPhone 13", "Apple", "13", "Baterai", "DIAGNOSA", 0, 0),
        ("SV-20260901-008", 7, "Realme C55", "Realme", "C55", "Charging", "KONFIRMASI", 280000, 0),
        ("SV-20260901-009", 8, "Samsung Galaxy A34", "Samsung", "A34", "Layar Pecah", "PERBAIKAN", 400000, 0),
        ("SV-20260901-010", 9, "Xiaomi Poco X5", "Xiaomi", "Poco X5", "Baterai", "SELESAI", 320000, 320000),
        ("SV-20260901-011", 0, "OPPO A78", "OPPO", "A78", "Speaker", "PERBAIKAN", 300000, 0),
        ("SV-20260901-012", 3, "iPhone 15", "Apple", "15", "Layar Pecah", "SELESAI", 1500000, 1500000),
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

    # payment untuk yang sudah lunas (SELESAI + ada nominal)
    paid = [(no, amt) for no, _, _, _, _, _, status, _, amt in orders_data if status == "SELESAI" and amt > 0]
    for no, amt in paid:
        order = next(o for o in orders if o.no_servis == no)
        db.add(Payment(service_order_id=order.id, kind="PELUNASAN", amount=amt, method="CASH",
                       note="Pelunasan (seed demo)"))
    db.commit()

    db.close()
    print(f"Seed selesai: {len(customers)} customer, {len(orders)} service order.")


if __name__ == "__main__":
    seed()
