# 自媒体运营Agent

`demo2` 是一个面向自媒体内容生产流程的 Agent 工作台。它把“热点发现、选题审批、文案生成、配图生成、终审复盘、微信公众号草稿/发布”串成一条可审计、可人工干预、可观测的运营流水线。

项目不是简单的聊天式写稿工具，而是一个围绕内容运营岗位设计的多 Agent 工作流 MVP：热点信号先进候选池，选题经过人工确认后再进入写作和生图，最终内容包通过终审后才允许同步到微信公众号草稿箱或提交发布。

详细实现说明见 [docs/technical_guide.md](docs/technical_guide.md)。

## 核心亮点

| 能力 | 说明 |
| --- | --- |
| 热点搜查 Agent | 支持按关键词搜索和自动搜索，使用 LLM 规划搜索词，结合 Firecrawl、公开来源适配器和可审计证据生成热点候选。 |
| LangGraph 工作流 | 通过 `topic_review -> writing_agent -> image_agent -> final_review -> finalize` 编排内容生产节点。 |
| Graph RAG | 使用 PostgreSQL + pgvector 检索内部素材，让写作 Agent 能结合热点、历史素材、标签和平台上下文生成内容。 |
| 人工审核闸门 | 选题审批和终审审批都是硬闸门，AI 不会绕过人工确认直接生成最终发布内容。 |
| 微信公众号发布链路 | 采用“草稿箱优先”策略，先同步微信公众号草稿，确认后再提交发布，发布任务全量入库。 |
| 全链路持久化 | workflow、事件、热点候选、素材、AI 调用摘要、最终内容包和发布任务都写入数据库。 |
| 可观测能力 | 支持 LangSmith trace 和结构化日志，用于查看工作流节点、模型调用和失败上下文。 |

## 系统架构

```mermaid
flowchart LR
    UI["Vue 运营中控台"]
    API["FastAPI /api/v1/media-agent"]
    Scout["HotTopicScoutAgent"]
    Graph["LangGraph Workflow"]
    Writer["WritingAgent"]
    Image["ImageAgent"]
    Review["人工审批"]
    Publish["Wechat Publish Service"]
    DB[("PostgreSQL + pgvector")]
    Redis[("Redis")]
    LLM["OpenAI-compatible LLM"]
    Firecrawl["Firecrawl / 公开来源"]
    Wechat["微信公众号 API"]

    UI --> API
    API --> Scout
    Scout --> Firecrawl
    Scout --> LLM
    Scout --> DB
    API --> Graph
    Graph --> Writer
    Writer --> DB
    Writer --> LLM
    Graph --> Image
    Image --> LLM
    Image --> DB
    Graph --> Review
    Review --> DB
    API --> Publish
    Publish --> Redis
    Publish --> Wechat
    Publish --> DB
```

## 工作流

```text
热点候选
-> AI 生成待审批选题
-> 人工通过选题
-> 写作 Agent 生成草稿和配图简报
-> 生图 Agent 生成封面/正文配图 prompt
-> 人工终审
-> 生成最终内容包
-> 同步微信公众号草稿箱
-> 可选提交发布
```

当前 LangGraph 主流程：

```text
topic_review -> writing_agent -> image_agent -> final_review -> finalize
```

## 三个 Agent

| Agent | 是否进入 LangGraph | 入口 | 主要职责 |
| --- | --- | --- | --- |
| `HotTopicScoutAgent` | 否 | `/hot-topics/refresh` | 规划搜索、调用 Firecrawl/来源适配器、综合外部公开信号生成最多 2 个热点候选。 |
| `WritingAgent` | 是 | `topic_review`、`writing_agent` | 读取候选池，执行 Graph RAG 检索，生成待审批选题、正文草稿、摘要和配图简报。 |
| `ImageAgent` | 是 | `image_agent` | 基于正文、摘要和图片简报生成图片提示词，每篇最多 3 张图。 |

微信公众号发布不是 Agent，而是由 `PublishService -> WechatOfficialAccountPublisher` 执行外部平台副作用，避免内容生成 Agent 直接触发真实发布。

## 前端体验

前端使用 Vue 3 + Vite，首页是“运营流程看板”：

- 左侧：平台选择、热点搜索、新建内容、写作 Agent 和生图 Agent 队列。
- 中间：候选、待审批选题、文案中、生图、待审批、待发布、已发布、异常等流程列。
- 详情页：展示流程状态、受众、下一步、草稿、图片 prompt、审批意见和发布任务。
- 待发布阶段：只显示微信公众号草稿/发布，不再保留小红书发布入口。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | Vue 3, Vite |
| 后端 | FastAPI, SQLAlchemy, SSE |
| 工作流 | LangGraph, langgraph-checkpoint-postgres |
| 数据库 | PostgreSQL, pgvector |
| 缓存 | Redis |
| 模型接口 | OpenAI-compatible Chat / Embedding / Image API |
| 热点工具 | Firecrawl v2, RSS/网页/授权来源 adapter |
| 发布 | 微信公众号草稿箱和发布 API |
| 观测 | LangSmith, structlog |

