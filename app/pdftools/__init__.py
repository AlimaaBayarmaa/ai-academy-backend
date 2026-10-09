"""PDF template helpers shared by contracts and certificates (permissive licences only).

- ``glyphs`` : pdfminer.six — where each placeholder is, per content stream
- ``strip``  : pypdf — delete placeholder glyphs without shifting the rest of the line
- ``page``   : remove the hits from a page, stamp a reportlab overlay on it
"""
from .glyphs import Hit, Stream, find, read_pages, streams, union
from .page import remove, stamp
from .strip import strip

__all__ = ["Hit", "Stream", "find", "read_pages", "remove", "stamp", "streams", "strip",
           "union"]
