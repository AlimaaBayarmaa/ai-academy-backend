"""Fill a contract PDF template — the ``ai-asia-contract`` ``fill.py`` logic.

Each literal placeholder (``#last_name``, ``<COVERAGE_PROGRAM>``, ``#signature`` …)
is covered with a white box and its value written there in bold UPPERCASE (the
e-mail keeps its case), shrunk when it would run into the next word on the line.
The signature sits on the ``#signature`` line. :mod:`app.pdftools` finds the
placeholders, deletes their text and stamps the overlay.
"""
from __future__ import annotations

import functools
import io
import os
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app import pdftools

SIG_TOKEN = "#signature"
KEEP_CASE = ("#email",)  # an address is not upper-cased like the other values
_BUNDLED_FONT = Path(pdftools.__file__).resolve().parent / "fonts" / "OpenSans-Regular.ttf"

# Bold Cyrillic fonts first (macOS dev, then the Docker image's fonts-liberation);
# the bundled regular font keeps it working anywhere. PDF_FONT overrides.
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    str(_BUNDLED_FONT),
)


class TemplateError(Exception):
    """The template bytes are not a readable PDF."""


@functools.lru_cache(maxsize=1)
def font_name() -> str:
    """Register the first available font with reportlab, once per process."""
    for path in (os.environ.get("PDF_FONT", ""), *FONT_CANDIDATES):
        if path and os.path.exists(path):
            pdfmetrics.registerFont(TTFont("ContractFont", path))
            return "ContractFont"
    raise RuntimeError("no Cyrillic font found; set PDF_FONT")


def _fit_size(font: str, text: str, base: float, x0: float, right_bound) -> float:
    """Shrink the font so the text stops short of the next word on its line."""
    if not right_bound:
        return base
    avail = right_bound - x0 - 2
    if avail <= 0:
        return base
    width = pdfmetrics.stringWidth(text, font, base)
    if width <= avail:
        return base
    return max(round(base * avail / width, 1), 3.0)


def _draw(hits, signature_png):
    """White boxes over the placeholders, then the values and the signature."""
    font = font_name()

    def draw(c, _width, _height):
        c.setFillColorRGB(1, 1, 1)
        for _, hit in hits:
            c.rect(hit.x0, hit.y0, hit.x1 - hit.x0, hit.y1 - hit.y0, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        for text, hit in hits:
            h = hit.y1 - hit.y0
            if text is None:  # the signature line
                if signature_png:
                    c.drawImage(ImageReader(io.BytesIO(signature_png)), hit.x0 - 60,
                                hit.y0 - 34, width=210, height=h + 34, mask="auto",
                                preserveAspectRatio=True, anchor="c")
            elif text:
                size = _fit_size(font, text, round(h * 0.86, 1), hit.x0, hit.right_bound)
                c.setFont(font, size)
                c.drawString(hit.x0, hit.y0 + h * 0.22, text)

    return draw


def fill_contract(template: bytes, values: dict, signature_png: bytes | None = None) -> bytes:
    """``signature_png`` comes from :func:`~.signature.prepare_signature`."""
    try:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template)))
        layouts = pdftools.read_pages(template)
    except Exception as exc:  # noqa: BLE001 — pdfminer / pypdf raise many types
        raise TemplateError(str(exc)) from exc

    for page, layout in zip(writer.pages, layouts):
        found = pdftools.streams(layout)
        hits = []
        for token, value in values.items():
            text = value if token in KEEP_CASE else value.upper()
            hits += [(text, hit) for hit in pdftools.find(found, token)]
        hits += [(None, hit) for hit in pdftools.find(found, SIG_TOKEN)]
        if hits:
            # Contracts cover placeholders with white boxes and keep their line art
            # (field underlines); only certificates need Canva outlines erased.
            pdftools.remove(page, found, [hit for _, hit in hits], outlines=False)
            pdftools.stamp(page, _draw(hits, signature_png))

    out = io.BytesIO()
    try:
        writer.write(out)
    except PyPdfError as exc:
        raise TemplateError(str(exc)) from exc
    return out.getvalue()
