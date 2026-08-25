<template>
  <div class="ai-screen-layout">

    <!-- ── 顶部：标题 + 多模型选择 + Prompt 开关 ── -->
    <div class="ai-screen-top">
      <div class="ai-top-title">
        <div class="step-head-icon" style="background:linear-gradient(135deg,#6366f1,#8b5cf6);width:32px;height:32px;border-radius:9px">
          <i class="fas fa-robot" style="font-size:0.85rem"></i>
        </div>
        <div>
          <h3 class="step-title" style="font-size:1rem;margin:0">AI 智能初筛</h3>
          <p class="step-subtitle" style="font-size:0.72rem;margin:0">基于纳排标准，大模型自动判断文献是否纳入</p>
        </div>
      </div>

      <!-- 多模型选择（多选 chip） -->
      <div class="ai-model-chips">
        <span class="text-xs text-gray-500 font-medium mr-2 whitespace-nowrap">选择模型：</span>
        <div v-if="s.aiModelsLoading" class="text-xs text-gray-400"><i class="fas fa-spinner fa-spin mr-1"></i>加载中...</div>
        <div v-else class="flex flex-wrap gap-1.5">
          <button
            v-for="m in s.aiModelsList"
            :key="m.id"
            @click="!s.isProcessing && m.configured && toggleModel(m)"
            :class="[
              'model-chip',
              isModelSelected(m.id) ? 'model-chip-active' : '',
              !m.configured ? 'model-chip-disabled' : '',
            ]"
          >
            <span>
              <span v-if="m.logo === 'deepseek'">🤖</span>
              <span v-else-if="m.logo === 'doubao'">🫘</span>
              <span v-else-if="m.logo === 'qwen'">🌙</span>
              <span v-else>🧠</span>
            </span>
            {{ m.name }}
            <i v-if="isModelSelected(m.id)" class="fas fa-check ml-1 text-indigo-500" style="font-size:0.65rem"></i>
            <span v-if="!m.configured" class="text-[10px] text-gray-400 ml-1">（未配置）</span>
          </button>
        </div>
        <span v-if="selectedModels.length > 1" class="ml-2 text-xs text-amber-600 whitespace-nowrap">
          <i class="fas fa-info-circle mr-0.5"></i>已选 {{ selectedModels.length }} 个模型，预估消耗 ×{{ selectedModels.length }}
        </span>
      </div>

      <!-- Prompt 折叠开关（暂时隐藏）-->
      <!-- <div class="ai-prompt-toggle">
        <button @click="promptPanelOpen = !promptPanelOpen" class="prompt-toggle-btn">
          <i class="fas fa-sliders-h mr-1"></i>Prompt
          <span v-if="s.useCustomPrompt" class="badge badge-purple ml-1" style="font-size:0.65rem;padding:1px 6px">自定义</span>
          <i :class="promptPanelOpen ? 'fa-chevron-up' : 'fa-chevron-down'" class="fas ml-1 text-xs text-gray-400"></i>
        </button>
      </div> -->
    </div>

    <!-- Prompt 展开区（暂时隐藏，功能保留待后续开放）-->
    <!-- <div v-show="promptPanelOpen" class="ai-prompt-panel step-collapse-body space-y-2">
      ...
    </div> -->

    <!-- ── 主体：三段式垂直布局 ── -->
    <div class="ai-screen-body">

      <!-- 段一：进度 / 模型状态区 -->
      <div v-if="s.isProcessing || (s.latestAiScreenTask && ['completed','stopped','running','pending','stopping','queuing'].includes(s.latestAiScreenTask.status))" class="ai-progress-section">
        <div class="ai-progress-header">
          <span class="font-semibold text-sm text-gray-700">
            <i class="fas fa-tasks mr-1.5 text-indigo-400"></i>筛选进度
          </span>
          <span class="text-xs text-gray-500">
            {{ s.screeningProgress.processed }} / {{ s.screeningProgress.total }} 篇
            ({{ s.screeningProgress.percent }}%)
          </span>
        </div>

        <!-- 单模型：简洁进度条 -->
        <div v-if="selectedModels.length <= 1" class="model-progress-row">
          <span class="model-progress-label text-xs text-gray-500 truncate">
            {{ selectedModels[0]?.name || '当前模型' }}
          </span>
          <div class="model-progress-track">
            <div class="model-progress-fill bg-indigo-500"
                 :style="{ width: s.screeningProgress.percent + '%' }"></div>
          </div>
          <span class="model-progress-pct text-xs font-semibold text-indigo-600">
            {{ s.screeningProgress.percent }}%
          </span>
          <span class="model-progress-status">
            <i v-if="s.latestAiScreenTask?.status === 'completed'" class="fas fa-check-circle text-green-500"></i>
            <i v-else-if="s.latestAiScreenTask?.status === 'stopped'" class="fas fa-pause-circle text-yellow-500"></i>
            <i v-else-if="s.isProcessing" class="fas fa-spinner fa-spin text-indigo-400"></i>
            <i v-else class="fas fa-hourglass-half text-gray-400"></i>
          </span>
        </div>

        <!-- 多模型：每个模型一行 -->
        <template v-else>
          <div v-for="m in selectedModels" :key="m.id" class="model-progress-row">
            <span class="model-progress-label text-xs text-gray-600 truncate font-medium">
              <span v-if="m.logo === 'deepseek'">🤖</span>
              <span v-else-if="m.logo === 'doubao'">🫘</span>
              <span v-else-if="m.logo === 'qwen'">🌙</span>
              <span v-else>🧠</span>
              {{ m.name }}
            </span>
            <div class="model-progress-track">
              <div class="model-progress-fill"
                   :style="{ width: getModelProgress(m.id).pct + '%', background: getModelProgress(m.id).color }"></div>
            </div>
            <span class="model-progress-pct text-xs font-semibold" :style="{ color: getModelProgress(m.id).color }">
              {{ getModelProgress(m.id).pct }}%
            </span>
            <span class="model-progress-status text-xs" :class="getModelProgress(m.id).statusClass">
              {{ getModelProgress(m.id).statusLabel }}
            </span>
          </div>
        </template>

        <!-- 排队中 -->
        <div v-if="s.latestAiScreenTask?.status === 'queuing'" class="queue-status-bar mt-2">
          <div class="flex items-center gap-2 text-amber-700">
            <i class="fas fa-clock fa-spin"></i>
            <span class="font-semibold text-sm">排队等待中</span>
            <span v-if="queueInfo.position > 0" class="text-sm">— 第 <b>{{ queueInfo.position }}</b> 位</span>
          </div>
          <p class="text-xs text-amber-600 mt-0.5">系统将自动为您分配资源，无需手动操作</p>
        </div>
      </div>

      <!-- 段二：结果统计卡片 -->
      <div v-if="s.aiScreenStats || s.latestAiScreenTask?.status === 'completed'" class="ai-stats-section">
        <div class="ai-stats-grid" :class="hasConflict ? 'ai-stats-grid-4' : 'ai-stats-grid-3'">
          <div class="ai-stat-card ai-stat-included">
            <div class="ai-stat-icon"><i class="fas fa-check-circle"></i></div>
            <div class="ai-stat-num">{{ s.aiScreenStats?.included_count ?? '—' }}</div>
            <div class="ai-stat-label">✅ 纳入</div>
          </div>
          <div class="ai-stat-card ai-stat-excluded">
            <div class="ai-stat-icon"><i class="fas fa-times-circle"></i></div>
            <div class="ai-stat-num">{{ s.aiScreenStats?.excluded_count ?? '—' }}</div>
            <div class="ai-stat-label">❌ 排除</div>
          </div>
          <div v-if="hasConflict" class="ai-stat-card ai-stat-conflict">
            <div class="ai-stat-icon"><i class="fas fa-exclamation-triangle"></i></div>
            <div class="ai-stat-num">{{ s.aiScreenStats?.conflict_count ?? '—' }}</div>
            <div class="ai-stat-label">⚠️ 分歧</div>
          </div>
          <div class="ai-stat-card ai-stat-pending">
            <div class="ai-stat-icon"><i class="fas fa-hourglass-half"></i></div>
            <div class="ai-stat-num">{{ s.aiScreenStats?.pending_count ?? s.pendingTotal ?? '—' }}</div>
            <div class="ai-stat-label">⏳ 待筛</div>
          </div>
        </div>
        <div v-if="s.latestAiScreenTask?.result?.token_stats" class="ai-token-summary">
          <i class="fas fa-coins mr-1 text-amber-500"></i>
          本次共消耗 <b>{{ s.latestAiScreenTask.result.token_stats.total_tokens?.toLocaleString() }}</b> tokens
          ≈ <b>{{ s.latestAiScreenTask.result.token_stats.credits_estimate }}</b> credits
        </div>
        <!-- 展示本次筛选使用的模型 -->
        <div class="ai-used-models" v-if="usedModels.length">
          <i class="fas fa-layer-group mr-1 text-indigo-400"></i>
          本次使用模型：
          <span v-for="m in usedModels" :key="m.id" class="used-model-chip">
            <span v-if="m.logo === 'deepseek'">🤖</span>
            <span v-else-if="m.logo === 'doubao'">🫘</span>
            <span v-else-if="m.logo === 'qwen'">🌙</span>
            <span v-else>🧠</span>
            {{ m.name }}
          </span>
        </div>
      </div>

      <!-- 段三：操作区 -->
      <div class="ai-action-area">
        <!-- 余额信息条 -->
        <div class="billing-bar" :class="billing.sufficient === false ? 'billing-bar-danger' : 'billing-bar-ok'">
          <span class="billing-item">
            <i class="fas fa-coins mr-1"></i>余额：<b>{{ billing.balance ?? '...' }}</b> credits
          </span>
          <span class="billing-item" v-if="s.pendingTotal > 0">
            预估：<b>{{ billing.estimated ?? '...' }}</b> credits（{{ s.pendingTotal }} 篇 × {{ selectedModels.length }} 模型）
          </span>
          <span v-if="billing.sufficient === false" class="billing-warn">
            <i class="fas fa-exclamation-triangle mr-0.5"></i>余额不足
          </span>
        </div>

        <!-- 按钮区 -->
        <template v-if="!s.latestAiScreenTask || ['completed','failed'].includes(s.latestAiScreenTask.status)">
          <button @click="startScreening"
                  :disabled="s.isProcessing || billing.sufficient === false || selectedModels.length === 0"
                  :class="s.latestAiScreenTask?.status === 'completed' ? 'bg-amber-600 hover:bg-amber-700' : 'bg-indigo-600 hover:bg-indigo-700'"
                  class="ai-action-btn text-white">
            <i v-if="s.isProcessing" class="fas fa-spinner fa-spin mr-2"></i>
            {{ s.isProcessing ? 'AI 正在筛选...' : s.latestAiScreenTask?.status === 'completed' ? '重新筛选' : '启动 AI 筛选' }}
          </button>
          <p v-if="billing.sufficient === false" class="text-xs text-red-500 text-center">余额不足，请联系管理员充值</p>
          <p v-if="selectedModels.length === 0" class="text-xs text-orange-500 text-center">请至少选择一个已配置的模型</p>
        </template>
        <template v-else-if="s.latestAiScreenTask.status === 'queuing'">
          <button disabled class="ai-action-btn bg-amber-400 text-white cursor-wait">
            <i class="fas fa-clock fa-spin mr-2"></i>排队中（第 {{ queueInfo.position || '?' }} 位）
          </button>
        </template>
        <template v-else-if="s.latestAiScreenTask.status === 'pending'">
          <button disabled class="ai-action-btn bg-gray-400 text-white cursor-wait">
            <i class="fas fa-hourglass-half fa-spin mr-2"></i>初始化中...
          </button>
        </template>
        <template v-else-if="s.latestAiScreenTask.status === 'running'">
          <button @click="stopTask" class="ai-action-btn bg-red-600 hover:bg-red-700 text-white">
            <i class="fas fa-stop mr-2"></i>暂停筛选
          </button>
        </template>
        <template v-else-if="s.latestAiScreenTask.status === 'stopping'">
          <button disabled class="ai-action-btn bg-yellow-500 text-white cursor-wait">
            <i class="fas fa-spinner fa-spin mr-2"></i>正在停止...
          </button>
        </template>
        <template v-else-if="s.latestAiScreenTask.status === 'stopped'">
          <button @click="resumeTask" class="ai-action-btn bg-green-600 hover:bg-green-700 text-white">
            <i class="fas fa-play mr-2"></i>继续筛选
          </button>
          <button @click="abandonTask" class="ai-action-btn bg-gray-400 hover:bg-gray-500 text-white mt-1">
            <i class="fas fa-trash mr-2"></i>放弃任务
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useScreeningStore } from '@/stores/screening'
import { useProjectStore } from '@/stores/project'
import { useTaskStore } from '@/stores/task'
import http, { httpNoTimeout } from '@/api/http'
import { extractListData } from '@/utils/format'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const promptPanelOpen = ref(false)
const promptSaveStatus = ref('')
const defaultPromptPreview = ref('（加载中...）')
const billing = ref({ balance: null, estimated: null, sufficient: null })
const queueInfo = ref({ position: 0, queueLength: 0, slotsNeeded: 0, slotsFree: 0, slotsTotal: 0 })

