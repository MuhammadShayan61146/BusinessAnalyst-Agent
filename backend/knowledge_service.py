"""
KnowledgeService: safely add documents to the RAG knowledge base.

Safety rules
  * Only .txt .md .docx .pdf files, up to a size limit.
  * The client's filename is NEVER used as a path. It is reduced to a safe
    name (letters, digits, '.', '_', '-') and always saved inside the
    knowledge base's own "uploads" folder.
  * The file is test-extracted first; an unreadable or empty file is
    rejected before anything is stored.
  * If ingestion fails, the saved file is rolled back (restored to its
    previous content, or removed), so the vector store and the folder never
    disagree.
  * One upload is processed at a time (lock), so two simultaneous uploads
    cannot corrupt the store's manifest.
  * Responses only ever contain RELATIVE source names, never server paths.

No FastAPI import.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time

from services.document_ingestion_service import (
    DocumentIngestionService, IngestionError, SUPPORTED_EXTENSIONS, extract_text,
)

UPLOAD_SUBDIR = "uploads"


class KnowledgeError(Exception):
    """Rejected upload (bad type, too large, unreadable, ingestion failure)."""


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(raw_name: str) -> str:
    """Reduce an untrusted filename to a safe one (keeps only the extension
    if it is allowed). Raises KnowledgeError for unsupported types."""
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise KnowledgeError("A filename is required.")
    base = raw_name.replace("\\", "/").split("/")[-1]  # drop any directory part
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise KnowledgeError("Unsupported file type. Allowed: " + ", ".join(SUPPORTED_EXTENSIONS) + ".")
    stem = _SAFE_CHARS.sub("-", stem).strip("-.")[:80] or "document"
    return stem + ext


class KnowledgeService:
    def __init__(self, kb_dir: str, store_factory, chunk_size: int, chunk_overlap: int,
                 max_bytes: int = 5 * 1024 * 1024):
        self._kb_dir = kb_dir
        self._store_factory = store_factory
        self._ingestion = DocumentIngestionService(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()

    @property
    def _upload_dir(self) -> str:
        return os.path.join(self._kb_dir, UPLOAD_SUBDIR)

    def add_document(self, filename: str, data: bytes) -> dict:
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise KnowledgeError("The file is empty.")
        if len(data) > self._max_bytes:
            raise KnowledgeError(f"The file is larger than the {self._max_bytes // (1024 * 1024)} MB limit.")
        name = safe_filename(filename)

        with self._lock:
            os.makedirs(self._upload_dir, exist_ok=True)
            final_path = os.path.join(self._upload_dir, name)

            # 1. Test-extract from a temporary file so a bad document is rejected
            #    before it can replace anything.
            ext = os.path.splitext(name)[1]
            fd, tmp_path = tempfile.mkstemp(suffix=ext, dir=self._upload_dir)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                try:
                    extract_text(tmp_path)
                except IngestionError as e:
                    raise KnowledgeError("The document could not be read: it may be empty, "
                                         "corrupted or password-protected.") from e
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            # 2. Save, ingest, and roll back on any failure.
            previous = None
            if os.path.exists(final_path):
                with open(final_path, "rb") as f:
                    previous = f.read()
            with open(final_path, "wb") as f:
                f.write(data)
            try:
                chunks = self._ingestion.load_document(final_path, base_dir=self._kb_dir).chunks
                summary = self._store_factory().add_chunks(chunks)
            except Exception as e:
                if previous is None:
                    os.remove(final_path)
                else:
                    with open(final_path, "wb") as f:
                        f.write(previous)
                raise KnowledgeError(f"Ingestion failed and the upload was rolled back: {e}") from e

            source = f"{UPLOAD_SUBDIR}/{name}"
            status = ("added" if source in summary.get("added_sources", []) else
                      "updated" if source in summary.get("updated_sources", []) else "unchanged")
            return {"source": source, "chunks": len(chunks), "status": status,
                    "sha256": hashlib.sha256(data).hexdigest()[:16]}

    def list_documents(self) -> list:
        docs = []
        if not os.path.isdir(self._kb_dir):
            return docs
        for root, _dirs, files in os.walk(self._kb_dir):
            for fn in sorted(files):
                if os.path.splitext(fn)[1].lower() not in SUPPORTED_EXTENSIONS:
                    continue
                full = os.path.join(root, fn)
                docs.append({
                    "source": os.path.relpath(full, self._kb_dir).replace(os.sep, "/"),
                    "size_bytes": os.path.getsize(full),
                    "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(full))),
                })
        return docs
