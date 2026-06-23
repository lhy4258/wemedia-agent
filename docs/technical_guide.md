# 自媒体 Agent 技术使用文档

本文档说明 `demo2` 当前真实可用的后端、前端、数据库、工作流、Agent、Graph RAG、热点采集和启动方式。

## 1. 当前定位

`demo2` 是一个自媒体内容运营 Agent MVP。系统从外部热点候选和内部素材库出发，经过选题审批、写作、生图、终审和微信公众号草稿/发布，最终形成可发布的图文内容包。

当前主流程：

```text
topic_review -> writing_agent -> image_agent -> final_review -> finalize
```

当前技术栈：

| 模块 | 技术 | 说明 |
| --- | --- | --- |
| 前端 | Vue 3 + Vite | 运营流程看板、审批页、草稿和图片 prompt 展示。 |
| 后端 | FastAPI | 业务 API、SSE、工作流入口。 |
| 工作流 | LangGraph | 编排 `topic_review -> writing_agent -> image_agent -> final_review -> finalize`。 |
| 业务持久化 | SQLAlchemy + PostgreSQL | 保存 workflow、热点、素材、内容包和审计记录。 |
| 向量检索 | pgvector | 保存和检索 `content_assets.embedding`。 |
| 模型服务 | OpenAI-compatible HTTP | LLM、embedding、image 都走可配置 base URL。 |
| 观测 | LangSmith + structlog | 可选 trace，不影响业务落库。 |

当前有一个热点搜查 Agent 和两个内容生产 Agent：

| Agent | 文件 | 职责 |
| --- | --- | --- |
| `HotTopicScoutAgent` | `backend/app/services/hot_topic_scout_agent.py` | 响应“按关键词搜热点 / 自动搜热点”，调用 browser-search、Firecrawl 和 source-adapter 工具生成候选池。它不进入前端流程栏。 |
| `WritingAgent` | `backend/app/agents/writing_agent.py` | 从候选池读取热点，执行 Graph RAG 检索、候选排序、选题生成、正文起草。 |
| `ImageAgent` | `backend/app/agents/image_agent.py` | 基于草稿正文、摘要和配图简报生成图片 prompt。 |

## 2. 运行配置

### 2.1 端口

| 服务 | 地址 |
| --- | --- |
| 前端 Vite | `http://127.0.0.1:5173` |
| 后端 FastAPI | `http://127.0.0.1:8000` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

`frontend/vite.config.js` 已配置 `/api` 代理到 `http://127.0.0.1:8000`，所以前端只需要调用 `/api/v1/media-agent/...`。`frontend/src/api.js` 是前端请求封装，负责统一拼接 `/api/v1/media-agent`；`vite.config.js` 只负责开发环境跨端口代理。

### 2.2 Python 环境

后端使用项目自己的虚拟环境：

```text
backend\.venv
```

不要使用 Codex 自带 Python 作为项目运行环境。

### 2.3 数据库连接

复用当前 Docker PostgreSQL 和 Redis，不改变端口、账号和连接方式。

| 配置 | 值 |
| --- | --- |
| 数据库名 | `wemedia-agent` |
| 用户名 | `postgres` |
| 密码 | `postgres` |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/wemedia-agent` |
| `REDIS_URL` | `redis://localhost:6379/0` |

### 2.4 环境变量

后端启动时会自动读取 `backend/.env`。API key、base URL、模型名和 mock 开关都写在后端 `.env`，不要写进前端。

