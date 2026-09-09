import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/shared/api/http', () => ({ default: http }))

import * as operationsApi from './api'

describe('operations API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    http.get.mockResolvedValue({ data: {} })
    http.post.mockResolvedValue({ data: {} })
  })

  it('uses the system and administrator operations routes', async () => {
    await operationsApi.fetchSystemStatus()
    await operationsApi.sendHeartbeat({ tab_id: 'tab-1' })
    await operationsApi.fetchOperationsStatus(false)
    await operationsApi.changeSystemState({ mode: 'draining' })

    expect(http.get).toHaveBeenNthCalledWith(1, '/system/status/')
    expect(http.post).toHaveBeenNthCalledWith(1, '/presence/heartbeat/', { tab_id: 'tab-1' })
    expect(http.get).toHaveBeenNthCalledWith(2, '/operations/status/', { params: { inspect_celery: false } })
    expect(http.post).toHaveBeenNthCalledWith(2, '/operations/state/', { mode: 'draining' })
  })
})
