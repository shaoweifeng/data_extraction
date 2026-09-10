export const FEEDBACK_LIMITS = Object.freeze({
  minContentLength: 5,
  maxContentLength: 2000,
  maxImages: 3,
  maxImageBytes: 5 * 1024 * 1024,
  maxTotalImageBytes: 10 * 1024 * 1024,
})

const allowedTypes = new Set(['image/jpeg', 'image/png', 'image/webp'])

export function validateFeedbackFiles(existingFiles, incomingFiles) {
  const combined = [...existingFiles, ...incomingFiles]
  if (combined.length > FEEDBACK_LIMITS.maxImages) {
    return `最多上传 ${FEEDBACK_LIMITS.maxImages} 张图片`
  }
  for (const item of incomingFiles) {
    const file = item.file || item
    if (!allowedTypes.has(file.type)) return `${file.name} 不是支持的图片格式`
    if (file.size > FEEDBACK_LIMITS.maxImageBytes) return `${file.name} 超过 5 MiB`
  }
  const total = combined.reduce((sum, item) => sum + (item.file || item).size, 0)
  if (total > FEEDBACK_LIMITS.maxTotalImageBytes) return '图片总大小不能超过 10 MiB'
  return ''
}

export function validateFeedbackContent(content) {
  const length = content.trim().length
  if (length < FEEDBACK_LIMITS.minContentLength) return '请至少输入 5 个字符'
  if (length > FEEDBACK_LIMITS.maxContentLength) return '反馈内容不能超过 2000 个字符'
  return ''
}

