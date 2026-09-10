import { describe, expect, it } from 'vitest'
import { FEEDBACK_LIMITS, validateFeedbackContent, validateFeedbackFiles } from './validation'


function file(name, type, size) {
  return { name, type, size }
}

describe('feedback validation', () => {
  it('validates trimmed content length', () => {
    expect(validateFeedbackContent('  ok  ')).toContain('至少')
    expect(validateFeedbackContent('一个有效的反馈')).toBe('')
    expect(validateFeedbackContent('x'.repeat(FEEDBACK_LIMITS.maxContentLength + 1))).toContain('不能超过')
  })

  it('only accepts bounded image uploads', () => {
    expect(validateFeedbackFiles([], [file('screen.png', 'image/png', 1000)])).toBe('')
    expect(validateFeedbackFiles([], [file('bad.svg', 'image/svg+xml', 1000)])).toContain('不是支持')
    expect(validateFeedbackFiles([], [file('large.jpg', 'image/jpeg', FEEDBACK_LIMITS.maxImageBytes + 1)])).toContain('超过')
    expect(validateFeedbackFiles(
      [file('1.png', 'image/png', 1), file('2.png', 'image/png', 1)],
      [file('3.png', 'image/png', 1), file('4.png', 'image/png', 1)],
    )).toContain('最多上传')
  })
})

