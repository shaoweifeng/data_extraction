import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/shared/api/http', () => ({ default: http }))

import {
  changePassword,
  confirmEmailChange,
  fetchCurrentLegalDocuments,
  fetchLegalDocument,
  forgotPassword,
  requestEmailChange,
  resendVerificationEmail,
  resetPassword,
  verifyEmail,
} from './api'

describe('account verification API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('posts verification tokens to the public account endpoint', async () => {
    http.post.mockResolvedValue({ data: { code: 'email_verified' } })

    const result = await verifyEmail('raw-token')

    expect(http.post).toHaveBeenCalledWith('/auth/email/verify/', { token: 'raw-token' })
    expect(result).toEqual({ code: 'email_verified' })
  })

  it('posts normalized resend input through the account endpoint', async () => {
    http.post.mockResolvedValue({ data: { message: 'sent' } })

    await resendVerificationEmail('user@example.com')

    expect(http.post).toHaveBeenCalledWith('/auth/email/resend/', {
      email: 'user@example.com',
    })
  })

  it('uses dedicated password recovery endpoints', async () => {
    http.post.mockResolvedValue({ data: { message: 'ok' } })

    await forgotPassword('user@example.com')
    await resetPassword({ token: 'reset-token', password: 'new', password_confirm: 'new' })
    await changePassword({ current_password: 'old', new_password: 'new' })

    expect(http.post).toHaveBeenNthCalledWith(1, '/auth/password/forgot/', {
      email: 'user@example.com',
    })
    expect(http.post).toHaveBeenNthCalledWith(2, '/auth/password/reset/', {
      token: 'reset-token', password: 'new', password_confirm: 'new',
    })
    expect(http.post).toHaveBeenNthCalledWith(3, '/auth/password/change/', {
      current_password: 'old', new_password: 'new',
    })
  })

  it('uses dedicated trusted-email change endpoints', async () => {
    http.post.mockResolvedValue({ data: { message: 'ok' } })

    await requestEmailChange({ current_password: 'password', new_email: 'new@example.com' })
    await confirmEmailChange('change-token')

    expect(http.post).toHaveBeenNthCalledWith(1, '/auth/email/change/request/', {
      current_password: 'password', new_email: 'new@example.com',
    })
    expect(http.post).toHaveBeenNthCalledWith(2, '/auth/email/change/confirm/', {
      token: 'change-token',
    })
  })

  it('loads current legal versions and document content', async () => {
    http.get
      .mockResolvedValueOnce({ data: { documents: [{ type: 'terms', version: 'v1' }] } })
      .mockResolvedValueOnce({ data: { type: 'privacy', content: 'policy' } })

    expect(await fetchCurrentLegalDocuments()).toEqual([{ type: 'terms', version: 'v1' }])
    expect(await fetchLegalDocument('privacy')).toEqual({ type: 'privacy', content: 'policy' })
    expect(http.get).toHaveBeenNthCalledWith(1, '/auth/legal/current/')
    expect(http.get).toHaveBeenNthCalledWith(2, '/auth/legal/privacy/')
  })
})
