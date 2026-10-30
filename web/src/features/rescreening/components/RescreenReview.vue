<template>
  <div class="step-review rescreen-review">
    <div class="review-body">
      <div class="list-panel">
        <form class="search-box" @submit.prevent="search">
          <i class="fas fa-search"></i><input
            v-model="query"
            type="search"
            maxlength="200"
            placeholder="搜索标题或 DOI…"
            aria-label="搜索待审文献"
          /><button type="submit" aria-label="搜索">
            <i class="fas fa-arrow-right"></i>
          </button>
        </form>
        <div class="tab-bar">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: status === tab.key }"
            @click="switchTab(tab.key)"
          >
            <span class="tab-label">{{ tab.label }}</span><span class="tab-count-num">{{ tabCount(tab.key) }}</span>
          </button>
        </div>
        <div class="ref-list">
          <button
            v-for="(row, index) in ws.state.refs.items"
            :key="row.id"
            class="ref-item"
            :class="{
              selected: ws.state.detail?.id === row.id,
              override: row.review_valid,
            }"
            @click="open(row)"
          >
            <span class="ref-num">{{
              (ws.state.refs.page - 1) * ws.state.refs.page_size + index + 1
            }}</span>
            <span class="ref-main"><span class="ref-title" :title="row.title">{{ row.title }}</span><span class="ref-sub"><span>{{ row.publication_year || '未知年份' }}</span><span class="ref-journal">{{
              row.journal || '未知期刊'
            }}</span></span></span>
            <span class="ref-status"><span v-if="row.needs_reconfirmation" class="badge conflict">重确认</span><span
              v-else-if="row.decision"
              class="badge human"
              :class="row.decision"
            >{{ decisionLabel(row.decision) }}</span><span
              v-else-if="row.suggestion === 'conflict'"
              class="badge conflict"
            >分歧</span><span
              v-else-if="row.suggestion"
              class="badge ai"
              :class="row.suggestion"
            >AI · {{ decisionLabel(row.suggestion) }}</span><span v-else class="badge pending">待审</span></span>
          </button>
          <p v-if="!ws.state.refs.items.length" class="list-empty">
            没有符合条件的文献
          </p>
        </div>
        <div class="review-list-footer">
          <RescreenPagination
            :page="ws.state.refs"
            :disabled="ws.state.working"
            @change="changePage"
          />
          <p>
            已最终确认 {{ ws.state.info.counts.finalized }} /
            {{ ws.state.info.counts.total }} 篇
          </p>
          <button
            v-if="ws.state.info.counts.needs_reconfirmation"
            class="reconfirm-btn"
            @click="switchTab('reconfirm')"
          >
            查看
            {{ ws.state.info.counts.needs_reconfirmation }} 篇需重新确认文献
          </button>
        </div>
      </div>
      <div v-if="ws.state.detail" class="detail-panel">
        <div class="detail-meta">
          <div class="title-row">
            <h3 class="detail-title">{{ ws.state.detail.title }}</h3>
            <span
              class="fulltext-badge"
              :class="pdfUrl ? 'bound' : 'unbound'"
            >{{ fulltextLabel(ws.state.detail.fulltext_status) }}</span>
          </div>
          <div class="detail-info-row">
            <span class="info-chip"><i class="fas fa-user"></i>{{
              ws.state.detail.bibliography.authors?.join('，') || '作者未提供'
            }}</span><span class="info-chip"><i class="fas fa-calendar"></i>{{ ws.state.detail.publication_year || '年份未提供' }}</span><span class="info-chip"><i class="fas fa-book"></i>{{ ws.state.detail.bibliography.journal || '期刊未提供' }}</span><span v-if="ws.state.detail.doi" class="info-chip"><i class="fas fa-fingerprint"></i>{{ ws.state.detail.doi }}</span>
          </div>
        </div>
        <div class="abstract-box">
          <div class="abstract-box-header">
            <span class="section-label"><i class="fas fa-file-pdf"></i>PDF 全文</span>
            <div class="pdf-actions">
              <button :disabled="ws.state.working" @click="reload">
                <i class="fas fa-sync-alt"></i>刷新
              </button><a
                :href="`/workspace/${ws.state.projectId}?stage=SCREEN_2&rescreen_step=2`"
              >查看 / 更改全文</a><a v-if="pdfUrl" :href="pdfUrl" target="_blank" rel="noopener">新窗口打开</a>
            </div>
          </div>
          <div v-if="pdfUrl" class="abstract-box-body pdf-body">
            <RescreenPdf :url="ws.state.detail.pdf_url" :page="page" />
          </div>
          <div v-else class="fulltext-empty">
            <i class="fas fa-file-pdf"></i><strong>尚无可读全文</strong><span>返回“全文查找绑定”上传或绑定
              PDF；确实无法获取时，可标记“全文未获取”。</span>
            <p v-if="ws.state.detail.bibliography.abstract">
              {{ ws.state.detail.bibliography.abstract }}
            </p>
          </div>
        </div>
        <div class="detail-ai">
          <div
            v-if="ws.state.detail.needs_reconfirmation"
            class="conflict-banner"
          >
            <i class="fas fa-exclamation-triangle"></i>输入、标准或 AI
            建议已更新，原决定保留，需要重新确认。
          </div>
          <div class="ai-result-row">
            <span class="badge ai" :class="ws.state.aiDetail?.consensus">AI：{{ decisionLabel(ws.state.aiDetail?.consensus) }}</span><button
              v-if="
                ['included', 'excluded'].includes(ws.state.aiDetail?.consensus)
              "
              class="adopt-btn"
              :disabled="blocked"
              @click="adopt"
            >
              采纳到表单
            </button>
          </div>
          <RescreenEvidence
            :detail="ws.state.aiDetail"
            compact
            @page="showEvidence"
          />
          <details @toggle="historyToggle">
            <summary>人工审核历史</summary>
            <article
              v-for="event in ws.state.history.items"
              :key="event.id"
              class="rs-inset"
            >
              <strong>{{ decisionLabel(event.payload.decision) }} ·
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
        </div>
        <div class="detail-action">
          <div class="action-row">
            <div class="action-btns">
              <button
                v-for="choice in decisions"
                :key="choice.value"
                class="action-btn"
                :class="[choice.value, { active: decision === choice.value }]"
                :disabled="
                  blocked ||
                    (choice.value === 'not_retrieved' &&
                      !!ws.state.detail.asset_id &&
                      !['failed', 'rejected'].includes(
                        ws.state.detail.fulltext_status,
                      ))
                "
                @click="chooseDecision(choice.value)"
              >
                <i :class="choice.icon"></i>{{ choice.text }}
              </button>
            </div>
            <button
              class="save-decision"
              :disabled="
                blocked ||
                  !decision ||
                  (decision === 'excluded' && !reason.trim())
              "
              @click="save"
            >
              保存人工决定
            </button>
          </div>
          <div class="note-wrap">
            <label class="reason-wrap-label" for="rescreen-review-note"><i class="fas fa-sticky-note"></i>备注（可选）<small
              v-if="dirty"
              class="rs-warning"
            >
              · 有未保存的修改</small></label>
            <div class="note-input-row">
              <textarea
                id="rescreen-review-note"
                v-model="note"
                maxlength="4000"
                rows="1"
                placeholder="添加人工备注…"
                :disabled="blocked"
              /><button
                class="note-save-btn"
                aria-label="保存备注"
                :disabled="
                  blocked ||
                    !decision ||
                    (decision === 'excluded' && !reason.trim())
                "
                @click="save"
              >
                <i class="fas fa-save"></i>
              </button>
            </div>
            <small v-if="ws.state.info.busy" class="rs-warning">后台任务处理期间暂不能修改审核。</small>
          </div>
        </div>
        <transition name="reason-panel-slide">
          <div
            v-if="reasonPanelOpen"
            class="reason-side-panel"
            role="dialog"
            aria-label="排除理由"
            @keydown.esc="reasonPanelOpen = false"
          >
            <div class="reason-panel-header">
              <span><i class="fas fa-ban"></i>排除理由</span><button
                class="reason-panel-close"
                aria-label="关闭排除理由"
                @click="reasonPanelOpen = false"
              >
                <i class="fas fa-times"></i>
              </button>
            </div>
            <div class="reason-panel-body">
              <div class="reason-criteria-list">
                <div class="reason-criteria-label">快速选择排除标准：</div>
                <button
                  v-for="(criterion, index) in ws.state.info.configuration
                    .criteria"
                  :key="criterion.id"
                  class="reason-criteria-item"
                  :class="{ active: reason === criterion.text }"
                  @click="reason = criterion.text"
                >
                  <span class="rci-num">{{ index + 1 }}</span><span class="rci-text">{{ criterion.text }}</span>
                </button>
              </div>
              <div class="reason-panel-divider">或自定义理由</div>
              <textarea
                v-model="reason"
                class="reason-textarea"
                rows="4"
                maxlength="2000"
                placeholder="输入自定义排除理由…"
                :disabled="blocked"
              />
              <div class="reason-panel-actions">
                <button
                  class="reason-cancel-btn"
                  @click="reasonPanelOpen = false"
                >
                  返回
                </button><button
                  class="reason-confirm-btn"
                  :disabled="blocked || !reason.trim()"
                  @click="confirmExclude"
                >
                  <i class="fas fa-check"></i>确认排除
                </button>
              </div>
            </div>
          </div>
        </transition>
      </div>
      <div v-else class="detail-panel">
        <div class="detail-empty">
          <i class="fas fa-file-alt"></i><span>请选择一篇文献</span>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, inject, ref, watch, onBeforeUnmount, onMounted } from 'vue'
