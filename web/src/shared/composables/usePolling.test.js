import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPoller, pollUntil } from './usePolling'

describe('polling', () => {
  afterEach(() => vi.useRealTimers())

  it('stops scheduling after cancel', async () => {
    vi.useFakeTimers()
    const task = vi.fn().mockResolvedValue(null)
    const poller = createPoller(task, { interval: 100 })
    poller.start()
    await vi.runOnlyPendingTimersAsync()
    poller.cancel()
    const calls = task.mock.calls.length
    await vi.advanceTimersByTimeAsync(1000)
    expect(task).toHaveBeenCalledTimes(calls)
    expect(poller.isActive()).toBe(false)
  })

  it('pollUntil returns as soon as the terminal state arrives', async () => {
    vi.useFakeTimers()
    const task = vi.fn()
      .mockResolvedValueOnce({ status: 'running' })
      .mockResolvedValueOnce({ status: 'completed' })
    const promise = pollUntil(task, result => result.status === 'completed', { interval: 10 })
    await vi.runAllTimersAsync()
    await expect(promise).resolves.toEqual({ status: 'completed' })
    expect(task).toHaveBeenCalledTimes(2)
  })

  it('ignores completion from a cancelled generation', async () => {
    let resolveFirst
    const first = new Promise(resolve => { resolveFirst = resolve })
    const task = vi.fn().mockReturnValueOnce(first).mockResolvedValue('new-project')
    const poller = createPoller(task, { interval: 100, shouldStop: value => value === 'new-project' })
    poller.start()
    poller.start()
    await Promise.resolve()
    resolveFirst('old-project')
    await Promise.resolve()
    await Promise.resolve()
    expect(task).toHaveBeenCalledTimes(2)
    expect(poller.isActive()).toBe(false)
  })
})
