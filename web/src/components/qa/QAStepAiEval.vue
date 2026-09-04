<template>
  <div class="qa-aiev">
    <!-- 标题行 -->
    <div class="step-header">
      <div class="step-icon-wrap">
        <i class="fas fa-robot"></i>
      </div>
      <div>
        <h3 class="step-title">AI 质量评价</h3>
        <p class="step-subtitle">选择一个或多个模型进行质量评价，多模型时自动校验一致性</p>
      </div>
    </div>

    <!-- 主体：左右分栏 -->
    <div class="aiev-body">

      <!-- ── 左栏：配置 ── -->
      <div class="aiev-left">

        <!-- 文献概览 -->
        <div class="overview-row">
          <div class="ov-item">
            <span class="ov-val">{{ totalCount }}</span>
            <span class="ov-label">待评价</span>
          </div>
          <div class="ov-divider"></div>
          <div class="ov-item">
            <span class="ov-val ai-ok">{{ aiSupportedCount }}</span>
            <span class="ov-label">AI可评价</span>
          </div>
          <div class="ov-divider"></div>
          <div class="ov-item">
            <span class="ov-val text-gray">{{ noMethodCount }}</span>
            <span class="ov-label">未选方法</span>
          </div>
          <div class="ov-divider"></div>
          <div class="ov-item">
            <span class="ov-val text-orange">{{ noFultextCount }}</span>
            <span class="ov-label">无全文</span>
          </div>
        </div>

        <!-- 模型选择 -->
        <div class="config-card">
          <div class="config-label">
            <i class="fas fa-brain" style="color:#a5b4fc"></i>
            选择评价模型
            <span class="config-tip">
              <template v-if="selectedModels.length === 0">至少选择一个模型</template>
              <template v-else-if="selectedModels.length === 1">单模型评价</template>
              <template v-else>{{ selectedModels.length }} 个模型 · 自动校验一致性</template>
            </span>
          </div>

          <div v-if="modelsLoading" class="models-loading">
            <i class="fas fa-spinner fa-spin"></i> 加载中...
          </div>

          <div v-else class="ai-provider-list">
            <div v-for="provider in modelsList" :key="provider.id" class="ai-provider-group">
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
              <div class="ai-submodel-list">
                <button
                  v-for="sm in provider.sub_models"
                  :key="sm.id"
                  :class="[
                    'ai-submodel-btn',
                    isModelSelected(sm.id) ? 'ai-submodel-btn-active' : '',
                    !sm.configured ? 'ai-submodel-btn-disabled' : '',
                  ]"
                  :title="sm.description"
                  @click="sm.configured && toggleModel(sm.id)"
                >
                  <span class="ai-submodel-name">{{ sm.name }}</span>
                  <span class="ai-submodel-desc">{{ sm.description }}</span>
                  <i v-if="isModelSelected(sm.id)" class="fas fa-check ai-submodel-check"></i>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 启动区 -->
        <div class="start-section">
          <div class="start-hints">
            <div class="reeval-hint" v-if="isCompleted && reevalScope === 'failed'">
              <i class="fas fa-info-circle"></i> 仅重评 {{ failedCount }} 篇失败/跳过
            </div>
            <div class="credit-hint" v-if="estimatedCredits > 0">
              <i class="fas fa-coins"></i> 预计 {{ estimatedCredits }} 积分
            </div>
          </div>
          <div class="start-btns">
            <button
              class="btn-start"
              @click="openConfirmModal"
              :disabled="!canStart || isRunning"
            >
              <i class="fas fa-spinner fa-spin" v-if="isRunning"></i>
              <i class="fas fa-play" v-else></i>
              {{ isRunning ? '评价中...' : isCompleted ? '重新评价' : '开始 AI 评价' }}
            </button>
          </div>
        </div>
      </div>

      <!-- ── 右栏：进度 ── -->
      <div class="aiev-right">
        <!-- 未开始 -->
        <div v-if="!isRunning && !isCompleted" class="progress-empty">
          <i class="fas fa-robot"></i>
          <p>选好模型后点击「开始 AI 评价」</p>
          <p class="progress-empty-sub">评价进行中将在此实时显示进度</p>
        </div>

        <!-- 运行中 / 已完成 -->
        <div v-else class="progress-panel">
          <!-- 状态头 -->
          <div class="progress-head">
            <div class="progress-status-icon" :class="isCompleted ? 'done' : 'running'">
              <i :class="isCompleted ? 'fas fa-check' : 'fas fa-spinner fa-spin'"></i>
            </div>
            <div class="progress-head-text">
              <p class="progress-title">{{ isCompleted ? 'AI 评价完成' : 'AI 评价进行中...' }}</p>
              <p class="progress-subtitle">共 {{ totalCount }} 篇，已完成 {{ doneCount }} 篇</p>
            </div>
            <button v-if="!isCompleted" class="btn-cancel" @click="handleCancel">
              <i class="fas fa-stop"></i> 取消
            </button>
          </div>

          <!-- 完成后：积分消耗提示 -->
          <div v-if="isCompleted && lastConsumedCredits > 0" class="credits-consumed">
            <i class="fas fa-coins"></i>
            本次消耗 <strong>{{ lastConsumedCredits }}</strong> 积分
            <template v-if="lastTokenStats">
              <span class="credits-detail">
                （{{ lastTokenStats.total_tokens?.toLocaleString() }} tokens
                · {{ lastTokenStats.ref_count }} 篇）
              </span>
            </template>
            <template v-else>
              <span class="credits-est-tip">预估</span>
            </template>
            <span v-if="lastUsedModels.length" class="used-models-tip">
              · 使用模型：{{ lastUsedModels.join(' / ') }}
            </span>
          </div>

          <!-- 总进度条 -->
          <div class="progress-bar-wrap">
            <div class="progress-bar-track">
              <div class="progress-bar-fill" :style="{ width: progressPct + '%' }"></div>
            </div>
            <span class="progress-pct">{{ progressPct }}%</span>
          </div>

          <!-- 状态统计 -->
          <div class="stat-row" v-if="qa.evalProgress?.summary">
            <div class="stat-item"><span class="stat-dot dot-blue"></span>进行中 {{ qa.evalProgress.summary.running }}</div>
            <div class="stat-item"><span class="stat-dot dot-green"></span>完成 {{ qa.evalProgress.summary.completed }}</div>
            <div class="stat-item"><span class="stat-dot dot-orange"></span>摘要 {{ qa.evalProgress.summary.abstract_only || 0 }}</div>
            <div class="stat-item">
              <span class="stat-dot dot-gray"></span>
              跳过 {{ (qa.evalProgress.summary.skipped_no_fulltext || 0) + (qa.evalProgress.summary.skipped_no_method || 0) }}
            </div>
            <div class="stat-item"><span class="stat-dot dot-red"></span>失败 {{ qa.evalProgress.summary.failed || 0 }}</div>
          </div>

          <!-- 文献状态列表 -->
          <div class="ref-progress-list" v-if="qa.evalProgress?.refs?.length">
            <div v-for="pr in qa.evalProgress.refs" :key="pr.id" class="ref-prog-item">
              <i :class="['status-icon', statusIconClass(pr.ai_eval_status)]"></i>
              <span class="ref-prog-title">{{ pr.title }}</span>
              <span :class="['status-badge', statusBadgeClass(pr.ai_eval_status)]">{{ statusLabel(pr.ai_eval_status) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 启动确认弹窗 -->
    <Teleport to="body">
      <div v-if="showConfirmModal" class="modal-mask" @click.self="showConfirmModal = false">
        <div class="modal-box">
          <div class="modal-head">
            <i class="fas fa-robot" style="color:#f59e0b"></i>
            <span>确认启动 AI 评价</span>
            <button class="modal-close-btn" @click="showConfirmModal = false"><i class="fas fa-times"></i></button>
          </div>
          <div class="modal-body">
            <!-- 重评范围选择（仅已完成时展示） -->
            <div v-if="isCompleted" class="reeval-scope-row">
              <span class="reeval-scope-label">重评范围：</span>
              <div class="reeval-scope-btns">
                <button
                  :class="['scope-btn', { 'scope-btn-active': reevalScope === 'failed' }]"
                  @click="reevalScope = 'failed'"
                >
                  <i class="fas fa-redo"></i> 仅失败/跳过（{{ failedCount }} 篇）
                </button>
                <button
                  :class="['scope-btn', { 'scope-btn-active': reevalScope === 'all' }]"
                  @click="reevalScope = 'all'"
                >
                  <i class="fas fa-rotate"></i> 全部重评（{{ aiSupportedCount }} 篇）
                </button>
                <button
                  :class="['scope-btn', { 'scope-btn-active': reevalScope === 'custom' }]"
                  @click="reevalScope = 'custom'"
                >
                  <i class="fas fa-list-check"></i> 手动选择
                </button>
              </div>
            </div>

            <!-- 手动选择文献列表 -->
            <div v-if="reevalScope === 'custom'" class="custom-ref-picker">
              <div class="custom-ref-toolbar">
                <label class="check-all-label">
                  <input
                    type="checkbox"
                    :checked="customSelectedIds.length === customPickerRefs.length && customPickerRefs.length > 0"
                    :indeterminate="customSelectedIds.length > 0 && customSelectedIds.length < customPickerRefs.length"
                    @change="toggleAllCustom"
                  />
                  全选
                </label>
                <span class="custom-ref-count">已选 {{ customSelectedIds.length }} / {{ customPickerRefs.length }} 篇</span>
              </div>
              <div class="custom-ref-list">
                <label
                  v-for="ref in customPickerRefs"
                  :key="ref.id"
                  class="custom-ref-item"
                  :class="{ 'custom-ref-item-checked': customSelectedIds.includes(ref.id) }"
                >
                  <input
                    type="checkbox"
                    :value="ref.id"
                    v-model="customSelectedIds"
                    class="custom-ref-checkbox"
                  />
                  <span class="custom-ref-status-dot" :class="statusDotClass(ref.ai_eval_status)"></span>
                  <span class="custom-ref-title">{{ ref.title || '（无标题）' }}</span>
                  <span class="custom-ref-badge" :class="statusBadgeClass(ref.ai_eval_status)">{{ statusLabel(ref.ai_eval_status) }}</span>
                </label>
              </div>
            </div>

            <p v-if="reevalScope !== 'custom'">
              即将对 <strong>{{ reevalScope === 'failed' ? failedCount : aiSupportedCount }}</strong> 篇文献进行 AI 质量评价。
            </p>
            <p v-else-if="customSelectedIds.length === 0" class="custom-empty-tip">
              <i class="fas fa-info-circle"></i> 请至少选择一篇文献
            </p>
            <ul class="confirm-list" v-if="reevalScope !== 'custom' || customSelectedIds.length > 0">
              <li v-if="reevalScope === 'custom'">即将对 <strong>{{ customSelectedIds.length }}</strong> 篇文献进行 AI 质量评价</li>
              <li>评价模式：<strong>{{ selectedModels.length === 1 ? '单模型评价' : selectedModels.length + ' 个模型校验' }}</strong></li>
              <li>使用模型：<strong>{{ selectedModelNames.join(' / ') }}</strong></li>
              <li v-if="noFultextCount > 0">{{ noFultextCount }} 篇无全文，将用摘要评价</li>
            </ul>
            <p class="confirm-credit" v-if="estimatedCredits > 0">
              <i class="fas fa-coins" style="color:#f59e0b"></i>
              预计消耗 <strong>{{ estimatedCredits }}</strong> 积分
            </p>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="showConfirmModal = false">取消</button>
            <button
              class="btn-primary"
              @click="doStartEval"
              :disabled="startLoading || (reevalScope === 'custom' && customSelectedIds.length === 0)"
            >
              <i class="fas fa-spinner fa-spin" v-if="startLoading"></i>
              <i class="fas fa-play" v-else></i>
              {{ startLoading ? '启动中...' : '确认启动' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useQAStore } from '@/stores/qa'
import { useProjectStore } from '@/stores/project'
import { useTaskStore } from '@/stores/task'
import http from '@/api/http'

const qa      = useQAStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const selectedModels   = ref([])
const showConfirmModal = ref(false)
const startLoading     = ref(false)
const reevalScope      = ref('all')

// 手动选择模式的勾选状态
const customSelectedIds = ref([])

// 手动选择模式可选文献（AI 可评价文献）
const customPickerRefs = computed(() =>
  qa.refs.filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method))
)

// 切换全选/全不选
function toggleAllCustom(e) {
  if (e.target.checked) {
    customSelectedIds.value = customPickerRefs.value.map(r => r.id)
  } else {
    customSelectedIds.value = []
  }
}

// 打开弹窗时重置手动选择列表（默认选中失败/跳过的）
function openConfirmModal() {
  if (isCompleted.value) {
    reevalScope.value = 'failed'
    // 默认勾选失败/跳过的文献
    const fs = ['failed', 'skipped_no_fulltext', 'skipped_no_method']
    customSelectedIds.value = customPickerRefs.value
      .filter(r => fs.includes(r.ai_eval_status))
      .map(r => r.id)
  } else {
    reevalScope.value = 'all'
    customSelectedIds.value = []
  }
  showConfirmModal.value = true
}

// 记录最近一次评价消耗的积分和模型（评价完成后展示）
// 优先从后端 token_stats 读取真实值，不可用时退回预估值
const lastConsumedCredits = ref(0)
const lastUsedModels      = ref([])
const lastTokenStats      = ref(null)  // 后端真实 token 统计

// 监听进度，评价完成时同步真实积分消耗
watch(() => qa.evalProgress?.token_stats, (stats) => {
  if (stats && stats.credits_consumed > 0) {
    lastConsumedCredits.value = stats.credits_consumed
    lastTokenStats.value = stats
    // 如果 lastUsedModels 还未设置（刷新场景），从 token_stats.model 恢复
    if (!lastUsedModels.value.length && stats.model) {
      lastUsedModels.value = [stats.model]
    }
  }
}, { immediate: true })

// ── 模型列表 ──────────────────────────────────────────────────────────────────

const modelsList    = ref([])
const modelsLoading = ref(false)

async function loadModels() {
  modelsLoading.value = true
  try {
    const res = await http.get('/ai-models/')
    modelsList.value = res.data
    if (!selectedModels.value.length) {
      for (const provider of modelsList.value) {
        const def = provider.sub_models?.find(sm => sm.is_default && sm.configured)
          || provider.sub_models?.find(sm => sm.configured)
        if (def) { selectedModels.value = [def.id]; break }
      }
    }
  } catch (e) {
    console.error('加载模型列表失败', e)
  } finally {
    modelsLoading.value = false
  }
}

const allSubModels = computed(() => {
  const flat = []
  for (const p of modelsList.value) for (const sm of (p.sub_models || [])) flat.push(sm)
  return flat
})

const selectedModelNames = computed(() =>
  selectedModels.value.map(id => allSubModels.value.find(sm => sm.id === id)?.name || id)
)

// ── 统计 ──────────────────────────────────────────────────────────────────────

const AI_SUPPORTED = new Set(['QUADAS2', 'NOS'])

const totalCount       = computed(() => qa.refs.length)
const aiSupportedCount = computed(() => qa.refs.filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method)).length)
const noMethodCount    = computed(() => qa.refs.filter(r => !r.quality_method).length)
const noFultextCount   = computed(() => qa.refs.filter(r => r.fulltext_status !== 'available').length)
const failedCount      = computed(() => {
  const fs = ['failed', 'skipped_no_fulltext', 'skipped_no_method']
  return qa.refs.filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method) && fs.includes(r.ai_eval_status)).length
})
const estimatedCredits = computed(() => {
  let count
  if (reevalScope.value === 'failed') count = failedCount.value
  else if (reevalScope.value === 'custom') count = customSelectedIds.value.length
  else count = aiSupportedCount.value
  return count * selectedModels.value.length * 10
})

