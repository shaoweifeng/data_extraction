export const SCREENING_STEPS = [
  { id: 1, name: '文献解析', stepKey: 'parse' },
  { id: 2, name: '自动去重', stepKey: 'dedup' },
  { id: 3, name: '纳排标准', stepKey: 'criteria' },
  { id: 4, name: '提取字段', stepKey: 'field_extraction' },
  { id: 5, name: 'AI 初筛', stepKey: 'ai_screen' },
  { id: 6, name: '人工审阅', stepKey: 'review' },
  { id: 7, name: '结果导出', stepKey: 'export' },
]

export const QUALITY_STEPS = [
  { index: 1, key: 'upload', label: '上传文献' },
  { index: 2, key: 'method', label: '方法选择' },
  { index: 3, key: 'ai_eval', label: 'AI 质量评价' },
  { index: 4, key: 'review', label: '结果审核' },
  { index: 5, key: 'chart', label: '结果可视化' },
  { index: 6, key: 'export', label: '导出报告' },
]

export function inferQualityMaxStep(refs = []) {
  if (!refs.length) return 1
  let max = 2
  if (refs.some(item => item.quality_method)) max = 3
  if (refs.some(item => ['completed', 'abstract_only', 'failed'].includes(item.ai_eval_status))) max = 4
  if (refs.some(item => ['confirmed', 'partial'].includes(item.review_status))) max = 5
  return max
}

export function isQualityNextDisabled(step, refs = [], evalCompleted = false) {
  if (step === 1) return refs.length === 0
  if (step === 2) return !refs.some(item => item.quality_method)
  if (step === 3) return !evalCompleted
  if (step === 4) return !refs.some(item => ['confirmed', 'partial'].includes(item.review_status))
  return false
}

export function qualityFooterTip(step, refs = []) {
  if (step === 1 && refs.length) return `已导入 ${refs.length} 篇文献`
  if (step === 4) {
    const confirmed = refs.filter(item => item.review_status === 'confirmed').length
    return `${confirmed} / ${refs.length} 篇已确认`
  }
  return ''
}
