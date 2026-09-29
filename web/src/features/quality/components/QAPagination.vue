<template>
  <div v-if="totalPages > 1" class="qa-pagination">
    <span class="qa-pagination-summary">共 {{ total.toLocaleString() }} 篇</span>
    <button :disabled="loading || page <= 1" @click="$emit('change', page - 1)">
      <i class="fas fa-chevron-left"></i>
    </button>
    <label>
      第
      <input
        :value="page"
        type="number"
        min="1"
        :max="totalPages"
        :disabled="loading"
        @keyup.enter="submitPage"
        @blur="submitPage"
      />
      / {{ totalPages }} 页
    </label>
    <button :disabled="loading || page >= totalPages" @click="$emit('change', page + 1)">
      <i class="fas fa-chevron-right"></i>
    </button>
  </div>
</template>

<script setup>
const props = defineProps({
  page: { type: Number, required: true },
  totalPages: { type: Number, required: true },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['change'])

function submitPage(event) {
  const value = Number(event.target.value)
  const target = Math.min(props.totalPages, Math.max(1, Number.isFinite(value) ? value : props.page))
  event.target.value = target
  if (target !== props.page) emit('change', target)
}
</script>

<style scoped>
.qa-pagination { display:flex; align-items:center; justify-content:flex-end; gap:8px; padding:10px 12px; border-top:1px solid #f1f5f9; color:#64748b; font-size:.75rem; background:#fff; }
.qa-pagination-summary { margin-right:auto; }
.qa-pagination button { width:30px; height:28px; border:1px solid #e2e8f0; border-radius:7px; background:#fff; color:#475569; cursor:pointer; }
.qa-pagination button:hover:not(:disabled) { border-color:#6366f1; color:#6366f1; }
.qa-pagination button:disabled { opacity:.4; cursor:not-allowed; }
.qa-pagination label { display:flex; align-items:center; gap:5px; white-space:nowrap; }
.qa-pagination input { width:52px; height:28px; border:1px solid #e2e8f0; border-radius:7px; text-align:center; color:#334155; }
</style>
