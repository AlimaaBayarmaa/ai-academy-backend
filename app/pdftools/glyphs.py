"""Where text sits on a template page (pdfminer.six), grouped by content stream.

A page draws text from its own content stream and from Form XObjects (Canva puts
a whole certificate inside one). Each :class:`Stream` holds the glyphs one stream
draws, in drawing order (no layout analysis), so glyph *i* is the *i*-th glyph
that stream shows — :mod:`.strip` relies on that to delete placeholders.
"""
from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass, field

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar, LTFigure
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage


@dataclass
class Stream:
    """``path`` names the Form XObjects from the page down; ``()`` is the page itself."""
    path: tuple
    chars: list = field(default_factory=list)


@dataclass
class Hit:
    """One placeholder: its box (PDF units, origin bottom-left of the media box), the
    x where the next word on its line starts, the look of its first glyph, and the
    glyphs it covers in ``stream``."""
    x0: float
    y0: float
    x1: float
    y1: float
    right_bound: float | None
    baseline: float
    size: float
    color: object
    stream: int
    glyphs: range


def read_pages(template: bytes) -> list:
    """One pdfminer ``LTPage`` per page."""
    manager = PDFResourceManager()
    device = PDFPageAggregator(manager, laparams=None)
    interpreter = PDFPageInterpreter(manager, device)
    pages = []
    for page in PDFPage.get_pages(io.BytesIO(template)):
        interpreter.process_page(page)
        pages.append(device.get_result())
    return pages


def streams(layout) -> list:
    """The page's glyphs split by the content stream that draws them."""
    out = []

    def walk(container, path):
        here = Stream(path)
        out.append(here)
        for item in container:
            if isinstance(item, LTChar):
                here.chars.append(item)
            elif isinstance(item, LTFigure):
                walk(item, path + (item.name,))

    walk(layout, ())
    return [s for s in out if s.chars]


def _text(glyph) -> str:
    return unicodedata.normalize("NFKC", glyph.get_text())  # "ﬁ" ligature -> "fi"


def find(page_streams: list, token: str, *, ignore_spaces: bool = False) -> list:
    """Every occurrence of ``token`` (case-sensitive). ``ignore_spaces`` also matches a
    letter-spaced placeholder (``# c a p s t o n e``)."""
    every = [g for s in page_streams for g in s.chars if _text(g).strip()]
    hits = []
    for index, stream in enumerate(page_streams):
        text, owner = "", []  # owner[i] = the glyph that drew text[i]
        for n, glyph in enumerate(stream.chars):
            piece = _text(glyph)
            if ignore_spaces:
                piece = "".join(piece.split())
            text += piece
            owner += [n] * len(piece)
        start = text.find(token)
        while start != -1:
            first, last = owner[start], owner[start + len(token) - 1]
            hits.append(_hit(stream, index, first, last, every))
            start = text.find(token, start + len(token))
    return hits


def _hit(stream, index, first, last, every) -> Hit:
    span = stream.chars[first:last + 1]
    x0, y0 = min(g.x0 for g in span), min(g.y0 for g in span)
    x1, y1 = max(g.x1 for g in span), max(g.y1 for g in span)
    rights = [g.x0 for g in every if abs(g.y1 - y1) < 3 and g.x0 >= x1 - 0.5]
    head = span[0]
    return Hit(x0, y0, x1, y1, min(rights) if rights else None,
               baseline=head.matrix[5], size=head.size,
               color=getattr(head.graphicstate, "ncolor", None),
               stream=index, glyphs=range(first, last + 1))


def union(hits: list):
    """The box around several hits, as ``(x0, y0, x1, y1)``."""
    return (min(h.x0 for h in hits), min(h.y0 for h in hits),
            max(h.x1 for h in hits), max(h.y1 for h in hits))
