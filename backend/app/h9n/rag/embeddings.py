"""Embedding provider abstraction used by the H9N RAG pipeline."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from openai import OpenAI

from .config import RagSettings


class EmbeddingProvider(Protocol):
    """Lets tests replace the network-backed embedding provider with a fake."""

    def embed_texts(self, texts: list[str], organization_id: UUID) -> list[list[float]]:
        """Return one embedding vector per supplied text, in the same order."""


class OpenRouterEmbeddingProvider:
    """Creates embeddings through OpenRouter's OpenAI-compatible API.

    Keeping the standard ``openai`` SDK avoids an additional client dependency
    while allowing H9N to use OpenRouter's embedding-model catalog.
    """

    _BATCH_SIZE = 64

    def __init__(self, settings: RagSettings) -> None:
        settings.require("OPENROUTER_API_KEY")
        self._settings = settings
        headers = {}
        if settings.openrouter_referer:
            headers["HTTP-Referer"] = settings.openrouter_referer
        if settings.openrouter_title:
            headers["X-OpenRouter-Title"] = settings.openrouter_title

        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            default_headers=headers or None,
        )

    def embed_texts(self, texts: list[str], organization_id: UUID) -> list[list[float]]:
        """Embed text using one consistent model and dimension for the whole index."""
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("RAG cannot create an embedding for empty text.")

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._BATCH_SIZE):
            batch = texts[start : start + self._BATCH_SIZE]
            response = self._client.embeddings.create(
                model=self._settings.embedding_model,
                input=batch,
                dimensions=self._settings.embedding_dimensions,
                # This opaque tenant identifier helps API abuse monitoring
                # without sending a customer's name or source text as metadata.
                user=f"h9n-org-{organization_id}",
            )
            batch_vectors = [item.embedding for item in response.data]
            if any(len(vector) != self._settings.embedding_dimensions for vector in batch_vectors):
                raise RuntimeError("Embedding provider returned an unexpected vector dimension.")
            vectors.extend(batch_vectors)

        if len(vectors) != len(texts):
            raise RuntimeError("Embedding provider returned a different number of vectors than inputs.")
        return vectors
