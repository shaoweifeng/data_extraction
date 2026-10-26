import { describe, expect, it } from 'vitest'
import { addonConsultationDetails, selectAddonProducts } from './products'

const rows = [
  { code: 'CREDIT_50K', kind: 'CREDIT', credits: 50000, valid_months: 12 },
  { code: 'TRIAL_5K', kind: 'TRIAL', credits: 5000, valid_months: 12 },
  { code: 'SLOTS_8', kind: 'CONCURRENCY', target_slots: 8, valid_months: 1 },
]
describe('billing add-on product display', () => {
  it('prioritizes trial credits for free users and subscription packs for subscribers', () => {
    expect(selectAddonProducts(rows, 'credits', { plan_code: 'FREE' }).map(item => item.code)).toEqual(['TRIAL_5K', 'CREDIT_50K'])
    expect(selectAddonProducts(rows, 'credits', { plan_code: 'LITE' }).map(item => item.code)).toEqual(['CREDIT_50K', 'TRIAL_5K'])
    expect(rows[0].code).toBe('CREDIT_50K')
  })
  it('keeps concurrency separate from credits', () => {
    expect(selectAddonProducts(rows, 'concurrency')).toEqual([rows[2]])
  })
  it('copies the exact benefit and term into contact messages', () => {
    expect(addonConsultationDetails(rows[1])).toContain('5,000 积分')
    expect(addonConsultationDetails(rows[2])).toContain('提升至 8 并发')
    expect(addonConsultationDetails(rows[2])).toContain('1 个自然月')
    expect(addonConsultationDetails({ name: 'Lite' })).toBe('')
  })
})
