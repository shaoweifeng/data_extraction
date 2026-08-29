<template>
  <div class="qa-review">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#3b82f6,#6366f1)">
        <i class="fas fa-magnifying-glass-chart"></i>
      </div>
      <div>
        <h3 class="step-title">结果审核</h3>
        <p class="step-subtitle">逐篇审核 AI 评价结果，对每条信号问题进行人工确认</p>
      </div>
    </div>

    <!-- 主体：左侧文献列表 + 右侧内容 -->
    <div class="review-layout">
      <!-- 左侧文献列表 -->
      <div class="ref-panel">
        <div class="ref-panel-header">
          <span class="ref-count">{{ qa.refs.length }} 篇</span>
          <div class="filter-tabs">
            <button
              v-for="f in refFilters"
              :key="f.key"
              :class="['filter-btn', { active: refFilter === f.key }]"
              @click="refFilter = f.key"
            >{{ f.label }}</button>
          </div>
        </div>
        <div class="ref-list">
          <div
            v-for="ref in filteredRefList"
            :key="ref.id"
            :class="['ref-item', { active: qa.currentRef?.id === ref.id }, `eval-${ref.ai_eval_status}`]"
            @click="selectRef(ref)"
          >
            <div class="ref-item-title">{{ ref.title }}</div>
            <div class="ref-item-meta">
              <span class="ref-method-tag">{{ ref.quality_method }}</span>
              <span :class="['review-dot', reviewDotClass(ref.review_status)]" :title="reviewLabel(ref.review_status)"></span>
            </div>
          </div>
          <div v-if="!filteredRefList.length" class="ref-list-empty">暂无文献</div>
        </div>
      </div>

      <!-- 右侧内容区 -->
      <div class="review-main" v-if="qa.currentRef">
        <!-- 文献信息栏 -->
        <div class="ref-info-bar">
          <div class="ref-info-left">
            <p class="curr-ref-title">{{ qa.currentRef.title }}</p>
            <div class="curr-ref-meta">
              <span v-if="qa.currentRef.first_author" class="meta-item">{{ qa.currentRef.first_author }}</span>
              <span v-if="qa.currentRef.year" class="meta-item">{{ qa.currentRef.year }}</span>
              <span class="meta-item method-chip">{{ qa.currentRef.quality_method }}</span>
              <span :class="['meta-item', 'eval-status-chip', `chip-${qa.currentRef.ai_eval_status}`]">
                {{ evalStatusLabel(qa.currentRef.ai_eval_status) }}
              </span>
            </div>
          </div>
          <div class="ref-info-actions">
            <button
              class="btn-batch-confirm"
              @click="showBatchConfirmModal = true"
              :disabled="allConfirmed"
            >
              <i class="fas fa-check-double"></i>
              一键确认
            </button>
          </div>
        </div>

        <!-- 内容区：分栏 PDF 预览 + 信号问题 -->
        <div class="content-split" :class="{ 'has-pdf': showPdfPanel }">
          <!-- 信号问题列表 -->
          <div class="signals-panel">
            <!-- 领域过滤 -->
            <div class="domain-tabs" v-if="domains.length">
              <button
                v-for="d in [{ key: 'all', label: '全部' }, ...domains]"
                :key="d.key"
                :class="['domain-tab', { active: activeDomain === d.key }]"
                @click="activeDomain = d.key"
              >
                {{ d.label }}
                <span class="domain-count" v-if="d.key !== 'all'">
                  {{ domainConfirmedCount(d.key) }}/{{ domainSignalCount(d.key) }}
                </span>
              </button>
            </div>

            <!-- 加载中 -->
            <div v-if="qa.signalLoading" class="loading-signals">
              <i class="fas fa-spinner fa-spin"></i> 加载信号问题...
            </div>

            <!-- 信号卡片列表 -->
            <div v-else class="signal-list">
              <QASignalCard
                v-for="(item, idx) in filteredSignalItems"
                :key="item.id"
                :item="item"
                :index="idx"
              />
              <div v-if="!filteredSignalItems.length" class="empty-signals">
                暂无信号问题数据
              </div>
            </div>

            <!-- 领域结果摘要 -->
            <div v-if="qa.domainResults.length" class="domain-results-summary">
              <h4 class="summary-title">领域评估结果</h4>
              <div class="domain-result-grid">
                <div v-for="dr in qa.domainResults" :key="dr.id" class="domain-result-card">
                  <p class="dr-domain-name">{{ dr.domain_name }}</p>
                  <div class="dr-row">
                    <span class="dr-label">偏倚风险</span>
                    <span :class="['risk-badge', riskClass(dr.bias_risk_result)]">
                      {{ riskLabel(dr.bias_risk_result) }}
                      <i class="fas fa-lock" v-if="dr.bias_all_confirmed" style="font-size:0.6rem"></i>
                    </span>
                  </div>
                  <div class="dr-row" v-if="dr.applicability_result !== 'na'">
                    <span class="dr-label">适用性</span>
                    <span :class="['risk-badge', riskClass(dr.applicability_result)]">
                      {{ riskLabel(dr.applicability_result) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- PDF 预览面板 -->
          <div class="pdf-panel" v-if="showPdfPanel">
            <QAPdfViewer
              :pdfUrl="qa.currentRef.fulltext_url"
              :filename="qa.currentRef.title"
            />
          </div>
        </div>

        <!-- PDF 预览开关 -->
        <button
          class="toggle-pdf-btn"
          :class="{ active: showPdfPanel }"
          @click="showPdfPanel = !showPdfPanel"
          v-if="qa.currentRef.fulltext_url"
        >
          <i :class="showPdfPanel ? 'fas fa-compress-alt' : 'fas fa-file-pdf'"></i>
          {{ showPdfPanel ? '收起全文' : '查看全文' }}
        </button>
      </div>

      <!-- 未选文献时的占位 -->
      <div class="review-placeholder" v-else>
        <i class="fas fa-arrow-left" style="font-size:1.5rem;color:#cbd5e1"></i>
        <p>请从左侧选择文献开始审核</p>
      </div>
    </div>

    <!-- 底部操作 -->
    <div class="step-footer-actions">
      <button class="btn-secondary" @click="qa.currentStep = 3">
        <i class="fas fa-arrow-left"></i> 上一步
      </button>
      <span class="footer-tip">{{ confirmedCount }} / {{ qa.refs.length }} 篇已确认</span>
      <button class="btn-primary" :disabled="!confirmedCount" @click="qa.currentStep = 5">
        下一步：结果可视化 <i class="fas fa-arrow-right"></i>
      </button>
    </div>

    <!-- 一键确认弹窗 -->
    <Teleport to="body">
      <div v-if="showBatchConfirmModal" class="modal-mask" @click.self="showBatchConfirmModal = false">
        <div class="modal-box">
          <div class="modal-head">
            <i class="fas fa-check-double" style="color:#6366f1"></i>
            一键确认
          </div>
          <div class="modal-body">
            <p>选择确认方式，系统将自动设置所有未确认的信号问题：</p>
            <div class="confirm-mode-options">
              <div
                v-for="m in confirmModes"
                :key="m.key"
                :class="['confirm-mode-opt', { active: batchConfirmMode === m.key }]"
                @click="batchConfirmMode = m.key"
              >
                <div class="cmo-check"><i class="fas fa-check" v-if="batchConfirmMode === m.key"></i></div>
                <div>
                  <p class="cmo-name">{{ m.name }}</p>
                  <p class="cmo-desc">{{ m.desc }}</p>
                </div>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="showBatchConfirmModal = false">取消</button>
            <button class="btn-primary" @click="doBatchConfirm" :disabled="batchConfirmLoading">
              <i class="fas fa-spinner fa-spin" v-if="batchConfirmLoading"></i>
              <i class="fas fa-check" v-else></i>
              {{ batchConfirmLoading ? '确认中...' : '确认执行' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useQAStore } from '@/stores/qa'
import { useProjectStore } from '@/stores/project'
import QASignalCard from './QASignalCard.vue'
import QAPdfViewer  from './QAPdfViewer.vue'

const qa      = useQAStore()
const project = useProjectStore()

const refFilter     = ref('all')
const activeDomain  = ref('all')
const showPdfPanel  = ref(false)
const showBatchConfirmModal = ref(false)
const batchConfirmMode = ref('adopt_preselected')
const batchConfirmLoading = ref(false)

const refFilters = [
  { key: 'all',       label: '全部' },
  { key: 'pending',   label: '待审核' },
  { key: 'confirmed', label: '已完成' },
]

const confirmModes = [
  {
    key: 'adopt_preselected',
    name: '采纳预选结果',
    desc: '使用 AI 推荐的系统预选答案作为最终判断',
  },
  {
    key: 'adopt_ai',
    name: '采纳 AI 判断',
    desc: '直接使用 AI 原始评价答案（单模型：ai_judgment；双模型：model1 结果）',
  },
]

// ── 文献列表过滤 ────────────────────────────────────────────────────────────

const filteredRefList = computed(() => {
  let list = qa.refs
  if (refFilter.value === 'pending')   list = list.filter(r => r.review_status !== 'confirmed')
  if (refFilter.value === 'confirmed') list = list.filter(r => r.review_status === 'confirmed')
  return list
})

const confirmedCount = computed(() => qa.refs.filter(r => r.review_status === 'confirmed').length)

// ── 领域 & 信号过滤 ──────────────────────────────────────────────────────────

const domains = computed(() => {
  const seen = new Set()
  const list = []
  qa.signalItems.forEach(item => {
    if (!seen.has(item.domain)) {
      seen.add(item.domain)
      list.push({ key: item.domain, label: item.domain_name || item.domain })
    }
  })
  return list
})

const filteredSignalItems = computed(() => {
  if (activeDomain.value === 'all') return qa.signalItems
  return qa.signalItems.filter(i => i.domain === activeDomain.value)
})

const allConfirmed = computed(() => {
  if (!qa.signalItems.length) return false
  return qa.signalItems.every(i => i.is_confirmed)
})

function domainSignalCount(domain) {
  return qa.signalItems.filter(i => i.domain === domain).length
}
function domainConfirmedCount(domain) {
  return qa.signalItems.filter(i => i.domain === domain && i.is_confirmed).length
}

// ── 文献选择 ──────────────────────────────────────────────────────────────────

async function selectRef(ref) {
  activeDomain.value = 'all'
  await qa.selectRef(ref)
}

// ── 一键确认 ──────────────────────────────────────────────────────────────────

async function doBatchConfirm() {
  if (!qa.currentRef) return
  batchConfirmLoading.value = true
  try {
    await qa.batchConfirm(qa.currentRef.id, batchConfirmMode.value)
    showBatchConfirmModal.value = false
  } catch (e) {
    alert(e?.response?.data?.error || '批量确认失败')
  } finally {
    batchConfirmLoading.value = false
  }
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

function reviewDotClass(s) {
  return { confirmed: 'dot-confirmed', partial: 'dot-partial', not_started: 'dot-pending' }[s] || 'dot-pending'
}
function reviewLabel(s) {
  return { confirmed: '已完成', partial: '部分确认', not_started: '未开始' }[s] || ''
}
function evalStatusLabel(s) {
  return {
    completed: '全文评价', abstract_only: '摘要评价',
    failed: '评价失败', skipped_no_fulltext: '跳过', skipped_no_method: '跳过',
    pending: '待评价', running: '评价中',
  }[s] || s
}
function riskLabel(r) {
  return { low: '低风险', high: '高风险', unclear: '不清楚', pending: '待定', na: '不适用' }[r] || r
}
function riskClass(r) {
  return { low: 'risk-low', high: 'risk-high', unclear: 'risk-unclear', pending: 'risk-pending', na: 'risk-na' }[r] || ''
}

// ── 初始化 ────────────────────────────────────────────────────────────────────

onMounted(async () => {
  if (project.currentProject) await qa.fetchRefs(project.currentProject.id)
  if (qa.refs.length && !qa.currentRef) await selectRef(qa.refs[0])
})
</script>

<style scoped>
.qa-review { display: flex; flex-direction: column; gap: 14px; }
.step-header { display: flex; align-items: center; gap: 12px; }
.step-icon-wrap { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.step-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.step-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }

/* 主体布局 */
.review-layout { display: flex; gap: 12px; min-height: 560px; }

/* 左侧文献列表 */
.ref-panel { width: 220px; flex-shrink: 0; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
.ref-panel-header { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; }
.ref-count { font-size: 0.72rem; color: #94a3b8; display: block; margin-bottom: 6px; }
.filter-tabs { display: flex; gap: 2px; }
.filter-btn { flex: 1; padding: 4px 0; font-size: 0.7rem; background: none; border: 1px solid #e2e8f0; border-radius: 5px; cursor: pointer; color: #64748b; }
.filter-btn.active { background: #6366f1; color: #fff; border-color: #6366f1; }
.ref-list { flex: 1; overflow-y: auto; }
.ref-item { padding: 10px 12px; border-bottom: 1px solid #f8fafc; cursor: pointer; transition: background 0.1s; }
.ref-item:hover { background: #f5f3ff; }
.ref-item.active { background: #eef2ff; border-left: 3px solid #6366f1; }
.ref-item-title { font-size: 0.75rem; color: #334155; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 4px; }
.ref-item-meta { display: flex; align-items: center; justify-content: space-between; }
.ref-method-tag { font-size: 0.64rem; background: #ede9fe; color: #5b21b6; padding: 1px 5px; border-radius: 3px; }
.review-dot { width: 8px; height: 8px; border-radius: 50%; }
.dot-confirmed { background: #10b981; }
.dot-partial   { background: #f59e0b; }
.dot-pending   { background: #e2e8f0; }
.ref-list-empty { padding: 20px; text-align: center; font-size: 0.78rem; color: #94a3b8; }

/* 右侧主体 */
.review-main { flex: 1; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.review-placeholder { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #94a3b8; font-size: 0.85rem; }

/* 文献信息栏 */
.ref-info-bar { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 16px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ref-info-left { flex: 1; min-width: 0; }
.curr-ref-title { margin: 0 0 6px; font-size: 0.88rem; font-weight: 600; color: #1e293b; }
.curr-ref-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.meta-item { font-size: 0.72rem; color: #64748b; }
.method-chip { background: #ede9fe; color: #5b21b6; padding: 2px 6px; border-radius: 4px; }
.eval-status-chip { padding: 2px 6px; border-radius: 4px; }
.chip-completed     { background: #d1fae5; color: #065f46; }
.chip-abstract_only { background: #ffedd5; color: #9a3412; }
.chip-failed        { background: #fee2e2; color: #991b1b; }
.chip-skipped_no_fulltext, .chip-skipped_no_method { background: #f1f5f9; color: #64748b; }
.btn-batch-confirm { padding: 7px 14px; background: #6366f1; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 0.78rem; display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.btn-batch-confirm:disabled { opacity: 0.45; cursor: not-allowed; }

/* 内容分栏 */
.content-split { display: flex; gap: 12px; flex: 1; min-height: 0; }
.signals-panel { flex: 1; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.pdf-panel { width: 460px; flex-shrink: 0; }

/* 领域 tabs */
.domain-tabs { display: flex; gap: 4px; flex-wrap: wrap; }
.domain-tab { padding: 5px 12px; background: #fff; border: 1px solid #e2e8f0; border-radius: 7px; cursor: pointer; font-size: 0.78rem; color: #64748b; display: flex; align-items: center; gap: 5px; }
.domain-tab:hover { border-color: #6366f1; color: #6366f1; }
.domain-tab.active { background: #eef2ff; border-color: #6366f1; color: #4f46e5; font-weight: 500; }
.domain-count { font-size: 0.66rem; background: #e0e7ff; color: #4f46e5; padding: 0 5px; border-radius: 9999px; }

/* 加载 & 空 */
.loading-signals { display: flex; align-items: center; gap: 8px; color: #94a3b8; font-size: 0.82rem; padding: 20px; }
.signal-list { display: flex; flex-direction: column; gap: 10px; }
.empty-signals { text-align: center; color: #94a3b8; font-size: 0.82rem; padding: 30px; }

/* 领域结果摘要 */
.domain-results-summary { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; }
.summary-title { font-size: 0.82rem; font-weight: 600; color: #1e293b; margin: 0 0 10px; }
.domain-result-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.domain-result-card { background: #f8fafc; border-radius: 8px; padding: 10px; }
.dr-domain-name { font-size: 0.72rem; font-weight: 500; color: #475569; margin: 0 0 6px; }
.dr-row { display: flex; align-items: center; justify-content: space-between; gap: 4px; margin-bottom: 3px; }
.dr-label { font-size: 0.68rem; color: #94a3b8; }
.risk-badge { font-size: 0.68rem; padding: 2px 7px; border-radius: 4px; font-weight: 500; }
.risk-low     { background: #d1fae5; color: #065f46; }
.risk-high    { background: #fee2e2; color: #991b1b; }
.risk-unclear { background: #ffedd5; color: #9a3412; }
.risk-pending { background: #f1f5f9; color: #94a3b8; }
.risk-na      { background: #f1f5f9; color: #94a3b8; }

/* 底部 */
.step-footer-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.footer-tip { font-size: 0.78rem; color: #94a3b8; }
.btn-primary { padding: 8px 18px; background: #6366f1; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-primary:hover:not(:disabled) { background: #4f46e5; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { padding: 8px 16px; background: #fff; color: #6366f1; border: 1px solid #6366f1; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-secondary:hover { background: #f5f3ff; }

/* PDF 开关按钮 */
.toggle-pdf-btn { align-self: flex-start; padding: 5px 12px; background: #fff; border: 1px solid #e2e8f0; border-radius: 7px; cursor: pointer; font-size: 0.78rem; color: #64748b; display: flex; align-items: center; gap: 5px; }
.toggle-pdf-btn:hover { border-color: #6366f1; color: #6366f1; }
.toggle-pdf-btn.active { border-color: #6366f1; background: #eef2ff; color: #6366f1; }

/* 确认弹窗 */
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 9999; }
.modal-box { background: #fff; border-radius: 16px; width: 460px; max-width: 94vw; box-shadow: 0 16px 48px rgba(0,0,0,.18); }
.modal-head { display: flex; align-items: center; gap: 10px; padding: 20px 24px 16px; font-size: 1rem; font-weight: 600; color: #1e293b; border-bottom: 1px solid #f1f5f9; }
.modal-body { padding: 16px 24px; font-size: 0.85rem; color: #475569; }
.modal-body p { margin: 0 0 12px; }
.confirm-mode-options { display: flex; flex-direction: column; gap: 8px; }
.confirm-mode-opt { display: flex; align-items: flex-start; gap: 10px; padding: 12px; border: 2px solid #e2e8f0; border-radius: 10px; cursor: pointer; }
.confirm-mode-opt:hover { border-color: #a5b4fc; }
.confirm-mode-opt.active { border-color: #6366f1; background: #eef2ff; }
.cmo-check { width: 18px; height: 18px; border: 2px solid #e2e8f0; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.6rem; color: #fff; flex-shrink: 0; margin-top: 2px; }
.confirm-mode-opt.active .cmo-check { background: #6366f1; border-color: #6366f1; }
.cmo-name { font-size: 0.85rem; font-weight: 600; color: #1e293b; margin: 0 0 3px; }
.cmo-desc { font-size: 0.75rem; color: #64748b; margin: 0; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 24px; border-top: 1px solid #f1f5f9; }
</style>
