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
        expires_at=datetime.utcnow() + timedelta(days=TOKEN_TTL_DAYS),
    )
    db.add(db_token)
    user.last_login = datetime.utcnow()
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
    if db_token.expires_at < datetime.utcnow():
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
