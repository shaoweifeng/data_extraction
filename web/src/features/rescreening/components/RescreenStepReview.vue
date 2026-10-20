<template>
  <div class="step-review rescreen-review">
    <input ref="uploadInput" type="file" accept=".pdf" style="display:none" @change="onUploadSelected" />
    <div class="review-body">
      <!-- 左栏：直接复用初筛人工审阅的信息架构 -->
      <div class="list-panel">
        <div class="search-box">
          <i class="fas fa-search"></i>
          <input v-model="searchQ" placeholder="搜索标题…" />
        </div>

        <div class="tab-bar">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: rescreen.reviewTab === tab.key }"
            @click="switchTab(tab.key)"
          >
            <div class="tab-label">{{ tab.label }}</div>
            <div class="tab-count-num">{{ tabCount(tab.key) }}</div>
          </button>
        </div>

        <div class="ref-list">
          <div
            v-for="(paper, index) in displayItems"
            :key="paper.id"
            class="ref-item"
            :class="{ selected: selected?.id === paper.id, override: Boolean(paper.human_decision) }"
            @click="selectItem(paper)"
          >
            <div class="ref-num">{{ index + 1 }}</div>
            <div class="ref-main">
              <div class="ref-title">{{ paper.title }}</div>
              <div class="ref-sub">
                <span>{{ paper.year || '未知年份' }}</span>
                <span class="ref-journal">{{ paper.journal || '未知期刊' }}</span>
              </div>
            </div>
            <div class="ref-status">
              <span v-if="paper.human_decision" class="badge human" :class="paper.human_decision">
                <i class="fas fa-check"></i>{{ decisionLabel(paper.human_decision) }}
              </span>
              <span v-else-if="paper.consensus_status === 'divergent' || paper.ai_decision === 'pending'" class="badge conflict">
                <i class="fas fa-exclamation-triangle"></i> 分歧
              </span>
              <span v-else-if="paper.ai_decision" class="badge ai" :class="paper.ai_decision">
                AI · {{ decisionLabel(paper.ai_decision) }}
              </span>
              <span v-else class="badge pending">待审</span>
            </div>
          </div>
          <div v-if="displayItems.length === 0" class="list-empty">暂无文献</div>
        </div>

        <div class="review-list-footer">
          <button class="batch-include-btn" @click="batchIncludeConsistent">
            <i class="fas fa-check-double"></i> 一键纳入 AI 一致文献
          </button>
          <p>仅对 AI 一致纳入文献批量写入人工确认；分歧/待定/无全文仍需逐篇 check。</p>
        </div>
      </div>

      <!-- 右侧：沿用初筛详情面板；摘要区替换为 PDF 全文 -->
      <div v-if="selected" class="detail-panel">
        <div class="detail-meta">
          <div class="title-row">
            <h3 class="detail-title">{{ selected.title }}</h3>
            <span :class="['fulltext-badge', selected.fulltext_status]">{{ fulltextLabel(selected.fulltext_status) }}</span>
          </div>
          <div class="detail-info-row">
            <span class="info-chip"><i class="fas fa-user"></i>{{ selected.authors.join(', ') }}</span>
            <span class="info-chip"><i class="fas fa-calendar"></i>{{ selected.year || '—' }}</span>
            <span class="info-chip"><i class="fas fa-book"></i>{{ selected.journal || '—' }}</span>
            <span class="info-chip"><i class="fas fa-fingerprint"></i>{{ selected.doi || selected.pmid || '—' }}</span>
          </div>
        </div>

        <div class="abstract-box fulltext-box">
          <div class="abstract-box-header">
            <span class="section-label"><i class="fas fa-file-pdf"></i> PDF 全文</span>
            <div v-if="selected.fulltext_status === 'bound'" class="pdf-actions">
              <button @click="triggerUpload(selected.id)"><i class="fas fa-rotate"></i> 更改</button>
              <button @click="openPdf(selected)"><i class="fas fa-up-right-from-square"></i> 新窗口打开</button>
            </div>
            <button v-else class="upload-inline" @click="triggerUpload(selected.id)">
              <i class="fas fa-upload"></i> 上传全文
            </button>
          </div>
          <div class="abstract-box-body pdf-body">
            <template v-if="selected.fulltext_status === 'bound'">
              <QAPdfViewer
                :pdf-url="selected.fulltext_url"
                :filename="selected.fulltext_filename || 'document.pdf'"
                :page="currentPdfPage"
              />
            </template>
            <div v-else class="fulltext-empty">
              <i class="fas fa-file-circle-exclamation"></i>
              <strong>{{ fulltextLabel(selected.fulltext_status) }}</strong>
              <span>{{ selected.fulltext_error || '该文献暂无可用全文；可以先上传 PDF，或人工标记待定/排除并说明原因。' }}</span>
            </div>
          </div>
        </div>

        <div class="detail-ai">
          <div v-if="isConflict(selected)" class="conflict-banner">
            <i class="fas fa-exclamation-triangle"></i>
            <span><b>需要人工裁定</b> — 多模型分歧、证据不足或 AI 输出待定</span>
          </div>

          <div class="ai-result-row">
            <span class="badge ai" :class="selected.ai_decision || selected.ai_status">
              AI: {{ aiLabel(selected) }}
            </span>
            <span class="ai-reason">{{ selected.ai_reason || '该文献暂无 AI 复筛结果。' }}</span>
          </div>

          <div v-if="selected.ai_evidence?.length" class="evidence-list">
            <div v-for="item in selected.ai_evidence" :key="`${selected.id}-${item.page}-${item.text}`" class="evidence-card">
              <div class="evidence-head">
                <span><i class="fas fa-quote-left"></i> AI 证据</span>
                <button @click="jumpToEvidence(item.page)">第 {{ item.page }} 页</button>
              </div>
              <p>{{ item.text }}</p>
            </div>
          </div>
        </div>

        <div class="detail-action">
          <div class="action-row">
            <div class="action-btns">
              <button
                v-for="option in decisionOptions"
                :key="option.value"
                class="action-btn"
                :class="[option.value, { active: selected.human_decision === option.value }]"
                @click="setDecision(option.value)"
              >
                <i :class="option.icon"></i>{{ option.label }}
              </button>
            </div>
            <div v-if="saveStatus" class="save-status success">{{ saveStatus }}</div>
          </div>

          <div class="note-wrap">
            <div class="reason-wrap-label">
              <i class="fas fa-sticky-note mr-1 text-gray-400"></i>备注
              <span class="text-xs text-gray-400 ml-1">（可选）</span>
            </div>
            <div class="note-input-row">
              <textarea v-model="localNote" placeholder="添加人工备注…" rows="1" />
              <button class="note-save-btn" :disabled="!localNote.trim()" @click="saveNote">
                <i class="fas fa-save"></i>
              </button>
            </div>
          </div>
        </div>

        <transition name="reason-panel-slide">
          <div v-if="reasonPanelOpen" class="reason-side-panel" @keydown.esc="closeReasonPanel">
            <div class="reason-panel-header">
              <span><i class="fas fa-ban mr-1.5 text-red-400"></i>排除理由</span>
              <button class="reason-panel-close" title="取消排除" @click="closeReasonPanel">
                <i class="fas fa-times"></i>
              </button>
            </div>
            <div class="reason-panel-body">
              <div v-if="rescreen.criteriaList.length" class="reason-criteria-list">
                <div class="reason-criteria-label">快速选择复筛标准/排除理由：</div>
                <button
                  v-for="(item, index) in rescreen.criteriaList"
                  :key="item"
                  class="reason-criteria-item"
                  :class="{ active: localReason === item }"
                  :title="item"
                  @click="localReason = item"
                >
                  <span class="rci-num">{{ index + 1 }}</span>
                  <span class="rci-text">{{ item }}</span>
                </button>
              </div>
              <div class="reason-panel-divider"><span>或自定义理由</span></div>
              <textarea v-model="localReason" class="reason-textarea" placeholder="输入自定义排除理由…" rows="4" />
              <div class="reason-panel-actions">
                <button class="reason-cancel-btn" @click="closeReasonPanel">取消</button>
                <button class="reason-confirm-btn" :disabled="!localReason.trim()" @click="confirmExclude">
                  <i class="fas fa-check"></i>确认排除 → 下一篇
                </button>
              </div>
            </div>
          </div>
        </transition>
      </div>

      <div v-else class="detail-panel">
        <div class="detail-empty">
          <i class="fas fa-file-alt"></i>
          <span>请选择一篇文献</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import QAPdfViewer from '@/features/quality/components/QAPdfViewer.vue'
