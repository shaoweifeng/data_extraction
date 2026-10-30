import { describe, expect, it, vi } from 'vitest'
import { createSSRApp, reactive } from 'vue'
import { renderToString } from '@vue/server-renderer'
import RescreenAI from './RescreenAI.vue'
import RescreenReview from './RescreenReview.vue'
import RescreenExport from './RescreenExport.vue'
import RescreenPagination from './RescreenPagination.vue'
import RescreenUpload from './RescreenUpload.vue'
import RescreenFulltext from './RescreenFulltext.vue'
import RescreenCriteria from './RescreenCriteria.vue'
import { emptyPage } from '../state'

function workspace() {
  return {
    state: reactive({
      working: false,
      selected: [],
      run: null,
      runId: null,
      refs: emptyPage(),
      runs: emptyPage(),
      runItems: emptyPage(),
      history: emptyPage(),
      models: [],
      filters: { q: '', status: '' },
      detail: null,
      aiDetail: null,
      imports: emptyPage(),
      assets: emptyPage(),
      lookups: emptyPage(),
      lookupItems: emptyPage(),
      source: null,
      info: {
        busy: false,
        counts: {
          total: 1000,
          ready: 20,
          finalized: 6,
          included: 4,
          excluded: 2,
          not_retrieved: 0,
          remaining: 994,
          bound: 20,
          missing: 980,
          fulltext_failed: 0,
          pending: 2,
          conflict: 3,
        },
        configuration: {
          version: 1,
          model_ids: [],
          criteria: [],
          custom_prompt: 'SECRET-PROMPT',
          protocol_prompt: 'PRIVATE-PROTOCOL',
        },
        capabilities: { max_run: 1000, max_lookup: 50 },
      },
    }),
    read: vi.fn(),
    action: vi.fn(),
    api: {},
  }
}
const render = (component, ws, props = {}) =>
  renderToString(createSSRApp(component, props).provide('rescreen', ws))
describe('rescreen component visibility and layout contracts', () => {
  it('restores the source branch upload tabs and keeps paginated import history', async () => {
    const html = await render(RescreenUpload, workspace())
    expect(html).toContain('upload-tabs')
    expect(html).toContain('从初筛导入')
    expect(html).toContain('上传 PDF 全文')
    expect(html).toContain('上传题录')
    expect(html).toContain('dropzone--import')
    expect(html).toContain('导入记录与文件处理详情')
    expect(html).not.toContain('rs-upload-grid')
  })
  it('restores fulltext status cards and preview drawer without manual asset ID entry', async () => {
    const ws = workspace()
    ws.state.detail = { id: 1, title: '示例文献', fulltext_status: 'missing' }
    const html = await render(RescreenFulltext, ws)
    expect(html).toContain('status-cards')
    expect(html).toContain('preview-drawer')
    expect(html).toContain('980')
    expect(html).toContain('项目全文与查找记录 / 候选确认')
    expect(html).not.toContain('资产 ID')
  })
  it('restores criteria entry rows and writing guide while retaining explicit versioned save', async () => {
    const ws = workspace()
    ws.state.info.configuration.criteria = [{ id: 'C1', text: '排除动物实验' }]
    const html = await render(RescreenCriteria, ws)
    expect(html).toContain('input-row')
    expect(html).toContain('criteria-item')
    expect(html).toContain('guide-grid')
    expect(html).toContain('排除动物实验')
    expect(html).not.toContain('rows="12"')
  })
  it('restores AI input and result columns with real model and billing controls', async () => {
    const html = await render(RescreenAI, workspace())
    expect(html).toContain('ai-layout')
    expect(html).toContain('ai-left')
    expect(html).toContain('ai-right panel')
    expect(html).toContain('选择模型')
    expect(html).toContain('实际消费按返回用量结算')
    expect(html).toContain('运行进度与结果')
  })
  it('restores the two-column review and exclusion drawer instead of a third inspector', async () => {
    const ws = workspace()
    ws.state.detail = {
      id: 1,
      title: '示例文献',
      bibliography: {},
      fulltext_status: 'missing',
    }
    const html = await render(RescreenReview, ws)
    expect(html).toContain('list-panel')
    expect(html).toContain('detail-panel')
    expect(html).toContain('abstract-box')
    expect(html).toContain('detail-ai')
    expect(html).toContain('detail-action')
    expect(html).toMatch(/class="tab-count-num"[^>]*>3</)
    expect(html).toMatch(/class="tab-count-num"[^>]*>2</)
    expect(html).not.toContain('rs-review-inspector')
    expect(html).not.toContain('rs-review-grid')
  })
  it('restores export cards while keeping a shared format selector and QA handoff', async () => {
    const html = await render(RescreenExport, workspace())
    expect(html).toContain('summary-grid')
    expect(html).toContain('export-grid')
    expect(html.match(/class="export-card"/g)).toHaveLength(5)
    expect(html.match(/aria-label="导出文件格式"/g)).toHaveLength(1)
    expect(html).toContain('分批导出')
    expect(html).toContain('导入质量评价')
  })
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
    ws.state.detail = {
      id: 1,
      title: '长文献名'.repeat(25),
      bibliography: {},
      pdf_url: 'javascript:alert(1)',
    }
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
    const html = await renderToString(
      createSSRApp(RescreenPagination, { page: { ...emptyPage(), total: 1 } }),
    )
    expect(html).toContain('跳转页码')
    expect(html).toContain('value="20"')
    expect(html).toContain('value="50"')
    expect(html).toContain('value="100"')
  })
  it('only embeds authenticated export downloads and distinguishes historical/expired records', async () => {
    const ws = workspace()
    ws.state.info.export_completed_id = 1
    ws.state.exports = {
      ...emptyPage(),
      total: 2,
      items: [
        {
          id: 1,
          format: 'xlsx',
          scope: 'included',
          mode: 'final',
          current: false,
          status: 'completed',
          processed_count: 4,
          total_count: 4,
          download_url: 'https://untrusted.example/output.xlsx',
        },
        {
          id: 2,
          format: 'xml',
          scope: 'all',
          mode: 'draft',
          current: true,
          status: 'completed',
          expired: true,
          total_count: 1000,
          processed_count: 1000,
        },
      ],
    }
    const html = await render(RescreenExport, ws)
    expect(html).toContain('历史版本')
    expect(html).toContain('文件已清理或超过保留期')
    expect(html).not.toContain('https://untrusted.example')
    expect(html).toContain('当前版本已完成导出')
  })
})
