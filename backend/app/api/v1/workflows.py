from __future__ import annotations

import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.api.deps import workflow_service
from app.graph.state import WorkflowInput

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("")
async def list_workflows():
    return workflow_service.list()


@router.post("")
async def start_workflow(payload: WorkflowInput):
    return await workflow_service.start(payload)


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    return workflow_service.get(workflow_id)


@router.get("/{workflow_id}/events")
async def get_events(workflow_id: str):
    return list(workflow_service.stream_events(workflow_id))


@router.get("/{workflow_id}/posts")
async def get_generated_posts(workflow_id: str):
    return workflow_service.list_generated_posts(workflow_id)


@router.get("/{workflow_id}/publish-jobs")
async def get_publish_jobs(workflow_id: str):
    return workflow_service.list_publish_jobs(workflow_id)


@router.get("/{workflow_id}/stream")
async def stream_workflow(workflow_id: str):
    async def events():
        for event in workflow_service.stream_events(workflow_id):
            yield {"event": event["event"], "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(events())


@router.post("/{workflow_id}/retry")
async def retry_workflow(workflow_id: str, payload: dict):
    return await workflow_service.retry(workflow_id, payload.get("from_node", "writing_agent"))


@router.post("/{workflow_id}/topic-review")
async def submit_topic_review(workflow_id: str, payload: dict):
    return await workflow_service.topic_review(workflow_id, payload)


@router.post("/{workflow_id}/human-review")
async def submit_human_review(workflow_id: str, payload: dict):
    return await workflow_service.human_review(workflow_id, payload)


@router.post("/{workflow_id}/pause")
async def pause_workflow(workflow_id: str, payload: dict):
    return workflow_service.pause(workflow_id, payload)


@router.post("/{workflow_id}/return-to-previous")
async def return_workflow_to_previous(workflow_id: str, payload: dict):
    return workflow_service.return_to_previous(workflow_id, payload)


@router.post("/{workflow_id}/publish")
async def publish_workflow(workflow_id: str, payload: dict):
    return workflow_service.publish(workflow_id, payload)


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    return workflow_service.delete(workflow_id)
