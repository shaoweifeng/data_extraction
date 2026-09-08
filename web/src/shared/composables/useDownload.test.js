import { describe, expect, it, vi } from 'vitest'
import { downloadBlob } from './useDownload'

describe('downloadBlob', () => {
  it('clicks a temporary link and always revokes the object URL', () => {
    const link = { click: vi.fn() }
    const body = { appendChild: vi.fn(), removeChild: vi.fn() }
    const targetDocument = { createElement: vi.fn(() => link), body }
    const urlApi = { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() }

    downloadBlob(new Blob(['data']), 'report.xlsx', urlApi, targetDocument)

    expect(link).toMatchObject({ href: 'blob:test', download: 'report.xlsx' })
    expect(link.click).toHaveBeenCalledOnce()
    expect(urlApi.revokeObjectURL).toHaveBeenCalledWith('blob:test')
  })
})
