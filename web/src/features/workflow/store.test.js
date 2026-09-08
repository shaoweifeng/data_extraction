import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import * as workflowApi from '@/shared/api/workflow'
import { useTaskStore } from './store'

vi.mock('@/shared/api/workflow', () => ({
  fetchTasks: vi.fn(),
  fetchTaskLogs: vi.fn(),
  fetchActivityLogs: vi.fn(),
}))

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

describe('task store project isolation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    workflowApi.fetchTasks.mockReset()
    workflowApi.fetchActivityLogs.mockReset()
  })

  it('ignores a previous project response that arrives after the active project', async () => {
    const projectOne = deferred()
    const projectTwo = deferred()
    workflowApi.fetchTasks
      .mockReturnValueOnce(projectOne.promise)
      .mockReturnValueOnce(projectTwo.promise)

    const store = useTaskStore()
    const oldRequest = store.fetchRecentTasks(1)
    const currentRequest = store.fetchRecentTasks(2)

    projectTwo.resolve({ data: [{ id: 202, project: 2, task_type: 'ai_screen', status: 'running' }] })
    await currentRequest
    projectOne.resolve({ data: [{ id: 101, project: 1, task_type: 'ai_screen', status: 'running' }] })
    await oldRequest

    expect(store.activeProjectId).toBe(2)
    expect(store.recentTasks.map(task => task.id)).toEqual([202])
    expect(store.latestAiScreenTask.id).toBe(202)
  })

  it('clears the previous AI task when the current project has no AI task', async () => {
    workflowApi.fetchTasks
      .mockResolvedValueOnce({ data: [{ id: 101, project: 1, task_type: 'ai_screen', status: 'running' }] })
      .mockResolvedValueOnce({ data: [{ id: 203, project: 2, task_type: 'parse', status: 'completed' }] })

    const store = useTaskStore()
    await store.fetchRecentTasks(1)
    await store.fetchRecentTasks(2)

    expect(store.latestAiScreenTask).toBeNull()
    expect(store.recentTasks.map(task => task.id)).toEqual([203])
  })
})
