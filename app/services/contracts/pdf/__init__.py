"""Contract PDFs with permissively licensed libraries (no AGPL PyMuPDF).

- ``locate``    : pdfminer.six — where each placeholder is on the page
- ``strip``     : pypdf — drop the placeholder text from the text layer
- ``fill``      : reportlab overlay with the values + signature, merged by pypdf
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
