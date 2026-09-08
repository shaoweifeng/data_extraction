/**
 * shared/api/http.js
 * axios 实例 + CSRF 注入 + 401 统一处理
 */
import axios from 'axios'

/** 从 cookie 读取 Django CSRF token */
function getCsrfToken() {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith('csrftoken='))
    ?.split('=')[1]
}

const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：注入 CSRF token
http.interceptors.request.use((config) => {
  const token = getCsrfToken()
  if (token) config.headers['X-CSRFToken'] = token
  return config
})

// 响应拦截：401 → 清空用户状态（由 router 守卫负责重定向）
http.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 || err.response?.status === 403) {
      // 用全局事件通知 auth store，避免循环 import
      window.dispatchEvent(new CustomEvent('app:unauthorized'))
    }
    return Promise.reject(err)
  },
)

/**
 * 不带超时的 axios 实例（用于任务启动/停止/续传等耗时操作）
 */
export const httpNoTimeout = axios.create({
  baseURL: '/api',
  timeout: 0,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})
httpNoTimeout.interceptors.request.use((config) => {
  const token = getCsrfToken()
  if (token) config.headers['X-CSRFToken'] = token
  return config
})
httpNoTimeout.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 || err.response?.status === 403) {
      window.dispatchEvent(new CustomEvent('app:unauthorized'))
    }
    return Promise.reject(err)
  },
)

export default http
