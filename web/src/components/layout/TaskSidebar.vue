<template>
  <div class="flex flex-col h-full">
    <div class="p-3 border-b border-gray-100">
      <h3 class="text-sm font-semibold text-gray-600 flex items-center gap-1.5">
        <i class="fas fa-layer-group text-gray-400"></i>
        任务与日志
      </h3>
    </div>

    <div class="flex-1 overflow-auto p-3 space-y-3">
      <!-- 最近任务 -->
      <div class="bg-gray-50 rounded-xl border p-3">
        <div class="flex items-center justify-between mb-2">
          <h4 class="font-semibold text-gray-700 text-sm">
            <i class="fas fa-history mr-1"></i>最近任务
          </h4>
          <button
            @click="refreshTasks"
            :disabled="taskStore.isLoadingTasks"
            class="text-xs text-blue-600 hover:underline disabled:opacity-50"
          >
            <i :class="taskStore.isLoadingTasks ? 'fas fa-spinner fa-spin' : 'fas fa-sync-alt'"></i> 刷新
          </button>
        </div>

        <div class="space-y-1">
          <div v-if="taskStore.recentTasks.length === 0" class="text-xs text-gray-400 text-center py-3">
            暂无任务记录
          </div>
          <template v-else>
            <div
              v-for="task in pagedTasks"
              :key="task.id"
              class="px-2 py-1.5 bg-white rounded border text-xs"
            >
              <div class="flex items-center justify-between">
                <span class="font-medium text-gray-700 truncate mr-1">{{ getTaskTypeName(task.task_type) }}</span>
                <span
                  class="px-1.5 py-0.5 rounded-full text-xs flex-shrink-0"
                  :class="getTaskStatusClass(task.status)"
                >{{ getTaskStatusName(task.status) }}</span>
              </div>
              <div class="text-gray-400 mt-0.5">
                {{ task.created_at ? new Date(task.created_at).toLocaleString() : '' }}
                <span v-if="task.duration" class="ml-1">· {{ formatDuration(task.duration) }}</span>
              </div>
              <!-- 失败详情 -->
              <div v-if="task.status === 'failed'" class="mt-1">
                <div class="bg-red-50 border border-red-200 rounded px-2 py-1">
                  <div class="text-red-600 text-xs">
                    {{ task.error_message ? getShortError(task.error_message) : '任务执行失败' }}
                  </div>
                  <button
                    @click="taskStore.toggleTaskDetail(task.id)"
                    class="text-xs text-red-500 hover:text-red-700 underline"
                  >{{ taskStore.expandedTaskId === task.id ? '收起' : '查看详情' }}</button>
                  <div
                    v-if="taskStore.expandedTaskId === task.id"
                    class="mt-1 text-xs text-red-700 bg-white p-1 rounded max-h-24 overflow-y-auto whitespace-pre-wrap break-words"
                  >{{ task.error_message || '未记录具体错误信息' }}</div>
                </div>
              </div>
            </div>

            <!-- 分页 -->
            <div v-if="taskStore.recentTasks.length > 5" class="flex items-center justify-between pt-1">
              <button
                @click="taskPage = Math.max(0, taskPage - 1)"
                :disabled="taskPage === 0"
                class="text-xs text-gray-500 disabled:opacity-30 hover:text-gray-700"
              ><i class="fas fa-chevron-left"></i></button>
              <span class="text-xs text-gray-400">{{ taskPage + 1 }} / {{ taskPageCount }}</span>
              <button
                @click="taskPage = Math.min(taskPageCount - 1, taskPage + 1)"
                :disabled="taskPage >= taskPageCount - 1"
                class="text-xs text-gray-500 disabled:opacity-30 hover:text-gray-700"
              ><i class="fas fa-chevron-right"></i></button>
            </div>
          </template>
        </div>
      </div>

      <!-- 操作日志 -->
      <div class="bg-gray-50 rounded-xl border p-3">
        <div class="flex items-center justify-between mb-2">
          <h4 class="font-semibold text-gray-700 text-sm">
            <i class="fas fa-clipboard-list mr-1"></i>操作日志
          </h4>
          <button
            @click="refreshLogs"
            :disabled="taskStore.isLoadingLogs"
            class="text-xs text-blue-600 hover:underline disabled:opacity-50"
          >
            <i :class="taskStore.isLoadingLogs ? 'fas fa-spinner fa-spin' : 'fas fa-sync-alt'"></i> 刷新
          </button>
        </div>

        <div class="space-y-1">
          <div v-if="taskStore.activityLogs.length === 0" class="text-xs text-gray-400 text-center py-3">
            暂无操作记录
          </div>
          <template v-else>
            <div
              v-for="log in pagedLogs"
              :key="log.id"
              class="px-2 py-1.5 bg-white rounded border text-xs"
            >
              <div class="flex items-center gap-1">
                <span :class="getLogTypeClass(log.operation_type)" class="w-1.5 h-1.5 rounded-full flex-shrink-0"></span>
                <span class="font-medium text-gray-700">{{ log.operation_type_display }}</span>
              </div>
              <div class="text-gray-500 mt-0.5 truncate">{{ getLogDetail(log) }}</div>
              <div class="text-gray-400 mt-0.5">
                {{ log.created_at ? new Date(log.created_at).toLocaleString() : '' }}
              </div>
            </div>

            <!-- 分页 -->
            <div v-if="taskStore.activityLogs.length > 5" class="flex items-center justify-between pt-1">
              <button
                @click="logPage = Math.max(0, logPage - 1)"
                :disabled="logPage === 0"
                class="text-xs text-gray-500 disabled:opacity-30 hover:text-gray-700"
              ><i class="fas fa-chevron-left"></i></button>
              <span class="text-xs text-gray-400">{{ logPage + 1 }} / {{ logPageCount }}</span>
              <button
                @click="logPage = Math.min(logPageCount - 1, logPage + 1)"
                :disabled="logPage >= logPageCount - 1"
                class="text-xs text-gray-500 disabled:opacity-30 hover:text-gray-700"
              ><i class="fas fa-chevron-right"></i></button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { useProjectStore } from '@/stores/project'
import {
  formatDuration,
  getTaskTypeName,
  getTaskStatusClass,
  getTaskStatusName,
  getLogTypeClass,
  getLogDetail,
  getShortError,
} from '@/utils/format'

const taskStore = useTaskStore()
const project = useProjectStore()

const taskPage = ref(0)
const logPage = ref(0)

const taskPageCount = computed(() => Math.ceil(taskStore.recentTasks.length / 5) || 1)
const logPageCount = computed(() => Math.ceil(taskStore.activityLogs.length / 5) || 1)

const pagedTasks = computed(() =>
  taskStore.recentTasks.slice(taskPage.value * 5, taskPage.value * 5 + 5),
)
const pagedLogs = computed(() =>
  taskStore.activityLogs.slice(logPage.value * 5, logPage.value * 5 + 5),
)

function refreshTasks() {
  taskStore.fetchRecentTasks(project.currentProject?.id, project.stagesData)
}

function refreshLogs() {
  taskStore.fetchActivityLogs(project.currentProject?.id)
}
</script>
