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
    await qualityApi.retryFulltext(18)
    await qualityApi.fetchChartSettings(42, 'ROB2')
    await qualityApi.batchSetMethod([7, 8], 'NOS', 'case_control')

    expect(http.get).toHaveBeenNthCalledWith(1, '/qa/refs/', { params: { project_id: 42 } })
    expect(http.post).toHaveBeenCalledWith('/qa/eval/start/', { project_id: 42, ref_ids: [7] })
    expect(http.post).toHaveBeenCalledWith('/qa/fulltext-assets/18/retry/')
    expect(http.get).toHaveBeenNthCalledWith(2, '/qa/chart/settings/', {
      params: { project_id: 42, quality_method: 'ROB2' },
    })
    expect(http.post).toHaveBeenCalledWith('/qa/refs/batch-method/', {
      ref_ids: [7, 8],
      quality_method: 'NOS',
      quality_method_variant: 'case_control',
    })
  })
})
