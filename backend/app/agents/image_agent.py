from __future__ import annotations

from app.agents.tools import generate_images_for_draft, retrieve_graph_context
from app.graph.state import WorkflowState


class ImageAgent:
    async def run(self, state: WorkflowState) -> WorkflowState:
        if not state.retrieved_assets:
            state = retrieve_graph_context(state)
        return await generate_images_for_draft(state)
