import http from '@/shared/api/http'

const REVIEW_REQUEST_TIMEOUT = 60000

export function uploadReferenceFiles(files, projectId, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    files.forEach(file => form.append('files', file, file.name))
    form.append('project', projectId)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/screening-imports/')
    xhr.withCredentials = true
    const csrf = document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1]
    if (csrf) xhr.setRequestHeader('X-CSRFToken', csrf)
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText))
      else {
        let message = `上传失败 (${xhr.status})`
        try {
          const payload = JSON.parse(xhr.responseText)
          message = payload?.error?.message || payload?.error || message
        } catch {
          // 保留 HTTP 状态提示
        }
        reject(new Error(message))
      }
    }
    xhr.onerror = () => reject(new Error('上传失败（网络错误）'))
    xhr.send(form)
  })
}

export const fetchImportBatch = batchId => http.get(`/screening-imports/${batchId}/`)
export const fetchImportBatches = projectId => http.get('/screening-imports/', {
  params: { project: projectId },
})
export const cancelImportBatch = batchId => http.post(`/screening-imports/${batchId}/cancel/`)
export const retryImportBatch = batchId => http.post(`/screening-imports/${batchId}/retry/`)
export const deleteImportBatch = batchId => http.delete(`/screening-imports/${batchId}/`)
export const fetchDedupGroups = (projectId, runId, params, config = {}) => http.get(
  `/projects/${projectId}/dedup-runs/${runId}/groups/`,
  { ...config, params },
)
export const fetchDedupGroupMembers = (projectId, runId, groupId, params, config = {}) => http.get(
  `/projects/${projectId}/dedup-runs/${runId}/groups/${groupId}/members/`,
  { ...config, params },
)

export const fetchPrompt = projectId => http.get(`/projects/${projectId}/get_prompt/`)
export const savePrompt = (projectId, payload) => http.post(`/projects/${projectId}/save_prompt/`, payload)
export const resetPrompt = projectId => http.post(`/projects/${projectId}/reset_prompt/`)
export const fetchScreeningStats = (projectId, config = {}) => http.get(`/projects/${projectId}/ai_screen_stats/`, {
  timeout: REVIEW_REQUEST_TIMEOUT,
  ...config,
})
export const fetchScreeningInputs = (projectId, params = {}, config = {}) => http.get(
  `/projects/${projectId}/ai_screen_inputs/`,
  { ...config, params },
)
export const fetchScreeningResults = (projectId, params = {}, config = {}) => http.get(
  `/projects/${projectId}/ai_screen_results/`,
  { ...config, params },
)
export const fetchReviewList = (params, config = {}) => http.get('/review/list/', {
  timeout: REVIEW_REQUEST_TIMEOUT,
  ...config,
  params,
})
export const fetchReviewStats = (projectId, runId = null) => http.get('/review/stats/', {
  timeout: REVIEW_REQUEST_TIMEOUT,
  params: { project: projectId, ...(runId ? { run: runId } : {}) },
})
export const fetchReviewDetail = (runId, referenceId, params = {}, config = {}) => http.get(
  `/review/runs/${runId}/references/${referenceId}/`,
  { ...config, params },
)
export const updateReviewReference = (runId, referenceId, payload) => http.patch(
  `/review/runs/${runId}/references/${referenceId}/`,
  payload,
)
export const appendReviewReferenceNote = (runId, referenceId, payload) => http.post(
  `/review/runs/${runId}/references/${referenceId}/notes/`,
  payload,
)
export const fetchReviewReferenceNotes = (runId, referenceId, params = {}) => http.get(
  `/review/runs/${runId}/references/${referenceId}/notes/`,
  { params },
)
export const completeReview = (projectId, stepId, runId) =>
  http.post('/review/complete/', {
    project: projectId,
    step: stepId,
    screening_run: runId,
  })
export const clearAiScreenResults = projectId => http.post(`/projects/${projectId}/clear_ai_screen_results/`)
