"""Contract PDFs with permissively licensed libraries (no AGPL PyMuPDF).

- ``fill``      : the values + signature on the template (via :mod:`app.pdftools`)
- ``signature`` : Pillow — check the drawn PNG, make its background transparent
"""
from .fill import TemplateError, fill_contract
from .signature import MAX_DECODE_PIXELS, SignatureError, prepare_signature

__all__ = [
    "MAX_DECODE_PIXELS",
    "SignatureError",
    "TemplateError",
    "fill_contract",
    "prepare_signature",
]
