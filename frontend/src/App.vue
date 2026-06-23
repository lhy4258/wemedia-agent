<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { json, streamUrl } from './api'

const platform = ref('小红书')
const keywords = ref('AI,teacher')
const platformOptions = ['小红书', '微信公众号']
const workflows = ref([])
const topics = ref([])
const selected = ref(null)
const events = ref([])
const crawlRuns = ref([])
const posts = ref([])
const publishJobs = ref([])
const reviewComment = ref('内容可用，可以进入下一步')
const busy = ref(false)
const detailLoading = ref(false)
const screenMode = ref('board')
const activeStage = ref('all')
const statusMessage = ref('准备就绪')

let refreshTimer = null
let stream = null

const stageOrder = [
  'candidate',
  'topic_review',
  'copywriting',
  'image_generation',
  'final_review',
  'publish_ready',
  'published',
  'failed',
]

const stageMeta = {
  candidate: { title: '候选', subtitle: '搜索生成的热门选题', role: '热门候选池', code: '热' },
  topic_review: { title: '待审批选题', subtitle: 'AI 生成选题', role: '选题操盘手', code: '选' },
  copywriting: { title: '文案中', subtitle: '写作 Agent', role: '写作 Agent', code: '文' },
  image_generation: { title: '生图', subtitle: '生图 Agent', role: '生图 Agent', code: '图' },
  final_review: { title: '待审批', subtitle: '图文包人工审核', role: '人工审批', code: '审' },
  publish_ready: { title: '待发布', subtitle: '微信公众号草稿 / 发布', role: '发布排期官', code: '发' },
  published: { title: '已发布', subtitle: '发布结果回写', role: '复盘记录员', code: '复' },
  failed: { title: '异常', subtitle: '失败 / 暂停 / 退回', role: '运营处理', code: '异' },
}

function keywordList() {
  return keywords.value.split(',').map((item) => item.trim()).filter(Boolean)
}

function workflowStage(workflow) {
  if (workflow.status === 'topic_review') return 'topic_review'
  if (workflow.status === 'candidate_returned') return 'candidate'
  if (workflow.status === 'publish_ready') return 'publish_ready'
  if (workflow.status === 'completed') return 'publish_ready'
  if (workflow.status === 'published') return 'published'
  if (workflow.status === 'final_review') return 'final_review'
  if (workflow.status === 'image_generation') return 'image_generation'
  if (workflow.status === 'paused' || workflow.status === 'failed') return 'failed'
  if (workflow.current_node === 'writing_agent') return 'copywriting'
  if (workflow.current_node === 'image_agent') return 'image_generation'
  if (workflow.current_node === 'final_review') return 'final_review'
  if (workflow.current_node === 'publish_ready') return 'publish_ready'
  if (workflow.current_node === 'finalize') return 'publish_ready'
  return 'failed'
}

function workflowCard(workflow) {
  const state = workflow.state || {}
  const topic = state.topics?.[0] || {}
  const draft = state.draft || {}
  const input = state.input || {}
  const title = draft.title || topic.title || `${input.platform || 'unknown'} · ${workflow.id.slice(0, 6)}`
  return {
    id: workflow.id,
    kind: 'workflow',
    stage: workflowStage(workflow),
    title,
    summary: topic.reason || draft.body || workflow.error || '等待下一步处理',
    score: topic.score ?? '',
    workflow,
  }
}

function candidateCard(topic) {
  return {
    id: topic.id,
    kind: 'candidate',
    stage: 'candidate',
    title: topic.title,
    summary: topic.summary || '暂无摘要',
    score: topic.score ?? 0,
    topic,
  }
}

const cards = computed(() => [
  ...topics.value.map(candidateCard),
  ...workflows.value.map(workflowCard),
])

const columns = computed(() =>
  stageOrder.map((key) => ({
    key,
    ...stageMeta[key],
    cards: cards.value.filter((card) => card.stage === key),
  })),
)

const agentQueue = computed(() => [
  { key: 'writer', name: '写作 Agent', route: 'writing-agent', stage: 'copywriting', count: columnCount('copywriting') },
  { key: 'image', name: '生图 Agent', route: 'image-agent', stage: 'image_generation', count: columnCount('image_generation') },
])

function columnCount(key) {
  return columns.value.find((item) => item.key === key)?.cards.length || 0
}

