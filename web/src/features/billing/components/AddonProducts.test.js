import { describe, expect, it } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import AddonProducts from './AddonProducts.vue'

const render = props => renderToString(createSSRApp(AddonProducts, props))
describe('add-on storefront rendering', () => {
  it('offers the eligible 5,000-credit trial and explains subscription gating', async () => {
    const html = await render({ kind: 'credits', contactEnabled: true, current: { plan_code: 'FREE' }, products: [
      { version: 'trial', name: '追加体验积分', kind: 'TRIAL', credits: 5000, valid_months: 12, reference_price_cny: 99, eligible: true },
      { version: 'credit', name: '50,000 积分包', kind: 'CREDIT', credits: 50000, valid_months: 12, reference_price_cny: 399, eligible: false, ineligible_reason: '请先开通有效的个人套餐' },
    ] })
    expect(html).toContain('5,000 积分')
    expect(html).toContain('¥99')
    expect(html).toContain('查看个人套餐')
    expect(html.match(/>申请使用<\/button>/g)).toHaveLength(1)
    expect(html).not.toContain('成本')
  })
  it('shows a highest-tier explanation and does not offer ineligible concurrency', async () => {
    const html = await render({ kind: 'concurrency', contactEnabled: true, current: { plan_code: 'PRO', ai_call_slots: 16 }, products: [
      { version: 'slots', name: '16 并发升级', kind: 'CONCURRENCY', target_slots: 16, valid_months: 1, reference_price_cny: 199, eligible: false, ineligible_reason: '当前基础并发已达到或超过此档位' },
    ] })
    expect(html).toContain('最高公开并发档位')
    expect(html).not.toContain('>申请使用</button>')
  })
})
