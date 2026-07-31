/**
 * stores/auth.js
 * 登录用户状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const initialized = ref(false)

  // 是否管理员：Django 超级用户 或 profile.role === 'admin'
  const isAdmin = computed(() => {
    const u = user.value
    if (!u) return false
    return !!u.is_superuser || u.profile?.role === 'admin' || u.profile?.is_admin === true
  })

  async function fetchCurrentUser() {
    user.value = await authApi.fetchCurrentUser()
    initialized.value = true
  }

  async function login(form) {
    const data = await authApi.login(form)
    user.value = data.user
  }

  async function register(form) {
    return await authApi.register(form)
  }

  async function logout() {
    await authApi.logout()
    user.value = null
  }

  return { user, initialized, isAdmin, fetchCurrentUser, login, register, logout }
})
