import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('@/shared/api/http', () => ({ default: http }))

import * as qualityApi from './api'

describe('quality API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('keeps the established QA route contract', async () => {
    await qualityApi.fetchRefs(42)
    await qualityApi.startEvaluation({ project_id: 42, ref_ids: [7] })
    await qualityApi.fetchChartSettings(42, 'ROB2')

    expect(http.get).toHaveBeenNthCalledWith(1, '/qa/refs/', { params: { project_id: 42 } })
    expect(http.post).toHaveBeenCalledWith('/qa/eval/start/', { project_id: 42, ref_ids: [7] })
    expect(http.get).toHaveBeenNthCalledWith(2, '/qa/chart/settings/', {
      params: { project_id: 42, quality_method: 'ROB2' },
    })
  })
})