// ── 进度 ──────────────────────────────────────────────────────────────────────

const isRunning   = computed(() => !!qa.evalProgress?.summary && qa.evalProgress.summary.running > 0)
const isCompleted = computed(() => qa.evalCompleted)

const doneCount = computed(() => {
  if (!qa.evalProgress?.summary) return 0
  const s = qa.evalProgress.summary
  return (s.completed || 0) + (s.failed || 0) + (s.abstract_only || 0) + (s.skipped_no_fulltext || 0) + (s.skipped_no_method || 0)
})

const progressPct = computed(() => {
  if (!totalCount.value) return 0
  return Math.round((doneCount.value / totalCount.value) * 100)
})

const btnLabel = computed(() => {
  if (isRunning.value) return '评价中...'
  if (isCompleted.value) return '重新评价'
  return '开始 AI 评价'
})

// ── 模型选择 ──────────────────────────────────────────────────────────────────

function isModelSelected(id) { return selectedModels.value.includes(id) }

function toggleModel(id) {
  const idx = selectedModels.value.indexOf(id)
  if (idx !== -1) {
    if (selectedModels.value.length > 1) selectedModels.value.splice(idx, 1)
  } else {
    selectedModels.value.push(id)
  }
}

const canStart = computed(() => aiSupportedCount.value > 0 && selectedModels.value.length > 0)

