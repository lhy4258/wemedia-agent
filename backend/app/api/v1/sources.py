from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import workflow_service

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("")
async def list_sources():
    return workflow_service.list_sources()


@router.post("")
async def create_source(payload: dict):
    return workflow_service.save_source(payload)
