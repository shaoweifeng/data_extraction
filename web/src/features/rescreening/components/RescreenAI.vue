<template>
  <div class="ai-layout">
    <section class="ai-left panel" aria-label="复筛文献列表">
      <header class="rs-head">
        <span class="heading-icon"><i class="fas fa-robot"></i></span>
        <div>
          <h3>AI 全文复筛</h3>
          <p>根据全文与排除标准生成筛选建议</p>
        </div>
      </header>
      <div class="result-tabs">
        <button
          :class="{ selected: resultTab === 'all' }"
          :aria-pressed="resultTab === 'all'"
          @click="selectTab('all')"
        >
          全部
          <span class="rs-badge">{{ ws.state.info.counts.total }}</span>
        </button>
        <button
          :class="{ selected: resultTab === 'input' }"
          :aria-pressed="resultTab === 'input'"
          title="全文已就绪，但当前全文与排除标准下尚未完成 AI 复筛"
          @click="selectTab('input')"
        >
          待复筛文献
          <span class="rs-badge">{{ ws.state.info.counts.ai_pending ?? 0 }}</span>
        </button><button
          :class="{ selected: resultTab === 'screened' }"
          :aria-pressed="resultTab === 'screened'"
          title="当前全文与排除标准下已完成 AI 复筛，可查看结果或选择重跑"
          @click="selectTab('screened')"
        >
          已复筛文献
          <span class="rs-badge">{{ ws.state.info.counts.ai_completed ?? 0 }}</span>
        </button>
      </div>
      <div>
        <RescreenReferenceList
          variant="ai"
          selectable
          ready-only
          :ai-status="listStatus"
          action-label="查看"
          @open="openReference"
        />
      </div>
    </section>
    <section class="ai-right" aria-label="模型与任务进度">
      <template v-if="!showRun">
        <section class="panel model-panel">
          <div class="rs-toolbar panel-heading">
            <h3 class="model-heading"><i class="fas fa-brain"></i> 选择模型</h3>
            <button v-if="canSwitchView" class="panel-view-switch" :disabled="blocked" @click="openRun(ws.state.runId)">
              查看运行结果 <i class="fas fa-arrow-right" aria-hidden="true"></i>
            </button>
          </div>
          <small class="model-hint">参考倍率以 DeepSeek Flash 为 1.0×；实际预估按本次证据包计算</small>
          <AiModelPicker
            :providers="ws.state.models"
            :disabled="blocked"
            :is-selected="(id) => selectedModels.includes(id)"
            :multiplier-for="(id) => hints[id]"
            @toggle="toggleModel"
          />
          <small v-if="hintError">{{ hintError }}</small>
        </section>

        <RescreenPrompt v-if="canPrompt" />
        <section class="panel rs-estimate">
          <div>
            <p>
              选择 {{ ws.state.selected.length }} 篇文献 ·
              {{ selectedModels.length }} 个模型
              <button v-if="ws.state.selected.length" type="button" class="rs-link" :disabled="blocked" @click="clearAllSelection">清空已选</button>
            </p>
            <strong>{{
              validEstimate
                ? `${validEstimate.reserve_credits.toLocaleString()} 积分预占`
                : '选择文献和模型后自动预估'
            }}</strong><small>实际消费按返回用量结算，未用积分自动释放。</small><small v-if="balance">{{
              balance.is_unlimited
                ? '管理员：不扣积分，保留用量审计'
                : `可用余额 ${balance.balance.toLocaleString()} 积分`
            }}</small>
          </div>
          <div class="rs-actions">
            <button :disabled="blocked || !canEstimate" @click="calculate">
              重新预估
            </button>
            <button
              class="primary-btn"
              :disabled="
                blocked ||
                  !validEstimate ||
                  ws.state.promptDirty ||
                  (!balance?.is_unlimited &&
                    balance &&
                    balance.balance < validEstimate.reserve_credits)
              "
              @click="start"
            >
              <i class="fas fa-play"></i>开始 AI 复筛
            </button>
          </div>
        </section>
      </template>
      <section v-else class="panel run-panel">
        <div class="rs-toolbar panel-heading">
          <h3>{{ runActive ? '复筛进度' : '复筛结果' }}</h3>
          <button v-if="canSwitchView" class="panel-view-switch" :disabled="blocked" @click="newRound">
            选择模型 <i class="fas fa-arrow-right" aria-hidden="true"></i>
          </button>
          <button
            v-if="ws.state.info.active_run_id && ws.state.runId !== ws.state.info.active_run_id"
            :disabled="ws.state.working"
            @click="openRun(ws.state.info.active_run_id)"
          >
            返回活动任务
          </button>
        </div>
        <div class="rs-run-summary">
          <strong>运行 #{{ ws.state.run.id }} ·
            {{ label(ws.state.run.status) }}</strong><span>{{ ws.state.run.processed_count }} /
            {{ ws.state.run.total_count }} 篇</span>
        </div>
        <div
          v-if="runActive"
          class="progress"
          role="progressbar"
          aria-label="复筛运行进度"
          :aria-valuenow="ws.state.run.processed_count"
          :aria-valuemax="ws.state.run.total_count || 1"
          aria-valuemin="0"
        >
          <div
            :style="{
              width: `${Math.min(100, (ws.state.run.processed_count / (ws.state.run.total_count || 1)) * 100)}%`,
            }"
          ></div>
        </div>
        <div class="rs-toolbar">
          <span
            v-for="(count, status) in ws.state.run.counts"
            :key="status"
            class="rs-badge"
          >{{ label(status) }} {{ count }}</span><button
            v-if="['pending', 'running'].includes(ws.state.run.status)"
            :disabled="ws.state.working"
            @click="runAction('cancel')"
          >
            停止本轮
          </button><button
            v-if="
              ['failed', 'partial', 'paused', 'cancelled'].includes(
                ws.state.run.status,
              )
            "
            :disabled="blocked"
            @click="retry"
          >
            续跑未完成项
          </button><button
            v-if="ws.state.run.status === 'settlement_pending'"
            :disabled="ws.state.working"
            @click="runAction('settle')"
          >
            恢复结算
          </button>
        </div>
        <p v-if="ws.state.run.needs_unknown_ack" class="rs-warning">
          存在处理结果或用量未知的请求，重试可能再次产生供应商费用，需要显式确认。
        </p>
        <details class="run-items-details" open>
          <summary>运行明细 · {{ ws.state.run.total_count }} 篇</summary>
          <div class="run-list">
            <div v-for="item in ws.state.runItems.items" :key="item.id" class="result-item">
              <div>
                <strong :title="item.title">{{ item.title }}</strong>
                <p>{{ label(item.status) }}</p>
              </div>
              <div class="rs-actions">
                <span class="decision" :class="item.consensus">{{ decisionLabel(item.consensus) }}</span>
                <button @click="view(item)">查看结果</button>
              </div>
            </div>
            <RescreenPagination :page="ws.state.runItems" @change="(p, s) => ws.read(() => ws.loadRunItems(p, s))" />
          </div>
        </details>
      </section>
      <section v-if="resultDetail" class="panel result-detail">
        <div class="rs-toolbar">
          <h3 class="rs-wrap">{{ resultDetail.bibliography.title }}</h3>
          <button @click="resultDetail = null">关闭结果</button>
        </div>
        <RescreenEvidence :detail="resultDetail" @page="openPdf" />
      </section>
    </section>
  </div>
