"""Page-level steps every filler takes: drop placeholder glyphs, stamp an overlay."""
from __future__ import annotations

import io

from pypdf import PdfReader, Transformation
from reportlab.pdfgen import canvas

from .glyphs import union
from .paths import erase
from .strip import strip


def remove(page, page_streams: list, hits: list, *, outlines: bool = True) -> None:
    """Delete the hits' glyphs from whichever streams draw them and, with ``outlines``,
    vector shapes inside their boxes (best effort: what cannot be matched stays,
    under whatever is drawn on top)."""
    by_path = {}  # one Form XObject drawn twice is one stream to rewrite, once
    for hit in hits:
        stream = page_streams[hit.stream]
        by_path.setdefault(stream.path, (stream, set()))[1].update(hit.glyphs)
    for stream, glyphs in by_path.values():
        strip(page, stream, glyphs)
    if not outlines:
        return
    boxes = [(h.x0, h.y0, h.x1, h.y1) for h in hits]
    lines = {}  # placeholders on one line may be outlined as one shape ("#firstname #lastname")
    for hit in hits:
        lines.setdefault((hit.stream, round(hit.baseline)), []).append(hit)
    boxes += [union(group) for group in lines.values() if len(group) > 1]
    erase(page, boxes)


def stamp(page, draw) -> None:
    """Merge what ``draw(canvas, width, height)`` paints onto ``page``. Coordinates are
    pdfminer's: origin at the media box's lower-left corner."""
    box = page.mediabox
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(float(box.width), float(box.height)))
    draw(c, float(box.width), float(box.height))
    c.save()
    overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
    page.merge_transformed_page(overlay, Transformation().translate(box.left, box.bottom))
