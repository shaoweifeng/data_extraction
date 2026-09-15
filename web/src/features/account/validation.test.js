import { describe, expect, it } from 'vitest'

import { firstAccountError, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from './validation'

describe('account validation helpers', () => {
  it('uses the first backend field validation error', () => {
    const error = {
      response: {
        data: {
          error: '注册信息有误',
          fields: { password_confirm: ['两次输入的密码不一致'] },
        },
      },
    }

    expect(firstAccountError(error, '注册失败')).toBe('两次输入的密码不一致')
  })

  it('exposes the commercial password length limits', () => {
    expect(PASSWORD_MIN_LENGTH).toBe(8)
    expect(PASSWORD_MAX_LENGTH).toBe(128)
  })
})
