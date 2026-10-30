<template>
  <div class="ai-layout">
    <section class="ai-left">
      <div class="rs-head">
        <div>
          <h3>AI 全文复筛</h3>
          <p>选择模型，根据全文与排除标准生成建议；最终结果仍需人工确认。</p>
        </div>
        <button
          class="primary-btn"
          :disabled="
            blocked ||
              modelsDirty ||
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
      <div class="panel">
        <div class="panel-title">
          <h4>任务输入</h4>
          <span>仅处理全文已就绪的文献</span>
        </div>
        <div class="task-grid">
          <div>
            <b>{{ ws.state.info.counts.ready }}</b><span>可进入 AI</span>
          </div>
          <div>
            <b>{{ ws.state.selected.length }}</b><span>本次已选</span>
          </div>
          <div>
            <b>{{ ws.state.info.configuration.criteria.length }}</b><span>排除标准</span>
          </div>
        </div>
      </div>
      <section class="panel model-panel">
        <div class="rs-toolbar">
          <h3>选择模型</h3>
          <small>参考倍率以 DeepSeek Flash 为 1.0×；实际预估按本次证据包计算</small>
        </div>
        <div class="rs-model-grid">
          <div v-for="provider in ws.state.models" :key="provider.id">
            <h4>{{ provider.name }}</h4>
            <label
              v-for="model in provider.sub_models"
              :key="model.id"
              class="rs-model-option"
              :class="{
                chosen: selectedModels.includes(model.id),
                unavailable: !model.configured,
              }"
            ><input
              v-model="selectedModels"
              type="checkbox"
              :value="model.id"
              :disabled="!model.configured || blocked"
            /><span><strong>{{ model.name }}</strong><small>{{
              model.configured ? model.description : '模型凭据未配置'
            }}</small></span><b v-if="hints[model.id]">{{ hints[model.id] }}×</b></label>
          </div>
        </div>
        <div class="rs-toolbar">
          <span v-if="modelsDirty" class="rs-warning">模型选择尚未保存</span><button v-if="modelsDirty" :disabled="blocked" @click="saveModels">
            保存模型选择
          </button><small v-if="hintError">{{ hintError }}</small>
        </div>
      </section>

      <RescreenPrompt v-if="canPrompt" />
      <div class="panel">
        <div class="panel-title">
          <h4>排除标准摘要</h4>
          <span>已保存到服务器</span>
        </div>
        <ul class="criteria-mini">
          <li
            v-for="criterion in ws.state.info.configuration.criteria"
            :key="criterion.id"
          >
            {{ criterion.text }}
          </li>
        </ul>
      </div>
      <section class="panel rs-estimate">
        <div>
          <h3>本次预估</h3>
          <p>
            选择 {{ ws.state.selected.length }} 篇文献 ·
            {{ selectedModels.length }} 个模型
          </p>
          <strong>{{
            validEstimate
              ? `${validEstimate.reserve_credits.toLocaleString()} 积分预占`
              : '选择文献和模型后自动预估'
          }}</strong><small>预占采用保守上界，实际消费按返回用量结算，未使用部分会释放。</small><small v-if="balance">{{
            balance.is_unlimited
              ? '管理员：不扣积分，保留用量审计'
              : `可用余额 ${balance.balance.toLocaleString()} 积分`
          }}</small>
        </div>
        <div class="rs-actions">
          <button :disabled="blocked || !canEstimate" @click="calculate">
            重新预估
          </button>
        </div>
      </section>
    </section>
    <section class="ai-right panel">
      <div class="panel-title">
        <h4>AI 结果预览</h4>
        <span>最终仍需人工确认</span>
      </div>
      <div class="result-tabs">
        <button
          :class="{ selected: resultTab === 'input' }"
          @click="resultTab = 'input'"
        >
          待复筛文献
        </button><button
          :class="{ selected: resultTab === 'results' }"
          @click="resultTab = 'results'"
        >
          运行进度与结果
        </button>
      </div>
      <div v-show="resultTab === 'input'">
        <RescreenReferenceList
          variant="ai"
          selectable
          ready-only
          action-label="查看"
          @open="openReference"
        />
      </div>
      <div v-show="resultTab === 'results'">
        <section class="run-panel">
          <div class="rs-toolbar">
            <h4>运行记录</h4>
            <select
              :value="ws.state.runId || ''"
              aria-label="选择复筛运行记录"
              @change="ws.read(() => ws.loadRun(Number($event.target.value)))"
            >
              <option value="" disabled>暂无运行</option>
              <option
                v-for="run in ws.state.runs.items"
                :key="run.id"
                :value="run.id"
              >
                #{{ run.id }} · {{ label(run.status) }} ·
                {{ run.total_count }} 篇
              </option>
            </select><button
              v-if="
                ws.state.info.active_run_id &&
                  ws.state.runId !== ws.state.info.active_run_id
              "
              @click="ws.read(() => ws.loadRun(ws.state.info.active_run_id))"
            >
              返回活动任务
            </button>
          </div>
          <template v-if="ws.state.run">
            <div class="rs-run-summary">
              <strong>运行 #{{ ws.state.run.id }} ·
                {{ label(ws.state.run.status) }}</strong><span>{{ ws.state.run.processed_count }} /
                {{ ws.state.run.total_count }} 篇</span>
            </div>
            <div
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
            <div
              v-for="item in ws.state.runItems.items"
              :key="item.id"
              class="result-item"
            >
              <div>
                <strong :title="item.title">{{ item.title }}</strong>
                <p>{{ label(item.status) }}</p>
              </div>
              <div class="rs-actions">
                <span class="decision" :class="item.consensus">{{
                  decisionLabel(item.consensus)
                }}</span><button @click="view(item)">查看结果</button>
              </div>
            </div>
            <RescreenPagination
              :page="ws.state.runItems"
              @change="(p, s) => ws.read(() => ws.loadRunItems(p, s))"
            />
          </template>
          <p v-else class="rs-empty">暂无 AI 运行，可以先选择文献和模型。</p>
          <RescreenPagination
            :page="ws.state.runs"
            @change="(p, s) => ws.read(() => ws.loadRuns(p, s))"
          />
        </section>
      </div>
      <section v-if="resultDetail" class="result-detail">
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
import { computed, inject, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as billing from '@/features/billing/api'
import { label, decisionLabel, safePdfUrl } from '../state'
import RescreenReferenceList from './RescreenReferenceList.vue'
import RescreenPagination from './RescreenPagination.vue'
import RescreenEvidence from './RescreenEvidence.vue'
import RescreenPrompt from './RescreenPrompt.vue'
defineProps({ canPrompt: Boolean })
const ws = inject('rescreen')
const selectedModels = ref([...ws.state.info.configuration.model_ids])
const savedModels = ref([...selectedModels.value])
const baseVersion = ref(ws.state.info.configuration.version)
const hints = ref({})
const hintError = ref('')
const balance = ref(null)
const resultDetail = ref(null)
const resultTab = ref(ws.state.run ? 'results' : 'input')
const estimateKey = ref('')
const modelsDirty = computed(
  () =>
    JSON.stringify([...selectedModels.value].sort()) !==
    JSON.stringify([...savedModels.value].sort()),
)
watch(
  () => ws.state.info.configuration.version,
  () => {
    if (!modelsDirty.value) {
      selectedModels.value = [...ws.state.info.configuration.model_ids]
      savedModels.value = [...selectedModels.value]
      baseVersion.value = ws.state.info.configuration.version
    }
  },
)
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
onMounted(async () => {
  ws.read(() => ws.loadRuns())
  try {
    const data = (await billing.fetchBalance()).data
    if (alive) balance.value = data
  } catch {
    /* 后端启动仍会核对真实余额 */
  }
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
  ws.state.modelDirty = false
})
watch(
  modelsDirty,
  (value) => {
    ws.state.modelDirty = value
  },
  { immediate: true },
)
watch(
  [signature, () => ws.state.working],
  () => {
    clearTimeout(timer)
    if (!blocked.value && canEstimate.value && lastAttempt !== signature.value)
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
async function saveModels() {
  const result = await ws.action(
    () =>
      ws.api.configuration(ws.state.projectId, {
        expected_version: baseVersion.value,
        criteria: payload.value.criteria,
        model_ids: selectedModels.value,
      }),
    '模型选择已保存。',
  )
  if (result) {
    savedModels.value = [...selectedModels.value]
    baseVersion.value = result.version
  }
}
async function start() {
  if (
    !window.confirm(
      `本轮将预占约 ${validEstimate.value.reserve_credits} 积分，按实际用量结算。${ws.state.info.latest_run_id ? '这是新一轮评价，已完成的文献也会重新调用并计费。' : ''}是否继续？`,
    )
  )
    return
  const result = await ws.start(payload.value)
  if (result) resultTab.value = 'results'
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
  grid-template-columns: 420px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}
.ai-left {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rs-head,
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 18px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}
.rs-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
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
.panel-title span,
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
.panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.task-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.task-grid div {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
}
.task-grid b {
  font-size: 1.3rem;
  color: #1e293b;
  margin-right: 6px;
}
.task-grid span {
  font-size: 0.76rem;
  color: #64748b;
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
.criteria-mini {
  margin: 0;
  padding-left: 18px;
  color: #475569;
  font-size: 0.82rem;
}
.criteria-mini li {
  margin: 7px 0;
}
.ai-right {
  overflow: auto;
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
@media (max-width: 1100px) {
  .ai-layout {
    grid-template-columns: 1fr;
  }
}

.ai-layout {
  align-items: start;
}
.ai-left,
.ai-right {
  min-width: 0;
}
.ai-left .rs-model-grid {
  grid-template-columns: 1fr;
}
.ai-left .rs-model-grid > div {
  grid-column: auto;
}
.ai-left .rs-model-grid h4 {
  margin: 0 0 8px;
}
.ai-left .rs-estimate {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 16px;
}
.ai-left .rs-estimate .rs-actions {
  justify-content: flex-end;
}
.ai-left .rs-estimate strong {
  font-size: 1.2rem;
}
.ai-left :deep(.rs-card) {
  padding: 16px;
}
.ai-right {
  min-height: 420px;
}
.result-tabs {
  display: flex;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 12px;
}
.result-tabs button.selected {
  background: #eef2ff;
  border-color: #c7d2fe;
  color: #4f46e5;
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
.run-panel > p {
  padding: 20px 0;
}
@media (min-width: 1101px) {
  .ai-layout {
    grid-template-columns: 420px minmax(0, 1fr);
  }
}
.decision.excluded {
  background: #fef2f2;
  color: #b91c1c;
}
.decision.conflict {
  background: #fff7ed;
  color: #c2410c;
}
</style>
