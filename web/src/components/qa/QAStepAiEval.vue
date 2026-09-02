<template>
  <div class="qa-aiev">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#f59e0b,#f97316)">
        <i class="fas fa-robot"></i>
      </div>
      <div>
        <h3 class="step-title">AI 质量评价</h3>
        <p class="step-subtitle">选择评价模式与模型，AI 将自动分析每篇文献的信号问题</p>
      </div>
    </div>

    <!-- 评价配置卡片 -->
    <div class="config-section" v-if="!isRunning && showConfig">
      <!-- 文献概览 -->
      <div class="overview-row">
        <div class="ov-item">
          <span class="ov-val">{{ totalCount }}</span>
          <span class="ov-label">待评价文献</span>
        </div>
        <div class="ov-divider"></div>
        <div class="ov-item">
          <span class="ov-val ai-ok">{{ aiSupportedCount }}</span>
          <span class="ov-label">AI 可评价</span>
        </div>
        <div class="ov-divider"></div>
        <div class="ov-item">
          <span class="ov-val text-gray">{{ noMethodCount }}</span>
          <span class="ov-label">未选方法</span>
        </div>
        <div class="ov-divider"></div>
        <div class="ov-item">
          <span class="ov-val text-orange">{{ noFultextCount }}</span>
          <span class="ov-label">无全文（用摘要）</span>
        </div>
      </div>

      <!-- 模式选择 -->
      <div class="config-card">
        <div class="config-label">评价模式</div>
        <div class="mode-options">
          <div
            v-for="mode in evalModes"
            :key="mode.key"
            :class="['mode-option', { active: evalMode === mode.key }]"
            @click="evalMode = mode.key"
          >
            <div class="mode-icon"><i :class="mode.icon"></i></div>
            <div>
              <p class="mode-name">{{ mode.name }}</p>
              <p class="mode-desc">{{ mode.desc }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 模型选择 -->
      <div class="config-card">
        <div class="config-label">
          选择模型
          <span class="config-tip">{{ evalMode === 'dual' ? '双模型校验需选择两个不同模型' : '选择单个模型进行评价' }}</span>
        </div>
        <div class="model-grid">
          <div
            v-for="m in availableModels"
            :key="m.id"
            :class="['model-option', { selected: selectedModels.includes(m.id), disabled: isModelDisabled(m.id) }]"
            @click="toggleModel(m.id)"
          >
            <div class="model-check"><i class="fas fa-check" v-if="selectedModels.includes(m.id)"></i></div>
            <div class="model-info">
              <p class="model-name">{{ m.name }}</p>
              <p class="model-provider">{{ m.provider }}</p>
            </div>
            <span v-if="m.recommended" class="tag tag-amber">推荐</span>
          </div>
        </div>
      </div>

      <!-- 启动按钮 -->
      <div class="start-section">
        <button v-if="isCompleted" class="btn-back-result" @click="showConfig = false">
          <i class="fas fa-arrow-left"></i> 返回结果
        </button>
        <div class="reeval-hint" v-if="isCompleted && reevalScope === 'failed'">
          <i class="fas fa-info-circle" style="color:#f59e0b"></i>
          仅重评 {{ failedCount }} 篇失败/跳过的文献
        </div>
        <div class="credit-hint" v-if="estimatedCredits > 0">
          <i class="fas fa-coins" style="color:#f59e0b"></i>
          预计消耗 {{ estimatedCredits }} 积分
        </div>
        <button
          class="btn-start"
          @click="showConfirmModal = true"
          :disabled="!canStart"
        >
          <i class="fas fa-play"></i>
          {{ isCompleted ? (reevalScope === 'failed' ? '重新评价（失败/跳过）' : '重新评价（全部）') : '开始 AI 评价' }}
        </button>
      </div>
    </div>

      <!-- 运行中 / 已完成进度面板 -->
    <div v-if="isRunning || (isCompleted && !showConfig)" class="progress-panel">
      <div class="progress-head">
        <div class="progress-status-icon" :class="isCompleted ? 'done' : 'running'">
          <i :class="isCompleted ? 'fas fa-check' : 'fas fa-spinner fa-spin'"></i>
        </div>
        <div>
          <p class="progress-title">{{ isCompleted ? 'AI 评价完成' : 'AI 评价进行中...' }}</p>
          <p class="progress-subtitle">共 {{ totalCount }} 篇文献，已完成 {{ doneCount }} 篇</p>
        </div>
        <div style="margin-left:auto;display:flex;gap:8px;">
          <button v-if="isCompleted" class="btn-reeval" @click="enterReeval('failed')">
            <i class="fas fa-redo"></i> 重评失败/跳过
          </button>
          <button v-if="isCompleted" class="btn-reeval btn-reeval-all" @click="enterReeval('all')">
            <i class="fas fa-rotate"></i> 重评全部
          </button>
          <button v-if="!isCompleted" class="btn-cancel" @click="handleCancel">
            <i class="fas fa-stop"></i> 取消
          </button>
        </div>
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
        <div class="stat-item">
          <span class="stat-dot dot-blue"></span>
          运行中 {{ qa.evalProgress.summary.running }}
        </div>
        <div class="stat-item">
          <span class="stat-dot dot-green"></span>
          完成 {{ qa.evalProgress.summary.completed }}
        </div>
        <div class="stat-item">
          <span class="stat-dot dot-orange"></span>
          摘要评价 {{ qa.evalProgress.summary.abstract_only || 0 }}
        </div>
        <div class="stat-item">
          <span class="stat-dot dot-gray"></span>
          跳过 {{ (qa.evalProgress.summary.skipped_no_fulltext || 0) + (qa.evalProgress.summary.skipped_no_method || 0) }}
        </div>
        <div class="stat-item">
          <span class="stat-dot dot-red"></span>
          失败 {{ qa.evalProgress.summary.failed || 0 }}
        </div>
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

    <!-- 底部操作 -->
    <div class="step-footer-actions">
      <button class="btn-secondary" @click="qa.currentStep = 2">
        <i class="fas fa-arrow-left"></i> 上一步
      </button>
      <button
        class="btn-primary"
        :disabled="!isCompleted"
        @click="qa.currentStep = 4"
      >
        下一步：结果审核 <i class="fas fa-arrow-right"></i>
      </button>
    </div>

    <!-- 启动确认弹窗 -->
    <Teleport to="body">
      <div v-if="showConfirmModal" class="modal-mask" @click.self="showConfirmModal = false">
        <div class="modal-box">
          <div class="modal-head">
            <i class="fas fa-robot" style="color:#f59e0b"></i>
            <span>确认启动 AI 评价</span>
          </div>
          <div class="modal-body">
            <p>即将对 <strong>{{ aiSupportedCount }}</strong> 篇文献进行 AI 质量评价。</p>
            <ul class="confirm-list">
              <li>评价模式：<strong>{{ evalMode === 'dual' ? '双模型校验' : '单模型评价' }}</strong></li>
              <li>使用模型：<strong>{{ selectedModels.join(' / ') }}</strong></li>
              <li v-if="noFultextCount > 0">{{ noFultextCount }} 篇文献无全文，将使用摘要评价</li>
            </ul>
            <p class="confirm-credit" v-if="estimatedCredits > 0">
              <i class="fas fa-coins" style="color:#f59e0b"></i>
              本次预计消耗 <strong>{{ estimatedCredits }}</strong> 积分
            </p>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="showConfirmModal = false">取消</button>
            <button class="btn-primary" @click="doStartEval" :disabled="startLoading">
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useQAStore } from '@/stores/qa'
import { useProjectStore } from '@/stores/project'

