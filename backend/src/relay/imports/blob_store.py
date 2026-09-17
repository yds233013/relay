"""Content-addressed local file storage (SEC-02, SEC-06, SEC-07).

Files are stored under their SHA-256 (``ab/cd/<sha256>``). User-supplied filenames never reach a
path. Reads verify the hash, so a modified blob is detected rather than silently used.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, Protocol

from relay.core.errors import RelayError

_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_CHUNK: Final = 1024 * 1024


class UploadTooLargeError(RelayError):
    code: ClassVar[str] = "import.too_large"
    title: ClassVar[str] = "Upload exceeds the size limit"
    http_status: ClassVar[int] = 413


class BlobIntegrityError(RelayError):
    code: ClassVar[str] = "storage.integrity_failure"
    title: ClassVar[str] = "Stored file does not match its hash"
    http_status: ClassVar[int] = 500


@dataclass(frozen=True, slots=True)
class SpooledUpload:
    path: Path
    sha256: str
    size_bytes: int
    head: bytes
    """The first bytes of the file, for content sniffing."""


class BlobStore(Protocol):
    def spool(self, chunks: Iterable[bytes], max_bytes: int) -> SpooledUpload: ...

    def put(self, upload: SpooledUpload) -> str: ...

    def read(self, storage_key: str, sha256: str) -> bytes: ...

    def exists(self, storage_key: str) -> bool: ...

    def discard(self, upload: SpooledUpload) -> None: ...


def _check_size(size: int, max_bytes: int) -> None:
    if size > max_bytes:
        raise UploadTooLargeError(f"uploads are limited to {max_bytes} bytes")


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.tmp = root / "tmp"

    def _ensure_dirs(self) -> None:
        self.tmp.mkdir(parents=True, exist_ok=True, mode=0o700)

    def spool(self, chunks: Iterable[bytes], max_bytes: int) -> SpooledUpload:
        """Stream to a private temporary file, hashing and enforcing the size limit on the way."""
        self._ensure_dirs()
        descriptor, name = tempfile.mkstemp(dir=self.tmp, prefix="upload-")
        path = Path(name)
        digest = hashlib.sha256()
        size = 0
        head = b""
        try:
            with os.fdopen(descriptor, "wb") as handle:
                for chunk in chunks:
                    size += len(chunk)
                    _check_size(size, max_bytes)
                    if len(head) < 8192:
                        head += chunk[: 8192 - len(head)]
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return SpooledUpload(path=path, sha256=digest.hexdigest(), size_bytes=size, head=head)

    def _key(self, sha256: str) -> str:
        if not _SHA256.fullmatch(sha256):
            raise ValueError("invalid sha256")
        return f"{sha256[:2]}/{sha256[2:4]}/{sha256}"

    def put(self, upload: SpooledUpload) -> str:
        key = self._key(upload.sha256)
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            upload.path.unlink(missing_ok=True)
        else:
            os.replace(upload.path, destination)
        return key

    def read(self, storage_key: str, sha256: str) -> bytes:
        if storage_key != self._key(sha256):
            raise BlobIntegrityError("storage key does not match the file hash")
        path = self.root / storage_key
        if not path.is_file():
            raise BlobIntegrityError("stored file is missing")
        digest = hashlib.sha256()
        data = bytearray()
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
                data.extend(chunk)
        if digest.hexdigest() != sha256:
            raise BlobIntegrityError("stored file content changed")
        return bytes(data)

    def exists(self, storage_key: str) -> bool:
        return (self.root / storage_key).is_file()

    def discard(self, upload: SpooledUpload) -> None:
        upload.path.unlink(missing_ok=True)
