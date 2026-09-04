<template>
  <component :is="currentStepComponent" />
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useQAStore } from '@/stores/qa'
import { useProjectStore } from '@/stores/project'
import QAStepUpload   from '@/components/qa/QAStepUpload.vue'
import QAStepMethod   from '@/components/qa/QAStepMethod.vue'
import QAStepAiEval   from '@/components/qa/QAStepAiEval.vue'
import QAStepReview   from '@/components/qa/QAStepReview.vue'
import QAStepChart    from '@/components/qa/QAStepChart.vue'
import QAStepExport   from '@/components/qa/QAStepExport.vue'

const qa      = useQAStore()
const project = useProjectStore()

const steps = [
  { index: 1, component: QAStepUpload },
  { index: 2, component: QAStepMethod },
  { index: 3, component: QAStepAiEval },
  { index: 4, component: QAStepReview },
  { index: 5, component: QAStepChart },
  { index: 6, component: QAStepExport },
]

const currentStepComponent = computed(() =>
  steps.find(s => s.index === qa.currentStep)?.component || QAStepUpload
)

// 根据后端数据推断已解锁的最高步骤
function inferMaxStep(refs) {
  if (!refs || refs.length === 0) return 1
  let max = 2
  if (refs.some(r => r.quality_method)) max = 3
  if (refs.some(r => ['completed', 'abstract_only', 'failed'].includes(r.ai_eval_status))) max = 4
  if (refs.some(r => r.review_status === 'confirmed' || r.review_status === 'partial')) max = 5
  return max
}

// 初始化：拉取当前项目数据
async function initForProject(projectId) {
  if (!projectId) return
  qa.refs          = []
  qa.currentRef    = null
  qa.signalItems   = []
  qa.domainResults = []
  qa.evalProgress  = null
  qa.chartData     = null
  qa.currentStep   = 1
  qa.maxReachedStep = 1
  qa.stopPolling()

  await qa.fetchRefs(projectId)
  qa.maxReachedStep = inferMaxStep(qa.refs)
  qa.currentStep    = qa.maxReachedStep
}

// 监听 currentStep 变化，更新高水位
watch(() => qa.currentStep, (newStep) => {
  if (newStep > qa.maxReachedStep) {
    qa.maxReachedStep = newStep
  }
})

onMounted(async () => {
  if (project.currentProject) {
    await initForProject(project.currentProject.id)
  }
})

watch(
  () => project.currentProject?.id,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      initForProject(newId)
    }
  }
)

onUnmounted(() => {
  qa.stopPolling()
})
</script>