| 变量 | 作用 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串。 |
| `REDIS_URL` | Redis 连接串。 |
| `MODEL_USE_SYSTEM_PROXY` | 是否让模型 HTTP 请求使用系统代理。默认 `false`。 |
| `LLM_MOCK` | 是否关闭真实 LLM 调用。 |
| `LLM_API_KEY` | 文案生成模型 API key。 |
| `LLM_BASE_URL` | 文案生成模型 base URL。 |
| `LLM_MODEL` | 文案生成模型名。 |
| `LLM_TEMPERATURE` | 文案生成随机性。 |
| `LLM_TOP_P` | nucleus sampling 参数。 |
| `LLM_MAX_TOKENS` | 单次生成最大 token 数。 |
| `LLM_PRESENCE_PENALTY` | 主题重复惩罚。 |
| `LLM_FREQUENCY_PENALTY` | 词频重复惩罚。 |
| `LLM_TIMEOUT_SECONDS` | LLM 请求超时时间。 |
| `EMBED_MOCK` | 是否关闭真实 embedding 调用。 |
| `EMBED_API_KEY` | embedding 模型 API key。 |
| `EMBED_BASE_URL` | embedding 模型 base URL。 |
| `EMBED_MODEL` | embedding 模型名。 |
| `EMBED_DIMENSION` | pgvector 维度，必须和真实 embedding 输出维度一致。 |
| `IMAGE_MOCK` | 是否关闭真实生图调用。 |
| `IMAGE_API_KEY` | 图片模型 API key。 |
| `IMAGE_BASE_URL` | 图片模型 base URL。 |
| `IMAGE_MODEL` | 图片模型名。 |
| `CHECKPOINTER_MOCK` | 是否关闭 LangGraph Postgres checkpointer。 |
| `LANGSMITH_TRACING` | 是否启用 LangSmith trace。 |
| `LANGSMITH_API_KEY` | LangSmith API key。 |
| `LANGSMITH_ENDPOINT` | LangSmith API 地址；美区默认 `https://api.smith.langchain.com`，欧区可用 `https://eu.api.smith.langchain.com`。 |
| `LANGSMITH_PROJECT` | LangSmith 项目名。 |
| `FIRECRAWL_ENABLED` | 是否启用 Firecrawl 工具。 |
| `FIRECRAWL_API_KEY` | Firecrawl API key。 |
| `FIRECRAWL_BASE_URL` | Firecrawl API 地址，默认 `https://api.firecrawl.dev/v2`。 |
| `FIRECRAWL_TIMEOUT_SECONDS` | Firecrawl 请求超时时间。 |
| `FIRECRAWL_MAX_RESULTS` | 单次 Firecrawl 搜索最大结果数。 |
| `WECHAT_PUBLISH_MOCK` | 是否启用微信公众号发布 mock；本地演示默认 `true`。 |
| `WECHAT_APP_ID` | 微信公众号 AppID。 |
| `WECHAT_APP_SECRET` | 微信公众号 AppSecret。 |
| `WECHAT_API_BASE_URL` | 微信公众号 API 地址，默认 `https://api.weixin.qq.com`。 |
| `WECHAT_TOKEN_CACHE_SECONDS` | access_token 缓存秒数。 |
| `WECHAT_DEFAULT_THUMB_MEDIA_ID` | 默认封面素材 media_id；真实调用时必填。 |
| `WECHAT_PUBLISH_DEFAULT_MODE` | 默认发布模式，`draft` 表示先同步草稿箱。 |

配置读取规则：

- `LLM_MODEL`、`EMBED_MODEL`、`IMAGE_MODEL` 等字段优先读取 `.env` 的真实值。
- 代码里的默认模型名只在 `.env` 没有设置时生效，不会覆盖用户配置。
- `LLM_BASE_URL` 会优先读取 `.env` 中的 `LLM_BASE_URL`，其次兼容 `LLM_URL`。
- `EMBED_BASE_URL` 会优先读取 `.env` 中的 `EMBED_BASE_URL`，其次兼容 `EMBED_URL`。

## 3. 整体流程

### 3.1 创建 workflow

入口：

```text
POST /api/v1/media-agent/workflows
```

后端创建 `workflow_records`，初始化 `WorkflowState`，然后从 `topic_review` 节点开始运行。

首次运行不会直接写文章。`WritingAgent.create_topics()` 会先执行热点发现、Graph RAG、候选排序和选题生成，然后停在选题审批状态：

```text
status = topic_review
current_node = topic_review
```

此时 `workflow_records.state_json.topics` 已有待审批选题，`draft` 和 `image_prompts` 仍为空。

### 3.2 选题审批

入口：

```text
POST /api/v1/media-agent/workflows/{id}/topic-review
```

如果选题未通过：

```text
status = candidate_returned
current_node = candidate
```

如果选题通过，后端继续运行：

```text
writing_agent -> image_agent -> final_review
```

写作和生图完成后，workflow 停在终审：

```text
status = final_review
current_node = final_review
```

### 3.3 终审

入口：

```text
POST /api/v1/media-agent/workflows/{id}/human-review
```

终审通过后进入：

```text
status = publish_ready
current_node = publish_ready
```

同时写入 `generated_posts`。

终审不通过时，状态回到：

```text
status = image_generation
current_node = image_agent
```

### 3.4 微信公众号发布

入口：

```text
POST /api/v1/media-agent/workflows/{id}/publish
```

第一版只做微信公众号发布，不做小红书发布通道。发布采用草稿箱优先：

```text
mode=draft  -> 创建公众号草稿，workflow 保持 publish_ready
mode=submit -> 提交公众号发布，成功后 workflow 进入 published
失败        -> workflow 保持 publish_ready，错误写入 publish_jobs 和 state.review.publish
```

发布任务写入 `publish_jobs`，审批页会展示草稿 `media_id`、发布 `publish_id`、状态和失败原因。确认发布成功后：

```text
status = published
current_node = published
```

## 4. 实现细节

### 4.1 LangGraph 编排

主节点定义在 `backend/app/graph/workflow.py`：

```text
topic_review
writing_agent
image_agent
final_review
finalize
```

`WorkflowService._run()` 负责按节点顺序执行，并在每个节点：

