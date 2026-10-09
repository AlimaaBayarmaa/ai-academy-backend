"""Template files (course contract / certificate PDFs) read from S3, cached per worker.

Generating a document reads its template every time; caching on ``(key, version)``
means one S3 read per upload. ``version`` is anything that changes when the file
is re-uploaded under the same key (the course's ``updated_at``).
"""
import functools

from . import s3


@functools.lru_cache(maxsize=8)
def read_template(key: str, version) -> bytes:
    """The object's bytes. Raises :class:`~app.storage.S3StorageError` (not cached)."""
    stream, _ = s3.download_stream(key)
    return stream.read()
