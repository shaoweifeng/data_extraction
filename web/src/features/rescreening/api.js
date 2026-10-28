import http from '@/shared/api/http'

const root = '/rescreening'
const read = async (request) => {
  const response = await request
  return response.data.data
}
const get = (path, params) => read(http.get(`${root}/${path}`, { params }))
const post = (path, payload, key, timeout = 60000) =>
  read(
    http.post(`${root}/${path}`, payload, {
      timeout,
      ...(key ? { headers: { 'Idempotency-Key': key } } : {}),
    }),
  )
export const workspace = (projectId) =>
  get('workspace/', { project_id: projectId })
export const references = (projectId, params = {}) =>
  get('workspace/references/', { project_id: projectId, ...params })
export const configuration = (projectId, payload) =>
  post('configuration/', { project_id: projectId, ...payload })
export const preview = (projectId) =>
  get('imports/preview/', { project_id: projectId })
export const importScreening = (projectId, fingerprint, key) =>
  post(
    'imports/from-screening/',
    { project_id: projectId, source_fingerprint: fingerprint },
    key,
  )
export const imports = (projectId, params = {}) =>
  get('imports/', { project_id: projectId, ...params })
export const importDetail = (id) => get(`imports/${id}/`)
export const importAction = (id, action) => post(`imports/${id}/${action}/`, {})
export const remove = (projectId, ids, revision) =>
  post('references/remove/', {
    project_id: projectId,
    ids,
    expected_revision: revision,
  })
export const assets = (projectId, params = {}) =>
  read(
    http.get('/fulltext/assets/', {
      params: { project_id: projectId, ...params },
    }),
  )
export const assetAction = (id, action) =>
  read(http.post(`/fulltext/assets/${id}/${action}/`, {}))
export const binding = (id, payload) =>
  payload
    ? post(`references/${id}/fulltext/`, payload)
    : get(`references/${id}/fulltext/`)
export const lookups = (projectId, params = {}) =>
  get('lookups/', { project_id: projectId, ...params })
export const lookupItems = (id, params = {}) =>
  get(`lookups/${id}/items/`, params)
export const lookupStart = (projectId, payload, key) =>
  post('lookups/start/', { project_id: projectId, ...payload }, key)
export const lookupAction = (id, action) => post(`lookups/${id}/${action}/`, {})
export const confirmCandidate = (id, version) =>
  post(`candidates/${id}/confirm/`, { expected_version: version })
export const estimate = (projectId, payload) =>
  post('ai/estimate/', { project_id: projectId, ...payload }, null, 120000)
export const start = (projectId, payload, key) =>
  post('ai/start/', { project_id: projectId, ...payload }, key, 120000)
export const runs = (projectId, params = {}) =>
  get('ai/runs/', { project_id: projectId, ...params })
export const run = (id) => get(`ai/runs/${id}/`)
export const runItems = (id, params = {}) => get(`ai/runs/${id}/items/`, params)
export const runAction = (id, action, payload = {}) =>
  post(`ai/runs/${id}/${action}/`, payload)
export const item = (id) => get(`ai/items/${id}/`)
export const review = (id) => get(`references/${id}/review/`)
export const saveReview = (id, payload) =>
  post(`references/${id}/review/`, payload)
export const history = (id, params = {}) =>
  get(`references/${id}/review/history/`, params)
export const models = async () => (await http.get('/ai-models/')).data
export const exports = (projectId, params = {}) => get('exports/', { project_id: projectId, ...params })
export const startExport = (projectId, payload, key) => post('exports/', { project_id: projectId, ...payload }, key, 120000)
export const cancelExport = (id) => post(`exports/${id}/cancel/`, {})
export const purgeExport = (id) => post(`exports/${id}/purge/`, {})
export const skipExport = (projectId, payload, key) => post('exports/skip/', {project_id: projectId, ...payload}, key)
export const qaPreview = (projectId) => get('qa-handoff/', { project_id: projectId })
export const qaHandoff = (projectId, payload) => post('qa-handoff/', { project_id: projectId, ...payload }, null, 120000)

export const upload = (
  projectId,
  files,
  pdf,
  createReferences,
  key,
  onProgress,
) => {
  const form = new FormData()
  form.append('project_id', projectId)
  if (pdf) form.append('create_references', String(createReferences))
  files.forEach((file) => form.append('files', file, file.name))
  return read(
    http.post(
      pdf ? '/fulltext/assets/upload/' : `${root}/imports/upload/`,
      form,
      {
        timeout: 120000,
        headers: {
          'Content-Type': undefined,
          ...(key ? { 'Idempotency-Key': key } : {}),
        },
        onUploadProgress: (event) =>
          onProgress?.(
            event.total ? Math.round((event.loaded / event.total) * 100) : 0,
          ),
      },
    ),
  )
}
