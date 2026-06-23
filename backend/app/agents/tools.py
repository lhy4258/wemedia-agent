from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.graph.state import WorkflowState
from app.services.graph_rag_service import GraphRAGService
from app.services.image_service import ImageService
from app.services.llm_service import LLMService


MAX_IMAGES_PER_ARTICLE = 3

WRITER_SYSTEM_PROMPT = """You are the Writing Agent for a Chinese self-media operations workflow.
Your job is to turn an approved hot-topic angle into an original, platform-ready draft.

Rules:
- Write in Simplified Chinese unless the input explicitly asks for another language.
- Write original content; do not copy source wording.
- Use hot-topic candidates only as trend evidence, audience signal, and angle reference.
- Ground claims in provided internal assets when available, and avoid unsupported certainty.
- Match the target platform, audience pain point, and practical action style.
- Avoid exaggerated guarantees, medical/legal/financial certainty, and unsafe claims.
- Produce content that a human editor can approve, revise, or return.
- Also produce a concise summary and an image brief for the Image Agent.

Return valid JSON only with:
{
  "title": "string",
  "body": "string",
  "summary": "string",
  "image_brief": {
    "visual_style": "string",
    "cover": "string",
    "inline_images": ["string", "string"],
    "avoid": ["string"]
  }
}
"""

IMAGE_SYSTEM_PROMPT = """You are the Image Agent for a Chinese self-media operations workflow.
Your job is to convert an approved article, summary, and image brief into image-generation prompts.

Rules:
- Generate at most 3 image prompts total for one article.
- The first prompt must be the cover image.
- Optional remaining prompts should support the article body, such as a workflow diagram or checklist card.
- Keep prompts specific, visual, and safe for public publishing.
- Do not request copyrighted characters, brand logos, celebrity likenesses, real platform screenshots, or misleading proof.
- Prefer clean editorial visuals, useful diagrams, and readable social-media visual cards.
"""

WRITER_RESPONSE_SCHEMA: dict[str, Any] = {
    "title": "string",
    "body": "string",
    "summary": "string",
    "image_brief": {
        "visual_style": "string",
        "cover": "string",
        "inline_images": ["string", "string"],
        "avoid": ["string"],
    },
}


def discover_hot_topic_candidates(state: WorkflowState) -> WorkflowState:
    if state.repository is not None:
        candidates = state.repository.list_top_hot_topics()
        if state.input.candidate_id:
            candidates = [item for item in candidates if item["id"] == state.input.candidate_id]
        if candidates:
            state.candidates = candidates
            return state

    state.candidates = [
        {
            "id": "mock-ai-teacher",
            "source_id": "mock-trends",
            "title": "AI tools for busy teachers",
            "url": "https://example.com/trends/teacher-ai",
            "summary": "Teachers want practical AI workflows that save prep time.",
            "signals": {"heat": 92, "growth": 28, "keywords": ["AI", "teacher"]},
            "score": 80,
            "risk_level": "low",
            "evidence": {"source_name": "Mock Trend Board", "access_method": "mock-public", "auth_type": "none"},
        }
    ]
    return state


def retrieve_graph_context(state: WorkflowState) -> WorkflowState:
    if state.repository is None:
        state.retrieved_assets = []
        return state
    state.retrieved_assets = GraphRAGService(state.repository).retrieve(state)
    return state


def rank_hot_topic_candidates(state: WorkflowState) -> WorkflowState:
    ranked = sorted(state.candidates, key=lambda item: item.get("score", 0), reverse=True)
    for candidate in ranked:
        candidate["rank_reason"] = f"score={candidate.get('score', 0)} risk={candidate.get('risk_level', 'unknown')}"
    state.candidates = ranked
    return state


def create_topic_cards(state: WorkflowState) -> WorkflowState:
    candidate = state.candidates[0]
    supporting_assets = state.retrieved_assets[:3]
    state.topics = [
        {
            "title": candidate["title"],
            "angle": "Turn the trend into a concrete audience pain-point solution.",
            "score": 100,
            "reason": candidate.get("summary", ""),
            "candidate_id": candidate.get("id"),
            "source_url": candidate.get("url", ""),
            "supporting_assets": supporting_assets,
        }
    ]
    return state


def prepare_topic_review_gate(state: WorkflowState) -> WorkflowState:
    if not state.topic_review:
        state.topic_review = {
            "status": "pending",
            "required": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "next_step": "等待确认选题角度",
        }
    return state