import { decisionLabel, fulltextLabel, safePdfUrl } from '../state'
import RescreenPagination from './RescreenPagination.vue'
import RescreenEvidence from './RescreenEvidence.vue'
import RescreenPdf from './RescreenPdf.vue'
const ws = inject('rescreen')
const query = ref(ws.state.filters.q)
const status = ref(ws.state.filters.status)
const page = ref(1)
const reasonPanelOpen = ref(false)
const blocked = computed(() => ws.state.working || ws.state.info.busy)
const decision = ref('')
const reason = ref('')
const note = ref('')
const original = ref('')
const decisions = [
  { value: 'included', text: '纳入', icon: 'fas fa-check' },
  { value: 'excluded', text: '排除', icon: 'fas fa-times' },
  { value: 'pending', text: '待定', icon: 'fas fa-question' },
  { value: 'not_retrieved', text: '全文未获取', icon: 'fas fa-file-excel' },
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
    reasonPanelOpen.value = false
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
async function search() {
  if (dirty.value && !window.confirm('当前修改尚未保存，确定切换列表？')) return
  ws.state.filters = { q: query.value, status: status.value }
  await loadList(1)
}
async function save() {
  const detail = ws.state.detail
  if (!detail || blocked.value) return null
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
  if (result && ws.state.step === 5 && ws.state.detail?.id === detail.id)
    ws.state.detail = result
  return result
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
}
function historyToggle(event) {
  if (event.target.open) ws.read(() => ws.loadHistory())
}

const tabs = [
  { key: '', label: '全部' },
  { key: 'unreviewed', label: '待审' },
  { key: 'conflict', label: '分歧' },
  { key: 'included', label: '纳入' },
  { key: 'excluded', label: '排除' },
  { key: 'pending', label: '待定' },
]
function tabCount(key) {
  const counts = ws.state.info.counts
  return (
    {
      '': counts.total,
      unreviewed: counts.remaining,
      conflict: counts.conflict,
      included: counts.included,
      excluded: counts.excluded,
      pending: counts.pending,
    }[key] ?? '—'
  )
}
async function switchTab(value) {
  if (dirty.value && !window.confirm('当前修改尚未保存，确定切换列表？')) return
  status.value = value
  ws.state.filters = { q: query.value, status: value }
  await loadList(1)
}
async function changePage(p, s) {
  if (dirty.value && !window.confirm('当前修改尚未保存，确定切换页码？')) return
  await loadList(p, s)
}
async function loadList(p, s) {
  const projectId = ws.state.projectId
  const result = await ws.read(() => ws.loadReferences(p, s))
  if (!result || ws.state.step !== 5 || ws.state.projectId !== projectId) return
  if (result.items.length) await ws.read(() => ws.selectReference(result.items[0].id))
  else {
    ws.clearReference()
  }
}
async function chooseDecision(value) {
  if (blocked.value) return
  decision.value = value
  if (value === 'excluded') {
    reasonPanelOpen.value = true
    return
  }
  await save()
}
async function confirmExclude() {
  const result = await save()
  if (result) reasonPanelOpen.value = false
}
onMounted(() => {
  if (!ws.state.detail && ws.state.refs.items.length)
    ws.read(() => ws.selectReference(ws.state.refs.items[0].id))
})
watch(() => ws.state.refs, (value) => {
  if (ws.state.step === 5 && !ws.state.detail && value.items.length)
    ws.read(() => ws.selectReference(value.items[0].id))
})
</script>
<style scoped>
.step-review {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  font-size: 0.88rem;
  overflow: hidden;
}
.review-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
}
.list-panel {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e2e8f0;
  background: #fff;
  overflow: hidden;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.search-box i {
  color: #94a3b8;
  font-size: 0.8rem;
}
.search-box input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 0.83rem;
  color: #334155;
  background: transparent;
}
.tab-bar {
  display: flex;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  flex-shrink: 0;
}
.tab-btn {
  flex: 1;
  padding: 0.5rem 0.2rem 0.4rem;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.05rem;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.tab-btn.active {
  background: #fff;
  border-bottom-color: #6366f1;
}
.tab-label {
  font-size: 0.75rem;
  color: #64748b;
  white-space: nowrap;
}
.tab-btn.active .tab-label {
  color: #6366f1;
  font-weight: 600;
}
.tab-count-num {
  font-size: 0.78rem;
  font-weight: 700;
  color: #334155;
}
.tab-btn.active .tab-count-num {
  color: #6366f1;
}
.ref-list {
  flex: 1;
  overflow-y: auto;
}
.ref-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.6rem 0.75rem;
  cursor: pointer;
  border-bottom: 1px solid #f1f5f9;
  transition: background 0.12s;
  position: relative;
}
.ref-item:hover {
  background: #f8fafc;
}
.ref-item.selected {
  background: #eef2ff;
  border-left: 3px solid #6366f1;
}
.ref-item.override::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 0;
  height: 0;
  border-top: 8px solid #a855f7;
  border-left: 8px solid transparent;
}
.ref-num {
  font-size: 0.7rem;
  color: #cbd5e1;
  min-width: 18px;
  padding-top: 3px;
  text-align: right;
  flex-shrink: 0;
}
.ref-main {
  flex: 1;
  min-width: 0;
}
.ref-title {
  font-size: 0.82rem;
  color: #1e293b;
  line-height: 1.38;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  word-break: break-word;
  margin-bottom: 0.18rem;
}
.ref-sub {
  display: flex;
  gap: 0.4rem;
  align-items: center;
  flex-wrap: wrap;
}
.ref-sub span {
  font-size: 0.71rem;
  color: #94a3b8;
}
.ref-journal {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}
.ref-status {
  flex-shrink: 0;
  padding-top: 2px;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.13rem 0.4rem;
  border-radius: 9px;
  font-size: 0.7rem;
  font-weight: 600;
}
.badge.human.included,
.badge.ai.included {
  background: #dcfce7;
  color: #16a34a;
}
.badge.human.excluded,
.badge.ai.excluded {
  background: #fee2e2;
  color: #dc2626;
}
.badge.human.pending,
.badge.pending,
.badge.ai.pending {
  background: #fef9c3;
  color: #ca8a04;
}
.badge.conflict {
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
}
.badge.ai {
  background: #f1f5f9;
  color: #64748b;
}
.list-empty {
  text-align: center;
  padding: 1.2rem;
  color: #94a3b8;
  font-size: 0.8rem;
}
.review-list-footer {
  flex-shrink: 0;
  border-top: 1px solid #e2e8f0;
  padding: 0.65rem 0.75rem;
  background: #fff;
}
.review-list-footer p {
  margin: 0.4rem 0 0;
  font-size: 0.7rem;
  line-height: 1.4;
  color: #94a3b8;
}
.batch-include-btn {
  width: 100%;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  padding: 0.48rem 0.65rem;
  font-size: 0.78rem;
  font-weight: 700;
  cursor: pointer;
}
.detail-panel {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  min-width: 0;
}
.detail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #cbd5e1;
  gap: 0.8rem;
  font-size: 0.9rem;
}
.detail-empty i {
  font-size: 2.5rem;
}
.detail-meta {
  flex-shrink: 0;
  padding: 0.8rem 1.1rem 0.5rem;
}
.title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.8rem;
  margin-bottom: 0.45rem;
}
.detail-title {
  margin: 0;
  font-size: 1rem;
  color: #1e293b;
  line-height: 1.35;
}
.detail-info-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.info-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  font-size: 0.73rem;
  color: #64748b;
  background: #f8fafc;
  border-radius: 5px;
  padding: 0.15rem 0.4rem;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fulltext-badge {
  flex-shrink: 0;
  display: inline-flex;
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.72rem;
  font-weight: 700;
}
.fulltext-badge.bound {
  background: #dcfce7;
  color: #16a34a;
}
.fulltext-badge.unbound {
  background: #f1f5f9;
  color: #64748b;
}
.fulltext-badge.bind_failed {
  background: #fee2e2;
  color: #dc2626;
}
.section-label {
  font-size: 0.73rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.abstract-box {
  flex: 1;
  min-height: 0;
  margin: 0 1.1rem 0.6rem;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.abstract-box-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.38rem 0.65rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  gap: 0.6rem;
}
.abstract-box-body {
  flex: 1;
  overflow: hidden;
  padding: 0.6rem 0.65rem;
}
.pdf-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.pdf-actions button,
.upload-inline {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  color: #6366f1;
  padding: 0.28rem 0.5rem;
  font-size: 0.72rem;
  cursor: pointer;
}
.pdf-body {
  background: #1e1e2e;
  padding: 0.75rem;
}
.fulltext-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  color: #94a3b8;
  text-align: center;
  padding: 1rem;
  overflow: auto;
  background: #f8fafc;
}
.fulltext-empty i {
  font-size: 2rem;
}
.fulltext-empty strong {
  color: #64748b;
}
.fulltext-empty span {
  max-width: 420px;
  font-size: 0.8rem;
  line-height: 1.5;
}
.detail-ai {
  flex-shrink: 0;
  max-height: 245px;
  overflow-y: auto;
  padding: 0 1.1rem 0.5rem;
}
.conflict-banner {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  padding: 0.5rem 0.65rem;
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  font-size: 0.78rem;
  margin-bottom: 0.55rem;
}
.ai-result-row {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-bottom: 0.55rem;
}
.ai-reason {
  font-size: 0.78rem;
  color: #64748b;
  flex: 1;
  line-height: 1.5;
}
.evidence-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
}
.evidence-card {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 8px;
  padding: 0.55rem 0.65rem;
}
.evidence-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}
.evidence-head span {
  font-size: 0.72rem;
  font-weight: 700;
  color: #475569;
}
.evidence-head button {
  border: 0;
  background: #eef2ff;
  color: #4f46e5;
  border-radius: 999px;
  padding: 0.16rem 0.45rem;
  font-size: 0.7rem;
  cursor: pointer;
}
.evidence-card p {
  margin: 0;
  font-size: 0.77rem;
  line-height: 1.45;
  color: #475569;
}
.detail-action {
  flex-shrink: 0;
  padding: 0.65rem 1.1rem;
  border-top: 1px solid #e2e8f0;
  background: #fff;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.04);
}
.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  margin-bottom: 0.4rem;
}
.action-btns {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.action-btn {
  padding: 0.4rem 0.9rem;
  border-radius: 7px;
  border: 2px solid #e2e8f0;
  background: #fff;
  font-size: 0.82rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.32rem;
  transition: all 0.15s;
  color: #64748b;
}
.action-btn.included:hover,
.action-btn.included.active {
  background: #dcfce7;
  border-color: #16a34a;
  color: #16a34a;
}
.action-btn.excluded:hover,
.action-btn.excluded.active {
  background: #fee2e2;
  border-color: #dc2626;
  color: #dc2626;
}
.action-btn.pending:hover,
.action-btn.pending.active {
  background: #fef9c3;
  border-color: #ca8a04;
  color: #ca8a04;
}
.save-status {
  font-size: 0.73rem;
  white-space: nowrap;
}
.save-status.success {
  color: #16a34a;
}
.reason-wrap-label {
  font-size: 0.74rem;
  color: #64748b;
  font-weight: 600;
  margin-bottom: 5px;
  display: flex;
  align-items: center;
}
.note-wrap {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
}
.note-input-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.note-input-row textarea {
  flex: 1;
  min-height: 34px;
  max-height: 68px;
  resize: vertical;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  padding: 0.42rem 0.55rem;
  font-size: 0.78rem;
}
.note-save-btn {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 7px;
  background: #eef2ff;
  color: #6366f1;
  cursor: pointer;
}
.note-save-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.reason-side-panel {
  position: absolute;
  top: 0;
  right: 0;
  width: 320px;
  max-width: 80%;
  height: 100%;
  background: #fff;
  border-left: 1px solid #e2e8f0;
  box-shadow: -8px 0 24px rgba(15, 23, 42, 0.12);
  z-index: 20;
  display: flex;
  flex-direction: column;
}
.reason-panel-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.8rem 0.9rem;
  border-bottom: 1px solid #e2e8f0;
  font-size: 0.88rem;
  font-weight: 700;
  color: #1e293b;
}
.reason-panel-close {
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
}
.reason-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.85rem;
}
.reason-criteria-label {
  font-size: 0.74rem;
  color: #64748b;
  font-weight: 700;
  margin-bottom: 0.45rem;
}
.reason-criteria-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.reason-criteria-item {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  width: 100%;
  border: 1px solid #e2e8f0;
  background: #fff;
  border-radius: 8px;
  padding: 0.45rem 0.5rem;
  cursor: pointer;
  text-align: left;
  color: #475569;
}
.reason-criteria-item.active {
  border-color: #ef4444;
  background: #fef2f2;
  color: #b91c1c;
}
.rci-num {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.68rem;
  font-weight: 700;
}
.rci-text {
  font-size: 0.76rem;
  line-height: 1.35;
}
.reason-panel-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0.8rem 0;
  color: #94a3b8;
  font-size: 0.72rem;
}
.reason-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.55rem;
  font-size: 0.8rem;
  resize: vertical;
}
.reason-panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.reason-cancel-btn,
.reason-confirm-btn {
  border: 0;
  border-radius: 8px;
  padding: 0.48rem 0.75rem;
  font-weight: 700;
  cursor: pointer;
}
.reason-cancel-btn {
  background: #f8fafc;
  color: #64748b;
}
.reason-confirm-btn {
  background: #ef4444;
  color: #fff;
}
.reason-confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.reason-panel-slide-enter-active,
.reason-panel-slide-leave-active {
  transition:
    transform 0.18s ease,
    opacity 0.18s ease;
}
.reason-panel-slide-enter-from,
.reason-panel-slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}
@media (max-width: 1100px) {
  .list-panel {
    width: 280px;
  }
  .evidence-list {
    grid-template-columns: 1fr;
  }
}

