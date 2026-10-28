#!/usr/bin/env python3
"""
Phase 3C.1 — standalone knowledge-base ingestion entry point.

Run independently of the interactive agent:

    cd Business-Analyst-Agent-main
    python3 scripts/ingest_knowledge_base.py

Reads every supported file under config.settings.KNOWLEDGE_BASE_DIR
(default: Business-Analyst-Agent-main/knowledge_base/), chunks it, and
persists embeddings + metadata into config.settings.VECTOR_STORE_DIR
(default: Business-Analyst-Agent-main/vector_store/) via
VectorStoreService. Safe to re-run: unchanged source documents are
skipped (see VectorStoreService.add_chunks' manifest-based dedup).

Requires GEMINI_API_KEY (or GOOGLE_API_KEY) to be set, since embedding
generation calls the real Gemini embeddings API — this script makes a
live API call and is not part of the offline test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import KNOWLEDGE_BASE_DIR, VECTOR_STORE_DIR, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP
from services.document_ingestion_service import DocumentIngestionService


def main():
    print(f"Ingesting knowledge base from: {KNOWLEDGE_BASE_DIR}")
    print(f"Persisting vector store to:    {VECTOR_STORE_DIR}")
    print(f"Chunk size / overlap:          {RAG_CHUNK_SIZE} / {RAG_CHUNK_OVERLAP}")

    ingestion = DocumentIngestionService(chunk_size=RAG_CHUNK_SIZE, chunk_overlap=RAG_CHUNK_OVERLAP)
    result = ingestion.load_directory(KNOWLEDGE_BASE_DIR)

    if result.errors:
        print("\nFiles that FAILED to ingest (skipped, not fatal to the rest):")
        for path, message in result.errors:
            print(f"  - {path}: {message}")

    if result.skipped_unsupported:
        print(f"\nSkipped {len(result.skipped_unsupported)} file(s) with unsupported extensions.")

    if not result.chunks:
        print("\nNo chunks extracted — nothing to persist. "
              "Add .txt/.md/.docx/.pdf files to the knowledge base directory above.")
        return 1

    print(f"\nExtracted {len(result.chunks)} chunk(s) from "
          f"{len({c.source_path for c in result.chunks})} source document(s).")

    try:
        from services.vector_store_service import VectorStoreService
    except ImportError as e:
        print(f"\nCould not import VectorStoreService's real dependencies: {e}")
        print("Install langchain-chroma, chromadb, and langchain-google-genai (see requirements.txt).")
        return 1

    try:
        store = VectorStoreService(persist_directory=VECTOR_STORE_DIR)
    except Exception as e:
        print(f"\nCould not initialize the vector store (check GEMINI_API_KEY): {e}")
        return 1

    summary = store.add_chunks(result.chunks)
    print("\nIngestion summary:")
    print(f"  Added (new) sources:            {len(summary['added_sources'])}")
    print(f"  Updated (changed) sources:      {len(summary['updated_sources'])}")
    print(f"  Skipped (unchanged) sources:    {len(summary['skipped_unchanged_sources'])}")
    print(f"  Total chunks now in store:      {store.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