- 更新 `workflow_records.current_node`。
- 写入 `workflow_events.node_start`。
- 调用 `run_node()` 执行节点。
- 保存最新 `workflow_records.state_json`。
- 写入 `workflow_events.node_end`。
- 对 `writing_agent` 和 `image_agent` 写入 `ai_call_logs`。
- 在人工闸门处暂停。

### 4.2 业务持久化

业务主链路依赖 `SqlWorkflowRepository`，不是直接依赖 LangGraph checkpointer。

核心写入点：

| 时机 | 写入 |
| --- | --- |
| 创建 workflow | `workflow_records` |
| 节点开始/结束 | `workflow_events` |
| 每个节点完成 | `workflow_records.state_json` |
| 写作和生图入口 | `ai_call_logs` |
| 终审通过 | `generated_posts` |
| 同步草稿/提交发布 | `publish_jobs` |
| 热点刷新 | `crawl_runs`、`hot_topic_candidates` |
| 来源配置 | `external_sources` |
| 素材配置 | `content_assets` |

LangGraph `PostgresSaver` 是图执行 checkpoint，不替代业务数据库。即使 checkpointer 不可用，Repository 主链路仍然可以保存 workflow、事件和最终内容包。

### 4.3 临时数据和落库数据

| 数据 | 是否业务落库 | 说明 |
| --- | --- | --- |
| `build_writer_messages()` 生成的 user prompt | 否 | 只作为 LLM 调用输入；开启 LangSmith 时会进入 trace inputs。 |
| Writer 系统提示词 | 是 | 存入 `workflow_records.state_json.draft.writer_system_prompt`，用于审计当次写作规则。 |
| Writer 生成的标题、正文、摘要、配图简报 | 是 | 存入 `workflow_records.state_json.draft`；终审通过后标题和正文写入 `generated_posts`。 |
| Image 生成的图片 prompt | 是 | 存入 `workflow_records.state_json.image_prompts`；终审通过后写入 `generated_posts.image_prompts`。 |
| 微信发布任务 | 是 | 存入 `publish_jobs`；最新状态同步到 `workflow_records.state_json.review.publish`。 |
| 模型调用摘要 | 是 | 存入 `ai_call_logs`，只保存入口、模型名、token 估算、耗时和错误。 |

### 4.4 SSE

SSE 入口：

```text
GET /api/v1/media-agent/workflows/{id}/stream
```

当前 SSE 是从 `workflow_events` 回放事件，不是 LLM token 级流式输出。前端用它展示 workflow 节点进度。

### 4.5 Mock

Mock 是本地演示和测试模式，不代表真实模型能力：

- `LLM_MOCK=true`：不调用真实 LLM。
- `EMBED_MOCK=true`：不调用真实 embedding。
- `IMAGE_MOCK=true`：不调用真实生图接口，返回 `mock://image/...`。
- `WECHAT_PUBLISH_MOCK=true`：不调用真实微信公众号 API，返回 mock 草稿和发布 ID。

## 5. 三个 Agent 和工具

当前系统有 3 个 Agent：

| Agent | 是否在 LangGraph 主流程中 | 入口 | 主要产物 |
| --- | --- | --- | --- |
| `HotTopicScoutAgent` | 否 | `/hot-topics/refresh` | `hot_topic_candidates`、`crawl_runs`。 |
| `WritingAgent` | 是 | `topic_review`、`writing_agent` 节点 | 待审批选题、正文草稿、摘要、配图简报。 |
| `ImageAgent` | 是 | `image_agent` 节点 | 封面和正文配图 prompt，最多 3 张。 |

`HotTopicScoutAgent` 不显示在前端流程栏里；前端只保留“写作 Agent”和“生图 Agent”两个岗位队列。发布不是 Agent，由 `PublishService` 和 `WechatOfficialAccountPublisher` 处理。

### 5.1 HotTopicScoutAgent

文件：`backend/app/services/hot_topic_scout_agent.py`

职责：响应“按关键词搜热点”和“自动搜热点”，用 LLM 规划搜索，再调用公开信息工具收集信号，最后汇总成最多 2 个原创候选题目。候选只进入候选池，不直接生成文章。

工具和子能力：