// ── 启动评价 ──────────────────────────────────────────────────────────────────

async function doStartEval() {
  startLoading.value = true
  try {
    let refIds
    if (reevalScope.value === 'failed') {
      const fs = ['failed', 'skipped_no_fulltext', 'skipped_no_method']
      refIds = qa.refs
        .filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method) && fs.includes(r.ai_eval_status))
        .map(r => r.id)
      if (!refIds.length) { alert('没有需要重评的文献'); return }
    } else if (reevalScope.value === 'custom') {
      refIds = customSelectedIds.value.slice()
      if (!refIds.length) { alert('请至少选择一篇文献'); return }
    } else {
      refIds = qa.refs
        .filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method))
        .map(r => r.id)
    }
    await qa.startEval(project.currentProject.id, refIds, null, selectedModels.value)
    showConfirmModal.value = false
    // 估算值先占位，完成后 watch token_stats 自动替换为真实值
    lastConsumedCredits.value = estimatedCredits.value
    lastUsedModels.value = selectedModelNames.value.slice()
    // 启动后刷新任务与日志
    taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    taskStore.fetchActivityLogs(project.currentProject.id)
    qa.startPollingProgress(project.currentProject.id)
    await qa.fetchEvalProgress(project.currentProject.id)
  } catch (e) {
    alert(e?.response?.data?.error || '启动失败，请重试')
  } finally {
    startLoading.value = false
  }
}

