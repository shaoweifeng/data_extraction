import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import * as projectApi from '@/features/projects/api'
import { useProjectStore } from './store'

vi.mock('@/features/projects/api', () => ({
  fetchProjects: vi.fn(),
  fetchStages: vi.fn(),
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  skipStep: vi.fn(),
}))

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

describe('project store request isolation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    projectApi.fetchStages.mockReset()
  })

  it('does not let an old stage response overwrite the current project', async () => {
    const projectOne = deferred()
    const projectTwo = deferred()
    projectApi.fetchStages
      .mockReturnValueOnce(projectOne.promise)
      .mockReturnValueOnce(projectTwo.promise)

    const store = useProjectStore()
    const oldRequest = store.selectProject({ id: 1, name: 'one' })
    const currentRequest = store.selectProject({ id: 2, name: 'two' })

    projectTwo.resolve([{ id: 22, project: 2, stage_key: 'SCREEN_1' }])
    await currentRequest
    projectOne.resolve([{ id: 11, project: 1, stage_key: 'SCREEN_1' }])
    await oldRequest

    expect(store.currentProject.id).toBe(2)
    expect(store.stagesData.map(stage => stage.id)).toEqual([22])
  })

  it('replaces a saved step without leaving stale metadata in stagesData', () => {
    const store = useProjectStore()
    store.stagesData = [{
      id: 10,
      stage_key: 'SCREEN_1',
      steps: [
        { id: 31, step_key: 'criteria', status: 'pending', metadata: { criteria: ['标准 A'] } },
        { id: 32, step_key: 'ai_screen', status: 'pending', metadata: {} },
      ],
    }]

    const replaced = store.replaceStep({
      id: 31,
      step_key: 'criteria',
      status: 'completed',
      metadata: { criteria: ['标准 A', '标准 B', '标准 C'] },
    })

    expect(replaced).toBe(true)
    expect(store.stagesData[0].steps[0]).toMatchObject({
      status: 'completed',
      metadata: { criteria: ['标准 A', '标准 B', '标准 C'] },
    })
    expect(store.stagesData[0].steps[1].step_key).toBe('ai_screen')
  })
})
