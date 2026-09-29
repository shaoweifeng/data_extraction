import { describe, expect, it } from 'vitest'

import { exportFileLabel } from './format'


describe('exportFileLabel', () => {
  it.each([
    ['all', '全部'],
    ['included', '纳入'],
    ['excluded', '排除'],
  ])('在导出版本标签中保留 %s 范围', (scope, label) => {
    const result = exportFileLabel({
      filename: `screening_results_${scope}_deepseek_20260929_140500.xml`,
    })

    expect(result).toBe(`${label} · deepseek  2026-09-29 14:05`)
  })
})
