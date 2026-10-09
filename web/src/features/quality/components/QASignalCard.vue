<template>
  <!-- 单条信号问题卡片（紧凑版） -->
  <div :class="['signal-card', consistencyClass, { confirmed: item.is_confirmed }]">
    <!-- 头部：编号 + 领域 + AI评价状态 + 展开/收起（合一） -->
    <div class="card-head" @click="detailExpanded = !detailExpanded">
      <span class="signal-idx">{{ index + 1 }}</span>
      <div class="card-meta">
        <span class="domain-badge">{{ item.domain_name || item.domain }}</span>
        <span v-if="item.result_type === 'applicability'" class="type-badge">适用性</span>
      </div>
      <div class="consistency-tag" :class="consistencyClass">
        <i :class="consistencyIcon"></i>
        {{ consistencyLabel }}
      </div>
      <div
        v-if="hasDetail"
        class="toggle-btn"
      >
        {{ detailExpanded ? '收起' : '展开' }}
        <i :class="['fas', detailExpanded ? 'fa-chevron-up' : 'fa-chevron-down']"></i>
      </div>
    </div>

    <!-- 信号问题（始终显示） -->
    <p class="signal-question">{{ item.signal_question }}</p>

    <!-- AI 摘要行：始终显示，只展示 chip 和页码，不展示长文本 -->
    <div class="ai-summary-row">
      <!-- 单模型 -->
      <template v-if="!isMultiMode">
        <span class="ai-label">AI 判断</span>
        <span :class="['judgment-chip', judgmentColor(item.ai_judgment)]">{{ item.ai_judgment || '—' }}</span>
        <span v-if="primaryModelResult?.validation_status === 'no_evidence_unclear'" class="no-evidence-chip">证据不足</span>
        <template v-if="item.ai_evidence">
          <span class="summary-sep">·</span>
          <span class="ev-label">原文依据</span>
          <span class="ev-page-inline" v-if="item.ai_evidence_page">{{ item.ai_evidence_page }}</span>
          <span class="ev-page-inline" v-else>有依据</span>
        </template>
      </template>
      <!-- 多模型 -->
      <template v-else>
        <span v-for="mr in effectiveModelResults" :key="mr.model_id" class="model-summary-item">
          <span class="model-label-sm">{{ mr.model_name || mr.model_id }}</span>
          <span :class="['judgment-chip', judgmentColor(mr.judgment)]">{{ mr.judgment || '—' }}</span>
          <span v-if="mr.validation_status === 'no_evidence_unclear'" class="no-evidence-chip">证据不足</span>
        </span>
        <template v-if="item.ai_evidence">
          <span class="summary-sep">·</span>
          <span class="ev-label">原文依据</span>
          <span class="ev-page-inline" v-if="item.ai_evidence_page">{{ item.ai_evidence_page }}</span>
        </template>
      </template>
    </div>

    <!-- 可展开详情：理由 + 全文引用 -->
    <template v-if="detailExpanded">
      <!-- 单模型详情 -->
      <div class="ai-detail" v-if="!isMultiMode">
        <p class="detail-reason" v-if="item.ai_reason">{{ item.ai_reason }}</p>
        <div v-if="item.ai_evidence" class="detail-evidence">
          <span class="ev-label">原文</span>
          <div class="evidence-body">
            <div class="evidence-meta" v-if="primaryModelResult?.evidence_page">
              <span>{{ primaryModelResult.evidence_page }}</span>
              <span v-if="primaryModelResult.evidence_section">{{ sectionLabel(primaryModelResult.evidence_section) }}</span>
            </div>
            <span class="ev-text">{{ item.ai_evidence }}</span>
            <button
              v-if="primaryModelResult?.evidence_chunk_id"
              class="btn-context"
              @click.stop="loadContext(primaryModelResult)"
            ><i class="fas fa-book-open"></i> 查看相邻上下文</button>
          </div>
        </div>
      </div>
      <!-- 多模型详情 -->
      <div class="ai-detail" v-else>
        <div class="multi-models-row">
          <div v-for="mr in effectiveModelResults" :key="mr.model_id" class="multi-model-col">
            <span class="model-label">{{ mr.model_name || mr.model_id }}</span>
            <span :class="['judgment-chip', judgmentColor(mr.judgment)]">{{ mr.judgment || '—' }}</span>
            <p class="detail-reason" v-if="mr.reason">{{ mr.reason }}</p>
            <div v-if="mr.evidence" class="model-evidence">
              <div class="evidence-meta">
                <span>{{ mr.evidence_page || '位置未知' }}</span>
                <span v-if="mr.evidence_section">{{ sectionLabel(mr.evidence_section) }}</span>
              </div>
              <p>{{ mr.evidence }}</p>
              <button
                v-if="mr.evidence_chunk_id"
                class="btn-context"
                @click.stop="loadContext(mr)"
              ><i class="fas fa-book-open"></i> 查看相邻上下文</button>
              <div v-if="auth.isAdmin" class="model-audit">
                {{ mr.prompt_version || 'legacy' }} · {{ mr.retrieval_version || '无检索版本' }}
              </div>
            </div>
          </div>
        </div>
        <div class="recommend-row" v-if="item.system_recommendation">
          <span class="rec-label"><i :class="consistencyIcon" style="margin-right:3px"></i>{{ consistencyLabel }}</span>
          <span :class="['judgment-chip', judgmentColor(item.system_recommendation)]">{{ item.system_recommendation }}</span>
        </div>
        <div v-if="item.ai_evidence" class="detail-evidence">
          <span class="ev-label">原文</span>
          <span class="ev-text">{{ item.ai_evidence }}</span>
        </div>
      </div>

      <div v-if="contextLoading || contextData || contextError" class="context-panel">
        <div class="context-head">
          <strong>证据上下文</strong>
          <button @click.stop="closeContext" aria-label="关闭上下文">×</button>
        </div>
        <div v-if="contextLoading" class="context-loading"><i class="fas fa-spinner fa-spin"></i> 加载中…</div>
        <div v-else-if="contextError" class="context-error">{{ contextError }}</div>
        <div v-else class="context-chunks">
          <article v-for="chunk in contextData.chunks" :key="chunk.chunk_id" :class="{ cited: chunk.is_cited }">
            <header>
              {{ pageLabel(chunk) }} · {{ sectionLabel(chunk.section) }}
              <span v-if="chunk.is_cited">当前引用</span>
            </header>
            <p>{{ chunk.text }}</p>
            <small v-if="chunk.text_truncated">片段过长，已限长显示</small>
          </article>
        </div>
      </div>
    </template>

    <!-- 确认区：始终一行显示 -->
    <div class="confirm-zone">
      <div class="judgment-options">
        <button
          v-for="opt in safeOptions"
          :key="opt"
          :class="['opt-btn', {
            active: humanJudgment === opt,
            preselect: opt === item.pre_selected && humanJudgment !== opt,
          }]"
          @click.stop="selectJudgment(opt)"
        >
          {{ opt }}
          <i class="fas fa-star preselect-star" v-if="opt === item.pre_selected && !item.is_confirmed"></i>
        </button>
      </div>
      <button
        class="btn-confirm"
        :class="{ confirmed: item.is_confirmed }"
        @click.stop="doConfirm"
        :disabled="!humanJudgment || confirmLoading"
      >
        <i class="fas fa-spinner fa-spin" v-if="confirmLoading"></i>
        <i class="fas fa-check" v-else></i>
        {{ item.is_confirmed ? '已确认' : '确认' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useQAStore } from '@/features/quality/store'
import { useAuthStore } from '@/features/account/store'

const props = defineProps({
  item:  { type: Object, required: true },
  index: { type: Number, default: 0 },
})

const qa = useQAStore()
const auth = useAuthStore()
const humanJudgment  = ref(props.item.human_judgment || props.item.pre_selected || '')
const confirmLoading = ref(false)
const detailExpanded = ref(false)  // AI 详情默认收起
const contextLoading = ref(false)
const contextData = ref(null)
const contextError = ref('')

const safeOptions = computed(() => {
  const o = props.item.options
  if (Array.isArray(o)) return o
  if (typeof o === 'string' && o) {
    try { const p = JSON.parse(o); return Array.isArray(p) ? p : [p] } catch { return [o] }
  }
  return []
})

watch(() => props.item, (newItem) => {
  humanJudgment.value = newItem.human_judgment || newItem.pre_selected || ''
}, { deep: true })

// 是否有可展开的详情（理由或原文全文）
const hasDetail = computed(() => {
  if (!isMultiMode.value) return !!(props.item.ai_reason || props.item.ai_evidence)
  return effectiveModelResults.value.some(mr => mr.reason) || !!props.item.ai_evidence
})

const isMultiMode = computed(() => props.item.consistency !== 'single')

const effectiveModelResults = computed(() => {
  const mr = props.item.model_results
  if (Array.isArray(mr) && mr.length > 0) return mr
  const results = []
  if (props.item.model1_id || props.item.model1_judgment)
    results.push({ model_id: props.item.model1_id || 'Model 1', model_name: props.item.model1_id || 'Model 1', judgment: props.item.model1_judgment, reason: props.item.model1_reason })
  if (props.item.model2_id || props.item.model2_judgment)
    results.push({ model_id: props.item.model2_id || 'Model 2', model_name: props.item.model2_id || 'Model 2', judgment: props.item.model2_judgment, reason: props.item.model2_reason })
  return results
})

const primaryModelResult = computed(() => (
  effectiveModelResults.value.find(result => (
    result.judgment === props.item.ai_judgment && result.evidence_chunk_id
  )) || effectiveModelResults.value.find(result => result.evidence_chunk_id) || null
))

const consistencyClass = computed(() => {
  if (props.item.is_confirmed) return 'state-confirmed'
  const c = props.item.consistency
  if (c === 'consistent' || c === 'majority') return 'state-consistent'
  if (c === 'divergent') return 'state-divergent'
  if (c === 'failed')    return 'state-failed'
  if (c === 'partial')   return 'state-partial'
  return ''
})

const consistencyLabel = computed(() => {
  if (props.item.is_confirmed) return '已确认'
  const c = props.item.consistency
  const n = effectiveModelResults.value.length
  return {
    single:     'AI 评价',
    consistent: n > 2 ? `${n} 模型一致` : '双模型一致',
    majority:   `多数一致（${n} 模型）`,
    divergent:  '存在分歧',
    partial:    '部分结果',
    failed:     '评价失败',
  }[c] || ''
})

const consistencyIcon = computed(() => {
  if (props.item.is_confirmed) return 'fas fa-check'
  const c = props.item.consistency
  return {
    single:     'fas fa-robot',
    consistent: 'fas fa-handshake',
    majority:   'fas fa-users',
    divergent:  'fas fa-code-compare',
    partial:    'fas fa-minus-circle',
    failed:     'fas fa-times-circle',
  }[c] || 'fas fa-circle'
})

function judgmentColor(val) {
  if (!val) return ''
  if (['否', '高', '高风险'].includes(val)) return 'chip-red'
  if (['是', '低', '低风险'].includes(val)) return 'chip-green'
  if (['不清楚', '不确定', '中等'].includes(val)) return 'chip-orange'
  if (val.startsWith('★')) return 'chip-star'
  if (val.startsWith('✗')) return 'chip-fail'
  return 'chip-gray'
}

function selectJudgment(opt) { humanJudgment.value = opt }

function sectionLabel(section) {
  return {
    title: '标题', abstract: '摘要', introduction: '引言', methods: '方法',
    results: '结果', discussion: '讨论', references: '参考文献', unknown: '未识别章节',
  }[section] || section || '未识别章节'
}

function pageLabel(chunk) {
  return chunk.page_start === chunk.page_end
    ? `第${chunk.page_start}页`
    : `第${chunk.page_start}-${chunk.page_end}页`
}

async function loadContext(modelResult) {
  contextLoading.value = true
  contextError.value = ''
  contextData.value = null
  try {
    contextData.value = await qa.fetchEvidenceContext(
      props.item.id,
      modelResult.evidence_chunk_id,
      modelResult.model_id,
    )
  } catch (error) {
    contextError.value = error?.response?.data?.error || '证据上下文暂时无法读取'
  } finally {
    contextLoading.value = false
  }
}

function closeContext() {
  contextData.value = null
  contextError.value = ''
  contextLoading.value = false
}

async function doConfirm() {
  if (!humanJudgment.value) return
  confirmLoading.value = true
  try {
    await qa.confirmSignalItem(props.item.id, humanJudgment.value)
  } finally {
    confirmLoading.value = false
  }
}
</script>

<style scoped>
.signal-card {
  background: #fff;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  transition: border-color 0.15s;
}
.signal-card.state-divergent  { border-color: #fbbf24; background: #fffbeb; }
.signal-card.state-consistent { border-color: #a7f3d0; }
.signal-card.state-confirmed  { border-color: #6ee7b7; background: #f0fdf4; }
.signal-card.state-failed     { border-color: #fca5a5; background: #fff5f5; }

/* 头部 */
.card-head {
  display: flex; align-items: center; gap: 7px;
  cursor: pointer; user-select: none;
}
.signal-idx {
  width: 20px; height: 20px; background: #6366f1; color: #fff;
  border-radius: 50%; font-size: 0.65rem; font-weight: 700;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.card-meta { display: flex; gap: 4px; flex: 1; min-width: 0; }
.domain-badge { font-size: 0.68rem; padding: 2px 6px; background: #ede9fe; color: #5b21b6; border-radius: 4px; white-space: nowrap; }
.type-badge   { font-size: 0.68rem; padding: 2px 6px; background: #dbeafe; color: #1e40af; border-radius: 4px; }
.consistency-tag {
  font-size: 0.65rem; padding: 2px 7px; border-radius: 4px;
  display: flex; align-items: center; gap: 3px;
  background: #f1f5f9; color: #64748b; flex-shrink: 0; white-space: nowrap;
}
.consistency-tag.state-divergent  { background: #fef9c3; color: #a16207; }
.consistency-tag.state-consistent { background: #d1fae5; color: #065f46; }
.consistency-tag.state-confirmed  { background: #d1fae5; color: #065f46; }
.consistency-tag.state-failed     { background: #fee2e2; color: #991b1b; }
.toggle-icon { font-size: 0.65rem; color: #94a3b8; flex-shrink: 0; }
.toggle-btn {
  display: flex; align-items: center; gap: 3px;
  font-size: 0.68rem; color: #94a3b8;
  flex-shrink: 0;
}

/* 问题标题 */
.signal-question {
  margin: 0; font-size: 0.82rem; font-weight: 500; color: #1e293b;
  line-height: 1.4;
}

/* AI 摘要行（始终显示，一行） */
.ai-summary-row {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  background: #f8fafc; border-radius: 6px; padding: 5px 8px;
}
.ai-label, .ev-label, .model-label, .rec-label {
  font-size: 0.65rem; color: #94a3b8; flex-shrink: 0;
}
.model-label-sm { font-size: 0.65rem; color: #94a3b8; }
.model-summary-item { display: flex; align-items: center; gap: 4px; }
.summary-sep { color: #cbd5e1; font-size: 0.7rem; }
.ev-page-inline { font-size: 0.68rem; color: #64748b; background: #e2e8f0; padding: 1px 5px; border-radius: 3px; }
.no-evidence-chip { font-size:.62rem; color:#92400e; background:#fef3c7; border-radius:4px; padding:1px 5px; }
.btn-expand { display: none; } /* 已合并到卡片头部，保留空规则防止引用报错 */

/* 展开后详情区 */
.ai-detail {
  background: #f8fafc; border-radius: 6px; padding: 8px 10px;
  display: flex; flex-direction: column; gap: 6px;
}
.detail-reason { margin: 0; font-size: 0.72rem; color: #475569; line-height: 1.5; }
.detail-evidence { display: flex; gap: 6px; align-items: flex-start; }
.ev-text { font-size: 0.7rem; color: #475569; font-style: italic; line-height: 1.5; flex: 1; }
.evidence-body { display:flex; flex-direction:column; gap:5px; min-width:0; flex:1; }
.evidence-meta { display:flex; flex-wrap:wrap; gap:4px; }
.evidence-meta span { font-size:.62rem; color:#475569; background:#e2e8f0; border-radius:999px; padding:1px 6px; }
.btn-context { align-self:flex-start; border:1px solid #c7d2fe; background:#eef2ff; color:#4f46e5; border-radius:5px; padding:3px 7px; font-size:.65rem; cursor:pointer; }
.btn-context:hover { background:#e0e7ff; }

/* 多模型 */
.multi-models-row { display: flex; gap: 8px; flex-wrap: wrap; }
.multi-model-col {
  flex: 1; min-width: 100px;
  display: flex; flex-direction: column; gap: 4px;
  background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px 8px;
}
.model-evidence { border-top:1px dashed #e2e8f0; padding-top:5px; display:flex; flex-direction:column; gap:4px; }
.model-evidence p { margin:0; font-size:.68rem; line-height:1.45; color:#475569; font-style:italic; }
.model-audit { color:#94a3b8; font-size:.58rem; overflow-wrap:anywhere; }
.recommend-row { display: flex; align-items: center; gap: 7px; padding-top: 6px; border-top: 1px dashed #e2e8f0; }

.context-panel { background:#fff; border:1px solid #c7d2fe; border-radius:8px; padding:8px; display:flex; flex-direction:column; gap:7px; }
.context-head { display:flex; justify-content:space-between; align-items:center; font-size:.72rem; color:#3730a3; }
.context-head button { border:0; background:transparent; color:#94a3b8; font-size:1rem; cursor:pointer; }
.context-loading, .context-error { font-size:.7rem; color:#64748b; }
.context-error { color:#b91c1c; }
.context-chunks { display:flex; flex-direction:column; gap:6px; }
.context-chunks article { background:#f8fafc; border-left:3px solid #cbd5e1; border-radius:5px; padding:6px 8px; }
.context-chunks article.cited { background:#eef2ff; border-left-color:#6366f1; }
.context-chunks header { font-size:.62rem; color:#64748b; display:flex; justify-content:space-between; gap:6px; }
.context-chunks header span { color:#4f46e5; font-weight:600; }
.context-chunks p { white-space:pre-wrap; margin:4px 0 0; font-size:.68rem; line-height:1.5; color:#334155; }
.context-chunks small { color:#b45309; font-size:.6rem; }

/* 判断颜色 */
.judgment-chip { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 600; }
.chip-red    { background: #fee2e2; color: #991b1b; }
.chip-green  { background: #d1fae5; color: #065f46; }
.chip-orange { background: #ffedd5; color: #9a3412; }
.chip-star   { background: #fef3c7; color: #b45309; }
.chip-fail   { background: #fee2e2; color: #991b1b; }
.chip-gray   { background: #f1f5f9; color: #475569; }

/* 确认区（始终一行） */
.confirm-zone {
  display: flex; align-items: center; gap: 8px;
  padding-top: 7px; border-top: 1px solid #f1f5f9;
  flex-wrap: nowrap;
}
.judgment-options { display: flex; gap: 5px; flex: 1; }
.opt-btn {
  padding: 4px 10px;
  border: 1.5px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.12s;
  display: flex; align-items: center; gap: 3px;
  color: #475569;
  white-space: nowrap;
}
.opt-btn:hover { border-color: #6366f1; color: #6366f1; }
.opt-btn.active { border-color: #6366f1; background: #eef2ff; color: #4f46e5; font-weight: 600; }
.opt-btn.preselect { border-color: #a5b4fc; border-style: dashed; }
.preselect-star { font-size: 0.55rem; color: #f59e0b; }

.btn-confirm {
  padding: 5px 12px;
  background: #6366f1; color: #fff;
  border: none; border-radius: 6px;
  cursor: pointer; font-size: 0.75rem;
  display: flex; align-items: center; gap: 4px;
  flex-shrink: 0; white-space: nowrap;
}
.btn-confirm:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-confirm.confirmed { background: #10b981; }
</style>