const selectedWorkflow = computed(() => selected.value?.kind === 'workflow' ? selected.value.workflow : null)
const selectedState = computed(() => selectedWorkflow.value?.state || {})
const selectedTopic = computed(() => selectedState.value.topics?.[0] || selected.value?.topic || {})
const selectedDraft = computed(() => selectedState.value.draft || {})
const selectedImages = computed(() => selectedState.value.image_prompts || {})
const selectedInput = computed(() => selectedState.value.input || {})
const selectedStage = computed(() => selectedWorkflow.value ? workflowStage(selectedWorkflow.value) : 'candidate')
const selectedPublish = computed(() => selectedState.value.review?.publish || {})
const latestPublishJob = computed(() => publishJobs.value[0] || selectedPublish.value || {})

const detailTitle = computed(() => {
  if (!selected.value) return '选择一张内容卡片'
  return selectedDraft.value.title || selectedTopic.value.title || selected.value.title
})

const detailSummary = computed(() => {
  if (selectedDraft.value.body) return selectedDraft.value.body.slice(0, 96)
  return selectedTopic.value.reason || selectedTopic.value.summary || selected.value?.summary || '等待节点产出'
})

const detailAudience = computed(() => {
  if (!selected.value) return '暂无'
  return selectedInput.value.platform || platform.value
})

const nextStep = computed(() => {
  if (!selected.value) return '等待选择内容'
  const map = {
    candidate: '用候选创建待审批选题',
    topic_review: '等待确认选题角度',
    copywriting: '写作 Agent 正在生成草稿',
    image_generation: '生图 Agent 正在生成图片提示词',
    final_review: '等待确认图文内容',
    publish_ready: '同步公众号草稿箱，确认后发布',
    published: '等待发布数据和复盘指标回写',
    failed: '需要处理异常、暂停原因或删除',
  }
  return map[selectedStage.value]
})

const flowLabel = computed(() => stageMeta[selectedStage.value]?.title || '未选择')
const selectedRole = computed(() => stageMeta[selectedStage.value]?.role || '运营')

const processSteps = computed(() => {
  const currentIndex = stageOrder.indexOf(selectedStage.value)
  return stageOrder.map((key, index) => ({
    key,
    title: stageMeta[key].title,
    role: stageMeta[key].role,
    done: currentIndex > index && selectedStage.value !== 'failed',
    active: currentIndex === index,
  }))
})

const reviewNote = computed(() => {
  const state = selectedState.value
  return state.review?.returned?.comment
    || state.review?.paused?.reason
    || state.review?.publish?.comment
    || state.human_review?.comment
    || state.topic_review?.comment
    || '暂无审批意见'
})

const latestEvent = computed(() => events.value.at(-1)?.event || events.value.at(-1)?.name || '等待事件')

const availableActions = computed(() => {
  if (!selectedWorkflow.value) return []
  const stage = selectedStage.value
  const commonDanger = { key: 'delete', label: '删除', variant: 'danger' }
  if (stage === 'topic_review') {
    return [
      { key: 'approve-topic', label: '通过', variant: 'primary' },
      { key: 'return-topic', label: '退回（上一步）', variant: 'ghost' },
      { key: 'pause', label: '暂停', variant: 'ghost' },
      commonDanger,
    ]
  }
  if (stage === 'final_review') {
    return [
      { key: 'approve-final', label: '通过', variant: 'primary' },
      { key: 'return-final', label: '退回（上一步）', variant: 'ghost' },
      { key: 'pause', label: '暂停', variant: 'ghost' },
      commonDanger,
    ]
  }
  if (stage === 'publish_ready') {
    return [
      { key: 'publish-draft', label: '同步到公众号草稿箱', variant: 'primary' },
      { key: 'publish-submit', label: '确认发布', variant: 'primary' },
      { key: 'return-publish', label: '退回（上一步）', variant: 'ghost' },
      { key: 'pause', label: '暂停', variant: 'ghost' },
      commonDanger,
    ]
  }
  if (stage === 'image_generation') {
    return [
      { key: 'retry-image', label: '重试生图', variant: 'primary' },
      { key: 'pause', label: '暂停', variant: 'ghost' },
      commonDanger,
    ]
  }
  if (stage === 'copywriting') {
    return [
      { key: 'retry-writing', label: '重试文案', variant: 'primary' },
      { key: 'pause', label: '暂停', variant: 'ghost' },
      commonDanger,
    ]
  }
  if (stage === 'failed') {
    return [
      { key: 'retry-current', label: '重试当前节点', variant: 'primary' },
      commonDanger,
    ]
  }
  if (stage === 'published') {
    return [commonDanger]
  }
  return []
})

