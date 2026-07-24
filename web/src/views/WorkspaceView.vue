<template>
  <div class="page-layout">
    <!-- 左侧项目列表 -->
    <AppSidebar />

    <!-- 主内容区 -->
    <main class="main-content">
      <!-- 加载中 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner">
          <svg class="spin-icon" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        </div>
        <p class="loading-text">正在加载项目数据...</p>
      </div>

      <template v-else>
        <!-- 顶部 Header -->
        <div class="workspace-header">
          <div class="workspace-header-left">
            <div class="workspace-project-badge">
              <i class="fas fa-folder-open"></i>
            </div>
            <div>
              <h2 class="workspace-project-name">{{ project.currentProject?.name || '工作区' }}</h2>
              <p class="workspace-project-desc">
                {{ project.currentProject?.description || '暂无描述' }}
              </p>
            </div>
          </div>
        </div>

        <!-- 步骤指示器 -->
        <div class="step-indicator-wrap">
          <StepIndicator
            :steps="screen1Steps"
            :current-step="screening.currentStep"
            :stages-data="project.stagesData"
          />
        </div>

        <!-- 步骤内容 + 右侧任务栏 -->
        <div class="workspace-body">
          <div class="step-content-area">
            <StepParse    v-if="screening.currentStep === 1" />
            <StepDedup    v-else-if="screening.currentStep === 2" />
            <StepCriteria v-else-if="screening.currentStep === 3" />
            <StepFields   v-else-if="screening.currentStep === 4" />
            <StepAiScreen v-else-if="screening.currentStep === 5" />
            <StepExport   v-else-if="screening.currentStep === 6" />
            <!-- 步骤导航 -->
            <StepNav class="step-nav-bar" />
          </div>

          <!-- 右侧任务侧栏 -->
          <TaskSidebar class="task-sidebar" />
        </div>
      </template>
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
  { id: 6, name: '结果导出',  stepKey: 'export' },
]

onMounted(async () => {
  const projectId = Number(route.params.projectId)

  if (!project.currentProject || project.currentProject.id !== projectId) {
    await project.fetchProjects()
    const found = project.projects.find((p) => p.id === projectId)
    if (!found) {
      router.push('/')
      return
    }
    await project.selectProject(found)
  }

  await Promise.all([
    taskStore.fetchRecentTasks(projectId, project.stagesData),
    taskStore.fetchActivityLogs(projectId),
  ])

  loading.value = false
})
</script>

<style scoped>
.page-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: #f8fafc;
}
.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 加载状态 */
.loading-state {
  flex: 1;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 12px;
}
.loading-spinner {
  width: 40px; height: 40px;
  display: flex; align-items: center; justify-content: center;
}
.spin-icon {
  width: 32px; height: 32px; color: #6366f1;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { font-size: 0.875rem; color: #94a3b8; margin: 0; }

/* Header */
.workspace-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 24px 14px;
  border-bottom: 1px solid #f1f5f9;
  background: #fff;
  flex-shrink: 0;
}
.workspace-header-left {
  display: flex; align-items: center; gap: 12px;
}
.workspace-project-badge {
  width: 38px; height: 38px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.workspace-project-badge i { color: #fff; font-size: 0.95rem; }
.workspace-project-name {
  font-size: 1rem; font-weight: 700; color: #1e293b; margin: 0;
}
.workspace-project-desc {
  font-size: 0.75rem; color: #94a3b8; margin: 2px 0 0;
}

/* 步骤指示器区 */
.step-indicator-wrap {
  padding: 12px 24px;
  background: #fff;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}

/* 主体区 */
.workspace-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.step-content-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.step-nav-bar { margin-top: auto; padding-top: 16px; }

/* 任务侧栏 */
.task-sidebar {
  width: 288px;
  min-width: 288px;
  border-left: 1px solid #f1f5f9;
  background: #fff;
  overflow-y: auto;
  flex-shrink: 0;
}
</style>
