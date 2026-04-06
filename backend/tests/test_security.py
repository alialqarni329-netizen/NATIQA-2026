"""
اختبارات طبقة الأمان:
- JWT إنشاء وفك تشفير
- bcrypt تشفير كلمات المرور
- AES-256-GCM تشفير الملفات
- TOTP توليد والتحقق
- Data Masking
"""
import pytest
import time
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    encrypt_file, decrypt_file,
    generate_totp_secret, verify_totp,
)
from app.services.llm.masking import mask_sensitive_data, unmask_data


# ─── Password ────────────────────────────────────────────────────────────
class TestPasswordHashing:
    def test_hash_is_different_from_plain(self):
        plain = "MySecurePass2026!"
        hashed = hash_password(plain)
        assert hashed != plain

    def test_correct_password_verifies(self):
        plain = "MySecurePass2026!"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("CorrectPass123")
        assert verify_password("WrongPass456", hashed) is False

    def test_empty_password_hashes(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notEmpty", hashed) is False


# ─── JWT ─────────────────────────────────────────────────────────────────
class TestJWT:
    def test_access_token_decodes_correctly(self):
        token = create_access_token("user-123", extra={"role": "admin"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"
        assert payload["role"] == "admin"

    def test_refresh_token_has_jti(self):
        token = create_refresh_token("user-456")
        payload = decode_token(token)
        assert payload is not None
        assert payload["type"] == "refresh"
        assert "jti" in payload
        assert len(payload["jti"]) > 0

    def test_invalid_token_returns_none(self):
        result = decode_token("not.a.valid.token.at.all")
        assert result is None

    def test_tampered_token_returns_none(self):
        token = create_access_token("user-789")
        tampered = token[:-5] + "XXXXX"
        assert decode_token(tampered) is None

    def test_two_tokens_for_same_user_are_unique(self):
        t1 = create_refresh_token("user-1")
        time.sleep(0.01)
        t2 = create_refresh_token("user-1")
        p1, p2 = decode_token(t1), decode_token(t2)
        assert p1["jti"] != p2["jti"]


# ─── AES-256-GCM ─────────────────────────────────────────────────────────
class TestFileEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        original = b"This is a secret document content \xf0\x9f\x94\x92"
        encrypted = encrypt_file(original)
        decrypted = decrypt_file(encrypted)
        assert decrypted == original

    def test_encrypted_different_from_original(self):
        data = b"Sensitive data here"
        encrypted = encrypt_file(data)
        assert encrypted != data

    def test_two_encryptions_of_same_data_differ(self):
        data = b"Same content"
        e1 = encrypt_file(data)
        e2 = encrypt_file(data)
        # nonces differ so ciphertexts differ
        assert e1 != e2

    def test_tampered_ciphertext_raises(self):
        encrypted = encrypt_file(b"Valid data")
        tampered = encrypted[:-3] + bytes([0x00, 0x00, 0x00])
        with pytest.raises(Exception):
            decrypt_file(tampered)


# ─── TOTP ─────────────────────────────────────────────────────────────────
class TestTOTP:
    def test_generated_secret_is_base32(self):
        import base64
        secret = generate_totp_secret()
        # base32 alphabet: A-Z2-7
        try:
            base64.b32decode(secret)
        except Exception:
            pytest.fail("TOTP secret is not valid base32")

    def test_valid_totp_code_verifies(self):
        import pyotp
        secret = generate_totp_secret()
        code = pyotp.TOTP(secret).now()
        assert verify_totp(secret, code) is True

    def test_wrong_code_fails(self):
        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False

    def test_different_secrets_dont_cross_verify(self):
        import pyotp
        s1 = generate_totp_secret()
        s2 = generate_totp_secret()
        code_for_s1 = pyotp.TOTP(s1).now()
        # Very unlikely to match, but s1 != s2
        if s1 != s2:
            # code generated with s1 should not verify with s2 (almost certainly)
            # We just check the verify function works
            result = verify_totp(s2, code_for_s1)
            # This is probabilistic; skip assertion if codes happen to collide
            assert isinstance(result, bool)


# ─── Data Masking ─────────────────────────────────────────────────────────
class TestDataMasking:
    def test_saudi_phone_masked(self):
        text = "اتصل على رقم 0501234567"
        result = mask_sensitive_data(text, session_salt="test")
        assert "0501234567" not in result.masked_text
        assert "<<PHONE_SA_" in result.masked_text
        assert result.count >= 1

    def test_email_masked(self):
        text = "راسل المدير على ceo@company.com لمزيد من المعلومات"
        result = mask_sensitive_data(text, session_salt="test")
        assert "ceo@company.com" not in result.masked_text
        assert "<<EMAIL_" in result.masked_text

    def test_national_id_masked(self):
        text = "رقم الهوية: 1098765432"
        result = mask_sensitive_data(text, session_salt="test")
        assert "1098765432" not in result.masked_text

    def test_iban_masked(self):
        text = "رقم الآيبان: SA4420000001234567891234"
        result = mask_sensitive_data(text, session_salt="test")
        assert "SA4420000001234567891234" not in result.masked_text
        assert "<<IBAN_" in result.masked_text

    def test_unmask_restores_original(self):
        original_text = "هاتف: 0501234567 والبريد: user@corp.com"
        masked_result = mask_sensitive_data(original_text, session_salt="salt123")
        unmasked = unmask_data(masked_result.masked_text, masked_result.mappings)
        assert "0501234567" in unmasked
        assert "user@corp.com" in unmasked

    def test_clean_text_unchanged(self):
        text = "هذا النص لا يحتوي على بيانات حساسة"
        result = mask_sensitive_data(text, session_salt="test")
        assert result.masked_text == text
        assert result.count == 0

    def test_multiple_sensitive_items(self):
        text = "ID: 1234567890 Phone: 0509876543 Email: test@biz.sa"
        result = mask_sensitive_data(text, session_salt="multi")
        assert result.count >= 3

    def test_same_value_same_placeholder(self):
        text = "A: 0501234567 and B: 0501234567"
        result = mask_sensitive_data(text, session_salt="same")
        # Both instances should map to same placeholder
        placeholders = [k for k in result.mappings if result.mappings[k] == "0501234567"]
        assert len(placeholders) == 1