function isSelected(card) {
  return selected.value?.id === card.id && selected.value?.kind === card.kind
}

async function loadAll() {
  const [workflowList, topicList, runList] = await Promise.all([
    json('/workflows'),
    json('/hot-topics'),
    json('/hot-topics/runs'),
  ])
  workflows.value = workflowList
  topics.value = topicList
  crawlRuns.value = runList
  syncSelected()
  if (screenMode.value === 'detail' && selectedWorkflow.value) {
    await loadSelectedArtifacts(false)
  }
}

function syncSelected() {
  if (!selected.value || selected.value.kind !== 'workflow') return
  const fresh = workflows.value.find((workflow) => workflow.id === selected.value.workflow.id)
  if (fresh) selected.value = workflowCard(fresh)
}

async function loadSelectedArtifacts(showLoading = true) {
  if (!selectedWorkflow.value) return
  detailLoading.value = showLoading
  try {
    const workflowId = selectedWorkflow.value.id
    const [freshWorkflow, eventList, postList, jobList] = await Promise.all([
      json(`/workflows/${workflowId}`),
      json(`/workflows/${workflowId}/events`),
      json(`/workflows/${workflowId}/posts`),
      json(`/workflows/${workflowId}/publish-jobs`),
    ])
    selected.value = workflowCard(freshWorkflow)
    events.value = eventList
    posts.value = postList
    publishJobs.value = jobList
  } finally {
    detailLoading.value = false
  }
}

async function withBusy(task, successMessage = '操作完成') {
  busy.value = true
  statusMessage.value = '处理中...'
  try {
    const result = await task()
    statusMessage.value = successMessage
    return result
  } catch (error) {
    statusMessage.value = error instanceof Error ? error.message : '操作失败'
    return null
  } finally {
    busy.value = false
  }
}

async function focusAgentStage(stage) {
  activeStage.value = stage
  statusMessage.value = `已定位到「${stageMeta[stage]?.title || stage}」`
  await nextTick()
  document.querySelector(`[data-stage="${stage}"]`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'nearest',
    inline: 'center',
  })
}

async function refreshTopics(mode = 'keyword') {
  await withBusy(async () => {
    await json('/hot-topics/refresh', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ platform: platform.value, keywords: keywordList(), mode }),
    })
    await loadAll()
  }, mode === 'auto' ? '自动热点搜索已完成' : '关键词热点搜索已完成')
}

async function createWorkflow(candidateId = null, openAfterCreate = false) {
  await withBusy(async () => {
    const workflow = await json('/workflows', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ platform: platform.value, keywords: keywordList(), candidate_id: candidateId }),
    })
    selected.value = workflowCard(workflow)
    reviewComment.value = approvalComment(selected.value)
    if (openAfterCreate) {
      screenMode.value = 'detail'
      watchStream(workflow.id)
      await loadSelectedArtifacts()
    } else {
      screenMode.value = 'board'
      statusMessage.value = '已创建，进入待审批选题'
    }
    await loadAll()
  }, openAfterCreate ? '已进入审批详情' : '已创建，进入待审批选题')
}

async function openDetail(card) {
  if (card.kind === 'candidate') {
    await createWorkflow(card.topic.id, false)
    return
  }
  selected.value = card
  reviewComment.value = approvalComment(card)
  screenMode.value = 'detail'
  watchStream(card.workflow.id)
  await loadSelectedArtifacts()
}

async function deleteCandidate(card, event) {
  event?.stopPropagation()
  if (!card?.topic?.id || busy.value) return
  if (!window.confirm('确认删除这个候选选题？')) return
  await withBusy(async () => {
    await json(`/hot-topics/${card.topic.id}`, { method: 'DELETE' })
    if (selected.value?.kind === 'candidate' && selected.value.id === card.id) selected.value = null
    await loadAll()
  }, '已删除候选选题')
}

function goBoard() {
  screenMode.value = 'board'
}

