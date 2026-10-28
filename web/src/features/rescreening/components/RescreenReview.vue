<template>
  <div class="rs-stack">
    <header class="rs-section-heading">
      <div>
        <h2>人工审阅</h2>
        <p>AI 只是建议。请结合全文作出最终决定；允许跳过 AI 直接审核。</p>
      </div>
      <span class="rs-badge">已最终确认 {{ ws.state.info.counts.finalized }} /
        {{ ws.state.info.counts.total }} 篇</span>
    </header>
    <div class="rs-review-tabs" aria-label="审阅面板切换">
      <button :class="{ primary: pane === 'pdf' }" @click="pane = 'pdf'">全文阅读</button>
      <button :class="{ primary: pane === 'review' }" @click="pane = 'review'">判断与证据</button>
    </div>
    <div class="rs-review-grid">
      <section class="rs-card rs-review-list">
        <form class="rs-stack" @submit.prevent="search">
          <input
            v-model="query"
            type="search"
            maxlength="200"
            placeholder="搜索标题或 DOI"
            aria-label="搜索待审文献"
          />
          <div class="rs-toolbar">
            <select v-model="status" aria-label="审核状态" @change="search">
              <option value="">全部</option>
              <option value="unreviewed">待审核 / 待定</option>
              <option value="reconfirm">需重新确认</option>
              <option value="included">已纳入</option>
              <option value="excluded">已排除</option>
              <option value="not_retrieved">全文未获取</option>
            </select><button>搜索</button>
          </div>
        </form>
        <div class="rs-review-titles">
          <button
            v-for="row in ws.state.refs.items"
            :key="row.id"
            :class="{ current: ws.state.detail?.id === row.id }"
            @click="open(row)"
          >
            <strong :title="row.title">{{ row.title }}</strong><small>{{ row.publication_year || '年份未提供' }} ·
              {{
                row.needs_reconfirmation ? '需重新确认' : label(row.decision)
              }}</small>
          </button>
          <p v-if="!ws.state.refs.items.length" class="rs-empty">
            没有符合条件的文献
          </p>
        </div>
        <RescreenPagination
          :page="ws.state.refs"
          @change="(p, s) => ws.read(() => ws.loadReferences(p, s))"
        />
      </section>
      <section class="rs-card rs-pdf-panel" :class="{ 'rs-hidden-narrow': pane !== 'pdf' }">
        <template v-if="ws.state.detail">
          <div class="rs-toolbar">
            <strong class="rs-wrap">{{ ws.state.detail.title }}</strong><a v-if="pdfUrl" :href="pdfUrl" target="_blank" rel="noopener">独立打开</a>
          </div>
          <RescreenPdf v-if="pdfUrl" :url="ws.state.detail.pdf_url" :page="page" />
          <div v-else class="rs-pdf-empty">
            <i class="fas fa-file-pdf"></i>
            <h3>尚无可读全文</h3>
            <p>返回“全文获取”上传或绑定 PDF；确实无法获取时，可在右侧标记。</p>
            <p v-if="ws.state.detail.bibliography.abstract">
              {{ ws.state.detail.bibliography.abstract }}
            </p>
          </div>
        </template>
        <p v-else class="rs-empty">从左侧选择一篇文献开始审阅</p>
      </section>
      <aside class="rs-card rs-review-inspector" :class="{ 'rs-hidden-narrow': pane !== 'review' }">
        <template v-if="ws.state.detail">
          <h4 class="rs-wrap">{{ ws.state.detail.title }}</h4>
          <div class="rs-toolbar">
            <h3>最终决定</h3>
            <button :disabled="ws.state.working" @click="reload">
              刷新当前文献
            </button>
          </div>
          <p v-if="ws.state.detail.needs_reconfirmation" class="rs-warning">
            输入、标准或 AI 建议已更新。原人工决定保留，但需要重新确认。
          </p>
          <form class="rs-stack" @submit.prevent="save">
            <div class="rs-decision-grid">
              <label
                v-for="choice in decisions"
                :key="choice.value"
                :class="{ chosen: decision === choice.value }"
              ><input
                v-model="decision"
                type="radio"
                :value="choice.value"
                :disabled="
                  ws.state.info.busy ||
                    (choice.value === 'not_retrieved' &&
                      (!!ws.state.detail.pdf_url ||
                        ws.state.detail.fulltext_status === 'processing'))
                "
              />{{ choice.text }}</label>
            </div>
            <template v-if="decision === 'excluded'">
              <label class="rs-field-label">排除理由
                <select
                  :value="''"
                  aria-label="使用排除标准作为理由"
                  @change="reason = $event.target.value"
                >
                  <option value="" disabled>
                    从排除标准选择，或填写具体理由
                  </option>
                  <option
                    v-for="criterion in ws.state.info.configuration.criteria"
                    :key="criterion.id"
                    :value="criterion.text"
                  >
                    {{ criterion.id }} · {{ criterion.text }}
                  </option>
                </select></label><textarea
                v-model="reason"
                rows="3"
                maxlength="2000"
                required
                placeholder="请写明排除理由"
              />
            </template>
            <label class="rs-field-label">备注<textarea
              v-model="note"
              rows="3"
              maxlength="4000"
              placeholder="可选，记录人工判断依据"
            /></label><button
              class="primary"
              :disabled="ws.state.working || ws.state.info.busy || !decision"
            >
              保存人工决定
            </button><small v-if="ws.state.info.busy" class="rs-warning">后台任务运行期间暂不能修改审核，请等待完成或停止。</small><small v-if="dirty" class="rs-warning">有未保存的修改</small>
          </form>
          <div class="rs-toolbar rs-inset">
            <span>AI 共识：{{ label(ws.state.aiDetail?.consensus) }}</span><button
              v-if="
                ['included', 'excluded'].includes(ws.state.aiDetail?.consensus)
              "
              :disabled="ws.state.info.busy"
              @click="adopt"
            >
              采纳到表单
            </button>
          </div>
          <RescreenEvidence :detail="ws.state.aiDetail" @page="showEvidence" />
          <details @toggle="historyToggle">
            <summary>人工审核历史</summary>
            <article
              v-for="event in ws.state.history.items"
              :key="event.id"
              class="rs-inset"
            >
              <strong>{{ label(event.payload.decision) }} ·
                {{ event.author || '原用户已删除' }}</strong><small>{{ new Date(event.created_at).toLocaleString() }}</small>
              <p v-if="event.payload.exclusion_reason">
                {{ event.payload.exclusion_reason }}
              </p>
              <p v-if="event.payload.note" class="rs-wrap">
                {{ event.payload.note }}
              </p>
            </article>
            <RescreenPagination
              :page="ws.state.history"
              @change="(p, s) => ws.read(() => ws.loadHistory(p, s))"
            />
          </details>
        </template>
        <p v-else class="rs-empty">选择文献后显示审核表单和 AI 证据</p>
      </aside>
    </div>
  </div>
