from __future__ import annotations

import hashlib
import asyncio
import json
import threading
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from app.core.config import settings
from app.services.hot_topic_adapters import collect_candidates, merge_and_score
from app.services.http_client import open_http_request
from app.services.llm_service import LLMService


SCOUT_SOURCE_ID = "hot-topic-scout"
MAX_SCOUT_CANDIDATES_PER_REQUEST = 2

SCOUT_SYSTEM_PROMPT = """
You are Hot Topic Scout Agent for a Chinese self-media operations console.
Your job is to plan compliant public research and synthesize original hot-topic candidates.

Rules:
- 合规第一：只能使用公开网页、公开搜索结果、RSS、Firecrawl 返回内容或用户授权来源；不得绕过验证码、登录墙、付费墙、robots/条款硬限制。
- 保留证据：每个候选必须保留 source_urls、使用的工具、搜索词、access_method 和 auth_type，便于人工审计。
- 原创表达：只抽象趋势、结构、关键词、用户痛点和选题角度，不复制外部原文表达。
- 自适应搜索：keyword 模式围绕用户关键词扩展；auto 模式基于平台、近期内容方向和用户痛点自行规划搜索词。
- 候选数量：同一组关键词或一次自动搜索最多输出 2 个候选题目；优先综合多篇来源提炼成一个题目，不要把每篇资料拆成单独候选。
- 输出必须是 valid JSON，不要 Markdown，不要代码块。
""".strip()

