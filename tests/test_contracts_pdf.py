"""The PDF filler on its own (pypdf + reportlab + pdfminer, no PyMuPDF)."""
import io
from datetime import date

from contract_helpers import good_form, guardian, pdf_text, template_pdf


def _values(**form):
    from app.services.contracts import fields

    return fields.build_values(fields.clean(good_form(**guardian(), **form)),
                               contract_number="AIAA-C-2026-00007", programme="Удирдагчид",
                               finance={"total_paid": 400_000, "balance": 600_000,
                                        "discount_percent": 5}, today=date(2026, 10, 8))


def test_every_placeholder_is_replaced_and_gone_from_the_text_layer():
    from app.services.contracts.pdf import fill_contract

    text = pdf_text(fill_contract(template_pdf(), _values()))
    for expected in ("AIAA-C-2026-00007", "10", "08", "ДОРЖ", "УБ12345678", "ЭХ", "САРАА",
                     "УДИРДАГЧИД", "5%", "400,000₮", "600,000₮", "bat@example.mn"):
        assert expected in text
    assert "#" not in text and "<COVERAGE_PROGRAM>" not in text


def test_a_placeholder_sharing_a_text_run_is_still_filled():
    from reportlab.pdfgen import canvas

    from app.services.contracts.pdf import fill_contract

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.setFont("Helvetica", 11)
    c.drawString(40, 780, "Name: #last_name, born here")  # one run: covered, not deleted
    c.save()
    assert "ДОРЖ" in pdf_text(fill_contract(buf.getvalue(), _values()))


def test_a_broken_template_is_a_template_error():
    import pytest

    from app.services.contracts.pdf import TemplateError, fill_contract

    with pytest.raises(TemplateError):
        fill_contract(b"%PDF-1.4 nonsense", _values())