</template>
<script setup>
import { computed, inject, ref, watch, onBeforeUnmount } from 'vue'
import { label, safePdfUrl } from '../state'
import RescreenPagination from './RescreenPagination.vue'
import RescreenEvidence from './RescreenEvidence.vue'
import RescreenPdf from './RescreenPdf.vue'
const ws = inject('rescreen')
const query = ref(ws.state.filters.q)
const status = ref(ws.state.filters.status)
const page = ref(1)
const pane = ref('review')
const decision = ref('')
const reason = ref('')
const note = ref('')
const original = ref('')
const decisions = [
  { value: 'included', text: '纳入' },
  { value: 'excluded', text: '排除' },
  { value: 'pending', text: '待定' },
  { value: 'not_retrieved', text: '全文未获取' },
]
const fingerprint = computed(() =>
  JSON.stringify([decision.value, reason.value, note.value]),
)
const dirty = computed(
  () => !!ws.state.detail && fingerprint.value !== original.value,
)
const pdfUrl = computed(() => safePdfUrl(ws.state.detail?.pdf_url, page.value))
watch(
  () => ws.state.detail,
  (detail) => {
    if (!detail) return
    decision.value = detail.review?.decision || ''
    reason.value = detail.review?.exclusion_reason || ''
    note.value = detail.review?.note || ''
    page.value = 1
    original.value = fingerprint.value
  },
  { immediate: true },
)
watch(
  dirty,
  (value) => {
    ws.state.reviewDirty = value
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  ws.state.reviewDirty = false
})
function open(row) {
  if (dirty.value && !window.confirm('当前修改尚未保存，确定切换文献？')) return
  ws.read(() => ws.selectReference(row.id))
}
function reload() {
  if (dirty.value && !window.confirm('刷新会放弃未保存修改，是否继续？')) return
  ws.read(() => ws.selectReference(ws.state.detail.id))
}
function search() {
  ws.state.filters = { q: query.value, status: status.value }
  ws.read(() => ws.loadReferences(1))
}
async function save() {
  const detail = ws.state.detail
  const payload = {
    input_version: detail.input_version,
    expected_version: detail.review_version,
    criteria_revision_id: detail.criteria_revision_id,
    suggestion_id: detail.suggestion_id,
    suggestion_revision: detail.suggestion_revision,
    decision: decision.value,
    exclusion_reason: decision.value === 'excluded' ? reason.value : '',
    note: note.value,
  }
  const result = await ws.action(
    () => ws.api.saveReview(detail.id, payload),
    '人工决定已保存，统计已同步。',
  )
  if (result) ws.state.detail = result
}
function adopt() {
  decision.value = ws.state.aiDetail.consensus
  if (decision.value === 'excluded')
    reason.value = ws.state.aiDetail.models
      .filter(
        (row) => row.status === 'completed' && row.decision === 'excluded',
      )
      .map((row) => row.reason)
      .join('\n')
      .slice(0, 2000)
}
function showEvidence(value) {
  page.value = value
  pane.value = 'pdf'
}
function historyToggle(event) {
  if (event.target.open) ws.read(() => ws.loadHistory())
}
</script>
