import { describe, expect, it, vi } from 'vitest'

const screeningApi = vi.hoisted(() => ({
  fetchReviewStats: vi.fn(), fetchReviewList: vi.fn(), fetchPrompt: vi.fn(),
  fetchReviewDetail: vi.fn(), updateReviewReference: vi.fn(),
  appendReviewReferenceNote: vi.fn(), fetchReviewReferenceNotes: vi.fn(),
  savePrompt: vi.fn(), resetPrompt: vi.fn(), fetchScreeningStats: vi.fn(),
  fetchScreeningInputs: vi.fn(), fetchScreeningResults: vi.fn(), clearAiScreenResults: vi.fn(),
}))
vi.mock('../api', () => screeningApi)
vi.mock('@/features/billing/api', () => ({ fetchBalance: vi.fn(), estimateUsage: vi.fn() }))
vi.mock('@/shared/api/workflow', () => ({
  fetchAiModels: vi.fn(), fetchFiles: vi.fn(), fetchTask: vi.fn(), createTask: vi.fn(),
  stopTask: vi.fn(), resumeTask: vi.fn(), deleteTask: vi.fn(),
}))

import { createReviewController } from './useReviewController'
import { createAiScreenController } from './useAiScreenController'

describe('screening controllers', () => {
  it('injects current project and step into run-bound review requests', async () => {
    const controller = createReviewController({ projectId: () => 12, stepId: () => 34 })
    await controller.loadItems({ page: 2 })
    await controller.saveDecision(56, 78, 'included')
    expect(screeningApi.fetchReviewList).toHaveBeenCalledWith({ project: 12, step: 34, page: 2 })
    expect(screeningApi.updateReviewReference).toHaveBeenCalledWith(56, 78, {
      project: 12, step: 34, decision: 'included', reason: '',
    })
  })

  it('binds database review requests to a screening run and reference', async () => {
    const controller = createReviewController({ projectId: () => 12, stepId: () => 34 })
    await controller.loadDetail(56, 78)
    await controller.saveDecision(56, 78, 'excluded', 'reason')
    await controller.appendNote(56, 78, 'note')

    expect(screeningApi.fetchReviewDetail).toHaveBeenCalledWith(
      56, 78, { project: 12 }, {},
    )
    expect(screeningApi.updateReviewReference).toHaveBeenCalledWith(56, 78, {
      project: 12, step: 34, decision: 'excluded', reason: 'reason',
    })
    expect(screeningApi.appendReviewReferenceNote).toHaveBeenCalledWith(56, 78, {
      project: 12, step: 34, content: 'note',
    })
  })

  it('reads the project lazily so controllers survive project changes', async () => {
    let id = 1
    const controller = createAiScreenController(() => id)
    await controller.loadPrompt()
    id = 2
    await controller.clearResults()
    expect(screeningApi.fetchPrompt).toHaveBeenCalledWith(1)
    expect(screeningApi.clearAiScreenResults).toHaveBeenCalledWith(2)
  })

  it('keeps project binding when forwarding cancellation config', async () => {
    const controller = createAiScreenController(() => 12)
    const signal = new AbortController().signal

    await controller.loadStats(12, { signal })
    await controller.loadResults(12, { limit: 50, offset: 0 }, { signal })
    await controller.loadReviewPage({ page: 3 }, 12, { signal })

    expect(screeningApi.fetchScreeningStats).toHaveBeenCalledWith(12, { signal })
    expect(screeningApi.fetchScreeningResults).toHaveBeenCalledWith(
      12,
      { limit: 50, offset: 0 },
      { signal },
    )
    expect(screeningApi.fetchReviewList).toHaveBeenCalledWith(
      { project: 12, page: 3 },
      { signal },
    )
  })
})