async function retryWorkflow(fromNode) {
  if (!selectedWorkflow.value) return
  const workflow = await json(`/workflows/${selectedWorkflow.value.id}/retry`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ from_node: fromNode || selectedWorkflow.value.current_node }),
  })
  selected.value = workflowCard(workflow)
  watchStream(workflow.id)
  await loadSelectedArtifacts()
  await loadAll()
}

async function runApprovalAction(action) {
  if (!action || busy.value) return
  busy.value = true
  statusMessage.value = '处理中...'
  try {
    if (action.key === 'approve-topic') await submitTopicReview(true)
    if (action.key === 'return-topic') await submitTopicReview(false)
    if (action.key === 'approve-final') await submitFinalReview(true)
    if (action.key === 'return-final') await submitFinalReview(false)
    if (action.key === 'publish-draft') await submitPublish('draft')
    if (action.key === 'publish-submit') await submitPublish('submit')
    if (action.key === 'return-publish') await submitReturnToPrevious()
    if (action.key === 'retry-image') await retryWorkflow('image_agent')
    if (action.key === 'retry-writing') await retryWorkflow('writing_agent')
    if (action.key === 'retry-current') await retryWorkflow(selectedWorkflow.value?.current_node || 'topic_review')
    if (action.key === 'pause') await pauseSelected()
    if (action.key === 'delete') await deleteSelected()
    statusMessage.value = '操作完成'
  } catch (error) {
    statusMessage.value = error instanceof Error ? error.message : '操作失败'
  } finally {
    busy.value = false
  }
}

async function submitTopicReview(approved) {
  const workflow = await json(`/workflows/${selectedWorkflow.value.id}/topic-review`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ approved, reviewer: 'operator', comment: reviewComment.value }),
  })
  selected.value = workflowCard(workflow)
  watchStream(workflow.id)
  await loadSelectedArtifacts()
  await loadAll()
}

async function submitFinalReview(approved) {
  const workflow = await json(`/workflows/${selectedWorkflow.value.id}/human-review`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ approved, reviewer: 'operator', comment: reviewComment.value }),
  })
  selected.value = workflowCard(workflow)
  watchStream(workflow.id)
  await loadSelectedArtifacts()
  await loadAll()
}

async function submitReturnToPrevious() {
  const workflow = await json(`/workflows/${selectedWorkflow.value.id}/return-to-previous`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ operator: 'operator', comment: reviewComment.value }),
  })
  selected.value = workflowCard(workflow)
  watchStream(workflow.id)
  await loadSelectedArtifacts()
  await loadAll()
}

async function submitPublish(mode = 'draft') {
  const workflow = await json(`/workflows/${selectedWorkflow.value.id}/publish`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      operator: 'operator',
      comment: reviewComment.value,
      platform: 'wechat_official_account',
      mode,
    }),
  })
  selected.value = workflowCard(workflow)
  watchStream(workflow.id)
  await loadSelectedArtifacts()
  await loadAll()
}

async function pauseSelected() {
  if (!selectedWorkflow.value) return
  const workflow = await json(`/workflows/${selectedWorkflow.value.id}/pause`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ reason: reviewComment.value, operator: 'operator' }),
  })
  selected.value = workflowCard(workflow)
  await loadSelectedArtifacts()
  await loadAll()
}

async function deleteSelected() {
  if (!selectedWorkflow.value) return
  if (!window.confirm('确认删除这份内容 workflow？删除后无法在看板中恢复。')) return
  await json(`/workflows/${selectedWorkflow.value.id}`, { method: 'DELETE' })
  selected.value = null
  events.value = []
  posts.value = []
  publishJobs.value = []
  screenMode.value = 'board'
  statusMessage.value = '已删除 workflow'
  await loadAll()
}

function approvalComment(card) {
  if (card.kind === 'candidate') return '将该热门候选生成待审批选题'
  const stage = workflowStage(card.workflow)
  if (stage === 'topic_review') return '选题角度可用，进入写作和生图'
  if (stage === 'final_review') return '图文内容可用，进入待发布'
  if (stage === 'publish_ready') return '同步公众号草稿箱，确认后发布'
  return card.workflow.state?.human_review?.comment || card.workflow.state?.topic_review?.comment || ''
}

function watchStream(workflowId) {
  if (stream) stream.close()
  stream = new EventSource(streamUrl(workflowId))
  for (const name of ['node_start', 'node_end', 'topic_review', 'human_review', 'returned', 'paused', 'publish_job', 'published', 'error']) {
    stream.addEventListener(name, (event) => {
      events.value.push({ name, data: event.data })
      loadAll()
    })
  }
  stream.onerror = () => stream?.close()
}

