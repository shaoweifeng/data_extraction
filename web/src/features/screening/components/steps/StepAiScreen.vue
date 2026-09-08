<template>
  <div class="ai-screen-layout">

    <!-- ── 左栏：待筛/已筛文献列表 (40%) ── -->
    <div class="ai-left-panel">
      <div class="ai-left-header">
        <div class="step-head-icon" style="background:linear-gradient(135deg,#6366f1,#8b5cf6);width:28px;height:28px;border-radius:8px;flex-shrink:0">
          <i class="fas fa-robot" style="font-size:0.75rem"></i>
        </div>
        <div>
          <h3 class="step-title" style="font-size:0.92rem;margin:0">AI 智能初筛</h3>
          <p class="step-subtitle" style="font-size:0.7rem;margin:0">基于纳排标准，大模型自动筛选</p>
        </div>
      </div>

      <!-- Tab 切换（同时作统计展示） -->
      <div class="ai-list-tabs">
        <button
          class="ai-list-tab"
          :class="{ active: listTab === 'pending' }"
          @click="switchListTab('pending')"
        >
          <i class="fas fa-hourglass-half"></i>
          待筛选
          <span class="ai-list-tab-count">{{ s.pendingTotal }}</span>
        </button>
        <button
          class="ai-list-tab"
          :class="{ active: listTab === 'screened' }"
          @click="switchListTab('screened')"
        >
          <i class="fas fa-check-circle"></i>
          已筛选
          <span class="ai-list-tab-count">{{ screenedCount }}</span>
        </button>
        <div class="ai-list-tab-total">共 {{ totalRefCount }} 篇</div>
      </div>

      <!-- 文献列表 -->
      <div class="ai-refs-list">
        <div v-if="s.pendingTotal === 0 && screenedCount === 0" class="ai-refs-empty">
          <i class="fas fa-inbox"></i>
          <span>暂无文献，请先完成文献解析步骤</span>
        </div>
        <template v-else>
          <!-- 待筛 tab -->
          <template v-if="listTab === 'pending'">
            <div v-if="s.pendingFiles.length === 0" class="ai-refs-group-empty">已全部筛完 🎉</div>
            <div v-for="f in s.pendingFiles" :key="f.id" class="ai-ref-item">
              <div class="ai-ref-name">{{ f.filename }}</div>
            </div>
            <div class="ai-refs-pagination" v-if="pendingTotalPages > 1">
              <button class="ai-pg-btn" :disabled="pendingListPage <= 1" @click="goPendingPage(pendingListPage - 1)">
                <i class="fas fa-chevron-left"></i>
              </button>
              <span class="ai-pg-info">{{ pendingListPage }} / {{ pendingTotalPages }}</span>
              <button class="ai-pg-btn" :disabled="pendingListPage >= pendingTotalPages" @click="goPendingPage(pendingListPage + 1)">
                <i class="fas fa-chevron-right"></i>
              </button>
            </div>
          </template>

          <!-- 已筛 tab -->
          <template v-if="listTab === 'screened'">
            <div v-if="screenedCount === 0" class="ai-refs-group-empty">暂无已筛文献</div>
            <div v-for="f in pagedScreenedFiles" :key="f.source_xml || f.id" class="ai-ref-item ai-ref-item-done">
              <div class="ai-ref-name">{{ f.title || f.filename || f.source_xml }}</div>
              <span class="ai-ref-decision" :class="decisionClass(f)">{{ decisionShort(f) }}</span>
            </div>
            <div class="ai-refs-pagination" v-if="screenedTotalPages > 1">
              <button class="ai-pg-btn" :disabled="screenedListPage <= 1" @click="goScreenedPage(screenedListPage - 1)">
                <i class="fas fa-chevron-left"></i>
              </button>
              <span class="ai-pg-info">{{ screenedListPage }} / {{ screenedTotalPages }}</span>
              <button class="ai-pg-btn" :disabled="screenedListPage >= screenedTotalPages" @click="goScreenedPage(screenedListPage + 1)">
                <i class="fas fa-chevron-right"></i>
              </button>
            </div>
          </template>
        </template>
      </div>
    </div>

    <!-- ── 右栏：模型选择 + 进度 + 操作 (60%) ── -->
    <div class="ai-right-panel">

      <!-- 模型选择区 -->
      <div class="ai-model-section">
        <div class="ai-section-label">
          <i class="fas fa-brain text-indigo-400 mr-1.5"></i>选择模型
          <span v-if="selectedModels.length > 1" class="ml-2 text-xs text-amber-600">
            <i class="fas fa-info-circle mr-0.5"></i>已选 {{ selectedModels.length }} 个，预估消耗 ×{{ selectedModels.length }}
          </span>
        </div>

        <div v-if="s.aiModelsLoading" class="text-xs text-gray-400 py-2">
          <i class="fas fa-spinner fa-spin mr-1"></i>加载中...
        </div>

        <!-- 按厂家分组展示 -->
        <div v-else class="ai-provider-list">
          <div v-for="provider in s.aiModelsList" :key="provider.id" class="ai-provider-group">
            <!-- 厂家标题行 -->
            <div class="ai-provider-header">
              <span class="ai-provider-logo">
                <span v-if="provider.logo === 'deepseek'">🤖</span>
                <span v-else-if="provider.logo === 'doubao'">🫘</span>
                <span v-else-if="provider.logo === 'qwen'">🌙</span>
                <span v-else>🧠</span>
              </span>
              <span class="ai-provider-name">{{ provider.name }}</span>
              <span v-if="!provider.configured" class="ai-provider-unconfigured">未配置</span>
            </div>
            <!-- 子模型列表 -->
            <div class="ai-submodel-list">
              <button
                v-for="sm in provider.sub_models"
                :key="sm.id"
                @click="!s.isProcessing && sm.configured && toggleModel(sm)"
                :class="[
                  'ai-submodel-btn',
                  isModelSelected(sm.id) ? 'ai-submodel-btn-active' : '',
                  !sm.configured ? 'ai-submodel-btn-disabled' : '',
                ]"
                :title="sm.description"
              >
                <span class="ai-submodel-name">{{ sm.name }}</span>
                <span class="ai-submodel-desc">{{ sm.description }}</span>
                <i v-if="isModelSelected(sm.id)" class="fas fa-check ai-submodel-check"></i>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Prompt 设置区 -->
      <div class="ai-prompt-section">
        <button
          @click="promptPanelOpen = !promptPanelOpen"
          class="ai-prompt-toggle-btn"
          :class="{ 'ai-prompt-toggle-btn-active': promptPanelOpen }"
        >
          <span class="flex items-center gap-1.5">
            <i class="fas fa-sliders-h text-indigo-400"></i>
            <span class="font-medium">Prompt 设置</span>
            <span v-if="s.useCustomPrompt" class="ai-prompt-badge">自定义</span>
          </span>
          <i :class="promptPanelOpen ? 'fa-chevron-up' : 'fa-chevron-down'" class="fas text-gray-400 text-xs"></i>
        </button>

        <div v-show="promptPanelOpen" class="ai-prompt-panel">
          <!-- 默认/自定义 切换 -->
          <div class="flex gap-5 text-sm mb-3">
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="radio" :value="false" v-model="s.useCustomPrompt" class="accent-indigo-600" />
              <span :class="!s.useCustomPrompt ? 'text-indigo-700 font-semibold' : 'text-gray-500'">默认 Prompt</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="radio" :value="true" v-model="s.useCustomPrompt" class="accent-indigo-600" />
              <span :class="s.useCustomPrompt ? 'text-indigo-700 font-semibold' : 'text-gray-500'">自定义 Prompt</span>
            </label>
          </div>

          <!-- 默认 Prompt 预览 -->
          <div v-if="!s.useCustomPrompt" class="ai-prompt-preview">
            {{ defaultPromptPreview }}
          </div>

          <!-- 自定义 Prompt 编辑区 -->
          <div v-else class="space-y-2">
            <div class="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              <i class="fas fa-exclamation-triangle mt-0.5 flex-shrink-0"></i>
              <span>必须包含 <code class="bg-amber-100 px-1 rounded font-mono">{screening_criteria}</code> 占位符，纳排标准将自动注入</span>
            </div>
            <textarea
              v-model="s.customPromptText"
              rows="9"
              placeholder="在此输入自定义 Prompt，必须包含 {screening_criteria} 占位符..."
              class="ai-prompt-textarea"
              :class="s.customPromptText && !s.customPromptText.includes('{screening_criteria}') ? 'ai-prompt-textarea-error' : ''"
            ></textarea>
            <div v-if="s.customPromptText && !s.customPromptText.includes('{screening_criteria}')" class="text-xs text-red-500 flex items-center gap-1">
              <i class="fas fa-times-circle"></i> 缺少 {screening_criteria} 占位符，无法保存
            </div>
          </div>

          <!-- 操作行 -->
          <div class="flex gap-2 items-center mt-3">
            <button
              @click="savePrompt"
              :disabled="s.useCustomPrompt && (!s.customPromptText || !s.customPromptText.includes('{screening_criteria}'))"
              class="ai-prompt-save-btn"
            >
              <i class="fas fa-save mr-1"></i>保存
            </button>
            <button
              v-if="s.useCustomPrompt"
              @click="resetPrompt"
              class="ai-prompt-reset-btn"
            >
              <i class="fas fa-undo mr-1"></i>重置为默认
            </button>
            <span v-if="promptSaveStatus" class="text-xs" :class="promptSaveStatus === 'ok' ? 'text-green-600' : 'text-red-500'">
              {{ promptSaveStatus === 'ok' ? '✓ 已保存' : '✗ 保存失败' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 进度区 -->
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

        <template v-else>
          <div v-for="m in selectedModels" :key="m.id" class="model-progress-row">
            <span class="model-progress-label text-xs text-gray-600 truncate font-medium">
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

        <div v-if="s.latestAiScreenTask?.status === 'queuing'" class="queue-status-bar mt-2">
          <div class="flex items-center gap-2 text-amber-700">
            <i class="fas fa-clock fa-spin"></i>
            <span class="font-semibold text-sm">排队等待中</span>
            <span v-if="queueInfo.position > 0" class="text-sm">— 第 <b>{{ queueInfo.position }}</b> 位</span>
          </div>
          <p class="text-xs text-amber-600 mt-0.5">系统将自动为您分配资源，无需手动操作</p>
        </div>
      </div>

      <!-- 结果统计（仅完成后显示） -->
      <div v-if="s.latestAiScreenTask?.status === 'completed' && s.aiScreenStats" class="ai-stats-section">
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
        <div class="ai-used-models" v-if="usedModels.length">
          <i class="fas fa-layer-group mr-1 text-indigo-400"></i>
          本次使用模型：
          <span v-for="m in usedModels" :key="m.id" class="used-model-chip">{{ m.name }}</span>
        </div>
      </div>

      <!-- 操作区 -->
      <div class="ai-action-area">
        <div class="billing-bar" :class="billing.sufficient === false ? 'billing-bar-danger' : 'billing-bar-ok'">
          <span class="billing-item">
            <i class="fas fa-coins mr-1"></i>余额：<b>{{ billing.balance ?? '...' }}</b> credits
          </span>
          <span class="billing-item" v-if="s.pendingTotal > 0">
            预估：<b>{{ billing.estimated ?? '...' }}</b> credits（{{ s.pendingTotal }} 篇，{{ selectedModels.length }} 个模型）
          </span>
          <span v-if="billing.sufficient === false" class="billing-warn">
            <i class="fas fa-exclamation-triangle mr-0.5"></i>余额不足
          </span>
        </div>

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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'
import { createAiScreenController } from '@/features/screening/composables/useAiScreenController'
import { prepareAiScreenRestart } from '@/features/screening/aiScreenRestart'
import { extractListData } from '@/utils/format'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()
const controller = createAiScreenController(() => project.currentProject?.id)

const billing = ref({ balance: null, estimated: null, sufficient: null })
const queueInfo = ref({ position: 0, queueLength: 0, slotsNeeded: 0, slotsFree: 0, slotsTotal: 0 })
const promptPanelOpen = ref(false)
const promptSaveStatus = ref('')
const defaultPromptPreview = ref('（加载中...）')
let aiPollGeneration = 0
let aiPollTimer = null
let componentActive = true
let pendingRequestGeneration = 0
let statsRequestGeneration = 0
let screenedRequestGeneration = 0
let pendingAbortController = null
let statsAbortController = null
let screenedAbortController = null

function isCurrentProject(projectId) {
  return componentActive && Number(project.currentProject?.id) === Number(projectId)
}

// ── 文献计数 ──────────────────────────────────────────────────
// 后端 aiModelsList 现在是分组结构，展平为子模型列表供选择
const flatModels = computed(() => {
  const list = []
  for (const provider of (s.aiModelsList || [])) {
    for (const sm of (provider.sub_models || [])) {
      list.push({ ...sm, logo: provider.logo, providerName: provider.name })
    }
  }
  return list
})

const totalRefCount = computed(() => {
  const screened = s.aiScreenStats
    ? (s.aiScreenStats.included_count ?? 0) + (s.aiScreenStats.excluded_count ?? 0) + (s.aiScreenStats.conflict_count ?? 0)
    : 0
  return (s.pendingTotal || 0) + screened
})
const LIST_PAGE_SIZE = 50

// 左栏 Tab：pending | screened
const listTab = ref('pending')
function switchListTab(tab) {
  listTab.value = tab
  if (tab === 'screened') loadScreenedFiles({ resetPage: false })
}

// ── 待筛分页（后端分页，每页 50 条）──
const pendingListPage = ref(1)
const pendingTotalPages = computed(() => Math.max(1, Math.ceil(s.pendingTotal / LIST_PAGE_SIZE)))

function goPendingPage(p) {
  if (p < 1 || p > pendingTotalPages.value) return
  pendingListPage.value = p
  loadPending(p - 1)   // loadPending 的 page 参数是 0-indexed offset page
}

// ── 已筛分页（后端分页，每页 50 条）──
const screenedListPage = ref(1)
const screenedTotalPages = computed(() => Math.max(1, Math.ceil(screenedCount.value / LIST_PAGE_SIZE)))
const pagedScreenedFiles = computed(() => s.screenedFiles || [])

const screenedCount = computed(() => {
  if (s.aiScreenStats) {
    return (s.aiScreenStats.included_count ?? 0) + (s.aiScreenStats.excluded_count ?? 0) + (s.aiScreenStats.conflict_count ?? 0)
  }
  return s.screenedTotal || s.screenedFiles?.length || 0
})

function goScreenedPage(page) {
  if (page < 1 || page > screenedTotalPages.value) return
  loadScreenedFiles({ page, resetPage: false })
}

function decisionClass(f) {
  const consensus = f.consensus
  if (consensus === 'conflict') return 'conflict'
  // review/list 返回 ai_decision；兼容旧字段 decision / include_or_not
  const d = f.ai_decision || f.decision
    || (f.include_or_not === 'yes' ? 'included' : f.include_or_not === 'no' ? 'excluded' : '')
  return d || ''
}

function decisionShort(f) {
  const consensus = f.consensus
  if (consensus === 'conflict') return '⚠'
  const d = f.ai_decision || f.decision
    || (f.include_or_not === 'yes' ? 'included' : f.include_or_not === 'no' ? 'excluded' : '')
  if (d === 'included') return '✓'
  if (d === 'excluded') return '✗'
  if (d === 'pending')  return '…'
  return '?'
}

// ── 模型选择 ──────────────────────────────────────────────────
const selectedModels = computed(() => {
  const ids = s.selectedAiModels?.length ? s.selectedAiModels : (s.selectedAiModel ? [s.selectedAiModel] : [])
  return ids.map(id => flatModels.value.find(m => m.id === id)).filter(Boolean)
})

function isModelSelected(id) {
  if (s.selectedAiModels?.length) return s.selectedAiModels.includes(id)
  return s.selectedAiModel === id
}

function toggleModel(sm) {
  if (s.isProcessing) return
  if (!s.selectedAiModels) s.selectedAiModels = []
  const idx = s.selectedAiModels.indexOf(sm.id)
  if (idx >= 0) {
    if (s.selectedAiModels.length === 1) return
    s.selectedAiModels = s.selectedAiModels.filter(id => id !== sm.id)
  } else {
    s.selectedAiModels = [...s.selectedAiModels, sm.id]
  }
  s.selectedAiModel = s.selectedAiModels[0] || ''
  loadBilling()
}

const hasConflict = computed(() => {
  return (s.aiScreenStats?.conflict_count ?? 0) > 0 || selectedModels.value.length > 1
})

const usedModels = computed(() => {
  const task = s.latestAiScreenTask
  if (!task || task.status !== 'completed') return []
  const ids = task.config?.ai_models || (task.config?.ai_model ? [task.config.ai_model] : [])
  return ids.map(id => {
    const found = flatModels.value.find(m => m.id === id)
    return found || { id, name: id, logo: '' }
  })
})

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
  const projectId = project.currentProject?.id
  if (!projectId) return
  if (s.criteriaList.length === 0) {
    const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
    const step  = stage?.steps?.find((st) => st.step_key === 'criteria')
    if (step?.metadata?.criteria?.length) s.criteriaList = step.metadata.criteria
  }
  await Promise.all([
    loadAiModels(),
    loadPrompt(),
    taskStore.fetchRecentTasks(projectId, project.stagesData),
  ])
  if (!isCurrentProject(projectId)) return
  await loadPending()
  await loadAiScreenStats()
  await loadScreenedFiles()
  if (!isCurrentProject(projectId)) return
  syncLatestAiTask()
  loadBilling()
})

