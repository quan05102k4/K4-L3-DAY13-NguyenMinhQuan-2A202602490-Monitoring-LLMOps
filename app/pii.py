from __future__ import annotations

import hashlib
import re

# Lookaround (?<!\d)/(?!\d) ngăn pattern khớp một phần của số dài hơn.
# CCCD (12 số liền) chạy trước thẻ: separator của thẻ là tùy chọn nên
# "001099012345 4111 1111 1111 1111" sẽ bị pattern thẻ nuốt nhầm CCCD nếu đảo thứ tự.
PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "cccd": r"(?<!\d)\d{12}(?!\d)",
    "credit_card": r"(?<!\d)\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?!\d)",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    "passport_vn": r"\b[A-Z]\d{7}\b",
}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in PII_PATTERNS.items():
        safe = re.sub(pattern, f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