const qa      = useQAStore()
const project = useProjectStore()

const evalMode      = ref('single')
const selectedModels = ref(['deepseek'])
const showConfirmModal = ref(false)
const startLoading  = ref(false)
const showConfig    = ref(true)   // 控制配置面板显示：未评价时/点重新评价时显示
const reevalScope   = ref('all')  // 重评范围：'all' | 'failed'

const evalModes = [
  {
    key: 'single',
    icon: 'fas fa-circle-dot',
    name: '单模型评价',
    desc: '使用一个模型进行评价，速度较快，适合初步筛查',
  },
  {
    key: 'dual',
    icon: 'fas fa-code-compare',
    name: '双模型校验',
    desc: '两个模型独立评价并比对结果，不一致时标记分歧，结果更可靠',
  },
]

const availableModels = [
  { id: 'deepseek', name: 'DeepSeek V3', provider: 'DeepSeek', recommended: true },
  { id: 'gpt4o',   name: 'GPT-4o',      provider: 'OpenAI',    recommended: false },
  { id: 'claude3',  name: 'Claude 3.5',  provider: 'Anthropic', recommended: false },
  { id: 'qwen',    name: 'Qwen-Max',     provider: '阿里云',    recommended: false },
]

// ── 统计 ──────────────────────────────────────────────────────────────────────

