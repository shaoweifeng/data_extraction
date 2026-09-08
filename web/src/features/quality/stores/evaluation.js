import { computed, ref } from 'vue'
import * as qualityApi from '../api'
import { createPoller } from '@/shared/composables/usePolling'

export function createEvaluationCapability(refs) {
  const methods = ref([])
  const evalProgress = ref(null)
  let evalPoller = null
  const evalCompleted = computed(() => {
    const summary = evalProgress.value?.summary
    return !!summary && summary.running === 0 && (summary.completed + summary.failed) > 0
  })

  async function fetchMethods() {
    if (methods.value.length) return methods.value
    try {
      const response = await qualityApi.fetchMethods()
      methods.value = response.data.data || []
    } catch (error) {
      console.warn('[QA] fetchMethods failed', error)
    }
    return methods.value
  }

  async function startEval(projectId, refIds, evalMode, modelIds) {
    const payload = { project_id: projectId, ref_ids: refIds, model_ids: modelIds }
    // 评价模式由模型数量推导；兼容真实旧值，但不向后端发送 null。
    if (evalMode) payload.eval_mode = evalMode
    const response = await qualityApi.startEvaluation(payload)
    return response.data.data
  }

  async function fetchEvalProgress(projectId) {
    const response = await qualityApi.fetchEvaluationProgress(projectId)
    evalProgress.value = response.data.data
    for (const progressRef of evalProgress.value?.refs || []) {
      const target = refs.value.find(item => item.id === progressRef.id)
      if (target) {
        target.ai_eval_status = progressRef.ai_eval_status
        target.review_status = progressRef.review_status
      }
    }
    return evalProgress.value
  }

  function stopPolling() {
    evalPoller?.cancel()
    evalPoller = null
  }

  function startPollingProgress(projectId) {
    stopPolling()
    evalPoller = createPoller(() => fetchEvalProgress(projectId), {
      interval: 5000,
      immediate: false,
      shouldStop: () => evalCompleted.value,
    })
    evalPoller.start()
  }

  function resetEvaluation() {
    evalProgress.value = null
    stopPolling()
  }

  return { methods, evalProgress, evalCompleted, fetchMethods, startEval, fetchEvalProgress, startPollingProgress, stopPolling, resetEvaluation }
}
