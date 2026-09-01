<template>
  <!-- 单条信号问题卡片 -->
  <div :class="['signal-card', consistencyClass, { confirmed: item.is_confirmed }]">
    <!-- 头部：编号 + 领域 + 一致性状态 -->
    <div class="card-head">
      <span class="signal-idx">{{ index + 1 }}</span>
      <div class="card-meta">
        <span class="domain-badge">{{ item.domain_name || item.domain }}</span>
        <span v-if="item.result_type === 'applicability'" class="type-badge">适用性</span>
      </div>
      <div class="consistency-tag" :class="consistencyClass">
        <i :class="consistencyIcon"></i>
        {{ consistencyLabel }}
      </div>
    </div>

    <!-- 信号问题 -->
    <p class="signal-question">{{ item.signal_question }}</p>
    <p class="signal-desc" v-if="item.signal_description">{{ item.signal_description }}</p>

    <!-- AI 评价结果（单模型 / 双模型） -->
    <div class="ai-results" v-if="!isDualMode">
      <!-- 单模型 -->
      <div class="ai-result-row">
        <span class="ai-label">AI 判断</span>
        <span :class="['judgment-chip', judgmentColor(item.ai_judgment)]">{{ item.ai_judgment || '—' }}</span>
        <span class="ai-reason" v-if="item.ai_reason">{{ item.ai_reason }}</span>
      </div>
      <div v-if="item.ai_evidence" class="evidence-block">
        <span class="ev-label">原文依据</span>
        <span class="ev-text">{{ item.ai_evidence }}</span>
        <span class="ev-page" v-if="item.ai_evidence_page">{{ item.ai_evidence_page }}</span>
      </div>
    </div>

    <div class="ai-results dual" v-else>
      <!-- 双模型 -->
      <div class="dual-row">
        <div class="dual-model-col">
          <span class="model-label">{{ item.model1_id || 'Model 1' }}</span>
          <span :class="['judgment-chip', judgmentColor(item.model1_judgment)]">{{ item.model1_judgment || '—' }}</span>
          <p class="ai-reason" v-if="item.model1_reason">{{ item.model1_reason }}</p>
        </div>
        <div class="dual-vs">VS</div>
        <div class="dual-model-col">
          <span class="model-label">{{ item.model2_id || 'Model 2' }}</span>
          <span :class="['judgment-chip', judgmentColor(item.model2_judgment)]">{{ item.model2_judgment || '—' }}</span>
          <p class="ai-reason" v-if="item.model2_reason">{{ item.model2_reason }}</p>
        </div>
      </div>
      <div class="recommend-row" v-if="item.system_recommendation">
        <span class="rec-label">系统推荐</span>
        <span :class="['judgment-chip', judgmentColor(item.system_recommendation)]">{{ item.system_recommendation }}</span>
      </div>
    </div>

    <!-- 人工确认区 -->
    <div class="confirm-zone">
      <span class="confirm-label">最终判断</span>
      <div class="judgment-options">
        <button
          v-for="opt in safeOptions"
          :key="opt"
          :class="['opt-btn', {
            active: humanJudgment === opt,
            preselect: opt === item.pre_selected && humanJudgment !== opt,
          }]"
          @click="selectJudgment(opt)"
        >
          {{ opt }}
          <i class="fas fa-star preselect-star" v-if="opt === item.pre_selected && !item.is_confirmed"></i>
        </button>
      </div>
      <button
        class="btn-confirm"
        :class="{ confirmed: item.is_confirmed }"
        @click="doConfirm"
        :disabled="!humanJudgment || confirmLoading"
      >
        <i class="fas fa-spinner fa-spin" v-if="confirmLoading"></i>
        <i class="fas fa-check" v-else-if="item.is_confirmed"></i>
        <i class="fas fa-check-circle" v-else></i>
        {{ item.is_confirmed ? '已确认' : '确认' }}
      </button>
    </div>

    <!-- 确认人信息 -->
    <div v-if="item.is_confirmed" class="confirmed-info">
      <i class="fas fa-user-check"></i>
      已由 {{ item.confirmed_by_name || '当前用户' }} 确认
      <template v-if="item.human_judgment !== item.original_ai_judgment && item.original_ai_judgment">
        · <span class="modified-hint">已修改（原 AI：{{ item.original_ai_judgment }}）</span>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useQAStore } from '@/stores/qa'

const props = defineProps({
  item:     { type: Object, required: true },
  index:    { type: Number, default: 0 },
})

const qa = useQAStore()
const humanJudgment = ref(props.item.human_judgment || props.item.pre_selected || '')
const confirmLoading = ref(false)

// 防御：options 可能是 null / 字符串，保证始终是数组
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

const isDualMode = computed(() => props.item.consistency !== 'single')

const consistencyClass = computed(() => {
  if (props.item.is_confirmed) return 'state-confirmed'
  const c = props.item.consistency
  if (c === 'consistent') return 'state-consistent'
  if (c === 'divergent')  return 'state-divergent'
  if (c === 'failed')     return 'state-failed'
  if (c === 'partial')    return 'state-partial'
  return ''
})