const AI_SUPPORTED = new Set(['QUADAS2', 'NOS'])

const totalCount      = computed(() => qa.refs.length)
const aiSupportedCount = computed(() => qa.refs.filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method)).length)
const noMethodCount   = computed(() => qa.refs.filter(r => !r.quality_method).length)
const noFultextCount  = computed(() => qa.refs.filter(r => r.fulltext_status !== 'available').length)
const failedCount     = computed(() => {
  const failedStatuses = ['failed', 'skipped_no_fulltext', 'skipped_no_method']
  return qa.refs.filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method) && failedStatuses.includes(r.ai_eval_status)).length
})
const estimatedCredits = computed(() => {
  const count = reevalScope.value === 'failed' ? failedCount.value : aiSupportedCount.value
  return count * (evalMode.value === 'dual' ? 10 : 5)
})

// ── 进度 ──────────────────────────────────────────────────────────────────────

const isRunning   = computed(() => {
  if (!qa.evalProgress?.summary) return false
  return qa.evalProgress.summary.running > 0
})
const isCompleted = computed(() => qa.evalCompleted)

const doneCount = computed(() => {
  if (!qa.evalProgress?.summary) return 0
  return (qa.evalProgress.summary.completed || 0) +
         (qa.evalProgress.summary.failed || 0) +
         (qa.evalProgress.summary.abstract_only || 0) +
         (qa.evalProgress.summary.skipped_no_fulltext || 0) +
         (qa.evalProgress.summary.skipped_no_method || 0)
})

const progressPct = computed(() => {
  if (!totalCount.value) return 0
  return Math.round((doneCount.value / totalCount.value) * 100)
})

// ── 模型选择 ──────────────────────────────────────────────────────────────────

function isModelDisabled(id) {
  if (evalMode.value === 'single') return false
  // dual 模式：已选 2 个且当前不在选中列表 → 禁用
  return selectedModels.value.length >= 2 && !selectedModels.value.includes(id)
}

function toggleModel(id) {
  if (isModelDisabled(id)) return
  const idx = selectedModels.value.indexOf(id)
  if (idx !== -1) {
    if (selectedModels.value.length > 1) selectedModels.value.splice(idx, 1)
    return
  }
  if (evalMode.value === 'single') {
    selectedModels.value = [id]
  } else {
    if (selectedModels.value.length < 2) selectedModels.value.push(id)
  }
}

const canStart = computed(() => {
  if (!aiSupportedCount.value) return false
  if (!selectedModels.value.length) return false
  if (evalMode.value === 'dual' && selectedModels.value.length < 2) return false
  return true
})

// ── 启动评价 ──────────────────────────────────────────────────────────────────

async function doStartEval() {
  startLoading.value = true
  try {
    let refIds
    if (reevalScope.value === 'failed') {
      // 仅重评失败/跳过的文献
      const failedStatuses = ['failed', 'skipped_no_fulltext', 'skipped_no_method']
      refIds = qa.refs
        .filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method) && failedStatuses.includes(r.ai_eval_status))
        .map(r => r.id)
      if (!refIds.length) {
        alert('没有需要重评的失败/跳过文献')
        return
      }
    } else {
      refIds = qa.refs
        .filter(r => r.quality_method && AI_SUPPORTED.has(r.quality_method))
        .map(r => r.id)
    }
    await qa.startEval(project.currentProject.id, refIds, evalMode.value, selectedModels.value)
    showConfirmModal.value = false
    showConfig.value = false   // 启动后隐藏配置，显示进度
    // 开始轮询
    qa.startPollingProgress(project.currentProject.id)
    // 立即拉一次
    await qa.fetchEvalProgress(project.currentProject.id)
  } catch (e) {
    alert(e?.response?.data?.error || '启动失败，请重试')
  } finally {
    startLoading.value = false
  }
}

function enterReeval(scope) {
  reevalScope.value = scope
  showConfig.value = true   // 回到配置界面
}

function handleCancel() {
  qa.stopPolling()
}

// ── 生命周期 ──────────────────────────────────────────────────────────────────

onMounted(async () => {
  // 如果有进行中的评价，自动恢复轮询
  if (project.currentProject) {
    await qa.fetchEvalProgress(project.currentProject.id)
    if (isRunning.value) {
      qa.startPollingProgress(project.currentProject.id)
      showConfig.value = false
    } else if (isCompleted.value) {
      showConfig.value = false   // 已完成 → 默认显示结果面板，不遮住进度
    }
  }
})

