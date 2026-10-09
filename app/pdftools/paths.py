"""Erase vector shapes that lie inside placeholder boxes (pypdf).

Canva exports text twice: an invisible text layer and the visible letters as
filled outlines. Deleting the text (:mod:`.strip`) leaves the outlines, so every
painted path whose bounds fall entirely inside a placeholder's box is dropped too
— what the earlier PyMuPDF redaction did to "line art" under a placeholder.
Form XObjects are searched too. Clipping paths (``W n``) are kept.
"""
from __future__ import annotations

from pypdf.generic import ContentStream

from .strip import write_stream

_BUILD = {b"m", b"l", b"c", b"v", b"y", b"h", b"re"}
_PAINT = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
_MARGIN = 1.0


def _mul(a, b):
    """``a × b`` for PDF matrices ``(a, b, c, d, e, f)``."""
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def _apply(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _points(operands, op):
    nums = [float(v) for v in operands]
    if op == b"re":
        x, y, w, h = nums
        return [(x, y), (x + w, y + h)]
    return list(zip(nums[0::2], nums[1::2]))


def _inside(points, boxes) -> bool:
    """Within a box grown by a quarter of its height: script capitals and underscores
    reach past the glyph boxes pdfminer reports."""
    if not points:
        return False
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    for x0, y0, x1, y1 in boxes:
        pad = max(_MARGIN, (y1 - y0) * 0.25)
        if (min(xs) >= x0 - pad and max(xs) <= x1 + pad
                and min(ys) >= y0 - pad and max(ys) <= y1 + pad):
            return True
    return False


def _form(resources, name):
    xobjects = resources.get("/XObject") if resources is not None else None
    target = xobjects.get_object().get(name) if xobjects is not None else None
    target = target.get_object() if target is not None else None
    return target if target is not None and target.get("/Subtype") == "/Form" else None


def _walk(operations, ctm, boxes, resources, pdf, seen):
    """(operations to keep, paths dropped) for one stream; recurses into Form XObjects,
    where Canva puts whole certificates."""
    saved, kept, path, points, dropped = [], [], [], [], 0
    for operands, op in operations:
        if op in _BUILD:
            path.append((operands, op))
            points += [_apply(ctm, x, y) for x, y in _points(operands, op)]
            continue
        if path:
            if op in _PAINT and _inside(points, boxes):
                dropped += 1
            else:
                kept.extend(path)
                kept.append((operands, op))
            path, points = [], []
            continue
        if op == b"q":
            saved.append(ctm)
        elif op == b"Q" and saved:
            ctm = saved.pop()
        elif op == b"cm":
            ctm = _mul(tuple(float(v) for v in operands), ctm)
        elif op == b"Do":
            dropped += _erase_form(_form(resources, operands[0]), ctm, boxes, resources,
                                   pdf, seen)
        kept.append((operands, op))
    kept.extend(path)
    return kept, dropped


def _erase_form(form, ctm, boxes, resources, pdf, seen) -> int:
    if form is None or id(form) in seen:
        return 0
    seen.add(id(form))
    matrix = tuple(float(v) for v in form.get("/Matrix", (1, 0, 0, 1, 0, 0)))
    content = ContentStream(form, pdf)
    kept, dropped = _walk(content.operations, _mul(matrix, ctm), boxes,
                          (form.get("/Resources") or resources).get_object(), pdf, seen)
    if dropped:
        content.operations = kept
        write_stream(form, content.get_data())
    return dropped


def erase(page, boxes: list) -> int:
    """Drop the painted paths inside ``boxes`` (pdfminer coordinates) from the page and
    the Form XObjects it draws. Returns how many were dropped."""
    content = page.get_contents()
    if content is None or not boxes:
        return 0
    box = page.mediabox
    ctm = (1.0, 0.0, 0.0, 1.0, -float(box.left), -float(box.bottom))
    resources = page.get("/Resources")
    kept, dropped = _walk(content.operations, ctm, boxes,
                          resources.get_object() if resources is not None else None,
                          page.pdf, set())
    if dropped:
        content.operations = kept
        page.replace_contents(content)
    return dropped