import { useProjectStore } from '@/features/projects/store'
import { useRescreenStore } from '@/features/rescreening/store'

const project = useProjectStore()
const rescreen = useRescreenStore()
const searchQ = ref('')
const localReason = ref('')
const localNote = ref('')
const reasonPanelOpen = ref(false)
const saveStatus = ref('')
const uploadInput = ref(null)
const pendingRefId = ref(null)
const currentPdfPage = ref('')

const tabs = [
  { key: '', label: '全部' },
  { key: 'unreviewed', label: '待审' },
  { key: 'conflict', label: '⚠️ 分歧' },
  { key: 'included', label: '纳入' },
  { key: 'excluded', label: '排除' },
  { key: 'pending', label: '待定' },
]

const decisionOptions = [
  { value: 'included', label: '纳入', icon: 'fas fa-check' },
  { value: 'pending', label: '待定', icon: 'fas fa-question' },
  { value: 'excluded', label: '排除', icon: 'fas fa-times' },
]

const selected = computed(() => rescreen.activeRef)
const displayItems = computed(() => {
  const query = searchQ.value.trim().toLowerCase()
  const list = rescreen.reviewFilteredRefs
  if (!query) return list
  return list.filter(item => [item.title, item.first_author, item.journal, item.doi, item.pmid]
    .filter(Boolean)
    .some(value => String(value).toLowerCase().includes(query)))
})

