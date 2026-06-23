# 自媒体 Agent

后端按文档目标重建为 FastAPI + LangGraph + PostgreSQL/pgvector 架构，前端为 Vue 3 + Vite。当前主流程是：

```text
topic_review -> writing_agent -> image_agent -> final_review -> finalize
```

也就是先生成待审批选题，人工通过后再写作和生图，图文包进入终审，终审通过后进入待发布；发布确认后进入已发布。

详细技术文档见 [docs/technical_guide.md](docs/technical_guide.md)。

## 数据库

复用已有 Docker 服务，不改端口和账号：

- PostgreSQL: `localhost:5432`
- User/password: `postgres/postgres`
- Database: `wemedia-agent`
- Redis: `localhost:6379`

数据库已可用时，后端连接串：

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/wemedia-agent
REDIS_URL=redis://localhost:6379/0
```

## API Key 配置

后端启动会自动读取 `backend/.env`。API key、base URL 和模型名写在这个文件里，不写入前端，也不需要 PowerShell 临时设置。

```env
MODEL_USE_SYSTEM_PROXY=false

LLM_MOCK=false
LLM_API_KEY=replace-with-your-llm-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini

EMBED_MOCK=false
EMBED_API_KEY=replace-with-your-embed-api-key
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_MODEL=text-embedding-3-small
EMBED_DIMENSION=1536

IMAGE_MOCK=true
IMAGE_API_KEY=replace-with-your-image-api-key
IMAGE_BASE_URL=https://api.openai.com/v1
IMAGE_MODEL=gpt-image-1

LANGSMITH_TRACING=false
LANGSMITH_API_KEY=replace-with-your-langsmith-key
LANGSMITH_PROJECT=wemedia-agent-dev
```

`MODEL_USE_SYSTEM_PROXY=false` 会让模型 API 请求默认绕开系统代理，避免本机代理配置残留导致连接被拒。需要走系统代理时再改为 `true`。

## 本地运行

```powershell
cd C:\Users\36183\Desktop\working\demo2\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\init_db.py
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd C:\Users\36183\Desktop\working\demo2\frontend
npm install
npm run dev
```

后端依赖使用 `backend\.venv`；前端默认地址是 `http://127.0.0.1:5173`，后端默认地址是 `http://127.0.0.1:8000`。
