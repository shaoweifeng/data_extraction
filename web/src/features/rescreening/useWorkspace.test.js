import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRescreenWorkspace } from './useWorkspace'
import { emptyPage } from './state'

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function info(id, polling = false) {
  return { project_id: id, latest_run_id: null, active_run_id: null, poll_required: polling,
    configuration: { version: 1, criteria: [{ id: 'C1', text: 'exclude' }], model_ids: [] },
    capabilities: { max_run: 3 }, steps: Array.from({ length: 6 }, (_, index) => ({ index: index+1, enabled: true, completed: false })) }
}
function fakeApi() {
  return { workspace: vi.fn(async id => info(id)), references: vi.fn(async (_id, params) => ({ ...emptyPage(), ...params })),
    models: vi.fn(async () => []), run: vi.fn(async id => ({ id, status: 'completed' })),
    runItems: vi.fn(async () => emptyPage()), imports: vi.fn(async () => emptyPage()),
    assets: vi.fn(async () => emptyPage()), lookups: vi.fn(async () => emptyPage()),
    runs: vi.fn(async () => emptyPage()), exports: vi.fn(async () => emptyPage()), lookupItems: vi.fn(async () => emptyPage()),
    review: vi.fn(async id => ({ id, suggestion_id: null })), item: vi.fn(), history: vi.fn(async () => emptyPage()) }
}
afterEach(() => vi.useRealTimers())

