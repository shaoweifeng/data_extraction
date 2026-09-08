import http, { httpNoTimeout } from './http'

export const fetchTasks = (projectId) => http.get('/tasks/', { params: { project: projectId } })
export const fetchTask = (taskId) => http.get(`/tasks/${taskId}/`)
export const fetchTaskLogs = (taskId) => http.get(`/tasks/${taskId}/logs/`)
export const createTask = (payload, options = {}) => (options.noTimeout ? httpNoTimeout : http).post('/tasks/', payload)
export const deleteTask = (taskId) => http.delete(`/tasks/${taskId}/`)
export const stopTask = taskId => httpNoTimeout.post(`/tasks/${taskId}/stop/`)
export const resumeTask = taskId => httpNoTimeout.post(`/tasks/${taskId}/resume/`)
export const fetchActivityLogs = (projectId, page = 1) =>
  http.get('/activity-logs/', { params: { project: projectId, page } })
export const fetchFiles = (params, config = {}) => http.get('/files/', { ...config, params })
export const deleteFile = (fileId) => http.delete(`/files/${fileId}/`)
export const updateStepMetadata = (stepId, metadata) =>
  http.patch(`/steps/${stepId}/update_metadata/`, { metadata })
export const completeStep = (stepId) => http.post(`/steps/${stepId}/complete/`)
export const fetchAiModels = () => http.get('/ai-models/')