// 多模型选择（多选，兼容旧的单选 selectedAiModel）
const selectedModels = computed(() => {
  const ids = s.selectedAiModels?.length ? s.selectedAiModels : (s.selectedAiModel ? [s.selectedAiModel] : [])
  return ids.map(id => s.aiModelsList.find(m => m.id === id)).filter(Boolean)
})

function isModelSelected(id) {
  if (s.selectedAiModels?.length) return s.selectedAiModels.includes(id)
  return s.selectedAiModel === id
}

function toggleModel(m) {
  if (s.isProcessing) return
  if (!s.selectedAiModels) s.selectedAiModels = []
  const idx = s.selectedAiModels.indexOf(m.id)
  if (idx >= 0) {
    // 至少保留 1 个
    if (s.selectedAiModels.length === 1) return
    s.selectedAiModels = s.selectedAiModels.filter(id => id !== m.id)
  } else {
    s.selectedAiModels = [...s.selectedAiModels, m.id]
  }
  s.selectedAiModel = s.selectedAiModels[0] || ''
  loadBilling()
}

// 是否有分歧文献（多模型时才显示）
const hasConflict = computed(() => {
  return (s.aiScreenStats?.conflict_count ?? 0) > 0 || selectedModels.value.length > 1
})

// 已完成任务实际使用的模型列表（从任务 config 读，不依赖当前选择状态）
const usedModels = computed(() => {
  const task = s.latestAiScreenTask
  if (!task || task.status !== 'completed') return []
  const ids = task.config?.ai_models || (task.config?.ai_model ? [task.config.ai_model] : [])
  return ids.map(id => {
    const found = s.aiModelsList.find(m => m.id === id)
    return found || { id, name: id, logo: '' }
  })
})

