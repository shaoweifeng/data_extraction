/**
 * src/utils/format.js
 * 纯工具函数（无副作用，无 Vue 依赖）
 * 从 frontend/js/utils.js 迁移
 */

/** 秒数 → "X时Y分Z秒" */
export function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '0秒'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  const parts = []
  if (hours > 0) parts.push(`${hours}时`)
  if (minutes > 0) parts.push(`${minutes}分`)
  if (secs > 0) parts.push(`${secs}秒`)
  return parts.join('') || '0秒'
}

/** 任务类型/步骤 key → 中文名 */
export function getTaskTypeName(taskType) {
  const names = {
    reference_parsing: '文献解析',
    deduplication: '文献去重',
    ai_screening: 'AI初筛',
    result_aggregation: '结果归纳',
    parse: '文献解析',
    dedup: '文献去重',
    ai_screen: 'AI初筛',
    export: '结果归纳',
    criteria: '纳排标准',
    SCREEN_1: '初筛阶段',
    SEARCH: '文献检索',
  }
  return names[taskType] || taskType
}

/** 任务状态 → badge CSS 类 */
export function getTaskStatusClass(status) {
  const classes = {
    completed: 'badge badge-green',
    running:   'badge badge-blue',
    pending:   'badge badge-gray',
    failed:    'badge badge-red',
    stopped:   'badge badge-yellow',
    stopping:  'badge badge-yellow',
  }
  return classes[status] || 'badge badge-gray'
}

/** 任务状态 → 中文名 */
export function getTaskStatusName(status) {
  const names = {
    completed: '已完成',
    running: '执行中',
    pending: '等待中',
    failed: '失败',
    stopped: '已停止',
  }
  return names[status] || status
}

/** 操作日志类型 → Tailwind 颜色类 */
export function getLogTypeClass(opType) {
  const map = {
    file_add: 'bg-blue-500',
    file_delete: 'bg-red-500',
    criteria_add: 'bg-green-500',
    criteria_delete: 'bg-orange-500',
    task_start_parse: 'bg-indigo-500',
    task_start_dedup: 'bg-purple-500',
    task_start_ai_screen: 'bg-violet-500',
    task_start_export: 'bg-teal-500',
    task_stop: 'bg-yellow-500',
    task_resume: 'bg-green-500',
    task_abandon: 'bg-gray-500',
    prompt_set: 'bg-purple-500',
    prompt_reset: 'bg-gray-400',
    model_select: 'bg-blue-400',
    field_extraction_add: 'bg-orange-400',
    field_extraction_delete: 'bg-red-400',
  }
  return map[opType] || 'bg-gray-400'
}

/** 操作日志对象 → 详情文本 */
export function getLogDetail(log) {
  const d = log.operation_detail || {}
  if (log.operation_type === 'prompt_set')
    return d.use_custom ? `自定义 Prompt（${d.prompt_length || 0} 字符）` : '切换为默认 Prompt'
  if (log.operation_type === 'prompt_reset') return '已重置为默认 Prompt'
  if (log.operation_type === 'model_select') return `切换为 ${d.model_name || d.model_id}`
  if (log.operation_type === 'field_extraction_add') return `添加字段: ${d.field_name || ''}`
  if (log.operation_type === 'field_extraction_delete') return `删除字段: ${d.field_name || ''}`
  if (d.filename) return d.filename
  if (d.criteria) return d.criteria
  if (d.task_type) return d.task_type
  return ''
}

/** 错误信息截断（超 50 字符加省略号） */
export function getShortError(errorMsg) {
  if (!errorMsg) return ''
  return errorMsg.length > 50 ? errorMsg.substring(0, 50) + '...' : errorMsg
}

/**
 * 导出文件名 → 版本标签
 * 格式：screening_results_{type}_{model}_{YYYYMMDD}_{HHMMSS}.ext
 */
export function exportFileLabel(f) {
  const name = f.filename || ''
  const m = name.match(/screening_results_(?:all|included|excluded)_(.+?)_(\d{8})_(\d{6})\./)
  if (m) {
    const model = m[1]
    const d = m[2]
    const t = m[3]
    const dateStr = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)} ${t.slice(0, 2)}:${t.slice(2, 4)}`
    return `${model}  ${dateStr}`
  }
  return f.created_at?.slice(0, 16) || name
}

/** 解析 DRF 分页/非分页响应 */
export function extractListData(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.results)) return payload.results
  return []
}