.step-review {
  min-height: 540px;
  height: 100%;
}
.review-body {
  min-height: 0;
}
.list-panel .ref-item {
  width: 100%;
  text-align: left;
  border: 0;
  border-radius: 0;
  border-bottom: 1px solid #f1f5f9;
  background: white;
  font: inherit;
}
.list-panel .ref-item.selected {
  border-left: 3px solid #6366f1;
  background: #eef2ff;
}
.ref-title,
.ref-sub {
  display: flex;
}
.ref-title {
  display: -webkit-box;
}
.search-box input {
  min-width: 0;
}
.search-box button {
  padding: 3px;
  border: 0;
  background: none;
  color: #94a3b8;
}
.ref-status {
  max-width: 70px;
}
.review-list-footer :deep(.rs-pagination) {
  padding: 0;
  justify-content: center;
  gap: 5px;
}
.review-list-footer :deep(.rs-pagination > span) {
  width: 100%;
  text-align: center;
}
.detail-title {
  overflow-wrap: anywhere;
}
.abstract-box {
  min-height: 140px;
}
.abstract-box-body {
  padding: 0;
}
.pdf-body :deep(.rs-pdf-viewer),
.pdf-body :deep(iframe) {
  height: 100%;
  min-height: 140px;
  width: 100%;
  border: 0;
}
.detail-ai :deep(.rs-model-result) {
  margin-top: 8px;
  padding-top: 8px;
}
.detail-ai :deep(.rs-model-result p) {
  margin: 6px 0;
  font-size: 0.78rem;
}
.detail-ai :deep(.rs-model-result:first-child) {
  border-top: 0;
}
.pdf-actions a {
  font-size: 0.72rem;
  text-decoration: none;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0.28rem 0.5rem;
}
.save-decision,
.adopt-btn {
  border: 1px solid #c7d2fe;
  border-radius: 7px;
  background: #eef2ff;
  color: #4f46e5;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 0.75rem;
}
.action-btn.not_retrieved.active {
  background: #f1f5f9;
  border-color: #94a3b8;
}
.reason-wrap-label {
  gap: 6px;
}
.detail-ai {
  flex: 0 1 160px;
  min-height: 60px;
  max-height: 200px;
}
.list-panel .search-box input {
  border: 0;
  border-radius: 0;
  padding: 0;
  background: transparent;
}
.reconfirm-btn {
  margin-top: 8px;
  width: 100%;
  font-size: 0.72rem;
  color: #b45309;
}
.badge.not_retrieved {
  background: #f1f5f9;
  color: #64748b;
}
@media (max-width: 900px) {
  .step-review {
    overflow: auto;
    height: auto;
    min-height: 0;
  }
  .review-body {
    flex-direction: column;
    overflow: visible;
  }
  .list-panel {
    width: 100%;
    max-height: 360px;
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }
  .detail-panel {
    overflow: visible;
  }
  .abstract-box {
    flex: none;
    height: 420px;
  }
  .detail-ai {
    max-height: 320px;
  }
  .detail-action {
    position: sticky;
    bottom: 0;
  }
  .reason-side-panel {
    position: fixed;
    top: auto;
    bottom: 0;
    width: 360px;
    height: 80vh;
  }
  .tab-label {
    font-size: 0.72rem;
  }
}
</style>
