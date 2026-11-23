<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#10b981,#34d399)">
        <i class="fas fa-list-check"></i>
      </div>
      <div>
        <h3 class="step-title">设定排除标准</h3>
        <p class="step-subtitle">
          定义文献在初筛阶段应被排除的条件
          <button class="ml-2 text-xs text-indigo-500 hover:text-indigo-700 underline" @click="showGuide = true">
            <i class="fas fa-lightbulb mr-0.5"></i>查看撰写指南
          </button>
        </p>
      </div>
    </div>

    <ExclusionCriteriaPresets :model-value="s.criteriaList" @toggle="togglePreset" />

    <!-- 自定义输入 -->
    <div class="flex space-x-2 mb-4">
      <input
        v-model="newCriteria"
        type="text"
        placeholder="自定义：输入一条标准并回车"
        class="flex-1 px-4 py-2.5 input-base"
        @keyup.enter="addCriteria"
      />
      <button class="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700" @click="addCriteria">
        <i class="fas fa-plus"></i> 添加
      </button>
    </div>

    <!-- 标准列表 -->
    <div class="step-list-box" style="min-height:200px;max-height:400px">
      <div v-if="s.criteriaList.length === 0" class="h-full flex flex-col items-center justify-center text-gray-400 py-8">
        <i class="fas fa-clipboard-list text-3xl mb-2 opacity-50"></i>
        <p>暂无标准，请在上方添加</p>
      </div>
      <div v-else class="space-y-2">
        <div
          v-for="(c, idx) in s.criteriaList"
          :key="idx"
          class="step-list-item group"
        >
          <span class="text-gray-700">
            <span class="font-bold text-green-600 mr-2">{{ idx + 1 }}.</span>{{ c }}
          </span>
          <button
            class="text-gray-300 hover:text-red-500 transition opacity-0 group-hover:opacity-100"
            @click="removeCriteria(idx)"
          >
            <i class="fas fa-trash-alt"></i>
          </button>
        </div>
      </div>
    </div>

    <ExclusionCriteriaGuide v-model="showGuide" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import ExclusionCriteriaGuide from '@/shared/components/ExclusionCriteriaGuide.vue'
import ExclusionCriteriaPresets from '@/shared/components/ExclusionCriteriaPresets.vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'
import * as workflowApi from '@/shared/api/workflow'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const newCriteria = ref('')
const showGuide = ref(false)



async function saveCriteria() {
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'criteria')
  if (!step) return
  try {
    const criteria = [...s.criteriaList]
    const metadataResponse = await workflowApi.updateStepMetadata(step.id, { criteria })
    project.replaceStep(metadataResponse.data)
    // 有排除标准时，将步骤标记为 completed
    if (criteria.length > 0 && step.status !== 'completed') {
      const completeResponse = await workflowApi.completeStep(step.id)
      project.replaceStep(completeResponse.data)
    }
  } catch (err) {
    console.error('保存排除标准失败', err)
  }
}

async function addCriteria() {
  const val = newCriteria.value.trim()
  if (!val) return
  s.criteriaList.push(val)
  newCriteria.value = ''
  await saveCriteria()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function removeCriteria(idx) {
  s.criteriaList.splice(idx, 1)
  await saveCriteria()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function togglePreset(preset) {
  const idx = s.criteriaList.indexOf(preset)
  if (idx === -1) {
    s.criteriaList.push(preset)
  } else {
    s.criteriaList.splice(idx, 1)
  }
  await saveCriteria()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function loadCriteria() {
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'criteria')
  s.criteriaList = [...(step?.metadata?.criteria || [])]
}

onMounted(loadCriteria)
</script>
