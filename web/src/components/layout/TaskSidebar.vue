<template>
  <div class="ts-panel">
    <!-- 顶部标题 -->
    <div class="ts-header">
      <i class="fas fa-layer-group ts-header-icon"></i>
      <span class="ts-header-title">任务与日志</span>
    </div>

    <div class="ts-body">
      <!-- ── 最近任务 ── -->
      <section class="ts-section">
        <div class="ts-section-head">
          <span class="ts-section-title">
            <i class="fas fa-history"></i> 最近任务
          </span>
          <button
            @click="refreshTasks"
            :disabled="taskStore.isLoadingTasks"
            class="ts-refresh-btn"
          >
            <i :class="taskStore.isLoadingTasks ? 'fas fa-spinner fa-spin' : 'fas fa-sync-alt'"></i>
          </button>
        </div>

        <div v-if="taskStore.recentTasks.length === 0" class="ts-empty">
          <i class="fas fa-inbox"></i>
          <span>暂无任务记录</span>
        </div>
        <template v-else>
          <div v-for="task in pagedTasks" :key="task.id" class="task-card">
            <div class="task-card-row">
              <span class="task-type">{{ getTaskTypeName(task.task_type) }}</span>
              <span class="task-badge" :class="getTaskStatusClass(task.status)">
                {{ getTaskStatusName(task.status) }}
              </span>
            </div>
            <div class="task-meta">
              {{ task.created_at ? new Date(task.created_at).toLocaleString('zh-CN',{dateStyle:'short',timeStyle:'short'}) : '' }}
              <span v-if="task.duration"> · {{ formatDuration(task.duration) }}</span>
            </div>
            <!-- 失败详情 -->
            <div v-if="task.status === 'failed'" class="task-error">
              <p class="task-error-msg">{{ task.error_message ? getShortError(task.error_message) : '任务执行失败' }}</p>
              <button @click="taskStore.toggleTaskDetail(task.id)" class="task-error-toggle">
                {{ taskStore.expandedTaskId === task.id ? '收起' : '查看详情' }}
              </button>
              <div v-if="taskStore.expandedTaskId === task.id" class="task-error-detail">
                {{ task.error_message || '未记录具体错误信息' }}
              </div>
            </div>
          </div>
          <div v-if="taskStore.recentTasks.length > PAGE" class="ts-pager">
            <button @click="taskPage = Math.max(0, taskPage - 1)" :disabled="taskPage === 0" class="pager-btn">
              <i class="fas fa-chevron-left"></i>
            </button>
            <span class="pager-info">{{ taskPage + 1 }} / {{ taskPageCount }}</span>
            <button @click="taskPage = Math.min(taskPageCount-1, taskPage+1)" :disabled="taskPage >= taskPageCount-1" class="pager-btn">
              <i class="fas fa-chevron-right"></i>
            </button>
          </div>
        </template>
      </section>

      <!-- ── 操作日志 ── -->
      <section class="ts-section">
        <div class="ts-section-head">
          <span class="ts-section-title">
            <i class="fas fa-clipboard-list"></i> 操作日志
          </span>
          <button
            @click="refreshLogs"
            :disabled="taskStore.isLoadingLogs"
            class="ts-refresh-btn"
          >
            <i :class="taskStore.isLoadingLogs ? 'fas fa-spinner fa-spin' : 'fas fa-sync-alt'"></i>
          </button>
        </div>

        <div v-if="taskStore.activityLogs.length === 0" class="ts-empty">
          <i class="fas fa-scroll"></i>
          <span>暂无操作记录</span>
        </div>
        <template v-else>
          <div v-for="log in pagedLogs" :key="log.id" class="log-card">
            <div class="log-card-row">
              <span class="log-dot" :class="getLogTypeClass(log.operation_type)"></span>
              <span class="log-op">{{ log.operation_type_display }}</span>
            </div>
            <p class="log-detail">{{ getLogDetail(log) }}</p>
            <p class="log-time">{{ log.created_at ? new Date(log.created_at).toLocaleString('zh-CN',{dateStyle:'short',timeStyle:'short'}) : '' }}</p>
          </div>
          <div v-if="taskStore.activityLogs.length > PAGE" class="ts-pager">
            <button @click="logPage = Math.max(0, logPage - 1)" :disabled="logPage === 0" class="pager-btn">
              <i class="fas fa-chevron-left"></i>
            </button>
            <span class="pager-info">{{ logPage + 1 }} / {{ logPageCount }}</span>
            <button @click="logPage = Math.min(logPageCount-1, logPage+1)" :disabled="logPage >= logPageCount-1" class="pager-btn">
              <i class="fas fa-chevron-right"></i>
            </button>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { useProjectStore } from '@/stores/project'
