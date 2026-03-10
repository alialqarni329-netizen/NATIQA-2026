"""
Data Masking Layer
====================
تُطبَّق هذه الطبقة على أي نص قبل إرساله إلى API خارجي (Claude, OpenAI ...).

تكشف وتُخفي:
  - أرقام الهواتف السعودية والدولية
  - أرقام الهوية الوطنية / الإقامة
  - الأرقام البنكية (IBAN / بطاقات الائتمان)
  - عناوين البريد الإلكتروني
  - أرقام السجل التجاري
  - IP Addresses

المبدأ:
  - لا يُحذف أي شيء — تُستبدل البيانات بـ placeholder
  - الـ LLM يُرجع الـ placeholder في إجابته
  - نستعيد القيم الأصلية (Unmasking) عند العرض للمستخدم
  - الـ mappings تُخزَّن في الذاكرة فقط ولا تخرج لأي مكان
"""
import re
import hashlib
from dataclasses import dataclass, field
import structlog

log = structlog.get_logger()


# ─── أنماط الكشف ─────────────────────────────────────────────
PATTERNS = {
    # IBAN سعودي: SA + 22 رقم/حرف
    "IBAN": re.compile(
        r'\bSA\d{2}[A-Z0-9]{18,20}\b', re.IGNORECASE
    ),
    # بطاقة ائتمانية: 4 مجموعات أرقام
    "CREDIT_CARD": re.compile(
        r'\b(?:\d{4}[- ]?){3}\d{4}\b'
    ),
    # هوية وطنية / إقامة: 10 أرقام تبدأ بـ 1 أو 2
    "NATIONAL_ID": re.compile(
        r'\b([12]\d{9})\b'
    ),
    # سجل تجاري: 10 أرقام تبدأ بـ 1 أو 7
    "CR_NUMBER": re.compile(
        r'\b[17]\d{9}\b'
    ),
    # جوال سعودي: 05XXXXXXXX أو +9665XXXXXXXX
    "PHONE_SA": re.compile(
        r'\b(?:\+966|00966|0)(5\d{8})\b'
    ),
    # بريد إلكتروني
    "EMAIL": re.compile(
        r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
    ),
    # IPv4
    "IP_ADDRESS": re.compile(
        r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
        r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
    ),
}

# ترتيب المعالجة: الأطول أولاً لتجنب تداخل الأنماط
PATTERN_ORDER = [
    "IBAN", "CREDIT_CARD", "NATIONAL_ID",
    "CR_NUMBER", "PHONE_SA", "EMAIL", "IP_ADDRESS",
]


@dataclass
class MaskingResult:
    masked_text: str
    mappings: dict = field(default_factory=dict)  # {placeholder: original_value}
    count: int = 0


def mask_sensitive_data(text: str, session_salt: str = "") -> MaskingResult:
    """
    يستبدل البيانات الحساسة بـ placeholders فريدة.

    مثال:
        input:   "رقم هاتف العميل: 0501234567"
        output:  "رقم هاتف العميل: <<PHONE_SA_a3f2c1>>"
        mappings: {"<<PHONE_SA_a3f2c1>>": "0501234567"}
    """
    result = text
    mappings: dict = {}
    count = 0

    for ptype in PATTERN_ORDER:
        pattern = PATTERNS[ptype]
        matches = list(pattern.finditer(result))

        for match in matches:
            original = match.group(0)
            # placeholder فريد يعتمد على salt + القيمة
            h = hashlib.sha256(
                f"{session_salt}:{original}".encode()
            ).hexdigest()[:6]
            placeholder = f"<<{ptype}_{h}>>"

            if placeholder not in mappings:
                mappings[placeholder] = original
                count += 1

            result = result.replace(original, placeholder, 1)

    if count > 0:
        types_found = list({k.split("_")[0] for k in mappings})
        log.info(
            "Sensitive data masked before API call",
            fields_masked=count,
            types=types_found,
        )

    return MaskingResult(masked_text=result, mappings=mappings, count=count)


def unmask_data(text: str, mappings: dict) -> str:
    """
    يستعيد القيم الأصلية من الـ placeholders.
    يُستخدم فقط عند تسليم الإجابة للمستخدم المُصرَّح له.
    """
    result = text
    for placeholder, original in mappings.items():
        result = result.replace(placeholder, original)
    return result


def mask_dict(
    data: dict,
    keys_to_mask: list,
    session_salt: str = "",
) -> tuple:
    """
    يُطبّق masking على قيم محددة في dict.
    يُرجع: (masked_dict, all_mappings)
    """
    masked = dict(data)
    all_mappings = {}

    for key in keys_to_mask:
        if key in masked and isinstance(masked[key], str):
            r = mask_sensitive_data(masked[key], session_salt)
            masked[key] = r.masked_text
            all_mappings.update(r.mappings)

    return masked, all_mappings