// 多模型进度（单模型时使用整体进度）
function getModelProgress(modelId) {
  const modelProgress = s.latestAiScreenTask?.config?.model_progress
  if (modelProgress && modelProgress[modelId]) {
    const mp = modelProgress[modelId]
    const total = mp.total || 1
    const pct = Math.round((mp.current / total) * 100)
    const statusMap = {
      completed: { statusClass: 'text-green-600', statusLabel: '✓ 完成', color: '#22c55e' },
      running:   { statusClass: 'text-indigo-600', statusLabel: '⟳ 进行中', color: '#6366f1' },
      waiting:   { statusClass: 'text-gray-400', statusLabel: '⏳ 等待中', color: '#94a3b8' },
    }
    return { pct, color: (statusMap[mp.status] || statusMap.waiting).color, ...(statusMap[mp.status] || statusMap.waiting) }
  }
  // 降级：使用整体进度
  const pct = Math.round(s.screeningProgress.percent || 0)
  const isRunning = s.isProcessing
  const isCompleted = s.latestAiScreenTask?.status === 'completed'
  return {
    pct,
    color: isCompleted ? '#22c55e' : isRunning ? '#6366f1' : '#94a3b8',
    statusClass: isCompleted ? 'text-green-600' : isRunning ? 'text-indigo-600' : 'text-gray-400',
    statusLabel: isCompleted ? '✓ 完成' : isRunning ? '⟳ 进行中' : '⏳ 等待中',
  }
}

