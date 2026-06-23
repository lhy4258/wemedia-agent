from __future__ import annotations

from app.agents.tools import (
    create_topic_cards,
    discover_hot_topic_candidates,
    draft_post_with_llm,
    prepare_topic_review_gate,
    rank_hot_topic_candidates,
    retrieve_graph_context,
)
from app.graph.state import WorkflowState


class WritingAgent:
    async def create_topics(self, state: WorkflowState) -> WorkflowState:
        state = discover_hot_topic_candidates(state)
        state = retrieve_graph_context(state)
        state = rank_hot_topic_candidates(state)
        state = create_topic_cards(state)
        return prepare_topic_review_gate(state)

    async def run(self, state: WorkflowState) -> WorkflowState:
        if not state.topics:
            state = await self.create_topics(state)
        return await draft_post_with_llm(state)
