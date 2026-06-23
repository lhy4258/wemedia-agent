from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import workflow_service

router = APIRouter(prefix="/hot-topics", tags=["hot-topics"])


@router.get("")
async def list_hot_topics():
    return workflow_service.list_hot_topics()


@router.get("/runs")
async def list_crawl_runs():
    return workflow_service.list_crawl_runs()


@router.post("/refresh")
async def refresh_hot_topics(payload: dict):
    return workflow_service.refresh_hot_topics(payload)


@router.delete("/{topic_id}")
async def delete_hot_topic(topic_id: str):
    return workflow_service.delete_hot_topic(topic_id)
