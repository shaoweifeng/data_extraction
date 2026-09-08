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
                @select="screening.currentStep = $event"
              />
            </div>
            <!-- 步骤内容 + 右侧任务栏 -->
            <div class="ws-body" :key="`screen-${project.currentProject?.id}`">
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
              <div class="ws-task-sidebar" :class="{ 'ws-task-sidebar--collapsed': sidebarCollapsed }">
                <!-- 收起时只显示展开按钮 -->
                <button v-if="sidebarCollapsed" class="ws-sidebar-expand-btn" @click="sidebarCollapsed = false" title="展开任务面板">
                  <i class="fas fa-chevron-left"></i>
                  <span class="ws-sidebar-expand-label">任务</span>
                </button>
                <TaskSidebar v-else @toggle="sidebarCollapsed = true" />
              </div>
            </div>
          </template>

          <!-- ── QUALITY：文献质量评价 ── -->
          <template v-else-if="project.currentStage === 'QUALITY'">
            <!-- 步骤指示器（与 SCREEN_1 完全一致的容器 + 组件） -->
            <div class="ws-step-bar">
              <div class="step-indicator">
                <template v-for="(step, idx) in qaSteps" :key="step.key">
                  <button
                    :class="['step-node', getQANodeClass(step)]"
                    @click="jumpToQAStep(step.index)"
                  >
                    <span class="step-node-num">
                      <i v-if="step.index < qa.maxReachedStep && qa.currentStep !== step.index" class="fas fa-check step-check-icon"></i>
                      <span v-else>{{ step.index }}</span>
                    </span>
                    <span class="step-node-label">{{ step.label }}</span>
                  </button>
                  <div
                    v-if="idx < qaSteps.length - 1"
                    :class="['step-line', step.index < qa.maxReachedStep ? 'step-line-done' : '']"
                  ></div>
                </template>
              </div>
            </div>
            <div class="ws-body">
              <div class="ws-step-wrap">
                <div class="ws-step-content" :class="{ 'qa-review-mode': qa.currentStep === 4 }">
                  <QAWorkspaceView />
                </div>
                <!-- 固定底部页脚，与 SCREEN_1 完全一致的结构 -->
                <div class="ws-step-footer">
                  <QAStepNav :next-disabled="qaNextDisabled">
                    <template #center>
                      <span class="qa-footer-tip" v-if="qaFooterTip">{{ qaFooterTip }}</span>
                    </template>
                  </QAStepNav>
                </div>
              </div>
              <div class="ws-task-sidebar" :class="{ 'ws-task-sidebar--collapsed': qaSidebarCollapsed }">
                <button v-if="qaSidebarCollapsed" class="ws-sidebar-expand-btn" @click="qaSidebarCollapsed = false" title="展开任务面板">
                  <i class="fas fa-chevron-left"></i>
                  <span class="ws-sidebar-expand-label">任务</span>
                </button>
                <TaskSidebar v-else @toggle="qaSidebarCollapsed = true" />
              </div>
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
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '@/features/projects/store'
import { useScreeningStore } from '@/features/screening/store'
import { useTaskStore } from '@/features/workflow/store'
import AppHeader from '@/shared/components/AppHeader.vue'
import AppSidebar from '@/shared/components/AppSidebar.vue'
import TaskSidebar from '@/shared/components/TaskSidebar.vue'
import StepIndicator from '@/shared/components/WorkflowStepIndicator.vue'
import StepNav from '@/features/screening/components/ScreeningStepNav.vue'
import StepParse from '@/features/screening/components/steps/StepParse.vue'
import StepDedup from '@/features/screening/components/steps/StepDedup.vue'
import StepCriteria from '@/features/screening/components/steps/StepCriteria.vue'
import StepFields from '@/features/screening/components/steps/StepFields.vue'
import StepAiScreen from '@/features/screening/components/steps/StepAiScreen.vue'
import StepReview from '@/features/screening/components/steps/StepReview.vue'
import StepExport from '@/features/screening/components/steps/StepExport.vue'
import QAWorkspaceView from '@/features/quality/components/QualityWorkspace.vue'
import QAStepNav from '@/features/quality/components/QAStepNav.vue'
import { useQAStore } from '@/features/quality/store'
import {
  SCREENING_STEPS,
  QUALITY_STEPS,
  isQualityNextDisabled,
  qualityFooterTip,
} from '@/features/projects/workspaceNavigation'

const route = useRoute()
const router = useRouter()
const project = useProjectStore()
const screening = useScreeningStore()
const taskStore = useTaskStore()
const qa = useQAStore()

const loading = ref(true)
const sidebarCollapsed = ref(false)
const qaSidebarCollapsed = ref(false)

// QA 页脚：下一步禁用条件 + 中间提示文字
const qaNextDisabled = computed(() => isQualityNextDisabled(qa.currentStep, qa.refs, qa.evalCompleted))
const qaFooterTip = computed(() => qualityFooterTip(qa.currentStep, qa.refs))
const screen1Steps = SCREENING_STEPS
const qaSteps = QUALITY_STEPS

