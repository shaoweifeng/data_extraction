import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  fulltextActionsForStatus,
  fulltextLabelForStatus,
  useRescreenStore,
} from './store'
import { mockRescreenRefs } from './mock'

function seedMockRefs(store) {
  store.refs = JSON.parse(JSON.stringify(mockRescreenRefs))
  store.activeRefId = store.refs[0]?.id || null
}

describe('rescreening store', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('keeps fulltext status actions aligned with the PRD', () => {
    expect(fulltextLabelForStatus('bound')).toBe('已绑定')
    expect(fulltextLabelForStatus('unbound')).toBe('未绑定')
    expect(fulltextLabelForStatus('bind_failed')).toBe('绑定失败')
    expect(fulltextActionsForStatus('bound')).toEqual(['view', 'replace'])
    expect(fulltextActionsForStatus('unbound')).toEqual(['upload'])
    expect(fulltextActionsForStatus('bind_failed')).toEqual(['upload'])
  })

  it('starts with an empty rescreening reference list before upload/import', () => {
    const store = useRescreenStore()
    expect(store.refs).toEqual([])
    expect(store.totalRefs).toBe(0)
  })

  it('auto-search binds found fulltexts without creating a manual candidate confirmation state', async () => {
    const store = useRescreenStore()
    seedMockRefs(store)
    expect(store.refs.find(item => item.id === 2).fulltext_status).toBe('unbound')

    store.autoSearchFulltext()
    expect(store.fulltextSearching).toBe(true)
    await vi.runAllTimersAsync()

    expect(store.fulltextSearching).toBe(false)
    expect(store.refs.find(item => item.id === 2).fulltext_status).toBe('bound')
    expect(store.refs.map(item => item.fulltext_status).sort()).toEqual([
      'bind_failed',
      'bound',
      'bound',
      'bound',
    ])
  })

  it('runs AI only for bound fulltexts and skips unbound or failed items', async () => {
    const store = useRescreenStore()
    seedMockRefs(store)

    store.runAiRescreen()
    expect(store.refs.find(item => item.id === 1).ai_status).toBe('running')
    expect(store.refs.find(item => item.id === 2).ai_status).toBe('skipped_unbound')
    expect(store.refs.find(item => item.id === 3).ai_status).toBe('skipped_unbound')

    await vi.runAllTimersAsync()
    expect(store.aiRunning).toBe(false)
    expect(store.aiProgress).toBe(100)
    expect(store.refs.find(item => item.id === 1).ai_status).toBe('completed')
    expect(store.refs.find(item => item.id === 3).ai_status).toBe('skipped_unbound')
  })

  it('batch-includes only AI consistent included papers', () => {
    const store = useRescreenStore()
    seedMockRefs(store)

    store.batchIncludeConsistent()

    expect(store.refs.find(item => item.id === 1).human_decision).toBe('included')
    expect(store.refs.find(item => item.id === 4).human_decision).toBe('')
    expect(store.refs.find(item => item.id === 2).human_decision).toBe('')
  })

  it('blocks final export until every paper is reviewed and excluded papers have reasons', () => {
    const store = useRescreenStore()
    seedMockRefs(store)
    expect(store.exportBlockingMessages).toContain('还有 4 篇文献未完成人工审阅')

    store.refs.forEach(item => {
      store.saveHumanDecision(item.id, item.id === 2 ? 'excluded' : 'included')
    })
    expect(store.exportBlockingMessages).toContain('还有 1 篇排除文献缺少排除理由')

    store.saveHumanDecision(2, 'excluded', '无全文，无法完成全文复筛判断')
    expect(store.exportBlockingMessages).toEqual([])
  })
})
