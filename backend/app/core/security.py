"""
Security — JWT + AES-256-GCM + bcrypt + TOTP (2FA)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import secrets
import hashlib
import base64

from jose import JWTError, jwt
import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pyotp

from app.core.config import settings


# ─── Password hashing ────────────────────────────────────────────────
def _prepare(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))


# ─── JWT ─────────────────────────────────────────────────────────────
def create_access_token(subject: Any, extra: dict = {}) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
        **extra,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: Any) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        return None


# ─── AES-256-GCM ─────────────────────────────────────────────────────
def get_aes_key() -> bytes:
    """يشتق مفتاح AES-256 ثابت من ENCRYPTION_KEY باستخدام SHA-256."""
    return hashlib.sha256(settings.ENCRYPTION_KEY.encode()).digest()


def encrypt_file(data: bytes) -> bytes:
    key = get_aes_key()
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt_file(encrypted: bytes) -> bytes:
    key = get_aes_key()
    return AESGCM(key).decrypt(encrypted[:12], encrypted[12:], None)


# ─── 2FA / TOTP ──────────────────────────────────────────────────────
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="NATIQA")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)