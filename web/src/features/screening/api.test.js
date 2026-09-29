import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('@/shared/api/http', () => ({ default: http }))

import * as screeningApi from './api'
import * as workflowApi from '@/shared/api/workflow'

describe('screening API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('keeps run-bound review routes centralized', async () => {
    await screeningApi.fetchReviewStats(8)
    await screeningApi.fetchReviewDetail(12, 34, { project: 8 })
    await screeningApi.updateReviewReference(12, 34, { decision: 'included' })

    expect(http.get).toHaveBeenCalledWith('/review/stats/', {
      timeout: 60000,
      params: { project: 8 },
    })
    expect(http.get).toHaveBeenCalledWith('/review/runs/12/references/34/', {
      params: { project: 8 },
    })
    expect(http.patch).toHaveBeenCalledWith('/review/runs/12/references/34/', {
      decision: 'included',
    })
  })

  it('forwards abort signals without dropping request parameters', async () => {
    const signal = new AbortController().signal
    await screeningApi.fetchScreeningStats(8, { signal })
    await screeningApi.fetchScreeningInputs(8, { limit: 50, offset: 0 }, { signal })
    await screeningApi.fetchReviewList({ project: 8, page: 2 }, { signal })
    await workflowApi.fetchFiles({ project: 8, limit: 50 }, { signal })

    expect(http.get).toHaveBeenCalledWith('/projects/8/ai_screen_stats/', {
      timeout: 60000,
      signal,
    })
    expect(http.get).toHaveBeenCalledWith('/projects/8/ai_screen_inputs/', {
      signal,
      params: { limit: 50, offset: 0 },
    })
    expect(http.get).toHaveBeenCalledWith('/review/list/', {
      timeout: 60000,
      signal,
      params: { project: 8, page: 2 },
    })
    expect(http.get).toHaveBeenCalledWith('/files/', {
      signal,
      params: { project: 8, limit: 50 },
    })
  })

  it('scopes import batches to one project and supports failed batch cleanup', async () => {
    await screeningApi.fetchImportBatches(8)
    await screeningApi.retryImportBatch(12)
    await screeningApi.deleteImportBatch(12)

    expect(http.get).toHaveBeenCalledWith('/screening-imports/', {
      params: { project: 8 },
    })
    expect(http.post).toHaveBeenCalledWith('/screening-imports/12/retry/')
    expect(http.delete).toHaveBeenCalledWith('/screening-imports/12/')
  })
})
