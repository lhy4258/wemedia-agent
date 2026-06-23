from __future__ import annotations

from typing import Any

from app.graph.state import WorkflowState
from app.services.embedding_service import EmbeddingService, build_hash_embedding


class GraphRAGService:
    def __init__(self, repository, embedding_service: EmbeddingService | None = None):
        self.repository = repository
        self.embedding_service = embedding_service or EmbeddingService()

    def retrieve(self, state: WorkflowState, limit: int = 5) -> list[dict[str, Any]]:
        query_terms = [
            state.input.platform,
            *state.input.keywords,
            *(candidate.get("title", "") for candidate in state.candidates[:3]),
            *(candidate.get("summary", "") for candidate in state.candidates[:3]),
        ]
        query_text = " ".join(term for term in query_terms if term)
        query_embedding = self.embedding_service.embed_texts([query_text])[0] if query_text else None
        return self.repository.search_assets(
            query_terms,
            limit=limit,
            query_embedding=query_embedding,
        )


def build_query_embedding(query_terms: list[str]) -> list[float]:
    return build_hash_embedding(" ".join(term for term in query_terms if term))