// ── 初始化 ───────────────────────────────────────────────────
const PAGE_SIZE = 50

onMounted(async () => {
  if (s.criteriaList.length === 0) {
    const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
    const step  = stage?.steps?.find((st) => st.step_key === 'criteria')
    if (step?.metadata?.criteria?.length) s.criteriaList = step.metadata.criteria
  }
  // 先并行加载模型 + 刷新最近任务（刷新页面后恢复状态用）
  await Promise.all([
    loadAiModels(),
    loadPrompt(),
    taskStore.fetchRecentTasks(project.currentProject?.id, project.stagesData),
  ])
  // syncLatestAiTask 依赖 aiModelsList 和 recentTasks，必须在二者都加载完后调用
  await loadPending()
  await loadAiScreenStats()
  syncLatestAiTask()
  loadBilling()
})

// ── 计费 ─────────────────────────────────────────────────────
async function loadBilling() {
  try {
    const balRes = await http.get('/billing/balance/')
    const balData = balRes.data
    if (balData.is_unlimited) {
      billing.value = { balance: '∞', estimated: null, sufficient: true }
      return
    }
    billing.value.balance = balData.balance
    if (s.pendingTotal > 0) {
      const modelCount = selectedModels.value.length || 1
      const estRes = await http.get(`/billing/estimate/?ref_count=${s.pendingTotal}&model_count=${modelCount}`)
      billing.value.estimated = estRes.data.estimated_credits
      billing.value.sufficient = estRes.data.sufficient
    } else {
      billing.value.estimated = null
      billing.value.sufficient = true
    }
  } catch (e) {
    console.error('加载余额失败', e)
  }
}

