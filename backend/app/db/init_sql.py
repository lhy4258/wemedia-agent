from __future__ import annotations

from app.core.config import settings


def build_init_sql() -> str:
    sql = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS content_assets (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  source TEXT NOT NULL DEFAULT 'seed',
  license TEXT NOT NULL DEFAULT 'internal',
  embedding vector(__EMBED_DIMENSION__)
);

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

CREATE TABLE IF NOT EXISTS metrics_context (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflow_records(id) ON DELETE CASCADE,
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
    return sql.replace("__EMBED_DIMENSION__", str(settings.embed_dimension)).strip()