</template>
<script setup>
import AiModelPicker from '@/shared/components/AiModelPicker.vue'
import { computed, inject, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as billing from '@/features/billing/api'
import { ACTIVE_RUNS, label, decisionLabel, safePdfUrl } from '../state'
import RescreenReferenceList from './RescreenReferenceList.vue'
import RescreenPagination from './RescreenPagination.vue'
import RescreenEvidence from './RescreenEvidence.vue'
import RescreenPrompt from './RescreenPrompt.vue'
defineProps({ canPrompt: Boolean })
const ws = inject('rescreen')
const selectedModels = ref([
  ...(ws.state.run?.model_ids?.length
    ? ws.state.run.model_ids
    : ws.state.info.configuration.model_ids),
])
function toggleModel(model) {
  selectedModels.value = selectedModels.value.includes(model.id)
    ? selectedModels.value.filter((id) => id !== model.id)
    : [...selectedModels.value, model.id]
}
const hints = ref({})
const hintError = ref('')
const balance = ref(null)
const resultDetail = ref(null)
const resultTab = ref('input')
const listStatus = computed(() => resultTab.value === 'all' ? '' : resultTab.value === 'screened' ? 'ai_completed' : 'ai_pending')
const configuringNewRound = ref(!ACTIVE_RUNS.includes(ws.state.run?.status))
const runActive = computed(() => ACTIVE_RUNS.includes(ws.state.run?.status))
const canSwitchView = computed(() => ws.state.run && !runActive.value && !ws.state.info.active_run_id)
const showRun = computed(() =>
  Boolean(ws.state.run && (!configuringNewRound.value || runActive.value || ws.state.info.active_run_id)),
)
const estimateKey = ref('')
const blocked = computed(() => ws.state.working || ws.state.info.busy)
const payload = computed(() => ({
  ids: [...ws.state.selected].sort((a, b) => a - b),
  criteria: ws.state.info.configuration.criteria.map((row) => row.text),
  model_ids: [...selectedModels.value].sort(),
  expected_revision: ws.state.info.revision,
  expected_settings_version: ws.state.info.configuration.version,
}))
const signature = computed(() => JSON.stringify(payload.value))
const canEstimate = computed(
  () =>
    payload.value.ids.length &&
    payload.value.criteria.length &&
    selectedModels.value.length,
)
const validEstimate = computed(() =>
  estimateKey.value === signature.value ? ws.state.estimate : null,
)
let timer
let alive = true
let lastAttempt = ''
async function refreshBalance() {
  balance.value = null
  try {
    const data = (await billing.fetchBalance()).data
    if (alive) balance.value = data
  } catch {
    /* 后端启动仍会核对真实余额 */
  }
}
onMounted(async () => {
  if (!showRun.value) refreshBalance()
  try {
    const ids = ws.state.models
      .flatMap((provider) => provider.sub_models)
      .filter((row) => row.configured)
      .map((row) => row.id)
    if (!ids.length) return
    const data = (await billing.estimateUsage(1, ids)).data
    if (alive)
      hints.value = Object.fromEntries(
        (data.estimate_detail?.models || []).map((row) => [
          row.model_id,
          row.multiplier,
        ]),
      )
  } catch {
    if (alive) hintError.value = '参考倍率暂不可用，请以本次预估为准。'
  }
})
onBeforeUnmount(() => {
  alive = false
  clearTimeout(timer)
})
watch(
  [signature, blocked, showRun],
  ([key], [previousKey] = []) => {
    clearTimeout(timer)
    if (key !== previousKey) lastAttempt = ''
    if (!showRun.value && !blocked.value && canEstimate.value && lastAttempt !== signature.value)
      timer = setTimeout(calculate, 800)
  },
  { immediate: true },
)
async function calculate() {
  const key = signature.value
  lastAttempt = key
  const result = await ws.estimate(payload.value)
  if (alive && result && key === signature.value) estimateKey.value = key
}
function clearAllSelection() {
  ws.state.selected = []
  ws.state.estimate = null
}
async function start() {
  if (
    !window.confirm(
      `本轮将预占约 ${validEstimate.value.reserve_credits} 积分，按实际用量结算。${ws.state.info.latest_run_id ? '这是新一轮评价，已完成的文献也会重新调用并计费。' : ''}是否继续？`,
    )
  )
    return
  const result = await ws.start(payload.value)
  if (result) {
    clearAllSelection()
    configuringNewRound.value = false
    resultDetail.value = null
  }
}
function newRound() {
  configuringNewRound.value = true
  resultDetail.value = null
  selectTab('input')
  estimateKey.value = ''
  lastAttempt = ''
  refreshBalance()
}
function selectTab(tab) {
  resultTab.value = tab
  ws.state.filters = { q: ws.state.filters.q, status: listStatus.value }
  ws.read(() => ws.loadReferences(1))
}
async function openRun(id) {
  if (!id) return
  await ws.read(() => ws.loadRun(id))
  if (alive && ws.state.run?.id === id) {
    configuringNewRound.value = false
    resultDetail.value = null
  }
}
function runAction(action) {
  ws.action(() => ws.api.runAction(ws.state.runId, action))
}
function retry() {
  const unknown = ws.state.run.needs_unknown_ack
  if (
    unknown &&
    !window.confirm(
      '历史请求的处理结果或费用未知，续跑可能再次产生费用。确认仍要重试？',
    )
  )
    return
  ws.action(() =>
    ws.api.runAction(ws.state.runId, 'retry', { acknowledge_unknown: unknown }),
  )
}
async function view(item) {
  resultDetail.value = await ws.read(() => ws.api.item(item.id))
}
async function openReference(row) {
  const detail = await ws.read(() => ws.selectReference(row.id))
  if (detail)
    resultDetail.value = ws.state.aiDetail
      ? { ...ws.state.aiDetail, pdf_url: detail.pdf_url }
      : {
          bibliography: detail.bibliography,
          models: [],
          pdf_url: detail.pdf_url,
        }
}
function openPdf(page) {
  const url = safePdfUrl(resultDetail.value?.pdf_url, page)
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}
</script>
<style scoped>
.ai-layout {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  gap: 0;
  min-height: 0;
}
.ai-left.panel {
  padding: 0;
  background: #fafbff;
  overflow: hidden;
}
.ai-right {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 16px;
}
.heading-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 18px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}
.rs-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid #e2e8f0;
}
h3,
h4,
p {
  margin: 0;
}
h3 {
  font-size: 1.05rem;
  color: #1e293b;
}
.rs-head p,
.result-item p {
  font-size: 0.78rem;
  color: #64748b;
  margin-top: 4px;
  line-height: 1.5;
}
.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 0;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}
.primary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.progress {
  height: 8px;
  background: #eef2ff;
  border-radius: 999px;
  overflow: hidden;
  margin-top: 14px;
}
.progress div {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  transition: width 0.3s;
}
.result-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 0;
  border-bottom: 1px solid #f1f5f9;
}
.result-item strong {
  font-size: 0.86rem;
  color: #1e293b;
}
.decision {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 4px 9px;
  font-size: 0.74rem;
  font-weight: 700;
  background: #f8fafc;
  color: #64748b;
}
.decision.included {
  background: #ecfdf5;
  color: #047857;
}
.decision.pending {
  background: #fffbeb;
  color: #b45309;
}
.decision.skipped_unbound {
  background: #f1f5f9;
  color: #64748b;
}
@media (max-width: 1000px) {
  .ai-layout {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .ai-right {
    padding-left: 0;
  }
}

.ai-layout {
  align-items: start;
}
.ai-left,
.ai-right {
  min-width: 0;
}
.ai-right .rs-estimate {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.ai-right .rs-estimate .rs-actions {
  justify-content: flex-end;
  flex-wrap: wrap;
}
.ai-right :deep(.rs-card) {
  padding: 16px;
}
.result-tabs {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  flex-wrap: wrap;
  border-bottom: 1px solid #e2e8f0;
}
.result-tabs button.selected {
  background: #eef2ff;
  border-color: #c7d2fe;
  color: #4f46e5;
}
.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.ai-right .panel-view-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: #4f46e5;
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}
.ai-right .panel-view-switch:hover:not(:disabled) {
  color: #3730a3;
  text-decoration: underline;
}
.ai-right .panel-view-switch:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.model-hint {
  display: block;
  margin-bottom: 12px;
  color: #64748b;
}
.result-item > div:first-child {
  min-width: 0;
}
.result-item strong {
  overflow-wrap: anywhere;
}
.result-item .rs-actions {
  flex-shrink: 0;
}
.result-detail {
  padding-top: 16px;
  margin-top: 16px;
  border-top: 1px solid #e2e8f0;
}
.model-panel small {
  line-height: 1.5;
}
.decision.excluded {
  background: #fef2f2;
  color: #b91c1c;
}
.decision.conflict {
  background: #fff7ed;
  color: #c2410c;
}
.run-list {
  padding: 0 12px 12px;
  max-height: 520px;
  overflow: auto;
}
.run-items-details {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}
.run-items-details summary {
  cursor: pointer;
  color: #475569;
  font-size: 0.84rem;
  font-weight: 600;
}
.model-panel {
  background: #fafbff;
  border-color: #e0e7ff;
}
.result-item .rs-actions {
  max-width: 45%;
  justify-content: flex-end;
}
.model-panel {
  padding: 12px 14px;
}
.model-panel > .rs-toolbar:first-child {
  margin-bottom: 10px;
}
.model-heading {
  font-size: 0.82rem;
  font-weight: 600;
}
.model-heading i {
  color: #818cf8;
}
.ai-right .rs-estimate {
  padding: 12px 14px;
}
.ai-right .rs-estimate p {
  margin: 0 0 4px;
}
.ai-right .rs-estimate strong {
  margin-bottom: 4px;
  font-size: 1rem;
}
</style>
