/**
 * stores/task.js
 * 任务列表 / 操作日志状态
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '@/api/http'
import { extractListData } from '@/utils/format'

export const useTaskStore = defineStore('task', () => {
  const recentTasks = ref([])
  const latestAiScreenTask = ref(null)
  const isLoadingTasks = ref(false)
  const taskPage = ref(0)

  const expandedTaskId = ref(null)
  const taskLogs = ref({}) // { [taskId]: logData }

  const activityLogs = ref([])
  const isLoadingLogs = ref(false)
  const logPage = ref(0)

  async function fetchRecentTasks(projectId, stagesData) {
    if (!projectId) return
    isLoadingTasks.value = true
    try {
      const res = await http.get(`/tasks/?project=${projectId}`)
      const tasks = extractListData(res.data).filter((t) => t.status !== 'superseded')
      recentTasks.value = tasks.slice(0, 10)

      const aiTask = tasks.find((t) => t.task_type === 'ai_screen')
      if (aiTask) latestAiScreenTask.value = aiTask

      return { tasks, aiTask }
    } catch (err) {
      console.error('获取任务列表失败', err)
    } finally {
      isLoadingTasks.value = false
    }
  }

  async function toggleTaskDetail(taskId) {
    if (expandedTaskId.value === taskId) {
      expandedTaskId.value = null
    } else {
      expandedTaskId.value = taskId
      if (!taskLogs.value[taskId]) {
        try {
          const res = await http.get(`/tasks/${taskId}/logs/`)
          taskLogs.value = { ...taskLogs.value, [taskId]: res.data }
        } catch (err) {
          console.error('获取日志失败', err)
        }
      }
    }
  }

  function getLogDisplay(task) {
    const cached = taskLogs.value[task.id]
    if (!cached) return '加载中...'
    if (cached.error) return `错误: ${cached.error}`
    return cached.log_content || '暂无日志'
  }

  async function fetchActivityLogs(projectId) {
    if (!projectId) return
    isLoadingLogs.value = true
    try {
      const res = await http.get(`/activity-logs/?project=${projectId}&page=${logPage.value + 1}`)
      const data = res.data
      if (logPage.value === 0) {
        activityLogs.value = extractListData(data)
      } else {
        activityLogs.value.push(...extractListData(data))
      }
      if (data.next) logPage.value++
    } catch (err) {
      console.error('获取操作日志失败', err)
    } finally {
      isLoadingLogs.value = false
    }
  }

  function reset() {
    recentTasks.value = []
    latestAiScreenTask.value = null
    taskPage.value = 0
    expandedTaskId.value = null
    taskLogs.value = {}
    activityLogs.value = []
    logPage.value = 0
  }

  return {
    recentTasks,
    latestAiScreenTask,
    isLoadingTasks,
    taskPage,
    expandedTaskId,
    taskLogs,
    activityLogs,
    isLoadingLogs,
    logPage,
    fetchRecentTasks,
    toggleTaskDetail,
    getLogDisplay,
    fetchActivityLogs,
    reset,
  }
})
