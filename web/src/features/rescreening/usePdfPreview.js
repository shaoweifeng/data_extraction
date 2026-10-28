import { reactive } from 'vue'

/** Uses QA's authenticated blob-preview approach without changing the QA viewer.
 * Page jumps reuse the loaded blob; source changes abort and invalidate old work.
 */
export function createPdfPreview({ fetcher = (...args) => fetch(...args),
  createUrl = blob => URL.createObjectURL(blob), revokeUrl = url => URL.revokeObjectURL(url),
  maxBytes = 50 * 1024 * 1024 } = {}) {
  const state = reactive({ url: '', loading: false, error: '' })
  let generation = 0
  let controller
  function clear() {
    controller?.abort()
    if (state.url) revokeUrl(state.url)
    state.url = ''
  }
  function dispose() { generation++; clear(); state.loading = false }
  async function load(url) {
    const stamp = ++generation
    clear(); state.error = ''; state.loading = !!url
    if (!url) return
    controller = new AbortController()
    const current = controller
    const timeout = setTimeout(() => current.abort(), 60000)
    try {
      const response = await fetcher(url, { credentials: 'same-origin', signal: current.signal })
      if (!response.ok) throw new Error(`HTTP ${response.status}，请检查登录状态或独立打开`)
      if (Number(response.headers.get('Content-Length')) > maxBytes) throw new Error('文件超出内嵌预览预算，请独立打开或下载')
      const blob = await response.blob()
      if (blob.size > maxBytes) throw new Error('文件超出内嵌预览预算，请独立打开或下载')
      if (await blob.slice(0, 5).text() !== '%PDF-') throw new Error('返回的不是有效 PDF 文件')
      if (stamp !== generation) return
      state.url = createUrl(blob.type === 'application/pdf' ? blob : blob.slice(0, blob.size, 'application/pdf'))
    } catch (error) {
      if (stamp === generation) state.error = current.signal.aborted ? 'PDF 加载已中断或超时，请重试' : error.message
    } finally {
      clearTimeout(timeout)
      if (stamp === generation) state.loading = false
    }
  }
  return { state, load, dispose }
}
