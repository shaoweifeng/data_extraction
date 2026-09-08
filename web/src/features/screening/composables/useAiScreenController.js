import * as screeningApi from '../api'
import * as billingApi from '@/features/billing/api'
import * as workflowApi from '@/shared/api/workflow'

export function createAiScreenController(projectId) {
  return {
    loadPrompt: (targetProjectId = projectId()) => screeningApi.fetchPrompt(targetProjectId),
    savePrompt: payload => screeningApi.savePrompt(projectId(), payload),
    resetPrompt: () => screeningApi.resetPrompt(projectId()),
    loadStats: (targetProjectId = projectId(), config = {}) => screeningApi.fetchScreeningStats(targetProjectId, config),
    loadReviewPage: (params, targetProjectId = projectId(), config = {}) => (
      screeningApi.fetchReviewList({ project: targetProjectId, ...params }, config)
    ),
    loadBalance: billingApi.fetchBalance,
    estimate: (refCount, modelIds) => billingApi.estimateUsage(refCount, modelIds),
    loadModels: workflowApi.fetchAiModels,
    loadFiles: workflowApi.fetchFiles,
    loadTask: workflowApi.fetchTask,
    createTask: payload => workflowApi.createTask(payload, { noTimeout: true }),
    stopTask: workflowApi.stopTask,
    resumeTask: workflowApi.resumeTask,
    deleteTask: workflowApi.deleteTask,
    clearResults: (targetProjectId = projectId()) => screeningApi.clearAiScreenResults(targetProjectId),
  }
}
