# 02 - 自媒体 Agent

## 新会话交接 Prompt

```text
请只实现“自媒体 Agent”项目。目标是基于 Graph RAG + LangGraph 做一个自媒体智能内容运营系统，支持选题、写作、配图、审核和发布草稿的多阶段工作流。必须参考本分册中的目录结构和技术约束：FastAPI 路由层、LangGraph graph 层、PostgreSQL Checkpointer、workflow_record 元数据、SSE 流式输出、MetricsContext 成本追踪、Mock 开关、LangSmith/structlog 观测。不要实现其它项目，只预留 MCP/tool 接口。
```

## 项目目标与面试讲法

这个项目不是普通“生成一篇小红书文案”。面试重点是你把内容生产拆成多阶段工作流，并解决状态持久化、失败恢复、流式体验、成本追踪、模型路由和可观测性。

参考简历技术点应落地为：

- LangGraph + SubGraph：选题、写作、配图、审核独立节点。
- PostgreSQL Checkpointer：任意历史节点回滚和增量重试。
- MetricsContext：追踪 token、延迟、错误率、成本。
- SSE + `astream_events`：实时返回节点进度和 token 流。
- 图片批量生成异步并行：`asyncio.gather` + 指数退避重试。
- 模型动态路由：简单任务走轻量模型，复杂任务走旗舰模型。
- Mock 开关：`llm_mock`、`image_mock`、`checkpointer_mock`。
- LangSmith/structlog：全链路 trace 和 request_id 关联。
- SlowAPI：限流、熔断、健康检查和优雅关闭。

## 推荐目录结构

```text
project_root/
  app/
    api/
      v1/
        workflows.py      # 触发工作流、获取状态、SSE 流
        assets.py         # 图片、文章资源管理
      deps.py             # DB、LLM clients 依赖注入
    core/
      config.py           # 环境变量
      database.py         # PostgreSQL 连接池
    graph/
      state.py            # LangGraph State 定义
      nodes/
        writing_agent.py  # 写作 Agent
        image_agent.py    # 生图 Agent
        tools.py          # 采集、检索、排序、选题、写作、生图工具
      edges.py            # 条件路由逻辑
      workflow.py         # Graph 组装与编译
    services/
      llm_service.py      # OpenAI-compatible 调用
      image_service.py    # 图片生成 API 封装
      social_service.py   # 未来发布 API 适配
    models/
      workflow_record.py  # 每次运行元数据
  data/
  main.py
  requirements.txt
  .env
```

## MVP 功能范围

必须做：

- 输入账号定位、目标平台、主题关键词，生成选题列表。
- 对选题生成文章、标题，人工审核通过后生成封面图 prompt、配图 prompt。
- 自动审核：检查违规词、事实不确定性、风格偏离、结构完整度。
- 工作流状态持久化，支持失败节点重试。
- SSE 展示节点进度和部分流式文本。
- 工作流记录列表和详情页。

可选做：

- 真实图片生成。
- 发布到公众号/小红书的草稿 API。
- A/B 标题测试。

不做：

- 自动发布真实内容。
- 未授权爬取竞品账号。

## 高质量数据获取方案

数据来源：

- 自造 5 个账号人设：AI 教育、职场成长、电商运营、母婴消费、本地生活。
- 为每个人设人工写 20 条高质量样例：标题、开头、正文结构、CTA。
- 收集公开平台的爆款标题结构规律，只抽象模板，不复制原文。
- 自造 100 条素材卡片：用户痛点、产品卖点、行业知识、案例故事。

清洗和标注：

- 每条样例标注 `platform`、`persona`、`tone`、`hook_type`、`cta_type`。
- 标记不可用样例：夸大承诺、医疗金融敏感、虚假数据。
- 为选题建立知识图谱边：`persona -> pain_point -> content_angle -> asset`。

最小数据量：

- 100 条优质内容样例。
- 100 条素材卡片。
- 50 条审核规则或负例。

## 核心数据结构

```text
personas(id, name, audience, tone, forbidden_topics)
content_assets(id, type, title, text, tags, source, license)
topic_cards(id, persona_id, title, angle, score, reason)
workflow_records(id, request_id, persona_id, status, current_node, state_json)
workflow_events(id, workflow_id, node, event_type, payload, latency_ms)
generated_posts(id, workflow_id, title, body, image_prompts, review_json)
metrics_context(id, workflow_id, token_in, token_out, latency_ms, cost_estimate)
```

## 预留接口

REST：

- `POST /api/v1/media-agent/workflows`
- `GET /api/v1/media-agent/workflows/{id}`
- `GET /api/v1/media-agent/workflows/{id}/events`
- `GET /api/v1/media-agent/workflows/{id}/stream`
- `POST /api/v1/media-agent/assets`
- `POST /api/v1/media-agent/evals/run`

Service：

- `WorkflowService.start(input)`
- `WorkflowService.retry(workflow_id, from_node)`
- `LLMService.complete(task_type, messages, schema)`
- `ImageService.generate_batch(prompts)`
- `MetricsContext.record(node, model, tokens, latency, error)`

MCP 预留：

- `media_agent.generate_post`
- `media_agent.review_post`
- `media_agent.search_assets`

## 依赖清单

- Python：FastAPI、LangGraph、LangChain、SQLAlchemy、psycopg、redis、rq、sse-starlette、slowapi、structlog、langsmith。
- 数据库：PostgreSQL + pgvector。MVP 阶段 Graph RAG 的节点素材、账号画像和内容知识片段都写入 PostgreSQL，使用 `project_id`、`persona_id`、`source_type` 做过滤，不再引入 ChromaDB。
- 前端：Next.js、React Query、ReadableStream 解析 SSE。
- 外部：OpenAI-compatible LLM、图片生成 API，可用 mock 替代。

## 实现步骤

1. 建立目录结构、配置、数据库和 workflow_records。
2. 定义 LangGraph State：输入、选题、正文、图片 prompt、审核结果、metrics。
3. 实现 writing_agent、human_review、image_agent、finalize 节点和条件路由。
4. 接入 PostgreSQL Checkpointer，确保中断后恢复。
5. 实现 SSE 输出：节点开始/结束、token 流、错误事件。
6. 实现 MetricsContext 和 ai_call_logs。
7. 实现 mock 开关和本地演示数据。
8. 实现管理台：创建工作流、看进度、看结果、重试节点。

## 测试与验收

- 功能：输入一个账号人设和主题，能生成完整内容包。
- 状态：中途模拟 writing_agent 或 image_agent 节点失败后，可从失败节点重试。
- 流式：前端能实时看到节点事件和生成片段。
- 成本：每次 workflow 展示 token、延迟、模型和成本估算。
- 数据：至少 5 个人设、100 条素材、50 条审核规则。
- 演示：展示一次完整 workflow、一次失败恢复、一次 mock 模式。

## 风险与降级方案

- 图片 API 不稳定：默认先生成 prompt 和占位图。
- 模型输出不稳定：所有关键节点使用 Pydantic schema 或 JSON mode。
- 成本过高：模型路由按 `draft/review/final` 分层。
- 状态复杂：先只支持节点级重试，不做任意 token 级回放。
