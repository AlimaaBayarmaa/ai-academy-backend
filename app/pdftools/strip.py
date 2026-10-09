"""Delete placeholder glyphs from a content stream (pypdf), keeping the rest in place.

Each text-showing operator that draws a placeholder glyph is rewritten as a
``TJ`` array: the kept glyphs stay, and each removed run becomes a number that
moves the pen by exactly the width that run took — so text after a placeholder on
the same line does not shift. Widths come from pdfminer (``LTChar.adv``) together
with the text state tracked here (``Tf``, ``Tc``, ``Tw``, ``Tz``).

Glyphs are matched to operators by position, so the stream must decode
glyph-for-glyph like pdfminer read it (simple fonts and Identity-encoded CID
fonts). Otherwise nothing is changed and :func:`strip` answers ``False``.
"""
from __future__ import annotations

from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    ContentStream,
    FloatObject,
    NameObject,
)

_SHOWS = {b"Tj", b"TJ", b"'", b'"'}


def _bytes_per_glyph(fonts, name):
    """1 for a simple font, 2 for an Identity-encoded CID font, None if unknown."""
    font = fonts.get(name) if fonts is not None else None
    font = font.get_object() if font is not None else None
    if font is None:
        return None
    if font.get("/Subtype") != "/Type0":
        return 1
    return 2 if str(font.get("/Encoding")) in ("/Identity-H", "/Identity-V") else None


def _container(page, path):
    """(stream owner, its resources) — the page, or the Form XObject at ``path``."""
    owner, resources = page, page.get("/Resources")
    for name in path:
        xobjects = resources.get_object()["/XObject"]
        owner = xobjects[f"/{name}"].get_object()
        resources = owner.get("/Resources") or resources
    return owner, resources.get_object() if resources is not None else None


def write_stream(owner, data: bytes) -> None:
    """Replace a Form XObject's content. pypdf can only re-encode Flate streams, so any
    other filter (ASCII85, LZW, ...) is swapped for Flate first."""
    if owner.get("/Filter") not in (None, "/FlateDecode", ["/FlateDecode"]):
        owner[NameObject("/Filter")] = NameObject("/FlateDecode")
        owner.pop("/DecodeParms", None)
    owner.set_data(data)


def _raw(string) -> bytes:
    original = getattr(string, "original_bytes", None)
    return original if original is not None else bytes(string)


class _State:
    def __init__(self):
        self.width = self.size = None
        self.tc, self.tw, self.th = 0.0, 0.0, 1.0

    def copy(self):
        clone = _State()
        clone.__dict__.update(self.__dict__)
        return clone

    def apply(self, operands, op, fonts):
        if op == b"Tf":
            self.width, self.size = _bytes_per_glyph(fonts, operands[0]), float(operands[1])
        elif op == b"Tc":
            self.tc = float(operands[0])
        elif op == b"Tw":
            self.tw = float(operands[0])
        elif op == b"Tz":
            self.th = float(operands[0]) / 100
        elif op == b'"':
            self.tw, self.tc = float(operands[0]), float(operands[1])


def _gap(width: float, st) -> FloatObject:
    """A TJ number that moves the pen ``width`` text-space units to the right."""
    return FloatObject(round(-1000 * width / st.size, 3))


def _cut(raw: bytes, st, index, removable, chars):
    """(TJ elements for one string, next glyph index, whether anything was removed)."""
    out, seg, gap, changed = [], b"", 0.0, False
    for j in range(len(raw) // st.width):
        glyph = raw[j * st.width:(j + 1) * st.width]
        if index in removable:
            changed = True
            if seg:
                out.append(ByteStringObject(seg))
                seg = b""
            space = st.tw if st.width == 1 and glyph == b" " else 0.0
            gap += chars[index].adv / st.th + st.tc + space
        else:
            if gap:
                out.append(_gap(gap, st))
                gap = 0.0
            seg += glyph
        index += 1
    if seg:
        out.append(ByteStringObject(seg))
    if gap:
        out.append(_gap(gap, st))
    return out, index, changed


def _rewrite(operands, op, st, start, removable, chars):
    """(replacement operators, index of the next glyph)."""
    elements = operands[0] if op == b"TJ" else [operands[-1]]
    out, index, changed = [], start, False
    for element in elements:
        if not isinstance(element, (str, bytes)):
            out.append(element)
            continue
        cut, index, removed = _cut(_raw(element), st, index, removable, chars)
        out += cut
        changed = changed or removed
    if not changed:
        return [(operands, op)], index
    line = []  # ' and " also move to the next line (and " sets the spacing first)
    if op == b'"':
        line = [([operands[0]], b"Tw"), ([operands[1]], b"Tc")]
    if op in (b"'", b'"'):
        line.append(([], b"T*"))
    return line + [([ArrayObject(out)], b"TJ")], index


def strip(page, stream, removable: set) -> bool:
    """Remove the glyphs ``removable`` (indexes into ``stream.chars``) from the stream
    that draws them. ``False`` when it cannot be matched, leaving it unchanged."""
    if not removable:
        return True
    owner, resources = _container(page, stream.path)
    fonts = resources.get("/Font") if resources is not None else None
    fonts = fonts.get_object() if fonts is not None else None
    content = page.get_contents() if not stream.path else ContentStream(owner, page.pdf)
    if content is None:
        return False
    st, saved, counted, kept = _State(), [], 0, []
    for operands, op in content.operations:
        if op == b"q":
            saved.append(st.copy())
        elif op == b"Q" and saved:
            st = saved.pop()
        st.apply(operands, op, fonts)
        if op not in _SHOWS:
            kept.append((operands, op))
            continue
        if st.width is None or not st.size:
            return False
        replacement, counted = _rewrite(operands, op, st, counted, removable, stream.chars)
        kept.extend(replacement)
    if counted != len(stream.chars):
        return False
    content.operations = kept
    if stream.path:
        write_stream(owner, content.get_data())
    else:
        page.replace_contents(content)
    return True