import {
  formatDuration, getTaskTypeName,
  getTaskStatusClass, getTaskStatusName,
  getLogTypeClass, getLogDetail, getShortError,
} from '@/utils/format'

const taskStore = useTaskStore()
const project = useProjectStore()

const PAGE = 5
const taskPage = ref(0)
const logPage = ref(0)

const taskPageCount = computed(() => Math.ceil(taskStore.recentTasks.length / PAGE) || 1)
const logPageCount = computed(() => Math.ceil(taskStore.activityLogs.length / PAGE) || 1)
const pagedTasks = computed(() => taskStore.recentTasks.slice(taskPage.value * PAGE, taskPage.value * PAGE + PAGE))
const pagedLogs = computed(() => taskStore.activityLogs.slice(logPage.value * PAGE, logPage.value * PAGE + PAGE))

function refreshTasks() {
  taskStore.fetchRecentTasks(project.currentProject?.id, project.stagesData)
}
function refreshLogs() {
  taskStore.fetchActivityLogs(project.currentProject?.id)
}
</script>

<style scoped>
.ts-panel {
  display: flex; flex-direction: column;
  height: 100%; overflow: hidden;
}

/* Header */
.ts-header {
  display: flex; align-items: center; gap: 8px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.ts-header-icon { color: #a5b4fc; font-size: 0.85rem; }
.ts-header-title { font-size: 0.85rem; font-weight: 600; color: #374151; }

/* Body */
.ts-body {
  flex: 1; overflow-y: auto;
  padding: 10px;
  display: flex; flex-direction: column; gap: 10px;
}

/* Section */
.ts-section {
  background: #fafafa;
  border: 1px solid #f1f5f9;
  border-radius: 10px;
  overflow: hidden;
}
.ts-section-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #f1f5f9;
}
.ts-section-title {
  font-size: 0.75rem; font-weight: 600; color: #374151;
}
.ts-section-title i { color: #a5b4fc; margin-right: 4px; }

.ts-refresh-btn {
  border: none; background: transparent;
  color: #a5b4fc; cursor: pointer;
  font-size: 0.7rem; padding: 2px 4px;
  border-radius: 4px; transition: all 0.15s;
}
.ts-refresh-btn:hover { color: #6366f1; background: #ede9fe; }
.ts-refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Empty */
.ts-empty {
  display: flex; flex-direction: column; align-items: center;
  padding: 1.5rem 1rem; gap: 6px;
  color: #cbd5e1; font-size: 0.75rem;
}
.ts-empty i { font-size: 1.25rem; }

/* Task card */
.task-card {
  padding: 9px 12px;
  border-bottom: 1px solid #f1f5f9;
}
.task-card:last-child { border-bottom: none; }
.task-card-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 6px;
}
.task-type { font-size: 0.78rem; font-weight: 500; color: #374151; }
.task-badge {
  font-size: 0.68rem; font-weight: 600;
  padding: 1px 7px; border-radius: 999px;
}
.task-meta { font-size: 0.7rem; color: #94a3b8; margin-top: 3px; }

.task-error { margin-top: 6px; }
.task-error-msg {
  font-size: 0.72rem; color: #e11d48;
  background: #fff1f2; border: 1px solid #fecdd3;
  padding: 4px 8px; border-radius: 6px; margin: 0 0 3px;
}
.task-error-toggle {
  font-size: 0.7rem; color: #e11d48; cursor: pointer;
  border: none; background: none; padding: 0; text-decoration: underline;
}
.task-error-detail {
  margin-top: 4px; font-size: 0.7rem; color: #dc2626;
  background: #fff; border: 1px solid #fecdd3;
  border-radius: 6px; padding: 6px 8px;
  max-height: 80px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-all;
}

/* Log card */
.log-card {
  padding: 8px 12px;
  border-bottom: 1px solid #f1f5f9;
}
.log-card:last-child { border-bottom: none; }
.log-card-row { display: flex; align-items: center; gap: 6px; }
.log-dot {
  width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
}
.log-op { font-size: 0.78rem; font-weight: 500; color: #374151; }
.log-detail { font-size: 0.72rem; color: #64748b; margin: 2px 0; }
.log-time { font-size: 0.68rem; color: #94a3b8; margin: 0; }

/* Pager */
.ts-pager {
  display: flex; align-items: center; justify-content: center;
  gap: 8px; padding: 8px 12px;
  border-top: 1px solid #f1f5f9;
}
.pager-btn {
  width: 24px; height: 24px;
  border: 1px solid #e2e8f0; border-radius: 6px;
  background: #fff; color: #64748b;
  cursor: pointer; font-size: 0.65rem;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.pager-btn:hover:not(:disabled) { border-color: #a5b4fc; color: #6366f1; }
.pager-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.pager-info { font-size: 0.7rem; color: #94a3b8; min-width: 40px; text-align: center; }
</style>
