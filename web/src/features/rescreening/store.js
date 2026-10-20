import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as rescreenApi from './api'
import { defaultCriteria } from './mock'

export function fulltextActionsForStatus(status) {
  if (status === 'bound') return ['view', 'replace']
  if (status === 'unbound' || status === 'bind_failed') return ['upload']
  return []
}

export function fulltextLabelForStatus(status) {
  return { bound: '已绑定', unbound: '未绑定', bind_failed: '绑定失败' }[status] || status
}

export const RESCREEN_STEPS = [
  { index: 1, key: 'upload', label: '上传/导入' },
  { index: 2, key: 'fulltext', label: '全文查找绑定' },
  { index: 3, key: 'criteria', label: '纳排标准' },
  { index: 4, key: 'ai_rescreen', label: 'AI 全文复筛' },
  { index: 5, key: 'review', label: '人工审阅' },
  { index: 6, key: 'export', label: '结果导出' },
]


function normalizeRef(item) {
  return {
    ...item,
    authors: Array.isArray(item.authors) ? item.authors : [],
    ai_evidence: Array.isArray(item.ai_evidence) ? item.ai_evidence : [],
    fulltext_filename: item.fulltext_filename || '',
    fulltext_url: item.fulltext_url || '',
    fulltext_lookup_url: item.fulltext_lookup_url || '',
    fulltext_source: item.fulltext_source || '',
    fulltext_source_url: item.fulltext_source_url || '',
    fulltext_license: item.fulltext_license || '',
    fulltext_resolver: item.fulltext_resolver || '',
    fulltext_checked_at: item.fulltext_checked_at || '',
    fulltext_attempts: Array.isArray(item.fulltext_attempts) ? item.fulltext_attempts : [],
    human_decision: item.human_decision || '',
    exclusion_reason: item.exclusion_reason || '',
    review_note: item.review_note || '',
  }
}


function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function apiErrorMessage(error, fallback = '操作失败，请稍后重试') {
  const payload = error?.response?.data
  if (typeof payload?.error === 'string') return payload.error
  if (payload?.error) return JSON.stringify(payload.error)
  return error?.message || fallback
}

