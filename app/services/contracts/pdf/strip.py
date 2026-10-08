"""Delete placeholder glyphs from a page's text layer (pypdf).

The filled values are drawn on top over a white box, so this is about the text
layer only: without it, copying text out of the signed PDF would still give
``#last_name``. A text-showing operator is dropped when *every* glyph it draws
belongs to a placeholder — the case for templates exported by Word, which draws
each glyph (or each placeholder) separately. An operator mixing placeholder and
other text is left alone (still hidden under the box): taking glyphs out of the
middle of a run would shift the rest of it.
"""
from __future__ import annotations

_SHOWS = {b"Tj", b"TJ", b"'", b'"'}


def _bytes_per_glyph(fonts, name):
    """1 for a simple font, 2 for an Identity-encoded CID font, None if unknown."""
    font = fonts.get(name)
    font = font.get_object() if font is not None else None
    if font is None:
        return None
    if font.get("/Subtype") != "/Type0":
        return 1
    return 2 if str(font.get("/Encoding")) in ("/Identity-H", "/Identity-V") else None


def _shown(operands, op) -> list:
    if op == b"TJ":
        return [s for s in operands[0] if isinstance(s, (str, bytes))]
    return [operands[-1]]


def _raw(string) -> bytes:
    original = getattr(string, "original_bytes", None)
    return original if original is not None else bytes(string)


def _replacement(operands, op) -> list:
    """What remains of a dropped operator: ``'`` and ``"`` also move to the next line."""
    if op == b"'":
        return [([], b"T*")]
    if op == b'"':
        return [([operands[0]], b"Tw"), ([operands[1]], b"Tc"), ([], b"T*")]
    return []


def strip(page, placeholder_glyphs: set, glyph_total: int) -> bool:
    """Drop the operators that draw only placeholder glyphs. ``False`` (page left as it
    is) when the operators cannot be matched glyph-for-glyph to what pdfminer read."""
    content = page.get_contents()
    resources = page.get("/Resources")
    fonts = (resources.get_object().get("/Font") if resources is not None else None) or {}
    fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
    if content is None:
        return False
    width, saved, counted, kept = None, [], 0, []
    for operands, op in content.operations:
        if op == b"q":
            saved.append(width)
        elif op == b"Q" and saved:
            width = saved.pop()
        elif op == b"Tf":
            width = _bytes_per_glyph(fonts, operands[0])
        if op not in _SHOWS:
            kept.append((operands, op))
            continue
        if width is None:
            return False
        n = sum(len(_raw(s)) // width for s in _shown(operands, op))
        mine = range(counted, counted + n)
        counted += n
        if n and all(i in placeholder_glyphs for i in mine):
            kept.extend(_replacement(operands, op))
        else:
            kept.append((operands, op))
    if counted != glyph_total:
        return False
    content.operations = kept
    page.replace_contents(content)
    return True
