from __future__ import annotations

import json
from typing import Any
from urllib.request import Request

from app.core.config import settings
from app.services.http_client import open_http_request
from app.services.tracing_service import TracingService, finish_trace


class LLMService:
    def __init__(
        self,
        mock: bool | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
        timeout_seconds: int | None = None,
        tracing: TracingService | None = None,
    ):
        self.mock = settings.llm_mock if mock is None else mock
        self.api_key = api_key or settings.llm_api_key
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.top_p = settings.llm_top_p if top_p is None else top_p
        self.max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens
        self.presence_penalty = settings.llm_presence_penalty if presence_penalty is None else presence_penalty
        self.frequency_penalty = settings.llm_frequency_penalty if frequency_penalty is None else frequency_penalty
        self.timeout_seconds = settings.llm_timeout_seconds if timeout_seconds is None else timeout_seconds
        self.tracing = tracing or TracingService()

    async def complete(self, task_type: str, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> dict[str, Any]:
        parameters = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
        }
        with self.tracing.model(
            f"llm:{task_type}",
            inputs={"messages": messages, "schema": schema or {}},
            metadata={
                "model": self.model,
                "mock": self.mock,
                "base_url": self.base_url,
                "task_type": task_type,
                **parameters,
            },
        ) as run:
            if self.mock:
                result = {"task_type": task_type, "content": messages[-1]["content"] if messages else "", "schema": schema or {}}
                finish_trace(run, {"task_type": task_type, "mock": True})
                return result
            if not self.api_key:
                raise RuntimeError("LLM_API_KEY is required when LLM_MOCK=false")
            payload: dict[str, Any] = {"model": self.model, "messages": messages, **parameters}
            if schema:
                payload["response_format"] = {"type": "json_object"}
            request = Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with open_http_request(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            message = data.get("choices", [{}])[0].get("message", {})
            result = {
                "task_type": task_type,
                "content": message.get("content", ""),
                "raw": data,
                "usage": data.get("usage", {}),
            }
            finish_trace(run, {"task_type": task_type, "usage": result["usage"]})
            return result
