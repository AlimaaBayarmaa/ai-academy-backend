"""Fixtures for certificate generation: a template PDF on a fake S3.
Test modules bind the fixtures they use by name."""
import io
import unicodedata

import pytest

CERT_TEMPLATE_KEY = "courses/1/cert_template.pdf"


def cert_template_pdf(qr=True) -> bytes:
    """An A4-landscape certificate like the Canva ones: every placeholder, and a
    sample vector QR (dark squares) in the bottom-left badge."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(842, 595))
    c.setFont("Helvetica", 14)
    c.drawCentredString(421, 470, "#certificate_no")
    c.drawCentredString(421, 440, "is hereby awarded to")
    c.setFont("Helvetica", 40)
    c.drawString(270, 380, "#firstname")
    c.drawString(480, 380, "#lastname")
    c.setFont("Helvetica", 12)
    c.drawString(80, 300, "Capstone project:")
    c.drawString(190, 300, "#capstone_topic")
    c.setFont("Helvetica-BoldOblique", 17)
    c.drawCentredString(421, 40, "#date")
    if qr:
        c.setFillColorRGB(0, 0, 0)
        for i in range(8):
            for j in range(8):
                if (i + j) % 2 == 0:
                    c.rect(90 + i * 9, 90 + j * 9, 8, 8, stroke=0, fill=1)
    c.save()
    return buf.getvalue()


def pdf_text(data: bytes) -> str:
    from pdfminer.high_level import extract_text

    return unicodedata.normalize("NFKC", extract_text(io.BytesIO(data)))


class FakeS3:
    def __init__(self):
        self.objects = {CERT_TEMPLATE_KEY: (cert_template_pdf(), "application/pdf")}
        self.fail = set()

    def _check(self, op):
        from app.storage import S3StorageError
        if op in self.fail:
            raise S3StorageError(f"{op} failed")

    def upload_fileobj(self, fileobj, key, content_type=None):
        self._check("upload")
        self.objects[key] = (fileobj.read(), content_type)

    def download_stream(self, key):
        self._check("download")
        data, content_type = self.objects[key]
        return io.BytesIO(data), content_type

    def presigned_url(self, key, expires=300):
        self._check("presign")
        return f"https://s3.test/{key}?expires={expires}"


@pytest.fixture
def cert_s3(monkeypatch):
    from app.storage import read_template

    read_template.cache_clear()
    fake = FakeS3()
    monkeypatch.setattr("app.storage.s3.download_stream", fake.download_stream)
    monkeypatch.setattr("app.services.certificates.generation.upload_fileobj",
                        fake.upload_fileobj)
    for name in ("upload_fileobj", "presigned_url"):
        monkeypatch.setattr(f"app.services.certificates.issuing.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def templated(earned, db):
    """``earned`` with a certificate template on the course."""
    _, _, course, _ = earned
    course.cert_template_key = CERT_TEMPLATE_KEY
    db.session.commit()
    return earned


def issue(client, headers, student_id, course_id, **extra):
    return client.post("/admin/certificates", headers=headers,
                       json={"student_id": student_id, "course_id": course_id, **extra})
