"""Auth endpoints - login, logout, current user.
Menggunakan token acak (persisted di DB) + PBKDF2 untuk hashing passcode.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from typing import Optional

from dependencies import get_db_session
from models import AuthToken, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_TTL_DAYS = 7
PBKDF2_ITERATIONS = 200_000


# ---------- Schemas ----------
class LoginRequest(BaseModel):
    username: str
    passcode: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class ChangePasscodeRequest(BaseModel):
    current_passcode: str
    new_passcode: str


#: Panjang minimum passcode agar tidak terlalu pendek untuk mesin kasir yang dipakai
#: bersama, tapi juga tidak membuat passcode merepotkan staff yang menghafal.
MIN_PASSCODE = 4
MIN_PASSCODE = 4


# ---------- Helpers ----------
def hash_passcode(passcode: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", passcode.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()


def verify_passcode(passcode: str, salt: str, expected_hash: str) -> bool:
    computed = hash_passcode(passcode, salt)
    return hmac.compare_digest(computed, expected_hash)


def create_token(db: Session, user: User) -> str:
    token = secrets.token_hex(32)
    db_token = AuthToken(
        token=token,
        user_id=user.id,
        expires_at=datetime.now() + timedelta(days=TOKEN_TTL_DAYS),
    )
    db.add(db_token)
    user.last_login = datetime.now()
    db.commit()
    db.refresh(db_token)
    return token


# ---------- Routes ----------
@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Username atau passcode salah.")
    if not verify_passcode(payload.passcode, user.passcode_salt, user.passcode_hash):
        raise HTTPException(status_code=401, detail="Username atau passcode salah.")
    token = create_token(db, user)
    return LoginResponse(token=token, user=UserOut.model_validate(user))


def require_authorization_header(authorization: str) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Tidak terautentikasi.")
    return authorization[7:]


def get_bearer_token(authorization: str = Header(None)) -> str:
    return require_authorization_header(authorization)


def get_current_user(db: Session, token: str) -> User:
    db_token = db.query(AuthToken).filter(AuthToken.token == token).first()
    if not db_token:
        raise HTTPException(status_code=401, detail="Sesi tidak valid.")
    if db_token.expires_at < datetime.now():
        db.delete(db_token)
        db.commit()
        raise HTTPException(status_code=401, detail="Sesi telah kedaluwarsa.")
    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Akun tidak aktif.")
    return user


def get_authenticated_user(
    token: str = Depends(get_bearer_token),
    db: Session = Depends(get_db_session),
) -> User:
    """FastAPI dependency untuk melindungi endpoint."""
    return get_current_user(db, token)


@router.post("/logout")
def logout(
    token: str = Depends(get_bearer_token),
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db_session),
):
    db.query(AuthToken).filter(AuthToken.token == token).delete()
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_authenticated_user)):
    return UserOut.model_validate(user)


@router.post("/change-passcode")
def change_passcode(
    payload: ChangePasscodeRequest,
    token: str = Depends(get_bearer_token),
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db_session),
):
    """Ganti passcode AKUN YANG SEDANG LOGIN.

    Alasan kenapa ini perlu: tadinya tidak ada jalan mengubah passcode sendiri.
    "Lupa Password?" di halaman login cuma menampilkan pesan "hubungi
    administrator", padahal kalau toko cuma punya SATU akun, tidak ada admin lain
    yang bisa membantu -- hasilnya user terkunci dari sistemnya sendiri.

    Keamanan:
    - WAJIB menyertakan passcode lama, jadi tanpa akses fisik ke sesi aktif
      tidak ada yang bisa mengganti passcode orang lain.
    - Ganti salt + hash (PBKDF2, sama seperti account creation), bukan hash saja.
    - Semua token LAIN milik user ini langsung dicabut, supaya passcode lama
      tidak masih berlaku di perangkat yang sebelumnya sudah login. Token yang
      sedang dipakai (browser ini) juga dicabut supaya user harus login ulang
      dengan passcode baru -- kalau tidak, passcode yang baru bisa salah ketik
      tanpa terdeteksi sampai token-nya kadaluarsa 7 hari.
    """
    if not verify_passcode(payload.current_passcode, user.passcode_salt,
                           user.passcode_hash):
        raise HTTPException(status_code=400,
                            detail="Passcode lama salah.")
    baru = (payload.new_passcode or "").strip()
    if len(baru) < MIN_PASSCODE:
        raise HTTPException(
            status_code=400,
            detail="Passcode baru minimal %d karakter." % MIN_PASSCODE)
    if baru == (payload.current_passcode or ""):
        raise HTTPException(status_code=400,
                            detail="Passcode baru harus berbeda dari yang lama.")
    user.passcode_salt = secrets.token_hex(16)
    user.passcode_hash = hash_passcode(baru, user.passcode_salt)
    db.query(AuthToken).filter(AuthToken.user_id == user.id).delete()
    db.commit()
    return {"ok": True,
            "pesan": "Passcode diubah. Silakan login ulang dengan passcode baru."}


def require_admin(user: User = Depends(get_authenticated_user)) -> User:
    if (user.role or "").upper() not in ("SUPERADMIN", "ADMIN"):
        raise HTTPException(status_code=403, detail="Hanya Admin yang boleh mengelola akun.")
    return user


# ---------- Aturan keuangan (alur kas konsep) ----------
# Istilah & UI tetap konsep baru; yang dijaga di sini hanya alur uang:
# peran kasir/teknis vs admin sesuai konsep (Kasir ≈ Admin untuk closing).
FINANCE_ROLES = ("SUPERADMIN", "ADMIN")


def can_edit_finance(user: User) -> bool:
    """True bila boleh mengubah angka keuangan (harga/modal/DP/jurnal)."""
    return (getattr(user, "role", "") or "").strip().upper() in FINANCE_ROLES


def require_finance(user: User = Depends(get_authenticated_user)) -> User:
    """Dependency: tolak Teknisi (dan role non-keuangan) untuk aksi uang."""
    if not can_edit_finance(user):
        raise HTTPException(status_code=403,
                            detail="Hanya Admin yang boleh mengelola keuangan")
    return user


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str
    active: int
    last_login: Optional[datetime] = None


class UserCreate(BaseModel):
    username: str
    display_name: str
    role: str = "Teknisi"
    passcode: str = ""
    active: int = 1


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[int] = None
    passcode: Optional[str] = None


@router.get("/users", response_model=list[UserAdminOut])
def list_users(admin: User = Depends(require_admin),
               db: Session = Depends(get_db_session)):
    return db.query(User).order_by(User.id.asc()).all()


@router.post("/users", response_model=UserAdminOut, status_code=201)
def create_user(payload: UserCreate, admin: User = Depends(require_admin),
                db: Session = Depends(get_db_session)):
    username = (payload.username or "").strip()
    nama = (payload.display_name or "").strip()
    if not username or not nama:
        raise HTTPException(status_code=400, detail="Nama dan username wajib diisi")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username sudah dipakai akun lain.")
    if not payload.passcode or len(payload.passcode) < 4:
        raise HTTPException(status_code=400, detail="Passcode minimal 4 karakter")
    salt = secrets.token_hex(16)
    user = User(username=username, display_name=nama,
                role=(payload.role or "Teknisi").strip() or "Teknisi",
                passcode_hash=hash_passcode(payload.passcode, salt),
                passcode_salt=salt, active=1 if payload.active else 0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserAdminOut)
def update_user(user_id: int, payload: UserUpdate,
                admin: User = Depends(require_admin),
                db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    if user.id == admin.id and (payload.role is not None or payload.active is not None):
        raise HTTPException(status_code=400, detail="Tidak dapat mengubah role/status akun sendiri")
    if (user.role or "").upper() == "SUPERADMIN" and (admin.role or "").upper() != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Hanya Superadmin yang boleh mengubah Superadmin")
    data = payload.model_dump(exclude_unset=True)
    if "display_name" in data:
        if not (data["display_name"] or "").strip():
            raise HTTPException(status_code=400, detail="Nama wajib diisi")
        user.display_name = data["display_name"].strip()
    if "role" in data and data["role"] is not None:
        user.role = (data["role"] or "").strip() or user.role
    if "active" in data and data["active"] is not None:
        user.active = 1 if data["active"] else 0
    if "passcode" in data and data["passcode"]:
        if len(data["passcode"]) < 4:
            raise HTTPException(status_code=400, detail="Passcode minimal 4 karakter")
        salt = secrets.token_hex(16)
        user.passcode_salt = salt
        user.passcode_hash = hash_passcode(data["passcode"], salt)
    db.commit()
    db.refresh(user)
    return user
