import * as screeningApi from '../api'

export function createReviewController(context) {
  const loadStats = (runId = null) => screeningApi.fetchReviewStats(context.projectId(), runId)
  const loadItems = (filters = {}) => screeningApi.fetchReviewList({
    project: context.projectId(),
    step: context.stepId(),
    ...filters,
  })
  const loadDetail = (runId, referenceId, config = {}) =>
    screeningApi.fetchReviewDetail(runId, referenceId, { project: context.projectId() }, config)
  const saveDecision = (runId, referenceId, decision, reason = '') => {
    const payload = {
      project: context.projectId(),
      step: context.stepId(),
      decision,
      reason,
    }
    return screeningApi.updateReviewReference(runId, referenceId, payload)
  }
  const appendNote = (runId, referenceId, content) => {
    const payload = {
      project: context.projectId(),
      step: context.stepId(),
      content,
    }
    return screeningApi.appendReviewReferenceNote(runId, referenceId, payload)
  }
  const loadNotes = (runId, referenceId) => screeningApi.fetchReviewReferenceNotes(
    runId, referenceId, { project: context.projectId() },
  )

  return { loadStats, loadItems, loadDetail, saveDecision, appendNote, loadNotes }
}