function handleCancel() {
  qa.stopPolling()
}

// ── 生命周期 ──────────────────────────────────────────────────────────────────

onMounted(async () => {
  await loadModels()
  if (project.currentProject) {
    await qa.fetchEvalProgress(project.currentProject.id)
    // fetchEvalProgress 完成后手动同步一次 token_stats（避免 watch immediate 时数据未就绪）
    const stats = qa.evalProgress?.token_stats
    if (stats && stats.credits_consumed > 0) {
      lastConsumedCredits.value = stats.credits_consumed
      lastTokenStats.value = stats
      if (!lastUsedModels.value.length && stats.model) {
        lastUsedModels.value = [stats.model]
      }
    }
    if (isRunning.value) qa.startPollingProgress(project.currentProject.id)
  }
})

onUnmounted(() => {
  if (!isCompleted.value) qa.stopPolling()
})

// ── 状态显示辅助 ──────────────────────────────────────────────────────────────

function statusLabel(s) {
  return { pending: '等待中', running: '评价中', completed: '已完成', abstract_only: '摘要评价',
           failed: '失败', skipped_no_fulltext: '跳过(无内容)', skipped_no_method: '跳过(无方法)' }[s] || s
}
function statusIconClass(s) {
  return { pending: 'fas fa-clock text-gray', running: 'fas fa-spinner fa-spin text-blue',
           completed: 'fas fa-check-circle text-green', abstract_only: 'fas fa-file-lines text-orange',
           failed: 'fas fa-times-circle text-red', skipped_no_fulltext: 'fas fa-ban text-gray',
           skipped_no_method: 'fas fa-ban text-gray' }[s] || 'fas fa-circle'
}
function statusBadgeClass(s) {
  return { pending: 'badge-gray', running: 'badge-blue', completed: 'badge-green',
           abstract_only: 'badge-orange', failed: 'badge-red',
           skipped_no_fulltext: 'badge-gray', skipped_no_method: 'badge-gray' }[s] || 'badge-gray'
}
function statusDotClass(s) {
  return { pending: 'dot-gray', running: 'dot-blue', completed: 'dot-green',
           abstract_only: 'dot-orange', failed: 'dot-red',
           skipped_no_fulltext: 'dot-gray', skipped_no_method: 'dot-gray' }[s] || 'dot-gray'
}
</script>

