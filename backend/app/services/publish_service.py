from __future__ import annotations

import uuid
from typing import Any

from app.core.config import settings
from app.services.wechat_publisher import WechatOfficialAccountPublisher


class PublishService:
    def __init__(self, repository: Any, publisher: Any | None = None):
        self.repository = repository
        self.publisher = publisher or WechatOfficialAccountPublisher()

    def publish(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        platform = payload.get("platform", "wechat_official_account")
        if platform != "wechat_official_account":
            raise ValueError("Only wechat_official_account publishing is supported")
        mode = payload.get("mode") or settings.wechat_publish_default_mode
        if mode not in {"draft", "submit"}:
            raise ValueError("mode must be draft or submit")

        posts = self.repository.list_generated_posts(workflow_id)
        if not posts:
            raise ValueError("No generated post found for this workflow")
        post = posts[0]
        job = {
            "id": uuid.uuid4().hex,
            "workflow_id": workflow_id,
            "post_id": post["id"],
            "platform": platform,
            "mode": mode,
            "status": "pending",
            "external_media_id": None,
            "publish_id": None,
            "article_id": None,
            "article_url": None,
            "request": {"operator": payload.get("operator"), "comment": payload.get("comment"), "mode": mode},
            "response": {},
            "error": None,
        }
        self.repository.save_publish_job(job)
        try:
            result = self.publisher.publish_post(post, mode)
            job.update(
                {
                    "status": result.get("status", "draft_created"),
                    "external_media_id": result.get("external_media_id"),
                    "publish_id": result.get("publish_id"),
                    "article_id": result.get("article_id"),
                    "article_url": result.get("article_url"),
                    "request": result.get("request") or job["request"],
                    "response": result.get("response") or result,
                    "error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            job.update(
                {
                    "status": "failed",
                    "response": {},
                    "error": str(exc),
                }
            )
        self.repository.save_publish_job(job)
        return job
