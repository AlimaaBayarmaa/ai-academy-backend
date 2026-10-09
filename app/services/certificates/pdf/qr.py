"""The verification QR: where the template's sample QR is, and drawing ours over it.

Templates carry a sample QR in the bottom-left badge. As in ``ai-asia-contract``:
- **vector** QR (AI Engineer / Leaders): the box around the small dark filled
  shapes in the bottom-left corner;
- **raster** QR inside a badge image (Junior AI): the box around the badge
  image's dark pixels.
A ``#qr`` text placeholder, if a template has one, wins over both.

Ours is drawn as vector rounded modules (like the earlier rounded-module PNG) on a
white square that covers the sample.
"""
from __future__ import annotations

import segno
from pdfminer.layout import LTCurve, LTFigure, LTImage, LTRect
from PIL import ImageChops

_DESIGN_WIDTH = 842.0  # the A4-landscape templates the size limits were tuned on


def _walk(container, path=()):
    for item in container:
        if isinstance(item, LTFigure):
            yield from _walk(item, path + (item.name,))
        else:
            yield item, path


def _dark(color) -> bool:
    if color is None:
        return False
    values = color if isinstance(color, (list, tuple)) else (color,)
    try:
        values = [float(v) for v in values]
    except (TypeError, ValueError):
        return False  # a pattern / named colour
    if len(values) == 4:  # CMYK
        return values[3] > 0.7 or all(v > 0.7 for v in values[:3])
    return all(v < 0.3 for v in values)


def _square(w, h, tolerance=0.15) -> bool:
    return w > 0 and h > 0 and abs(w - h) <= tolerance * max(w, h)


def _vector_box(layout, width, height):
    """QR modules are dark squares; glyph outlines and ornaments rarely are."""
    limit = 60 * width / _DESIGN_WIDTH
    shapes = [item for item, _ in _walk(layout)
              if isinstance(item, (LTRect, LTCurve)) and item.fill
              and _dark(item.non_stroking_color) and _square(item.width, item.height)
              and item.x1 < width * 0.3 and item.y1 < height * 0.4 and item.width < limit]
    if len(shapes) < 20:
        return None
    box = (min(s.x0 for s in shapes), min(s.y0 for s in shapes),
           max(s.x1 for s in shapes), max(s.y1 for s in shapes))
    return box if _square(box[2] - box[0], box[3] - box[1]) else None


def _image(page, path, name):
    resources = page["/Resources"].get_object()
    for part in path:
        owner = resources["/XObject"][f"/{part}"].get_object()
        resources = (owner.get("/Resources") or resources).get_object()
    return resources["/XObject"][f"/{name}"].get_object().decode_as_image()


def _raster_box(page, layout, width, height):
    badges = [(item, path) for item, path in _walk(layout)
              if isinstance(item, LTImage) and item.x1 < width * 0.4
              and item.y1 < height * 0.4 and item.width > width * 0.047]
    if not badges:
        return None
    badge, path = max(badges, key=lambda pair: pair[0].width)
    try:
        img = _image(page, path, badge.name).convert("RGBA")
    except Exception:  # noqa: BLE001 — an image pypdf cannot decode has no QR we can find
        return None
    r, g, b, a = img.split()
    dark = [band.point(lambda v: 255 if v < 100 else 0) for band in (r, g, b)]
    opaque = a.point(lambda v: 255 if v >= 128 else 0)  # transparent pixels read as black
    found = ImageChops.multiply(ImageChops.multiply(ImageChops.multiply(*dark[:2]), dark[2]),
                                opaque).getbbox()
    if found is None:
        return None
    left, upper, right, lower = found
    sx, sy = badge.width / img.width, badge.height / img.height
    return (badge.x0 + left * sx, badge.y1 - lower * sy,
            badge.x0 + right * sx, badge.y1 - upper * sy)


def find_box(page, layout, width, height, marker=None):
    """``(x0, y0, x1, y1)`` for the QR, or ``None`` when the template has none."""
    if marker is not None:
        side = max(marker.x1 - marker.x0, marker.y1 - marker.y0)
        return marker.x0, marker.y1 - side, marker.x0 + side, marker.y1
    return _vector_box(layout, width, height) or _raster_box(page, layout, width, height)


def draw(c, box, url: str, ink=(0, 0, 0)) -> None:
    """A white square over ``box`` with the QR for ``url`` centred in it."""
    x0, y0, x1, y1 = box
    side = min(x1 - x0, y1 - y0)
    left, bottom = (x0 + x1 - side) / 2, (y0 + y1 - side) / 2
    c.setFillColorRGB(1, 1, 1)
    c.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
    rows = list(segno.make(url, error="m").matrix_iter(border=1))
    module = side / len(rows)
    c.setFillColorRGB(*ink)
    for i, row in enumerate(rows):
        for j, dark in enumerate(row):
            if dark:
                c.roundRect(left + j * module, bottom + side - (i + 1) * module,
                            module, module, module * 0.35, stroke=0, fill=1)
