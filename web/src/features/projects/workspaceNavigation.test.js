import { describe, expect, it } from 'vitest'
import { inferQualityMaxStep, isQualityNextDisabled, qualityFooterTip } from './workspaceNavigation'

describe('workspace navigation', () => {
  it('infers the unlocked quality step from project-scoped references', () => {
    expect(inferQualityMaxStep([])).toBe(1)
    expect(inferQualityMaxStep([{ quality_method: 'ROB2' }])).toBe(3)
    expect(inferQualityMaxStep([{ quality_method: 'ROB2', ai_eval_status: 'completed', review_status: 'partial' }])).toBe(5)
  })

  it('keeps navigation guards and footer summaries deterministic', () => {
    const refs = [{ quality_method: 'ROB2', review_status: 'confirmed' }, { quality_method: null }]
    expect(isQualityNextDisabled(2, refs)).toBe(false)
    expect(isQualityNextDisabled(3, refs, false)).toBe(true)
    expect(qualityFooterTip(4, refs)).toBe('1 / 2 篇已确认')
  })
})
