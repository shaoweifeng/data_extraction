/**
 * features/account/api.js
 * 认证相关 API（登录接口不走 axios，避免 401 拦截器干扰）
 */
import http from '@/shared/api/http'

/** 获取当前登录用户，未登录返回 null */
export async function fetchCurrentUser() {
  try {
    const res = await http.get('/auth/me/')
    return res.data
  } catch {
    return null
  }
}

/** 登录，成功返回 { user }，失败抛出 Error */
export async function login(form) {
  // 登录直接用 fetch，避免 axios 拦截器对 401 的干扰
  function getCsrf() {
    return document.cookie.split('; ').find((r) => r.startsWith('csrftoken='))?.split('=')[1]
  }
  const res = await fetch('/api/auth/login/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() || '' },
    credentials: 'include',
    body: JSON.stringify(form),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || '登录失败')
  return data
}

/** 注册 */
export async function register(form) {
  const res = await http.post('/auth/register/', form)
  return res.data
}

/** 登出 */
export async function logout() {
  await http.post('/auth/logout/')
}
