from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowInput:
    platform: str
    keywords: list[str]
    persona_id: str = "default"
    candidate_id: str | None = None
    simulate_fail_at: str | None = None


@dataclass(slots=True)
class WorkflowState:
    input: WorkflowInput
    repository: Any | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    retrieved_assets: list[dict[str, Any]] = field(default_factory=list)
    topics: list[dict[str, Any]] = field(default_factory=list)
    topic_review: dict[str, Any] = field(default_factory=dict)
    draft: dict[str, Any] = field(default_factory=dict)
    image_prompts: dict[str, Any] = field(default_factory=dict)
    human_review: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
