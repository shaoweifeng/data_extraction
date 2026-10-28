<template>
  <div class="rs-evidence">
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
            ? label(model.decision)
            : label(model.status)
        }}</span>
      </div>
      <p v-if="model.reason" class="rs-wrap">{{ model.reason }}</p>
      <p v-if="model.error" class="rs-warning">{{ model.error }}</p>
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
import { label } from '../state'
defineProps({ detail: { type: Object, default: null } })
defineEmits(['page'])
const ws = inject('rescreen')
const judgments = {
  satisfied: '不触发排除',
  violated: '触发排除',
  unclear: '证据不明确',
}
function evidence(model, id) {
  return model.evidence.find((row) => row.id === id)
}
function modelName(id) {
  return (
    ws.state.models
      .flatMap((provider) => provider.sub_models)
      .find((row) => row.id === id)?.name || id
  )
}
</script>
