from __future__ import annotations

import re


DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]")
TAMIL_PATTERN = re.compile(r"[\u0B80-\u0BFF]")


def detect_language(text: str, fallback: str = "en") -> str:
    normalized = (text or "").strip()
    if not normalized:
        return fallback

    if DEVANAGARI_PATTERN.search(normalized):
        return "hi"
    if TAMIL_PATTERN.search(normalized):
        return "ta"

    lower_text = normalized.lower()
    hindi_markers = (
        "namaste",
        "kripya",
        "samay",
        "mujhe",
        "chahiye",
        "kal",
        "aaj",
    )
    tamil_markers = (
        "vanakkam",
        "maruthuvam",
        "sandhippu",
        "neram",
        "indru",
        "naalai",
        "venum",
    )

    if any(token in lower_text for token in hindi_markers):
        return "hi"
    if any(token in lower_text for token in tamil_markers):
        return "ta"
    return "en"


def get_language_name(language_code: str) -> str:
    lookup = {
        "en": "English",
        "hi": "Hindi",
        "ta": "Tamil",
    }
    return lookup.get(language_code, "English")
