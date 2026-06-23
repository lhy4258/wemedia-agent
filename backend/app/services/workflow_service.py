from __future__ import annotations

import json
import os
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.agents.tools import apply_human_review, apply_topic_review
from app.graph.langgraph_app import build_persistent_state_graph
from app.graph.state import WorkflowInput, WorkflowState
from app.graph.workflow import NODES, run_node
from app.models.workflow_record import MetricsSnapshot, WorkflowRecord
from app.services.hot_topic_scout_agent import HotTopicScoutAgent, SCOUT_SOURCE_ID
from app.services.publish_service import PublishService
from app.services.tracing_service import TracingService, finish_trace


class SqlWorkflowRepository:
    def __init__(self, database_url: str | None = None):
        url = database_url or settings.database_url
        if url == "sqlite:///:memory:":
            self.engine = create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self.engine = create_engine(url)
        self._init_schema()

    def list_records(self) -> list[WorkflowRecord]:
        rows = self._fetchall(
            """
            SELECT wr.id, wr.request_id, wr.persona_id, wr.status, wr.current_node,
                   wr.state_json, wr.error,
                   COALESCE(mc.token_in, 0) AS token_in,
                   COALESCE(mc.token_out, 0) AS token_out,
                   COALESCE(mc.latency_ms, 0) AS latency_ms,
                   COALESCE(mc.cost_estimate, 0) AS cost_estimate,
                   COALESCE(mc.error_count, 0) AS error_count
            FROM workflow_records wr
            LEFT JOIN metrics_context mc ON mc.workflow_id = wr.id
            ORDER BY wr.updated_at DESC, wr.created_at DESC
            """
        )
        return [self._record_from_row(row) for row in rows]

    def get_record(self, workflow_id: str) -> WorkflowRecord:
        row = self._fetchone(
            """
            SELECT wr.id, wr.request_id, wr.persona_id, wr.status, wr.current_node,
                   wr.state_json, wr.error,
                   COALESCE(mc.token_in, 0) AS token_in,
                   COALESCE(mc.token_out, 0) AS token_out,
                   COALESCE(mc.latency_ms, 0) AS latency_ms,
                   COALESCE(mc.cost_estimate, 0) AS cost_estimate,
                   COALESCE(mc.error_count, 0) AS error_count
            FROM workflow_records wr
            LEFT JOIN metrics_context mc ON mc.workflow_id = wr.id
            WHERE wr.id = :id
            """,
            {"id": workflow_id},
        )
        if row is None:
            raise KeyError(workflow_id)
        return self._record_from_row(row)

    def save_record(self, record: WorkflowRecord) -> None:
        state_json = json.dumps(record.state, ensure_ascii=False)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO workflow_records (id, request_id, persona_id, status, current_node, state_json, error)
                    VALUES (:id, :request_id, :persona_id, :status, :current_node, :state_json, :error)
                    ON CONFLICT(id) DO UPDATE SET
                      request_id = excluded.request_id,
                      persona_id = excluded.persona_id,
                      status = excluded.status,
                      current_node = excluded.current_node,
                      state_json = excluded.state_json,
                      error = excluded.error,
                      updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "id": record.id,
                    "request_id": record.request_id,
                    "persona_id": record.persona_id,
                    "status": record.status,
                    "current_node": record.current_node,
                    "state_json": state_json,
                    "error": record.error,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO metrics_context (
                      id, workflow_id, token_in, token_out, latency_ms, cost_estimate, error_count, model
                    ) VALUES (
                      :id, :workflow_id, :token_in, :token_out, :latency_ms, :cost_estimate, :error_count, :model
                    )
                    ON CONFLICT(id) DO UPDATE SET
                      workflow_id = excluded.workflow_id,
                      token_in = excluded.token_in,
                      token_out = excluded.token_out,
                      latency_ms = excluded.latency_ms,
                      cost_estimate = excluded.cost_estimate,
                      error_count = excluded.error_count,
                      model = excluded.model
                    """
                ),
                {
                    "id": f"metrics-{record.id}",
                    "workflow_id": record.id,
                    "token_in": record.metrics.token_in,
                    "token_out": record.metrics.token_out,
                    "latency_ms": record.metrics.latency_ms,
                    "cost_estimate": record.metrics.cost_estimate,
                    "error_count": record.metrics.error_count,
                    "model": "mock",
                },
            )

    def add_event(self, workflow_id: str, event: str, node: str, payload: dict[str, Any], latency_ms: int = 0) -> None:
        self._execute(
            """
            INSERT INTO workflow_events (id, workflow_id, node, event_type, payload, latency_ms)
            VALUES (:id, :workflow_id, :node, :event_type, :payload, :latency_ms)
            """,
            {
                "id": uuid.uuid4().hex,
                "workflow_id": workflow_id,
                "node": node,
                "event_type": event,
                "payload": json.dumps(payload, ensure_ascii=False),
                "latency_ms": latency_ms,
            },
        )

    def list_events(self, workflow_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT event_type, node, payload
            FROM workflow_events
            WHERE workflow_id = :workflow_id
            ORDER BY created_at ASC, id ASC
            """,
            {"workflow_id": workflow_id},
        )
        return [
            {"event": row["event_type"], "node": row["node"], "data": self._loads(row["payload"])}
            for row in rows
        ]

    def save_hot_topics(self, topics: list[dict[str, Any]]) -> None:
        if any(not topic.get("source_id") or topic.get("source_id") == "mock-trends" for topic in topics):
            self._ensure_mock_source()
        if any(topic.get("source_id") == SCOUT_SOURCE_ID for topic in topics):
            self._ensure_scout_source()
        with self.engine.begin() as conn:
            for topic in topics:
                conn.execute(
                    text(
                        """
                        INSERT INTO hot_topic_candidates (
                          id, source_id, title, url, summary, signals_json, score, risk_level, evidence_json
                        ) VALUES (
                          :id, :source_id, :title, :url, :summary, :signals_json, :score, :risk_level, :evidence_json
                        )
                        ON CONFLICT(id) DO UPDATE SET
                          source_id = excluded.source_id,
                          title = excluded.title,
                          url = excluded.url,
                          summary = excluded.summary,
                          signals_json = excluded.signals_json,
                          score = excluded.score,
                          risk_level = excluded.risk_level,
                          evidence_json = excluded.evidence_json,
                          collected_at = CURRENT_TIMESTAMP
                        """
                    ),
                    {
                        "id": topic["id"],
                        "source_id": topic.get("source_id", "mock-trends"),
                        "title": topic["title"],
                        "url": topic["url"],
                        "summary": topic.get("summary", ""),
                        "signals_json": json.dumps(topic.get("signals", {}), ensure_ascii=False),
                        "score": topic.get("score", 0),
                        "risk_level": topic.get("risk_level", "low"),
                        "evidence_json": json.dumps(topic.get("evidence", {}), ensure_ascii=False),
                    },
                )

    def list_top_hot_topics(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_hot_topics()[:limit]

    def list_hot_topics(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, source_id, title, url, summary, signals_json, score, risk_level, evidence_json, collected_at
            FROM hot_topic_candidates
            ORDER BY score DESC, collected_at DESC
            """
        )
        return [
            {
                "id": row["id"],
                "source_id": row["source_id"],
                "title": row["title"],
                "url": row["url"],
                "summary": row["summary"],
                "signals": self._loads(row["signals_json"]),
                "score": row["score"],
                "risk_level": row["risk_level"],
                "evidence": self._loads(row["evidence_json"]),
                "collected_at": str(row["collected_at"]),
            }
            for row in rows
        ]

    def delete_hot_topic(self, topic_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM hot_topic_candidates WHERE id = :id"),
                {"id": topic_id},
            )
        return bool(result.rowcount)

    def add_crawl_run(
        self,
        source_id: str,
        status: str,
        error: str | None = None,
        finished: bool = True,
    ) -> dict[str, Any]:
        run = {
            "id": uuid.uuid4().hex,
            "source_id": source_id,
            "status": status,
            "error": error,
            "finished_at": "CURRENT_TIMESTAMP" if finished else None,
        }
        finished_sql = "CURRENT_TIMESTAMP" if finished else "NULL"
        self._execute(
            f"""
            INSERT INTO crawl_runs (id, source_id, status, finished_at, error)
            VALUES (:id, :source_id, :status, {finished_sql}, :error)
            """,
            {
                "id": run["id"],
                "source_id": source_id,
                "status": status,
                "error": error,
            },
        )
        return run

    def list_crawl_runs(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, source_id, status, started_at, finished_at, error
            FROM crawl_runs
        """
        params: dict[str, Any] = {}
        if status:
            sql += " WHERE status = :status"
            params["status"] = status
        sql += " ORDER BY started_at ASC, id ASC"
        rows = self._fetchall(sql, params)
        return [
            {
                "id": row["id"],
                "source_id": row["source_id"],
                "status": row["status"],
                "started_at": str(row["started_at"]),
                "finished_at": str(row["finished_at"]) if row["finished_at"] else None,
                "error": row["error"],
            }
            for row in rows
        ]

    def should_skip_source(self, source: dict[str, Any]) -> bool:
        if int(source.get("rate_limit_seconds") or 0) <= 0:
            return False
        row = self._fetchone(
            """
            SELECT started_at
            FROM crawl_runs
            WHERE source_id = :source_id AND status = 'succeeded'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            {"source_id": source["id"]},
        )
        return row is not None

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, name, type, base_url, auth_mode, enabled, rate_limit_seconds, rules_json
            FROM external_sources
            ORDER BY id
            """
        )
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "base_url": row["base_url"],
                "auth_mode": row["auth_mode"],
                "enabled": bool(row["enabled"]),
                "rate_limit_seconds": row["rate_limit_seconds"],
                "rules": self._loads(row["rules_json"]),
            }
            for row in rows
        ]

    def save_source(self, source: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": source.get("id") or uuid.uuid4().hex,
            "name": source["name"],
            "type": source.get("type", "web"),
            "base_url": source["base_url"],
            "auth_mode": source.get("auth_mode", "public"),
            "enabled": source.get("enabled", True),
            "rate_limit_seconds": source.get("rate_limit_seconds", source.get("rate_limit", 300)),
            "rules": source.get("rules", source.get("rules_json", {})),
        }
        self._execute(
            """
            INSERT INTO external_sources (id, name, type, base_url, auth_mode, enabled, rate_limit_seconds, rules_json)
            VALUES (:id, :name, :type, :base_url, :auth_mode, :enabled, :rate_limit_seconds, :rules_json)
            ON CONFLICT(id) DO UPDATE SET
              name = excluded.name,
              type = excluded.type,
              base_url = excluded.base_url,
              auth_mode = excluded.auth_mode,
              enabled = excluded.enabled,
              rate_limit_seconds = excluded.rate_limit_seconds,
              rules_json = excluded.rules_json
            """,
            {
                "id": item["id"],
                "name": item["name"],
                "type": item["type"],
                "base_url": item["base_url"],
                "auth_mode": item["auth_mode"],
                "enabled": item["enabled"],
                "rate_limit_seconds": item["rate_limit_seconds"],
                "rules_json": json.dumps(item["rules"], ensure_ascii=False),
            },
        )
        return item

    def save_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": asset.get("id") or uuid.uuid4().hex,
            "type": asset["type"],
            "title": asset["title"],
            "text": asset["text"],
            "tags": asset.get("tags", []),
            "source": asset.get("source", "manual"),
            "license": asset.get("license", "internal"),
        }
        self._execute(
            """
            INSERT INTO content_assets (id, type, title, text, tags, source, license)
            VALUES (:id, :type, :title, :text, :tags, :source, :license)
            ON CONFLICT(id) DO UPDATE SET
              type = excluded.type,
              title = excluded.title,
              text = excluded.text,
              tags = excluded.tags,
              source = excluded.source,
              license = excluded.license
            """,
            {
                "id": item["id"],
                "type": item["type"],
                "title": item["title"],
                "text": item["text"],
                "tags": json.dumps(item["tags"], ensure_ascii=False),
                "source": item["source"],
                "license": item["license"],
            },
        )
        return item

    def list_assets(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, type, title, text, tags, source, license, embedding
            FROM content_assets
            ORDER BY title ASC, id ASC
            """
        )
        return [
            {
                "id": row["id"],
                "type": row["type"],
                "title": row["title"],
                "text": row["text"],
                "tags": self._loads(row["tags"]),
                "source": row["source"],
                "license": row["license"],
                "embedding": self._loads(row["embedding"]) if row.get("embedding") else None,
            }
            for row in rows
        ]

    def search_assets(
        self,
        query_terms: list[str],
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        if self.engine.dialect.name != "sqlite" and query_embedding:
            return self._search_assets_pgvector(query_terms, limit, query_embedding)
        assets = self.list_assets()
        terms = [term.casefold() for term in query_terms if term]
        scored = []
        for asset in assets:
            haystack = f"{asset['title']} {asset['text']} {' '.join(asset['tags'])}".casefold()
            score = sum(1 for term in terms if term and term in haystack)
            if query_embedding and asset.get("embedding"):
                score += _dot_product(query_embedding, asset["embedding"])
            if score:
                item = dict(asset)
                item["match_score"] = score
                scored.append(item)
        return sorted(scored, key=lambda item: item["match_score"], reverse=True)[:limit]

    def _search_assets_pgvector(
        self,
        query_terms: list[str],
        limit: int,
        query_embedding: list[float],
    ) -> list[dict[str, Any]]:
        terms = [term.casefold() for term in query_terms if term]
        query_text = " ".join(terms)
        vector = _fit_embedding_dimension(query_embedding, settings.embed_dimension)
        rows = self._fetchall(
            """
            SELECT id, type, title, text, tags, source, license, embedding,
                   (1.0 / (1.0 + (embedding <=> CAST(:query_embedding AS vector)))) AS match_score
            FROM content_assets
            WHERE embedding IS NOT NULL
              AND (
                :query_text = ''
                OR lower(title || ' ' || text || ' ' || tags::text) LIKE :like_query
              )
            ORDER BY embedding <=> CAST(:query_embedding AS vector)
            LIMIT :limit
            """,
            {
                "query_embedding": _pgvector_literal(vector),
                "query_text": query_text,
                "like_query": f"%{terms[0]}%" if terms else "%",
                "limit": limit,
            },
        )
        return [
            {
                "id": row["id"],
                "type": row["type"],
                "title": row["title"],
                "text": row["text"],
                "tags": self._loads(row["tags"]),
                "source": row["source"],
                "license": row["license"],
                "embedding": row["embedding"],
                "match_score": row["match_score"],
            }
            for row in rows
        ]

    def save_asset_embedding(self, asset_id: str, embedding: list[float]) -> None:
        stored_embedding = embedding
        if self.engine.dialect.name != "sqlite":
            stored_embedding = _fit_embedding_dimension(embedding, settings.embed_dimension)
        value = json.dumps(stored_embedding)
        if self.engine.dialect.name != "sqlite":
            value = "[" + ",".join(str(item) for item in stored_embedding) + "]"
        self._execute(
            "UPDATE content_assets SET embedding = :embedding WHERE id = :id",
            {"id": asset_id, "embedding": value},
        )

    def add_ai_call_log(
        self,
        workflow_id: str,
        node: str,
        model: str,
        token_in: int = 0,
        token_out: int = 0,
        latency_ms: int = 0,
        error: str | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO ai_call_logs (id, workflow_id, node, model, token_in, token_out, latency_ms, error)
            VALUES (:id, :workflow_id, :node, :model, :token_in, :token_out, :latency_ms, :error)
            """,
            {
                "id": uuid.uuid4().hex,
                "workflow_id": workflow_id,
                "node": node,
                "model": model,
                "token_in": token_in,
                "token_out": token_out,
                "latency_ms": latency_ms,
                "error": error,
            },
        )

    def list_ai_call_logs(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, workflow_id, node, model, token_in, token_out, latency_ms, error, created_at
            FROM ai_call_logs
        """
        params: dict[str, Any] = {}
        if workflow_id:
            sql += " WHERE workflow_id = :workflow_id"
            params["workflow_id"] = workflow_id
        sql += " ORDER BY created_at ASC, id ASC"
        rows = self._fetchall(sql, params)
        return [
            {
                "id": row["id"],
                "workflow_id": row["workflow_id"],
                "node": row["node"],
                "model": row["model"],
                "token_in": row["token_in"],
                "token_out": row["token_out"],
                "latency_ms": row["latency_ms"],
                "error": row["error"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def save_generated_post(self, workflow_id: str, state: WorkflowState) -> dict[str, Any]:
        item = {
            "id": f"post-{workflow_id}",
            "workflow_id": workflow_id,
            "title": state.draft.get("title", ""),
            "body": state.draft.get("body", ""),
            "image_prompts": state.image_prompts,
            "review": state.review,
        }
        self._execute(
            """
            INSERT INTO generated_posts (id, workflow_id, title, body, image_prompts, review_json)
            VALUES (:id, :workflow_id, :title, :body, :image_prompts, :review_json)
            ON CONFLICT(id) DO UPDATE SET
              title = excluded.title,
              body = excluded.body,
              image_prompts = excluded.image_prompts,
              review_json = excluded.review_json
            """,
            {
                "id": item["id"],
                "workflow_id": item["workflow_id"],
                "title": item["title"],
                "body": item["body"],
                "image_prompts": json.dumps(item["image_prompts"], ensure_ascii=False),
                "review_json": json.dumps(item["review"], ensure_ascii=False),
            },
        )
        return item

    def list_generated_posts(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, workflow_id, title, body, image_prompts, review_json, created_at
            FROM generated_posts
        """
        params: dict[str, Any] = {}
        if workflow_id:
            sql += " WHERE workflow_id = :workflow_id"
            params["workflow_id"] = workflow_id
        sql += " ORDER BY created_at DESC, id DESC"
        rows = self._fetchall(sql, params)
        return [
            {
                "id": row["id"],
                "workflow_id": row["workflow_id"],
                "title": row["title"],
                "body": row["body"],
                "image_prompts": self._loads(row["image_prompts"]),
                "review": self._loads(row["review_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def save_publish_job(self, job: dict[str, Any]) -> dict[str, Any]:
        self._execute(
            """
            INSERT INTO publish_jobs (
              id, workflow_id, post_id, platform, mode, status, external_media_id,
              publish_id, article_id, article_url, request_json, response_json, error
            ) VALUES (
              :id, :workflow_id, :post_id, :platform, :mode, :status, :external_media_id,
              :publish_id, :article_id, :article_url, :request_json, :response_json, :error
            )
            ON CONFLICT(id) DO UPDATE SET
              status = excluded.status,
              external_media_id = excluded.external_media_id,
              publish_id = excluded.publish_id,
              article_id = excluded.article_id,
              article_url = excluded.article_url,
              request_json = excluded.request_json,
              response_json = excluded.response_json,
              error = excluded.error,
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "id": job["id"],
                "workflow_id": job["workflow_id"],
                "post_id": job["post_id"],
                "platform": job["platform"],
                "mode": job["mode"],
                "status": job["status"],
                "external_media_id": job.get("external_media_id"),
                "publish_id": job.get("publish_id"),
                "article_id": job.get("article_id"),
                "article_url": job.get("article_url"),
                "request_json": json.dumps(job.get("request", {}), ensure_ascii=False),
                "response_json": json.dumps(job.get("response", {}), ensure_ascii=False),
                "error": job.get("error"),
            },
        )
        return job

    def list_publish_jobs(self, workflow_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, workflow_id, post_id, platform, mode, status, external_media_id,
                   publish_id, article_id, article_url, request_json, response_json,
                   error, created_at, updated_at
            FROM publish_jobs
            WHERE workflow_id = :workflow_id
            ORDER BY updated_at DESC, created_at DESC, id DESC
            """,
            {"workflow_id": workflow_id},
        )
        return [
            {
                "id": row["id"],
                "workflow_id": row["workflow_id"],
                "post_id": row["post_id"],
                "platform": row["platform"],
                "mode": row["mode"],
                "status": row["status"],
                "external_media_id": row["external_media_id"],
                "publish_id": row["publish_id"],
                "article_id": row["article_id"],
                "article_url": row["article_url"],
                "request": self._loads(row["request_json"]),
                "response": self._loads(row["response_json"]),
                "error": row["error"],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def delete_workflow(self, workflow_id: str) -> None:
        for table in ("publish_jobs", "generated_posts", "workflow_events", "metrics_context", "ai_call_logs"):
            self._execute(f"DELETE FROM {table} WHERE workflow_id = :workflow_id", {"workflow_id": workflow_id})
        self._execute("DELETE FROM workflow_records WHERE id = :workflow_id", {"workflow_id": workflow_id})

    def _record_from_row(self, row: dict[str, Any]) -> WorkflowRecord:
        return WorkflowRecord(
            id=row["id"],
            request_id=row["request_id"],
            persona_id=row["persona_id"],
            status=row["status"],
            current_node=row["current_node"],
            state=self._loads(row["state_json"]),
            metrics=MetricsSnapshot(
                token_in=row["token_in"],
                token_out=row["token_out"],
                latency_ms=row["latency_ms"],
                cost_estimate=float(row["cost_estimate"]),
                error_count=row["error_count"],
            ),
            error=row["error"],
        )

    def _init_schema(self) -> None:
        if self.engine.dialect.name == "sqlite":
            self._execute_script(SQLITE_SCHEMA)
            return
        self._execute_script(_postgres_schema())

    def _ensure_mock_source(self) -> None:
        self.save_source(
            {
                "id": "mock-trends",
                "name": "Mock Trend Board",
                "type": "mock",
                "base_url": "https://example.com/trends",
                "auth_mode": "public",
                "enabled": True,
                "rate_limit_seconds": 300,
                "rules": {"robots": "respect", "copy_policy": "summarize_only"},
            }
        )

    def _ensure_scout_source(self) -> None:
        self.save_source(
            {
                "id": SCOUT_SOURCE_ID,
                "name": "热点搜查Agent",
                "type": "agent",
                "base_url": "agent://hot-topic-scout",
                "auth_mode": "public",
                "enabled": True,
                "rate_limit_seconds": 0,
                "rules": {
                    "tools": ["browser-search", "firecrawl", "source-adapter"],
                    "copy_policy": "summarize_only",
                },
            }
        )

    def _execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(sql), params or {})

    def _execute_script(self, sql: str) -> None:
        statements = [item.strip() for item in sql.split(";") if item.strip()]
        with self.engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

    def _fetchone(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(text(sql), params or {}).mappings().fetchone()
        return dict(row) if row else None

    def _fetchall(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(text(sql), params or {}).mappings().fetchall()
        return [dict(row) for row in rows]

    def _loads(self, value: Any) -> dict[str, Any] | list[Any]:
        if value is None:
            return {}
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)


def build_mock_hot_topics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = payload.get("keywords") or ["AI", "teacher"]
    keyword_text = " ".join(keywords)
    return [
        {
            "id": f"mock-{payload.get('platform', 'platform')}",
            "source_id": "mock-trends",
            "title": f"{keyword_text}: 3 个正在升温的内容角度",
            "url": "https://example.com/trends/mock-wemedia",
            "summary": "公开趋势信号显示，用户更关心可复制的流程、真实案例和低风险上手路径。",
            "signals": {"heat": 92, "growth": 28, "platform_fit": 86, "material_fit": 80},
            "score": 91.5,
            "risk_level": "low",
            "evidence": {"source_name": "Mock Trend Board", "access_method": "mock-public", "auth_type": "none"},
        }
    ]


def _dot_product(left: list[float], right: list[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _fit_embedding_dimension(embedding: list[float], dimension: int) -> list[float]:
    if len(embedding) >= dimension:
        return embedding[:dimension]
    return [*embedding, *([0.0] * (dimension - len(embedding)))]


def _pgvector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(item)) for item in embedding) + "]"


def _state_summary(state: WorkflowState) -> dict[str, Any]:
    return {
        "platform": state.input.platform,
        "keyword_count": len(state.input.keywords),
        "candidate_count": len(state.candidates),
        "asset_count": len(state.retrieved_assets),
        "topic_count": len(state.topics),
        "has_draft": bool(state.draft),
        "has_images": bool(state.image_prompts),
        "topic_review_status": state.topic_review.get("status") or state.topic_review.get("approved"),
        "human_review_status": state.human_review.get("status") or state.human_review.get("approved"),
    }


class WorkflowService:
    def __init__(
        self,
        repository: SqlWorkflowRepository | None = None,
        tracing: TracingService | None = None,
        scout_agent: HotTopicScoutAgent | None = None,
        publisher: Any | None = None,
    ):
        self.repository = repository or SqlWorkflowRepository(os.getenv("DATABASE_URL", settings.database_url))
        self.tracing = tracing or TracingService()
        self.scout_agent = scout_agent or HotTopicScoutAgent()
        self.publish_service = PublishService(self.repository, publisher=publisher)
        self.state_graph = None
        self.checkpointer_status = {"status": "disabled", "reason": "sqlite or mock checkpointer"}
        if not settings.checkpointer_mock and self.repository.engine.dialect.name != "sqlite":
            try:
                engine_url = self.repository.engine.url
                database_url = (
                    engine_url.render_as_string(hide_password=False)
                    if hasattr(engine_url, "render_as_string")
                    else str(engine_url)
                )
                self.state_graph = build_persistent_state_graph(database_url)
                self.checkpointer_status = {"status": "enabled", "type": "postgres"}
            except RuntimeError as exc:
                self.checkpointer_status = {"status": "unavailable", "reason": str(exc)}

    async def start(self, workflow_input: WorkflowInput) -> WorkflowRecord:
        record = WorkflowRecord(
            id=uuid.uuid4().hex,
            request_id=uuid.uuid4().hex,
            persona_id=workflow_input.persona_id,
            status="running",
            current_node="topic_review",
            state={"input": asdict(workflow_input)},
        )
        self.repository.save_record(record)
        with self.tracing.workflow(
            "media_agent_workflow",
            inputs={"input": asdict(workflow_input)},
            metadata={
                "workflow_id": record.id,
                "platform": workflow_input.platform,
                "candidate_id": workflow_input.candidate_id,
            },
        ) as run:
            result = self._snapshot(
                await self._run(record, WorkflowState(input=workflow_input, repository=self.repository), "topic_review")
            )
            finish_trace(run, {"status": result.status, "current_node": result.current_node})
            return result

    def list(self) -> list[WorkflowRecord]:
        return [self._snapshot(record) for record in self.repository.list_records()]

    def get(self, workflow_id: str) -> WorkflowRecord:
        return self._snapshot(self.repository.get_record(workflow_id))

    async def retry(self, workflow_id: str, from_node: str) -> WorkflowRecord:
        record = self.repository.get_record(workflow_id)
        state = self._state_from_record(record, clear_simulated_failure=True)
        record.status = "running"
        record.error = None
        self.repository.save_record(record)
        return self._snapshot(await self._run(record, state, from_node))

    async def topic_review(self, workflow_id: str, payload: dict[str, Any]) -> WorkflowRecord:
        record = self.repository.get_record(workflow_id)
        state = self._state_from_record(record, clear_simulated_failure=True)
        state = apply_topic_review(state, payload)
        self._save_state(record, state)
        self._event(record.id, "topic_review", "topic_review", state.topic_review)
        if not state.topic_review.get("approved"):
            record.status = "candidate_returned"
            record.current_node = "candidate"
            self.repository.save_record(record)
            return self._snapshot(record)

        record.status = "running"
        record.current_node = "writing_agent"
        record.error = None
        self.repository.save_record(record)
        return self._snapshot(await self._run(record, state, "writing_agent"))

    async def human_review(self, workflow_id: str, payload: dict[str, Any]) -> WorkflowRecord:
        record = self.repository.get_record(workflow_id)
        state = self._state_from_record(record, clear_simulated_failure=True)
        state = apply_human_review(state, payload)
        self._save_state(record, state)
        self._event(record.id, "human_review", "final_review", state.human_review)
        if not state.human_review.get("approved"):
            record.status = "image_generation"
            record.current_node = "image_agent"
            self.repository.save_record(record)
            return self._snapshot(record)

        record.status = "running"
        record.current_node = "finalize"
        record.error = None
        self.repository.save_record(record)
        return self._snapshot(await self._run(record, state, "finalize"))

    def pause(self, workflow_id: str, payload: dict[str, Any]) -> WorkflowRecord:
        record = self.repository.get_record(workflow_id)
        state = self._state_from_record(record)
        state.review["paused"] = {
            "reason": payload.get("reason", ""),
            "operator": payload.get("operator", "operator"),
        }
        self._save_state(record, state)
        record.status = "paused"
        self.repository.save_record(record)
        self._event(record.id, "paused", record.current_node, state.review["paused"])
        return self._snapshot(record)

    def return_to_previous(self, workflow_id: str, payload: dict[str, Any]) -> WorkflowRecord:
        record = self.repository.get_record(workflow_id)
        state = self._state_from_record(record)
        decision = {
            "operator": payload.get("operator", "operator"),
            "comment": payload.get("comment", ""),
            "from_status": record.status,
        }
        state.review["returned"] = decision
        if record.status == "publish_ready":
            record.status = "final_review"
            record.current_node = "final_review"
            state.human_review["status"] = "returned"
            state.human_review["comment"] = decision["comment"]
            state.human_review["approved"] = False
        elif record.status == "final_review":
            record.status = "image_generation"
            record.current_node = "image_agent"
            state.human_review["status"] = "returned"
            state.human_review["comment"] = decision["comment"]
            state.human_review["approved"] = False
        elif record.status == "topic_review":
            record.status = "candidate_returned"
            record.current_node = "candidate"
            state.topic_review["status"] = "returned"
            state.topic_review["comment"] = decision["comment"]
            state.topic_review["approved"] = False
        else:
            record.status = "paused"
        self._save_state(record, state)
        self.repository.save_record(record)
        self._event(record.id, "returned", record.current_node, decision)
        return self._snapshot(record)

    def publish(self, workflow_id: str, payload: dict[str, Any]) -> WorkflowRecord:
        record = self.repository.get_record(workflow_id)
        state = self._state_from_record(record)
        job = self.publish_service.publish(workflow_id, payload)
        state.review["publish"] = {
            "operator": payload.get("operator", "operator"),
            "comment": payload.get("comment", ""),
            "platform": job["platform"],
            "mode": job["mode"],
            "status": job["status"],
            "external_media_id": job.get("external_media_id"),
            "publish_id": job.get("publish_id"),
            "article_id": job.get("article_id"),
            "article_url": job.get("article_url"),
            "error": job.get("error"),
        }
        self._save_state(record, state)
        if job["status"] == "published":
            record.status = "published"
            record.current_node = "published"
        else:
            record.status = "publish_ready"
            record.current_node = "publish_ready"
        self.repository.save_record(record)
        event = "published" if job["status"] == "published" else "publish_job"
        self._event(record.id, event, record.current_node, state.review["publish"])
        return self._snapshot(record)

    def delete(self, workflow_id: str) -> dict[str, Any]:
        self.repository.delete_workflow(workflow_id)
        return {"deleted": True, "workflow_id": workflow_id}

    def stream_events(self, workflow_id: str):
        yield from self.repository.list_events(workflow_id)

    def refresh_hot_topics(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self.repository._ensure_scout_source()
        sources = self.repository.list_sources()
        if not sources:
            self.repository._ensure_mock_source()
            sources = self.repository.list_sources()
        usable_sources = []
        for source in sources:
            if source["id"] == SCOUT_SOURCE_ID or not source["enabled"]:
                continue
            if self.repository.should_skip_source(source):
                self.repository.add_crawl_run(source["id"], "skipped", "rate limit")
                continue
            usable_sources.append(source)
        topics = self.scout_agent.research(payload, usable_sources)
        source_statuses = getattr(self.scout_agent, "last_source_statuses", {}) or {}
        for source in usable_sources:
            result = source_statuses.get(source["id"], {"status": "succeeded", "error": None})
            self.repository.add_crawl_run(source["id"], result["status"], result.get("error"))
        self.repository.add_crawl_run(SCOUT_SOURCE_ID, "succeeded")
        self.repository.save_hot_topics(topics)
        return topics

    def list_hot_topics(self) -> list[dict[str, Any]]:
        return self.repository.list_hot_topics()

    def delete_hot_topic(self, topic_id: str) -> dict[str, Any]:
        return {"deleted": self.repository.delete_hot_topic(topic_id), "id": topic_id}

    def list_crawl_runs(self) -> list[dict[str, Any]]:
        return self.repository.list_crawl_runs()

    def list_sources(self) -> list[dict[str, Any]]:
        sources = self.repository.list_sources()
        if sources:
            return sources
        return [
            {
                "id": "mock-trends",
                "name": "Mock Trend Board",
                "type": "mock",
                "base_url": "https://example.com/trends",
                "auth_mode": "public",
                "enabled": True,
                "rate_limit_seconds": 300,
                "rules": {"robots": "respect", "copy_policy": "summarize_only"},
            }
        ]

    def save_source(self, source: dict[str, Any]) -> dict[str, Any]:
        return self.repository.save_source(source)

    def save_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.repository.save_asset(asset)

    def list_assets(self) -> list[dict[str, Any]]:
        return self.repository.list_assets()

    def list_generated_posts(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_generated_posts(workflow_id)

    def list_publish_jobs(self, workflow_id: str) -> list[dict[str, Any]]:
        return self.repository.list_publish_jobs(workflow_id)

    async def _run(self, record: WorkflowRecord, state: WorkflowState, start_node: str) -> WorkflowRecord:
        try:
            for node in NODES[NODES.index(start_node) :]:
                started = time.perf_counter()
                record.current_node = node
                self.repository.save_record(record)
                self._event(record.id, "node_start", node, {})
                if state.input.simulate_fail_at == node:
                    raise RuntimeError(f"simulated failure at {node}")
                with self.tracing.node(
                    node,
                    inputs={"state": _state_summary(state)},
                    metadata={"workflow_id": record.id, "status": record.status},
                ) as run:
                    state = await run_node(node, state)
                    finish_trace(run, {"state": _state_summary(state), "current_node": node})
                self._save_state(record, state)
                if node in {"writing_agent", "image_agent"}:
                    self.repository.add_ai_call_log(
                        record.id,
                        node,
                        "mock",
                        token_in=len(json.dumps(record.state, ensure_ascii=False).split()),
                        token_out=len(json.dumps({"draft": state.draft, "image_prompts": state.image_prompts}, ensure_ascii=False).split()),
                    )
                self._event(record.id, "node_end", node, {"latency_ms": int((time.perf_counter() - started) * 1000)})
                if node == "topic_review" and not state.topic_review.get("approved"):
                    record.status = "topic_review"
                    record.current_node = "topic_review"
                    self.repository.save_record(record)
                    return record
                if node == "final_review" and not state.human_review.get("approved"):
                    record.status = "final_review"
                    record.current_node = "final_review"
                    self.repository.save_record(record)
                    return record
            record.status = "publish_ready"
            record.current_node = "publish_ready"
            record.metrics = MetricsSnapshot(
                token_in=220,
                token_out=len(state.draft.get("body", "").split()),
                latency_ms=80,
                cost_estimate=0.0002,
            )
            self.repository.save_generated_post(record.id, state)
            self.repository.save_record(record)
            return record
        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            record.error = str(exc)
            record.metrics.error_count += 1
            self.repository.save_record(record)
            self._event(record.id, "error", record.current_node, {"error": str(exc)})
            return record

    def _save_state(self, record: WorkflowRecord, state: WorkflowState) -> None:
        record.state = {
            "input": asdict(state.input),
            "candidates": state.candidates,
            "retrieved_assets": state.retrieved_assets,
            "topics": state.topics,
            "topic_review": state.topic_review,
            "draft": state.draft,
            "image_prompts": state.image_prompts,
            "human_review": state.human_review,
            "review": state.review,
        }
        self.repository.save_record(record)

    def _state_from_record(self, record: WorkflowRecord, clear_simulated_failure: bool = False) -> WorkflowState:
        payload = dict(record.state["input"])
        if clear_simulated_failure:
            payload["simulate_fail_at"] = None
        state = WorkflowState(input=WorkflowInput(**payload), repository=self.repository)
        state.candidates = record.state.get("candidates", [])
        state.retrieved_assets = record.state.get("retrieved_assets", [])
        state.topics = record.state.get("topics", [])
        state.topic_review = record.state.get("topic_review", {})
        state.draft = record.state.get("draft", {})
        state.image_prompts = record.state.get("image_prompts", {})
        state.human_review = record.state.get("human_review", {})
        state.review = record.state.get("review", {})
        return state

    def _event(self, workflow_id: str, event: str, node: str, payload: dict[str, Any]) -> None:
        self.repository.add_event(workflow_id, event, node, payload)

    def _snapshot(self, record: WorkflowRecord) -> WorkflowRecord:
        return WorkflowRecord(
            id=record.id,
            request_id=record.request_id,
            persona_id=record.persona_id,
            status=record.status,
            current_node=record.current_node,
            state=deepcopy(record.state),
            metrics=deepcopy(record.metrics),
            error=record.error,
        )


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_records (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL UNIQUE,
  persona_id TEXT NOT NULL,
  status TEXT NOT NULL,
  current_node TEXT NOT NULL,
  state_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  error TEXT
);
CREATE TABLE IF NOT EXISTS workflow_events (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  node TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  latency_ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS metrics_context (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL UNIQUE,
  token_in INTEGER NOT NULL DEFAULT 0,
  token_out INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  cost_estimate REAL NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  model TEXT NOT NULL DEFAULT 'mock'
);
CREATE TABLE IF NOT EXISTS external_sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  base_url TEXT NOT NULL,
  auth_mode TEXT NOT NULL DEFAULT 'public',
  enabled INTEGER NOT NULL DEFAULT 1,
  rate_limit_seconds INTEGER NOT NULL DEFAULT 300,
  rules_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS content_assets (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT 'manual',
  license TEXT NOT NULL DEFAULT 'internal',
  embedding TEXT
);
CREATE TABLE IF NOT EXISTS crawl_runs (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  error TEXT
);
CREATE TABLE IF NOT EXISTS hot_topic_candidates (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  signals_json TEXT NOT NULL DEFAULT '{}',
  score REAL NOT NULL DEFAULT 0,
  risk_level TEXT NOT NULL DEFAULT 'low',
  collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS generated_posts (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  image_prompts TEXT NOT NULL DEFAULT '{}',
  review_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publish_jobs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  post_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  external_media_id TEXT,
  publish_id TEXT,
  article_id TEXT,
  article_url TEXT,
  request_json TEXT NOT NULL DEFAULT '{}',
  response_json TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ai_call_logs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT,
  node TEXT NOT NULL,
  model TEXT NOT NULL,
  token_in INTEGER NOT NULL DEFAULT 0,
  token_out INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_records (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL UNIQUE,
  persona_id TEXT NOT NULL,
  status TEXT NOT NULL,
  current_node TEXT NOT NULL,
  state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  error TEXT
);
CREATE TABLE IF NOT EXISTS workflow_events (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflow_records(id) ON DELETE CASCADE,
  node TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS metrics_context (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL UNIQUE REFERENCES workflow_records(id) ON DELETE CASCADE,
  token_in INTEGER NOT NULL DEFAULT 0,
  token_out INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  cost_estimate NUMERIC(12,6) NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  model TEXT NOT NULL DEFAULT 'mock'
);
CREATE TABLE IF NOT EXISTS external_sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  base_url TEXT NOT NULL,
  auth_mode TEXT NOT NULL DEFAULT 'public',
  enabled BOOLEAN NOT NULL DEFAULT true,
  rate_limit_seconds INTEGER NOT NULL DEFAULT 300,
  rules_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS content_assets (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  source TEXT NOT NULL DEFAULT 'manual',
  license TEXT NOT NULL DEFAULT 'internal',
  embedding vector(__EMBED_DIMENSION__)
);
CREATE TABLE IF NOT EXISTS crawl_runs (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES external_sources(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  error TEXT
);
CREATE TABLE IF NOT EXISTS hot_topic_candidates (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES external_sources(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  signals_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  score DOUBLE PRECISION NOT NULL DEFAULT 0,
  risk_level TEXT NOT NULL DEFAULT 'low',
  collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS generated_posts (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflow_records(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  image_prompts JSONB NOT NULL DEFAULT '{}'::jsonb,
  review_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS publish_jobs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflow_records(id) ON DELETE CASCADE,
  post_id TEXT NOT NULL REFERENCES generated_posts(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  external_media_id TEXT,
  publish_id TEXT,
  article_id TEXT,
  article_url TEXT,
  request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ai_call_logs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT REFERENCES workflow_records(id) ON DELETE SET NULL,
  node TEXT NOT NULL,
  model TEXT NOT NULL,
  token_in INTEGER NOT NULL DEFAULT 0,
  token_out INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _postgres_schema() -> str:
    return POSTGRES_SCHEMA.replace("__EMBED_DIMENSION__", str(settings.embed_dimension))