export const useRescreenStore = defineStore('rescreen', () => {
  const currentStep = ref(1)
  const maxReachedStep = ref(1)
  const refs = ref([])
  const criteriaList = ref([...defaultCriteria])
  const newCriteria = ref('')
  const activeRefId = ref(refs.value[0]?.id || null)
  const fulltextSearching = ref(false)
  const aiRunning = ref(false)
  const aiProgress = ref(0)
  const reviewTab = ref('')
  const refsLoading = ref(false)
  const criteriaLoading = ref(false)
  const lastError = ref('')
  const apiReady = ref(false)

  const totalRefs = computed(() => refs.value.length)
  const boundRefs = computed(() => refs.value.filter(item => item.fulltext_status === 'bound'))
  const unboundRefs = computed(() => refs.value.filter(item => item.fulltext_status === 'unbound'))
  const bindFailedRefs = computed(() => refs.value.filter(item => item.fulltext_status === 'bind_failed'))
  const activeRef = computed(() => refs.value.find(item => item.id === activeRefId.value) || refs.value[0] || null)
  const reviewedRefs = computed(() => refs.value.filter(item => item.human_decision))
  const missingPdfCount = computed(() => refs.value.filter(item => item.fulltext_status !== 'bound').length)
  const includedRefs = computed(() => refs.value.filter(item => item.human_decision === 'included'))
  const excludedRefs = computed(() => refs.value.filter(item => item.human_decision === 'excluded'))
  const pendingRefs = computed(() => refs.value.filter(item => item.human_decision === 'pending'))
  const conflictRefs = computed(() => refs.value.filter(item => !item.human_decision && (item.consensus_status === 'divergent' || item.ai_decision === 'pending')))
  const unreviewedRefs = computed(() => refs.value.filter(item => !item.human_decision))

  const reviewFilteredRefs = computed(() => {
    if (reviewTab.value === 'unreviewed') return unreviewedRefs.value
    if (reviewTab.value === 'conflict') return conflictRefs.value
    if (reviewTab.value === 'included') return includedRefs.value
    if (reviewTab.value === 'excluded') return excludedRefs.value
    if (reviewTab.value === 'pending') return pendingRefs.value
    return refs.value
  })

  const exportBlockingMessages = computed(() => {
    const messages = []
    const unreviewed = refs.value.filter(item => !item.human_decision).length
    const excludedWithoutReason = refs.value.filter(item => item.human_decision === 'excluded' && !item.exclusion_reason).length
    if (unreviewed) messages.push(`还有 ${unreviewed} 篇文献未完成人工审阅`)
    if (excludedWithoutReason) messages.push(`还有 ${excludedWithoutReason} 篇排除文献缺少排除理由`)
    return messages
  })

  const canGoNext = computed(() => {
    if (currentStep.value === 1) return refs.value.length > 0
    if (currentStep.value === 2) return refs.value.every(item => ['bound', 'unbound', 'bind_failed'].includes(item.fulltext_status))
    if (currentStep.value === 3) return criteriaList.value.length > 0
    if (currentStep.value === 4) return refs.value.some(item => item.ai_status === 'completed') || refs.value.every(item => item.fulltext_status !== 'bound')
    if (currentStep.value === 5) return refs.value.every(item => item.human_decision && (item.human_decision !== 'excluded' || item.exclusion_reason))
    return true
  })

  const footerTip = computed(() => {
    if (currentStep.value === 1) return `已形成 ${totalRefs.value} 条复筛文献记录`
    if (currentStep.value === 2) return `已绑定 ${boundRefs.value.length} 篇，未绑定 ${unboundRefs.value.length} 篇，绑定失败 ${bindFailedRefs.value.length} 篇`
    if (currentStep.value === 3) return `已维护 ${criteriaList.value.length} 条自定义标准/排除理由`
    if (currentStep.value === 4) return `AI 可处理 ${boundRefs.value.length} 篇，跳过 ${totalRefs.value - boundRefs.value.length} 篇无全文文献`
    if (currentStep.value === 5) return `已人工确认 ${reviewedRefs.value.length} / ${totalRefs.value} 篇`
    return `纳入 ${includedRefs.value.length} 篇，排除 ${excludedRefs.value.length} 篇，待定 ${pendingRefs.value.length} 篇`
  })

  function applyRefs(nextRefs) {
    refs.value = (nextRefs || []).map(normalizeRef)
    if (!activeRefId.value || !refs.value.some(item => item.id === activeRefId.value)) {
      activeRefId.value = refs.value[0]?.id || null
    }
  }

  function mergeRefs(nextRefs) {
    const byId = new Map(refs.value.map(item => [item.id, item]))
    for (const item of nextRefs || []) byId.set(item.id, normalizeRef(item))
    refs.value = Array.from(byId.values()).sort((a, b) => a.id - b.id)
    if (!activeRefId.value && refs.value[0]) activeRefId.value = refs.value[0].id
  }

  async function fetchRefs(projectId) {
    if (!projectId) return refs.value
    refsLoading.value = true
    try {
      const response = await rescreenApi.fetchRefs(projectId)
      applyRefs(response.data.data || [])
      apiReady.value = true
      lastError.value = ''
      return refs.value
    } catch (error) {
      lastError.value = apiErrorMessage(error, '加载复筛文献失败')
      console.warn('[Rescreen] fetchRefs failed', error)
      return refs.value
    } finally {
      refsLoading.value = false
    }
  }

  async function fetchCriteria(projectId) {
    if (!projectId) return criteriaList.value
    criteriaLoading.value = true
    try {
      const response = await rescreenApi.fetchCriteria(projectId)
      criteriaList.value = response.data.data?.criteria_list || []
      apiReady.value = true
      lastError.value = ''
      return criteriaList.value
    } catch (error) {
      lastError.value = apiErrorMessage(error, '加载复筛标准失败')
      console.warn('[Rescreen] fetchCriteria failed', error)
      return criteriaList.value
    } finally {
      criteriaLoading.value = false
    }
  }

  async function loadProject(projectId) {
    if (!projectId) return
    await Promise.all([fetchRefs(projectId), fetchCriteria(projectId)])
  }

  function goToStep(step) {
    currentStep.value = Math.min(Math.max(1, step), RESCREEN_STEPS.length)
    maxReachedStep.value = Math.max(maxReachedStep.value, currentStep.value)
  }

  function nextStep() {
    if (!canGoNext.value) return
    goToStep(currentStep.value + 1)
  }

  function prevStep() {
    goToStep(currentStep.value - 1)
  }

  function addCriteria() {
    const text = newCriteria.value.trim()
    if (!text) return
    criteriaList.value.push(text)
    newCriteria.value = ''
  }

  async function saveCriteria(projectId) {
    if (!projectId) return criteriaList.value
    try {
      const response = await rescreenApi.saveCriteria({ project_id: projectId, criteria_list: criteriaList.value })
      criteriaList.value = response.data.data?.criteria_list || criteriaList.value
      apiReady.value = true
      lastError.value = ''
      return criteriaList.value
    } catch (error) {
      lastError.value = apiErrorMessage(error, '保存复筛标准失败')
      throw error
    }
  }

  function removeCriteria(index) {
    criteriaList.value.splice(index, 1)
  }

  async function importFromScreening(projectId) {
    if (!projectId) {
      maxReachedStep.value = Math.max(maxReachedStep.value, 2)
      return { imported: refs.value.length, ref_ids: refs.value.map(item => item.id) }
    }
    const response = await rescreenApi.importFromScreening(projectId)
    await fetchRefs(projectId)
    maxReachedStep.value = Math.max(maxReachedStep.value, 2)
    apiReady.value = true
    return response.data.data
  }

  async function uploadBibliographyFile(projectId, file) {
    if (!projectId || !file) {
      maxReachedStep.value = Math.max(maxReachedStep.value, 2)
      return { created: 0, refs: [] }
    }
    const form = new FormData()
    form.append('project_id', projectId)
    form.append('file', file)
    const response = await rescreenApi.uploadBibliography(form)
    mergeRefs(response.data.data?.refs || [])
    maxReachedStep.value = Math.max(maxReachedStep.value, 2)
    apiReady.value = true
    return response.data.data
  }

  async function uploadFulltextFiles(projectId, files, refId = null) {
    const fileList = Array.from(files || [])
    if (!projectId || fileList.length === 0) {
      if (refId) uploadPdf(refId)
      return { created: refId ? 1 : 0, refs: [] }
    }
    const form = new FormData()
    form.append('project_id', projectId)
    if (refId) form.append('ref_id', refId)
    fileList.forEach(file => form.append('files', file))
    const response = await rescreenApi.uploadFulltext(form)
    mergeRefs(response.data.data?.refs || [])
    maxReachedStep.value = Math.max(maxReachedStep.value, 2)
    apiReady.value = true
    return response.data.data
  }

  async function replaceFulltextFile(projectId, refId, file) {
    if (!projectId || !file) {
      uploadPdf(refId)
      return null
    }
    const form = new FormData()
    form.append('ref_id', refId)
    form.append('files', file)
    const response = await rescreenApi.replaceFulltext(form)
    mergeRefs([response.data.data])
    apiReady.value = true
    return response.data.data
  }

  function autoSearchFulltext(projectId) {
    fulltextSearching.value = true
    if (projectId) {
      return rescreenApi.autoSearchFulltexts({ project_id: projectId })
        .then((response) => {
          if (response.data.data?.refs) applyRefs(response.data.data.refs)
          apiReady.value = true
          lastError.value = ''
          return response.data.data
        })
        .catch((error) => {
          lastError.value = apiErrorMessage(error, '自动查找全文失败')
          throw error
        })
        .finally(() => { fulltextSearching.value = false })
    }

    setTimeout(() => {
      refs.value = refs.value.map(item => {
        if (item.fulltext_status !== 'unbound') return item
        if (item.id === 2) {
          return {
            ...item,
            fulltext_status: 'bound',
            fulltext_filename: 'smith-2021-review-protocol.pdf',
            fulltext_error: '',
          }
        }
        return item
      })
      fulltextSearching.value = false
    }, 700)
    return null
  }

  function uploadPdf(refId) {
    refs.value = refs.value.map(item => item.id === refId
      ? { ...item, fulltext_status: 'bound', fulltext_filename: `${item.first_author || 'paper'}-${item.year || 'unknown'}-manual.pdf`, fulltext_error: '' }
      : item)
  }

  function markBindFailed(refId) {
    refs.value = refs.value.map(item => item.id === refId
      ? { ...item, fulltext_status: 'bind_failed', fulltext_error: '文件无法解析，请重新上传可复制文本的 PDF。' }
      : item)
  }

  async function pollAiCompletion(projectId, maxAttempts = 90) {
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const progressResponse = await rescreenApi.fetchAiProgress(projectId)
      const payload = progressResponse.data.data || {}
      aiProgress.value = Number(payload.progress || 0)
      await fetchRefs(projectId)
      if (!payload.total || payload.finished >= payload.total) return payload
      await sleep(2000)
    }
    return null
  }

  async function runAiRescreen(projectId) {
    aiRunning.value = true
    aiProgress.value = 12
    refs.value = refs.value.map(item => item.fulltext_status === 'bound'
      ? { ...item, ai_status: projectId ? 'queued' : 'running' }
      : { ...item, ai_status: 'skipped_unbound' })

    if (projectId) {
      try {
        const response = await rescreenApi.startAiRescreen({ project_id: projectId })
        apiReady.value = true
        await pollAiCompletion(projectId)
        return response.data.data
      } catch (error) {
        lastError.value = apiErrorMessage(error, '启动 AI 复筛失败')
        throw error
      } finally {
        try {
          await fetchRefs(projectId)
        } catch {
          // 复筛任务启动后的最终刷新失败不阻断主流程，保留上一次状态。
        }
        aiRunning.value = false
      }
    }

    setTimeout(() => {
      aiProgress.value = 100
      refs.value = refs.value.map(item => {
        if (item.fulltext_status !== 'bound') return item
        if (item.ai_status === 'completed') return item
        return {
          ...item,
          ai_status: 'completed',
          ai_decision: 'included',
          ai_reason: '全文证据满足当前复筛标准，建议纳入。',
          consensus_status: 'consistent',
          ai_evidence: [{ page: 4, text: 'The included participants and outcome definition matched the review criteria.' }],
        }
      })
      aiRunning.value = false
    }, 900)
    return null
  }

  function saveHumanDecision(refId, decision, reason = '', note = '') {
    const previous = refs.value.find(item => item.id === refId)
    refs.value = refs.value.map(item => item.id === refId
      ? { ...item, human_decision: decision, exclusion_reason: decision === 'excluded' ? reason : '', review_note: note || item.review_note || '' }
      : item)
    return previous
  }

  async function saveHumanDecisionRemote(projectId, refId, decision, reason = '', note = '') {
    if (!projectId) {
      saveHumanDecision(refId, decision, reason, note)
      return null
    }
    const previous = saveHumanDecision(refId, decision, reason, note)
    try {
      const response = await rescreenApi.saveReview(refId, {
        human_decision: decision,
        exclusion_reason: reason,
        review_note: note,
      })
      mergeRefs([response.data.data])
      apiReady.value = true
      return response.data.data
    } catch (error) {
      if (previous) mergeRefs([previous])
      lastError.value = apiErrorMessage(error, '保存人工审阅失败')
      throw error
    }
  }

  function batchIncludeConsistent(projectId) {
    if (projectId) {
      return rescreenApi.batchInclude({ project_id: projectId })
        .then((response) => {
          refs.value = refs.value.map(item => {
            if (item.ai_status === 'completed' && item.ai_decision === 'included' && item.consensus_status === 'consistent' && !item.human_decision) {
              return { ...item, human_decision: 'included', exclusion_reason: '' }
            }
            return item
          })
          return response.data.data
        })
        .catch((error) => {
          lastError.value = apiErrorMessage(error, '一键纳入失败')
          throw error
        })
    }

    refs.value = refs.value.map(item => {
      if (item.ai_status === 'completed' && item.ai_decision === 'included' && item.consensus_status === 'consistent' && !item.human_decision) {
        return { ...item, human_decision: 'included', exclusion_reason: '' }
      }
      return item
    })
    return null
  }

  function reset() {
    currentStep.value = 1
    maxReachedStep.value = 1
    refs.value = []
    criteriaList.value = [...defaultCriteria]
    newCriteria.value = ''
    activeRefId.value = refs.value[0]?.id || null
    fulltextSearching.value = false
    aiRunning.value = false
    aiProgress.value = 0
    reviewTab.value = ''
    refsLoading.value = false
    criteriaLoading.value = false
    lastError.value = ''
    apiReady.value = false
  }

  return {
    currentStep,
    maxReachedStep,
    refs,
    criteriaList,
    newCriteria,
    activeRefId,
    fulltextSearching,
    aiRunning,
    aiProgress,
    reviewTab,
    refsLoading,
    criteriaLoading,
    lastError,
    apiReady,
    totalRefs,
    boundRefs,
    unboundRefs,
    bindFailedRefs,
    activeRef,
    reviewedRefs,
    missingPdfCount,
    includedRefs,
    excludedRefs,
    pendingRefs,
    conflictRefs,
    unreviewedRefs,
    reviewFilteredRefs,
    exportBlockingMessages,
    canGoNext,
    footerTip,
    fetchRefs,
    fetchCriteria,
    loadProject,
    goToStep,
    nextStep,
    prevStep,
    addCriteria,
    saveCriteria,
    removeCriteria,
    importFromScreening,
    uploadBibliographyFile,
    uploadFulltextFiles,
    replaceFulltextFile,
    autoSearchFulltext,
    uploadPdf,
    markBindFailed,
    runAiRescreen,
    saveHumanDecision,
    saveHumanDecisionRemote,
    batchIncludeConsistent,
    reset,
  }
})
