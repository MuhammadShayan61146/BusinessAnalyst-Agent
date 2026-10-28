"""
Phase 3C.1 — GeminiEmbeddingService.

Thin wrapper around langchain_google_genai.GoogleGenerativeAIEmbeddings.
Isolated here so VectorStoreService doesn't need to know which
embedding provider is in use, and so this is the single place credential
handling and import-guarding for the embeddings SDK live.
"""
from __future__ import annotations

from config.settings import GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL
from services.llm_service import MissingCredentialsError


class GeminiEmbeddingService:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model or GEMINI_EMBEDDING_MODEL
        if not self.api_key:
            raise MissingCredentialsError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set; cannot construct "
                "the Gemini embedding client. Ingestion and retrieval both "
                "require this."
            )
        # Imported lazily for the same reason as GeminiProvider in
        # llm_service.py: not every environment this repo is checked out
        # into is guaranteed to have langchain-google-genai installed, and
        # nothing else in this module needs it until a client is actually
        # constructed.
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        self._client = GoogleGenerativeAIEmbeddings(model=self.model_name, google_api_key=self.api_key)

    def embed_documents(self, texts: list) -> list:
        return self._client.embed_documents(list(texts))

    def embed_query(self, text: str) -> list:
        return self._client.embed_query(text)

    @property
    def langchain_embeddings(self):
        """Exposes the underlying LangChain Embeddings object directly,
        for callers (VectorStoreService) that hand it to a LangChain
        vector store constructor expecting that interface."""
        return self._client