<style scoped>
.qa-aiev { display: flex; flex-direction: column; gap: 14px; }

/* 标题 */
.step-header { display: flex; align-items: center; gap: 12px; }
.step-icon-wrap { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; background: linear-gradient(135deg,#f59e0b,#f97316); }
.step-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.step-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }

/* ── 主体左右分栏 ── */
.aiev-body {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 14px;
  align-items: start;
}

/* ── 左栏 ── */
.aiev-left { display: flex; flex-direction: column; gap: 10px; }

/* 概览 */
.overview-row { display: flex; align-items: center; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; }
.ov-item { flex: 1; text-align: center; }
.ov-val { display: block; font-size: 1.35rem; font-weight: 700; color: #1e293b; line-height: 1.2; }
.ov-val.ai-ok { color: #10b981; }
.ov-val.text-gray { color: #94a3b8; }
.ov-val.text-orange { color: #f59e0b; }
.ov-label { font-size: 0.68rem; color: #64748b; }
.ov-divider { width: 1px; height: 30px; background: #e2e8f0; flex-shrink: 0; }

/* 配置卡片 */
.config-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px; }
.config-label { font-size: 0.8rem; font-weight: 600; color: #475569; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
.config-tip { font-size: 0.7rem; color: #94a3b8; font-weight: 400; }

.models-loading { font-size: 0.8rem; color: #94a3b8; padding: 8px 0; display: flex; align-items: center; gap: 6px; }
.ai-provider-list { display: flex; flex-direction: column; gap: 10px; }
.ai-provider-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.ai-provider-logo { font-size: 0.95rem; line-height: 1; }
.ai-provider-name { font-size: 0.78rem; font-weight: 600; color: #334155; }
.ai-provider-unconfigured { font-size: 0.65rem; color: #94a3b8; background: #f1f5f9; padding: 1px 6px; border-radius: 4px; margin-left: 2px; }
.ai-submodel-list { display: flex; flex-wrap: wrap; gap: 5px; padding-left: 18px; }
.ai-submodel-btn { display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 7px; border: 1.5px solid #e2e8f0; background: #fff; cursor: pointer; transition: all 0.14s; font-size: 0.75rem; }
.ai-submodel-btn:hover:not(.ai-submodel-btn-disabled) { border-color: #a5b4fc; background: #f5f3ff; }
.ai-submodel-btn-active { border-color: #6366f1 !important; background: #eef2ff !important; }
.ai-submodel-btn-disabled { opacity: 0.42; cursor: not-allowed; }
.ai-submodel-name { font-weight: 500; color: #334155; }
.ai-submodel-desc { font-size: 0.65rem; color: #94a3b8; }
.ai-submodel-btn-active .ai-submodel-name { color: #4338ca; }
.ai-submodel-btn-active .ai-submodel-desc { color: #818cf8; }
.ai-submodel-check { font-size: 0.58rem; color: #6366f1; }

/* 启动区 */
.start-section { display: flex; flex-direction: column; gap: 8px; }
.start-hints { display: flex; flex-wrap: wrap; gap: 8px; }
.credit-hint { font-size: 0.75rem; color: #94a3b8; display: flex; align-items: center; gap: 4px; }
.reeval-hint { font-size: 0.75rem; color: #f59e0b; display: flex; align-items: center; gap: 4px; }
.start-btns { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.btn-reeval { padding: 6px 12px; background: #fff; border: 1px solid #e2e8f0; color: #475569; border-radius: 7px; cursor: pointer; font-size: 0.75rem; display: flex; align-items: center; gap: 4px; transition: all 0.12s; white-space: nowrap; }
.btn-reeval:hover { border-color: #f59e0b; color: #f59e0b; }
.btn-reeval-all:hover { border-color: #6366f1; color: #6366f1; }
.btn-reeval-active { border-color: #6366f1 !important; color: #6366f1 !important; background: #eef2ff !important; }
.btn-start { flex: 1; padding: 10px 0; background: linear-gradient(135deg, #f59e0b, #f97316); color: #fff; border: none; border-radius: 10px; cursor: pointer; font-size: 0.88rem; font-weight: 600; display: flex; align-items: center; justify-content: center; gap: 7px; box-shadow: 0 2px 8px rgba(249,115,22,.22); white-space: nowrap; }
.btn-start:hover:not(:disabled) { opacity: 0.88; }
.btn-start:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── 右栏：进度 ── */
.aiev-right { }

.progress-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 48px 20px;
  background: #fafafa; border: 1.5px dashed #e2e8f0; border-radius: 14px;
  color: #cbd5e1; text-align: center; min-height: 260px;
}
.progress-empty i { font-size: 2.4rem; }
.progress-empty p { font-size: 0.85rem; margin: 0; color: #94a3b8; }
.progress-empty-sub { font-size: 0.73rem !important; color: #cbd5e1 !important; }

.progress-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.progress-head { display: flex; align-items: center; gap: 10px; }
.progress-status-icon { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1rem; flex-shrink: 0; }
.progress-status-icon.running { background: #dbeafe; color: #2563eb; }
.progress-status-icon.done { background: #d1fae5; color: #059669; }
.progress-head-text { flex: 1; }
.progress-title { font-size: 0.9rem; font-weight: 600; color: #1e293b; margin: 0; }
.progress-subtitle { font-size: 0.73rem; color: #64748b; margin: 0; }

/* 积分消耗提示 */
.credits-consumed { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; color: #92400e; background: #fef3c7; border: 1px solid #fde68a; border-radius: 8px; padding: 7px 12px; flex-wrap: wrap; }
.credits-consumed i { color: #f59e0b; }
.credits-detail { color: #a16207; font-size: 0.72rem; }
.credits-est-tip { font-size: 0.7rem; color: #b45309; background: #fef9c3; border-radius: 3px; padding: 0 4px; }
.used-models-tip { color: #78716c; }

.btn-cancel { padding: 6px 12px; border: 1px solid #fca5a5; background: #fff; color: #ef4444; border-radius: 7px; cursor: pointer; font-size: 0.78rem; display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.btn-cancel:hover { background: #fee2e2; }

.progress-bar-wrap { display: flex; align-items: center; gap: 10px; }
.progress-bar-track { flex: 1; height: 7px; background: #f1f5f9; border-radius: 9999px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 9999px; transition: width 0.5s ease; }
.progress-pct { font-size: 0.78rem; color: #64748b; width: 34px; text-align: right; flex-shrink: 0; }

.stat-row { display: flex; gap: 12px; flex-wrap: wrap; }
.stat-item { display: flex; align-items: center; gap: 4px; font-size: 0.75rem; color: #64748b; }
.stat-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.dot-blue { background: #3b82f6; } .dot-green { background: #10b981; }
.dot-orange { background: #f59e0b; } .dot-gray { background: #94a3b8; } .dot-red { background: #ef4444; }

.ref-progress-list { display: flex; flex-direction: column; gap: 3px; max-height: 280px; overflow-y: auto; border-top: 1px solid #f1f5f9; padding-top: 10px; }
.ref-prog-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.status-icon { width: 14px; flex-shrink: 0; font-size: 0.75rem; }
.text-blue { color: #3b82f6; } .text-green { color: #10b981; }
.text-orange { color: #f59e0b; } .text-red { color: #ef4444; } .text-gray { color: #94a3b8; }
.ref-prog-title { flex: 1; font-size: 0.76rem; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-badge { font-size: 0.66rem; padding: 1px 6px; border-radius: 4px; flex-shrink: 0; }
.badge-gray { background: #f1f5f9; color: #64748b; }
.badge-blue { background: #dbeafe; color: #1d4ed8; }
.badge-green { background: #d1fae5; color: #065f46; }
.badge-orange { background: #ffedd5; color: #9a3412; }
.badge-red { background: #fee2e2; color: #991b1b; }

/* 底部 */
.step-footer-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.btn-primary { padding: 8px 18px; background: #6366f1; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-primary:hover:not(:disabled) { background: #4f46e5; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { padding: 8px 16px; background: #fff; color: #6366f1; border: 1px solid #6366f1; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-secondary:hover { background: #f5f3ff; }

/* 弹窗 */
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 9999; }
.modal-box { background: #fff; border-radius: 16px; width: 560px; max-width: 94vw; box-shadow: 0 16px 48px rgba(0,0,0,.18); }
.modal-box-wide { width: 580px; }
.modal-head { display: flex; align-items: center; gap: 10px; padding: 20px 24px 16px; font-size: 1rem; font-weight: 600; color: #1e293b; border-bottom: 1px solid #f1f5f9; }
.modal-head span { flex: 1; }
.modal-close-btn { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.85rem; padding: 2px 4px; border-radius: 4px; }
.modal-close-btn:hover { color: #475569; background: #f1f5f9; }
.modal-body { padding: 16px 24px; font-size: 0.85rem; color: #475569; }
.modal-body p { margin: 0 0 10px; }
.confirm-list { margin: 0 0 10px; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
.confirm-credit { color: #f59e0b; display: flex; align-items: center; gap: 6px; font-size: 0.82rem; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 24px; border-top: 1px solid #f1f5f9; }

/* 手动选择文献 */
.custom-ref-picker { border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; margin-bottom: 12px; }
.custom-ref-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }
.check-all-label { display: flex; align-items: center; gap: 7px; font-size: 0.78rem; font-weight: 600; color: #475569; cursor: pointer; user-select: none; }
.check-all-label input { cursor: pointer; width: 14px; height: 14px; accent-color: #6366f1; }
.custom-ref-count { font-size: 0.72rem; color: #94a3b8; }
.custom-ref-list { max-height: 240px; overflow-y: auto; }
.custom-ref-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #f1f5f9; transition: background 0.1s; user-select: none; }
.custom-ref-item:last-child { border-bottom: none; }
.custom-ref-item:hover { background: #f8fafc; }
.custom-ref-item-checked { background: #eef2ff; }
.custom-ref-item-checked:hover { background: #e0e7ff; }
.custom-ref-checkbox { width: 14px; height: 14px; flex-shrink: 0; cursor: pointer; accent-color: #6366f1; }
.custom-ref-status-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.custom-ref-title { flex: 1; font-size: 0.77rem; color: #334155; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.custom-ref-badge { font-size: 0.64rem; padding: 1px 6px; border-radius: 4px; flex-shrink: 0; }
.custom-empty-tip { color: #94a3b8; font-size: 0.78rem; display: flex; align-items: center; gap: 5px; margin-bottom: 8px; }

/* 重评范围选择 */
.reeval-scope-row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 14px; border-bottom: 1px solid #f1f5f9; flex-wrap: wrap; }
.reeval-scope-label { font-size: 0.82rem; color: #64748b; flex-shrink: 0; }
.reeval-scope-btns { display: flex; gap: 8px; flex-wrap: wrap; }
.scope-btn { padding: 5px 12px; border: 1.5px solid #e2e8f0; background: #fff; border-radius: 7px; cursor: pointer; font-size: 0.78rem; color: #475569; display: flex; align-items: center; gap: 5px; transition: all 0.12s; }
.scope-btn:hover { border-color: #a5b4fc; color: #6366f1; }
.scope-btn-active { border-color: #6366f1 !important; background: #eef2ff !important; color: #4338ca !important; font-weight: 600; }
</style>
