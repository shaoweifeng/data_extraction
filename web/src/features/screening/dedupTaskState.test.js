import { describe, expect, it } from 'vitest'

import { findLatestDedupTask, getDedupTaskUiState } from './dedupTaskState'

describe('dedup task UI state', () => {
  it('finds the latest dedup task from newest-first task results', () => {
    const task = findLatestDedupTask([
      { id: 9, task_type: 'parse' },
      { id: 8, task_type: 'dedup' },
      { id: 7, task_type: 'dedup' },
    ])
    expect(task.id).toBe(8)
  })

  it('restores active and completed task state', () => {
    expect(getDedupTaskUiState({ status: 'running', progress_percentage: 18 })).toEqual({
      active: true,
      completed: false,
      progress: 18,
      message: '正在扫描文献 18%',
    })
    expect(getDedupTaskUiState({ status: 'completed', progress_percentage: 100 })).toEqual({
      active: false,
      completed: true,
      progress: 100,
      message: '去重完成',
    })
  })
})
