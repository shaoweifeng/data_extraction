import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/shared/api/http', () => ({ default: http }))

import { resendVerificationEmail, verifyEmail } from './api'

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
})
