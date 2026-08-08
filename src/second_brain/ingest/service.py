"""Deterministic ingestion service: hash → preserve → parse → index before AI."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from second_brain.config import BrainConfig, load_config
from second_brain.embeddings.local import LocalEmbeddingProvider
from second_brain.exceptions import SecurityViolation, UnsupportedSourceError
from second_brain.ingest.archive import discover_folder_files
from second_brain.ingest.dispatcher import ParserDispatcher
from second_brain.ingest.fingerprint import sha256_file
from second_brain.ingest.fingerprint import source_id as make_source_id
from second_brain.ingest.security import classify_source, ensure_safe_input_path
from second_brain.models import ParsedDocument, ProcessingState, SourceRecord
from second_brain.paths import BrainPaths
from second_brain.storage.markdown import atomic_write
from second_brain.storage.sqlite import SQLiteStore
from second_brain.storage.vector import VectorStore


@dataclass(slots=True)
class IngestResult:
    input_path: Path
    source_id: str | None
    state: ProcessingState
    raw_path: Path | None = None
    extracted_path: Path | None = None
    duplicate_of: str | None = None
    error_type: str | None = None
    message: str = ""


CATEGORY_BY_SUFFIX: dict[str, str] = {
    ".txt": "Documents", ".md": "Documents", ".markdown": "Documents", ".pdf": "Documents",
    ".docx": "Documents", ".pptx": "Documents", ".xlsx": "Documents", ".csv": "Documents",
    ".tsv": "Documents", ".json": "Documents", ".yaml": "Documents", ".yml": "Documents",
    ".eml": "Conversations", ".html": "Websites", ".htm": "Websites",
    ".png": "Images", ".jpg": "Images", ".jpeg": "Images", ".gif": "Images", ".webp": "Images",
    ".bmp": "Images", ".tif": "Images", ".tiff": "Images",
    ".mp3": "Audio", ".wav": "Audio", ".m4a": "Audio", ".flac": "Audio", ".ogg": "Audio",
    ".mp4": "Videos", ".mov": "Videos", ".mkv": "Videos", ".webm": "Videos", ".avi": "Videos",
    ".py": "Code", ".js": "Code", ".jsx": "Code", ".ts": "Code", ".tsx": "Code",
    ".java": "Code", ".c": "Code", ".h": "Code", ".cpp": "Code", ".hpp": "Code",
    ".cs": "Code", ".go": "Code", ".rs": "Code", ".rb": "Code", ".php": "Code",
    ".swift": "Code", ".kt": "Code", ".sql": "Code", ".ps1": "Code", ".sh": "Code",
}


class IngestionService:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        config: BrainConfig | None = None,
        store: SQLiteStore | None = None,
        dispatcher: ParserDispatcher | None = None,
    ) -> None:
        self.paths = paths or BrainPaths.discover()
        self.config = config or load_config(self.paths)
        self.store = store or SQLiteStore(self.paths.db)
        self.dispatcher = dispatcher or ParserDispatcher()
        self.store.initialize()
        self.vectors = VectorStore(
            self.store,
            LocalEmbeddingProvider(self.config.embeddings.dimensions),
        )

    def ingest(self, path: Path | str) -> list[IngestResult]:
        candidate = Path(path).expanduser()
        if not candidate.exists():
            raise FileNotFoundError(candidate)
        if candidate.is_dir():
            results: list[IngestResult] = []
            for child in discover_folder_files(
                candidate, follow_symlinks=self.config.security.follow_symlinks
            ):
                results.append(self.ingest_file(child))
            return results
        return [self.ingest_file(candidate)]

    def ingest_file(self, path: Path) -> IngestResult:
        # Do not resolve symlinks before the security policy has inspected the submitted path.
        path = path.expanduser().absolute()
        job_id = f"JOB-{uuid4()}"
        self.store.create_job(
            job_id=job_id,
            input_path=str(path),
            state=ProcessingState.DETECTED.value,
            stage=ProcessingState.DETECTED.value,
        )
        sid: str | None = None
        raw_path: Path | None = None
        try:
            ensure_safe_input_path(
                path,
                vault=self.paths.vault,
                allow_symlink=self.config.security.follow_symlinks,
            )
            digest = sha256_file(path)
            sid = make_source_id(digest)
            self.store.update_job(
                job_id,
                state=ProcessingState.HASHED.value,
                stage=ProcessingState.HASHED.value,
            )

            existing = self.store.source_by_hash(digest)
            if existing is not None:
                existing_id = str(existing["id"])
                self.store.update_job(
                    job_id,
                    state=ProcessingState.DUPLICATE.value,
                    stage=ProcessingState.DUPLICATE.value,
                    source_id=existing_id,
                    next_action="No action; exact SHA256 already preserved.",
                )
                return IngestResult(
                    path,
                    existing_id,
                    ProcessingState.DUPLICATE,
                    raw_path=Path(str(existing["raw_path"])) if existing["raw_path"] else None,
                    duplicate_of=existing_id,
                    message="Exact SHA256 duplicate; canonical source was not duplicated.",
                )

            classification = classify_source(
                path, scan_secrets=self.config.security.secret_scanning
            )
            raw_path = self._preserve(path, sid, digest)
            now = datetime.now(UTC)
            stat = path.stat()
            source = SourceRecord(
                id=sid,
                source_type=self._source_type(path),
                title=path.stem or path.name,
                original_filename=path.name,
                original_path=str(path),
                content_hash=digest,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_ctime, UTC),
                ingested_at=now,
                status=ProcessingState.PRESERVED,
                authority="unknown",
                sensitivity=classification.sensitivity,
                raw_path=str(raw_path),
            )
            # Canonical raw bytes + manifest/source record are sufficient to recover this source.
            # Clear an Inbox copy before exposing the durable DB row, so observers never mistake a
            # merely-preserved source for an Inbox item that still needs user attention.
            self._write_manifest(source, security_reasons=classification.reasons)
            self._write_source_record(source)
            self._clear_inbox_copy_if_safe(path, raw_path)
            self.store.upsert_source(source, mime_type=mimetypes.guess_type(path.name)[0])
            self.store.update_job(
                job_id,
                state=ProcessingState.PRESERVED.value,
                stage=ProcessingState.PRESERVED.value,
                source_id=sid,
            )

            if not self.dispatcher.supports(path):
                source.status = ProcessingState.UNSUPPORTED
                self.store.upsert_source(source, mime_type=mimetypes.guess_type(path.name)[0])
                self.store.update_job(
                    job_id,
                    state=ProcessingState.UNSUPPORTED.value,
                    stage=ProcessingState.UNSUPPORTED.value,
                    source_id=sid,
                    next_action="Raw source preserved. Add/configure a safe parser to extract content.",
                )
                self._write_manifest(source, security_reasons=classification.reasons)
                self._write_source_record(source, extraction_note="No parser registered; raw bytes preserved.")
                self._clear_inbox_copy_if_safe(path, raw_path)
                return IngestResult(
                    path,
                    sid,
                    ProcessingState.UNSUPPORTED,
                    raw_path=raw_path,
                    message="Raw source preserved but extraction type is unsupported.",
                )

            document = self.dispatcher.parse(raw_path, sid)
            source.status = ProcessingState.EXTRACTED
            extracted_path = self._write_extraction(document)
            source.extracted_path = str(extracted_path)
            self.store.upsert_source(source, mime_type=document.mime_type)
            self.store.replace_segments(document)
            for segment in document.segments:
                self.vectors.upsert(
                    object_id=segment.segment_id,
                    object_type="source-segment",
                    title=document.title,
                    text=segment.text,
                    source_id=sid,
                    metadata={
                        "locator": segment.locator,
                        "position": segment.position,
                    },
                )
            self.store.update_job(
                job_id,
                state=ProcessingState.INDEXED.value,
                stage=ProcessingState.INDEXED.value,
                source_id=sid,
            )

            # AI compilation is a later, optional stage. Deterministic ingestion remains useful
            # and lossless when no provider is configured.
            final_state = (
                ProcessingState.NEEDS_AI
                if self.config.ai.provider.lower() in {"", "none"}
                else ProcessingState.CLASSIFIED
            )
            source.status = final_state
            self.store.upsert_source(source, mime_type=document.mime_type)
            self.store.update_job(
                job_id,
                state=final_state.value,
                stage=final_state.value,
                source_id=sid,
                next_action=(
                    "Configure/enable an AI provider to compile knowledge."
                    if final_state == ProcessingState.NEEDS_AI
                    else "Ready for structured AI compilation."
                ),
            )
            extraction_note = self._extraction_note(document)
            self._write_manifest(
                source,
                security_reasons=classification.reasons,
                document=document,
            )
            self._write_source_record(source, extraction_note=extraction_note)
            self._clear_inbox_copy_if_safe(path, raw_path)
            return IngestResult(
                path,
                sid,
                final_state,
                raw_path=raw_path,
                extracted_path=extracted_path,
                message="Preserved, extracted and indexed deterministically.",
            )
        except (SecurityViolation, UnsupportedSourceError) as exc:
            if sid is not None and self.store.source_by_id(sid) is not None:
                self.store.update_source_status(sid, ProcessingState.QUARANTINED.value)
            self.store.update_job(
                job_id,
                state=ProcessingState.QUARANTINED.value,
                stage=ProcessingState.QUARANTINED.value,
                source_id=sid,
                error_type=type(exc).__name__,
                error_message=str(exc),
                next_action="Review security condition before retrying.",
            )
            return IngestResult(
                path,
                sid,
                ProcessingState.QUARANTINED,
                raw_path=raw_path,
                error_type=type(exc).__name__,
                message=str(exc),
            )
        except Exception as exc:
            # The error message is intentionally not decorated with file contents/secrets.
            if sid is not None and self.store.source_by_id(sid) is not None:
                self.store.update_source_status(sid, ProcessingState.FAILED.value)
            self.store.update_job(
                job_id,
                state=ProcessingState.FAILED.value,
                stage=ProcessingState.FAILED.value,
                source_id=sid,
                error_type=type(exc).__name__,
                error_message=str(exc),
                next_action="Inspect parser/filesystem health and retry; preserved raw data is retained when available.",
            )
            return IngestResult(
                path,
                sid,
                ProcessingState.FAILED,
                raw_path=raw_path,
                error_type=type(exc).__name__,
                message=str(exc),
            )

    def _preserve(self, source: Path, sid: str, digest: str) -> Path:
        category = CATEGORY_BY_SUFFIX.get(source.suffix.lower(), "Other")
        target_dir = self.paths.raw / category / sid
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if target.exists():
            if sha256_file(target) != digest:
                raise RuntimeError(f"Canonical raw path collision/hash mismatch for {sid}")
            return target
        temp = target_dir / f".{source.name}.{uuid4().hex}.tmp"
        try:
            with source.open("rb") as src, temp.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            if sha256_file(temp) != digest:
                raise RuntimeError("Preserved copy SHA256 does not match input")
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)
        if sha256_file(target) != digest:
            raise RuntimeError("Canonical raw SHA256 verification failed after atomic replace")
        return target

    def _write_extraction(self, document: ParsedDocument) -> Path:
        json_path = self.paths.extracted / f"{document.source_id}.json"
        text_path = self.paths.extracted / f"{document.source_id}.txt"
        atomic_write(
            json_path,
            json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write(text_path, document.text + ("\n" if document.text else ""))
        return json_path

    def _write_manifest(
        self,
        source: SourceRecord,
        *,
        security_reasons: tuple[str, ...],
        document: ParsedDocument | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "source": source.model_dump(mode="json"),
            "security_reasons": list(security_reasons),
            "parser": document.mime_type if document else None,
            "segments": len(document.segments) if document else 0,
            "written_at": datetime.now(UTC).isoformat(),
        }
        atomic_write(
            self.paths.manifests / f"{source.id}.json",
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )

    def _write_source_record(self, source: SourceRecord, *, extraction_note: str = "") -> None:
        metadata = {
            "id": source.id,
            "type": "source",
            "source_type": source.source_type,
            "title": source.title,
            "original_filename": source.original_filename,
            "original_path": source.original_path,
            "content_hash": source.content_hash,
            "size_bytes": source.size_bytes,
            "created_at": source.created_at.isoformat() if source.created_at else None,
            "ingested_at": source.ingested_at.isoformat(),
            "status": source.status.value,
            "authority": source.authority,
            "sensitivity": source.sensitivity.value,
            "project_ids": source.project_ids,
            "topics": source.topics,
        }
        yaml_text = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
        body = (
            f"---\n{yaml_text}\n---\n\n# {source.title}\n\n"
            "## Summary\n\n_Compiled summary pending._\n\n"
            "## Important Information\n\n_Compiled information pending._\n\n"
            "## Extracted Claims\n\n_None compiled yet._\n\n"
            "## Entities\n\n_None compiled yet._\n\n"
            "## Relevant Projects\n\n_None compiled yet._\n\n"
            "## Derived Knowledge\n\n_None compiled yet._\n\n"
            "## Contradictions\n\n_None detected yet._\n\n"
            f"## Extraction Notes\n\n{extraction_note or 'Deterministic preservation complete.'}\n\n"
            f"## Source Locator\n\n`{source.raw_path}`\n"
        )
        atomic_write(self.paths.records / f"{source.id}.md", body)
        self.store.index_text(
            object_id=source.id,
            object_type="source-record",
            title=source.title,
            text=body,
            source_id=source.id,
            locator="source record",
        )

    @staticmethod
    def _source_type(path: Path) -> str:
        category = CATEGORY_BY_SUFFIX.get(path.suffix.lower(), "Other")
        return category.lower().rstrip("s") or "other"

    @staticmethod
    def _extraction_note(document: ParsedDocument) -> str:
        if bool(document.metadata.get("requires_ocr")):
            return "PDF appears to contain no extractable text. Raw source preserved; OCR/vision is required but was not run."
        if bool(document.metadata.get("requires_transcription")):
            return "Raw media preserved. Transcription is optional and not configured; only deterministic metadata was extracted."
        if bool(document.metadata.get("requires_vision_for_description")):
            return "Raw image preserved. Vision description is optional and was not run; only deterministic image metadata was extracted."
        return f"Deterministic extraction produced {len(document.segments)} segment(s) with source locators."

    def _clear_inbox_copy_if_safe(self, original: Path, raw_path: Path) -> None:
        try:
            original_resolved = original.resolve()
            inbox_resolved = self.paths.inbox.resolve()
            raw_resolved = raw_path.resolve()
            if (
                original_resolved != raw_resolved
                and inbox_resolved in original_resolved.parents
                and raw_resolved.exists()
            ):
                original.unlink(missing_ok=True)
        except OSError:
            # Cleanup failure must not invalidate already verified preservation.
            return
