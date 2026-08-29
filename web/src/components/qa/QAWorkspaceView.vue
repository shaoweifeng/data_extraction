<template>
  <div class="qa-workspace">
    <!-- 步骤进度条 -->
    <div class="qa-steps-bar">
      <div
        v-for="(step, idx) in steps"
        :key="step.key"
        :class="['qa-step', {
          active:     qa.currentStep === step.index,
          completed:  step.index <= maxReachedStep && qa.currentStep !== step.index,
          reachable:  step.index <= maxReachedStep && qa.currentStep !== step.index,
        }]"
        @click="jumpTo(step.index)"
      >
        <div class="step-circle">
          <i class="fas fa-check" v-if="step.index <= maxReachedStep && qa.currentStep !== step.index"></i>
          <span v-else>{{ step.index }}</span>
        </div>
        <span class="step-label">{{ step.label }}</span>
        <div class="step-connector" v-if="idx < steps.length - 1"></div>
      </div>
    </div>

    <!-- 步骤内容 -->
    <div class="qa-step-content">
      <component :is="currentStepComponent" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
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
  { index: 1, key: 'upload',  label: '上传文献',     component: QAStepUpload },
  { index: 2, key: 'method',  label: '方法选择',     component: QAStepMethod },
  { index: 3, key: 'ai_eval', label: 'AI 质量评价', component: QAStepAiEval },
  { index: 4, key: 'review',  label: '结果审核',     component: QAStepReview },
  { index: 5, key: 'chart',   label: '结果可视化',  component: QAStepChart },
  { index: 6, key: 'export',  label: '导出报告',     component: QAStepExport },
]

// 高水位：记录该项目曾经到达过的最高步骤
const maxReachedStep = ref(1)

const currentStepComponent = computed(() =>
  steps.find(s => s.index === qa.currentStep)?.component || QAStepUpload
)

// 根据后端数据推断已解锁的最高步骤
function inferMaxStep(refs) {
  if (!refs || refs.length === 0) return 1
  // 有文献 → 至少到步骤 2
  let max = 2
  // 有文献选了评价方法 → 至少到步骤 3
  if (refs.some(r => r.quality_method)) max = 3
  // 有文献完成了 AI 评价 → 至少到步骤 4
  if (refs.some(r => ['completed', 'abstract_only', 'failed'].includes(r.ai_eval_status))) max = 4
  // 有文献有人工确认记录 → 至少到步骤 5
  if (refs.some(r => r.review_status === 'confirmed' || r.review_status === 'partial')) max = 5
  return max
}

// 跳转到指定步骤（仅允许已解锁的步骤）
function jumpTo(index) {
  if (index > maxReachedStep.value) return
  qa.currentStep = index
  // 向前走时更新高水位
  if (index > maxReachedStep.value) maxReachedStep.value = index
}

// 监听 currentStep 变化，实时更新高水位
watch(() => qa.currentStep, (newStep) => {
  if (newStep > maxReachedStep.value) {
    maxReachedStep.value = newStep
  }
})

// 初始化：拉取当前项目数据，确保隔离
async function initForProject(projectId) {
  if (!projectId) return
  qa.refs          = []
  qa.currentRef    = null
  qa.signalItems   = []
  qa.domainResults = []
  qa.evalProgress  = null
  qa.chartData     = null
  qa.currentStep   = 1
  maxReachedStep.value = 1
  qa.stopPolling()

  // 拉取文献后推断高水位，允许直接跳到已完成的步骤
  await qa.fetchRefs(projectId)
  maxReachedStep.value = inferMaxStep(qa.refs)
  // 直接跳到之前执行到的最新步骤
  qa.currentStep = maxReachedStep.value
}

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

<style scoped>
.qa-workspace {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 0;
  height: 100%;
}

/* 步骤进度条 */
.qa-steps-bar {
  display: flex;
  align-items: center;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 14px 24px;
  gap: 0;
  flex-shrink: 0;
}

.qa-step {
  display: flex;
  align-items: center;
  flex: 1;
  position: relative;
}

.qa-step.reachable {
  cursor: pointer;
}
.qa-step.reachable:hover .step-circle {
  border-color: #6366f1;
  color: #6366f1;
}
.qa-step.reachable:hover .step-label {
  color: #6366f1;
}

.step-circle {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #f1f5f9;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
  font-weight: 600;
  flex-shrink: 0;
  transition: all 0.2s;
  border: 2px solid #e2e8f0;
}

.qa-step.active .step-circle {
  background: #6366f1;
  color: #fff;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99,102,241,.2);
}

.qa-step.completed .step-circle {
  background: #10b981;
  color: #fff;
  border-color: #10b981;
}

.step-label {
  margin-left: 8px;
  font-size: 0.78rem;
  color: #94a3b8;
  white-space: nowrap;
  transition: color 0.2s;
}

.qa-step.active .step-label  { color: #6366f1; font-weight: 600; }
.qa-step.completed .step-label { color: #10b981; }

.step-connector {
  flex: 1;
  height: 2px;
  background: #e2e8f0;
  margin: 0 8px;
  transition: background 0.2s;
}

.qa-step.completed + .qa-step .step-connector,
.qa-step.completed .step-connector {
  background: #a7f3d0;
}

/* 内容区 */
.qa-step-content {
  flex: 1;
  overflow-y: auto;
  background: #f8fafc;
  border-radius: 14px;
  padding: 20px;
}
</style>
