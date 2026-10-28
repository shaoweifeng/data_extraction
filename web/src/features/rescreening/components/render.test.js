import { describe, expect, it, vi } from 'vitest'
import { createSSRApp, reactive } from 'vue'
import { renderToString } from '@vue/server-renderer'
import RescreenAI from './RescreenAI.vue'
import RescreenReview from './RescreenReview.vue'
import RescreenExport from './RescreenExport.vue'
import RescreenPagination from './RescreenPagination.vue'
import { emptyPage } from '../state'

function workspace() {
  return { state: reactive({ working: false, selected: [], run: null, runId: null, refs: emptyPage(), runs: emptyPage(),
    runItems: emptyPage(), history: emptyPage(), models: [], filters: { q: '', status: '' }, detail: null,
    aiDetail: null, info: { busy: false, counts: { total: 1000, ready: 20, finalized: 6, included: 4, excluded: 2, not_retrieved: 0, remaining: 994 },
      configuration: { version: 1, model_ids: [], criteria: [], custom_prompt: 'SECRET-PROMPT', protocol_prompt: 'PRIVATE-PROTOCOL' },
      capabilities: { max_run: 1000 } } }), read: vi.fn(), action: vi.fn(), api: {} }
}
const render = (component, ws, props = {}) => renderToString(createSSRApp(component, props).provide('rescreen', ws))
describe('rescreen component visibility and layout contracts', () => {
  it('does not render private prompt UI or text for an ordinary account', async () => {
    const html = await render(RescreenAI, workspace(), { canPrompt: false })
    expect(html).not.toContain('Prompt 设置')
    expect(html).not.toContain('SECRET-PROMPT')
    expect(html).not.toContain('PRIVATE-PROTOCOL')
    expect(html).not.toContain('管理员：')
  })
  it('researcher/admin receives a real prompt editor, not a hidden element', async () => {
    const html = await render(RescreenAI, workspace(), { canPrompt: true })
    expect(html).toContain('Prompt 设置')
    expect(html).toContain('SECRET-PROMPT')
    expect(html).toContain('PRIVATE-PROTOCOL')
  })
  it('review displays server totals and does not embed arbitrary PDF URLs', async () => {
    const ws = workspace()
    ws.state.detail = { id: 1, title: '长文献名'.repeat(25), bibliography: {}, pdf_url: 'javascript:alert(1)' }
    const html = await render(RescreenReview, ws)
    expect(html).toContain('6 / 1000')
    expect(html).not.toContain('<iframe')
    expect(html).toContain('尚无可读全文')
  })
  it('exports expose a single format selector, draft restrictions and safe QA handoff', async () => {
    const html = await render(RescreenExport, workspace())
    expect(html).toContain('EndNote / RIS')
    expect(html).toContain('仅可导出草稿')
    expect(html).toContain('已存在的 QA 文献、AI 评价和人工成果')
    expect(html).toContain('994')
    expect(html).not.toContain('download=')
  })
  it('pagination always supports jump and page size selection, including a single page', async () => {
    const html = await renderToString(createSSRApp(RescreenPagination, { page: { ...emptyPage(), total: 1 } }))
    expect(html).toContain('跳转页码')
    expect(html).toContain('value="20"')
    expect(html).toContain('value="50"')
    expect(html).toContain('value="100"')
  })
  it('only embeds authenticated export downloads and distinguishes historical/expired records', async () => {
    const ws = workspace()
    ws.state.info.export_completed_id = 1
    ws.state.exports = { ...emptyPage(), total: 2, items: [
      { id: 1, format: 'xlsx', scope: 'included', mode: 'final', current: false, status: 'completed', processed_count: 4, total_count: 4, download_url: 'https://untrusted.example/output.xlsx' },
      { id: 2, format: 'xml', scope: 'all', mode: 'draft', current: true, status: 'completed', expired: true, total_count: 1000, processed_count: 1000 },
    ] }
    const html = await render(RescreenExport, ws)
    expect(html).toContain('历史版本')
    expect(html).toContain('文件已清理或超过保留期')
    expect(html).not.toContain('https://untrusted.example')
    expect(html).toContain('当前版本已完成导出')
  })
})
