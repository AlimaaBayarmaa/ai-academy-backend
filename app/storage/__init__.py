"""Object storage (S3) for uploaded files (cert / contract templates)."""
from .s3 import (
    S3StorageError,
    build_key,
    delete_object,
    download_stream,
    presigned_url,
    upload_fileobj,
)
from .templates import read_template

__all__ = [
    "S3StorageError",
    "build_key",
    "delete_object",
    "download_stream",
    "presigned_url",
    "read_template",
    "upload_fileobj",
]
