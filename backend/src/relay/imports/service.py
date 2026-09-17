"""Imports: upload (streamed, limited, sniffed, idempotent), parse, profile and activation.

Upload stores the file and queues parsing. Parsing writes immutable source and quarantined rows,
then activates the import for its dataset (superseding the previous one). Every state change writes
an audit event in the same transaction.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Final

from psycopg.types.json import Jsonb
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.core.actor import Actor
from relay.core.clock import Clock, SystemClock
from relay.core.db import copy_rows
from relay.core.errors import RelayError
from relay.core.hashing import fingerprint
from relay.core.ids import uuid7
from relay.imports.blob_store import BlobStore
from relay.imports.models import (
    DatasetProfile,
    Import,
    ImportStatus,
    QuarantinedRow,
    SourceRow,
    StoredFile,
)
from relay.ingestion.csv_reader import SourceFileError, read_csv
from relay.jobs import service as jobs
from relay.jobs.models import JobKind
from relay.profiling.domain import PROFILER_VERSION, profile_rows
from relay.workspace.models import Dataset

ALLOWED_EXTENSIONS: Final = frozenset({".csv", ".txt"})
_BINARY_SIGNATURES: Final = (
    b"PK\x03\x04",  # zip, xlsx
    b"%PDF",
    b"\x1f\x8b",  # gzip
    b"\xd0\xcf\x11\xe0",  # legacy Office
    b"\x7fELF",
    b"MZ",
)
_DELIMITERS: Final = (",", ";", "\t", "|")


class UnsupportedContentError(RelayError):
    code: ClassVar[str] = "import.unsupported_content"
    title: ClassVar[str] = "File type is not supported"
    http_status: ClassVar[int] = 415


class InvalidFilenameError(RelayError):
    code: ClassVar[str] = "import.invalid_filename"
    title: ClassVar[str] = "Invalid file name"
    http_status: ClassVar[int] = 422


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    import_: Import
    created: bool


@dataclass(frozen=True, slots=True)
class ImportLimits:
    max_upload_bytes: int
    max_rows: int


def sanitize_filename(raw: str) -> str:
    """Display-only name: last path component, no control characters, bounded length (SEC-02)."""
    name = re.split(r"[\\/]", raw)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    name = name.lstrip(".")
    if not name:
        raise InvalidFilenameError("file name is empty")
    return name[:255]


def _check_content(filename: str, head: bytes) -> None:
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedContentError("only .csv and .txt files are accepted")
    if any(head.startswith(signature) for signature in _BINARY_SIGNATURES) or b"\x00" in head:
        raise UnsupportedContentError("file content is not delimited text")


def upload(
    session: Session,
    *,
    actor: Actor,
    dataset: Dataset,
    filename: str,
    chunks: Iterable[bytes],
    blob_store: BlobStore,
    limits: ImportLimits,
    clock: Clock | None = None,
) -> UploadOutcome:
    display_name = sanitize_filename(filename)
    spooled = blob_store.spool(chunks, limits.max_upload_bytes)
    try:
        _check_content(display_name, spooled.head)
        if spooled.size_bytes == 0:
            raise UnsupportedContentError("file is empty")
        stored = session.scalars(
            select(StoredFile).where(StoredFile.sha256 == spooled.sha256)
        ).first()
        if stored is not None and not blob_store.exists(stored.storage_key):
            # The row outlived its blob (for example a different storage volume). The upload's
            # bytes hash to the same value, so storing them restores the file exactly.
            restored_key = blob_store.put(spooled)
            if restored_key != stored.storage_key:
                raise UnsupportedContentError("stored file key does not match its content hash")
        if stored is not None:
            existing = session.scalars(
                select(Import).where(
                    Import.dataset_id == dataset.id, Import.stored_file_id == stored.id
                )
            ).first()
            if existing is not None:
                blob_store.discard(spooled)
                audit.record(
                    session,
                    actor=actor,
                    action="import.duplicate_upload_ignored",
                    entity_type="import",
                    entity_id=existing.id,
                    migration_id=dataset.migration_id,
                    after={"sha256": spooled.sha256, "sequence": existing.sequence},
                    clock=clock,
                )
                return UploadOutcome(existing, created=False)
        else:
            storage_key = blob_store.put(spooled)
            stored = StoredFile(
                id=uuid7(clock),
                sha256=spooled.sha256,
                size_bytes=spooled.size_bytes,
                media_type="text/csv",
                storage_key=storage_key,
                first_uploaded_by=actor.user_id,
            )
            session.add(stored)
            session.flush()
    finally:
        blob_store.discard(spooled)
    sequence = (
        session.scalar(select(func.max(Import.sequence)).where(Import.dataset_id == dataset.id))
        or 0
    ) + 1
    record = Import(
        id=uuid7(clock),
        dataset_id=dataset.id,
        stored_file_id=stored.id,
        sequence=sequence,
        original_filename=display_name,
        status=ImportStatus.PENDING.value,
        created_by=actor.user_id,
    )
    session.add(record)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="import.uploaded",
        entity_type="import",
        entity_id=record.id,
        migration_id=dataset.migration_id,
        after={
            "dataset_id": dataset.id,
            "sequence": sequence,
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "filename": display_name,
        },
        clock=clock,
    )
    jobs.enqueue(
        session,
        JobKind.PARSE_IMPORT,
        {"import_id": str(record.id)},
        dedupe_key=f"parse_import:{record.id}",
        clock=clock,
    )
    return UploadOutcome(record, created=True)


def mark_failed(
    session: Session, *, import_id: uuid.UUID, error: dict[str, str], clock: Clock | None = None
) -> None:
    """Record a parse job that failed permanently, so the import never stays pending."""
    record = session.get(Import, import_id, with_for_update=True)
    if record is None or record.status not in {
        ImportStatus.PENDING.value,
        ImportStatus.PARSING.value,
    }:
        return
    dataset = session.get(Dataset, record.dataset_id)
    record.status = ImportStatus.FAILED.value
    record.error = dict(error)
    record.completed_at = (clock or SystemClock()).now()
    session.flush()
    audit.record(
        session,
        actor=Actor.system(),
        action="import.failed",
        entity_type="import",
        entity_id=record.id,
        migration_id=dataset.migration_id if dataset else None,
        after={"error": record.error},
        clock=clock,
    )


def sniff_encoding(content: bytes) -> str:
    """BOM → utf-8-sig; valid UTF-8 → utf-8; otherwise Windows-1252 (recorded on the import)."""
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8"


def sniff_delimiter(first_line: str) -> str:
    counts = {delimiter: first_line.count(delimiter) for delimiter in _DELIMITERS}
    best = max(counts.values())
    return "," if best == 0 else next(d for d in _DELIMITERS if counts[d] == best)


def _check_row_limit(rows: int, max_rows: int) -> None:
    if rows > max_rows:
        raise SourceFileError(f"file has more than {max_rows} rows")


def _row_hash(values: dict[str, str]) -> str:
    return fingerprint(values)


def parse(
    session: Session,
    *,
    import_id: uuid.UUID,
    blob_store: BlobStore,
    limits: ImportLimits,
    clock: Clock | None = None,
) -> Import:
    """Idempotent: an import that is already parsed or failed is returned unchanged."""
    record = session.get(Import, import_id, with_for_update=True)
    if record is None:
        raise RelayError(f"import {import_id} does not exist")
    if record.status not in {ImportStatus.PENDING.value, ImportStatus.PARSING.value}:
        return record
    dataset = session.get(Dataset, record.dataset_id, with_for_update=True)
    stored = session.get(StoredFile, record.stored_file_id)
    if dataset is None or stored is None:
        raise RelayError("import references a missing dataset or file")
    system = Actor.system()
    now = (clock or SystemClock()).now()
    record.status = ImportStatus.PARSING.value
    record.started_at = now
    content = blob_store.read(stored.storage_key, stored.sha256)
    encoding = sniff_encoding(content)
    try:
        text = content.decode(encoding)
        delimiter = sniff_delimiter(text.split("\n", 1)[0])
        table = read_csv(record.original_filename, content, encoding=encoding, delimiter=delimiter)
        _check_row_limit(len(table.rows), limits.max_rows)
    except (SourceFileError, UnicodeDecodeError) as exc:
        detail = exc.detail if isinstance(exc, SourceFileError) else "file cannot be decoded"
        record.status = ImportStatus.FAILED.value
        record.error = {"code": "import.unreadable", "detail": detail}
        record.encoding = encoding
        record.completed_at = (clock or SystemClock()).now()
        audit.record(
            session,
            actor=system,
            action="import.failed",
            entity_type="import",
            entity_id=record.id,
            migration_id=dataset.migration_id,
            after={"error": record.error},
            clock=clock,
        )
        return record

    copy_rows(
        session,
        SourceRow.__tablename__,
        ("id", "import_id", "row_number", "line_start", "line_end", "values", "row_hash"),
        (
            (
                uuid7(clock),
                record.id,
                row.row_number,
                row.line_start,
                row.line_end,
                Jsonb(row.values),
                _row_hash(row.values),
            )
            for row in table.rows
        ),
    )
    quarantined = [
        {
            "id": uuid7(clock),
            "import_id": record.id,
            "quarantine_key": row.key,
            "line_start": row.line_start,
            "line_end": row.line_end,
            "raw_text": row.raw_text,
            "reason": row.reason,
            "field_counts": list(row.field_counts),
        }
        for row in table.quarantined
    ]
    if quarantined:
        session.execute(insert(QuarantinedRow), quarantined)
    record.status = ImportStatus.PARSED.value
    record.encoding = encoding
    record.delimiter = delimiter
    record.header = list(table.header)
    record.row_count = len(table.rows)
    record.quarantined_count = len(table.quarantined)
    record.completed_at = (clock or SystemClock()).now()
    session.flush()
    audit.record(
        session,
        actor=system,
        action="import.parsed",
        entity_type="import",
        entity_id=record.id,
        migration_id=dataset.migration_id,
        after={
            "row_count": record.row_count,
            "quarantined_count": record.quarantined_count,
            "encoding": encoding,
            "delimiter": delimiter,
        },
        clock=clock,
    )
    _activate(session, dataset, record, clock)
    profile = profile_rows(table.header, (row.values for row in table.rows), len(table.quarantined))
    session.add(
        DatasetProfile(
            id=uuid7(clock),
            import_id=record.id,
            profiler_version=PROFILER_VERSION,
            profile=profile.model_dump(mode="json"),
        )
    )
    session.flush()
    return record


def _activate(session: Session, dataset: Dataset, record: Import, clock: Clock | None) -> None:
    previous_id = dataset.active_import_id
    if previous_id is not None and previous_id != record.id:
        previous = session.get(Import, previous_id, with_for_update=True)
        if previous is not None and previous.status == ImportStatus.PARSED.value:
            previous.status = ImportStatus.SUPERSEDED.value
            audit.record(
                session,
                actor=Actor.system(),
                action="import.superseded",
                entity_type="import",
                entity_id=previous.id,
                migration_id=dataset.migration_id,
                before={"status": ImportStatus.PARSED.value},
                after={"status": ImportStatus.SUPERSEDED.value, "superseded_by": record.id},
                clock=clock,
            )
    dataset.active_import_id = record.id
    dataset.version += 1
    dataset.updated_at = (clock or SystemClock()).now()
    session.flush()
    audit.record(
        session,
        actor=Actor.system(),
        action="import.activated",
        entity_type="dataset",
        entity_id=dataset.id,
        migration_id=dataset.migration_id,
        before={"active_import_id": previous_id},
        after={"active_import_id": record.id, "sequence": record.sequence},
        clock=clock,
    )
