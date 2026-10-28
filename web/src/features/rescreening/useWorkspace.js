import { reactive } from 'vue'
import * as defaultApi from './api'
import { emptyPage, errorMessage, toggleSelection, stepNumber } from './state'

/** Project generation + per-resource epochs discard out-of-order responses. */
export function createRescreenWorkspace(api = defaultApi) {
  const state = reactive({
    projectId: null,
    info: null,
    loading: false,
    working: false,
    error: '',
    notice: '',
    refs: emptyPage(),
    imports: emptyPage(),
    assets: emptyPage(),
    lookups: emptyPage(),
    lookupItems: emptyPage(),
    runs: emptyPage(),
    runItems: emptyPage(),
    history: emptyPage(),
    exports: emptyPage(),
    selected: [],
    detail: null,
    aiDetail: null,
    run: null,
    runId: null,
    lookupId: null,
    source: null,
    models: [],
    estimate: null,
    uploadProgress: null,
    filters: { q: '', status: '' },
    step: 1,
  })
  let generation = 0
  const epochs = {}
  let timer = null
  let disposed = false
  const keys = new Map()
  function stopPolling() {
    clearTimeout(timer)
    timer = null
  }
  function dispose() {
    disposed = true
    generation++
    stopPolling()
  }
  async function resource(name, fetcher) {
    const stamp = generation
    const epoch = (epochs[name] = (epochs[name] || 0) + 1)
    let value
    try { value = await fetcher() } catch (error) {
      if (disposed || stamp !== generation || epoch !== epochs[name]) return null
      throw error
    }
    if (disposed || stamp !== generation || epoch !== epochs[name]) return null
    state[name] = value
    return value
  }
  async function initialize(projectId, requestedStep = 1) {
    stopPolling()
    generation++
    disposed = false
    Object.assign(state, {
      projectId,
      info: null,
      loading: true,
      error: '',
      notice: '',
      selected: [],
      detail: null,
      aiDetail: null,
      run: null,
      runId: null,
      lookupId: null,
      source: null,
      estimate: null,
      working: false,
      uploadProgress: null,
      filters: { q: '', status: '' },
      step: 1,
      dirty: false,
      promptDirty: false,
      reviewDirty: false,
      modelDirty: false,
    })
    for (const key of [
      'refs',
      'imports',
      'assets',
      'lookups',
      'lookupItems',
      'runs',
      'runItems',
      'history',
      'exports',
    ])
      state[key] = emptyPage()
    const stamp = generation
    try {
      await resource('info', () => api.workspace(projectId))
      if (stamp !== generation || disposed) return
      state.step = stepNumber(requestedStep, state.info)
      if (state.step === 4) state.filters.status = 'ready'
      await Promise.all([
        loadReferences(1),
        resource('models', () => api.models()),
      ])
      if (stamp !== generation || disposed) return
      await loadRun(state.info.active_run_id || state.info.latest_run_id)
    } catch (error) {
      if (stamp === generation && !disposed) state.error = errorMessage(error)
    } finally {
      if (stamp === generation && !disposed) {
        state.loading = false
        schedule()
      }
    }
  }
  const loadReferences = (
    page = state.refs.page,
    size = state.refs.page_size,
  ) =>
    resource('refs', () =>
      api.references(state.projectId, {
        ...state.filters,
        page,
        page_size: size,
      }),
    )
  const loadImports = (
    page = state.imports.page,
    size = state.imports.page_size,
  ) =>
    resource('imports', () =>
      api.imports(state.projectId, { page, page_size: size }),
    )
  const loadAssets = (
    page = state.assets.page,
    size = state.assets.page_size,
  ) =>
    resource('assets', () =>
      api.assets(state.projectId, { page, page_size: size }),
    )
  const loadLookups = (
    page = state.lookups.page,
    size = state.lookups.page_size,
  ) =>
    resource('lookups', () =>
      api.lookups(state.projectId, { page, page_size: size }),
    )
  const loadRuns = (page = state.runs.page, size = state.runs.page_size) =>
    resource('runs', () => api.runs(state.projectId, { page, page_size: size }))
  const loadExports = (page = state.exports.page, size = state.exports.page_size) =>
    resource('exports', () => api.exports(state.projectId, { page, page_size: size }))
  const loadRunItems = (
    page = state.runItems.page,
    size = state.runItems.page_size,
  ) =>
    state.runId
      ? resource('runItems', () =>
          api.runItems(state.runId, { page, page_size: size }),
        )
      : Promise.resolve()
  async function loadRun(id) {
    state.runId = id || null
    epochs.run = (epochs.run || 0) + 1
    if (!id) {
      state.run = null
      state.runItems = emptyPage()
      return
    }
    await resource('run', () => api.run(id))
    if (state.runId === id) await loadRunItems(1)
  }
  async function loadLookup(id, page = 1, size = 50) {
    state.lookupId = id
    return resource('lookupItems', () =>
      api.lookupItems(id, { page, page_size: size }),
    )
  }
  async function selectReference(id) {
    state.detail = null
    state.aiDetail = null
    state.history = emptyPage()
    epochs.aiDetail = (epochs.aiDetail || 0) + 1
    const detail = await resource('detail', () => api.review(id))
    if (detail?.suggestion_id)
      await resource('aiDetail', () => api.item(detail.suggestion_id))
    return detail
  }
  const loadHistory = (page = 1, size = 50) =>
    state.detail
      ? resource('history', () =>
          api.history(state.detail.id, { page, page_size: size }),
        )
      : Promise.resolve()
  async function refresh() {
    const stamp = generation
    const projectId = state.projectId
    await resource('info', () => api.workspace(projectId))
    if (stamp !== generation || disposed) return
    await Promise.all([
      loadReferences(),
      ...(state.step === 1 ? [loadImports()] : []),
      ...(state.step === 2 ? [loadAssets(), loadLookups()] : []),
      ...(state.step === 4 ? [loadRuns()] : []),
      ...(state.step === 6 ? [loadExports()] : []),
    ])
    if (stamp !== generation || disposed) return
    if (!state.runId && state.info.latest_run_id)
      await loadRun(state.info.latest_run_id)
    else if (state.runId) {
      await resource('run', () => api.run(state.runId))
      if (stamp === generation && !disposed) await loadRunItems()
    }
    if (state.lookupId)
      await loadLookup(
        state.lookupId,
        state.lookupItems.page,
        state.lookupItems.page_size,
      )
  }
  function schedule() {
    stopPolling()
    const stamp = generation
    if (!disposed && state.info?.poll_required)
      timer = setTimeout(async () => {
        try {
          await refresh()
        } catch (error) {
          if (stamp === generation && !disposed)
            state.error = errorMessage(error)
        } finally {
          if (stamp === generation && !disposed) schedule()
        }
      }, 2500)
  }
  async function action(callback, message = '', refreshAfter = true) {
    if (state.working) return null
    state.working = true
    state.error = ''
    state.notice = ''
    const stamp = generation
    try {
      const result = await callback()
      if (stamp !== generation || disposed) return null
      if (message) state.notice = message
      if (refreshAfter) await refresh()
      return result
    } catch (error) {
      if (stamp === generation && !disposed) state.error = errorMessage(error)
      return null
    } finally {
      if (stamp === generation && !disposed) {
        state.working = false
        schedule()
      }
    }
  }
  async function keyed(name, payload, callback) {
    const fingerprint = JSON.stringify([state.projectId, name, payload])
    if (!keys.has(fingerprint))
      keys.set(
        fingerprint,
        globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      )
    const result = await callback(keys.get(fingerprint))
    keys.delete(fingerprint)
    return result
  }
  async function upload(files, pdf, createReferences) {
    const projectId = state.projectId
    return action(
      () =>
        keyed(
          'upload',
          files.map((file) => [file.name, file.size, file.lastModified]),
          (key) =>
            api.upload(
              projectId,
              files,
              pdf,
              createReferences,
              key,
              (value) => {
                if (state.projectId === projectId) state.uploadProgress = value
              },
            ),
        ),
      '上传已接收，正在后台处理。',
    )
  }
  async function estimate(payload) {
    state.estimate = null
    return action(
      () => resource('estimate', () => api.estimate(state.projectId, payload)),
      '',
      false,
    )
  }
  async function start(payload) {
    return action(async () => {
      const stamp = generation
      const result = await keyed('start', payload, (key) =>
        api.start(state.projectId, payload, key),
      )
      if (stamp === generation && !disposed) await loadRun(result.id)
      return result
    }, '任务已创建，可离开页面，返回后继续查看。')
  }
  function toggle(id) {
    state.selected = toggleSelection(
      state.selected,
      id,
      selectionLimit(),
    )
    state.estimate = null
  }
  function selectPage(readyOnly = false) {
    const ids = state.refs.items
      .filter((row) => !readyOnly || row.ai_ready)
      .map((row) => row.id)
    state.selected = [...new Set([...state.selected, ...ids])].slice(
      0,
      selectionLimit(),
    )
    state.estimate = null
  }
  function selectionLimit() { return state.step === 2 ? state.info?.capabilities.max_lookup || 50 : state.info?.capabilities.max_run || 1000 }
  async function read(callback) {
    const stamp = generation
    try {
      const value = await callback()
      return stamp === generation && !disposed ? value : null
    } catch (error) {
      if (stamp === generation && !disposed) state.error = errorMessage(error)
      return null
    }
  }
  return {
    state,
    api,
    initialize,
    dispose,
    action,
    read,
    refresh,
    keyed,
    upload,
    estimate,
    start,
    toggle,
    selectPage,
    loadReferences,
    loadExports,
    loadImports,
    loadAssets,
    loadLookups,
    loadRuns,
    loadRun,
    loadRunItems,
    loadLookup,
    selectReference,
    loadHistory,
    schedule,
    stopPolling,
  }
}