watch(() => selected.value?.id, () => {
  localReason.value = selected.value?.exclusion_reason || ''
  localNote.value = ''
  reasonPanelOpen.value = false
  saveStatus.value = ''
  currentPdfPage.value = ''
})

function switchTab(key) {
  rescreen.reviewTab = key
  const first = rescreen.reviewFilteredRefs[0]
  if (first) rescreen.activeRefId = first.id
}
function tabCount(key) {
  if (key === '') return rescreen.totalRefs
  if (key === 'unreviewed') return rescreen.unreviewedRefs.length
  if (key === 'conflict') return rescreen.conflictRefs.length
  if (key === 'included') return rescreen.includedRefs.length
  if (key === 'excluded') return rescreen.excludedRefs.length
  if (key === 'pending') return rescreen.pendingRefs.length
  return 0
}
function selectItem(item) { rescreen.activeRefId = item.id }
function decisionLabel(value) { return { included: '纳入', excluded: '排除', pending: '待定' }[value] || value || '—' }
function fulltextLabel(value) { return { bound: '已绑定', unbound: '未绑定', bind_failed: '绑定失败' }[value] || value }
function aiLabel(item) {
  if (item.ai_status === 'skipped_unbound') return '跳过'
  return { included: '建议纳入', excluded: '建议排除', pending: '待定' }[item.ai_decision] || '未开始'
}
function isConflict(item) { return item.consensus_status === 'divergent' || item.ai_decision === 'pending' }
async function setDecision(value) {
  if (!selected.value) return
  if (value === 'excluded') {
    reasonPanelOpen.value = true
    return
  }
  try {
    await rescreen.saveHumanDecisionRemote(project.currentProject?.id, selected.value.id, value, '', localNote.value.trim())
    flashSaved(value === 'included' ? '已保存：人工纳入' : '已保存：人工待定')
  } catch (error) {
    console.warn('[Rescreen] save decision failed', error)
    flashSaved(rescreen.lastError || '保存失败')
  }
}
async function confirmExclude() {
  if (!selected.value || !localReason.value.trim()) return
  try {
    await rescreen.saveHumanDecisionRemote(project.currentProject?.id, selected.value.id, 'excluded', localReason.value.trim(), localNote.value.trim())
    reasonPanelOpen.value = false
    flashSaved('已保存：人工排除')
  } catch (error) {
    console.warn('[Rescreen] save exclusion failed', error)
    flashSaved(rescreen.lastError || '保存失败')
  }
}
function closeReasonPanel() { reasonPanelOpen.value = false }
async function saveNote() {
  if (!selected.value) return
  try {
    await rescreen.saveHumanDecisionRemote(
      project.currentProject?.id,
      selected.value.id,
      selected.value.human_decision || 'pending',
      selected.value.exclusion_reason || '',
      localNote.value.trim(),
    )
    flashSaved('备注已保存')
    localNote.value = ''
  } catch (error) {
    console.warn('[Rescreen] save note failed', error)
    flashSaved(rescreen.lastError || '备注保存失败')
  }
}
function batchIncludeConsistent() {
  rescreen.batchIncludeConsistent(project.currentProject?.id)
}
function jumpToEvidence(page) {
  currentPdfPage.value = page || ''
  flashSaved(page ? `已定位到第 ${page} 页` : '该证据未返回页码')
}

