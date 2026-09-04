<template>
  <div class="step-nav">
    <button
      v-if="qa.currentStep > 1"
      class="nav-btn nav-prev"
      @click="qa.currentStep--"
    >
      <i class="fas fa-arrow-left"></i>
      <span>上一步</span>
    </button>
    <div v-else></div>

    <div class="step-nav-info">
      第 <span class="step-num">{{ qa.currentStep }}</span> 步 / 共 6 步
      <template v-if="$slots.center"><span class="center-sep">·</span><slot name="center" /></template>
    </div>

    <button
      v-if="qa.currentStep < 6"
      class="nav-btn nav-next"
      :disabled="nextDisabled"
      @click="qa.currentStep++"
    >
      <span>下一步</span>
      <i class="fas fa-arrow-right"></i>
    </button>
    <div v-else></div>
  </div>
</template>

<script setup>
import { useQAStore } from '@/stores/qa'

defineProps({
  nextDisabled: { type: Boolean, default: false },
})

const qa = useQAStore()
</script>

<style scoped>
.step-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
}

.nav-btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 8px 18px;
  border-radius: 8px; border: 1px solid #e2e8f0;
  font-size: 0.85rem; font-weight: 500;
  cursor: pointer; transition: all 0.18s;
  background: #fff; color: #374151;
}
.nav-btn:disabled { opacity: .5; cursor: not-allowed; }
.nav-btn:hover:not(:disabled) {
  border-color: #a5b4fc; color: #6366f1;
  box-shadow: 0 2px 8px rgba(99,102,241,.12);
}

.nav-next {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff; border-color: transparent;
}
.nav-next:hover:not(:disabled) {
  opacity: 0.9;
  box-shadow: 0 4px 12px rgba(99,102,241,.35);
  border-color: transparent; color: #fff;
}

.step-nav-info {
  display: flex; align-items: center; gap: 4px;
  font-size: 0.8rem; color: #94a3b8;
}
.step-num { color: #6366f1; font-weight: 700; }
.center-sep { color: #e2e8f0; }
</style>
