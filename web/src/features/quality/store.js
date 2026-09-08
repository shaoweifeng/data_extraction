/** Quality feature facade. Domain capabilities live in ./stores. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as qualityApi from './api'
import { createEvaluationCapability } from './stores/evaluation'
import { createReviewCapability } from './stores/review'
import { createChartCapability } from './stores/chart'

export const useQAStore = defineStore('qa', () => {
  const currentStep = ref(1)
  const maxReachedStep = ref(1)
  const refs = ref([])
  const refsLoading = ref(false)

  const confirmedRefs = computed(() => refs.value.filter(item => item.review_status === 'confirmed'))
  const pendingRefs = computed(() => refs.value.filter(item => !item.quality_method))
  const totalRefs = computed(() => refs.value.length)
  const evaluation = createEvaluationCapability(refs)
  const review = createReviewCapability(refs)
  const chart = createChartCapability()

  async function fetchRefs(projectId) {
    if (!projectId) return
    refsLoading.value = true
    try {
      const response = await qualityApi.fetchRefs(projectId)
      refs.value = response.data.data || []
    } catch (error) {
      console.warn('[QA] fetchRefs failed', error)
    } finally {
      refsLoading.value = false
    }
  }

  async function importFromScreening(projectId, sourceStage = 'SCREEN_1') {
    const response = await qualityApi.importFromScreening(projectId, sourceStage)
    return response.data.data
  }

  async function uploadFulltext(projectId, files) {
    const form = new FormData()
    form.append('project_id', projectId)
    files.forEach(file => form.append('files', file))
    const response = await qualityApi.uploadFulltext(form)
    return response.data.data
  }

  async function updateRef(refId, payload) {
    const response = await qualityApi.updateRef(refId, payload)
    const updated = response.data.data
    const index = refs.value.findIndex(item => item.id === refId)
    if (index !== -1) refs.value[index] = updated
    return updated
  }

  async function batchSetMethod(refIds, qualityMethod) {
    const response = await qualityApi.batchSetMethod(refIds, qualityMethod)
    for (const id of refIds) {
      const target = refs.value.find(item => item.id === id)
      if (target) target.quality_method = qualityMethod
    }
    return response.data.data
  }

  function reset() {
    currentStep.value = 1
    maxReachedStep.value = 1
    refs.value = []
    refsLoading.value = false
    evaluation.resetEvaluation()
    review.resetReview()
    chart.resetChart()
  }

  return {
    currentStep, maxReachedStep, refs, refsLoading,
    confirmedRefs, pendingRefs, totalRefs,
    ...evaluation,
    ...review,
    ...chart,
    fetchRefs, importFromScreening, uploadFulltext, updateRef, batchSetMethod, reset,
  }
})
