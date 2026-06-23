from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from langsmith import trace

from app.core.config import settings

SENSITIVE_KEYS = {"api_key", "authorization", "cookie", "password", "secret", "token"}


class TracingService:
    def __init__(
        self,
        enabled: bool | None = None,
        project_name: str | None = None,
        tracer: Callable[..., Any] = trace,
    ):
        self.enabled = settings.langsmith_tracing if enabled is None else enabled
        self.project_name = project_name or settings.langsmith_project
        self.tracer = tracer

    def workflow(self, name: str, inputs: dict[str, Any], metadata: dict[str, Any]):
        return self._trace(name, "chain", inputs, metadata, ["workflow"])

    def node(self, name: str, inputs: dict[str, Any], metadata: dict[str, Any]):
        return self._trace(name, "chain", inputs, metadata, ["node", name])

    def model(self, name: str, inputs: dict[str, Any], metadata: dict[str, Any]):
        return self._trace(name, "llm", inputs, metadata, ["model"])

    def _trace(
        self,
        name: str,
        run_type: str,
        inputs: dict[str, Any],
        metadata: dict[str, Any],
        tags: list[str],
    ):
        if not self.enabled:
            return nullcontext()
        try:
            return _SafeTraceContext(
                self.tracer(
                    name,
                    run_type=run_type,
                    inputs=sanitize_payload(inputs),
                    metadata=sanitize_payload(metadata),
                    project_name=self.project_name,
                    tags=tags,
                )
            )
        except Exception:  # noqa: BLE001
            return nullcontext()


def finish_trace(run: Any, outputs: dict[str, Any] | None = None) -> None:
    if run is None or not hasattr(run, "end"):
        return
    try:
        run.end(outputs=sanitize_payload(outputs or {}))
    except Exception:  # noqa: BLE001
        return


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _is_sensitive_key(key) else sanitize_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_payload(item) for item in value)
    return value


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).casefold()
    return any(part in normalized for part in SENSITIVE_KEYS)


class _SafeTraceContext:
    def __init__(self, context):
        self.context = context

    def __enter__(self):
        try:
            return self.context.__enter__()
        except Exception:  # noqa: BLE001
            return None

    def __exit__(self, exc_type, exc, traceback):
        try:
            return self.context.__exit__(exc_type, exc, traceback)
        except Exception:  # noqa: BLE001
            return False
