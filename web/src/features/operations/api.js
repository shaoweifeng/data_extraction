import http from '@/shared/api/http'

export const fetchSystemStatus = () => http.get('/system/status/').then(res => res.data)

export const sendHeartbeat = payload => (
  http.post('/presence/heartbeat/', payload).then(res => res.data)
)

export const fetchOperationsStatus = (inspectCelery = true) => (
  http.get('/operations/status/', { params: { inspect_celery: inspectCelery } }).then(res => res.data)
)

export const changeSystemState = payload => (
  http.post('/operations/state/', payload).then(res => res.data)
)

export const pauseMaintenanceTasks = () => (
  http.post('/operations/tasks/pause/').then(res => res.data)
)

export const resumeMaintenanceTasks = () => (
  http.post('/operations/tasks/resume/').then(res => res.data)
)
