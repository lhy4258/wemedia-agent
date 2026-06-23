from __future__ import annotations

from importlib import import_module
from typing import Any

from langgraph.graph import END, StateGraph

from app.graph.workflow import NODES, run_node


async def _run_named_node(state: dict[str, Any], node: str) -> dict[str, Any]:
    workflow_state = state["workflow_state"]
    state["workflow_state"] = await run_node(node, workflow_state)
    return state


def build_state_graph(checkpointer: Any | None = None):
    graph = StateGraph(dict)
    for node in NODES:
        graph.add_node(node, _node_runner(node))
    graph.set_entry_point(NODES[0])
    graph.add_conditional_edges(
        "topic_review",
        _topic_route,
        {
            "approved": "writing_agent",
            "waiting": END,
        },
    )
    graph.add_edge("writing_agent", "image_agent")
    graph.add_edge("image_agent", "final_review")
    graph.add_conditional_edges(
        "final_review",
        _review_route,
        {
            "approved": "finalize",
            "waiting": END,
        },
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def build_checkpointer_config(database_url: str) -> dict[str, str]:
    if database_url.startswith("postgresql"):
        return {"type": "postgres", "database_url": database_url}
    if database_url.startswith("sqlite"):
        return {"type": "sqlite", "database_url": database_url}
    return {"type": "none", "database_url": database_url}


def normalize_postgres_checkpoint_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def build_postgres_checkpointer(database_url: str):
    try:
        module = import_module("langgraph.checkpoint.postgres")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PostgreSQL LangGraph checkpointer requires dependency "
            "'langgraph-checkpoint-postgres'. Install backend requirements before enabling it."
        ) from exc
    context_manager = module.PostgresSaver.from_conn_string(normalize_postgres_checkpoint_url(database_url))
    saver = context_manager.__enter__()
    saver.setup()
    saver._wemedia_context_manager = context_manager
    return saver


def build_persistent_state_graph(database_url: str):
    return build_state_graph(checkpointer=build_postgres_checkpointer(database_url))


def _node_runner(node: str):
    async def runner(state: dict[str, Any]) -> dict[str, Any]:
        return await _run_named_node(state, node)

    return runner


def _review_route(state: dict[str, Any]) -> str:
    workflow_state = state["workflow_state"]
    if workflow_state.human_review.get("approved"):
        return "approved"
    return "waiting"


def _topic_route(state: dict[str, Any]) -> str:
    workflow_state = state["workflow_state"]
    if workflow_state.topic_review.get("approved"):
        return "approved"
    return "waiting"