| 工具/函数 | 类型 | 作用 | 当前边界 |
| --- | --- | --- | --- |
| `SCOUT_SYSTEM_PROMPT` | Agent 系统提示词 | 规定合规搜索、证据保留、原创表达、自动/关键词搜索和最多 2 个候选。 | 只约束模型行为，实际限频、去重和落库仍由代码执行。 |
| `SCOUT_PLAN_SCHEMA` | JSON 输出约束 | 约束搜索计划字段：`mode`、`queries.query`、`queries.tool`、`queries.reason`。 | `LLMService` 以 `json_object` 请求模型，返回后仍由 `_parse_json_object()` 校验。 |
| `SCOUT_SYNTHESIS_SCHEMA` | JSON 输出约束 | 约束候选汇总字段：`title`、`summary`、`source_urls`、`signals`、`risk_level`。 | 不直接信任模型分数，后续仍走规则评分和去重。 |
| `LLMService.complete("hot_topic_scout_plan")` | 模型判断 | 根据 `mode`、平台和关键词生成搜索计划。 | 只负责规划 query 和工具选择；限频、错误处理、落库由代码完成。 |
| `BrowserSearchTool.search()` | `browser-search` 抽象工具 | 记录浏览器搜索意图，生成可审计的搜索候选。 | 当前是占位/可注入接口，不会真正操控浏览器打开外部平台。 |
| `FirecrawlTool.search()` | Firecrawl 搜索 | 调用 Firecrawl v2 `/search` 搜索公开网页。 | 需要 `FIRECRAWL_ENABLED=true` 和 `FIRECRAWL_API_KEY`。 |
| `FirecrawlTool.enrich()` | Firecrawl 清洗 | 调用 Firecrawl v2 `/scrape` 清洗公开网页正文、摘要、链接和图片。 | 只处理可公开访问页面；失败时返回原结果，不中断整体搜索。 |
| `SourceAdapterTool.search()` | 来源适配器 | 调用 `collect_candidates()` 读取 `mock/rss/web/authorized` 来源。 | `authorized` 只接受用户提供的 token/cookie，不保存明文密码。 |
| `LLMService.complete("hot_topic_scout_synthesis")` | 模型汇总 | 把工具结果合并成原创候选题目、摘要、signals、risk_level 和证据。 | 最多输出 2 个候选；不能复制原文表达。 |
| `merge_and_score()` | 规则工具 | 对候选去重并按热度、增长、平台匹配、素材匹配和风险扣分排序。 | 评分是确定性代码，不交给模型随意决定。 |
| `_evidence_bonus()` | 规则工具 | 根据证据数量和工具多样性加分。 | 只影响排序，不改变来源证据。 |
| `_run_async()` | 同步/异步桥接 | 让同步的 `research()` 能调用异步的 `LLMService.complete()`。 | 不改变模型逻辑，只负责在已有事件循环时用独立线程运行协程。 |

输入：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `platform` | 前端下拉框 | 小红书或微信公众号，用作选题平台信号。 |
| `keywords` | 前端输入 | `mode=keyword` 时作为搜索核心词。 |
| `mode` | 前端按钮 | `keyword` 或 `auto`。 |
| `sources` | `external_sources` | 可配置的 mock、RSS、网页、授权来源和 Firecrawl 固定来源。 |

输出统一结构：

| 字段 | 说明 |
| --- | --- |
| `title` | 原创候选标题。 |
| `url` | 主来源 URL。 |
| `summary` | 趋势、用户痛点和可写角度摘要。 |
| `signals` | `heat/growth/platform_fit/audience_fit/material_fit/evidence_count/source_diversity` 等评分信号。 |
| `risk_level` | `low/medium/high`。 |
| `evidence` | 来源名、source_urls、queries、tools、access_method、auth_type、search_mode 和推荐理由。 |

容错：

- LLM 搜索计划失败时，`_plan_searches()` 回退到 `_build_queries()`。
- LLM 汇总失败时，`_synthesize_candidates()` 回退到 `_candidate_from_result()`。
- 单个来源失败只记录 `last_source_statuses[source_id]`，后续写入 `crawl_runs.error`，不影响其它来源。

### 5.2 WritingAgent

文件：`backend/app/agents/writing_agent.py`

职责：把热点候选和内部素材变成待审批选题；选题通过后，生成完整草稿、摘要和配图简报。

在 LangGraph 中的两个入口：

| 节点 | 调用 | 行为 |
| --- | --- | --- |
| `topic_review` | `WritingAgent.create_topics()` | 发现候选、检索素材、排序、生成待审批选题，然后停在人工选题审批。 |
| `writing_agent` | `WritingAgent.run()` | 如果已有选题，则调用 LLM 生成正文草稿。 |

工具和子能力：

| 工具/函数 | 类型 | 作用 |
| --- | --- | --- |
| `WRITER_SYSTEM_PROMPT` | Agent 系统提示词 | 规定中文原创写作、平台适配、风险边界、摘要和配图简报输出。 |
| `discover_hot_topic_candidates()` | 候选读取工具 | 从数据库候选池读取高分热点；如果指定 `candidate_id`，只读取该候选；没有候选时使用 mock 候选保证演示可跑。 |
| `retrieve_graph_context()` | Graph RAG 工具 | 调用 `GraphRAGService.retrieve()`，用平台、关键词、候选标题和摘要检索内部素材。 |
| `rank_hot_topic_candidates()` | 排序工具 | 按候选 `score` 排序，并写入 `rank_reason`。 |
| `create_topic_cards()` | 选题生成工具 | 把最高分候选转换成 workflow 内的待审批选题，并附带最多 3 条内部素材。 |
| `prepare_topic_review_gate()` | 人工闸门工具 | 初始化 `topic_review`，让 workflow 停在选题审批。 |
| `build_writer_messages()` | Prompt 组装工具 | 拼入平台、关键词、选题、热点证据和 Graph RAG 素材。 |
| `LLMService.complete("writing_agent")` | 写作模型工具 | 生成标题、正文、摘要和 `image_brief`。 |
| `parse_writer_result()` | JSON 解析工具 | 解析模型 JSON；失败时用 `_fallback_draft()` 兜底，避免生图阶段中断。 |

