import { describe, expect, it } from 'vitest'
import { pageNumber, stepNumber, safePdfUrl, criteriaLines, toggleSelection, errorMessage, label, decisionLabel, fulltextLabel } from './state'

describe('rescreening state contracts', () => {
  it('distinguishes pending decisions from pending tasks and localizes fulltext status', () => {
    expect(label('pending')).toBe('待处理')
    expect(decisionLabel('pending')).toBe('待定')
    expect(decisionLabel('conflict')).toBe('模型意见不一致')
    expect(fulltextLabel('ready')).toBe('已绑定')
    expect(fulltextLabel('missing')).toBe('未绑定')
    expect(fulltextLabel('extracting')).toBe('提取中')
  })
  it('only enables steps from server state, not from a visited-step counter', () => {
    const state = { steps: [{ index: 1, enabled: true }, { index: 5, enabled: false }] }
    expect(stepNumber(5, state)).toBe(1)
    expect(stepNumber('1', state)).toBe(1)
    expect(stepNumber(1.5, state)).toBe(1)
    state.steps[1].enabled = true
    expect(stepNumber('5', state)).toBe(5)
  })
  it('clamps page jumps and never displays fractional pages', () => {
    expect(pageNumber(9999, 5)).toBe(5)
    expect(pageNumber(-2, 5)).toBe(1)
    expect(pageNumber('3.6', 5)).toBe(3)
    expect(pageNumber('', 0)).toBe(1)
  })
  it('only opens same-origin authenticated PDF endpoints', () => {
    expect(safePdfUrl('/api/fulltext/assets/12/download/', 7)).toContain('#page=7')
    for (const value of ['javascript:alert(1)', 'https://example.com/x.pdf', '//evil.com', '/media/a.pdf']) expect(safePdfUrl(value)).toBe('')
  })
  it('preserves selection across pages with an explicit ceiling', () => {
    expect(toggleSelection([1, 2], 3, 2)).toEqual([1, 2])
    expect(toggleSelection([1, 2], 1, 2)).toEqual([2])
    expect(toggleSelection([1], 3, 2)).toEqual([1, 3])
  })
  it('retains exclusion semantics and supports localized errors', () => {
    expect(criteriaLines(' 排除动物\n\n排除综述 ')).toEqual(['排除动物', '排除综述'])
    expect(errorMessage({ response: { data: { error: '额度不足' } } })).toBe('额度不足')
    expect(errorMessage({ response: { data: { error: { message: '错误' } } } })).toBe('错误')
  })
})
