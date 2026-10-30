<template>
  <div class="rs-workspace">
    <div v-if="ws.state.loading" class="rs-loading">
      <i class="fas fa-spinner fa-spin"></i>正在加载复筛工作区…
    </div>
    <template v-else-if="ws.state.info">
      <nav class="ws-step-bar" aria-label="全文复筛步骤">
        <div class="step-indicator">
          <template v-for="(name, index) in STEPS" :key="name">
            <button
              class="step-node"
              :class="
                ws.state.step === index + 1
                  ? 'step-node-active'
                  : ws.state.info.steps[index].completed
                    ? 'step-node-done'
                    : 'step-node-idle'
              "
              :disabled="!ws.state.info.steps[index].enabled"
              :aria-current="ws.state.step === index + 1 ? 'step' : undefined"
              @click="navigate(index + 1)"
            >
              <span class="step-node-num"><i
                v-if="
                  ws.state.info.steps[index].completed &&
                    ws.state.step !== index + 1
                "
                class="fas fa-check step-check-icon"
              ></i><span v-else>{{ index + 1 }}</span></span><span class="step-node-label">{{ name }}</span>
            </button>
            <div
              v-if="index < STEPS.length - 1"
              class="step-line"
              :class="{
                'step-line-done': ws.state.info.steps[index].completed,
              }"
            ></div>
          </template>
        </div>
      </nav>
      <div class="ws-body">
        <div class="ws-step-wrap">
          <div
            class="rs-workspace-body"
            :class="{ 'rescreen-review-mode': ws.state.step === 5 }"
          >
            <div v-if="ws.state.error" class="rs-alert danger" role="alert">
              {{ ws.state.error
              }}<button aria-label="关闭错误提示" @click="ws.state.error = ''">
                ×
              </button>
            </div>
            <div v-if="ws.state.notice" class="rs-alert success" role="status">
              {{ ws.state.notice
              }}<button aria-label="关闭提示" @click="ws.state.notice = ''">
                ×
              </button>
            </div>
            <div v-if="ws.state.info.busy" class="rs-alert">
              后台有复筛任务正在处理，状态会自动更新。审核和输入变更暂时锁定，但可以查看文献与已有结果。
            </div>
            <component
              :is="components[ws.state.step - 1]"
              :key="ws.state.step"
              v-bind="ws.state.step === 4 ? { canPrompt } : {}"
            />
          </div>
          <footer class="ws-step-footer">
            <div class="step-nav">
              <button
                class="nav-btn nav-prev"
                :disabled="ws.state.step === 1"
                @click="navigate(ws.state.step - 1)"
              >
                <i class="fas fa-arrow-left"></i>上一步
              </button>
              <div class="step-nav-info">
                第 <span class="step-num">{{ ws.state.step }}</span> 步 / 共 6
                步<span class="center-sep">·</span>{{ footerTip
                }}<span v-if="ws.state.working"> · 正在处理…</span>
              </div>
              <button
                class="nav-btn nav-next"
                :disabled="
                  ws.state.step !== 6 &&
                    !ws.state.info.steps[ws.state.step]?.enabled
                "
                @click="
                  ws.state.step === 6
                    ? goQuality()
                    : navigate(ws.state.step + 1)
                "
              >
                {{ ws.state.step === 6 ? '前往质量评价' : '下一步'
                }}<i class="fas fa-arrow-right"></i>
              </button>
            </div>
          </footer>
        </div>
        <aside
          class="ws-task-sidebar"
          :class="{ 'ws-task-sidebar--collapsed': sidebarCollapsed }"
        >
          <button
            v-if="sidebarCollapsed"
            class="ws-sidebar-expand-btn"
            aria-label="展开任务与日志"
            @click="sidebarCollapsed = false"
          >
            <i class="fas fa-chevron-left"></i><span>任务</span>
          </button>
          <TaskSidebar v-else @toggle="sidebarCollapsed = true" />
        </aside>
      </div>
    </template>
    <div v-else class="rs-empty">
      <p>{{ ws.state.error || '无法加载复筛工作区。' }}</p>
      <button @click="ws.initialize(projectId)">重新加载</button>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, onMounted, onBeforeUnmount, provide, watch } from 'vue'
