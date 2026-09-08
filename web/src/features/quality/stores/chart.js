import { ref } from 'vue'
import * as qualityApi from '../api'
import * as workflowApi from '@/shared/api/workflow'
import { pollUntil } from '@/shared/composables/usePolling'
import { downloadBlob } from '@/shared/composables/useDownload'

export function createChartCapability() {
  const chartData = ref(null)
  const chartLoading = ref(false)
  const chartPreviewLoading = ref(false)
  const chartOrientation = ref('horizontal')
  const chartLang = ref('zh')
  const exportStatus = ref(null)
  let chartAbortController = null

  async function previewChart(projectId, qualityMethod, refIds = []) {
    chartPreviewLoading.value = true
    try {
      const response = await qualityApi.previewChart({ project_id: projectId, quality_method: qualityMethod, ref_ids: refIds })
      chartData.value = response.data.data
      return chartData.value
    } finally {
      chartPreviewLoading.value = false
    }
  }

  async function generateChart(projectId, qualityMethod, refIds = [], studyLabels = {}, orientation = 'horizontal', lang = 'zh') {
    chartAbortController?.abort()
    const controller = new AbortController()
    chartAbortController = controller
    chartLoading.value = true
    try {
      const response = await qualityApi.generateChart({ project_id: projectId, quality_method: qualityMethod, ref_ids: refIds, study_labels: studyLabels, orientation, lang })
      const taskId = response.data.data?.task_id
      if (!taskId) throw new Error('服务端未返回图表任务 ID')
      const task = await pollUntil(
        async () => (await workflowApi.fetchTask(taskId)).data,
        result => ['completed', 'failed', 'stopped', 'superseded'].includes(result.status),
        { interval: 750, maxAttempts: 400, timeoutMessage: '图表生成超时，请稍后重试', signal: controller.signal },
      )
      if (task.status !== 'completed') throw new Error(task.error_message || '图表生成任务未完成')
      if (!task.result) throw new Error('图表生成任务未返回结果')
      chartData.value = task.result
      try { sessionStorage.setItem(`qa_chart_${projectId}_${qualityMethod}`, JSON.stringify(task.result)) } catch { /* ignore */ }
      return chartData.value
    } finally {
      if (chartAbortController === controller) {
        chartAbortController = null
        chartLoading.value = false
      }
    }
  }

  function cancelChartGeneration() {
    chartAbortController?.abort()
    chartAbortController = null
    chartLoading.value = false
  }

  async function fetchChartInfo(projectId, qualityMethod = 'QUADAS2') {
    try {
      const cached = sessionStorage.getItem(`qa_chart_${projectId}_${qualityMethod}`)
      if (cached) {
        chartData.value = JSON.parse(cached)
        return chartData.value
      }
    } catch { /* fall through */ }
    const response = await qualityApi.fetchChartInfo(projectId, qualityMethod)
    if (response.data.data && chartData.value) chartData.value = { ...chartData.value, ...response.data.data }
    return response.data.data
  }

  async function exportExcel(projectId, qualityMethod = 'QUADAS2', includeUnconfirmed = false) {
    const response = await qualityApi.exportExcel({ project_id: projectId, quality_method: qualityMethod, include_unconfirmed: includeUnconfirmed })
    downloadBlob(response.data, `qa_export_${qualityMethod}_${new Date().toISOString().slice(0, 10)}.xlsx`)
  }

  async function fetchChartSettings(projectId, qualityMethod) {
    try {
      const response = await qualityApi.fetchChartSettings(projectId, qualityMethod)
      return response.data.data?.study_labels || {}
    } catch { return {} }
  }

  async function saveChartSettings(projectId, qualityMethod, studyLabels) {
    try {
      await qualityApi.saveChartSettings({ project_id: projectId, quality_method: qualityMethod, study_labels: studyLabels })
    } catch (error) { console.warn('保存图表设置失败', error) }
  }

  function resetChart() {
    cancelChartGeneration()
    chartData.value = null
    chartOrientation.value = 'horizontal'
    chartLang.value = 'zh'
    exportStatus.value = null
  }

  return { chartData, chartLoading, chartPreviewLoading, chartOrientation, chartLang, exportStatus, previewChart, generateChart, cancelChartGeneration, fetchChartInfo, exportExcel, fetchChartSettings, saveChartSettings, resetChart }
}
