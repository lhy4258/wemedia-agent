from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import workflow_service

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("")
async def list_assets():
    return workflow_service.list_assets()


@router.post("")
async def create_asset(payload: dict):
    return workflow_service.save_asset(payload)
