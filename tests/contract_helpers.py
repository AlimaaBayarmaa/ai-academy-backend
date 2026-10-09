"""Shared fixtures for the e-contract tests (/me/contracts, /admin/contracts).
Test modules bind the fixtures they use by name."""
import base64
import io
import unicodedata
from datetime import date, timedelta

import pytest
from PIL import Image, ImageDraw

TEMPLATE_KEY = "courses/1/contract_template.pdf"
PLACEHOLDERS = (
    "No #contact_name #month / #day",
    "#last_name #first_name #register",
    "#g_relation #g_last_name #g_first_name #g_register",
    "<COVERAGE_PROGRAM>",
    "#address_detail",
    "#discount #advance #balance #final_payment_date",
    "#phone #email",
    "Signature: #signature",
)


def template_pdf() -> bytes:
    """A one-page template carrying every placeholder the real contract uses. Each word
    is its own text run, as in a Word export."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.setFont("Helvetica", 11)
    for i, line in enumerate(PLACEHOLDERS):
        x = 40
        for word in line.split(" "):
            c.drawString(x, 780 - i * 30, word)
            x += stringWidth(word + " ", "Helvetica", 11)
    c.save()
    return buf.getvalue()


def pdf_text(data: bytes) -> str:
    from pdfminer.high_level import extract_text

    return unicodedata.normalize("NFKC", extract_text(io.BytesIO(data)))


def signature_png(width=40, height=20, ink=(5, 8, 35, 12), fmt="png") -> str:
    """A drawn-signature image as the app sends it: a base64 data URL. ``ink=None`` is
    a blank pad."""
    img = Image.new("RGB", (width, height), "white")
    if ink:
        ImageDraw.Draw(img).rectangle(ink, fill="black")
    buf = io.BytesIO()
    img.save(buf, fmt.upper())
    return f"data:image/{fmt};base64," + base64.b64encode(buf.getvalue()).decode()


def good_form(**overrides) -> dict:
    form = {
        "last_name": "Дорж", "first_name": "Бат", "register": "уб12345678",
        "phone": "99112233", "email": "bat@example.mn",
        "address": "Улаанбаатар хот, Сүхбаатар дүүрэг",
        "final_payment_date": (date.today() + timedelta(days=7)).isoformat(),
    }
    form.update(overrides)
    return form


def guardian(**overrides) -> dict:
    data = {"guardian_relation": "эх", "guardian_last_name": "Дорж",
            "guardian_first_name": "Сараа", "guardian_register": "УБ87654321"}
    data.update(overrides)
    return data


# ----------------------------------------------------------------- S3
class FakeS3:
    def __init__(self):
        self.objects = {TEMPLATE_KEY: (template_pdf(), "application/pdf")}
        self.fail = set()
        self.deleted = []

    def _check(self, op):
        from app.storage import S3StorageError
        if op in self.fail:
            raise S3StorageError(f"{op} failed")

    def upload_fileobj(self, fileobj, key, content_type=None):
        self._check("upload")
        self.objects[key] = (fileobj.read(), content_type)

    def download_stream(self, key):
        import io
        self._check("download")
        data, content_type = self.objects[key]
        return io.BytesIO(data), content_type

    def presigned_url(self, key, expires=300):
        self._check("presign")
        return f"https://s3.test/{key}?expires={expires}"

    def delete_object(self, key):
        self._check("delete")
        self.deleted.append(key)
        self.objects.pop(key, None)


def stored(s3, contract_id, suffix) -> tuple:
    """(key, bytes) of the one object under ``contracts/<id>/`` ending in ``suffix``."""
    [(key, (data, _))] = [(k, v) for k, v in s3.objects.items()
                          if k.startswith(f"contracts/{contract_id}/") and k.endswith(suffix)]
    return key, data


@pytest.fixture
def s3(monkeypatch):
    from app.storage import read_template

    read_template.cache_clear()  # the template cache is per process; tests swap templates
    fake = FakeS3()
    monkeypatch.setattr("app.storage.s3.download_stream", fake.download_stream)
    for target in ("student.upload_fileobj", "student.presigned_url", "staff.delete_object"):
        name = target.split(".")[1]
        monkeypatch.setattr(f"app.services.contracts.{target}", getattr(fake, name))
    return fake


# ----------------------------------------------------------------- domain
@pytest.fixture
def contract_course(make_course):
    """``contract_course(level="adult", **fields)`` -> a course with a PDF contract template."""
    def _make(level="adult", **fields):
        values = {"level": level, "contract_template_key": TEMPLATE_KEY,
                  "contract_template_name": "contract.pdf", "title_mn": "Удирдагчид"}
        values.update(fields)
        return make_course(**values)

    return _make


@pytest.fixture
def signer(s3, make_student, contract_course, make_cohort, enroll, make_ledger):
    """``signer(level="adult", due=1_000_000, paid=400_000)`` ->
    (account, headers, enrollment, contract_id)."""
    def _make(level="adult", due=1_000_000, paid=400_000, client=None, **student):
        student.setdefault("last_name", "Дорж")
        student.setdefault("phone", "99112233")
        account, headers = make_student(**student)
        cohort = make_cohort(course=contract_course(level=level))
        enr = enroll(account.actor_id, cohort)
        if due is not None:
            make_ledger(enr, due=due, paid=paid)
        contract_id = None
        if client is not None:
            [row] = client.get("/me/contracts", headers=headers).get_json()["contracts"]
            contract_id = row["id"]
        return account, headers, enr, contract_id

    return _make


def sign(client, headers, contract_id, form=None, signature=None, agreed=True):
    payload = {"form": form if form is not None else good_form(), "agreed": agreed,
               "signature": signature if signature is not None else signature_png()}
    return client.post(f"/me/contracts/{contract_id}/sign", headers=headers, json=payload)