import {
  useRoute,
  useRouter,
  onBeforeRouteLeave,
  onBeforeRouteUpdate,
} from 'vue-router'
import { useAuthStore } from '@/features/account/store'
import { createRescreenWorkspace } from '../useWorkspace'
import { STEPS, stepNumber, emptyPage } from '../state'
import RescreenUpload from './RescreenUpload.vue'
import RescreenFulltext from './RescreenFulltext.vue'
import RescreenCriteria from './RescreenCriteria.vue'
import RescreenAI from './RescreenAI.vue'
import RescreenReview from './RescreenReview.vue'
import RescreenExport from './RescreenExport.vue'
import TaskSidebar from '@/shared/components/TaskSidebar.vue'
import '../workspace.css'
const props = defineProps({ projectId: { type: Number, required: true } })
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ws = createRescreenWorkspace()
const sidebarCollapsed = ref(false)
const footerTip = computed(() => {
  const counts = ws.state.info?.counts || {}
  if (ws.state.step === 1) return `已形成 ${counts.total || 0} 条复筛文献记录`
  if (ws.state.step === 2)
    return `已绑定 ${counts.bound ?? counts.ready ?? 0} 篇，未绑定 ${counts.missing ?? 0} 篇`
  if (ws.state.step === 3)
    return `已保存 ${ws.state.info?.configuration.criteria.length || 0} 条排除标准`
  if (ws.state.step === 4)
    return `全文就绪 ${counts.ready || 0} 篇，本次已选 ${ws.state.selected.length} 篇`
  if (ws.state.step === 5)
    return `已最终确认 ${counts.finalized || 0} / ${counts.total || 0} 篇`
  return `纳入 ${counts.included || 0} 篇，排除 ${counts.excluded || 0} 篇，全文未获取 ${counts.not_retrieved || 0} 篇`
})
provide('rescreen', ws)
const components = [
  RescreenUpload,
  RescreenFulltext,
  RescreenCriteria,
  RescreenAI,
  RescreenReview,
  RescreenExport,
]
const canPrompt = computed(
  () => auth.canConfigureScreeningPrompt && ws.state.info?.capabilities.prompt,
)
const dirty = () =>
  ws.state.dirty ||
  ws.state.reviewDirty ||
  ws.state.promptDirty ||
  ws.state.modelDirty
function confirmLeave() {
  return !dirty() || window.confirm('当前存在未保存修改，确定离开此步骤？')
}
async function navigate(index) {
  if (!ws.state.info.steps.find((step) => step.index === index)?.enabled) return
  await router.replace({
    query: { ...route.query, stage: 'SCREEN_2', rescreen_step: index },
  })
}
watch(
  () => props.projectId,
  (id) => ws.initialize(id, route.query.rescreen_step),
  { immediate: true },
)
watch(
  () => route.query.rescreen_step,
  async (value) => {
    if (!ws.state.info) return
    const next = stepNumber(value, ws.state.info)
    if (ws.state.step === next) return
    ws.state.step = next
    ws.state.selected = []
    ws.clearReference()
    ws.state.refs = emptyPage()
    ws.state.filters = { q: '', status: next === 4 ? 'ready' : '' }
    await ws.read(() => ws.loadReferences(1))
  },
)
onBeforeRouteLeave(() => confirmLeave())
function goQuality() {
  return router.push({
    query: { ...route.query, stage: 'QUALITY', rescreen_step: undefined },
  })
}
onBeforeRouteUpdate((to, from) =>
  to.query.rescreen_step !== from.query.rescreen_step ||
  to.query.stage !== from.query.stage
    ? confirmLeave()
    : true,
)
function beforeUnload(event) {
  if (dirty()) {
    event.preventDefault()
    event.returnValue = ''
  }
}
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  ws.dispose()
})
</script>
<style scoped>
.ws-step-bar {
  padding: 10px 24px;
  background: #fff;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
  overflow-x: auto;
}