// ── Prompt ──────────────────────────────────────────────────
async function loadPrompt() {
  if (!project.currentProject) return
  const projectId = project.currentProject.id
  try {
    const res = await controller.loadPrompt(projectId)
    if (!isCurrentProject(projectId)) return
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
    await controller.savePrompt({
      custom_prompt: s.customPromptText,
      use_custom_prompt: s.useCustomPrompt,
    })
    promptSaveStatus.value = 'ok'
  } catch { promptSaveStatus.value = 'error' }
  setTimeout(() => { promptSaveStatus.value = '' }, 3000)
}

async function resetPrompt() {
  if (!project.currentProject) return
  try {
    await controller.resetPrompt()
    s.useCustomPrompt = false
    s.customPromptText = ''
    promptSaveStatus.value = 'ok'
    setTimeout(() => { promptSaveStatus.value = '' }, 2000)
  } catch { promptSaveStatus.value = 'error' }
}

// ── 计费 ─────────────────────────────────────────────────────
async function loadBilling() {
  try {
    const balRes = await controller.loadBalance()
    const balData = balRes.data
    if (balData.is_unlimited) {
      billing.value = { balance: '∞', estimated: null, sufficient: true }
      return
    }
    billing.value.balance = balData.balance
    if (s.pendingTotal > 0) {
      const modelIds = selectedModels.value.map(m => m.id).join(',')
      const estRes = await controller.estimate(s.pendingTotal, modelIds)
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

// ── 模型加载（现在返回分组结构）────────────────────────────────
async function loadAiModels() {
  s.aiModelsLoading = true
  try {
    const res = await controller.loadModels()
    // res.data 是分组结构 [{id, name, logo, sub_models:[...]}, ...]
    s.aiModelsList = res.data
    // 找默认子模型
    if (!s.selectedAiModels || s.selectedAiModels.length === 0) {
      for (const provider of s.aiModelsList) {
        const def = provider.sub_models?.find(sm => sm.is_default && sm.configured)
          || provider.sub_models?.find(sm => sm.configured)
        if (def) {
          s.selectedAiModels = [def.id]
          s.selectedAiModel = def.id
          break
        }
      }
    }
  } catch (e) {
    console.error('加载模型列表失败', e)
  } finally {
    s.aiModelsLoading = false
  }
}

// ── 文件 + 统计 ───────────────────────────────────────────────
async function loadPending(page) {
  if (!project.currentProject) return
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const pageNum = page ?? 0
  const offset = pageNum * LIST_PAGE_SIZE
  const pid = project.currentProject.id
  const requestGeneration = ++pendingRequestGeneration
  pendingAbortController?.abort()
  const abortController = new AbortController()
  pendingAbortController = abortController

  let sourceStep = null
  for (const key of ['dedup', 'parse']) {
    const step = stage.steps.find((st) => st.step_key === key)
    if (!step) continue
    try {
      const probe = await controller.loadFiles(
        { project: pid, step: step.id, data_category: 'intermediate', limit: 1, offset: 0 },
        { signal: abortController.signal },
      )
      if (!isCurrentProject(pid) || requestGeneration !== pendingRequestGeneration) return
      if ((probe.data.total ?? 0) > 0) { sourceStep = step; break }
    } catch {}
  }
  if (!sourceStep) {
    if (isCurrentProject(pid) && requestGeneration === pendingRequestGeneration) s.pendingTotal = 0
    return
  }
  try {
    const res = await controller.loadFiles(
      { project: pid, step: sourceStep.id, data_category: 'intermediate', exclude_screened: 1, limit: LIST_PAGE_SIZE, offset },
      { signal: abortController.signal },
    )
    if (!isCurrentProject(pid) || requestGeneration !== pendingRequestGeneration) return
    const data = res.data
    s.pendingFiles = extractListData(data)
    s.pendingTotal = data.total ?? s.pendingFiles.length
    if (page !== undefined) s.pendingPage = page
    if (page === undefined || page === 0) loadBilling()
  } catch {
    if (!abortController.signal.aborted && isCurrentProject(pid) && requestGeneration === pendingRequestGeneration) {
      s.pendingTotal = 0
    }
  }
}

async function loadAiScreenStats() {
  if (!project.currentProject) return
  const projectId = project.currentProject.id
  const requestGeneration = ++statsRequestGeneration
  statsAbortController?.abort()
  const abortController = new AbortController()
  statsAbortController = abortController
  try {
    const res = await controller.loadStats(projectId, { signal: abortController.signal })
    if (!isCurrentProject(projectId) || requestGeneration !== statsRequestGeneration) return
    s.aiScreenStats = res.data
  } catch {}
}

async function loadScreenedFiles({ page, resetPage = true } = {}) {
  if (!project.currentProject) return
  const projectId = project.currentProject.id
  const requestGeneration = ++screenedRequestGeneration
  screenedAbortController?.abort()
  const abortController = new AbortController()
  screenedAbortController = abortController
  const targetPage = resetPage ? 1 : (page || screenedListPage.value)
  const stage = project.stagesData.find(st => st.stage_key === 'SCREEN_1')
  const reviewStepId = stage?.steps?.find(st => st.step_key === 'review')?.id
  try {
    const response = await controller.loadReviewPage(
      { step: reviewStepId, decision: '', page: targetPage, page_size: LIST_PAGE_SIZE },
      projectId,
      { signal: abortController.signal },
    )
    if (!isCurrentProject(projectId) || requestGeneration !== screenedRequestGeneration) return
    s.screenedFiles = (response.data.results || []).filter(item => item.ai_decision)
    s.screenedTotal = response.data.total || 0
    screenedListPage.value = targetPage
  } catch (e) {
    // 静默失败：不影响主流程
  }
}

function syncLatestAiTask() {
  const aiTask = taskStore.recentTasks.find((t) => t.task_type === 'ai_screen')
  if (!aiTask) {
    // 重置到默认模型
    for (const provider of (s.aiModelsList || [])) {
      const def = provider.sub_models?.find(sm => sm.is_default && sm.configured)
        || provider.sub_models?.find(sm => sm.configured)
      if (def) {
        s.selectedAiModels = [def.id]
        s.selectedAiModel  = def.id
        break
      }
    }
    return
  }
  s.latestAiScreenTask = aiTask
  const lastModels = aiTask.config?.ai_models
  if (lastModels?.length && flatModels.value.length) {
    const validIds = lastModels.filter(id => flatModels.value.find(m => m.id === id && m.configured))
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
  if (['running', 'pending', 'stopping', 'queuing'].includes(aiTask.status)) {
    s.isProcessing = aiTask.status === 'running'
    pollAiScreening(aiTask.id)
  }
  if (aiTask.status === 'completed' && !s.aiScreenStats) {
    loadAiScreenStats()
  }
}

// ── 任务操作 ─────────────────────────────────────────────────
async function startScreening() {
  if (s.criteriaList.length === 0) { alert('请先设置纳排标准'); return }
  if (selectedModels.value.length === 0) { alert('请至少选择一个已配置的模型'); return }
  s.isProcessing = true
  // 重置左栏分页状态
  pendingListPage.value = 1
  screenedListPage.value = 1
  listTab.value = 'pending'
  try {
    if (!await clearAiScreenResults()) {
      s.isProcessing = false
      return
    }
    const modelIds = selectedModels.value.map(m => m.id)
    const res = await controller.createTask({
      project: project.currentProject.id,
      task_type: 'ai_screen',
      config: {
        criteria:  s.criteriaList,
        ai_model:  modelIds[0],
        ai_models: modelIds,
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
    await controller.stopTask(s.latestAiScreenTask.id)
    alert('任务已暂停')
    s.isProcessing = false
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    await project.fetchStages(project.currentProject.id)
  } catch (err) { alert(`暂停失败: ${err.response?.data?.error || err.message}`) }
}

async function resumeTask() {
  if (!s.latestAiScreenTask) return
  try {
    const res = await controller.resumeTask(s.latestAiScreenTask.id)
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
  const taskId = s.latestAiScreenTask.id
  try {
    if (!await clearAiScreenResults()) return
    await controller.deleteTask(taskId)
    s.latestAiScreenTask = null
    s.aiScreenStats = null
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    alert('任务已放弃，筛选结果已清除')
  } catch (err) { alert(`放弃失败: ${err.response?.data?.error || err.message}`) }
}

async function clearAiScreenResults() {
  if (!project.currentProject) return false
  const projectId = project.currentProject.id
  return prepareAiScreenRestart({
    state: s,
    clearResults: () => controller.clearResults(projectId),
    loadPending,
    shouldApply: () => isCurrentProject(projectId),
  })
}

async function pollAiScreening(taskId) {
  clearTimeout(aiPollTimer)
  const generation = ++aiPollGeneration
  const projectId = project.currentProject?.id
  if (!projectId) return
  // 进度变化时只刷新轻量统计；大列表在任务结束时统一刷新。
  let lastStatsCount = -1

  const poll = async () => {
    if (generation !== aiPollGeneration || !isCurrentProject(projectId)) return
    try {
      const res = await controller.loadTask(taskId)
      if (generation !== aiPollGeneration || !isCurrentProject(projectId)) return
      const task = res.data
      if (Number(task.project) !== Number(projectId)) return
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
        // 避免每个 batch 重新拉取待筛列表和最多 1000 条已筛结果。
        const currentCount = s.processedCount || 0
        if (status === 'running' && currentCount !== lastStatsCount) {
          lastStatsCount = currentCount
          loadAiScreenStats()
        }
        aiPollTimer = setTimeout(poll, interval)
      } else {
        s.isProcessing = false
        await taskStore.fetchRecentTasks(projectId, project.stagesData)
        if (generation !== aiPollGeneration || !isCurrentProject(projectId)) return
        await project.fetchStages(projectId)
        if (generation !== aiPollGeneration || !isCurrentProject(projectId)) return
        if (status === 'completed') {
          await Promise.all([loadPending(), loadAiScreenStats(), loadScreenedFiles()])
          loadBilling()
          window.dispatchEvent(new CustomEvent('app:balance-changed'))
          listTab.value = 'screened'   // 完成后自动切到已筛 Tab
          alert('AI初筛完成！')
        } else if (status === 'stopped') {
          await Promise.all([loadPending(), loadAiScreenStats(), loadScreenedFiles({ resetPage: false })])
        } else {
          alert(`AI初筛失败: ${task.error_message || '任务执行失败'}`)
        }
      }
    } catch (err) {
      if (generation !== aiPollGeneration || !isCurrentProject(projectId)) return
      console.error('轮询AI初筛状态失败', err)
      s.isProcessing = false
    }
  }
  await poll()
}
onUnmounted(() => {
  componentActive = false
  aiPollGeneration += 1
  pendingRequestGeneration += 1
  statsRequestGeneration += 1
  screenedRequestGeneration += 1
  pendingAbortController?.abort()
  statsAbortController?.abort()
  screenedAbortController?.abort()
  clearTimeout(aiPollTimer)
})
</script>

<style scoped>
/* ── 整体左右布局 ── */
.ai-screen-layout {
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* ── 左栏 40% ── */
.ai-left-panel {
  width: 40%;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e2e8f0;
  background: #fafbff;
  overflow: hidden;
}

.ai-left-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

/* Tab 切换 */
.ai-list-tabs {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
  background: #f8fafc;
  padding: 0 4px;
}
.ai-list-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 8px 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 500;
  color: #64748b;
  border-bottom: 2px solid transparent;
  transition: all .15s;
  white-space: nowrap;
}
.ai-list-tab i { font-size: 0.7rem; }
.ai-list-tab:hover { color: #334155; background: #f1f5f9; }
.ai-list-tab.active {
  color: #6366f1;
  font-weight: 700;
  border-bottom-color: #6366f1;
  background: #fff;
}
.ai-list-tab-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 18px;
  padding: 0 5px;
  border-radius: 99px;
  font-size: 0.68rem;
  font-weight: 700;
  background: #e2e8f0;
  color: #475569;
}
.ai-list-tab.active .ai-list-tab-count {
  background: #eef2ff;
  color: #4338ca;
}
.ai-list-tab-total {
  font-size: 0.7rem;
  color: #94a3b8;
  padding: 0 10px;
  white-space: nowrap;
  flex-shrink: 0;
}

/* 文献列表 */
.ai-refs-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.ai-refs-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  color: #cbd5e1;
  font-size: 0.8rem;
}
.ai-refs-empty i { font-size: 1.8rem; }
.ai-refs-group-empty {
  padding: 16px;
  font-size: 0.78rem;
  color: #94a3b8;
  text-align: center;
}
.ai-ref-item {
  padding: 5px 16px;
  font-size: 0.78rem;
  color: #475569;
  border-bottom: 1px solid #f8fafc;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ai-ref-item-pending { border-left: 3px solid transparent; }
.ai-ref-item-done { border-left: 3px solid #bbf7d0; }
.ai-ref-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-ref-decision {
  flex-shrink: 0;
  font-size: 0.68rem;
  font-weight: 700;
  width: 16px;
  text-align: center;
}
.ai-ref-decision.included { color: #16a34a; }
.ai-ref-decision.excluded { color: #dc2626; }
.ai-ref-decision.conflict { color: #d97706; }
/* 列表内分页控件 */
.ai-refs-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 0 4px;
  border-top: 1px solid #f1f5f9;
  margin: 2px 0 6px;
}
.ai-pg-btn {
  width: 24px; height: 24px;
  border-radius: 5px;
  border: 1px solid #e2e8f0;
  background: #fff;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  color: #6366f1;
  font-size: 0.62rem;
  transition: all .12s;
  flex-shrink: 0;
}
.ai-pg-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.ai-pg-btn:hover:not(:disabled) { background: #eef2ff; border-color: #6366f1; }
.ai-pg-info { font-size: 0.72rem; color: #64748b; white-space: nowrap; }

.ai-refs-more {
  padding: 6px 16px;
  font-size: 0.72rem;
  color: #94a3b8;
  text-align: center;
}

/* ── 右栏 60% ── */
.ai-right-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  overflow-y: auto;
}

/* 模型选择 */
.ai-model-section {
  background: #fafbff;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  padding: 12px 14px;
  flex-shrink: 0;
}
.ai-section-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: #374151;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
}
.ai-provider-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ai-provider-group { }
.ai-provider-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.ai-provider-logo { font-size: 1rem; line-height: 1; }
.ai-provider-name { font-size: 0.8rem; font-weight: 600; color: #334155; }
.ai-provider-unconfigured {
  font-size: 0.68rem;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 2px;
}
.ai-submodel-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-left: 20px;
}
.ai-submodel-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1.5px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 0.78rem;
  position: relative;
}
.ai-submodel-btn:hover:not(.ai-submodel-btn-disabled) {
  border-color: #a5b4fc;
  background: #f5f3ff;
}
.ai-submodel-btn-active {
  border-color: #6366f1;
  background: #eef2ff;
}
.ai-submodel-btn-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ai-submodel-name {
  font-weight: 500;
  color: #334155;
}
.ai-submodel-desc {
  font-size: 0.68rem;
  color: #94a3b8;
}
.ai-submodel-btn-active .ai-submodel-name { color: #4338ca; }
.ai-submodel-btn-active .ai-submodel-desc { color: #818cf8; }
.ai-submodel-check {
  font-size: 0.62rem;
  color: #6366f1;
  margin-left: 2px;
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
.model-progress-label { width: 110px; flex-shrink: 0; }
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
.ai-stats-grid { display: grid; gap: 10px; margin-bottom: 10px; }
.ai-stats-grid-3 { grid-template-columns: repeat(3, 1fr); }
.ai-stats-grid-4 { grid-template-columns: repeat(4, 1fr); }
.ai-stat-card {
  display: flex; flex-direction: column; align-items: center;
  gap: 4px; padding: 12px 8px; border-radius: 10px;
  background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.06);
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
  font-size: 0.75rem; color: #7c3aed;
  background: #ede9fe; border-radius: 6px;
  padding: 5px 10px; display: inline-block;
}
.ai-used-models {
  font-size: 0.75rem; color: #475569;
  margin-top: 6px; display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
}
.used-model-chip {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 8px; border-radius: 99px;
  background: #eef2ff; color: #4338ca;
  font-size: 0.72rem; font-weight: 500; border: 1px solid #c7d2fe;
}

/* 操作区 */
.ai-action-area { display: flex; flex-direction: column; gap: 6px; }
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

/* ── Prompt 设置区 ── */
.ai-prompt-section {
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  flex-shrink: 0;
}

.ai-prompt-toggle-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 14px;
  background: #f8fafc;
  border: none;
  cursor: pointer;
  font-size: 0.82rem;
  color: #374151;
  transition: background .12s;
}
.ai-prompt-toggle-btn:hover,
.ai-prompt-toggle-btn-active {
  background: #f0f0ff;
}

.ai-prompt-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 99px;
  background: #eef2ff;
  color: #4338ca;
  font-size: 0.68rem;
  font-weight: 600;
  border: 1px solid #c7d2fe;
}

.ai-prompt-panel {
  padding: 12px 14px;
  background: #fff;
  border-top: 1px solid #e2e8f0;
}

.ai-prompt-preview {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 0.72rem;
  font-family: monospace;
  color: #64748b;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  border: 1px solid #e2e8f0;
}

.ai-prompt-textarea {
  width: 100%;
  font-size: 0.72rem;
  font-family: monospace;
  border: 1.5px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  resize: vertical;
  outline: none;
  transition: border-color .15s;
  line-height: 1.5;
}
.ai-prompt-textarea:focus { border-color: #a5b4fc; }
.ai-prompt-textarea-error { border-color: #f87171 !important; background: #fff5f5; }

.ai-prompt-save-btn {
  padding: 5px 14px;
  font-size: 0.78rem;
  font-weight: 600;
  background: #6366f1;
  color: #fff;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  transition: background .12s;
}
.ai-prompt-save-btn:hover:not(:disabled) { background: #4f46e5; }
.ai-prompt-save-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.ai-prompt-reset-btn {
  padding: 5px 14px;
  font-size: 0.78rem;
  color: #64748b;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  cursor: pointer;
  transition: all .12s;
}
.ai-prompt-reset-btn:hover { border-color: #a5b4fc; color: #4338ca; }

/* 排队状态 */
.queue-status-bar {
  background: #fffbeb; border: 1px solid #fbbf24;
  border-radius: 6px; padding: 8px 12px;
}
</style>
