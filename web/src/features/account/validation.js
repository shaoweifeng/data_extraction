export const PASSWORD_MIN_LENGTH = 8
export const PASSWORD_MAX_LENGTH = 128

export function firstAccountError(error, fallback = '操作失败') {
  const data = error?.response?.data
  if (data?.fields && typeof data.fields === 'object') {
    for (const messages of Object.values(data.fields)) {
      if (Array.isArray(messages) && messages.length) return String(messages[0])
      if (typeof messages === 'string' && messages) return messages
    }
  }
  return data?.error || error?.message || fallback
}
