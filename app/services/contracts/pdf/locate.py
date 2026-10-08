"""Where each placeholder sits on a template page (pdfminer.six).

The page's glyphs are read in drawing order (no layout analysis), so glyph *i*
here is the *i*-th glyph the content stream shows — :mod:`.strip` relies on that
to delete the placeholders from the text layer.
"""
from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage


@dataclass
class Hit:
    """One occurrence of a placeholder: its box (PDF units, origin bottom-left),
    the x where the next word on its line starts (or None) and its glyph indexes."""
    x0: float
    y0: float
    x1: float
    y1: float
    right_bound: float | None
    glyphs: range


def page_glyphs(template: bytes) -> list:
    """Per page, the top-level :class:`LTChar` glyphs in drawing order."""
    manager = PDFResourceManager()
    device = PDFPageAggregator(manager, laparams=None)
    interpreter = PDFPageInterpreter(manager, device)
    pages = []
    for page in PDFPage.get_pages(io.BytesIO(template)):
        interpreter.process_page(page)
        pages.append([item for item in device.get_result() if isinstance(item, LTChar)])
    return pages


def find(glyphs: list, token: str) -> list:
    """Every occurrence of ``token`` among ``glyphs`` (case-sensitive)."""
    text, owner = "", []  # owner[i] = the glyph that drew text[i] (ligatures draw several)
    for index, glyph in enumerate(glyphs):
        piece = unicodedata.normalize("NFKC", glyph.get_text())  # "ﬁ" ligature -> "fi"
        text += piece
        owner += [index] * len(piece)
    hits, start = [], text.find(token)
    while start != -1:
        first, last = owner[start], owner[start + len(token) - 1]
        span = glyphs[first:last + 1]
        x0, y0 = min(g.x0 for g in span), min(g.y0 for g in span)
        x1, y1 = max(g.x1 for g in span), max(g.y1 for g in span)
        rights = [g.x0 for g in glyphs
                  if g.get_text().strip() and abs(g.y1 - y1) < 3 and g.x0 >= x1 - 0.5]
        hits.append(Hit(x0, y0, x1, y1, min(rights) if rights else None,
                        range(first, last + 1)))
        start = text.find(token, start + len(token))
    return hits
