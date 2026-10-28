"""
Phase 3C.1 — DocumentIngestionService.

Reads supported knowledge-base source documents, extracts text, and
splits them into overlapping chunks with deterministic, stable chunk
IDs and source metadata attached. Does not touch the vector store
itself (see VectorStoreService) and does not touch run-specific output
artifacts (Business-Analyst-Agent-main/outputs/) — this module only
ever reads from KNOWLEDGE_BASE_DIR.

Supported formats: .txt, .md (read directly, no extra dependency),
.docx (via python-docx, already a dependency of this project), and
.pdf (via pypdf — imported lazily, only when a .pdf file is actually
encountered, so environments without pypdf installed can still ingest
.txt/.md/.docx content).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field


class IngestionError(Exception):
    """Raised for a single document's extraction failure. Callers that
    ingest a whole directory should catch this per-file (see
    DocumentIngestionService.load_directory) rather than letting one
    bad file abort the entire run."""


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source_path: str
    chunk_index: int
    document_hash: str


@dataclass
class LoadResult:
    chunks: list = field(default_factory=list)   # list[Chunk]
    errors: list = field(default_factory=list)   # list[(path, error message)]
    skipped_unsupported: list = field(default_factory=list)  # list[path]


SUPPORTED_EXTENSIONS = (".txt", ".md", ".docx", ".pdf")


def _extract_text_txt_or_md(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise IngestionError(f"{path}: not valid UTF-8 text ({e}).") from e
    except OSError as e:
        raise IngestionError(f"{path}: could not be read ({e}).") from e


def _extract_text_docx(path: str) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise IngestionError(
            f"{path}: python-docx is not installed; cannot extract .docx content."
        ) from e
    try:
        doc = Document(path)
    except Exception as e:
        raise IngestionError(f"{path}: could not be opened as a .docx file ({e}).") from e
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_text_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise IngestionError(
            f"{path}: pypdf is not installed; cannot extract .pdf content. "
            f"Install it (see requirements.txt) or remove this file from the "
            f"knowledge base."
        ) from e
    try:
        reader = PdfReader(path)
    except Exception as e:
        raise IngestionError(f"{path}: could not be opened as a .pdf file ({e}).") from e
    texts = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


def extract_text(path: str) -> str:
    """Dispatches by extension. Raises IngestionError with a clear,
    file-specific message on any failure — never returns a fabricated
    or placeholder text for a file that failed to extract."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md"):
        text = _extract_text_txt_or_md(path)
    elif ext == ".docx":
        text = _extract_text_docx(path)
    elif ext == ".pdf":
        text = _extract_text_pdf(path)
    else:
        raise IngestionError(f"{path}: unsupported extension {ext!r}.")
    if not text or not text.strip():
        raise IngestionError(f"{path}: extracted zero usable text (empty document?).")
    return text


def chunk_text(text: str, chunk_size: int, overlap: int) -> list:
    """
    Deterministic, dependency-free sliding-window character chunker.
    Splits on whitespace-safe boundaries where practical (tries not to
    cut mid-word) while keeping chunk sizes close to chunk_size, with
    `overlap` characters of context repeated between consecutive
    chunks. Pure function: same input always produces the same output,
    which is what the deterministic chunk IDs below depend on.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size.")

    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    length = len(text)
    step = chunk_size - overlap
    while start < length:
        end = min(start + chunk_size, length)
        # Prefer to break on a whitespace boundary near `end`, so chunks
        # don't routinely split a word in half; falls back to a hard cut
        # if no whitespace is nearby.
        if end < length:
            lookback_limit = max(start, end - 50)
            last_space = text.rfind(" ", lookback_limit, end)
            if last_space != -1 and last_space > start:
                end = last_space
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start += step
    return chunks


def compute_document_hash(text: str) -> str:
    """Stable hash of a document's full extracted text — used by
    VectorStoreService to detect whether a source file's content has
    changed since the last ingestion (dedup)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_chunk_id(source_identifier: str, chunk_index: int, chunk_text_value: str) -> str:
    """
    Deterministic chunk ID: depends only on the source's stable
    identifier, its position in that source's chunk sequence, and the
    chunk's own text. Re-ingesting the same unchanged document always
    produces the same IDs, which is what lets VectorStoreService upsert
    (not duplicate) on repeat ingestion.
    """
    digest = hashlib.sha256(
        f"{source_identifier}::{chunk_index}::{chunk_text_value}".encode("utf-8")
    ).hexdigest()
    return f"{os.path.basename(source_identifier)}::{chunk_index}::{digest[:16]}"


class DocumentIngestionService:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load_document(self, path: str) -> LoadResult:
        """Loads and chunks a single file. Raises IngestionError on
        failure (caller decides whether to catch it) — this method does
        not swallow errors itself."""
        text = extract_text(path)
        document_hash = compute_document_hash(text)
        pieces = chunk_text(text, self.chunk_size, self.chunk_overlap)
        chunks = [
            Chunk(
                chunk_id=compute_chunk_id(path, i, piece),
                text=piece,
                source_path=path,
                chunk_index=i,
                document_hash=document_hash,
            )
            for i, piece in enumerate(pieces)
        ]
        return LoadResult(chunks=chunks)

    def load_directory(self, directory: str) -> LoadResult:
        """
        Loads every supported file under `directory` (non-recursive
        subfolders are fine — this walks the whole tree). Per-file
        failures are caught and recorded in LoadResult.errors; one bad
        file never aborts ingestion of the rest, and never corrupts
        anything already persisted (this method only reads from disk
        and builds in-memory Chunk objects — it does not touch the
        vector store).
        """
        result = LoadResult()
        if not os.path.isdir(directory):
            result.errors.append((directory, "knowledge base directory does not exist"))
            return result

        for root, _dirs, files in os.walk(directory):
            for filename in sorted(files):
                path = os.path.join(root, filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    result.skipped_unsupported.append(path)
                    continue
                try:
                    file_result = self.load_document(path)
                    result.chunks.extend(file_result.chunks)
                except IngestionError as e:
                    result.errors.append((path, str(e)))
        return result
