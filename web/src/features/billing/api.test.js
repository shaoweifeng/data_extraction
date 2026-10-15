import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/shared/api/http', () => ({ default: http }))

import {
  fetchBalance,
  fetchCreditBatches,
  fetchPlans,
  fetchServiceContact,
  fetchTransactions,
  redeemCode,
} from './api'

describe('billing API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads the account portal resources', async () => {
    http.get.mockResolvedValue({ data: {} })

    await fetchBalance()
    await fetchPlans()
    await fetchCreditBatches({ page: 2 })
    await fetchTransactions({ page: 3 })
    await fetchServiceContact()

    expect(http.get).toHaveBeenNthCalledWith(1, '/billing/balance/')
    expect(http.get).toHaveBeenNthCalledWith(2, '/billing/plans/')
    expect(http.get).toHaveBeenNthCalledWith(3, '/billing/batches/', { params: { page: 2 } })
    expect(http.get).toHaveBeenNthCalledWith(4, '/billing/transactions/', { params: { page: 3 } })
    expect(http.get).toHaveBeenNthCalledWith(5, '/billing/service-contact/')
  })

  it('redeems a normalized code', async () => {
    http.post.mockResolvedValue({ data: { message: 'ok' } })

    await redeemCode('PLAN-TEST')

    expect(http.post).toHaveBeenCalledWith('/billing/redeem/', { code: 'PLAN-TEST' })
  })
})
