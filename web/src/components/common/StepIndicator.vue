<template>
  <div class="flex items-center gap-1 flex-wrap">
    <template v-for="(step, idx) in steps" :key="step.id">
      <div class="flex items-center gap-1">
        <div
          @click="handleStepClick(step, idx)"
          :class="[
            'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer',
            getStepClass(step, idx),
          ]"
        >
          <span>{{ idx + 1 }}</span>
          <span>{{ step.name }}</span>
          <span v-if="getStepStatus(step) === 'completed'" class="text-green-600">✓</span>
          <span v-else-if="getStepStatus(step) === 'running'" class="text-blue-600 animate-pulse">●</span>
        </div>
        <span v-if="idx < steps.length - 1" class="text-gray-300 text-xs">→</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { useScreeningStore } from '@/stores/screening'
import { useProjectStore } from '@/stores/project'

const props = defineProps({
  steps: { type: Array, required: true },
  currentStep: { type: Number, required: true },
  stagesData: { type: Array, default: () => [] },
})

const screening = useScreeningStore()
const project = useProjectStore()

function getStepObj(step) {
  const stage = props.stagesData.find((s) => s.stage_key === 'SCREEN_1')
  return stage?.steps.find((s) => s.step_key === step.stepKey)
}

function getStepStatus(step) {
  return getStepObj(step)?.status || 'pending'
}

function getStepClass(step, idx) {
  const stepNum = idx + 1
  const status = getStepStatus(step)

  // 当前步骤高亮（用户点击的）
  if (props.currentStep === stepNum) {
    return 'bg-blue-600 text-white shadow-sm'
  }
  if (status === 'completed') return 'bg-green-100 text-green-700 hover:bg-green-200'
  if (status === 'running') return 'bg-blue-100 text-blue-700'
  if (status === 'failed') return 'bg-red-100 text-red-700'
  if (status === 'skipped') return 'bg-gray-100 text-gray-500'
  return 'bg-gray-100 text-gray-600 hover:bg-gray-200'
}

function handleStepClick(step, idx) {
  screening.currentStep = idx + 1
}
</script>
