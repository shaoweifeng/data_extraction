/**
 * stores/auth.js
 * 登录用户状态
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const initialized = ref(false)

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

  return { user, initialized, fetchCurrentUser, login, register, logout }
})