describe('rescreen workspace controller', () => {
  it('does not reopen a reference after closing its drawer or selecting an empty filter', async () => {
    const api = fakeApi(), ws = createRescreenWorkspace(api)
    await ws.initialize(1)
    const slow = deferred()
    api.review.mockReturnValue(slow.promise)
    const selecting = ws.selectReference(42)
    ws.clearReference()
    slow.resolve({ id: 42, suggestion_id: 50 })
    await selecting
    expect(ws.state.detail).toBeNull()
    expect(ws.state.aiDetail).toBeNull()
    expect(api.item).not.toHaveBeenCalled()
    ws.dispose()
  })
  it('refreshes exports on step 6 and discards old-project export responses', async () => {
    const api = fakeApi(), ws = createRescreenWorkspace(api)
    await ws.initialize(1, '6')
    await ws.refresh()
    expect(api.exports).toHaveBeenCalledWith(1, { page: 1, page_size: 50 })
    const slow = deferred()
    api.exports.mockImplementation(id => id === 1 ? slow.promise : Promise.resolve(emptyPage()))
    const loading = ws.loadExports(2)
    await ws.initialize(2, '6')
    slow.resolve({ ...emptyPage(), items: [{ id: 99 }] })
    await loading
    expect(ws.state.exports.items).toEqual([])
    ws.dispose()
  })
  it('recovers requested step from server gates on reload', async () => {
    const ws = createRescreenWorkspace(fakeApi())
    await ws.initialize(1, '5')
    expect(ws.state.step).toBe(5)
    expect(ws.state.refs.page_size).toBe(50)
    ws.dispose()
  })
  it('restores the server active run instead of a local browser completion flag', async () => {
    const api = fakeApi()
    api.workspace.mockResolvedValue({ ...info(1), active_run_id: 42 })
    const ws = createRescreenWorkspace(api)
    await ws.initialize(1)
    expect(ws.state.runId).toBe(42)
    expect(api.run).toHaveBeenCalledWith(42)
    ws.dispose()
  })
  it('discards responses from a previous project', async () => {
    const slow = deferred()
    const api = fakeApi()
    api.workspace.mockImplementation(id => id === 1 ? slow.promise : Promise.resolve(info(id)))
    const ws = createRescreenWorkspace(api)
    const first = ws.initialize(1)
    await ws.initialize(2)
    slow.resolve(info(1))
    await first
    expect(ws.state.projectId).toBe(2)
    expect(ws.state.info.project_id).toBe(2)
    expect(api.references.mock.calls.map(row => row[0])).toEqual([2])
    ws.dispose()
  })
  it('keeps the most recently requested page when responses arrive out of order', async () => {
    const api = fakeApi()
    const ws = createRescreenWorkspace(api)
    await ws.initialize(1)
    const slow = deferred()
    api.references.mockImplementation((_id, params) => params.page === 2 ? slow.promise : Promise.resolve({ ...emptyPage(), page: params.page }))
    const first = ws.loadReferences(2)
    await ws.loadReferences(3)
    slow.resolve({ ...emptyPage(), page: 2 })
    await first
    expect(ws.state.refs.page).toBe(3)
    ws.dispose()
  })
  it('a late detail cannot replace the next selected reference or its AI evidence', async () => {
    const api = fakeApi(), slow = deferred()
    api.review.mockImplementation(id => id === 1 ? slow.promise : Promise.resolve({ id, suggestion_id: null }))
    const ws = createRescreenWorkspace(api)
    await ws.initialize(1)
    const first = ws.selectReference(1)
    await ws.selectReference(2)
    slow.resolve({ id: 1, suggestion_id: 123 })
    await first
    expect(ws.state.detail.id).toBe(2)
    expect(api.item).not.toHaveBeenCalled()
    ws.dispose()
  })
  it('failed requests show errors and do not invent a successful import', async () => {
    const ws = createRescreenWorkspace(fakeApi())
    await ws.initialize(1)
    const result = await ws.action(() => Promise.reject({ response: { data: { error: '文件过大' } } }))
    expect(result).toBeNull()
    expect(ws.state.error).toBe('文件过大')
    expect(ws.state.refs.items).toEqual([])
    ws.dispose()
  })
  it('blocks duplicate mutations and keeps idempotency keys after a lost response', async () => {
    const ws = createRescreenWorkspace(fakeApi())
    await ws.initialize(1)
    const pending = deferred()
    const first = ws.action(() => pending.promise)
    const second = vi.fn()
    await ws.action(second)
    expect(second).not.toHaveBeenCalled()
    pending.resolve('ok'); await first
    let key
    await expect(ws.keyed('start', { ids: [1] }, async value => { key = value; throw new Error('network lost') })).rejects.toThrow()
    await ws.keyed('start', { ids: [1] }, async value => expect(value).toBe(key))
    ws.dispose()
  })
  it('polls while the server has active work and stops on terminal state', async () => {
    vi.useFakeTimers()
    const api = fakeApi()
    api.workspace.mockResolvedValueOnce(info(1, true)).mockResolvedValue(info(1, false))
    const ws = createRescreenWorkspace(api)
    await ws.initialize(1)
    await vi.advanceTimersByTimeAsync(2501)
    expect(api.workspace).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(10000)
    expect(api.workspace).toHaveBeenCalledTimes(2)
    ws.dispose()
  })
  it('never writes results or restarts polling after disposal', async () => {
    const slow = deferred(), api = fakeApi()
    api.workspace.mockReturnValue(slow.promise)
    const ws = createRescreenWorkspace(api)
    const loading = ws.initialize(1)
    ws.dispose()
    slow.resolve(info(1, true)); await loading
    expect(ws.state.info).toBeNull()
    expect(api.references).not.toHaveBeenCalled()
  })
  it('preserves explicit cross-page selections and never loads all references', async () => {
    const api = fakeApi(), ws = createRescreenWorkspace(api)
    await ws.initialize(1)
    ws.state.refs.items = [{ id: 1, ai_ready: true }, { id: 2, ai_ready: false }]
    ws.selectPage(true)
    ws.state.refs.items = [{ id: 3, ai_ready: true }]
    ws.selectPage(true)
    expect(ws.state.selected).toEqual([1, 3])
    expect(api.references).toHaveBeenCalledTimes(1)
    ws.dispose()
  })
  it('does not drop component initialization reads while a navigation or mutation is pending', async () => {
    const api = fakeApi(), pending = deferred(), ws = createRescreenWorkspace(api)
    await ws.initialize(1)
    const mutation = ws.action(() => pending.promise)
    await ws.read(() => ws.loadRuns())
    expect(api.runs).toHaveBeenCalledOnce()
    pending.resolve('ok'); await mutation
    ws.dispose()
  })
})