Writer 期望模型输出：

| 字段 | 用途 |
| --- | --- |
| `title` | 文章标题。 |
| `body` | 完整正文。 |
| `summary` | 给审批页和 ImageAgent 使用的一句话摘要。 |
| `image_brief.visual_style` | 图片整体视觉风格。 |
| `image_brief.cover` | 封面图方向。 |
| `image_brief.inline_images` | 正文配图方向，最多使用前 2 个。 |
| `image_brief.avoid` | 生图时需要避开的元素。 |

持久化：

- 草稿先进入 `workflow_records.state_json.draft`。
- 终审通过后，标题、正文、图片 prompt 和审核结果写入 `generated_posts`。
- `WRITER_SYSTEM_PROMPT` 会随草稿保存，方便后续复盘；临时 user prompt 不作为业务字段入库。

### 5.3 ImageAgent

文件：`backend/app/agents/image_agent.py`

职责：根据 Writer 的正文、摘要和配图简报生成图片提示词，再交给 `ImageService` 生成图片结果或 mock 图片结果。

工具和子能力：

| 工具/函数 | 类型 | 作用 |
| --- | --- | --- |
| `IMAGE_SYSTEM_PROMPT` | Agent 系统提示词 | 规定最多 3 张图、封面优先、公开发布安全边界和视觉方向。 |
| `retrieve_graph_context()` | Graph RAG 工具 | 如果 state 中还没有 `retrieved_assets`，补一次内部素材检索。 |
| `build_image_prompts_from_draft()` | Prompt 生成工具 | 从 `draft.title/body/summary/image_brief` 生成图片 prompt。 |
| `_normalize_image_brief()` | 规范化工具 | 清理 Writer 输出的图片简报；缺字段时用兜底值。 |
| `_fallback_image_brief()` | 兜底工具 | Writer 没有给图片简报时，生成可用封面和正文配图方向。 |
| `ImageService.generate_batch()` | 生图工具 | `IMAGE_MOCK=true` 时返回 `mock://image/...`；真实模式调用 `{IMAGE_BASE_URL}/images/generations`。 |

规则：

- 每篇文章最多 3 张图。
- 第 1 张固定为封面。
- 最多 2 张正文配图。
- 不生成品牌 logo、名人肖像、真实平台截图或误导性证明。
- 当前发布到微信公众号时不会自动上传 AI 图片，公众号封面先使用 `WECHAT_DEFAULT_THUMB_MEDIA_ID`。

输出字段：

| 字段 | 作用 |
| --- | --- |
| `cover_prompt` | 封面图 prompt。 |
| `inline_prompts` | 正文配图 prompt。 |
| `mock_images` | 图片服务返回结果；mock 模式下是 `mock://image/...`。 |
| `image_count` | 本篇文章实际生成图片 prompt 数。 |
| `system_prompt` | ImageAgent 系统提示词。 |
| `reviewed_by` | 触发该阶段的审核人。 |

### 5.4 发布服务不是 Agent

微信公众号发布不走 Agent，也不进入 LangGraph 节点。终审通过后，用户在“待发布”阶段点击按钮，后端由 `PublishService` 调用 `WechatOfficialAccountPublisher`：

```text
generated_posts -> PublishService -> WechatOfficialAccountPublisher -> publish_jobs
```

这样可以把“内容生产 Agent”和“外部平台发布副作用”分开，避免 AI 内容在未确认时直接发出。

## 6. Graph RAG

当前 Graph RAG 是最小可用版本，用于让写作 Agent 同时看到热点和内部素材。

检索入口：

```text
GraphRAGService.retrieve()
```

检索信号：

| 信号 | 来源 |
| --- | --- |
| `platform` | workflow 输入。 |
| `keywords` | workflow 输入。 |
| 热点标题 | `state.candidates`。 |
| 热点摘要 | `state.candidates`。 |

素材来源：

```text
content_assets
```

当前边界：

- `content_assets` 是素材节点。
- `tags/source/license` 是素材元信息。
- `embedding` 是 pgvector 向量检索入口。
- 当前没有独立实体表、关系边表或图数据库。
- 模型不会自己访问数据库图层。
- Agent 通过工具函数调用 `GraphRAGService`，再把检索结果提供给写作模型。

真实语义检索要求：

- `EMBED_MOCK=false`。
- `EMBED_API_KEY`、`EMBED_BASE_URL`、`EMBED_MODEL` 配置正确。
- `EMBED_DIMENSION` 必须和 embedding 模型输出维度一致。
- 素材入库和查询必须使用同一个 embedding 模型。