// ── 模型加载 ──────────────────────────────────────────────────
async function loadAiModels() {
  s.aiModelsLoading = true
  try {
    const res = await http.get('/ai-models/')
    s.aiModelsList = res.data
    const def = s.aiModelsList.find((m) => m.is_default && m.configured) || s.aiModelsList.find((m) => m.configured)
    // 仅在尚未有选中模型时才初始化默认值
    if (!s.selectedAiModels || s.selectedAiModels.length === 0) {
      if (def) {
        s.selectedAiModels = [def.id]
        s.selectedAiModel = def.id
      }
    }
  } catch (e) {
    console.error('加载模型列表失败', e)
  } finally {
    s.aiModelsLoading = false
  }
}

// ── Prompt ──────────────────────────────────────────────────
async function loadPrompt() {
  if (!project.currentProject) return
  try {
    const res = await http.get(`/projects/${project.currentProject.id}/get_prompt/`)
    s.useCustomPrompt = res.data.use_custom_prompt || false
    s.customPromptText = res.data.custom_prompt || ''
    if (res.data.default_prompt) defaultPromptPreview.value = res.data.default_prompt
  } catch {}
}

async function savePrompt() {
  if (!project.currentProject) return
  if (s.useCustomPrompt && !s.customPromptText.includes('{screening_criteria}')) return
  promptSaveStatus.value = ''
  try {
    await http.post(`/projects/${project.currentProject.id}/save_prompt/`, {
      custom_prompt: s.customPromptText,
      use_custom_prompt: s.useCustomPrompt,
    })
    promptSaveStatus.value = 'ok'
    await taskStore.fetchActivityLogs(project.currentProject.id)
  } catch { promptSaveStatus.value = 'error' }
  setTimeout(() => { promptSaveStatus.value = '' }, 3000)
}

async function resetPrompt() {
  if (!project.currentProject) return
  try {
    await http.post(`/projects/${project.currentProject.id}/reset_prompt/`)
    s.useCustomPrompt = false
    s.customPromptText = ''
    promptSaveStatus.value = 'ok'
    setTimeout(() => { promptSaveStatus.value = '' }, 2000)
  } catch { promptSaveStatus.value = 'error' }
}

