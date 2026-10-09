"""Public certificate verification and the code that guards it (spec §4.4).

Certificate numbers are sequential (``AIAA-2026-00012``), so anyone could walk
them. The printed QR therefore carries a short HMAC of the number
(``?code=…``, as the earlier certificates' signed QR token did): with the right
code the page shows whose certificate it is; without it, only that the number is
a valid certificate. Archived or unknown numbers are ``404``.
"""
from __future__ import annotations

import hashlib
import hmac

from flask import current_app

from app.models import Certificate
from app.timeutil import iso

from ..errors import ServiceError

CODE_LENGTH = 16


def code_for(cert_number: str) -> str:
    secret = current_app.config["CERT_SIGNING_SECRET"].encode()
    digest = hmac.new(secret, cert_number.encode(), hashlib.sha256).hexdigest()
    return digest[:CODE_LENGTH]


def verify_url(cert_number: str) -> str:
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    return f"{base}/certificates/verify/{cert_number}?code={code_for(cert_number)}"


def verify(cert_number, code=None) -> dict:
    cert = Certificate.query.filter_by(cert_number=str(cert_number), is_archived=False).first()
    if cert is None:
        raise ServiceError(404, "certificate_not_found")
    if code and hmac.compare_digest(str(code).encode(), code_for(cert.cert_number).encode()):
        return cert.to_verify_dict()
    # No (or a wrong) code: confirm the number, reveal no one.
    return {"valid": True, "cert_number": cert.cert_number, "issued_at": iso(cert.issued_at),
            "details_hidden": True}
