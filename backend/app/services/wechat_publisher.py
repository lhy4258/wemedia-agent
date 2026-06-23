from __future__ import annotations

import json
import time
import uuid
from html import escape
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

import redis

from app.core.config import settings
from app.services.http_client import open_http_request


class WechatPublishError(RuntimeError):
    pass


def wechat_body_html(body: str) -> str:
    paragraphs = [line.strip() for line in body.splitlines() if line.strip()]
    if not paragraphs and body.strip():
        paragraphs = [body.strip()]
    return "\n".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)


def wechat_digest(body: str, limit: int = 120) -> str:
    normalized = " ".join(line.strip() for line in body.splitlines() if line.strip())
    return normalized[:limit]


class WechatAccessTokenProvider:
    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.redis_url
        self.cache_key = "wemedia-agent:wechat:access_token"
        self._memory_token: tuple[str, float] | None = None

    def get_token(self) -> str:
        cached = self._get_cached_token()
        if cached:
            return cached
        token = self._request_token()
        self._set_cached_token(token)
        return token

    def clear(self) -> None:
        self._memory_token = None
        try:
            redis.Redis.from_url(self.redis_url).delete(self.cache_key)
        except Exception:
            return

    def _get_cached_token(self) -> str | None:
        if self._memory_token and self._memory_token[1] > time.time():
            return self._memory_token[0]
        try:
            value = redis.Redis.from_url(self.redis_url).get(self.cache_key)
        except Exception:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    def _set_cached_token(self, token: str) -> None:
        expires_at = time.time() + settings.wechat_token_cache_seconds
        self._memory_token = (token, expires_at)
        try:
            redis.Redis.from_url(self.redis_url).setex(self.cache_key, settings.wechat_token_cache_seconds, token)
        except Exception:
            return

    def _request_token(self) -> str:
        if not settings.wechat_app_id or not settings.wechat_app_secret:
            raise WechatPublishError("WECHAT_APP_ID and WECHAT_APP_SECRET are required")
        query = urlencode(
            {
                "grant_type": "client_credential",
                "appid": settings.wechat_app_id,
                "secret": settings.wechat_app_secret,
            }
        )
        data = self._request_json(f"/cgi-bin/token?{query}", method="GET")
        token = data.get("access_token")
        if not token:
            raise WechatPublishError(data.get("errmsg") or "WeChat access_token response missing access_token")
        return str(token)

    def _request_json(self, path: str, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{settings.wechat_api_base_url.rstrip('/')}{path}"
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=payload, method=method)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        with open_http_request(request, timeout=settings.llm_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


class WechatOfficialAccountPublisher:
    def __init__(self, token_provider: WechatAccessTokenProvider | None = None):
        self.token_provider = token_provider or WechatAccessTokenProvider()

    def publish_post(self, post: dict[str, Any], mode: str) -> dict[str, Any]:
        mode = mode or settings.wechat_publish_default_mode
        if mode not in {"draft", "submit"}:
            raise WechatPublishError("mode must be draft or submit")
        if settings.wechat_publish_mock:
            return self._mock_publish(post, mode)
        if not settings.wechat_default_thumb_media_id:
            raise WechatPublishError("WECHAT_DEFAULT_THUMB_MEDIA_ID is required")

        article = self._article_payload(post)
        draft_payload = {"articles": [article]}
        draft_response = self._request_with_token_retry("/cgi-bin/draft/add", draft_payload)
        media_id = draft_response.get("media_id")
        if not media_id:
            raise WechatPublishError(draft_response.get("errmsg") or "WeChat draft/add response missing media_id")

        result = {
            "status": "draft_created",
            "external_media_id": media_id,
            "request": {"draft": draft_payload},
            "response": {"draft": draft_response},
        }
        if mode == "draft":
            return result

        submit_payload = {"media_id": media_id}
        submit_response = self._request_with_token_retry("/cgi-bin/freepublish/submit", submit_payload)
        result.update(
            {
                "status": "published",
                "publish_id": submit_response.get("publish_id"),
                "article_id": submit_response.get("article_id") or submit_response.get("article_id_list"),
                "article_url": submit_response.get("article_url"),
                "request": {"draft": draft_payload, "submit": submit_payload},
                "response": {"draft": draft_response, "submit": submit_response},
            }
        )
        return result

    def _article_payload(self, post: dict[str, Any]) -> dict[str, Any]:
        body = post.get("body", "")
        return {
            "title": post.get("title", "")[:64],
            "author": "",
            "digest": wechat_digest(body),
            "content": wechat_body_html(body),
            "content_source_url": "",
            "thumb_media_id": settings.wechat_default_thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }

    def _request_with_token_retry(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = self.token_provider.get_token()
        response = self._request_json(path, token, body)
        if response.get("errcode") in {40001, 40014, 42001}:
            self.token_provider.clear()
            response = self._request_json(path, self.token_provider.get_token(), body)
        errcode = response.get("errcode")
        if errcode not in (None, 0):
            raise WechatPublishError(response.get("errmsg") or f"WeChat API error: {errcode}")
        return response

    def _request_json(self, path: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        query = urlencode({"access_token": token})
        url = f"{settings.wechat_api_base_url.rstrip('/')}{path}?{query}"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        with open_http_request(request, timeout=settings.llm_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _mock_publish(self, post: dict[str, Any], mode: str) -> dict[str, Any]:
        media_id = f"mock-draft-{post.get('id') or uuid.uuid4().hex}"
        result = {
            "status": "draft_created",
            "external_media_id": media_id,
            "request": {"mock": True, "mode": mode},
            "response": {"mock": True, "media_id": media_id},
        }
        if mode == "submit":
            publish_id = f"mock-publish-{post.get('id') or uuid.uuid4().hex}"
            result.update(
                {
                    "status": "published",
                    "publish_id": publish_id,
                    "article_id": f"mock-article-{post.get('id') or uuid.uuid4().hex}",
                    "article_url": f"mock://wechat/{publish_id}",
                    "response": {"mock": True, "media_id": media_id, "publish_id": publish_id},
                }
            )
        return result
