# -*- coding: utf-8 -*-
"""Ubah passcode milik sendiri (POST /api/auth/change-passcode).

Alasan fitur ini ada: sebelumnya TIDAK ADA jalan mengubah passcode milik sendiri.
"Lupa Password?" di halaman login cuma menampilkan pesan "hubungi administrator",
padahal kalau toko hanya punya satu akun, tidak ada admin lain -- user terkunci
dari sistemnya sendiri.

Yang dijaga test:
  - passcode LAMA salah ditolak (tanpa ini siapa pun yang punya token bisa
    mengganti passcode orang lain);
  - passcode baru terlalu pendek ditolak;
  - passcode baru harus berbeda dari yang lama;
  - setelah diganti, SEMUA token user itu dicabut, termasuk token yang sedang
    dipakai. Kalau token ini tidak ikut dicabut, passcode baru yang salah ketik
    tidak akan ketahuan sampai token lama kadaluarsa sendiri (7 hari).
"""
import pytest

from routers.auth import (MIN_PASSCODE, hash_passcode, verify_passcode)


def _hash(p):
    import secrets
    salt = secrets.token_hex(16)
    return salt, hash_passcode(p, salt)


def _make_user(db, username="pcuser", passcode="lama123"):
    from models import User
    salt, h = _hash(passcode)
    u = User(username=username, display_name="PC User", role="KASIR",
             passcode_salt=salt, passcode_hash=h, active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client, db, user, passcode):
    r = client.post("/api/auth/login",
                    json={"username": user.username, "passcode": passcode})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_ganti_passcode_berhasil_dan_token_lama_mati(client, db):
    u = _make_user(db)
    auth = _login(client, db, u, "lama123")
    # token lama jalan
    assert client.get("/api/auth/me", headers=auth).status_code == 200

    r = client.post("/api/auth/change-passcode", headers=auth,
                    json={"current_passcode": "lama123", "new_passcode": "baru456"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert "pesan" in r.json()

    # Token yang SEDANG dipakai ikut dicabut -> harus 401 lagi.
    assert client.get("/api/auth/me", headers=auth).status_code == 401

    # Passcode baru berlaku, yang lama tidak.
    assert client.post("/api/auth/login",
                       json={"username": u.username,
                             "passcode": "lama123"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": u.username,
                             "passcode": "baru456"}).status_code == 200


def test_passcode_lama_salah_ditolak(client, db):
    u = _make_user(db, "pcuser2")
    auth = _login(client, db, u, "lama123")
    r = client.post("/api/auth/change-passcode", headers=auth,
                    json={"current_passcode": "salah", "new_passcode": "baru456"})
    assert r.status_code == 400
    assert "lama" in r.json()["detail"].lower()
    # passcode tidak berubah
    assert client.post("/api/auth/login",
                       json={"username": u.username,
                             "passcode": "lama123"}).status_code == 200


def test_passcode_baru_terlalu_pendek_ditolak(client, db):
    u = _make_user(db, "pcuser3")
    auth = _login(client, db, u, "lama123")
    pendek = "a" * (MIN_PASSCODE - 1)
    r = client.post("/api/auth/change-passcode", headers=auth,
                    json={"current_passcode": "lama123", "new_passcode": pendek})
    assert r.status_code == 400
    assert str(MIN_PASSCODE) in r.json()["detail"]
    # passcode lama masih berlaku
    assert client.post("/api/auth/login",
                       json={"username": u.username,
                             "passcode": "lama123"}).status_code == 200


def test_passcode_baru_harus_berbeda(client, db):
    u = _make_user(db, "pcuser4")
    auth = _login(client, db, u, "lama123")
    r = client.post("/api/auth/change-passcode", headers=auth,
                    json={"current_passcode": "lama123", "new_passcode": "lama123"})
    assert r.status_code == 400


def test_tanpa_token_ditolak(client, db):
    r = client.post("/api/auth/change-passcode",
                    json={"current_passcode": "a", "new_passcode": "bbbb"})
    assert r.status_code == 401


def test_hash_menyimpan_salt_baru(client, db):
    """Passcode harus di-hash ulang dengan SALT baru, bukan hash ulang salt lama."""
    u = _make_user(db, "pcuser5")
    auth = _login(client, db, u, "lama123")
    salt_lama = u.passcode_salt
    r = client.post("/api/auth/change-passcode", headers=auth,
                    json={"current_passcode": "lama123", "new_passcode": "baru456"})
    assert r.status_code == 200
    db.expire_all()
    assert u.passcode_salt != salt_lama, "Salt harus dirotasi"
    assert verify_passcode("baru456", u.passcode_salt, u.passcode_hash)
    assert not verify_passcode("lama123", u.passcode_salt, u.passcode_hash)