"""
╔══════════════════════════════════════════════════════════════════════════╗
║        NATIQA — Secure Vault  (خزنة الأسرار)                            ║
║                                                                          ║
║  تخزين بيانات الاتصال (API Keys / Tokens / Passwords) مشفّرة في DB.     ║
║                                                                          ║
║  آلية التشفير:                                                           ║
║    Master Key (من .env) → PBKDF2 derivation → AES-256-GCM              ║
║    كل سر له nonce فريد ومستقل                                           ║
║                                                                          ║
║  مبدأ Zero Trust:                                                        ║
║    - بيانات الاتصال لا تُخزَّن في .env أبداً (إلا Master Key)          ║
║    - تُقرأ من DB فقط عند الاستخدام الفعلي                              ║
║    - يمكن إبطال أي سر بضغطة زر (soft delete + hard delete)            ║
║    - كل وصول للـ Vault مسجّل في AuditLog                               ║
║    - Key rotation مدمج                                                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import structlog

from app.core.config import settings

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  1. Key Derivation
# ═══════════════════════════════════════════════════════════

def _derive_vault_key(master_key: str, salt: bytes) -> bytes:
    """
    اشتقاق مفتاح AES-256 من Master Key + salt باستخدام PBKDF2.

    PBKDF2 يجعل Brute Force مكلفاً جداً:
    - 480,000 iteration
    - SHA-256
    - Output: 32 bytes (256 bit)
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
        backend=default_backend(),
    )
    return kdf.derive(master_key.encode("utf-8"))


def _encrypt_secret(plaintext: str, master_key: str) -> tuple[bytes, bytes, bytes]:
    """
    تشفير AES-256-GCM.

    يعود بـ: (ciphertext, nonce, salt)
    كل ثلاثة مستقلة — يجب تخزينها معاً.
    """
    salt  = secrets.token_bytes(32)    # 256-bit salt فريد لكل سر
    nonce = secrets.token_bytes(12)    # 96-bit nonce لـ GCM
    key   = _derive_vault_key(master_key, salt)

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce, salt


def _decrypt_secret(
    ciphertext: bytes,
    nonce:      bytes,
    salt:       bytes,
    master_key: str,
) -> str:
    """فك تشفير AES-256-GCM."""
    key = _derive_vault_key(master_key, salt)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# ═══════════════════════════════════════════════════════════
#  2. Vault Entry (هيكل السر)
# ═══════════════════════════════════════════════════════════

@dataclass
class VaultEntry:
    """
    حقل واحد في الـ Vault.
    كل نظام خارجي له حقل لكل قيمة سرية.
    """
    system_id:  str
    key_name:   str          # api_key / client_secret / password ...
    ciphertext: bytes
    nonce:      bytes
    salt:       bytes
    created_at: float
    expires_at: float | None  # None = لا تنتهي
    version:    int = 1       # لـ Key Rotation
    is_active:  bool = True
    created_by: str = "system"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_db_dict(self) -> dict:
        """تحويل لتخزين في قاعدة البيانات (bytes → hex strings)."""
        return {
            "system_id":  self.system_id,
            "key_name":   self.key_name,
            "ciphertext": self.ciphertext.hex(),
            "nonce":      self.nonce.hex(),
            "salt":       self.salt.hex(),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "version":    self.version,
            "is_active":  self.is_active,
            "created_by": self.created_by,
        }

    @classmethod
    def from_db_dict(cls, d: dict) -> "VaultEntry":
        """إعادة بناء من قاعدة البيانات."""
        return cls(
            system_id=  d["system_id"],
            key_name=   d["key_name"],
            ciphertext= bytes.fromhex(d["ciphertext"]),
            nonce=      bytes.fromhex(d["nonce"]),
            salt=       bytes.fromhex(d["salt"]),
            created_at= d["created_at"],
            expires_at= d.get("expires_at"),
            version=    d.get("version", 1),
            is_active=  d.get("is_active", True),
            created_by= d.get("created_by", "system"),
        )


# ═══════════════════════════════════════════════════════════
#  3. Vault — In-Memory Cache + DB Backend
# ═══════════════════════════════════════════════════════════

