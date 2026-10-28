export const STEPS = [
  '上传 / 导入',
  '全文获取',
  '排除标准',
  'AI 全文复筛',
  '人工审阅',
  '结果导出',
]
export const ACTIVE_RUNS = [
  'pending',
  'running',
  'cancelling',
  'settlement_pending',
]
export const labels = {
  pending: '待处理',
  uploaded: '等待导入',
  importing: '导入中',
  running: '进行中',
  processing: '处理中',
  cancelling: '正在停止',
  cancelled: '已取消',
  completed: '已完成',
  partial: '部分完成',
  paused: '已暂停',
  failed: '失败',
  ready: '可用',
  missing: '未获取',
  extracting: '提取中',
  validating: '校验中',
  scanning: '安全检查',
  rejected: '已拒绝',
  settlement_pending: '待恢复结算',
  included: '纳入',
  excluded: '排除',
  not_retrieved: '全文未获取',
  found: '找到候选',
  not_found: '未找到',
  offered: '待确认',
  downloaded: '已下载',
  bound: '已绑定',
}
export const label = (value) => labels[value] || value || '—'
export const emptyPage = () => ({
  items: [],
  total: 0,
  page: 1,
  page_size: 50,
  pages: 1,
})
export const errorMessage = (error) => {
  const value = error?.response?.data?.error
  return (
    (typeof value === 'string' ? value : value?.message) ||
    error?.message ||
    '请求失败，请重试。'
  )
}
export const pageNumber = (value, pages) =>
  Math.min(Math.max(1, Math.floor(Number(value) || 1)), Math.max(1, pages))
export const criteriaLines = (text) =>
  text
    .split('\n')
    .map((row) => row.trim())
    .filter(Boolean)
export const stepNumber = (value, info) => {
  const index = Number(value)
  return Number.isInteger(index) &&
    info?.steps?.some((step) => step.index === index && step.enabled)
    ? index
    : 1
}
export const safePdfUrl = (url, page = 1) =>
  /^\/api\/fulltext\/assets\/\d+\/download\/$/.test(url || '')
    ? `${url}#page=${Math.max(1, Math.floor(Number(page) || 1))}&view=FitH`
    : ''
export function toggleSelection(selected, id, maximum) {
  if (selected.includes(id)) return selected.filter((value) => value !== id)
  return selected.length < maximum ? [...selected, id] : selected
}