## 7. 热点搜查和来源配置

热点搜查入口：

```text
POST /api/v1/media-agent/hot-topics/refresh
```

前端动作：

| 动作 | 请求参数 | 结果 |
| --- | --- | --- |
| 按关键词搜热点 | `mode=keyword` | 围绕平台和关键词生成搜索计划。 |
| 自动搜热点 | `mode=auto` | 根据平台和近期内容方向自动生成搜索计划。 |

当前主线不是传统爬虫，而是 `HotTopicScoutAgent` 使用 LLM 做搜索规划和候选汇总，再调用工具收集公开信号，最后生成可审计的候选池。

端到端链路：

```text
前端按钮
-> POST /api/v1/media-agent/hot-topics/refresh
-> WorkflowService.refresh_hot_topics()
-> HotTopicScoutAgent.research()
-> browser-search / firecrawl / source-adapter
-> LLM 汇总候选
-> merge_and_score()
-> crawl_runs + hot_topic_candidates
```

当前真实能力：

| 能力 | 当前状态 |
| --- | --- |
| Firecrawl 搜索和网页清洗 | 已接入，配置正确时会真实请求 Firecrawl v2。 |
| RSS/普通网页/授权来源 | 已通过 `source-adapter` 接入。 |
| browser-search | 当前是可注入抽象和审计占位，不会真正打开浏览器搜索外部平台。 |
| 自动搜索 | 已由 LLM 生成搜索计划；实际搜索质量取决于 Firecrawl/source 配置。 |
| 候选数量 | 每次刷新最多保留 2 个候选。 |

### 7.1 来源类型

`external_sources.type` 支持：

| 类型 | 说明 |
| --- | --- |
| `mock` | 本地演示来源。 |
| `rss` | 公开 RSS。 |
| `web` | 普通公开网页。 |
| `authorized` | 用户授权 cookie/token 来源。 |
| `firecrawl_search` | 固定 Firecrawl 搜索来源。 |
| `firecrawl_scrape` | 固定 Firecrawl 单页清洗来源。 |

### 7.2 配置、限频和容错

- `enabled=false` 的来源会跳过。
- `rate_limit_seconds` 控制来源级限频。
- `should_skip_source()` 会根据最近成功采集记录决定是否跳过。
- 单个来源失败只影响该来源，错误写入 `crawl_runs.error`。
- 重复 URL 或相似标题由 `merge_and_score()` 去重。
- LLM 搜索计划失败时，`_plan_searches()` 回退到 `_build_queries()`。
- LLM 候选汇总失败时，`_synthesize_candidates()` 回退到 `_candidate_from_result()`。

### 7.3 合规和审计

- 不绕过验证码、登录墙、付费墙、平台风控或明确访问限制。
- 登录来源必须来自用户授权，不保存明文密码。
- 内容只抽象趋势、结构、关键词和用户痛点，不复制外部原文表达。
- 候选保留 `signals_json`、`score`、`risk_level` 和 `evidence_json`。
- 搜查结果只进入候选池，不直接生成文章。

## 8. 数据库表字段

表字段解释只在本章节出现一次。PostgreSQL 目标 schema 来源于 `backend/app/db/init_sql.py` 和运行时 repository schema。

### 8.1 `content_assets`

内部素材、案例、痛点、风格规则或运营知识。

| 字段 | 含义 |
| --- | --- |
| `id` | 素材 ID。 |
| `type` | 素材类型。 |
| `title` | 素材标题。 |
| `text` | 素材正文。 |
| `tags` | 标签，用于检索和匹配。 |
| `source` | 素材来源。 |
| `license` | 授权或使用范围。 |
| `embedding` | pgvector 向量，维度由 `EMBED_DIMENSION` 决定。 |

### 8.2 `workflow_records`

workflow 主记录表。

| 字段 | 含义 |
| --- | --- |
| `id` | workflow ID。 |
| `request_id` | 请求 ID。 |
| `persona_id` | 历史兼容字段；新请求默认写入 `default`，不再作为前端功能入口或模型提示输入。 |
| `status` | 业务状态。 |
| `current_node` | 当前节点。 |
| `state_json` | 完整 workflow 状态快照。 |
| `created_at` | 创建时间。 |
| `updated_at` | 更新时间。 |
| `error` | 错误信息。 |

`state_json` 包含输入、候选、素材、选题、草稿、图片 prompt、人工审核结果和复盘信息，是排查 workflow 的核心字段。

### 8.3 `workflow_events`

workflow 事件表，也是 SSE 事件来源。

| 字段 | 含义 |
| --- | --- |
| `id` | 事件 ID。 |
| `workflow_id` | workflow ID。 |
| `node` | 节点名。 |
| `event_type` | 事件类型，例如 `node_start`、`node_end`、`human_review`、`error`。 |
| `payload` | 事件内容。 |
| `latency_ms` | 节点耗时。 |
| `created_at` | 创建时间。 |