def apply_topic_review(state: WorkflowState, review: dict) -> WorkflowState:
    state.topic_review = {
        "approved": bool(review.get("approved")),
        "reviewer": review.get("reviewer", "human"),
        "comment": review.get("comment", ""),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    return state


def build_writer_messages(state: WorkflowState, topic: dict[str, Any], asset_section: str) -> list[dict[str, str]]:
    candidate = _candidate_for_topic(state, topic)
    user_prompt = (
        "请基于下面的已审批选题生成一篇自媒体草稿。\n\n"
        f"目标平台: {state.input.platform}\n"
        f"关键词: {', '.join(state.input.keywords) or '无'}\n\n"
        "选题信息:\n"
        f"- 标题: {topic.get('title', '')}\n"
        f"- 角度: {topic.get('angle', '')}\n"
        f"- 选题理由: {topic.get('reason', '')}\n"
        f"- 来源URL: {topic.get('source_url', '')}\n\n"
        "热点候选证据:\n"
        f"{_format_candidate(candidate)}\n\n"
        "Graph RAG 检索到的内部素材:\n"
        f"{asset_section}\n\n"
        "写作要求:\n"
        "- 给出能直接进入人工审批的完整草稿，不要只列大纲。\n"
        "- 结构要适合移动端阅读，段落短，给出明确操作建议。\n"
        "- 不复制外部原文表达，只抽象趋势、痛点、结构和关键词。\n"
        "- summary 用 1 句话概括全文，供审批页和生图 Agent 使用。\n"
        "- image_brief.cover 描述封面主视觉；inline_images 最多给 2 个正文配图方向。\n"
    )
    return [
        {"role": "system", "content": WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def parse_writer_result(content: str, topic: dict[str, Any], asset_section: str) -> dict[str, Any]:
    parsed = _loads_json_object(content)
    if not parsed:
        return _fallback_draft(topic, asset_section)
    draft = _fallback_draft(topic, asset_section)
    title = _clean_text(parsed.get("title"))
    body = _clean_text(parsed.get("body"))
    summary = _clean_text(parsed.get("summary"))
    image_brief = _normalize_image_brief(parsed.get("image_brief"), draft["image_brief"])
    if title:
        draft["title"] = title
    if body:
        draft["body"] = body
    if summary:
        draft["summary"] = summary
    draft["image_brief"] = image_brief
    return draft


def build_image_prompts_from_draft(draft: dict[str, Any], max_images: int = MAX_IMAGES_PER_ARTICLE) -> list[str]:
    title = _clean_text(draft.get("title")) or "未命名文章"
    body = _clean_text(draft.get("body"))
    summary = _clean_text(draft.get("summary")) or _summarize_text(body)
    image_brief = _normalize_image_brief(draft.get("image_brief"), _fallback_image_brief(title, summary))
    style = image_brief["visual_style"]
    avoid = ", ".join(image_brief.get("avoid", [])) or "copyrighted logos, celebrity likenesses, misleading claims"
    base_context = (
        f"Article title: {title}\n"
        f"Article summary: {summary}\n"
        f"Article body context: {_shorten(body, 700)}"
    )
    prompts = [
        (
            f"{IMAGE_SYSTEM_PROMPT}\n\n"
            f"{base_context}\n"
            f"Cover visual direction: {image_brief['cover']}\n"
            f"Style: {style}\n"
            f"Avoid: {avoid}\n"
            "Create one polished cover image prompt for a Chinese social-media article. "
            "No text-heavy layout unless it is a simple readable headline card."
        )
    ]
    for inline in image_brief["inline_images"]:
        prompts.append(
            (
                f"{IMAGE_SYSTEM_PROMPT}\n\n"
                f"{base_context}\n"
                f"Inline visual direction: {inline}\n"
                f"Style: {style}\n"
                f"Avoid: {avoid}\n"
                "Create one supporting image prompt that helps explain the article."
            )
        )
    return prompts[:max_images]


def _candidate_for_topic(state: WorkflowState, topic: dict[str, Any]) -> dict[str, Any] | None:
    candidate_id = topic.get("candidate_id")
    if not candidate_id:
        return state.candidates[0] if state.candidates else None
    for candidate in state.candidates:
        if candidate.get("id") == candidate_id:
            return candidate
    return None


def _format_candidate(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return "- No external candidate details available."
    evidence = candidate.get("evidence", {})
    signals = candidate.get("signals", {})
    return (
        f"- 标题: {candidate.get('title', '')}\n"
        f"- 摘要: {candidate.get('summary', '')}\n"
        f"- URL: {candidate.get('url', '')}\n"
        f"- 分数/风险: {candidate.get('score', 0)} / {candidate.get('risk_level', 'unknown')}\n"
        f"- 信号: {json.dumps(signals, ensure_ascii=False)}\n"
        f"- 来源证据: {json.dumps(evidence, ensure_ascii=False)}"
    )


def _loads_json_object(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fallback_draft(topic: dict[str, Any], asset_section: str) -> dict[str, Any]:
    title = _clean_text(topic.get("title")) or "Untitled topic"
    reason = _clean_text(topic.get("reason")) or "The audience is showing repeated interest in this topic."
    summary = f"围绕“{title}”给出一套可复制的实操流程，帮助读者从痛点进入行动。"
    return {
        "title": f"{title}: 3 practical ways to start",
        "body": (
            f"Hook: {title} is becoming a real audience question.\n\n"
            f"1. Start from the pain point: {reason}\n"
            "2. Ground the post in matched internal assets:\n"
            f"{asset_section}\n"
            "3. Give one simple workflow the reader can copy today.\n"
            "4. Close with a checklist and invite comments for the next example.\n\n"
            "CTA: Save this and comment with the scenario you want rewritten."
        ),
        "summary": summary,
        "image_brief": _fallback_image_brief(title, summary),
    }


def _fallback_image_brief(title: str, summary: str) -> dict[str, Any]:
    return {
        "visual_style": "clean editorial social media card, bright but restrained, readable composition",
        "cover": f"an editorial cover image showing the topic '{title}' through a practical work scene",
        "inline_images": [
            f"a three-step workflow diagram explaining: {summary}",
            "a concise checklist card with three actionable steps for the reader",
        ],
        "avoid": ["platform logos", "celebrity likeness", "medical/legal/financial guarantees"],
    }


def _normalize_image_brief(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return fallback
    visual_style = _clean_text(value.get("visual_style")) or fallback["visual_style"]
    cover = _clean_text(value.get("cover")) or fallback["cover"]
    inline_value = value.get("inline_images", [])
    inline_images = [_clean_text(item) for item in inline_value if _clean_text(item)] if isinstance(inline_value, list) else []
    avoid_value = value.get("avoid", [])
    avoid = [_clean_text(item) for item in avoid_value if _clean_text(item)] if isinstance(avoid_value, list) else []
    return {
        "visual_style": visual_style,
        "cover": cover,
        "inline_images": (inline_images or fallback["inline_images"])[: MAX_IMAGES_PER_ARTICLE - 1],
        "avoid": avoid or fallback["avoid"],
    }


def _summarize_text(text: str) -> str:
    return _shorten(" ".join(text.split()), 160) or "文章围绕热点选题提供可执行的方法和检查清单。"


def _shorten(text: str, max_length: int) -> str:
    compact = " ".join(_clean_text(text).split())
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 1].rstrip() + "..."


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


async def draft_post_with_llm(state: WorkflowState) -> WorkflowState:
    topic = state.topics[0]
    asset_lines = [asset["text"] for asset in topic.get("supporting_assets", [])]
    asset_section = "\n".join(f"- {line}" for line in asset_lines) if asset_lines else "- No matched internal asset yet."
    result = await LLMService().complete(
        "writing_agent",
        build_writer_messages(state, topic, asset_section),
        WRITER_RESPONSE_SCHEMA,
    )
    state.draft = parse_writer_result(result.get("content", ""), topic, asset_section)
    state.draft["topic"] = topic
    state.draft["writer_system_prompt"] = WRITER_SYSTEM_PROMPT
    return state


def prepare_human_review_gate(state: WorkflowState) -> WorkflowState:
    if not state.human_review:
        state.human_review = {
            "status": "pending",
            "required": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "next_step": "等待确认图文内容",
        }
    return state


def apply_human_review(state: WorkflowState, review: dict) -> WorkflowState:
    draft_patch = review.get("draft")
    if isinstance(draft_patch, dict):
        state.draft.update({key: value for key, value in draft_patch.items() if value is not None})
    state.human_review = {
        "approved": bool(review.get("approved")),
        "reviewer": review.get("reviewer", "human"),
        "comment": review.get("comment", ""),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    state.review = dict(state.human_review)
    return state


async def generate_images_for_draft(state: WorkflowState) -> WorkflowState:
    prompts = build_image_prompts_from_draft(state.draft, MAX_IMAGES_PER_ARTICLE)
    images = await ImageService().generate_batch(prompts)
    state.image_prompts = {
        "cover_prompt": prompts[0],
        "inline_prompts": prompts[1:],
        "mock_images": images,
        "image_count": len(prompts),
        "system_prompt": IMAGE_SYSTEM_PROMPT,
        "reviewed_by": state.human_review.get("reviewer", "human"),
    }
    return state