## 目录结构

```text
demo2
├── backend
│   ├── app
│   │   ├── agents          # WritingAgent / ImageAgent 和工具函数
│   │   ├── api             # FastAPI 路由
│   │   ├── core            # 配置、数据库、观测
│   │   ├── db              # PostgreSQL schema 初始化
│   │   ├── graph           # LangGraph 状态和节点编排
│   │   ├── models          # WorkflowRecord 等模型
│   │   └── services        # 热点搜查、RAG、LLM、图片、微信发布等服务
│   ├── data                # 演示种子数据
│   ├── scripts             # 数据库初始化脚本
│   ├── .env.example        # 后端环境变量模板
│   └── main.py             # FastAPI 入口
├── frontend
│   ├── src                 # Vue 中控台
│   ├── package.json
│   └── vite.config.js
├── docs
│   └── technical_guide.md  # 技术细节文档
└── README.md
```

## 运行环境

默认复用本机 Docker 中已经启动的 PostgreSQL 和 Redis：

| 服务 | 地址 |
| --- | --- |
| 前端 | `http://127.0.0.1:5173` |
| 后端 | `http://127.0.0.1:8000` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

数据库配置：

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/wemedia-agent
REDIS_URL=redis://localhost:6379/0
```

## 环境变量

后端启动会自动读取 `backend/.env`。建议从模板开始：

```powershell
cd C:\Users\36183\Desktop\working\demo2\backend
Copy-Item .env.example .env
```

核心配置：

```env
MODEL_USE_SYSTEM_PROXY=false

LLM_MOCK=true
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
LLM_TEMPERATURE=0.4
LLM_TOP_P=0.9
LLM_MAX_TOKENS=1600

EMBED_MOCK=true
EMBED_API_KEY=
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_MODEL=text-embedding-3-small
EMBED_DIMENSION=1536

IMAGE_MOCK=true
IMAGE_API_KEY=
IMAGE_BASE_URL=https://api.openai.com/v1
IMAGE_MODEL=gpt-image-1

FIRECRAWL_ENABLED=false
FIRECRAWL_API_KEY=
FIRECRAWL_BASE_URL=https://api.firecrawl.dev/v2

LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=wemedia-agent-dev

WECHAT_PUBLISH_MOCK=true
WECHAT_APP_ID=
WECHAT_APP_SECRET=
WECHAT_DEFAULT_THUMB_MEDIA_ID=
WECHAT_PUBLISH_DEFAULT_MODE=draft
```

真实模型接入时，将对应的 `*_MOCK` 改为 `false`，并填写 `*_API_KEY`、`*_BASE_URL` 和模型名。真实微信公众号调用时，需要把 `WECHAT_PUBLISH_MOCK=false`，并配置公众号 AppID、AppSecret 和默认封面素材 `media_id`。

## 启动项目

### 后端

```powershell
cd C:\Users\36183\Desktop\working\demo2\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\init_db.py
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### 前端

```powershell
cd C:\Users\36183\Desktop\working\demo2\frontend
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

前端请求统一使用：

```text
/api/v1/media-agent/...
```

Vite 会在开发环境把 `/api` 代理到 `http://127.0.0.1:8000`。

## 常用 API

统一前缀：

```text
/api/v1/media-agent
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/workflows` | 查询 workflow 列表。 |
| `POST` | `/workflows` | 新建内容生产 workflow。 |
| `POST` | `/workflows/{id}/topic-review` | 选题审批。 |
| `POST` | `/workflows/{id}/human-review` | 终审审批。 |
| `POST` | `/workflows/{id}/publish` | 同步微信公众号草稿或提交发布。 |
| `GET` | `/workflows/{id}/publish-jobs` | 查询发布任务。 |
| `POST` | `/hot-topics/refresh` | 启动热点搜查 Agent。 |
| `GET` | `/hot-topics` | 查询热点候选池。 |
| `DELETE` | `/hot-topics/{topic_id}` | 删除候选选题。 |
| `GET` | `/assets` | 查询内部素材。 |
| `POST` | `/assets` | 新增或更新内部素材。 |

## 当前边界

- 热点搜查遵守公开访问和用户授权边界，不实现验证码绕过、登录墙绕过、付费墙绕过或平台风控规避。
- `browser-search` 当前是可注入抽象和审计占位，不会真正操控浏览器访问外部平台。
- Firecrawl 配置正确时可以真实搜索和清洗公开网页。
- 第一版只做微信公众号发布；小红书保留为选题平台，不作为发布通道。
- 当前微信公众号发布不自动上传 AI 图片，封面使用 `WECHAT_DEFAULT_THUMB_MEDIA_ID`。
- Graph RAG 当前是基于 `content_assets`、标签和 pgvector 的最小可用实现，不是独立图数据库。

## 文档

- [技术使用文档](docs/technical_guide.md)：后端架构、数据表、Agent 工具、热点搜查、Graph RAG、API 和启动命令。
- [原始方案草稿](02-自媒体Agent.md)：早期设计参考，当前真实实现以技术文档和代码为准。
