<template>
  <div class="rs-evidence" :class="{ 'rs-evidence--compact': compact }">
    <p v-if="!detail?.models?.length" class="rs-empty">
      尚无 AI 建议，可直接进行人工审阅。
    </p>
    <article
      v-for="model in detail?.models || []"
      :key="model.id"
      class="rs-model-result"
    >
      <div class="rs-toolbar">
        <strong>{{ modelName(model.model_id) }}</strong><span
          class="rs-badge"
          :class="
            model.decision === 'included'
              ? 'success'
              : model.decision === 'excluded'
                ? 'danger'
                : 'warning'
          "
        >{{
          model.status === 'completed'
            ? decisionLabel(model.decision)
            : label(model.status)
        }}</span>
      </div>
      <p v-if="model.reason" class="rs-wrap">{{ model.reason }}</p>
      <p v-if="model.error" class="rs-warning">{{ model.error }}</p>
      <div v-if="compact && model.evidence?.length" class="evidence-list">
        <article
          v-for="row in model.evidence"
          :key="row.id"
          class="evidence-card"
        >
          <div class="evidence-head">
            <span><i class="fas fa-quote-left"></i> AI 证据</span><button :disabled="!row.page" @click="$emit('page', row.page)">
              {{ row.page ? `第 ${row.page} 页` : '未提供页码' }}
            </button>
          </div>
          <p>{{ row.text }}</p>
        </article>
      </div>
      <details
        v-for="criterion in model.criteria_results"
        :key="criterion.criterion_id"
        class="rs-criterion-result"
      >
        <summary>
          {{ criterion.criterion_id }} ·
          {{ judgments[criterion.judgment] || criterion.judgment }}
        </summary>
        <p>{{ criterion.reason }}</p>
        <blockquote v-for="id in criterion.evidence_ids" :key="id">
          <template v-if="evidence(model, id)">
            <p>{{ evidence(model, id).text }}</p>
            <button
              class="rs-link"
              @click="$emit('page', evidence(model, id).page)"
            >
              第 {{ evidence(model, id).page }} 页 · 定位原文
            </button>
          </template>
        </blockquote>
      </details>
    </article>
    <p v-if="detail?.coverage" class="rs-muted">
      {{
        detail.coverage.strategy === 'full'
          ? '完整可引用文本'
          : '按标准检索证据'
      }}
      · 选取 {{ detail.coverage.selected_spans }} /
      {{ detail.coverage.total_spans }} 个原文区间。AI
      建议仅供参考，请核对全文。
    </p>
  </div>
</template>
<script setup>
import { inject } from 'vue'
import { label, decisionLabel } from '../state'
defineProps({ detail: { type: Object, default: null }, compact: Boolean })
defineEmits(['page'])
const ws = inject('rescreen')
const judgments = {
  satisfied: '不触发排除',
  violated: '触发排除',
  unclear: '证据不明确',
}
function evidence(model, id) {
  return model.evidence?.find((row) => row.id === id)
}
function modelName(id) {
  return (
    ws.state.models
      .flatMap((provider) => provider.sub_models)
      .find((row) => row.id === id)?.name || id
  )
}
</script>
<style scoped>
.evidence-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
  margin: 8px 0;
}
.evidence-card {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 8px;
  padding: 0.55rem 0.65rem;
  min-width: 0;
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
  overflow-wrap: anywhere;
}
@media (max-width: 1100px) {
  .evidence-list {
    grid-template-columns: 1fr;
  }
}
.rs-evidence--compact .rs-model-result {
  margin-top: 8px;
  padding-top: 8px;
}
.rs-evidence--compact .rs-model-result > p {
  margin: 6px 0;
  font-size: 0.78rem;
}
.rs-evidence--compact .rs-criterion-result {
  margin-top: 6px;
  padding: 8px 10px;
}
.rs-evidence--compact .rs-model-result:first-child {
  border-top: 0;
}
.rs-evidence--compact blockquote {
  font-size: 0.77rem;
  line-height: 1.5;
}
</style>
