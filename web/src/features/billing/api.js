import http from '@/shared/api/http'

export const fetchBalance = () => http.get('/billing/balance/')

export const estimateUsage = (refCount, modelIds) =>
  http.get('/billing/estimate/', { params: { ref_count: refCount, model_ids: modelIds } })

export const redeemCode = (code) => http.post('/billing/redeem/', { code })

export const fetchTransactions = (params = {}) => http.get('/billing/transactions/', { params })
