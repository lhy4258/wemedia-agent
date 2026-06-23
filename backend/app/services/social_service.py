from __future__ import annotations

from typing import Any


class SocialService:
    async def create_draft(self, platform: str, post: dict[str, Any]) -> dict[str, Any]:
        return {"platform": platform, "status": "not_configured", "post": post}
