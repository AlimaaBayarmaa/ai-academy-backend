"""The contract form: which fields, how they are checked, and how they map onto the PDF.

The rules are the ``ai-asia-contract`` form's (``static/app.js`` ``validate()``):
names, the guardian's relation and the address in Cyrillic only; a register
number is two Cyrillic letters + 8 digits; a phone is 8 digits. ``phone`` /
``email`` are the contact on the contract — the guardian's for a child. Two rules are
generalised from that one summer camp: the guardian block is required for a
``junior`` course only, and the last-payment date only while a balance is owed,
between today and the cohort's end date (it was a fixed window there).
"""
from __future__ import annotations

import re
from datetime import date

FIELDS = (
    "last_name", "first_name", "register",
    "guardian_relation", "guardian_last_name", "guardian_first_name",
    "guardian_register", "phone", "email",
    "address", "final_payment_date",
)
STUDENT_REQUIRED = ("last_name", "first_name", "register", "phone", "address")
GUARDIAN_REQUIRED = ("guardian_relation", "guardian_last_name", "guardian_first_name",
                     "guardian_register")
CYRILLIC_ONLY = ("last_name", "first_name", "guardian_relation",
                 "guardian_last_name", "guardian_first_name", "address")
MAX_LENGTH = 300

RE_REGISTER = re.compile(r"^[Ѐ-ӿ]{2}\d{8}$")
RE_PHONE = re.compile(r"^\d{8}$")
RE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
RE_LATIN = re.compile(r"[A-Za-z]")


def _register(value: str) -> str:
    """Upper-case the two letters, as the web form did while typing."""
    return value[:2].upper() + value[2:]


def clean(raw) -> dict:
    """Known fields only, as trimmed strings (register numbers normalised)."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in FIELDS:
        value = raw.get(key)
        value = "" if value is None else str(value).strip()
        if key in ("register", "guardian_register"):
            value = _register(value)
        out[key] = value
    return out


def _format_checks(rules: dict, today: date):
    """``(fields, check)`` pairs; ``check(value)`` returns a reason or ``None``."""
    def date_check(text):
        return _date_problem(text, today, rules["final_payment_date_max"])

    return (
        (CYRILLIC_ONLY, lambda v: "cyrillic_only" if RE_LATIN.search(v) else None),
        (("register", "guardian_register"),
         lambda v: None if RE_REGISTER.match(v) else "invalid_format"),
        (("phone",), lambda v: None if RE_PHONE.match(v) else "invalid_format"),
        (("email",), lambda v: None if RE_EMAIL.match(v) else "invalid_format"),
        (("final_payment_date",), date_check),
    )


def validate(form: dict, rules: dict, today: date) -> dict:
    """``{field: reason}`` for every problem; empty when the form can be signed.

    Reasons: ``required``, ``too_long``, ``cyrillic_only``, ``invalid_format``,
    ``out_of_range``. A field reports its first problem only.
    """
    required = list(STUDENT_REQUIRED)
    if rules["guardian_required"]:
        required += GUARDIAN_REQUIRED
    if rules["final_payment_date_required"]:
        required.append("final_payment_date")
    errors = {key: "required" for key in required if not form[key]}
    errors.update({key: "too_long" for key in FIELDS if len(form[key]) > MAX_LENGTH})
    for keys, check in _format_checks(rules, today):
        for key in keys:
            if form[key] and key not in errors:
                reason = check(form[key])
                if reason:
                    errors[key] = reason
    return errors


def _date_problem(text: str, today: date, latest: str | None) -> str | None:
    try:
        value = date.fromisoformat(text)
    except ValueError:
        return "invalid_format"
    if value < today or (latest and value > date.fromisoformat(latest)):
        return "out_of_range"
    return None


def _money(amount) -> str:
    """``1,780,000₮``; nothing owed prints as an em dash (the web form's ``-``)."""
    if not amount:
        return "—"
    return f"{int(round(float(amount))):,}₮"


def build_values(form: dict, *, contract_number: str, programme: str, finance: dict,
                 today: date) -> dict:
    """The template placeholders and what goes in each (``fill.py build_values``)."""
    return {
        "#month": f"{today.month:02d}",
        "#day": f"{today.day:02d}",
        "#contact_name": contract_number,
        "#last_name": form["last_name"],
        "#first_name": form["first_name"],
        "#register": form["register"],
        "#g_relation": form["guardian_relation"],
        "#address_detail": form["address"],
        "#g_last_name": form["guardian_last_name"],
        "#g_first_name": form["guardian_first_name"],
        "#g_register": form["guardian_register"],
        "<COVERAGE_PROGRAM>": programme,
        "#discount": f"{finance['discount_percent'] or 0}%",
        "#advance": _money(finance["total_paid"]),
        "#balance": _money(finance["balance"]),
        "#final_payment_date": form["final_payment_date"].replace("-", "."),
        "#phone": form["phone"],
        "#email": form["email"],
    }