// ── 文件 + 统计 ───────────────────────────────────────────────
async function loadPending(page) {
  if (!project.currentProject) return
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const pageNum = page ?? s.pendingPage
  const offset = pageNum * PAGE_SIZE
  const pid = project.currentProject.id

  let sourceStep = null
  for (const key of ['dedup', 'parse']) {
    const step = stage.steps.find((st) => st.step_key === key)
    if (!step) continue
    try {
      const probe = await http.get(`/files/?project=${pid}&step=${step.id}&data_category=intermediate&limit=1&offset=0`)
      if ((probe.data.total ?? 0) > 0) { sourceStep = step; break }
    } catch {}
  }
  if (!sourceStep) { s.pendingTotal = 0; return }
  try {
    const res = await http.get(`/files/?project=${pid}&step=${sourceStep.id}&data_category=intermediate&exclude_screened=1&limit=${PAGE_SIZE}&offset=${offset}`)
    const data = res.data
    s.pendingFiles = extractListData(data)
    s.pendingTotal = data.total ?? s.pendingFiles.length
    if (page !== undefined) s.pendingPage = page
    if (page === undefined || page === 0) loadBilling()
  } catch { s.pendingTotal = 0 }
}

async function loadAiScreenStats() {
  if (!project.currentProject) return
  try {
    const res = await http.get(`/projects/${project.currentProject.id}/ai_screen_stats/`)
    s.aiScreenStats = res.data
  } catch {}
}

function syncLatestAiTask() {
  const aiTask = taskStore.recentTasks.find((t) => t.task_type === 'ai_screen')

  if (!aiTask) {
    // 当前项目没有任何 AI 初筛任务：重置模型选择到本项目的默认值，避免跨项目污染
    const def = s.aiModelsList.find((m) => m.is_default && m.configured) || s.aiModelsList.find((m) => m.configured)
    if (def) {
      s.selectedAiModels = [def.id]
      s.selectedAiModel  = def.id
    } else {
      s.selectedAiModels = []
      s.selectedAiModel  = null
    }
    return
  }

  s.latestAiScreenTask = aiTask

  // ── 恢复上次多模型选择（从任务 config.ai_models 中读取）──
  const lastModels = aiTask.config?.ai_models
  if (lastModels?.length && s.aiModelsList.length) {
    const validIds = lastModels.filter(id => s.aiModelsList.find(m => m.id === id && m.configured))
    if (validIds.length) {
      s.selectedAiModels = validIds
      s.selectedAiModel  = validIds[0]
    }
  }

  s.screeningProgressValue = aiTask.progress_percentage || 0
  const sp = aiTask.config?.screen_progress
  if (sp) {
    s.totalRefs = sp.total_refs || s.totalRefs
    s.processedCount = sp.processed_refs || 0
  }
  // 任务运行中：恢复轮询
  if (['running', 'pending', 'stopping', 'queuing'].includes(aiTask.status)) {
    s.isProcessing = aiTask.status === 'running'
    pollAiScreening(aiTask.id)
  }
  // 已完成：确保统计数据也已加载
  if (aiTask.status === 'completed' && !s.aiScreenStats) {
    loadAiScreenStats()
  }
}

// ── 任务操作 ─────────────────────────────────────────────────
async function startScreening() {
  if (s.criteriaList.length === 0) { alert('请先设置纳排标准'); return }
  if (selectedModels.value.length === 0) { alert('请至少选择一个已配置的模型'); return }
  s.isProcessing = true
  try {
    await clearAiScreenResults()
    const modelIds = selectedModels.value.map(m => m.id)
    const res = await httpNoTimeout.post('/tasks/', {
      project: project.currentProject.id,
      task_type: 'ai_screening',
      config: {
        criteria:  s.criteriaList,
        ai_model:  modelIds[0],       // 向后兼容
        ai_models: modelIds,          // 多模型列表
      },
    })
    s.latestAiScreenTask = res.data
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    pollAiScreening(res.data.id)
  } catch (err) {
    alert(`启动失败: ${err.response?.data?.error || err.message}`)
    s.isProcessing = false
  }
}

