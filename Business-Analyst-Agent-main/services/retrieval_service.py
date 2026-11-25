
from __future__ import annotations

from config.settings import VECTOR_STORE_DIR, RAG_TOP_K, RAG_RELEVANCE_THRESHOLD


class RetrievalService:
    def __init__(self, vector_store_service=None):
        #
        self._store = vector_store_service

    def _get_store(self):
        if self._store is None:
            from services.vector_store_service import VectorStoreService
            self._store = VectorStoreService(persist_directory=VECTOR_STORE_DIR)
        return self._store

    def retrieve(self, query: str, k: int = None, threshold: float = None) -> list:
        """
        Returns a list of VectorStoreService.RetrievedChunk. Returns []
        for an empty/uninitialized knowledge base rather than raising —
        callers (agent/nodes.py::analyse_requirements) are expected to
        continue the workflow with that empty list, not to treat its
        absence as a hard failure.
        """
        store = self._get_store()
        return store.similarity_search(
            query,
            k=k if k is not None else RAG_TOP_K,
            threshold=threshold if threshold is not None else RAG_RELEVANCE_THRESHOLD,
        )