SCOUT_PLAN_SCHEMA = {
    "type": "object",
    "required": ["mode", "queries"],
    "properties": {
        "mode": {"type": "string", "enum": ["keyword", "auto"]},
        "strategy": {"type": "string"},
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["query", "tool", "reason"],
                "properties": {
                    "query": {"type": "string"},
                    "tool": {"type": "string", "enum": ["browser-search", "firecrawl", "both"]},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}

SCOUT_SYNTHESIS_SCHEMA = {
    "type": "object",
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "summary", "signals", "risk_level"],
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "url": {"type": "string"},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                    "signals": {"type": "object"},
                    "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


class BrowserSearchTool:
    name = "browser-search"

    def search(self, query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        keywords = payload.get("keywords") or []
        keyword_text = " ".join(keywords) if keywords else payload.get("platform", "self media")
        return [
            {
                "title": f"{keyword_text}: 公开热点搜索任务",
                "url": f"https://search.local/wemedia-agent?{urlencode({'q': query})}",
                "summary": "浏览器搜索工具待接入真实浏览器控制器；当前记录搜索意图并生成可审计候选。",
                "signals": {"heat": 62, "growth": 16, "platform_fit": 70, "audience_fit": 70, "material_fit": 65},
                "tool": self.name,
            }
        ]


class FirecrawlTool:
    name = "firecrawl"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: int | None = None,
        max_results: int | None = None,
    ):
        self.api_key = api_key or settings.firecrawl_api_key
        self.base_url = (base_url or settings.firecrawl_base_url).rstrip("/")
        self.enabled = settings.firecrawl_enabled if enabled is None else enabled
        self.timeout_seconds = settings.firecrawl_timeout_seconds if timeout_seconds is None else timeout_seconds
        self.max_results = settings.firecrawl_max_results if max_results is None else max_results

    def search(self, query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.enabled or not self.api_key:
            return []
        body = {
            "query": query,
            "limit": int(payload.get("limit") or self.max_results),
            "sources": payload.get("sources") or ["web", "news"],
            "scrapeOptions": {"formats": ["markdown", "summary"]},
        }
        data = self._post("/search", body)
        raw_items = _firecrawl_result_items(data)
        return [self._search_item(item) for item in raw_items[: self.max_results]]

    def enrich(self, result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled or not self.api_key or not result.get("url"):
            return result
        try:
            data = self._post(
                "/scrape",
                {"url": result["url"], "formats": ["markdown", "summary", "links", "images"]},
            )
        except Exception:  # noqa: BLE001
            return result
        payload_data = data.get("data") or data
        enriched = dict(result)
        enriched["summary"] = (
            payload_data.get("summary")
            or payload_data.get("markdown", "")[:500]
            or enriched.get("summary", "")
        )
        enriched["signals"] = {
            **enriched.get("signals", {}),
            "material_fit": 80 if payload_data.get("markdown") else enriched.get("signals", {}).get("material_fit", 60),
        }
        return enriched

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with open_http_request(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _search_item(self, item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata") or {}
        title = item.get("title") or metadata.get("title") or item.get("url") or "Untitled result"
        summary = item.get("description") or item.get("summary") or item.get("markdown", "")[:500]
        return {
            "title": title,
            "url": item.get("url") or metadata.get("sourceURL") or "",
            "summary": summary,
            "signals": {"heat": 72, "growth": 18, "material_fit": 75},
            "tool": self.name,
        }


class SourceAdapterTool:
    name = "source-adapter"

    def search(self, source: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
        return collect_candidates(source, payload)


class HotTopicScoutAgent:
    def __init__(
        self,
        browser_search: BrowserSearchTool | Any | None = None,
        firecrawl: FirecrawlTool | Any | None = None,
        source_adapter: SourceAdapterTool | Any | None = None,
        llm_service: LLMService | Any | None = None,
    ):
        self.browser_search = browser_search or BrowserSearchTool()
        self.firecrawl = FirecrawlTool() if firecrawl is None else firecrawl
        self.source_adapter = source_adapter or SourceAdapterTool()
        self.llm_service = llm_service or LLMService()
        self.last_source_statuses: dict[str, dict[str, str | None]] = {}

    def research(self, payload: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        mode = _search_mode(payload)
        normalized_payload = {**payload, "mode": mode}
        plan = self._plan_searches(normalized_payload)
        queries = [item["query"] for item in plan] or _build_queries(normalized_payload)
        results: list[dict[str, Any]] = []
        used_tools: set[str] = set()
        self.last_source_statuses = {}

        if not sources:
            for item in plan or [{"query": query, "tool": "both", "reason": "fallback"} for query in queries]:
                query = item["query"]
                tool = item.get("tool", "both")
                try:
                    browser_results = (
                        self.browser_search.search(query, normalized_payload)
                        if tool in {"browser-search", "both"}
                        else []
                    )
                except Exception:  # noqa: BLE001
                    browser_results = []
                if browser_results:
                    used_tools.add(getattr(self.browser_search, "name", "browser-search"))
                    if tool in {"firecrawl", "both"} and hasattr(self.firecrawl, "enrich"):
                        used_tools.add(getattr(self.firecrawl, "name", "firecrawl"))
                        results.extend(self.firecrawl.enrich(item, normalized_payload) for item in browser_results)
                    else:
                        results.extend(browser_results)
                try:
                    firecrawl_results = (
                        self.firecrawl.search(query, normalized_payload)
                        if tool in {"firecrawl", "both"} and hasattr(self.firecrawl, "search")
                        else []
                    )
                except Exception:  # noqa: BLE001
                    firecrawl_results = []
                if firecrawl_results:
                    used_tools.add(getattr(self.firecrawl, "name", "firecrawl"))
                    for result in firecrawl_results:
                        results.append(self.firecrawl.enrich(result, normalized_payload))

        for source in sources or []:
            try:
                if source.get("type") in {"firecrawl_search", "firecrawl_scrape"}:
                    source_results = self._run_firecrawl_source(source, normalized_payload, used_tools)
                else:
                    used_tools.add(getattr(self.source_adapter, "name", "source-adapter"))
                    source_results = self.source_adapter.search(source, normalized_payload)
                self.last_source_statuses[source["id"]] = {"status": "succeeded", "error": None}
                results.extend(source_results)
            except Exception as exc:  # noqa: BLE001
                self.last_source_statuses[source["id"]] = {"status": "failed", "error": str(exc)}

        synthesized = self._synthesize_candidates(results, normalized_payload, sorted(used_tools), queries)
        topics = merge_and_score(synthesized, normalized_payload)
        for topic in topics:
            topic["score"] = round(float(topic.get("score", 0)) + _evidence_bonus(topic), 2)
        return sorted(topics, key=lambda item: item.get("score", 0), reverse=True)[:MAX_SCOUT_CANDIDATES_PER_REQUEST]

    def _plan_searches(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        fallback = [{"query": query, "tool": "both", "reason": "规则回退"} for query in _build_queries(payload)]
        try:
            result = _run_async(
                self.llm_service.complete(
                    "hot_topic_scout_plan",
                    [
                        {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
                        {"role": "user", "content": _plan_prompt(payload)},
                    ],
                    schema=SCOUT_PLAN_SCHEMA,
                )
            )
            data = _parse_json_object(result.get("content", ""))
            planned = []
            for item in data.get("queries", []):
                query = str(item.get("query", "")).strip()
                if not query:
                    continue
                tool = str(item.get("tool", "both")).strip()
                if tool not in {"browser-search", "firecrawl", "both"}:
                    tool = "both"
                planned.append(
                    {
                        "query": query,
                        "tool": tool,
                        "reason": str(item.get("reason", "")).strip() or "LLM search plan",
                    }
                )
            return planned[:5] or fallback
        except Exception:  # noqa: BLE001
            return fallback

    def _synthesize_candidates(
        self,
        results: list[dict[str, Any]],
        payload: dict[str, Any],
        tools: list[str],
        queries: list[str],
    ) -> list[dict[str, Any]]:
        fallback = [_candidate_from_result(item, payload, tools, queries) for item in results]
        if not results:
            return fallback
        try:
            result = _run_async(
                self.llm_service.complete(
                    "hot_topic_scout_synthesis",
                    [
                        {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
                        {"role": "user", "content": _synthesis_prompt(payload, results, tools, queries)},
                    ],
                    schema=SCOUT_SYNTHESIS_SCHEMA,
                )
            )
            data = _parse_json_object(result.get("content", ""))
            candidates = []
            for item in data.get("candidates", []):
                candidate = _candidate_from_llm(item, payload, tools, queries)
                if candidate:
                    candidates.append(candidate)
            return (candidates or fallback)[:MAX_SCOUT_CANDIDATES_PER_REQUEST]
        except Exception:  # noqa: BLE001
            return fallback

    def _run_firecrawl_source(
        self,
        source: dict[str, Any],
        payload: dict[str, Any],
        used_tools: set[str],
    ) -> list[dict[str, Any]]:
        used_tools.add(getattr(self.firecrawl, "name", "firecrawl"))
        rules = source.get("rules", {})
        if source.get("type") == "firecrawl_search":
            query = rules.get("query") or " ".join(_build_queries(payload)[:1])
            return self.firecrawl.search(query, payload)
        result = {
            "title": source["name"],
            "url": source["base_url"],
            "summary": "",
            "signals": {"heat": 60, "growth": 12},
            "tool": "firecrawl",
        }
        return [self.firecrawl.enrich(result, payload)]


def _search_mode(payload: dict[str, Any]) -> str:
    mode = str(payload.get("mode") or payload.get("search_mode") or "keyword").lower()
    return "auto" if mode == "auto" else "keyword"


def _firecrawl_result_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items: Any = data.get("data") or data.get("results") or []
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("results") or raw_items.get("items") or raw_items.get("data") or []
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _build_queries(payload: dict[str, Any]) -> list[str]:
    platform = payload.get("platform") or "self media"
    keywords = [str(item).strip() for item in payload.get("keywords") or [] if str(item).strip()]
    if payload.get("mode") == "auto" or not keywords:
        return [
            f"{platform} 热门选题 趋势",
            f"{platform} 内容热点 用户痛点",
            f"{platform} 爆款 内容 近期",
        ]
    keyword_text = " ".join(keywords)
    return [
        f"{keyword_text} {platform} 热门选题",
        f"{keyword_text} 用户痛点 趋势",
    ]


def _candidate_from_result(
    result: dict[str, Any],
    payload: dict[str, Any],
    tools: list[str],
    queries: list[str] | None = None,
) -> dict[str, Any]:
    title = str(result.get("title") or "未命名热点").strip()
    url = str(result.get("url") or f"https://search.local/wemedia-agent/{_stable_id(title, '')}")
    summary = str(result.get("summary") or "").strip()
    signals = {
        "heat": 65,
        "growth": 15,
        "platform_fit": 65,
        "audience_fit": 65,
        "material_fit": 60,
        "evidence_count": 1,
        "source_diversity": len(tools) or 1,
        **result.get("signals", {}),
    }
    return {
        "id": result.get("id") or _stable_id(url, title),
        "source_id": result.get("source_id") or SCOUT_SOURCE_ID,
        "title": title,
        "url": url,
        "summary": summary,
        "signals": signals,
        "risk_level": result.get("risk_level", "low"),
        "evidence": {
            **result.get("evidence", {}),
            "source_name": result.get("evidence", {}).get("source_name", "热点搜查Agent"),
            "url": url,
            "source_urls": [url],
            "queries": queries or _build_queries(payload),
            "tools": tools or [result.get("tool", "browser-search")],
            "access_method": result.get("evidence", {}).get("access_method", result.get("tool", "browser-search")),
            "auth_type": result.get("evidence", {}).get("auth_type", "public"),
            "search_mode": payload.get("mode", "keyword"),
        },
    }


def _candidate_from_llm(
    item: dict[str, Any],
    payload: dict[str, Any],
    tools: list[str],
    queries: list[str],
) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    source_urls = [str(url).strip() for url in item.get("source_urls") or [] if str(url).strip()]
    url = str(item.get("url") or (source_urls[0] if source_urls else "")).strip()
    if not url:
        url = f"https://search.local/wemedia-agent/{_stable_id(title, '')}"
    source_urls = source_urls or [url]
    signals = {
        "heat": 65,
        "growth": 15,
        "platform_fit": 65,
        "audience_fit": 65,
        "material_fit": 60,
        "evidence_count": len(source_urls),
        "source_diversity": len(tools) or 1,
        **(item.get("signals") or {}),
    }
    return {
        "id": item.get("id") or _stable_id(url, title),
        "source_id": SCOUT_SOURCE_ID,
        "title": title,
        "url": url,
        "summary": str(item.get("summary") or "").strip(),
        "signals": signals,
        "risk_level": item.get("risk_level", "low"),
        "evidence": {
            "source_name": "热点搜查Agent",
            "url": url,
            "source_urls": source_urls,
            "queries": queries,
            "tools": tools or ["browser-search"],
            "access_method": "llm-assisted-research",
            "auth_type": "public",
            "search_mode": payload.get("mode", "keyword"),
            "reason": str(item.get("reason") or "").strip(),
        },
    }


def _plan_prompt(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "plan_hot_topic_searches",
            "mode": payload.get("mode", "keyword"),
            "platform": payload.get("platform"),
            "keywords": payload.get("keywords") or [],
            "instructions": [
                "keyword 模式必须围绕 keywords 扩展搜索词",
                "auto 模式可自行寻找平台近期热门方向、用户痛点、行业讨论",
                "每条 query 指定 tool: browser-search、firecrawl 或 both",
                "最多返回 5 条 query",
            ],
        },
        ensure_ascii=False,
    )


def _synthesis_prompt(
    payload: dict[str, Any],
    results: list[dict[str, Any]],
    tools: list[str],
    queries: list[str],
) -> str:
    compact_results = [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "summary": item.get("summary"),
            "signals": item.get("signals", {}),
            "tool": item.get("tool"),
        }
        for item in results[:12]
    ]
    return json.dumps(
        {
            "task": "synthesize_hot_topic_candidates",
            "mode": payload.get("mode", "keyword"),
            "platform": payload.get("platform"),
            "keywords": payload.get("keywords") or [],
            "tools": tools,
            "queries": queries,
            "results": compact_results,
            "requirements": [
                "最多生成 2 个原创热门选题候选",
                "综合多篇来源提炼选题，不要按每篇资料拆分候选",
                "标题要像可执行的自媒体选题，不复制外部原文",
                "summary 说明趋势、用户痛点、可写角度",
                "signals 包含 heat/growth/platform_fit/audience_fit/material_fit",
                "risk_level 只能是 low/medium/high",
                "source_urls 必须来自 results.url",
            ],
        },
        ensure_ascii=False,
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response does not contain a JSON object")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return data


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner():
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _stable_id(url: str, title: str) -> str:
    digest = hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()
    return f"scout-{digest[:16]}"


def _evidence_bonus(topic: dict[str, Any]) -> float:
    signals = topic.get("signals", {})
    return min(8, float(signals.get("source_diversity", 1)) * 2 + float(signals.get("evidence_count", 1)))
