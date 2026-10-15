import http from '@/shared/api/http'

export const fetchBalance = () => http.get('/billing/balance/')

export const estimateUsage = (refCount, modelIds, feature = 'ai_screen') =>
  http.get('/billing/estimate/', {
    params: { ref_count: refCount, model_ids: modelIds, feature },
  })

export const redeemCode = (code) => http.post('/billing/redeem/', { code })

export const fetchTransactions = (params = {}) => http.get('/billing/transactions/', { params })

export const fetchPlans = () => http.get('/billing/plans/')

export const fetchCreditBatches = (params = {}) => http.get('/billing/batches/', { params })

export const fetchServiceContact = () => http.get('/billing/service-contact/')
