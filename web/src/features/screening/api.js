import http from '@/shared/api/http'

export function uploadReferenceFile(file, projectId, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    form.append('filename', file.name)
    form.append('project', projectId)
    form.append('data_category', 'input')
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/files/')
    xhr.withCredentials = true
    const csrf = document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1]
    if (csrf) xhr.setRequestHeader('X-CSRFToken', csrf)
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText))
      else reject(new Error(`上传失败 (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error('上传失败（网络错误）'))
    xhr.send(form)
  })
}

export const fetchPrompt = projectId => http.get(`/projects/${projectId}/get_prompt/`)
export const savePrompt = (projectId, payload) => http.post(`/projects/${projectId}/save_prompt/`, payload)
export const resetPrompt = projectId => http.post(`/projects/${projectId}/reset_prompt/`)
export const fetchScreeningStats = (projectId, config = {}) => http.get(`/projects/${projectId}/ai_screen_stats/`, config)
export const fetchReviewList = (params, config = {}) => http.get('/review/list/', { ...config, params })
export const fetchReviewStats = projectId => http.get('/review/stats/', { params: { project: projectId } })
export const updateReviewItem = (sourceXml, payload) => http.patch(`/review/item/${encodeURIComponent(sourceXml)}/`, payload)
export const appendReviewNote = (sourceXml, payload) => http.post(`/review/note/${encodeURIComponent(sourceXml)}/`, payload)
export const fetchReviewNotes = (sourceXml, params = {}) => http.get(`/review/notes/${encodeURIComponent(sourceXml)}/`, { params })
export const completeReview = (projectId, stepId) =>
  http.post('/review/complete/', { project: projectId, step: stepId })
export const clearAiScreenResults = projectId => http.post(`/projects/${projectId}/clear_ai_screen_results/`)
