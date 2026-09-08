import * as screeningApi from '../api'

export function createReviewController(context) {
  const loadStats = () => screeningApi.fetchReviewStats(context.projectId())
  const loadItems = (filters = {}) => screeningApi.fetchReviewList({
    project: context.projectId(),
    step: context.stepId(),
    ...filters,
  })
  const saveDecision = (sourceXml, decision, reason = '') =>
    screeningApi.updateReviewItem(sourceXml, {
      project: context.projectId(),
      step: context.stepId(),
      decision,
      reason,
    })
  const appendNote = (sourceXml, content) =>
    screeningApi.appendReviewNote(sourceXml, {
      project: context.projectId(),
      step: context.stepId(),
      content,
    })
  const loadNotes = sourceXml =>
    screeningApi.fetchReviewNotes(sourceXml, { project: context.projectId() })

  return { loadStats, loadItems, saveDecision, appendNote, loadNotes }
}