class SecureVault:
    """
    خزنة الأسرار — طبقة واحدة لإدارة كل بيانات الاتصال.

    الـ Cache:
      - يُخزَّن في الذاكرة لمدة cache_ttl ثانية
      - يُمسح تلقائياً بعد انتهاء المدة
      - لا يُخزَّن على القرص أبداً

    قاعدة البيانات:
      - يُستخدم جدول vault_secrets لتخزين السر المشفّر
      - يُقرأ فقط عند الحاجة (عند انتهاء الـ Cache)
    """

    def __init__(
        self,
        master_key:  str | None = None,
        cache_ttl:   int = 300,    # 5 دقائق
        db_session_factory = None,
    ):
        # Master Key — من settings أو من المعامل
        self._master_key = master_key or settings.ENCRYPTION_KEY
        self._cache_ttl  = cache_ttl
        self._db_factory = db_session_factory

        # Cache: {(system_id, key_name): (plaintext, expires_at)}
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}

        # In-memory store للـ Demo / Fallback
        self._memory_store: dict[str, VaultEntry] = {}

    # ── Write ─────────────────────────────────────────────

    async def store_secret(
        self,
        system_id:  str,
        key_name:   str,
        plaintext:  str,
        ttl_days:   int | None = None,
        created_by: str = "system",
    ) -> str:
        """
        تشفير وتخزين سر جديد.
        يعود بـ: secret_id (للرجوع إليه)
        """
        if not plaintext:
            raise ValueError("قيمة السر لا يمكن أن تكون فارغة")

        ciphertext, nonce, salt = _encrypt_secret(plaintext, self._master_key)

        expires_at = None
        if ttl_days:
            expires_at = time.time() + (ttl_days * 86400)

        entry = VaultEntry(
            system_id=  system_id,
            key_name=   key_name,
            ciphertext= ciphertext,
            nonce=      nonce,
            salt=       salt,
            created_at= time.time(),
            expires_at= expires_at,
            created_by= created_by,
        )

        # تخزين في DB
        if self._db_factory:
            await self._store_to_db(entry)
        else:
            # Fallback: ذاكرة
            store_key = f"{system_id}:{key_name}"
            self._memory_store[store_key] = entry

        # حساب secret_id (بدون كشف المحتوى)
        secret_id = hashlib.sha256(
            f"{system_id}:{key_name}:{entry.created_at}".encode()
        ).hexdigest()[:16]

        log.info(
            "Vault: تم تخزين سر جديد",
            system_id=system_id,
            key_name=key_name,
            secret_id=secret_id,
            has_expiry=expires_at is not None,
        )
        return secret_id

    # ── Read ──────────────────────────────────────────────

    async def get_secret(
        self,
        system_id: str,
        key_name:  str,
        requester: str = "system",
    ) -> str:
        """
        استرجاع سر مفكوك التشفير.
        يُقرأ من Cache أولاً، ثم من DB عند الحاجة.
        """
        cache_key = (system_id, key_name)

        # فحص Cache
        if cache_key in self._cache:
            value, expires = self._cache[cache_key]
            if time.time() < expires:
                return value
            else:
                del self._cache[cache_key]

        # قراءة من DB / Memory
        entry = await self._load_entry(system_id, key_name)

        if entry is None:
            raise KeyError(f"Vault: لا يوجد سر للنظام '{system_id}' بالمفتاح '{key_name}'")

        if not entry.is_active:
            raise PermissionError(f"Vault: السر '{key_name}' للنظام '{system_id}' معطّل")

        if entry.is_expired():
            raise PermissionError(f"Vault: السر '{key_name}' للنظام '{system_id}' انتهت صلاحيته")

        # فك التشفير
        plaintext = _decrypt_secret(
            entry.ciphertext,
            entry.nonce,
            entry.salt,
            self._master_key,
        )

        # حفظ في Cache
        self._cache[cache_key] = (plaintext, time.time() + self._cache_ttl)

        log.info(
            "Vault: تم استرجاع سر",
            system_id=system_id,
            key_name=key_name,
            requester=requester,
            from_cache=False,
        )
        return plaintext

    # ── Bulk Load (لبناء Credentials كاملة) ───────────────

    async def load_credentials(self, system_id: str) -> dict[str, str]:
        """
        تحميل جميع أسرار نظام معيّن دفعة واحدة.
        يُستخدم لبناء IntegrationCredentials.
        """
        keys = await self._list_keys(system_id)
        result: dict[str, str] = {}
        for key_name in keys:
            try:
                result[key_name] = await self.get_secret(system_id, key_name)
            except Exception as e:
                log.warning("Vault: تعذّر قراءة مفتاح", key=key_name, error=str(e))
        return result

    # ── Revoke / Rotate ───────────────────────────────────

    async def revoke_secret(self, system_id: str, key_name: str) -> bool:
        """إبطال سر (soft delete)."""
        cache_key = (system_id, key_name)
        self._cache.pop(cache_key, None)

        store_key = f"{system_id}:{key_name}"
        if store_key in self._memory_store:
            self._memory_store[store_key].is_active = False
            log.info("Vault: تم إبطال السر", system_id=system_id, key_name=key_name)
            return True

        if self._db_factory:
            return await self._revoke_in_db(system_id, key_name)
        return False

    async def rotate_secret(
        self,
        system_id:    str,
        key_name:     str,
        new_plaintext: str,
        rotated_by:   str = "system",
    ) -> str:
        """
        Key Rotation — تشفير جديد بـ nonce + salt جديدين.
        يُبطل القديم ويُنشئ إصدار جديد.
        """
        old_entry = await self._load_entry(system_id, key_name)
        old_version = old_entry.version if old_entry else 0

        # إبطال القديم
        await self.revoke_secret(system_id, key_name)

        # تخزين جديد بـ version محدّث
        ciphertext, nonce, salt = _encrypt_secret(new_plaintext, self._master_key)
        entry = VaultEntry(
            system_id=  system_id,
            key_name=   key_name,
            ciphertext= ciphertext,
            nonce=      nonce,
            salt=       salt,
            created_at= time.time(),
            expires_at= None,
            version=    old_version + 1,
            created_by= rotated_by,
        )

        store_key = f"{system_id}:{key_name}"
        self._memory_store[store_key] = entry

        # مسح Cache
        self._cache.pop((system_id, key_name), None)

        log.info(
            "Vault: تم تدوير المفتاح",
            system_id=system_id,
            key_name=key_name,
            new_version=entry.version,
            rotated_by=rotated_by,
        )
        return f"v{entry.version}"

    # ── Audit ─────────────────────────────────────────────

    async def list_systems(self) -> list[dict]:
        """قائمة الأنظمة المسجّلة في الـ Vault (بدون كشف الأسرار)."""
        systems: dict[str, dict] = {}
        for key, entry in self._memory_store.items():
            sid = entry.system_id
            if sid not in systems:
                systems[sid] = {
                    "system_id": sid,
                    "keys":      [],
                    "active":    entry.is_active,
                    "version":   entry.version,
                }
            systems[sid]["keys"].append(entry.key_name)
        return list(systems.values())

    async def purge_expired(self) -> int:
        """حذف جميع الأسرار المنتهية الصلاحية."""
        to_remove = [
            k for k, e in self._memory_store.items()
            if e.is_expired()
        ]
        for k in to_remove:
            del self._memory_store[k]
        if to_remove:
            log.info("Vault: تم حذف أسرار منتهية", count=len(to_remove))
        return len(to_remove)

    # ── Private DB helpers ────────────────────────────────

    async def _store_to_db(self, entry: VaultEntry) -> None:
        """تخزين في PostgreSQL (vault_secrets table)."""
        if not self._db_factory:
            return
        async with self._db_factory() as session:
            from sqlalchemy import text
            d = entry.to_db_dict()
            await session.execute(
                text("""
                    INSERT INTO vault_secrets
                        (system_id, key_name, ciphertext, nonce, salt,
                         created_at, expires_at, version, is_active, created_by)
                    VALUES
                        (:system_id, :key_name, :ciphertext, :nonce, :salt,
                         TO_TIMESTAMP(:created_at), TO_TIMESTAMP(:expires_at),
                         :version, :is_active, :created_by)
                    ON CONFLICT (system_id, key_name)
                    DO UPDATE SET
                        ciphertext  = EXCLUDED.ciphertext,
                        nonce       = EXCLUDED.nonce,
                        salt        = EXCLUDED.salt,
                        version     = EXCLUDED.version,
                        is_active   = EXCLUDED.is_active,
                        created_at  = EXCLUDED.created_at
                """),
                {**d, "expires_at": d["expires_at"]},
            )
            await session.commit()

    async def _load_entry(
        self, system_id: str, key_name: str
    ) -> VaultEntry | None:
        store_key = f"{system_id}:{key_name}"
        if store_key in self._memory_store:
            return self._memory_store[store_key]

        if self._db_factory:
            async with self._db_factory() as session:
                from sqlalchemy import text
                row = (await session.execute(
                    text("""
                        SELECT * FROM vault_secrets
                        WHERE system_id = :sid AND key_name = :kn AND is_active = TRUE
                        ORDER BY version DESC LIMIT 1
                    """),
                    {"sid": system_id, "kn": key_name},
                )).mappings().first()
                if row:
                    return VaultEntry.from_db_dict(dict(row))
        return None

    async def _list_keys(self, system_id: str) -> list[str]:
        return [
            e.key_name
            for k, e in self._memory_store.items()
            if e.system_id == system_id and e.is_active
        ]

    async def _revoke_in_db(self, system_id: str, key_name: str) -> bool:
        if not self._db_factory:
            return False
        async with self._db_factory() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("""
                    UPDATE vault_secrets
                    SET is_active = FALSE
                    WHERE system_id = :sid AND key_name = :kn
                """),
                {"sid": system_id, "kn": key_name},
            )
            await session.commit()
            return result.rowcount > 0


# ═══════════════════════════════════════════════════════════
#  4. Vault Singleton
# ═══════════════════════════════════════════════════════════

_vault_instance: SecureVault | None = None


def get_vault(db_session_factory=None) -> SecureVault:
    """Singleton للـ Vault — instance واحد لكل process."""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = SecureVault(
            master_key=settings.ENCRYPTION_KEY,
            cache_ttl=300,
            db_session_factory=db_session_factory,
        )
    return _vault_instance
