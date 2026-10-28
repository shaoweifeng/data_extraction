import { describe, expect, it, vi } from 'vitest'
import { createPdfPreview } from './usePdfPreview'
const response = (text = '%PDF-1.4 content', size = 0) => ({ ok: true, headers: { get: () => size || null }, blob: async () => new Blob([text], { type: 'application/pdf' }) })
describe('private PDF preview lifecycle', () => {
  it('fetches authenticated sources and releases the previous object URL', async () => {
    const fetcher = vi.fn(async () => response()), revokeUrl = vi.fn()
    const preview = createPdfPreview({ fetcher, createUrl: () => 'blob:private-pdf', revokeUrl })
    await preview.load('/api/fulltext/assets/1/download/')
    expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin')
    expect(preview.state.url).toBe('blob:private-pdf')
    preview.dispose()
    expect(revokeUrl).toHaveBeenCalledWith('blob:private-pdf')
  })
  it('an old document response cannot replace a newly selected document', async () => {
    let resolve
    const slow = new Promise(yes => { resolve = yes })
    const fetcher = vi.fn(url => url === '/old' ? slow : Promise.resolve(response()))
    const createUrl = vi.fn(() => 'blob:new')
    const preview = createPdfPreview({ fetcher, createUrl, revokeUrl: vi.fn() })
    const old = preview.load('/old')
    await preview.load('/new')
    resolve(response()); await old
    expect(preview.state.url).toBe('blob:new')
    expect(createUrl).toHaveBeenCalledOnce()
    preview.dispose()
  })
  it('rejects oversized and non-PDF responses without creating a URL', async () => {
    const createUrl = vi.fn(), fetcher = vi.fn(async () => response('login page'))
    const preview = createPdfPreview({ fetcher, createUrl, revokeUrl: vi.fn(), maxBytes: 30 })
    await preview.load('/source')
    expect(preview.state.error).toContain('不是有效 PDF')
    fetcher.mockResolvedValue(response('%PDF-', 100))
    await preview.load('/source')
    expect(preview.state.error).toContain('超出内嵌预览预算')
    expect(createUrl).not.toHaveBeenCalled()
    preview.dispose()
  })
})
