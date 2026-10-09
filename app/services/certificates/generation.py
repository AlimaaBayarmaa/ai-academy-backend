"""The certificate PDF, generated from the course's template (as ``ai-asia-contract``
generated each class's certificates), stored on S3.

A course with a PDF certificate template gets its PDFs made automatically: on
issue, on a staff "generate" and — for anything issued before the template was
uploaded — on the student's first download. Without a template the file stays a
staff upload (``PUT /admin/certificates/<id>/file``).
"""
from __future__ import annotations

import io
import logging

from app import pdftools
from app.extensions import db
from app.models import Certificate
from app.storage import S3StorageError, build_key, read_template, upload_fileobj
from app.timeutil import local

from ..errors import ServiceError
from .pdf import TemplateError, fill_certificate
from .verification import verify_url

log = logging.getLogger(__name__)


def has_template(course) -> bool:
    return course is not None and course.has_pdf_cert_template


def file_key(cert: Certificate) -> str:
    return build_key("certificates", f"{cert.cert_number}.pdf")


def render(cert: Certificate) -> bytes:
    course, student = cert.course, cert.student
    if not has_template(course):
        raise ServiceError(409, "certificate_template_missing")
    version = (course.cert_template_key, course.updated_at)
    try:
        template = read_template(*version)
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None
    try:
        return fill_certificate(
            template, layouts=_layouts(template, version), number=cert.cert_number,
            first_name=student.first_name, last_name=student.last_name,
            issued_on=local(cert.issued_at).date(), verify_url=verify_url(cert.cert_number))
    except TemplateError:
        raise ServiceError(409, "certificate_template_invalid") from None
    except Exception:  # noqa: BLE001 — an odd template must not 500 an issue already saved
        log.exception("certificate %s: template could not be filled", cert.cert_number)
        raise ServiceError(409, "certificate_template_invalid") from None


_LAYOUTS: dict = {}  # template version -> parsed pages, so a class re-parses it once


def _layouts(template: bytes, version):
    layouts = _LAYOUTS.get(version)
    if layouts is None:
        try:
            layouts = pdftools.read_pages(template)
        except Exception:  # noqa: BLE001 — fill_certificate reports it as a TemplateError
            return None
        _LAYOUTS.clear()  # only the latest template is worth keeping
        _LAYOUTS[version] = layouts
    return layouts


def generate(cert: Certificate) -> Certificate:
    """(Re)build the PDF and store it as the certificate's file."""
    pdf = render(cert)
    key = file_key(cert)
    try:
        upload_fileobj(io.BytesIO(pdf), key, "application/pdf")
    except S3StorageError:
        raise ServiceError(502, "storage_error") from None
    cert.file_key = key
    cert.verify_url = verify_url(cert.cert_number)
    db.session.commit()
    return cert


def generate_if_possible(cert: Certificate) -> bool:
    """For issuing: make the PDF when the course has a template; a failure is logged,
    and leaves the certificate issued without a file (staff can retry)."""
    if not has_template(cert.course):
        return False
    try:
        generate(cert)
        return True
    except ServiceError as exc:
        log.warning("certificate %s: PDF not generated (%s)", cert.cert_number, exc.code)
        return False