onMounted(() => {
  loadAll()
  refreshTimer = window.setInterval(loadAll, 3000)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  if (stream) stream.close()
})
</script>

<template>
  <header class="topbar">
    <div>
      <p class="eyebrow">自媒体 Agent</p>
      <h1>{{ screenMode === 'board' ? '运营流程看板' : '统一审批 + 复盘详情' }}</h1>
    </div>
    <button v-if="screenMode === 'detail'" class="ghost" @click="goBoard">返回看板</button>
    <div class="status-message">{{ statusMessage }}</div>
  </header>

  <main v-if="screenMode === 'board'" class="board-screen">
    <aside class="queue-panel">
      <section class="setup-panel">
        <div>
          <p class="eyebrow">创建入口</p>
          <h2>平台和关键词</h2>
        </div>
        <label>平台</label>
        <select v-model="platform">
          <option v-for="option in platformOptions" :key="option" :value="option">{{ option }}</option>
        </select>
        <label>关键词</label>
        <input v-model="keywords" />

        <div class="sidebar-actions">
          <button class="ghost" @click="loadAll">刷新</button>
          <button @click="refreshTopics('keyword')" :disabled="busy">按关键词搜热点</button>
          <button @click="refreshTopics('auto')" :disabled="busy">自动搜热点</button>
          <button class="dark" @click="createWorkflow(null, false)" :disabled="busy">新建内容</button>
        </div>
      </section>

      <section class="agent-list">
        <div class="section-title">
          <span>岗位/Agent 队列</span>
          <strong>{{ agentQueue.length }}</strong>
        </div>
        <button
          v-for="agent in agentQueue"
          :key="agent.key"
          class="agent-row"
          :class="{ active: activeStage === agent.stage }"
          type="button"
          @click="focusAgentStage(agent.stage)"
        >
          <span class="agent-icon">{{ agent.name.slice(0, 1) }}</span>
          <span>
            <strong>{{ agent.name }}</strong>
            <small>{{ agent.route }}</small>
          </span>
          <b>{{ agent.count }}</b>
        </button>
      </section>
    </aside>

    <section class="flow-panel">
      <div class="board-heading">
        <div>
          <p class="eyebrow">内容流水线</p>
          <h2>自媒体运营中控台</h2>
        </div>
        <div class="board-tools">
          <span>自动刷新</span>
          <span>最近采集 {{ crawlRuns.length }}</span>
        </div>
      </div>

      <div class="kanban-scroll">
        <div class="kanban">
          <section
            v-for="column in columns"
            :key="column.key"
            class="kanban-column"
            :class="{ muted: activeStage !== 'all' && activeStage !== column.key }"
            :data-stage="column.key"
          >
            <header>
              <div>
                <h3>{{ column.title }}</h3>
                <small>{{ column.subtitle }}</small>
              </div>
              <b>{{ column.cards.length }}</b>
            </header>

            <article
              v-for="card in column.cards"
              :key="`${card.kind}-${card.id}`"
              class="content-card"
              :class="{ active: isSelected(card), candidate: card.kind === 'candidate' }"
              @click="openDetail(card)"
            >
              <div class="card-topline">
                <span>{{ card.kind === 'candidate' ? '热' : stageMeta[card.stage].code }}</span>
                <strong>{{ card.score || card.workflow?.status }}</strong>
              </div>
              <h4>{{ card.title }}</h4>
              <p>{{ card.summary }}</p>
              <div class="card-footer">
                <small>{{ card.kind === 'candidate' ? '点击生成待审批选题' : '点击进入统一审批' }}</small>
                <button
                  v-if="card.kind === 'candidate'"
                  class="ghost mini card-delete"
                  type="button"
                  @click.stop="deleteCandidate(card, $event)"
                  :disabled="busy"
                >
                  删除
                </button>
              </div>
            </article>

            <p v-if="!column.cards.length" class="empty-column">暂无内容</p>
          </section>
        </div>
      </div>
    </section>
  </main>

  <main v-else class="approval-screen">
    <section class="approval-shell">
      <div class="approval-header">
        <div>
          <p class="eyebrow">{{ flowLabel }}</p>
          <h2>{{ detailTitle }}</h2>
          <p>{{ detailSummary }}</p>
        </div>
        <span>{{ detailLoading ? '同步中' : latestEvent }}</span>
      </div>

      <section class="process-strip" aria-label="流程">
        <div
          v-for="step in processSteps"
          :key="step.key"
          :class="{ done: step.done, active: step.active }"
        >
          <small>{{ step.role }}</small>
          <strong>{{ step.title }}</strong>
        </div>
      </section>

      <section class="approval-info">
        <div>
          <small>流程</small>
          <strong>{{ flowLabel }}</strong>
        </div>
        <div>
          <small>受众</small>
          <strong>{{ detailAudience }}</strong>
        </div>
        <div>
          <small>负责人</small>
          <strong>{{ selectedRole }}</strong>
        </div>
        <div>
          <small>线程</small>
          <strong>{{ selectedWorkflow?.request_id?.slice(0, 14) || '暂无' }}</strong>
        </div>
        <div>
          <small>下一步</small>
          <strong>{{ nextStep }}</strong>
        </div>
        <div>
          <small>审批记录</small>
          <strong>{{ reviewNote }}</strong>
        </div>
      </section>

      <section class="handoff-row">
        <strong>岗位产出</strong>
        <span>{{ selectedTopic.title || selectedDraft.title || '等待产出' }}</span>
      </section>

      <section
        v-if="selectedStage === 'publish_ready' || selectedStage === 'published' || publishJobs.length"
        class="publish-status-grid"
      >
        <div>
          <small>发布状态</small>
          <strong>{{ latestPublishJob.status || '未同步' }}</strong>
        </div>
        <div>
          <small>公众号草稿 media_id</small>
          <strong>{{ latestPublishJob.external_media_id || '暂无' }}</strong>
        </div>
        <div>
          <small>发布 publish_id</small>
          <strong>{{ latestPublishJob.publish_id || '暂无' }}</strong>
        </div>
        <div>
          <small>失败原因</small>
          <strong>{{ latestPublishJob.error || '暂无' }}</strong>
        </div>
      </section>

      <label>退回意见或审批意见</label>
      <textarea v-model="reviewComment" placeholder="填写审批意见，退回时会作为返工说明。" />

      <div class="approval-actions">
        <button
          v-for="action in availableActions"
          :key="action.key"
          :class="{ ghost: action.variant === 'ghost', danger: action.variant === 'danger' }"
          @click="runApprovalAction(action)"
          :disabled="busy || !selectedWorkflow"
        >
          {{ action.label }}
        </button>
        <p v-if="!availableActions.length" class="empty-detail">当前阶段没有可执行动作。</p>
      </div>

      <section class="artifact-section">
        <h3>草稿</h3>
        <div v-if="selectedDraft.title || selectedDraft.body" class="artifact-box">
          <h4>{{ selectedDraft.title }}</h4>
          <p>{{ selectedDraft.body }}</p>
        </div>
        <p v-else class="empty-detail">当前阶段还没有生成草稿。</p>
      </section>

      <section class="artifact-section">
        <h3>图片</h3>
        <div v-if="selectedImages.cover_prompt" class="artifact-box image-output">
          <div>
            <strong>封面</strong>
            <p>{{ selectedImages.cover_prompt }}</p>
          </div>
          <div>
            <strong>正文配图</strong>
            <p>{{ Array.isArray(selectedImages.inline_prompts) ? selectedImages.inline_prompts.join(' / ') : selectedImages.inline_prompts }}</p>
          </div>
        </div>
        <p v-else class="empty-detail">当前阶段还没有生成图片提示词。</p>
      </section>

      <section class="artifact-section">
        <h3>复盘</h3>
        <div class="review-grid">
          <div>
            <strong>节点事件</strong>
            <p v-if="!events.length" class="empty-detail">暂无节点事件。</p>
            <div v-for="(event, index) in events" :key="index" class="event-row">
              <span>{{ event.event || event.name }}</span>
              <code>{{ event.node || event.data }}</code>
            </div>
          </div>
          <div>
            <strong>生成记录</strong>
            <p v-if="!posts.length" class="empty-detail">暂未写入生成稿。</p>
            <div v-for="post in posts" :key="post.id" class="post-row">
              <span>{{ post.title }}</span>
              <small>{{ post.created_at }}</small>
            </div>
          </div>
        </div>
      </section>
    </section>
  </main>
</template>