async function stopTask() {
  if (!s.latestAiScreenTask) return
  if (!confirm('确定暂停当前筛选任务？')) return
  try {
    await httpNoTimeout.post(`/tasks/${s.latestAiScreenTask.id}/stop/`)
    alert('任务已暂停')
    s.isProcessing = false
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    await project.fetchStages(project.currentProject.id)
  } catch (err) { alert(`暂停失败: ${err.response?.data?.error || err.message}`) }
}

async function resumeTask() {
  if (!s.latestAiScreenTask) return
  try {
    const res = await httpNoTimeout.post(`/tasks/${s.latestAiScreenTask.id}/resume/`)
    const newTask = res.data.task || res.data
    s.latestAiScreenTask = newTask
    s.screeningProgressValue = newTask.progress_percentage || 0
    s.totalRefs = newTask.config?.screen_progress?.total_refs || s.totalRefs || s.pendingTotal
    s.isProcessing = true
    pollAiScreening(newTask.id)
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
  } catch (err) { alert(`继续失败: ${err.response?.data?.error || err.message}`) }
}

async function abandonTask() {
  if (!s.latestAiScreenTask) return
  if (!confirm('确定放弃此任务？已筛选结果将被清除。')) return
  try {
    await clearAiScreenResults()
    await http.delete(`/tasks/${s.latestAiScreenTask.id}/`)
    s.latestAiScreenTask = null
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    alert('任务已放弃，筛选结果已清除')
  } catch (err) { alert(`放弃失败: ${err.response?.data?.error || err.message}`) }
}

async function clearAiScreenResults() {
  if (!project.currentProject) return
  try { await httpNoTimeout.post(`/projects/${project.currentProject.id}/clear_ai_screen_results/`) } catch {}
}

async function pollAiScreening(taskId) {
  let pollCount = 0
  const poll = async () => {
    pollCount++
    try {
      const res = await http.get(`/tasks/${taskId}/`)
      const task = res.data
      s.latestAiScreenTask = task
      const status = task.status
      s.screeningProgressValue = task.progress_percentage || 0
      const sp = task.config?.screen_progress
      if (sp) {
        s.totalRefs = sp.total_refs || s.totalRefs
        s.processedCount = sp.processed_refs || 0
      }

      if (['running', 'pending', 'stopping', 'queuing'].includes(status)) {
        const interval = status === 'queuing' ? 5000 : 2000
        if (status === 'queuing') {
          const qi = task.config?.queue_info || {}
          queueInfo.value = {
            position: qi.position || 0,
            queueLength: qi.queue_length || 0,
            slotsNeeded: qi.slots_needed || 0,
            slotsFree: qi.slots_free || 0,
            slotsTotal: qi.slots_total || queueInfo.value.slotsTotal,
          }
        }
        if (pollCount % 5 === 0 && status !== 'queuing') {
          loadAiScreenStats()
        }
        setTimeout(poll, interval)
      } else {
        s.isProcessing = false
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        await project.fetchStages(project.currentProject.id)
        if (status === 'completed') {
          await Promise.all([loadPending(), loadAiScreenStats()])
          loadBilling()
          window.dispatchEvent(new CustomEvent('app:balance-changed'))
          alert('AI初筛完成！')
        } else if (status === 'stopped') {
          loadAiScreenStats()
        } else {
          alert(`AI初筛失败: ${task.error_message || '任务执行失败'}`)
        }
      }
    } catch (err) {
      console.error('轮询AI初筛状态失败', err)
      s.isProcessing = false
    }
  }
  await poll()
}
</script>

<style scoped>
/* ── 整体布局 ── */
.ai-screen-layout {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 16px;
  overflow-y: auto;
}

