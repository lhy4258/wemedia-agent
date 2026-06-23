from __future__ import annotations

import json
from urllib.request import Request

from app.core.config import settings
from app.services.http_client import open_http_request
from app.services.tracing_service import TracingService, finish_trace


class ImageService:
    def __init__(
        self,
        mock: bool | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tracing: TracingService | None = None,
    ):
        self.mock = settings.image_mock if mock is None else mock
        self.api_key = api_key or settings.image_api_key
        self.base_url = (base_url or settings.image_base_url).rstrip("/")
        self.model = model or settings.image_model
        self.tracing = tracing or TracingService()

    async def generate_batch(self, prompts: list[str]) -> list[dict[str, str]]:
        with self.tracing.model(
            "image_generation",
            inputs={"prompt_count": len(prompts), "prompts": prompts},
            metadata={"model": self.model, "mock": self.mock, "base_url": self.base_url},
        ) as run:
            if self.mock:
                images = [{"prompt": prompt, "url": f"mock://image/{index}"} for index, prompt in enumerate(prompts)]
                finish_trace(run, {"image_count": len(images), "mock": True})
                return images
            if not self.api_key:
                raise RuntimeError("IMAGE_API_KEY is required when IMAGE_MOCK=false")
            images: list[dict[str, str]] = []
            for prompt in prompts:
                request = Request(
                    f"{self.base_url}/images/generations",
                    data=json.dumps({"model": self.model, "prompt": prompt}).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with open_http_request(request, timeout=60) as response:
                    data = json.loads(response.read().decode("utf-8"))
                image = data.get("data", [{}])[0]
                images.append({"prompt": prompt, "url": image.get("url", ""), "raw": data})
            finish_trace(run, {"image_count": len(images)})
            return images
