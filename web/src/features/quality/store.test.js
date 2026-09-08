import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  fetchRefs: vi.fn(),
  fetchEvaluationProgress: vi.fn(),
  startEvaluation: vi.fn(),
}))
vi.mock('./api', () => api)

import { useQAStore } from './store'
import { reviewStatus } from './stores/review'

describe('quality store capabilities', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('loads and resets project-scoped quality state', async () => {
    api.fetchRefs.mockResolvedValue({ data: { data: [{ id: 1, quality_method: 'ROB2' }] } })
    const store = useQAStore()
    await store.fetchRefs(9)
    store.currentStep = 4
    expect(store.refs).toHaveLength(1)
    store.reset()
    expect(store.refs).toEqual([])
    expect(store.currentStep).toBe(1)
  })

  it('derives review status from confirmed signal items', () => {
    expect(reviewStatus([])).toBe('not_started')
    expect(reviewStatus([{ is_confirmed: true }, { is_confirmed: false }])).toBe('partial')
    expect(reviewStatus([{ is_confirmed: true }])).toBe('confirmed')
  })

  it('does not send a null eval_mode when starting AI evaluation', async () => {
    api.startEvaluation.mockResolvedValue({ data: { data: { task_id: 8 } } })
    const store = useQAStore()

    await store.startEval(42, [7], null, ['deepseek-v4-pro'])

    expect(api.startEvaluation).toHaveBeenCalledWith({
      project_id: 42,
      ref_ids: [7],
      model_ids: ['deepseek-v4-pro'],
    })
  })
})
