from __future__ import annotations

import hashlib
import json
from urllib.request import Request

from app.core.config import settings
from app.services.http_client import open_http_request
from app.services.tracing_service import TracingService, finish_trace

EMBEDDING_DIMENSION = settings.embed_dimension


class EmbeddingService:
    def __init__(
        self,
        mock: bool | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tracing: TracingService | None = None,
    ):
        self.mock = settings.embed_mock if mock is None else mock
        self.api_key = api_key or settings.embed_api_key
        self.base_url = (base_url or settings.embed_base_url).rstrip("/")
        self.model = model or settings.embed_model
        self.tracing = tracing or TracingService()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        with self.tracing.model(
            "embedding",
            inputs={"text_count": len(texts)},
            metadata={"model": self.model, "mock": self.mock, "base_url": self.base_url},
        ) as run:
            if self.mock:
                vectors = [build_hash_embedding(text) for text in texts]
                finish_trace(run, {"text_count": len(texts), "mock": True})
                return vectors
            if not self.api_key:
                raise RuntimeError("EMBED_API_KEY is required when EMBED_MOCK=false")
            payload = {"model": self.model, "input": texts}
            request = Request(
                f"{self.base_url}/embeddings",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with open_http_request(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            vectors = [item.get("embedding", []) for item in data.get("data", [])]
            finish_trace(run, {"text_count": len(texts), "usage": data.get("usage", {})})
            return vectors


def build_hash_embedding(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    vector = [0.0] * dimension
    for term in text.split():
        normalized = term.strip().casefold()
        if not normalized:
            continue
        digest = hashlib.sha256(normalized.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    magnitude = sum(value * value for value in vector) ** 0.5
    if not magnitude:
        return vector
    return [value / magnitude for value in vector]
