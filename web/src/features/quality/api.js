import http from '@/shared/api/http'

export const fetchMethods = () => http.get('/qa/methods/')
export const fetchRefs = projectId => http.get('/qa/refs/', { params: { project_id: projectId } })
export const importFromScreening = (projectId, sourceStage) =>
  http.post('/qa/refs/import/', { project_id: projectId, source_stage: sourceStage })
export const uploadFulltext = form => http.post('/qa/refs/upload/', form, {
  headers: { 'Content-Type': 'multipart/form-data' },
})
export const updateRef = (refId, payload) => http.patch(`/qa/refs/${refId}/`, payload)
export const batchSetMethod = (refIds, qualityMethod) =>
  http.post('/qa/refs/batch-method/', { ref_ids: refIds, quality_method: qualityMethod })
export const startEvaluation = payload => http.post('/qa/eval/start/', payload)
export const fetchEvaluationProgress = projectId =>
  http.get('/qa/eval/progress/', { params: { project_id: projectId } })
export const fetchSignalItems = (qaRefId, filters = {}) =>
  http.get('/qa/signal-items/', { params: { qa_ref_id: qaRefId, ...filters } })
export const fetchDomainResults = qaRefId =>
  http.get('/qa/domain-results/', { params: { qa_ref_id: qaRefId } })
export const confirmSignalItem = (itemId, humanJudgment) =>
  http.patch(`/qa/signal-items/${itemId}/confirm/`, { human_judgment: humanJudgment })
export const batchConfirm = payload => http.post('/qa/signal-items/batch-confirm/', payload)
export const previewChart = payload => http.post('/qa/chart/preview/', payload)
export const generateChart = payload => http.post('/qa/chart/generate/', payload)
export const fetchChartInfo = (projectId, qualityMethod) =>
  http.get('/qa/chart/', { params: { project_id: projectId, quality_method: qualityMethod } })
export const exportExcel = payload => http.post('/qa/export/excel/', payload, { responseType: 'blob' })
export const fetchChartSettings = (projectId, qualityMethod) =>
  http.get('/qa/chart/settings/', { params: { project_id: projectId, quality_method: qualityMethod } })
export const saveChartSettings = payload => http.patch('/qa/chart/settings/save/', payload)
