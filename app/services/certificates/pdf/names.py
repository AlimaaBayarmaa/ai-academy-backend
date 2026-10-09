"""Names and dates as the certificate prints them (``ai-asia-contract`` ``certificate.py``).

The certificate is in English: a Mongolian Cyrillic name is transliterated the
way the earlier certificates were (Neguun Purevdorj, Tsetsenbileg), each word
capitalised, given name first.
"""
from __future__ import annotations

import re
from datetime import date

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "ө": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ү": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "sh", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def _clean(text: str | None) -> str:
    text = re.sub(r"\(.*?\)", "", (text or "").strip())  # drop notes: "(Asral egch)"
    text = text.split("/")[0]                              # "Удвал /Уугий" -> the first
    return re.sub(r"\s+", " ", text).strip()


def transliterate(text: str | None) -> str:
    """Latin letters, each word capitalised. Latin input only gets the capitals."""
    out = "".join(_TRANSLIT.get(ch, ch) for ch in _clean(text).lower())
    return re.sub(r"(^|[\s\-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)


def full_name(first_name: str | None, last_name: str | None) -> str:
    return f"{transliterate(first_name)} {transliterate(last_name)}".strip()


def long_date(day: date) -> str:
    """``October 9, 2026`` — fixed English, whatever the server locale."""
    return f"{_MONTHS[day.month - 1]} {day.day}, {day.year}"
