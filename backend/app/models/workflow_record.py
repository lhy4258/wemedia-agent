from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MetricsSnapshot:
    token_in: int = 0
    token_out: int = 0
    latency_ms: int = 0
    cost_estimate: float = 0.0
    error_count: int = 0


@dataclass(slots=True)
class WorkflowRecord:
    id: str
    request_id: str
    persona_id: str
    status: str
    current_node: str
    state: dict[str, Any] = field(default_factory=dict)
    metrics: MetricsSnapshot = field(default_factory=MetricsSnapshot)
    error: str | None = None