const consistencyLabel = computed(() => {
  if (props.item.is_confirmed) return '已确认'
  const c = props.item.consistency
  return {
    single:     'AI 评价',
    consistent: '双模型一致',
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

function selectJudgment(opt) {
  humanJudgment.value = opt
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
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color 0.15s;
}
.signal-card.state-divergent { border-color: #fbbf24; background: #fffbeb; }
.signal-card.state-consistent { border-color: #a7f3d0; }
.signal-card.state-confirmed { border-color: #6ee7b7; background: #f0fdf4; }
.signal-card.state-failed { border-color: #fca5a5; background: #fff5f5; }

/* 头部 */
.card-head { display: flex; align-items: center; gap: 8px; }
.signal-idx { width: 22px; height: 22px; background: #6366f1; color: #fff; border-radius: 50%; font-size: 0.68rem; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.card-meta { display: flex; gap: 4px; flex: 1; }
.domain-badge { font-size: 0.7rem; padding: 2px 7px; background: #ede9fe; color: #5b21b6; border-radius: 4px; }
.type-badge { font-size: 0.7rem; padding: 2px 7px; background: #dbeafe; color: #1e40af; border-radius: 4px; }
.consistency-tag { font-size: 0.68rem; padding: 2px 8px; border-radius: 4px; display: flex; align-items: center; gap: 4px; background: #f1f5f9; color: #64748b; }
.consistency-tag.state-divergent { background: #fef9c3; color: #a16207; }
.consistency-tag.state-consistent { background: #d1fae5; color: #065f46; }
.consistency-tag.state-confirmed { background: #d1fae5; color: #065f46; }
.consistency-tag.state-failed { background: #fee2e2; color: #991b1b; }

/* 问题 */
.signal-question { margin: 0; font-size: 0.85rem; font-weight: 500; color: #1e293b; }
.signal-desc { margin: 0; font-size: 0.75rem; color: #64748b; }

/* AI 结果 */
.ai-results { background: #f8fafc; border-radius: 8px; padding: 10px 12px; }
.ai-result-row { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
.ai-label, .model-label, .rec-label { font-size: 0.7rem; color: #64748b; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; flex-shrink: 0; }
.ai-reason { font-size: 0.75rem; color: #475569; flex: 1; margin: 0; }
.evidence-block { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; align-items: flex-start; }
.ev-label { font-size: 0.65rem; color: #94a3b8; flex-shrink: 0; margin-top: 2px; }
.ev-text { font-size: 0.75rem; color: #475569; flex: 1; font-style: italic; }
.ev-page { font-size: 0.65rem; color: #94a3b8; flex-shrink: 0; margin-top: 2px; }

/* 双模型 */
.ai-results.dual { }
.dual-row { display: flex; align-items: flex-start; gap: 12px; }
.dual-model-col { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.dual-vs { width: 28px; text-align: center; font-size: 0.7rem; color: #94a3b8; font-weight: 600; padding-top: 4px; }
.recommend-row { margin-top: 8px; padding-top: 8px; border-top: 1px dashed #e2e8f0; display: flex; align-items: center; gap: 8px; }

/* 判断颜色 */
.judgment-chip { display: inline-block; padding: 2px 8px; border-radius: 5px; font-size: 0.75rem; font-weight: 600; }
.chip-red    { background: #fee2e2; color: #991b1b; }
.chip-green  { background: #d1fae5; color: #065f46; }
.chip-orange { background: #ffedd5; color: #9a3412; }
.chip-star   { background: #fef3c7; color: #b45309; }
.chip-fail   { background: #fee2e2; color: #991b1b; }
.chip-gray   { background: #f1f5f9; color: #475569; }

/* 确认区 */
.confirm-zone { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding-top: 8px; border-top: 1px solid #f1f5f9; }
.confirm-label { font-size: 0.75rem; font-weight: 500; color: #475569; flex-shrink: 0; }
.judgment-options { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }
.opt-btn {
  padding: 5px 12px;
  border: 1.5px solid #e2e8f0;
  border-radius: 7px;
  background: #fff;
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.12s;
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  color: #475569;
}
.opt-btn:hover { border-color: #6366f1; color: #6366f1; }
.opt-btn.active { border-color: #6366f1; background: #eef2ff; color: #4f46e5; font-weight: 600; }
.opt-btn.preselect { border-color: #a5b4fc; border-style: dashed; }
.preselect-star { font-size: 0.6rem; color: #f59e0b; }
.btn-confirm {
  padding: 6px 14px;
  background: #6366f1;
  color: #fff;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  font-size: 0.78rem;
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}
.btn-confirm:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-confirm.confirmed { background: #10b981; }

/* 已确认信息 */
.confirmed-info { font-size: 0.7rem; color: #64748b; display: flex; align-items: center; gap: 4px; }
.modified-hint { color: #f59e0b; }
</style>