function triggerUpload(refId) {
  pendingRefId.value = refId
  uploadInput.value?.click()
}
async function onUploadSelected(event) {
  const file = event.target.files?.[0]
  if (file && pendingRefId.value) {
    try {
      await rescreen.replaceFulltextFile(project.currentProject?.id, pendingRefId.value, file)
      flashSaved('全文已更新')
    } catch (error) {
      console.warn('[Rescreen] replace fulltext failed', error)
      flashSaved(rescreen.lastError || '全文上传失败')
    }
  }
  event.target.value = ''
  pendingRefId.value = null
}
function openPdf(ref) {
  if (ref?.fulltext_url) window.open(ref.fulltext_url, '_blank', 'noopener,noreferrer')
}
function flashSaved(message) {
  saveStatus.value = message
  window.setTimeout(() => { saveStatus.value = '' }, 1400)
}
</script>

<style scoped>
.step-review { display:flex; flex-direction:column; flex:1; min-height:0; font-size:.88rem; overflow:hidden; }
.review-body { display:flex; flex:1; overflow:hidden; background:#fff; border:1px solid #e2e8f0; border-radius:14px; }
.list-panel { width:300px; flex-shrink:0; display:flex; flex-direction:column; border-right:1px solid #e2e8f0; background:#fff; overflow:hidden; }
.search-box { display:flex; align-items:center; gap:.45rem; padding:.55rem .75rem; border-bottom:1px solid #f1f5f9; flex-shrink:0; }
.search-box i { color:#94a3b8; font-size:.8rem; }
.search-box input { flex:1; border:none; outline:none; font-size:.83rem; color:#334155; background:transparent; }
.tab-bar { display:flex; border-bottom:1px solid #e2e8f0; background:#f8fafc; flex-shrink:0; }
.tab-btn { flex:1; padding:.5rem .2rem .4rem; border:none; background:transparent; cursor:pointer; display:flex; flex-direction:column; align-items:center; gap:.05rem; border-bottom:2px solid transparent; transition:all .15s; }
.tab-btn.active { background:#fff; border-bottom-color:#6366f1; }
.tab-label { font-size:.75rem; color:#64748b; white-space:nowrap; }
.tab-btn.active .tab-label { color:#6366f1; font-weight:600; }
.tab-count-num { font-size:.78rem; font-weight:700; color:#334155; }
.tab-btn.active .tab-count-num { color:#6366f1; }
.ref-list { flex:1; overflow-y:auto; }
.ref-item { display:flex; align-items:flex-start; gap:.5rem; padding:.6rem .75rem; cursor:pointer; border-bottom:1px solid #f1f5f9; transition:background .12s; position:relative; }
.ref-item:hover { background:#f8fafc; }
.ref-item.selected { background:#eef2ff; border-left:3px solid #6366f1; }
.ref-item.override::after { content:''; position:absolute; top:0; right:0; width:0; height:0; border-top:8px solid #a855f7; border-left:8px solid transparent; }
.ref-num { font-size:.7rem; color:#cbd5e1; min-width:18px; padding-top:3px; text-align:right; flex-shrink:0; }
.ref-main { flex:1; min-width:0; }
.ref-title { font-size:.82rem; color:#1e293b; line-height:1.38; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; word-break:break-word; margin-bottom:.18rem; }
.ref-sub { display:flex; gap:.4rem; align-items:center; flex-wrap:wrap; }
.ref-sub span { font-size:.71rem; color:#94a3b8; }
.ref-journal { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:120px; }
.ref-status { flex-shrink:0; padding-top:2px; }
.badge { display:inline-flex; align-items:center; gap:.2rem; padding:.13rem .4rem; border-radius:9px; font-size:.7rem; font-weight:600; }
.badge.human.included,.badge.ai.included { background:#dcfce7; color:#16a34a; }
.badge.human.excluded,.badge.ai.excluded { background:#fee2e2; color:#dc2626; }
.badge.human.pending,.badge.pending,.badge.ai.pending { background:#fef9c3; color:#ca8a04; }
.badge.conflict { background:#fff7ed; color:#c2410c; border:1px solid #fed7aa; }
.badge.ai { background:#f1f5f9; color:#64748b; }
.list-empty { text-align:center; padding:1.2rem; color:#94a3b8; font-size:.8rem; }
.review-list-footer { flex-shrink:0; border-top:1px solid #e2e8f0; padding:.65rem .75rem; background:#fff; }
.review-list-footer p { margin:.4rem 0 0; font-size:.7rem; line-height:1.4; color:#94a3b8; }
.batch-include-btn { width:100%; border:0; border-radius:8px; background:linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff; padding:.48rem .65rem; font-size:.78rem; font-weight:700; cursor:pointer; }
.detail-panel { position:relative; flex:1; display:flex; flex-direction:column; overflow:hidden; background:#fff; min-width:0; }
.detail-empty { display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; color:#cbd5e1; gap:.8rem; font-size:.9rem; }
.detail-empty i { font-size:2.5rem; }
.detail-meta { flex-shrink:0; padding:.8rem 1.1rem .5rem; }
.title-row { display:flex; align-items:flex-start; justify-content:space-between; gap:.8rem; margin-bottom:.45rem; }
.detail-title { margin:0; font-size:1rem; color:#1e293b; line-height:1.35; }
.detail-info-row { display:flex; flex-wrap:wrap; gap:.35rem; }
.info-chip { display:inline-flex; align-items:center; gap:.28rem; font-size:.73rem; color:#64748b; background:#f8fafc; border-radius:5px; padding:.15rem .4rem; max-width:360px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.fulltext-badge { flex-shrink:0; display:inline-flex; border-radius:999px; padding:.2rem .55rem; font-size:.72rem; font-weight:700; }
.fulltext-badge.bound { background:#dcfce7; color:#16a34a; }
.fulltext-badge.unbound { background:#f1f5f9; color:#64748b; }
.fulltext-badge.bind_failed { background:#fee2e2; color:#dc2626; }
.section-label { font-size:.73rem; font-weight:600; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; display:flex; align-items:center; gap:.35rem; }
.abstract-box { flex:1; min-height:0; margin:0 1.1rem .6rem; border-radius:8px; border:1px solid #e2e8f0; display:flex; flex-direction:column; overflow:hidden; }
.abstract-box-header { flex-shrink:0; display:flex; align-items:center; justify-content:space-between; padding:.38rem .65rem; background:#f8fafc; border-bottom:1px solid #e2e8f0; gap:.6rem; }
.abstract-box-body { flex:1; overflow:hidden; padding:.6rem .65rem; }
.pdf-actions { display:flex; align-items:center; gap:.4rem; }
.pdf-actions button,.upload-inline { border:1px solid #e2e8f0; border-radius:6px; background:#fff; color:#6366f1; padding:.28rem .5rem; font-size:.72rem; cursor:pointer; }
.pdf-body { background:#1e1e2e; padding:.75rem; }
.fulltext-empty { height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:.45rem; color:#94a3b8; text-align:center; padding:2rem; background:#f8fafc; }
.fulltext-empty i { font-size:2rem; }
.fulltext-empty strong { color:#64748b; }
.fulltext-empty span { max-width:420px; font-size:.8rem; line-height:1.5; }
.detail-ai { flex-shrink:0; max-height:245px; overflow-y:auto; padding:0 1.1rem .5rem; }
.conflict-banner { display:flex; gap:.5rem; align-items:center; padding:.5rem .65rem; background:#fff7ed; color:#c2410c; border:1px solid #fed7aa; border-radius:8px; font-size:.78rem; margin-bottom:.55rem; }
.ai-result-row { display:flex; align-items:flex-start; gap:.6rem; flex-wrap:wrap; margin-bottom:.55rem; }
.ai-reason { font-size:.78rem; color:#64748b; flex:1; line-height:1.5; }
.evidence-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.5rem; }
.evidence-card { border:1px solid #e2e8f0; background:#f8fafc; border-radius:8px; padding:.55rem .65rem; }
.evidence-head { display:flex; align-items:center; justify-content:space-between; gap:.5rem; margin-bottom:.35rem; }
.evidence-head span { font-size:.72rem; font-weight:700; color:#475569; }
.evidence-head button { border:0; background:#eef2ff; color:#4f46e5; border-radius:999px; padding:.16rem .45rem; font-size:.7rem; cursor:pointer; }
.evidence-card p { margin:0; font-size:.77rem; line-height:1.45; color:#475569; }
.detail-action { flex-shrink:0; padding:.65rem 1.1rem; border-top:1px solid #e2e8f0; background:#fff; box-shadow:0 -2px 8px rgba(0,0,0,.04); }
.action-row { display:flex; align-items:center; justify-content:space-between; gap:.6rem; margin-bottom:.4rem; }
.action-btns { display:flex; gap:.5rem; flex-wrap:wrap; }
.action-btn { padding:.4rem .9rem; border-radius:7px; border:2px solid #e2e8f0; background:#fff; font-size:.82rem; cursor:pointer; display:flex; align-items:center; gap:.32rem; transition:all .15s; color:#64748b; }
.action-btn.included:hover,.action-btn.included.active { background:#dcfce7; border-color:#16a34a; color:#16a34a; }
.action-btn.excluded:hover,.action-btn.excluded.active { background:#fee2e2; border-color:#dc2626; color:#dc2626; }
.action-btn.pending:hover,.action-btn.pending.active { background:#fef9c3; border-color:#ca8a04; color:#ca8a04; }
.save-status { font-size:.73rem; white-space:nowrap; }
.save-status.success { color:#16a34a; }
.reason-wrap-label { font-size:.74rem; color:#64748b; font-weight:600; margin-bottom:5px; display:flex; align-items:center; }
.note-wrap { margin-top:8px; padding-top:8px; border-top:1px dashed #e2e8f0; }
.note-input-row { display:flex; align-items:flex-start; gap:6px; }
.note-input-row textarea { flex:1; min-height:34px; max-height:68px; resize:vertical; border:1px solid #e2e8f0; border-radius:7px; padding:.42rem .55rem; font-size:.78rem; }
.note-save-btn { width:34px; height:34px; border:none; border-radius:7px; background:#eef2ff; color:#6366f1; cursor:pointer; }
.note-save-btn:disabled { opacity:.45; cursor:not-allowed; }
.reason-side-panel { position:absolute; top:0; right:0; width:320px; max-width:80%; height:100%; background:#fff; border-left:1px solid #e2e8f0; box-shadow:-8px 0 24px rgba(15,23,42,.12); z-index:20; display:flex; flex-direction:column; }
.reason-panel-header { flex-shrink:0; display:flex; align-items:center; justify-content:space-between; padding:.8rem .9rem; border-bottom:1px solid #e2e8f0; font-size:.88rem; font-weight:700; color:#1e293b; }
.reason-panel-close { border:0; background:transparent; color:#94a3b8; cursor:pointer; }
.reason-panel-body { flex:1; overflow-y:auto; padding:.85rem; }
.reason-criteria-label { font-size:.74rem; color:#64748b; font-weight:700; margin-bottom:.45rem; }
.reason-criteria-list { display:flex; flex-direction:column; gap:.4rem; }
.reason-criteria-item { display:flex; align-items:flex-start; gap:.45rem; width:100%; border:1px solid #e2e8f0; background:#fff; border-radius:8px; padding:.45rem .5rem; cursor:pointer; text-align:left; color:#475569; }
.reason-criteria-item.active { border-color:#ef4444; background:#fef2f2; color:#b91c1c; }
.rci-num { flex-shrink:0; width:18px; height:18px; border-radius:50%; background:#f1f5f9; display:flex; align-items:center; justify-content:center; font-size:.68rem; font-weight:700; }
.rci-text { font-size:.76rem; line-height:1.35; }
.reason-panel-divider { display:flex; align-items:center; justify-content:center; margin:.8rem 0; color:#94a3b8; font-size:.72rem; }
.reason-textarea { width:100%; box-sizing:border-box; border:1px solid #e2e8f0; border-radius:8px; padding:.55rem; font-size:.8rem; resize:vertical; }
.reason-panel-actions { display:flex; justify-content:flex-end; gap:.5rem; margin-top:.75rem; }
.reason-cancel-btn,.reason-confirm-btn { border:0; border-radius:8px; padding:.48rem .75rem; font-weight:700; cursor:pointer; }
.reason-cancel-btn { background:#f8fafc; color:#64748b; }
.reason-confirm-btn { background:#ef4444; color:#fff; }
.reason-confirm-btn:disabled { opacity:.5; cursor:not-allowed; }
.reason-panel-slide-enter-active,.reason-panel-slide-leave-active { transition:transform .18s ease, opacity .18s ease; }
.reason-panel-slide-enter-from,.reason-panel-slide-leave-to { transform:translateX(100%); opacity:0; }
@media(max-width:1100px){.list-panel{width:280px}.evidence-list{grid-template-columns:1fr}}
</style>
