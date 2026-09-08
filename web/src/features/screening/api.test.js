import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('@/shared/api/http', () => ({ default: http }))

import * as screeningApi from './api'
import * as workflowApi from '@/shared/api/workflow'

describe('screening API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('encodes review item paths and keeps review routes centralized', async () => {
    await screeningApi.fetchReviewStats(8)
    await screeningApi.updateReviewItem('folder/a b.xml', { decision: 'included' })

    expect(http.get).toHaveBeenCalledWith('/review/stats/', { params: { project: 8 } })
    expect(http.patch).toHaveBeenCalledWith('/review/item/folder%2Fa%20b.xml/', {
      decision: 'included',
    })
  })

  it('forwards abort signals without dropping request parameters', async () => {
    const signal = new AbortController().signal
    await screeningApi.fetchScreeningStats(8, { signal })
    await screeningApi.fetchReviewList({ project: 8, page: 2 }, { signal })
    await workflowApi.fetchFiles({ project: 8, limit: 50 }, { signal })

    expect(http.get).toHaveBeenCalledWith('/projects/8/ai_screen_stats/', { signal })
    expect(http.get).toHaveBeenCalledWith('/review/list/', {
      signal,
      params: { project: 8, page: 2 },
    })
    expect(http.get).toHaveBeenCalledWith('/files/', {
      signal,
      params: { project: 8, limit: 50 },
    })
  })
})
