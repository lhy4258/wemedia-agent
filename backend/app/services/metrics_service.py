from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MetricsEvent:
    node: str
    model: str
    token_in: int = 0
    token_out: int = 0
    latency_ms: int = 0
    error: str | None = None


class MetricsContext:
    def __init__(self):
        self.events: list[MetricsEvent] = []

    def record(
        self,
        node: str,
        model: str,
        token_in: int = 0,
        token_out: int = 0,
        latency_ms: int = 0,
        error: str | None = None,
    ) -> MetricsEvent:
        event = MetricsEvent(
            node=node,
            model=model,
            token_in=token_in,
            token_out=token_out,
            latency_ms=latency_ms,
            error=error,
        )
        self.events.append(event)
        return event
