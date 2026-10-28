<template>
  <div class="rs-stack">
    <header class="rs-section-heading">
      <div>
        <h2>AI 全文复筛</h2>
        <p>
          选择已准备全文的文献和模型，按排除标准生成可追溯建议。也可以跳过
          AI，直接人工审阅。
        </p>
      </div>
    </header>
    <RescreenReferenceList
      selectable
      ready-only
      action-label="查看"
      @open="openReference"
    />
    <section class="rs-card">
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
    <section class="rs-card rs-estimate">
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
        }}</strong><small>预占采用保守上界，实际消费按返回用量结算，未使用部分会释放。不展示
          Token。</small><small v-if="balance">{{
          balance.is_unlimited
            ? '管理员：不扣积分，保留用量审计'
            : `可用余额 ${balance.balance.toLocaleString()} 积分`
        }}</small>
      </div>
      <div class="rs-actions">
        <button :disabled="blocked || !canEstimate" @click="calculate">
          重新预估
        </button><button
          class="primary"
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
          开始 AI 复筛
        </button>
      </div>
    </section>
    <section class="rs-card">
      <div class="rs-toolbar">
        <h3>运行记录</h3>
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
            #{{ run.id }} · {{ label(run.status) }} · {{ run.total_count }} 篇
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
        <progress
          :value="ws.state.run.processed_count"
          :max="ws.state.run.total_count || 1"
        />
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
        <div class="rs-table-scroll">
          <table class="rs-table">
            <thead>
              <tr>
                <th>文献</th>
                <th>状态</th>
                <th>共识建议</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in ws.state.runItems.items" :key="item.id">
                <td class="rs-title-cell">
                  <strong :title="item.title">{{ item.title }}</strong>
                </td>
                <td>{{ label(item.status) }}</td>
                <td>{{ label(item.consensus) }}</td>
                <td><button @click="view(item)">查看结果</button></td>
              </tr>
            </tbody>
          </table>
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
    <section v-if="resultDetail" class="rs-card">
      <div class="rs-toolbar">
        <h3 class="rs-wrap">{{ resultDetail.bibliography.title }}</h3>
        <button @click="resultDetail = null">关闭结果</button>
      </div>
      <RescreenEvidence :detail="resultDetail" @page="openPdf" />
    </section>
  </div>
</template>
<script setup>
import { computed, inject, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as billing from '@/features/billing/api'
import { label, safePdfUrl } from '../state'
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
const estimateKey = ref('')
const modelsDirty = computed(
  () =>
    JSON.stringify([...selectedModels.value].sort()) !==
    JSON.stringify([...savedModels.value].sort()),
)
watch(() => ws.state.info.configuration.version, () => {
  if (!modelsDirty.value) {
    selectedModels.value = [...ws.state.info.configuration.model_ids]
    savedModels.value = [...selectedModels.value]
    baseVersion.value = ws.state.info.configuration.version
  }
})
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
  await ws.start(payload.value)
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