function getQANodeClass(step) {
  if (qa.currentStep === step.index) return 'step-node-active'
  if (step.index <= qa.maxReachedStep) return 'step-node-done'
  return 'step-node-idle'
}

function jumpToQAStep(index) {
  if (index > qa.maxReachedStep) return
  qa.currentStep = index
}

const stageMeta = {
  SEARCH:   { name: '文献检索',   icon: 'fas fa-search',       bg: '#eff6ff', color: '#3b82f6' },
  SCREEN_2: { name: '文献复筛',   icon: 'fas fa-tasks',        bg: '#faf5ff', color: '#8b5cf6' },
  QUALITY:  { name: '文献质量评价', icon: 'fas fa-shield-virus', bg: '#f0fdf4', color: '#10b981' },
  EXTRACT:  { name: '数据提取',   icon: 'fas fa-file-export',  bg: '#fff7ed', color: '#f59e0b' },
  META:     { name: 'Meta 分析',  icon: 'fas fa-chart-line',  bg: '#fdf2f8', color: '#ec4899' },
}

let workspaceGeneration = 0

async function initializeWorkspace(projectId) {
  const generation = ++workspaceGeneration
  loading.value = true

  if (!project.currentProject || project.currentProject.id !== projectId) {
    await project.fetchProjects()
    if (generation !== workspaceGeneration) return
    const found = project.projects.find((p) => p.id === projectId)
    if (!found) { router.push('/'); return }
    // 切换项目时先清空所有项目级状态，防止旧项目数据短暂显示。
    screening.reset()
    taskStore.reset()
    qa.reset()
    await project.selectProject(found)
    if (generation !== workspaceGeneration || project.currentProject?.id !== projectId) return
  }

  await Promise.all([
    taskStore.fetchRecentTasks(projectId, project.stagesData),
    taskStore.fetchActivityLogs(projectId),
  ])
  if (generation !== workspaceGeneration || project.currentProject?.id !== projectId) return
  loading.value = false
}

watch(
  () => Number(route.params.projectId),
  projectId => initializeWorkspace(projectId),
  { immediate: true },
)
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
/* QA 结果审核步骤：内部三栏自己管理滚动，外层不滚动 */
.ws-step-content.qa-review-mode {
  overflow: hidden;
  padding: 20px 24px;
}


.ws-task-sidebar {
  width: 280px; min-width: 280px;
  border-left: 1px solid #f1f5f9;
  background: #fff; overflow-y: auto; flex-shrink: 0;
  transition: width 0.2s ease, min-width 0.2s ease;
}
.ws-task-sidebar--collapsed {
  width: 36px; min-width: 36px;
  overflow: hidden;
}

/* 收起时显示的展开按钮 */
.ws-sidebar-expand-btn {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  width: 100%; height: 100%;
  border: none; background: transparent; cursor: pointer;
  color: #a5b4fc; gap: 6px;
  transition: color 0.15s;
}
.ws-sidebar-expand-btn:hover { color: #6366f1; background: #f5f3ff; }
.ws-sidebar-expand-label {
  writing-mode: vertical-rl;
  font-size: 0.72rem; font-weight: 600; color: inherit; letter-spacing: 0.05em;
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

/* ── QA 步骤条（与 StepIndicator.vue 样式完全一致）── */
.step-indicator {
  display: flex; align-items: center; gap: 0; overflow-x: auto;
}
.step-node {
  display: flex; align-items: center; gap: 7px;
  padding: 6px 12px; border-radius: 999px; border: none;
  cursor: pointer; font-size: 0.8rem; font-weight: 500;
  white-space: nowrap; transition: all 0.2s;
  position: relative; flex-shrink: 0;
}
.step-node-num {
  width: 20px; height: 20px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; font-weight: 700; flex-shrink: 0;
}
.step-check-icon { font-size: 0.65rem; }
.step-node-label { font-size: 0.8rem; }
.step-node-active {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff; box-shadow: 0 4px 12px rgba(99,102,241,.35);
}
.step-node-active .step-node-num { background: rgba(255,255,255,0.25); color: #fff; }
.step-node-done { background: #ecfdf5; color: #059669; }
.step-node-done:hover { background: #d1fae5; }
.step-node-done .step-node-num { background: #10b981; color: #fff; }
.step-node-idle { background: transparent; color: #64748b; cursor: default; }
.step-node-idle .step-node-num { background: #e2e8f0; color: #64748b; }
.step-line {
  flex: 1; min-width: 8px; max-width: 28px; height: 2px;
  background: #e2e8f0; border-radius: 999px; flex-shrink: 0;
}
.step-line-done { background: linear-gradient(90deg, #10b981, #6366f1); }
</style>
