<template>
  <div class="flex h-screen bg-gray-50">
    <!-- 左侧项目列表 -->
    <AppSidebar />

    <!-- 主内容区 -->
    <main class="flex-1 flex overflow-hidden">
      <!-- 步骤内容 -->
      <div class="flex-1 overflow-auto p-6">
        <!-- 加载中 -->
        <div v-if="loading" class="flex items-center justify-center h-64">
          <div class="flex items-center gap-3 text-gray-400">
            <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            <span>加载项目数据...</span>
          </div>
        </div>

        <template v-else>
          <!-- 项目名 + 步骤指示器 -->
          <div class="mb-6">
            <h2 class="text-lg font-semibold text-gray-800 mb-3">
              {{ project.currentProject?.name || '工作区' }}
            </h2>
            <StepIndicator
              :steps="screen1Steps"
              :current-step="screening.currentStep"
              :stages-data="project.stagesData"
            />
          </div>

          <!-- 步骤内容区 -->
          <StepParse    v-if="screening.currentStep === 1" />
          <StepDedup    v-else-if="screening.currentStep === 2" />
          <StepCriteria v-else-if="screening.currentStep === 3" />
          <StepFields   v-else-if="screening.currentStep === 4" />
          <StepAiScreen v-else-if="screening.currentStep === 5" />
          <StepExport   v-else-if="screening.currentStep === 6" />

          <!-- 步骤导航 -->
          <StepNav class="mt-6" />
        </template>
      </div>

      <!-- 右侧任务状态栏 -->
      <TaskSidebar class="w-80 border-l border-gray-200 overflow-auto bg-white" />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
const router = useRouter()
const project = useProjectStore()
const screening = useScreeningStore()
const taskStore = useTaskStore()

const loading = ref(true)

const screen1Steps = [
  { id: 1, name: '文献解析',  stepKey: 'parse' },
  { id: 2, name: '自动去重',  stepKey: 'dedup' },
  { id: 3, name: '纳排标准',  stepKey: 'criteria' },
  { id: 4, name: '提取字段',  stepKey: 'extraction_fields' },
  { id: 5, name: 'AI 初筛',   stepKey: 'ai_screen' },
  { id: 6, name: '结果归纳',  stepKey: 'export' },
]

onMounted(async () => {
  const projectId = Number(route.params.projectId)

  // 如果 URL 直接进入（刷新或分享链接），需要先加载项目列表
  if (!project.currentProject || project.currentProject.id !== projectId) {
    await project.fetchProjects()
    const found = project.projects.find((p) => p.id === projectId)
    if (!found) {
      router.push('/')
      return
    }
    await project.selectProject(found)
  }

  // 并行加载任务 & 日志
  await Promise.all([
    taskStore.fetchRecentTasks(projectId, project.stagesData),
    taskStore.fetchActivityLogs(projectId),
  ])

  loading.value = false
})
</script>