/* ── 顶部栏 ── */
.ai-screen-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.ai-top-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.ai-model-chips {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
  gap: 4px;
}
.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #fff;
  font-size: 0.78rem;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.model-chip:hover { border-color: #a5b4fc; color: #4338ca; }
.model-chip-active { border-color: #6366f1; background: #eef2ff; color: #4338ca; font-weight: 600; }
.model-chip-disabled { opacity: 0.5; cursor: not-allowed; }
.ai-prompt-toggle { flex-shrink: 0; }
.prompt-toggle-btn {
  display: flex; align-items: center;
  padding: 4px 12px; border-radius: 8px;
  border: 1px solid #e2e8f0; background: #f8fafc;
  font-size: 0.78rem; color: #64748b; cursor: pointer;
}
.prompt-toggle-btn:hover { border-color: #a5b4fc; color: #4338ca; }

/* Prompt 面板 */
.ai-prompt-panel {
  margin-bottom: 8px; padding: 12px 16px;
  border-radius: 12px; border: 1px solid #e2e8f0; background: #f8fafc;
}

/* ── 主体三段式 ── */
.ai-screen-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 进度区 */
.ai-progress-section {
  background: #fafbff;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  padding: 14px 16px;
}
.ai-progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.model-progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.model-progress-label { width: 120px; flex-shrink: 0; }
.model-progress-track { flex: 1; height: 8px; background: #f1f5f9; border-radius: 99px; overflow: hidden; }
.model-progress-fill { height: 100%; border-radius: 99px; transition: width .5s ease; }
.model-progress-pct { width: 36px; text-align: right; flex-shrink: 0; }
.model-progress-status { width: 60px; text-align: right; flex-shrink: 0; }

/* 结果统计 */
.ai-stats-section {
  background: linear-gradient(135deg, #faf5ff, #eef2ff);
  border: 1px solid #ddd6fe;
  border-radius: 12px;
  padding: 14px 16px;
}
.ai-stats-grid {
  display: grid;
  gap: 10px;
  margin-bottom: 10px;
}
.ai-stats-grid-3 { grid-template-columns: repeat(3, 1fr); }
.ai-stats-grid-4 { grid-template-columns: repeat(4, 1fr); }
.ai-stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 8px;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.ai-stat-icon { font-size: 1.1rem; }
.ai-stat-num { font-size: 1.4rem; font-weight: 700; line-height: 1.1; }
.ai-stat-label { font-size: 0.72rem; color: #94a3b8; }
.ai-stat-included .ai-stat-icon { color: #22c55e; }
.ai-stat-included .ai-stat-num  { color: #16a34a; }
.ai-stat-excluded .ai-stat-icon { color: #ef4444; }
.ai-stat-excluded .ai-stat-num  { color: #dc2626; }
.ai-stat-conflict .ai-stat-icon { color: #f59e0b; }
.ai-stat-conflict .ai-stat-num  { color: #d97706; }
.ai-stat-pending  .ai-stat-icon { color: #94a3b8; }
.ai-stat-pending  .ai-stat-num  { color: #64748b; }
.ai-token-summary {
  font-size: 0.75rem;
  color: #7c3aed;
  background: #ede9fe;
  border-radius: 6px;
  padding: 5px 10px;
  display: inline-block;
}
.ai-used-models {
  font-size: 0.75rem;
  color: #475569;
  margin-top: 6px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.used-model-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 99px;
  background: #eef2ff;
  color: #4338ca;
  font-size: 0.72rem;
  font-weight: 500;
  border: 1px solid #c7d2fe;
}

/* 操作区 */
.ai-action-area {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ai-action-btn {
  width: 100%; padding: 10px 16px; border-radius: 10px;
  font-size: 0.9rem; font-weight: 600; border: none;
  cursor: pointer; transition: all .15s;
}
.ai-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 余额栏 */
.billing-bar {
  display: flex; align-items: center; flex-wrap: wrap;
  gap: 8px; padding: 6px 10px; border-radius: 8px;
  font-size: 0.78rem; border: 1px solid #e2e8f0;
}
.billing-bar-ok { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
.billing-bar-danger { background: #fff1f2; border-color: #fecdd3; color: #be123c; }
.billing-item { white-space: nowrap; }
.billing-warn { font-weight: 600; margin-left: auto; }

/* 排队状态 */
.queue-status-bar {
  background: #fffbeb; border: 1px solid #fbbf24;
  border-radius: 6px; padding: 8px 12px;
}
</style>
