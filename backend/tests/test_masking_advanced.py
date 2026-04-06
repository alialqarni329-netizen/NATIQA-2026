"""
اختبارات متقدمة لطبقة Data Masking:
- اختبار أنماط متعددة في نص واحد
- اختبار الحدود الحرجة
- التحقق من عدم تسرب البيانات
"""
import pytest
from app.services.llm.masking import mask_sensitive_data, unmask_data, PATTERNS, PATTERN_ORDER


class TestMaskingEdgeCases:
    def test_empty_string(self):
        result = mask_sensitive_data("", session_salt="test")
        assert result.masked_text == ""
        assert result.count == 0
        assert result.mappings == {}

    def test_arabic_text_preserved(self):
        text = "هذا نص عربي بحت بدون بيانات حساسة."
        result = mask_sensitive_data(text)
        assert result.masked_text == text

    def test_international_phone_not_matched(self):
        # هاتف دولي غير سعودي لا يجب أن يُقنَّع
        text = "US number: +12025551234"
        result = mask_sensitive_data(text)
        # PHONE_SA pattern only matches Saudi numbers
        phone_masked = any("PHONE_SA" in k for k in result.mappings)
        assert not phone_masked

    def test_ip_address_masked(self):
        text = "Server IP: 192.168.1.100"
        result = mask_sensitive_data(text, session_salt="ip-test")
        assert "192.168.1.100" not in result.masked_text
        assert "<<IP_ADDRESS_" in result.masked_text

    def test_credit_card_masked(self):
        text = "Card: 4111 1111 1111 1111"
        result = mask_sensitive_data(text, session_salt="cc-test")
        assert "4111" not in result.masked_text or "<<CREDIT_CARD_" in result.masked_text

    def test_multiple_emails_in_text(self):
        text = "Contact: a@corp.com and b@biz.sa for details."
        result = mask_sensitive_data(text, session_salt="multi-email")
        assert "a@corp.com" not in result.masked_text
        assert "b@biz.sa" not in result.masked_text

    def test_masking_is_deterministic_with_same_salt(self):
        text = "Phone: 0505550000"
        r1 = mask_sensitive_data(text, session_salt="fixed-salt")
        r2 = mask_sensitive_data(text, session_salt="fixed-salt")
        assert r1.masked_text == r2.masked_text
        assert r1.mappings == r2.mappings

    def test_masking_differs_with_different_salt(self):
        text = "Phone: 0505550000"
        r1 = mask_sensitive_data(text, session_salt="salt-A")
        r2 = mask_sensitive_data(text, session_salt="salt-B")
        # placeholders are different but both mask the phone
        assert "0505550000" not in r1.masked_text
        assert "0505550000" not in r2.masked_text
        # The placeholder keys differ
        keys1 = list(r1.mappings.keys())
        keys2 = list(r2.mappings.keys())
        assert keys1 != keys2

    def test_unmask_with_empty_mappings(self):
        text = "No sensitive data"
        result = unmask_data(text, {})
        assert result == text

    def test_partial_unmask(self):
        # Only unmask one of two items
        text = "Phone: 0501111111 and ID: 1234567890"
        result = mask_sensitive_data(text, session_salt="partial")
        # Get only phone mappings
        phone_mappings = {k: v for k, v in result.mappings.items() if "PHONE" in k}
        partially_unmasked = unmask_data(result.masked_text, phone_mappings)
        assert "0501111111" in partially_unmasked

    def test_national_id_starting_with_1(self):
        text = "ID: 1234567890"
        result = mask_sensitive_data(text)
        assert "1234567890" not in result.masked_text

    def test_national_id_starting_with_2(self):
        text = "رقم إقامة: 2345678901"
        result = mask_sensitive_data(text)
        assert "2345678901" not in result.masked_text

    def test_saudi_iban_format(self):
        text = "IBAN: SA4420000001234567891234"
        result = mask_sensitive_data(text)
        assert "SA4420000001234567891234" not in result.masked_text
        assert "<<IBAN_" in result.masked_text

    def test_full_roundtrip_complex_document(self):
        document = """
        تقرير مالي سري
        ===============
        العميل: محمد العمري
        رقم الهوية: 1098765432
        الجوال: 0551234567
        البريد: m.omari@company.sa
        الآيبان: SA4420000001234567891234
        IP المشرف: 10.0.0.1

        تم مراجعة الحساب وإقرار الدفع.
        """
        masked = mask_sensitive_data(document, session_salt="doc-test")
        assert "1098765432" not in masked.masked_text
        assert "0551234567" not in masked.masked_text
        assert "m.omari@company.sa" not in masked.masked_text
        assert "SA4420000001234567891234" not in masked.masked_text
        assert masked.count >= 4

        # استعادة كاملة
        restored = unmask_data(masked.masked_text, masked.mappings)
        assert "1098765432" in restored
        assert "0551234567" in restored
        assert "m.omari@company.sa" in restored


class TestPatternCoverage:
    """تتحقق من وجود كل الأنماط المتوقعة."""
    def test_all_pattern_types_defined(self):
        expected = {"IBAN", "CREDIT_CARD", "NATIONAL_ID", "CR_NUMBER", "PHONE_SA", "EMAIL", "IP_ADDRESS"}
        assert set(PATTERNS.keys()) == expected

    def test_pattern_order_matches_patterns(self):
        for ptype in PATTERN_ORDER:
            assert ptype in PATTERNS, f"Pattern '{ptype}' in ORDER but not in PATTERNS"

    def test_all_patterns_compile(self):
        import re
        for name, pattern in PATTERNS.items():
            assert hasattr(pattern, "finditer"), f"Pattern {name} is not compiled regex"
