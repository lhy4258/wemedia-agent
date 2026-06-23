from __future__ import annotations

from app.agents.image_agent import ImageAgent
from app.agents.tools import prepare_human_review_gate
from app.agents.writing_agent import WritingAgent
from app.graph.state import WorkflowState

NODES = ("topic_review", "writing_agent", "image_agent", "final_review", "finalize")


async def run_node(name: str, state: WorkflowState) -> WorkflowState:
    if name == "topic_review":
        if not state.topics:
            return await WritingAgent().create_topics(state)
        return state
    if name == "writing_agent":
        return await WritingAgent().run(state)
    if name == "image_agent":
        return await ImageAgent().run(state)
    if name == "final_review":
        return prepare_human_review_gate(state)
    if name == "finalize":
        return state
    raise KeyError(name)
