/**
 * stores/qa.js
 * 文献质量评价模块全局状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import http from '@/api/http'

export const useQAStore = defineStore('qa', () => {
  // ── 步骤导航 ─────────────────────────────────────────────
  const currentStep    = ref(1)  // 1~6
  const maxReachedStep = ref(1)  // 高水位，已解锁的最大步骤

  // ── 文献列表（Step1/2/3共用）────────────────────────────
  const refs = ref([])
  const refsLoading = ref(false)

  // ── 当前选中文献（Step4/5）─────────────────────────────
  const currentRef = ref(null)
  const signalItems = ref([])
  const domainResults = ref([])
  const signalLoading = ref(false)

  // ── AI 评价进度（Step3）────────────────────────────────
  const evalProgress = ref(null)
  const evalPollingTimer = ref(null)

  // ── 图表数据（Step5）───────────────────────────────────
  const chartData = ref(null)
  const chartLoading = ref(false)
  const chartPreviewLoading = ref(false)

  // ── 导出状态（Step6）───────────────────────────────────
  const exportStatus = ref(null)

  // ── 质量评价方法列表 ────────────────────────────────────
  const methods = ref([])

  // ── 计算属性 ─────────────────────────────────────────────
  const confirmedRefs = computed(() => refs.value.filter(r => r.review_status === 'confirmed'))
  const pendingRefs   = computed(() => refs.value.filter(r => !r.quality_method))
  const totalRefs     = computed(() => refs.value.length)
  const evalCompleted = computed(() => {
    if (!evalProgress.value) return false
    const s = evalProgress.value.summary
    return s && s.running === 0 && (s.completed + s.failed) > 0
  })

  // ── 方法 ─────────────────────────────────────────────────

  async function fetchMethods() {
    if (methods.value.length) return
    try {
      const res = await http.get('/qa/methods/')
      methods.value = res.data.data || []
    } catch (e) {
      console.warn('[QA] fetchMethods failed', e)
    }
  }

  async function fetchRefs(projectId) {
    if (!projectId) return
    refsLoading.value = true
    try {
      const res = await http.get('/qa/refs/', { params: { project_id: projectId } })
      refs.value = res.data.data || []
    } catch (e) {
      console.warn('[QA] fetchRefs failed', e)
    } finally {
      refsLoading.value = false
    }
  }

  async function importFromScreening(projectId, sourceStage = 'SCREEN_1') {
    const res = await http.post('/qa/refs/import/', { project_id: projectId, source_stage: sourceStage })
    return res.data.data
  }

  async function uploadFulltext(projectId, files) {
    const form = new FormData()
    form.append('project_id', projectId)
    files.forEach(f => form.append('files', f))
    const res = await http.post('/qa/refs/upload/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data.data
  }

  async function updateRef(refId, payload) {
    const res = await http.patch(`/qa/refs/${refId}/`, payload)
    const updated = res.data.data
    const idx = refs.value.findIndex(r => r.id === refId)
    if (idx !== -1) refs.value[idx] = updated
    return updated
  }

  async function batchSetMethod(refIds, qualityMethod) {
    const res = await http.post('/qa/refs/batch-method/', { ref_ids: refIds, quality_method: qualityMethod })
    // 更新本地
    refIds.forEach(id => {
      const idx = refs.value.findIndex(r => r.id === id)
      if (idx !== -1) refs.value[idx].quality_method = qualityMethod
    })
    return res.data.data
  }

  async function startEval(projectId, refIds, evalMode, modelIds) {
    const res = await http.post('/qa/eval/start/', {
      project_id: projectId,
      ref_ids: refIds,
      eval_mode: evalMode,
      model_ids: modelIds,
    })
    return res.data.data
  }

  async function fetchEvalProgress(projectId) {
    const res = await http.get('/qa/eval/progress/', { params: { project_id: projectId } })
    evalProgress.value = res.data.data
    // 同步 refs 状态
    if (evalProgress.value?.refs) {
      evalProgress.value.refs.forEach(pr => {
        const idx = refs.value.findIndex(r => r.id === pr.id)
        if (idx !== -1) {
          refs.value[idx].ai_eval_status = pr.ai_eval_status
          refs.value[idx].review_status  = pr.review_status
        }
      })
    }
    return evalProgress.value
  }

  function startPollingProgress(projectId) {
    if (evalPollingTimer.value) clearInterval(evalPollingTimer.value)
    evalPollingTimer.value = setInterval(async () => {
      await fetchEvalProgress(projectId)
      if (evalCompleted.value) {
        clearInterval(evalPollingTimer.value)
        evalPollingTimer.value = null
      }
    }, 5000)
  }

  function stopPolling() {
    if (evalPollingTimer.value) {
      clearInterval(evalPollingTimer.value)
      evalPollingTimer.value = null
    }
  }

  async function selectRef(ref) {
    currentRef.value = ref
    await fetchSignalItems(ref.id)
    await fetchDomainResults(ref.id)
  }

  async function fetchSignalItems(qaRefId, filters = {}) {
    signalLoading.value = true
    try {
      const res = await http.get('/qa/signal-items/', { params: { qa_ref_id: qaRefId, ...filters } })
      signalItems.value = res.data.data || []
    } finally {
      signalLoading.value = false
    }
  }

  async function fetchDomainResults(qaRefId) {
    const res = await http.get('/qa/domain-results/', { params: { qa_ref_id: qaRefId } })
    domainResults.value = res.data.data || []
  }

  async function confirmSignalItem(itemId, humanJudgment) {
    const res = await http.patch(`/qa/signal-items/${itemId}/confirm/`, { human_judgment: humanJudgment })
    const updated = res.data.data
    const idx = signalItems.value.findIndex(i => i.id === itemId)
    if (idx !== -1) signalItems.value[idx] = updated
    // 刷新领域结果
    if (currentRef.value) await fetchDomainResults(currentRef.value.id)

    // 同步 refs 里该文献的 review_status
    if (currentRef.value) {
      const total     = signalItems.value.length
      const confirmed = signalItems.value.filter(i => i.is_confirmed).length
      const newStatus = total === 0 ? 'not_started'
        : confirmed === total ? 'confirmed'
        : confirmed > 0       ? 'partial'
        : 'not_started'

      const refIdx = refs.value.findIndex(r => r.id === currentRef.value.id)
      if (refIdx !== -1) refs.value[refIdx] = { ...refs.value[refIdx], review_status: newStatus }
      currentRef.value = { ...currentRef.value, review_status: newStatus }
    }

    return updated
  }

  async function batchConfirm(qaRefId, confirmMode = 'adopt_preselected', signalKeys = []) {
    const res = await http.post('/qa/signal-items/batch-confirm/', {
      qa_ref_id: qaRefId,
      confirm_mode: confirmMode,
      signal_keys: signalKeys,
    })
    // 刷新信号问题列表
    await fetchSignalItems(qaRefId)
    if (currentRef.value) await fetchDomainResults(currentRef.value.id)

    // 根据刷新后的 signalItems 同步更新 qa.refs 里该文献的 review_status
    // 与后端 _recalc_domain_results 逻辑保持一致
    const total     = signalItems.value.length
    const confirmed = signalItems.value.filter(i => i.is_confirmed).length
    const newStatus = total === 0 ? 'not_started'
      : confirmed === total ? 'confirmed'
      : confirmed > 0       ? 'partial'
      : 'not_started'

    const idx = refs.value.findIndex(r => r.id === qaRefId)
    if (idx !== -1) refs.value[idx] = { ...refs.value[idx], review_status: newStatus }
    if (currentRef.value?.id === qaRefId) {
      currentRef.value = { ...currentRef.value, review_status: newStatus }
    }

    return res.data.data
  }

  async function previewChart(projectId, qualityMethod, refIds = []) {
    chartPreviewLoading.value = true
    try {
      const res = await http.post('/qa/chart/preview/', {
        project_id: projectId,
        quality_method: qualityMethod,
        ref_ids: refIds,
      })
      // preview 不含图片，但结构与 chartData 兼容
      chartData.value = res.data.data
      return chartData.value
    } finally {
      chartPreviewLoading.value = false
    }
  }

  async function generateChart(projectId, qualityMethod, refIds = [], studyLabels = {}, orientation = 'horizontal') {
    chartLoading.value = true
    try {
      const res = await http.post('/qa/chart/generate/', {
        project_id: projectId,
        quality_method: qualityMethod,
        ref_ids: refIds,
        study_labels: studyLabels,
        orientation,
      })
      chartData.value = res.data.data
      // 缓存到 sessionStorage，刷新后可恢复（key 带 projectId 隔离）
      try {
        sessionStorage.setItem(
          `qa_chart_${projectId}_${qualityMethod}`,
          JSON.stringify(res.data.data)
        )
      } catch (e) { /* storage 满时忽略 */ }
      return chartData.value
    } finally {
      chartLoading.value = false
    }
  }

  async function fetchChartInfo(projectId, qualityMethod = 'QUADAS2') {
    // 先尝试从 sessionStorage 恢复（含完整渲染数据）
    try {
      const cached = sessionStorage.getItem(`qa_chart_${projectId}_${qualityMethod}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        chartData.value = parsed
        return parsed
      }
    } catch (e) { /* 解析失败忽略 */ }

    // sessionStorage 无缓存时查后端（只有 meta，无渲染数据，不覆盖 chartData）
    const res = await http.get('/qa/chart/', { params: { project_id: projectId, quality_method: qualityMethod } })
    if (res.data.data) {
      // 后端只返回 meta，不含 traffic_light/proportion，不覆盖 chartData
      // 仅保留 image_url / excel_url 等下载链接
      if (chartData.value) {
        chartData.value = { ...chartData.value, ...res.data.data }
      }
    }
    return res.data.data
  }

  async function exportExcel(projectId, qualityMethod = 'QUADAS2', includeUnconfirmed = false) {
    const res = await http.post('/qa/export/excel/', {
      project_id: projectId,
      quality_method: qualityMethod,
      include_unconfirmed: includeUnconfirmed,
    }, { responseType: 'blob' })
    // 触发下载
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `qa_export_${qualityMethod}_${new Date().toISOString().slice(0,10)}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  function reset() {
    currentStep.value = 1
    maxReachedStep.value = 1
    refs.value = []
    refsLoading.value = false
    currentRef.value = null
    signalItems.value = []
    domainResults.value = []
    signalLoading.value = false
    evalProgress.value = null
    chartData.value = null
    exportStatus.value = null
    // methods 是公共配置，不随项目切换清空
    stopPolling()
  }

  return {
    // state
    currentStep, maxReachedStep, refs, refsLoading,
    currentRef, signalItems, domainResults, signalLoading,
    evalProgress, chartData, chartLoading, chartPreviewLoading, exportStatus, methods,
    // computed
    confirmedRefs, pendingRefs, totalRefs, evalCompleted,
    // actions
    fetchMethods, fetchRefs,
    importFromScreening, uploadFulltext, updateRef, batchSetMethod,
    startEval, fetchEvalProgress, startPollingProgress, stopPolling,
    selectRef, fetchSignalItems, fetchDomainResults,
    confirmSignalItem, batchConfirm,
    previewChart, generateChart, fetchChartInfo, exportExcel,
    reset,
  }
})
