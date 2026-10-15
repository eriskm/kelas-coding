# -*- coding: utf-8 -*-
"""Buat SATU akun Super Admin (Developer) tanpa menyentuh akun yang sudah ada.

Kenapa skrip, bukan tombol di UI:
    Home dengan role ADMIN. Owner memisahkan Super Admin dari Manager Toko
    dan dengan sengaja menutup jalan agar PERMISSION Super Admin tidak bisa
    diberikan oleh Manager Toko. Kalau pembuatan akun Super Admin lewat API
    biasa, Admin bisa membuat akun itu sendiri dan naikkan dirinya -- persis
    privilege escalation yang harus dicegah.

    Jadi account pertama harus dibuat di luar aplikasi, oleh orang yang sudah
    memegang akses mesin (file database). Setelah ada, mekanisme normal: akun
    itu yang membuat akun Super Admin berikutnya lewat Kelola Akun.

Ketentuan yang dijaga:
  - ❌ Tidak mengubah, tidak meng-nonaktifkan, tidak menghapus akun yang ada.
  - ❌ Tidak menyalin passcode dari akun mana pun.
  - ❌ Tidak pernah MENAMPILKAN atau mencatat passcode/token. Passcode
    diketik sendiri di terminal dan tidak bergema.
  - ✅ Satu kali saja: berhenti kalau sudah ada akun Super Admin.
  - ✅ Semua proses tercatat ke journal `AKUN_DIBUAT`.

Pemakaian:
    cd D:\\PRAKTEK MJPRO\\backend
    python bootstrap_superadmin.py --username dev --nama "Nama Developer"
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal  # noqa: E402
from models import User  # noqa: E402

#: Sama dengan aturan create_user di routers/auth.py (minimal 4). Dulu
#: skrip ini mewajibkan 12 karakter -- lebih ketat dari aplikasi sendiri dan
#: tidak punya alasan bisnis. Disamakan supaya aturannya konsisten.

MIN_PASSCODE = 4


def _sudah_ada_superadmin(db) -> bool:
    import authority as auth_mod

    for u in db.query(User).all():
        if auth_mod.canonical_role(u) == auth_mod.ROLE_SUPERADMIN:
            return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Buat akun Super Admin pertama (satu kali saja).")
    ap.add_argument("--username", required=True,
                    help="username unik untuk akun developer")
    ap.add_argument("--nama", required=True, help="nama yang tampil")
    args = ap.parse_args(argv)

    username = (args.username or "").strip()
    nama = (args.nama or "").strip()
    if not username or not nama:
        print("Username dan nama wajib diisi.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        if _sudah_ada_superadmin(db):
            print("BERHENTI: sudah ada akun Super Admin. Skrip ini hanya untuk "
                  "pembuatan pertama.", file=sys.stderr)
            return 1
        if db.query(User).filter(User.username == username).first():
            print("BERHENTI: username sudah dipakai. Pilih yang lain.",
                  file=sys.stderr)
            return 1

        # Passcode TIDAK pernah dicetak. Operator mengetiknya sendiri.
        passcode = getpass.getpass("Passcode untuk akun Super Admin "
                                   "(tidak akan ditampilkan): ")
        if len(passcode) < MIN_PASSCODE:
            print("Passcode terlalu pendek (minimal %d karakter)." % MIN_PASSCODE,
                  file=sys.stderr)
            return 2
        ulang = getpass.getpass("Ulangi passcode: ")
        if passcode != ulang:
            print("Passcode tidak cocok.", file=sys.stderr)
            return 2

        import secrets

        from routers.auth import hash_passcode

        salt = secrets.token_hex(16)
        user = User(username=username, display_name=nama,
                    role="SUPERADMIN",
                    passcode_hash=hash_passcode(passcode, salt),
                    passcode_salt=salt, active=1)
        db.add(user)
        db.commit()
        db.refresh(user)

        # Jejak audit. Password TIDAK ikut dicatat.
        try:
            import journal

            from routers.auth import (DOMAIN_AKUN, EVENT_AKUN_DIBUAT)

            journal.record(
                db, DOMAIN_AKUN, EVENT_AKUN_DIBUAT,
                entity_type="user", entity_id=user.id,
                actor="bootstrap-superadmin", source="system",
                ref_type="user", ref_code=user.username,
                details={"perubahan": {"role": ["", "SUPERADMIN"],
                                       "active": ["", 1],
                                       "display_name": ["", nama]},
                         "catatan": "pembuatan akun Super Admin pertama; "
                                    "passcode tidak dicatat"})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            print("Peringatan: akun dibuat, tetapi pencatatan journal gagal: %s"
                  % exc, file=sys.stderr)

        print("")
        print("Akun Super Admin dibuat.")
        print("  username : %s" % user.username)
        print("  role     : %s" % user.role)
        print("  passcode : (tidak ditampilkan, tidak disimpan polos)")
        print("")
        print("Akun lain di database TIDAK diubah. Statusnya:")
        for u in db.query(User).order_by(User.id).all():
            print("  - %-14s %-12s aktif=%s" % (u.username, u.role, u.active))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
