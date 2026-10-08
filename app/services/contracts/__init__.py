"""Student training contracts (e-contract), ported from ``ai-asia-contract``.

- ``core``    : when a contract exists, its money and rules, rendering the PDF
- ``fields``  : the form — validation and template placeholders
- ``pdf``     : template filling + signature image (pypdf, reportlab, pdfminer)
- ``student`` : ``/me/contracts`` list / detail / preview / sign / download
- ``staff``   : ``/admin/contracts`` list / detail / download / reset
"""
from . import staff, student

__all__ = ["staff", "student"]
