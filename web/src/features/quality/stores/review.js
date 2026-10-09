import { ref } from 'vue'
import * as qualityApi from '../api'

export function reviewStatus(items) {
  const confirmed = items.filter(item => item.is_confirmed).length
  if (!items.length) return 'not_started'
  if (confirmed === items.length) return 'confirmed'
  return confirmed > 0 ? 'partial' : 'not_started'
}

export function createReviewCapability(refs) {
  const currentRef = ref(null)
  const signalItems = ref([])
  const domainResults = ref([])
  const signalLoading = ref(false)
  const evaluationAudit = ref(null)

  function syncRefStatus(qaRefId) {
    const status = reviewStatus(signalItems.value)
    const index = refs.value.findIndex(item => item.id === qaRefId)
    if (index !== -1) refs.value[index] = { ...refs.value[index], review_status: status }
    if (currentRef.value?.id === qaRefId) currentRef.value = { ...currentRef.value, review_status: status }
  }

  async function fetchSignalItems(qaRefId, filters = {}) {
    signalLoading.value = true
    try {
      const response = await qualityApi.fetchSignalItems(qaRefId, filters)
      signalItems.value = response.data.data || []
      return signalItems.value
    } finally {
      signalLoading.value = false
    }
  }

  async function fetchDomainResults(qaRefId) {
    const response = await qualityApi.fetchDomainResults(qaRefId)
    domainResults.value = response.data.data || []
    return domainResults.value
  }

  async function fetchEvidenceContext(itemId, chunkId, modelId = '') {
    const response = await qualityApi.fetchEvidenceContext(itemId, chunkId, modelId)
    return response.data.data
  }

  async function fetchEvaluationAudit(qaRefId) {
    const response = await qualityApi.fetchEvaluationAudit(qaRefId)
    evaluationAudit.value = response.data.data
    return evaluationAudit.value
  }

  async function selectRef(refItem) {
    currentRef.value = refItem
    await Promise.all([fetchSignalItems(refItem.id), fetchDomainResults(refItem.id)])
  }

  async function confirmSignalItem(itemId, humanJudgment) {
    const response = await qualityApi.confirmSignalItem(itemId, humanJudgment)
    const updated = response.data.data
    const index = signalItems.value.findIndex(item => item.id === itemId)
    if (index !== -1) signalItems.value[index] = updated
    if (currentRef.value) {
      await fetchDomainResults(currentRef.value.id)
      syncRefStatus(currentRef.value.id)
    }
    return updated
  }

  async function batchConfirm(qaRefId, confirmMode = 'adopt_preselected', signalKeys = []) {
    const response = await qualityApi.batchConfirm({ qa_ref_id: qaRefId, confirm_mode: confirmMode, signal_keys: signalKeys })
    await Promise.all([fetchSignalItems(qaRefId), fetchDomainResults(qaRefId)])
    syncRefStatus(qaRefId)
    return response.data.data
  }

  async function batchConfirmProject(projectId, confirmMode = 'adopt_preselected') {
    const response = await qualityApi.batchConfirmProject({
      project_id: projectId,
      confirm_mode: confirmMode,
    })
    const refsResponse = await qualityApi.fetchRefs(projectId)
    refs.value = refsResponse.data.data || []
    return response.data.data
  }

  function resetReview() {
    currentRef.value = null
    signalItems.value = []
    domainResults.value = []
    signalLoading.value = false
    evaluationAudit.value = null
  }

  return {
    currentRef, signalItems, domainResults, signalLoading, evaluationAudit,
    selectRef, fetchSignalItems, fetchDomainResults, fetchEvidenceContext,
    fetchEvaluationAudit, confirmSignalItem, batchConfirm, batchConfirmProject, resetReview,
  }
}
