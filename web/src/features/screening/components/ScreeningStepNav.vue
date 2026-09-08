<template>
  <div class="step-nav">
    <button
      v-if="screening.currentStep > 1"
      @click="screening.currentStep--"
      class="nav-btn nav-prev"
    >
      <i class="fas fa-arrow-left"></i>
      <span>上一步</span>
    </button>
    <div v-else></div>

    <div class="step-nav-info">
      第 <span class="step-num">{{ screening.currentStep }}</span> 步 / 共 7 步
    </div>

    <button
      v-if="screening.currentStep < 7"
      @click="handleNext"
      :disabled="nextLoading"
      class="nav-btn nav-next"
    >
      <i v-if="nextLoading" class="fas fa-spinner fa-spin"></i>
      <span>下一步</span>
      <i v-if="!nextLoading" class="fas fa-arrow-right"></i>
    </button>
    <div v-else></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import * as screeningApi from '@/features/screening/api'

const screening = useScreeningStore()
const project   = useProjectStore()

const nextLoading = ref(false)

async function handleNext() {
  // 第 6 步（人工审阅）：先调 complete API 把步骤标记为 completed，再跳步
  if (screening.currentStep === 6) {
    nextLoading.value = true
    try {
      const stage = project.stagesData?.find(s => s.stage_key === 'SCREEN_1')
      const reviewStep = stage?.steps?.find(s => s.step_key === 'review')
      if (reviewStep) {
        await screeningApi.completeReview(project.currentProject?.id, reviewStep.id)
        // 刷新 stagesData，让步骤指示器变绿
        await project.fetchStages(project.currentProject?.id)
      }
    } catch (e) {
      console.error('[StepNav] review complete 失败', e)
    } finally {
      nextLoading.value = false
    }
  }
  screening.currentStep++
}
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
  font-size: 0.8rem; color: #94a3b8;
}
.step-num {
  color: #6366f1; font-weight: 700;
}
</style>
