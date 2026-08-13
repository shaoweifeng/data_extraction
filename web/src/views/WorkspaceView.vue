<template>
  <div class="page-layout">
    <!-- 统一顶部导航（贯穿全页面顶部） -->
    <AppHeader />

    <!-- 下方主体：侧边栏 + 内容区 -->
    <div class="page-body">
      <AppSidebar />

      <main class="main-content">
        <!-- 加载中 -->
        <div v-if="loading" class="loading-state">
          <i class="fas fa-spinner fa-spin" style="font-size:1.4rem;color:#a5b4fc"></i>
          <p>正在加载项目数据...</p>
        </div>

        <template v-else>
          <!-- ── SCREEN_1：文献初筛（含步骤指示器）── -->
          <template v-if="project.currentStage === 'SCREEN_1'">
            <!-- 步骤指示器 -->
            <div class="ws-step-bar">
              <StepIndicator
                :steps="screen1Steps"
                :current-step="screening.currentStep"
                :stages-data="project.stagesData"
              />
            </div>
            <!-- 步骤内容 + 右侧任务栏 -->
            <div class="ws-body">
              <div class="ws-step-wrap">
                <div class="ws-step-content" :class="{ 'review-mode': screening.currentStep === 6 }">
                  <StepParse    v-if="screening.currentStep === 1" />
                  <StepDedup    v-else-if="screening.currentStep === 2" />
                  <StepCriteria v-else-if="screening.currentStep === 3" />
                  <StepFields   v-else-if="screening.currentStep === 4" />
                  <StepAiScreen v-else-if="screening.currentStep === 5" />
                  <StepReview   v-else-if="screening.currentStep === 6" />
                  <StepExport   v-else-if="screening.currentStep === 7" />
                </div>
                <div class="ws-step-footer">
                  <StepNav />
                </div>
              </div>
              <TaskSidebar class="ws-task-sidebar" />
            </div>
          </template>

          <!-- ── 其他阶段：占位页 ── -->
          <template v-else>
            <div class="ws-placeholder">
              <div class="placeholder-icon" :style="{ background: stageMeta[project.currentStage]?.bg || '#f1f5f9' }">
                <i :class="stageMeta[project.currentStage]?.icon || 'fas fa-tools'" :style="{ color: stageMeta[project.currentStage]?.color || '#6366f1' }"></i>
              </div>
              <h2 class="placeholder-title">{{ stageMeta[project.currentStage]?.name || project.currentStage }}</h2>
              <p class="placeholder-desc">该功能模块正在建设中，敬请期待。</p>
              <div class="placeholder-tag">Coming Soon</div>
            </div>
          </template>
        </template>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useScreeningStore } from '@/stores/screening'
import { useTaskStore } from '@/stores/task'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import TaskSidebar from '@/components/layout/TaskSidebar.vue'
import StepIndicator from '@/components/common/StepIndicator.vue'
import StepNav from '@/components/common/StepNav.vue'
import StepParse from '@/components/steps/StepParse.vue'
import StepDedup from '@/components/steps/StepDedup.vue'
import StepCriteria from '@/components/steps/StepCriteria.vue'
import StepFields from '@/components/steps/StepFields.vue'
import StepAiScreen from '@/components/steps/StepAiScreen.vue'
import StepReview from '@/components/steps/StepReview.vue'
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
  { id: 4, name: '提取字段',  stepKey: 'field_extraction' },
  { id: 5, name: 'AI 初筛',   stepKey: 'ai_screen' },
  { id: 6, name: '人工审阅',  stepKey: 'review' },
  { id: 7, name: '结果导出',  stepKey: 'export' },
]

const stageMeta = {
  SEARCH:   { name: '文献检索',   icon: 'fas fa-search',       bg: '#eff6ff', color: '#3b82f6' },
  SCREEN_2: { name: '文献复筛',   icon: 'fas fa-tasks',        bg: '#faf5ff', color: '#8b5cf6' },
  QUALITY:  { name: '文献质量评价', icon: 'fas fa-shield-virus', bg: '#f0fdf4', color: '#10b981' },
  EXTRACT:  { name: '数据提取',   icon: 'fas fa-file-export',  bg: '#fff7ed', color: '#f59e0b' },
  META:     { name: 'Meta 分析',  icon: 'fas fa-chart-line',  bg: '#fdf2f8', color: '#ec4899' },
}

onMounted(async () => {
  const projectId = Number(route.params.projectId)

  if (!project.currentProject || project.currentProject.id !== projectId) {
    await project.fetchProjects()
    const found = project.projects.find((p) => p.id === projectId)
    if (!found) { router.push('/'); return }
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
/* 整体布局：顶部固定 header + 下方左右分栏 */
.page-layout {
  height: 100vh; overflow: hidden; background: #f8fafc;
  display: flex; flex-direction: column;
}
.page-body {
  flex: 1; display: flex; overflow: hidden; min-height: 0;
}
.main-content {
  flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden;
}

/* 加载 */
.loading-state {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px; color: #94a3b8;
  font-size: 0.85rem;
}

/* 步骤指示器条 */
.ws-step-bar {
  padding: 10px 24px;
  background: #fff; border-bottom: 1px solid #f1f5f9; flex-shrink: 0;
  overflow-x: auto;
}

/* 内容 + 任务栏 */
.ws-body {
  flex: 1; display: flex; overflow: hidden; min-height: 0;
}
/* step 内容区外层：上方可滚动内容区 + 下方固定页脚 */
.ws-step-wrap {
  flex: 1; min-width: 0; min-height: 0;
  display: flex; flex-direction: column; overflow: hidden;
}
.ws-step-content {
  flex: 1; overflow-y: auto; padding: 20px 24px;
  min-width: 0; min-height: 0; display: flex; flex-direction: column;
}
/* step 6 (人工审阅) 不用 padding，让 StepReview 自己擑满 */
.ws-step-content.review-mode {
  padding: 0;
  overflow: hidden;
}
.ws-step-footer {
  flex-shrink: 0;
  padding: 0 24px;
  border-top: 1px solid #f1f5f9;
  background: #fff;
}

.ws-task-sidebar {
  width: 280px; min-width: 280px;
  border-left: 1px solid #f1f5f9;
  background: #fff; overflow-y: auto; flex-shrink: 0;
}

/* 占位页 */
.ws-placeholder {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 12px;
  padding: 4rem 2rem; text-align: center;
}
.placeholder-icon {
  width: 80px; height: 80px; border-radius: 22px;
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 4px;
}
.placeholder-icon i { font-size: 2rem; }
.placeholder-title { font-size: 1.3rem; font-weight: 700; color: #1e293b; margin: 0; }
.placeholder-desc { font-size: 0.875rem; color: #94a3b8; margin: 0; max-width: 320px; }
.placeholder-tag {
  display: inline-flex; padding: 4px 14px;
  background: #ede9fe; color: #7c3aed;
  border-radius: 999px; font-size: 0.75rem; font-weight: 600;
  margin-top: 4px;
}
</style>