### 8.4 `generated_posts`

终审通过后的最终内容包。

| 字段 | 含义 |
| --- | --- |
| `id` | 内容包 ID。 |
| `workflow_id` | workflow ID。 |
| `title` | 最终标题。 |
| `body` | 最终正文。 |
| `image_prompts` | 封面和正文配图 prompt。 |
| `review_json` | 人工审核结果。 |
| `created_at` | 创建时间。 |

### 8.5 `publish_jobs`

微信公众号发布任务表。

| 字段 | 含义 |
| --- | --- |
| `id` | 发布任务 ID。 |
| `workflow_id` | workflow ID。 |
| `post_id` | 对应 `generated_posts.id`。 |
| `platform` | 发布平台，第一版固定为 `wechat_official_account`。 |
| `mode` | 发布模式，`draft` 或 `submit`。 |
| `status` | 任务状态，`pending`、`draft_created`、`published` 或 `failed`。 |
| `external_media_id` | 微信草稿 `media_id`。 |
| `publish_id` | 微信发布 `publish_id`。 |
| `article_id` | 微信文章 ID。 |
| `article_url` | 微信文章 URL。 |
| `request_json` | 发给微信或 mock publisher 的请求摘要。 |
| `response_json` | 微信或 mock publisher 返回内容。 |
| `error` | 失败原因。 |
| `created_at` | 创建时间。 |
| `updated_at` | 更新时间。 |

### 8.6 `metrics_context`

workflow 级指标摘要。

| 字段 | 含义 |
| --- | --- |
| `id` | 指标记录 ID。 |
| `workflow_id` | workflow ID。 |
| `token_in` | 输入 token 估算。 |
| `token_out` | 输出 token 估算。 |
| `latency_ms` | 总耗时。 |
| `cost_estimate` | 成本估算。 |
| `error_count` | 错误数。 |
| `model` | 模型名。 |

### 8.7 `external_sources`

外部热点来源配置。

| 字段 | 含义 |
| --- | --- |
| `id` | 来源 ID。 |
| `name` | 来源名称。 |
| `type` | 来源类型，例如 `mock`、`rss`、`web`、`authorized`、`firecrawl_search`、`firecrawl_scrape`。 |
| `base_url` | 来源地址。 |
| `auth_mode` | 授权模式。 |
| `enabled` | 是否启用。 |
| `rate_limit_seconds` | 来源级采集限频。 |
| `rules_json` | 来源规则、授权信息或 mock items。 |

### 8.8 `crawl_runs`

采集运行记录。

| 字段 | 含义 |
| --- | --- |
| `id` | 采集运行 ID。 |
| `source_id` | 来源 ID。 |
| `status` | `succeeded`、`failed` 或 `skipped`。 |
| `started_at` | 开始时间。 |
| `finished_at` | 结束时间。 |
| `error` | 失败原因。 |

### 8.9 `hot_topic_candidates`

热点候选池。

| 字段 | 含义 |
| --- | --- |
| `id` | 候选 ID。 |
| `source_id` | 来源 ID。 |
| `title` | 候选标题。 |
| `url` | 来源 URL。 |
| `summary` | 候选摘要。 |
| `signals_json` | 热度、增长、关键词等信号。 |
| `score` | 规则评分。 |
| `risk_level` | 风险等级。 |
| `collected_at` | 采集时间。 |
| `evidence_json` | 来源证据，例如来源名、访问方式、授权类型。 |

### 8.10 `ai_call_logs`

Agent 入口调用审计表。

| 字段 | 含义 |
| --- | --- |
| `id` | 日志 ID。 |
| `workflow_id` | workflow ID。 |
| `node` | `writing_agent` 或 `image_agent`。 |
| `model` | 模型名。 |
| `token_in` | 输入 token 估算。 |
| `token_out` | 输出 token 估算。 |
| `latency_ms` | 调用耗时。 |
| `error` | 错误信息。 |
| `created_at` | 创建时间。 |

## 9. API 清单

统一前缀：

```text
/api/v1/media-agent
```

### 9.1 Workflow

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/workflows` | workflow 列表。 |
| `POST` | `/workflows` | 新建 workflow。 |
| `GET` | `/workflows/{id}` | workflow 详情。 |
| `GET` | `/workflows/{id}/events` | workflow 事件。 |
| `GET` | `/workflows/{id}/posts` | workflow 生成内容包。 |
| `GET` | `/workflows/{id}/publish-jobs` | 微信公众号发布任务记录。 |
| `GET` | `/workflows/{id}/stream` | SSE 事件流。 |
| `POST` | `/workflows/{id}/retry` | 从指定节点重试。 |
| `POST` | `/workflows/{id}/topic-review` | 选题审批。 |
| `POST` | `/workflows/{id}/human-review` | 终审审批。 |
| `POST` | `/workflows/{id}/pause` | 暂停 workflow。 |
| `POST` | `/workflows/{id}/return-to-previous` | 退回上一步。 |
| `POST` | `/workflows/{id}/publish` | 同步微信公众号草稿或提交发布。 |
| `DELETE` | `/workflows/{id}` | 删除 workflow。 |

### 9.2 热点和来源

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/hot-topics` | 热点候选列表。 |
| `GET` | `/hot-topics/runs` | 采集运行记录。 |
| `POST` | `/hot-topics/refresh` | 刷新热点候选。 |
| `DELETE` | `/hot-topics/{topic_id}` | 删除候选选题。 |
| `GET` | `/sources` | 来源列表。 |
| `POST` | `/sources` | 新增或更新来源。 |

