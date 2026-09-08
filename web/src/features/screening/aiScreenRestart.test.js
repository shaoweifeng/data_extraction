import { describe, expect, it, vi } from 'vitest'

import { prepareAiScreenRestart } from './aiScreenRestart'

describe('prepareAiScreenRestart', () => {
  it('reloads pending files after old screening results are cleared', async () => {
    const order = []
    const state = {
      pendingFiles: [],
      pendingTotal: 0,
      screenedFiles: [{ id: 1 }],
      screenedTotal: 1,
      aiScreenStats: { included_count: 1 },
      processedCount: 1,
      screeningProgressValue: 100,
      totalRefs: 1,
    }
    const clearResults = vi.fn(async () => { order.push('clear') })
    const loadPending = vi.fn(async () => {
      order.push('pending')
      state.pendingFiles = [{ id: 2 }]
      state.pendingTotal = 1
    })

    await prepareAiScreenRestart({ state, clearResults, loadPending })

    expect(order).toEqual(['clear', 'pending'])
    expect(state.pendingFiles).toEqual([{ id: 2 }])
    expect(state.pendingTotal).toBe(1)
    expect(state.screenedFiles).toEqual([])
    expect(state.screenedTotal).toBe(0)
    expect(state.aiScreenStats).toBeNull()
    expect(state.screeningProgressValue).toBe(0)
  })

  it('does not apply a late response after the user switches projects', async () => {
    const state = { screenedTotal: 3 }
    const loadPending = vi.fn()

    const applied = await prepareAiScreenRestart({
      state,
      clearResults: vi.fn(),
      loadPending,
      shouldApply: () => false,
    })

    expect(applied).toBe(false)
    expect(state.screenedTotal).toBe(3)
    expect(loadPending).not.toHaveBeenCalled()
  })

  it('does not reset UI or start reloading when clearing results fails', async () => {
    const state = { screenedTotal: 3 }
    const error = new Error('clear failed')
    const loadPending = vi.fn()

    await expect(prepareAiScreenRestart({
      state,
      clearResults: vi.fn().mockRejectedValue(error),
      loadPending,
    })).rejects.toThrow('clear failed')

    expect(state.screenedTotal).toBe(3)
    expect(loadPending).not.toHaveBeenCalled()
  })
})