onUnmounted(() => {
  // 离开步骤时停止轮询（已完成则保留状态）
  if (!isCompleted.value) qa.stopPolling()
})

// ── 状态显示 ──────────────────────────────────────────────────────────────────

function statusLabel(s) {
  return {
    pending:              '等待中',
    running:              '评价中',
    completed:            '已完成',
    abstract_only:        '摘要评价',
    failed:               '失败',
    skipped_no_fulltext:  '跳过（无内容）',
    skipped_no_method:    '跳过（无方法）',
  }[s] || s
}
function statusIconClass(s) {
  return {
    pending:              'fas fa-clock text-gray',
    running:              'fas fa-spinner fa-spin text-blue',
    completed:            'fas fa-check-circle text-green',
    abstract_only:        'fas fa-file-lines text-orange',
    failed:               'fas fa-times-circle text-red',
    skipped_no_fulltext:  'fas fa-ban text-gray',
    skipped_no_method:    'fas fa-ban text-gray',
  }[s] || 'fas fa-circle'
}
function statusBadgeClass(s) {
  return {
    pending:              'badge-gray',
    running:              'badge-blue',
    completed:            'badge-green',
    abstract_only:        'badge-orange',
    failed:               'badge-red',
    skipped_no_fulltext:  'badge-gray',
    skipped_no_method:    'badge-gray',
  }[s] || 'badge-gray'
}
</script>

<style scoped>
.qa-aiev { display: flex; flex-direction: column; gap: 16px; }
.step-header { display: flex; align-items: center; gap: 12px; }
.step-icon-wrap { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.step-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.step-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }

