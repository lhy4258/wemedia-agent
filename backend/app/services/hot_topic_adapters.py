from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote_to_bytes, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


class _HtmlSummaryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        self._in_title = tag.lower() == "title"

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
            return
        self._parts.append(text)

    @property
    def summary(self) -> str:
        return " ".join(self._parts)[:300]


def collect_candidates(source: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    source_type = source.get("type", "web")
    if source_type == "rss":
        return _collect_rss(source, payload)
    if source_type == "web":
        return _collect_web(source, payload)
    if source_type == "mock":
        return _collect_mock(source, payload)
    if source_type == "authorized":
        return _collect_authorized(source, payload)
    raise ValueError(f"unsupported source type: {source_type}")


def merge_and_score(candidates: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for candidate in candidates:
        keys = _dedupe_keys(candidate)
        key = next((aliases[item] for item in keys if item in aliases), keys[0])
        scored = dict(candidate)
        scored["score"] = _score(scored, payload)
        current = deduped.get(key)
        if current is None or scored["score"] > current["score"]:
            deduped[key] = scored
        for item in keys:
            aliases[item] = key
    return sorted(deduped.values(), key=lambda item: item["score"], reverse=True)


def _collect_mock(source: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    rules = source.get("rules", {})
    items = rules.get("items")
    if not items:
        keywords = payload.get("keywords") or ["AI", "teacher"]
        keyword_text = " ".join(keywords)
        items = [
            {
                "title": f"{keyword_text}: 3 个正在升温的内容角度",
                "url": "https://example.com/trends/mock-wemedia",
                "summary": "公开趋势信号显示，用户更关心可复制的流程、真实案例和低风险上手路径。",
                "signals": {"heat": 92, "growth": 28, "platform_fit": 86, "material_fit": 80},
                "risk_level": "low",
            }
        ]
    return [_candidate(source, item, "mock-public") for item in items]


def _collect_authorized(source: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    rules = source.get("rules", {})
    if not rules.get("token") and not rules.get("cookie"):
        raise ValueError("authorized source requires user-provided token or cookie")
    items = rules.get("items", [])
    return [_candidate(source, item, "user-authorized") for item in items]


def _collect_rss(source: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    content = _read_text(source["base_url"])
    root = ElementTree.fromstring(content)
    items = root.findall(".//item")
    candidates = []
    for item in items[:10]:
        title = _xml_text(item, "title")
        url = _xml_text(item, "link") or source["base_url"]
        summary = _xml_text(item, "description")
        if title:
            candidates.append(
                _candidate(
                    source,
                    {"title": title, "url": url, "summary": summary, "signals": {"heat": 55, "growth": 12}},
                    "public-rss",
                )
            )
    return candidates


def _collect_web(source: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    content = _read_text(source["base_url"])
    parser = _HtmlSummaryParser()
    parser.feed(content)
    title = parser.title.strip() or source["name"]
    return [
        _candidate(
            source,
            {
                "title": title,
                "url": source["base_url"],
                "summary": parser.summary,
                "signals": {"heat": 50, "growth": 10},
            },
            "public-web",
        )
    ]


def _candidate(source: dict[str, Any], item: dict[str, Any], access_method: str) -> dict[str, Any]:
    url = item.get("url") or source["base_url"]
    title = item["title"].strip()
    return {
        "id": item.get("id") or _stable_id(url, title),
        "source_id": source["id"],
        "title": title,
        "url": url,
        "summary": item.get("summary", "").strip(),
        "signals": item.get("signals", {}),
        "risk_level": item.get("risk_level", "low"),
        "evidence": {
            "source_name": source["name"],
            "url": url,
            "access_method": access_method,
            "auth_type": source.get("auth_mode", "public"),
        },
    }


def _read_text(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "data":
        _, _, payload = url.partition(",")
        return unquote_to_bytes(payload).decode("utf-8")
    request = Request(url, headers={"User-Agent": "wemedia-agent/0.1"})
    with urlopen(request, timeout=8) as response:
        return response.read().decode("utf-8", errors="replace")


def _xml_text(node, tag: str) -> str:
    value = node.findtext(tag)
    return value.strip() if value else ""


def _stable_id(url: str, title: str) -> str:
    digest = hashlib.sha1(f"{url}|{_normalize_title(title)}".encode("utf-8")).hexdigest()
    return f"hot-{digest[:16]}"


def _dedupe_keys(candidate: dict[str, Any]) -> list[str]:
    keys = [f"title:{_normalize_title(candidate['title'])}"]
    url = candidate.get("url", "")
    if url and not url.startswith("data:"):
        keys.insert(0, f"url:{url.rstrip('/')}")
    return keys


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().casefold()


def _score(candidate: dict[str, Any], payload: dict[str, Any]) -> float:
    signals = candidate.get("signals", {})
    heat = float(signals.get("heat", 50))
    growth = float(signals.get("growth", 10))
    platform_fit = float(signals.get("platform_fit", _keyword_fit(candidate, [payload.get("platform", "")])))
    audience_fit = float(signals.get("audience_fit", 50))
    material_fit = float(signals.get("material_fit", _keyword_fit(candidate, payload.get("keywords") or [])))
    risk_penalty = {"low": 0, "medium": 12, "high": 30}.get(candidate.get("risk_level", "low"), 10)
    return round(heat * 0.35 + growth * 0.2 + platform_fit * 0.15 + audience_fit * 0.15 + material_fit * 0.15 - risk_penalty, 2)


def _keyword_fit(candidate: dict[str, Any], keywords: list[str]) -> float:
    text = f"{candidate.get('title', '')} {candidate.get('summary', '')}".casefold()
    usable = [keyword.casefold() for keyword in keywords if keyword]
    if not usable:
        return 50
    hits = sum(1 for keyword in usable if keyword in text)
    return min(100, 40 + hits * 30)
