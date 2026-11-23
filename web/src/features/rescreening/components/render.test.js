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
          ai_pending: 14,
          ai_completed: 6,
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
    const ws = workspace()
    ws.state.info.import_mode = 'screening'
    const html = await render(RescreenUpload, ws)
    expect(html).toContain('upload-tabs')
    expect(html).toContain('从初筛导入')
    expect(html).toContain('上传 PDF 全文')
    expect(html).toContain('上传题录')
    expect(html).toContain('dropzone--import')
    expect(html).toContain('导入记录与文件处理详情')
    expect(html).not.toContain('rs-upload-grid')
  })
  it('keeps selection actions in one toolbar even after selecting references', async () => {
    const ws = workspace()
    ws.state.selected = [1, 2]
    const html = await render(RescreenUpload, ws)
    expect(html).not.toContain('selection-toolbar')
    expect(html).not.toContain('已选择')
    expect(html.match(/class="selection-tools"/g)).toHaveLength(1)
    expect(html).toContain('移除所选')
    expect(html).toContain('导入与文件处理详情')
  })
  it('restores fulltext status cards and preview drawer without manual asset ID entry', async () => {
    const ws = workspace()
    ws.state.detail = { id: 1, title: '示例文献', fulltext_status: 'missing' }
    const html = await render(RescreenFulltext, ws)
    expect(html).toContain('status-cards')
    expect(html).toContain('已绑定全文')
    expect(html).toContain('未绑定全文')
    expect(html).toContain('preview-drawer')
    expect(html).toContain('980')
    expect(html).not.toContain('项目全文与查找记录 / 候选确认')
    expect(html).toContain('选择项目已有全文')
    expect(html).not.toContain('资产 ID')
  })
  it('restores criteria entry rows and writing guide while retaining explicit versioned save', async () => {
    const ws = workspace()
    ws.state.info.configuration.criteria = [{ id: 'C1', text: '排除动物实验' }]
    const html = await render(RescreenCriteria, ws)
    expect(html).toContain('input-row')
    expect(html).toContain('criteria-item')
    expect(html).toContain('查看初筛标准')
    expect(html).not.toContain('保存排除标准')
    expect(html).not.toContain('有未保存的修改')
    expect(html).toContain('查看撰写指南')
    expect(html).toContain('常用排除标准（勾选后自动添加）')
    expect(html).toContain('未以人类为研究对象（如动物实验、细胞实验）')
    expect(html).toContain('排除动物实验')
    expect(html).not.toContain('rows="12"')
    expect(html).not.toContain('更改后已有审核需要重新确认')
  })
  it('locks upload modes after selection and requires reset before switching', async () => {
    const ws = workspace()
    ws.state.info.import_mode = 'pdf'
    const html = await render(RescreenUpload, ws)
    expect(html).toContain('清空当前文献')
    expect(html).toContain('确认清空')
    const tabs = html.match(/<button[^>]*class="upload-tab[^"]*"[^>]*>/g)
    expect(tabs.filter((tag) => tag.includes('disabled'))).toHaveLength(2)
    expect(html).not.toContain('dropzone--import')
    const fresh = workspace()
    fresh.state.info.import_mode = ''
    expect(await render(RescreenUpload, fresh)).toContain('请选择一种导入模式')
  })
  it('places literature on the left and AI model, billing and progress controls on the right', async () => {
    const ws = workspace()
    ws.state.models = [
      {
        id: 'deepseek',
        name: 'DeepSeek',
        configured: true,
        sub_models: [{ id: 'flash', name: 'Flash', configured: true }],
      },
    ]
    ws.state.info.configuration.model_ids = ['flash']
    const html = await render(RescreenAI, ws)
    expect(html).toContain('ai-layout')
    expect(html).toContain('ai-left')
    const right = html.indexOf('aria-label="模型与任务进度"')
    expect(right).toBeGreaterThan(0)
    expect(html.slice(0, right)).toContain('待复筛文献')
    expect(html.slice(0, right)).toContain('全部')
    expect(html.slice(0, right)).toContain('已复筛文献')
    expect(html.slice(0, right)).not.toContain('运行明细')
    expect(html.slice(0, right)).toContain('ai-list-tools')
    expect(html.slice(0, right)).toContain('选本页')
    expect(html.slice(0, right)).not.toContain('筛选文献状态')
    expect(html.slice(0, right)).not.toContain('跨页保留')
    expect(html.slice(right)).toContain('选择模型')
    expect(html.slice(right)).toContain('ai-submodel-btn-active')
    expect(html.slice(right)).toContain('开始 AI 复筛')
    expect(html).not.toContain('任务输入')
    expect(html).not.toContain('排除标准摘要')
    expect(html).not.toContain('保存模型选择')
    expect(html).toContain('实际消费按返回用量结算')
    expect(html).not.toContain('复筛运行进度')
    expect(html).not.toContain('历史运行')
  })
  it('shows an explicit cancel-page action when this page is selected', async () => {
    const ws = workspace()
    ws.state.refs.items = [{ id: 1, title: '文献一', ai_ready: true }]
    ws.state.selected = [1, 2]
    const html = await render(RescreenAI, ws)
    expect(html).toContain('取消本页')
    expect(html).toContain('只取消本页，保留其他页的选择')
    expect(html).toContain('清空已选')
    expect(html).not.toContain('fa-check-double')
  })
  it.each([
    ['running', '复筛进度', '停止本轮'],
    ['settlement_pending', '复筛进度', '恢复结算'],
  ])(
    'replaces configuration with the %s run view',
    async (status, heading, action) => {
      const ws = workspace()
      ws.state.run = {
        id: 1,
        status,
        processed_count: 2,
        total_count: 4,
        counts: {},
      }
      ws.state.runId = 1
      const html = await render(RescreenAI, ws)
      expect(html).toContain(heading)
      expect(html).toContain(action)
      expect(html).not.toContain('历史运行')
      expect(html).toContain('运行明细')
      const right = html.indexOf('aria-label="模型与任务进度"')
      expect(html.slice(0, right)).not.toContain('运行明细')
      expect(html.slice(right)).toContain('run-items-details')
      expect(html).not.toContain('选择模型')
      expect(html).not.toContain('开始 AI 复筛')
    },
  )
  it('reopens a completed run in model configuration with pending and screened tabs', async () => {
    const ws = workspace()
    ws.state.run = {
      id: 1,
      status: 'completed',
      processed_count: 4,
      total_count: 4,
      counts: {},
    }
    ws.state.runId = 1
    const html = await render(RescreenAI, ws)
    expect(html).toContain('选择模型')
    expect(html).toContain('开始 AI 复筛')
    expect(html).toContain('待复筛文献')
    expect(html).toContain('已复筛文献')
    expect(html).toContain('查看运行结果')
    expect(html).not.toContain('class="panel run-panel"')
  })
  it('restores the two-column review and exclusion drawer instead of a third inspector', async () => {
    const ws = workspace()
    ws.state.detail = {
      id: 1,
      title: '示例文献',
      bibliography: { abstract: '不应替代全文展示的摘要' },
      fulltext_status: 'missing',
    }
    const html = await render(RescreenReview, ws)
    expect(html).toContain('list-panel')
    expect(html).toContain('detail-panel')
    expect(html).toContain('abstract-box')
    expect(html).toContain('detail-ai')
    expect(html).toContain('review-reading-grid')
    expect(html).toContain('aria-label="AI 判断与审核历史"')
    expect(html).toContain('detail-action')
    expect(html).toContain('没有绑定全文')
    expect(html).toContain('上传 / 绑定全文')
    expect(html).toContain('rescreen_step=2')
    expect(html).not.toContain('不应替代全文展示的摘要')
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
    expect(html).toContain('没有绑定全文')
  })
  it('keeps AI evidence collapsed and leaves human decisions independent from AI suggestions', async () => {
    const ws = workspace()
    ws.state.detail = {
      id: 1,
      title: '示例文献',
      bibliography: {},
      fulltext_status: 'missing',
    }
    ws.state.aiDetail = {
      consensus: 'included',
      models: [
        {
          id: 1,
          model_id: 'flash',
          status: 'completed',
          decision: 'included',
          reason: '研究符合标准',
          criteria_results: [],
          evidence: [{ id: 'e1', page: 2, text: '原文证据' }],
        },
      ],
    }
    const html = await render(RescreenReview, ws)
    expect(html).not.toContain('采纳到表单')
    expect(html).not.toContain('保存人工决定')
    expect(html).toContain('保存备注')
    expect(html).toContain('研究符合标准')
    expect(html).toContain('查看 AI 证据')
    const disclosure = html.match(
      /<details[^>]*class="evidence-disclosure"[^>]*>/,
    )?.[0]
    expect(disclosure).toBeTruthy()
    expect(disclosure).not.toMatch(/\bopen(?:\s|=|>)/)
    expect(html).toContain('第 2 页')
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
