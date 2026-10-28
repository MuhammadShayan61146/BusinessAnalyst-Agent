"""
Phase 3C.1 — VectorStoreService.

Wraps a persistent vector store (langchain_chroma.Chroma by default) with:
  - whole-document dedup via a small JSON manifest (source_path ->
    {document_hash, chunk_ids}), so repeat ingestion of an unchanged
    source file performs zero embedding calls and zero store writes;
  - deterministic per-chunk IDs (from document_ingestion_service) as
    the store's own ids, so even without the manifest, re-adding the
    same chunk content upserts rather than duplicates;
  - a documented, minimal interface (add_texts/delete/
    similarity_search_with_relevance_scores) matching LangChain's
    standard VectorStore surface, so a real langchain_chroma.Chroma
    instance or a test fake can be injected interchangeably via the
    `vectorstore=` constructor argument.

The manifest and the vector store's own persistence are both scoped to
VECTOR_STORE_DIR (config/settings.py) — never OUTPUT_DIR/runs/, keeping
vector-store internals separate from run-specific generated artifacts.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def read_manifest_chunk_count(persist_directory: str) -> int:
    """
    Lightweight, dependency-free check of how many chunks are recorded
    in a vector store's manifest, WITHOUT constructing a full
    VectorStoreService (which requires embedding credentials). Used by
    the backend's health endpoint, which must report readiness without
    claiming the store is operational merely because a directory
    exists (returns 0 for a missing/empty/unreadable manifest, never
    raises).
    """
    manifest_path = os.path.join(persist_directory, "ingested_manifest.json")
    if not os.path.exists(manifest_path):
        return 0
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(len(v.get("chunk_ids", [])) for v in manifest.values())


@dataclass
class RetrievedChunk:
    text: str
    source: str
    chunk_id: str
    score: float
    metadata: dict = field(default_factory=dict)


class VectorStoreService:
    def __init__(self, persist_directory, collection_name="knowledge_base",
                 embedding_service=None, vectorstore=None):
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
        self.manifest_path = os.path.join(persist_directory, "ingested_manifest.json")
        self.embedding_service = embedding_service

        if vectorstore is not None:
            # Test/alternative-backend injection point.
            self._store = vectorstore
        else:
            self._store = self._build_real_chroma_store(collection_name)

    def _build_real_chroma_store(self, collection_name):
        if self.embedding_service is None:
            # Imported lazily: constructing a GeminiEmbeddingService
            # requires GEMINI_API_KEY, which not every environment this
            # service is loaded into will have set (e.g. unit tests that
            # never call this path at all).
            from services.embedding_service import GeminiEmbeddingService
            self.embedding_service = GeminiEmbeddingService()
        # Imported lazily: langchain_chroma/chromadb are not guaranteed
        # to be installed in every environment this repo is checked out
        # into (see PHASE_3C_1_DELIVERY.md). Every other method on this
        # class works fine without them as long as a `vectorstore=` was
        # injected instead (as the test suite does).
        from langchain_chroma import Chroma
        return Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding_service.langchain_embeddings,
            persist_directory=self.persist_directory,
        )

    def _load_manifest(self) -> dict:
        if os.path.exists(self.manifest_path):
            with open(self.manifest_path) as f:
                return json.load(f)
        return {}

    def _save_manifest(self, manifest: dict) -> None:
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

    def add_chunks(self, chunks: list) -> dict:
        """
        chunks: list[document_ingestion_service.Chunk].

        Groups chunks by source_path. For each source: if the manifest
        already has that source at the same document_hash, skips it
        entirely (item 7 of the ingestion requirements: repeatable
        ingestion without uncontrolled duplicate accumulation, with zero
        embedding calls on an unchanged document). Otherwise, deletes
        any previously-stored chunk ids for that source (if the source
        changed) and adds the new chunks, then updates the manifest.

        Returns a summary dict — never raises on a per-source basis
        beyond what the underlying store itself raises (a hard store
        failure for one source does not corrupt the manifest for
        others, since the manifest is only saved once, at the end, from
        the in-memory dict being built up here).
        """
        manifest = self._load_manifest()
        by_source: dict = {}
        for c in chunks:
            by_source.setdefault(c.source_path, []).append(c)

        summary = {"added_sources": [], "updated_sources": [], "skipped_unchanged_sources": []}
        for source_path, source_chunks in by_source.items():
            doc_hash = source_chunks[0].document_hash
            prior = manifest.get(source_path)
            if prior and prior.get("document_hash") == doc_hash:
                summary["skipped_unchanged_sources"].append(source_path)
                continue

            if prior and prior.get("chunk_ids"):
                self._store.delete(ids=prior["chunk_ids"])
                summary["updated_sources"].append(source_path)
            else:
                summary["added_sources"].append(source_path)

            ids = [c.chunk_id for c in source_chunks]
            texts = [c.text for c in source_chunks]
            metadatas = [
                {"source": c.source_path, "chunk_index": c.chunk_index, "chunk_id": c.chunk_id}
                for c in source_chunks
            ]
            self._store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
            manifest[source_path] = {"document_hash": doc_hash, "chunk_ids": ids}

        self._save_manifest(manifest)
        return summary

    def count(self) -> int:
        """Chunk count, derived from the manifest (authoritative record
        of what this service believes it has stored) rather than a
        backend-specific count call, so this works identically
        regardless of which vectorstore backend is injected."""
        return read_manifest_chunk_count(self.persist_directory)

    def similarity_search(self, query: str, k: int, threshold: float) -> list:
        """
        Returns [] cleanly for an empty/uninitialized store (checked via
        count() before ever calling the backend) — never raises or
        fabricates a result for a knowledge base that hasn't been
        ingested yet. Chunks scoring below `threshold` are filtered out.
        """
        if self.count() == 0:
            return []
        results = self._store.similarity_search_with_relevance_scores(query, k=k)
        out = []
        for doc, score in results:
            if score < threshold:
                continue
            out.append(RetrievedChunk(
                text=doc.page_content,
                source=doc.metadata.get("source", "unknown"),
                chunk_id=doc.metadata.get("chunk_id", ""),
                score=score,
                metadata=dict(doc.metadata),
            ))
        return out