/* 概览 */
.overview-row { display: flex; align-items: center; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 20px; gap: 0; }
.ov-item { flex: 1; text-align: center; }
.ov-val { display: block; font-size: 1.5rem; font-weight: 700; color: #1e293b; line-height: 1.2; }
.ov-val.ai-ok { color: #10b981; }
.ov-val.text-gray { color: #94a3b8; }
.ov-val.text-orange { color: #f59e0b; }
.ov-label { font-size: 0.72rem; color: #64748b; }
.ov-divider { width: 1px; height: 36px; background: #e2e8f0; flex-shrink: 0; }

/* 配置卡片 */
.config-section { display: flex; flex-direction: column; gap: 12px; }
.config-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; }
.config-label { font-size: 0.82rem; font-weight: 600; color: #475569; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.config-tip { font-size: 0.72rem; color: #94a3b8; font-weight: 400; }

/* 模式选项 */
.mode-options { display: flex; gap: 10px; }
.mode-option { flex: 1; display: flex; align-items: flex-start; gap: 12px; padding: 14px; border: 2px solid #e2e8f0; border-radius: 10px; cursor: pointer; transition: all 0.15s; }
.mode-option:hover { border-color: #a5b4fc; background: #f5f3ff; }
.mode-option.active { border-color: #6366f1; background: #eef2ff; }
.mode-icon { width: 32px; height: 32px; background: #f1f5f9; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #6366f1; flex-shrink: 0; font-size: 1rem; }
.mode-option.active .mode-icon { background: #6366f1; color: #fff; }
.mode-name { font-size: 0.85rem; font-weight: 600; color: #1e293b; margin: 0 0 2px; }
.mode-desc { font-size: 0.72rem; color: #64748b; margin: 0; }

/* 模型网格 */
.model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.model-option { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 2px solid #e2e8f0; border-radius: 10px; cursor: pointer; transition: all 0.15s; }
.model-option:hover:not(.disabled) { border-color: #a5b4fc; }
.model-option.selected { border-color: #6366f1; background: #eef2ff; }
.model-option.disabled { opacity: 0.45; cursor: not-allowed; }
.model-check { width: 18px; height: 18px; border: 2px solid #e2e8f0; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.6rem; color: #fff; flex-shrink: 0; background: #fff; }
.model-option.selected .model-check { background: #6366f1; border-color: #6366f1; }
.model-name { font-size: 0.82rem; font-weight: 600; color: #1e293b; margin: 0; }
.model-provider { font-size: 0.7rem; color: #94a3b8; margin: 0; }
.tag-amber { background: #fef3c7; color: #b45309; font-size: 0.65rem; padding: 1px 5px; border-radius: 4px; }

/* 启动区 */
.start-section { display: flex; justify-content: flex-end; align-items: center; gap: 12px; flex-wrap: wrap; }
.credit-hint { font-size: 0.78rem; color: #94a3b8; display: flex; align-items: center; gap: 4px; }
.reeval-hint { font-size: 0.78rem; color: #f59e0b; display: flex; align-items: center; gap: 4px; }
.btn-start { padding: 10px 28px; background: linear-gradient(135deg, #f59e0b, #f97316); color: #fff; border: none; border-radius: 10px; cursor: pointer; font-size: 0.9rem; font-weight: 600; display: flex; align-items: center; gap: 8px; box-shadow: 0 2px 8px rgba(249,115,22,.25); }
.btn-start:hover:not(:disabled) { opacity: 0.9; }
.btn-start:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-back-result { padding: 8px 14px; background: #fff; border: 1px solid #e2e8f0; color: #64748b; border-radius: 8px; cursor: pointer; font-size: 0.8rem; display: flex; align-items: center; gap: 5px; }
.btn-back-result:hover { border-color: #6366f1; color: #6366f1; }
.btn-reeval { padding: 7px 14px; background: #fff; border: 1px solid #e2e8f0; color: #475569; border-radius: 8px; cursor: pointer; font-size: 0.78rem; display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.btn-reeval:hover { border-color: #f59e0b; color: #f59e0b; }
.btn-reeval-all:hover { border-color: #6366f1; color: #6366f1; }

/* 进度面板 */
.progress-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.progress-head { display: flex; align-items: center; gap: 12px; }
.progress-status-icon { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.1rem; flex-shrink: 0; }
.progress-status-icon.running { background: #dbeafe; color: #2563eb; }
.progress-status-icon.done { background: #d1fae5; color: #059669; }
.progress-title { font-size: 0.92rem; font-weight: 600; color: #1e293b; margin: 0; }
.progress-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }
.btn-cancel { margin-left: auto; padding: 6px 14px; border: 1px solid #fca5a5; background: #fff; color: #ef4444; border-radius: 7px; cursor: pointer; font-size: 0.8rem; display: flex; align-items: center; gap: 6px; }

.progress-bar-wrap { display: flex; align-items: center; gap: 10px; }
.progress-bar-track { flex: 1; height: 8px; background: #f1f5f9; border-radius: 9999px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 9999px; transition: width 0.5s ease; }
.progress-pct { font-size: 0.78rem; color: #64748b; width: 36px; text-align: right; flex-shrink: 0; }

.stat-row { display: flex; gap: 16px; flex-wrap: wrap; }
.stat-item { display: flex; align-items: center; gap: 5px; font-size: 0.78rem; color: #64748b; }
.stat-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-blue { background: #3b82f6; }
.dot-green { background: #10b981; }
.dot-orange { background: #f59e0b; }
.dot-gray { background: #94a3b8; }
.dot-red { background: #ef4444; }

.ref-progress-list { display: flex; flex-direction: column; gap: 4px; max-height: 220px; overflow-y: auto; border-top: 1px solid #f1f5f9; padding-top: 10px; }
.ref-prog-item { display: flex; align-items: center; gap: 8px; padding: 5px 0; }
.status-icon { width: 14px; flex-shrink: 0; font-size: 0.78rem; }
.text-blue { color: #3b82f6; }
.text-green { color: #10b981; }
.text-orange { color: #f59e0b; }
.text-red { color: #ef4444; }
.text-gray { color: #94a3b8; }
.ref-prog-title { flex: 1; font-size: 0.78rem; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-badge { font-size: 0.68rem; padding: 1px 6px; border-radius: 4px; flex-shrink: 0; }
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

/* 确认弹窗 */
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 9999; }
.modal-box { background: #fff; border-radius: 16px; width: 420px; max-width: 94vw; box-shadow: 0 16px 48px rgba(0,0,0,.18); }
.modal-head { display: flex; align-items: center; gap: 10px; padding: 20px 24px 16px; font-size: 1rem; font-weight: 600; color: #1e293b; border-bottom: 1px solid #f1f5f9; }
.modal-body { padding: 16px 24px; font-size: 0.85rem; color: #475569; }
.modal-body p { margin: 0 0 10px; }
.confirm-list { margin: 0 0 10px; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; }
.confirm-credit { color: #f59e0b; display: flex; align-items: center; gap: 6px; font-size: 0.82rem; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 24px; border-top: 1px solid #f1f5f9; }
</style>