/* 内容 + 任务栏 */
.ws-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}
/* step 内容区外层：上方可滚动内容区 + 下方固定页脚 */
.ws-step-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ws-step-footer {
  flex-shrink: 0;
  padding: 0 24px;
  border-top: 1px solid #f1f5f9;
  background: #fff;
}

.ws-task-sidebar {
  width: 280px;
  min-width: 280px;
  border-left: 1px solid #f1f5f9;
  background: #fff;
  overflow-y: auto;
  flex-shrink: 0;
  transition:
    width 0.2s ease,
    min-width 0.2s ease;
}
.ws-task-sidebar--collapsed {
  width: 36px;
  min-width: 36px;
  overflow: hidden;
}

/* 收起时显示的展开按钮 */
.ws-sidebar-expand-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border: none;
  background: transparent;
  cursor: pointer;
  color: #a5b4fc;
  gap: 6px;
  transition: color 0.15s;
}
.ws-sidebar-expand-btn:hover {
  color: #6366f1;
  background: #f5f3ff;
}
.step-indicator {
  display: flex;
  align-items: center;
  gap: 0;
  overflow-x: auto;
}
.step-node {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border-radius: 999px;
  border: none;
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 500;
  white-space: nowrap;
  transition: all 0.2s;
  position: relative;
  flex-shrink: 0;
}
.step-node-num {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 700;
  flex-shrink: 0;
}
.step-check-icon {
  font-size: 0.65rem;
}
.step-node-label {
  font-size: 0.8rem;
}
.step-node-active {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
}
.step-node-active .step-node-num {
  background: rgba(255, 255, 255, 0.25);
  color: #fff;
}
.step-node-done {
  background: #ecfdf5;
  color: #059669;
}
.step-node-done:hover {
  background: #d1fae5;
}
.step-node-done .step-node-num {
  background: #10b981;
  color: #fff;
}
.step-node-idle {
  background: transparent;
  color: #64748b;
  cursor: default;
}
.step-node-idle .step-node-num {
  background: #e2e8f0;
  color: #64748b;
}
.step-line {
  flex: 1;
  min-width: 8px;
  max-width: 28px;
  height: 2px;
  background: #e2e8f0;
  border-radius: 999px;
  flex-shrink: 0;
}
.step-line-done {
  background: linear-gradient(90deg, #10b981, #6366f1);
}

.step-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
}
.nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 18px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s;
  background: #fff;
  color: #374151;
}
.nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.nav-btn:hover:not(:disabled) {
  border-color: #a5b4fc;
  color: #6366f1;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.12);
}
.nav-next {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  border-color: transparent;
}
.nav-next:hover:not(:disabled) {
  opacity: 0.9;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
  color: #fff;
}
.step-nav-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.8rem;
  color: #94a3b8;
}
.step-num {
  color: #6366f1;
  font-weight: 700;
}
.center-sep {
  color: #e2e8f0;
}

.rs-workspace-body {
  display: flex;
  flex-direction: column;
  padding: 20px 24px;
  min-height: 0;
}
.rs-workspace-body.rescreen-review-mode {
  overflow: hidden;
}
.rescreen-review-mode > .rescreen-review {
  flex: 1;
  min-height: 0;
}
.ws-task-sidebar :deep(button) {
  font-weight: inherit;
}
.step-node-idle:not(:disabled) {
  cursor: pointer;
}
.step-nav-info {
  min-width: 0;
  flex-wrap: wrap;
  justify-content: center;
}
.ws-sidebar-expand-btn span {
  writing-mode: vertical-rl;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .ws-task-sidebar:not(.ws-task-sidebar--collapsed) {
    width: 240px;
    min-width: 240px;
  }
  .step-nav-info {
    font-size: 0.7rem;
  }
}
@media (max-width: 900px) {
  .ws-task-sidebar {
    display: none;
  }
  .rs-workspace-body.rescreen-review-mode {
    overflow: auto;
  }
  .step-nav-info {
    display: none;
  }
  .rs-workspace-body {
    padding: 16px;
  }
}
</style>