### 9.3 素材和评测

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/assets` | 素材列表。 |
| `POST` | `/assets` | 新增或更新素材。 |
| `POST` | `/evals/run` | 简单内容评测。 |

## 10. 技术重难点

### 10.1 三个 Agent 和工具边界

系统有 3 个 Agent，但只有 `WritingAgent` 和 `ImageAgent` 在 LangGraph 主流程中。`HotTopicScoutAgent` 是候选池入口，通过 `/hot-topics/refresh` 被按钮触发，不作为看板流程节点展示。这样主工作流稳定，热点搜索工具可以独立迭代，前端也只展示真正执行生产任务的写作和生图岗位。

### 10.2 人工审核是硬闸门

`topic_review` 和 `final_review` 都是人工闸门：

- 选题未通过时，不进入写作。
- 终审未通过时，不进入最终内容包。
- 终审通过前不写 `generated_posts`。

### 10.3 Repository 和 LangGraph checkpointer 是两层持久化

Repository 保存业务可读数据，包括 workflow、events、posts、sources、topics、assets。LangGraph checkpointer 保存图执行 checkpoint，用于恢复更复杂的图执行状态。当前业务查询和前端展示主要依赖 Repository。

### 10.4 Graph RAG 不是图数据库

当前 Graph RAG 没有独立实体表、关系边表或图数据库。它的作用是把内部素材、标签、embedding、热点候选和 workflow 上下文组合起来，让写作模型能看到相关素材关系。

### 10.5 Embedding 维度必须一致

`content_assets.embedding` 的 pgvector 维度由 `EMBED_DIMENSION` 决定。真实 embedding 模型接入后，素材入库和查询必须使用同一个模型，并保持输出维度一致，否则会出现写入或检索错误。

### 10.6 Prompt 不是业务数据

Writer 的 user prompt 是临时拼装的模型输入，不作为业务字段入库。真正业务需要复盘的是模型生成结果、系统提示词版本、来源证据、审核意见和最终内容包。

### 10.7 LangSmith 是观测工具

LangSmith trace 用于查看 workflow、节点、LLM 和图片调用，不替代数据库。关闭 `LANGSMITH_TRACING` 时不会调用 LangSmith；打开后会读取 `LANGSMITH_API_KEY`、`LANGSMITH_ENDPOINT` 和 `LANGSMITH_PROJECT`。如果 LangSmith 不可用，也不应该阻断业务流程。

LangSmith SDK 会读取当前进程的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 等代理环境变量。如果这些变量指向不可用代理，trace 上传会失败；启动后端前需要清理无效代理或换成可用代理。

### 10.8 外部采集必须可审计

热点采集不是“抓到就行”。每个候选都要能追溯来源、访问方式、授权类型、采集时间、评分和风险。采集失败也要记录在 `crawl_runs`，不能影响其它来源。

### 10.9 前端请求如何转发到后端

前端请求路径和后端 API 路径是一致的，都是：

```text
/api/v1/media-agent/...
```

开发环境里，页面运行在 Vite 前端服务：

```text
http://127.0.0.1:5173
```

所以前端代码写相对路径即可。浏览器会先请求 Vite：

```text
http://127.0.0.1:5173/api/v1/media-agent/workflows
```

`frontend/vite.config.js` 配了 `/api` 代理，Vite 看到这个请求以 `/api` 开头，就转发到后端：

```text
http://127.0.0.1:8000/api/v1/media-agent/workflows
```

后端最终收到的路径仍然是 `/api/v1/media-agent/workflows`。Vite 代理只解决“5173 前端如何访问 8000 后端”的开发环境跨端口问题，不改变业务 API 路径。

## 11. 前后端启动命令

### 11.1 初始化后端依赖

```powershell
cd C:\Users\36183\Desktop\working\demo2\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 11.2 初始化数据库

```powershell
cd C:\Users\36183\Desktop\working\demo2\backend
.\.venv\Scripts\python.exe scripts\init_db.py
```

### 11.3 启动后端

```powershell
cd C:\Users\36183\Desktop\working\demo2\backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### 11.4 启动前端

```powershell
cd C:\Users\36183\Desktop\working\demo2\frontend
npm install
npm run dev
```
