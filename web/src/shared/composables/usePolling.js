import { onScopeDispose } from 'vue'

export function createPoller(task, options = {}) {
  const interval = options.interval ?? 1000
  const shouldStop = options.shouldStop ?? (() => false)
  const onError = options.onError ?? (() => {})
  let timer = null
  let active = false
  let generation = 0

  const cancel = () => {
    active = false
    generation += 1
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  const schedule = currentGeneration => {
    if (!active || currentGeneration !== generation) return
    timer = setTimeout(() => tick(currentGeneration), interval)
  }

  const tick = async currentGeneration => {
    if (!active || currentGeneration !== generation) return
    try {
      const result = await task()
      if (!active || currentGeneration !== generation) return
      if (shouldStop(result)) cancel()
      else schedule(currentGeneration)
    } catch (error) {
      if (!active || currentGeneration !== generation) return
      onError(error)
      if (options.stopOnError) cancel()
      else schedule(currentGeneration)
    }
  }

  const start = () => {
    cancel()
    active = true
    const currentGeneration = generation
    if (options.immediate === false) schedule(currentGeneration)
    else void tick(currentGeneration)
  }

  return { start, cancel, isActive: () => active }
}

export function usePolling(task, options = {}) {
  const poller = createPoller(task, options)
  onScopeDispose(poller.cancel)
  return poller
}

export async function pollUntil(task, shouldStop, options = {}) {
  const interval = options.interval ?? 1000
  const maxAttempts = options.maxAttempts ?? 120
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (options.signal?.aborted) throw new DOMException('Polling cancelled', 'AbortError')
    const result = await task(attempt)
    if (shouldStop(result)) return result
    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, interval)
      options.signal?.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(new DOMException('Polling cancelled', 'AbortError'))
      }, { once: true })
    })
  }
  throw new Error(options.timeoutMessage || 'Polling timed out')
}
