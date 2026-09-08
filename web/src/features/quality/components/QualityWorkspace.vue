<template>
  <component :is="currentStepComponent" />
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useQAStore } from '@/features/quality/store'
import { useProjectStore } from '@/features/projects/store'
import QAStepUpload   from '@/features/quality/components/QAStepUpload.vue'
import QAStepMethod   from '@/features/quality/components/QAStepMethod.vue'
import QAStepAiEval   from '@/features/quality/components/QAStepAiEval.vue'
import QAStepReview   from '@/features/quality/components/QAStepReview.vue'
import QAStepChart    from '@/features/quality/components/QAStepChart.vue'
import QAStepExport   from '@/features/quality/components/QAStepExport.vue'
import { inferQualityMaxStep } from '@/features/projects/workspaceNavigation'

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
  qa.maxReachedStep = inferQualityMaxStep(qa.refs)
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
