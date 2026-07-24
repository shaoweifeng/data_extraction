<template>
  <div class="flex h-screen bg-gray-50">
    <!-- 左侧项目列表 -->
    <AppSidebar />

    <!-- 主内容区 -->
    <main class="flex-1 flex overflow-hidden">
      <!-- 步骤内容（占大部分宽度） -->
      <div class="flex-1 overflow-auto p-6">
        <!-- 加载中 -->
        <div v-if="loading" class="flex items-center justify-center h-64">
          <div class="text-gray-400">加载项目数据...</div>
        </div>

        <template v-else>
          <!-- 步骤指示器 -->
          <StepIndicator
            :steps="screen1Steps"
            :current-step="screening.currentStep"
            :stages-data="project.stagesData"
          />

          <!-- 步骤内容区 -->
          <div class="mt-6">
            <StepParse    v-if="screening.currentStep === 1" />
            <StepDedup    v-else-if="screening.currentStep === 2" />
            <StepCriteria v-else-if="screening.currentStep === 3" />
            <StepFields   v-else-if="screening.currentStep === 4" />
            <StepAiScreen v-else-if="screening.currentStep === 5" />
            <StepExport   v-else-if="screening.currentStep === 6" />
          </div>

          <!-- 步骤导航按钮 -->
          <StepNav class="mt-6" />
        </template>
      </div>

      <!-- 右侧任务状态栏 -->
      <TaskSidebar class="w-80 border-l border-gray-200 overflow-auto" />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useScreeningStore } from '@/stores/screening'
import { useTaskStore } from '@/stores/task'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import TaskSidebar from '@/components/layout/TaskSidebar.vue'
import StepIndicator from '@/components/common/StepIndicator.vue'
import StepNav from '@/components/common/StepNav.vue'
import StepParse from '@/components/steps/StepParse.vue'
import StepDedup from '@/components/steps/StepDedup.vue'
import StepCriteria from '@/components/steps/StepCriteria.vue'
import StepFields from '@/components/steps/StepFields.vue'
import StepAiScreen from '@/components/steps/StepAiScreen.vue'
import StepExport from '@/components/steps/StepExport.vue'

const route = useRoute()
const project = useProjectStore()
const screening = useScreeningStore()
const taskStore = useTaskStore()

const loading = ref(true)

// 步骤配置（与原 index.html screen1Steps 一致）
const screen1Steps = [
  { id: 1, name: '文献解析', stepKey: 'parse' },
  { id: 2, name: '自动去重', stepKey: 'dedup' },
  { id: 3, name: '纳排标准', stepKey: 'criteria' },
  { id: 4, name: '提取字段', stepKey: 'extraction_fields' },
  { id: 5, name: 'AI 初筛', stepKey: 'ai_screen' },
  { id: 6, name: '结果归纳', stepKey: 'export' },
]

onMounted(async () => {
  const projectId = Number(route.params.projectId)

  // 如果当前 project store 没有数据（直接通过 URL 进入），先加载项目列表
  if (!project.currentProject || project.currentProject.id !== projectId) {
    await project.fetchProjects()
    const found = project.projects.find((p) => p.id === projectId)
    if (found) {
      await project.selectProject(found)
    }
  }

  // 加载任务 & 日志
  await Promise.all([
    taskStore.fetchRecentTasks(projectId, project.stagesData),
    taskStore.fetchActivityLogs(projectId),
  ])

  loading.value = false
})
</script>
