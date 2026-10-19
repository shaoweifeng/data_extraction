/**
 * features/account/store.js
 * 登录用户状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/features/account/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const initialized = ref(false)

  // 是否管理员：Django 超级用户 或 profile.role === 'admin'
  const isAdmin = computed(() => {
    const u = user.value
    if (!u) return false
    return !!u.is_superuser || u.profile?.role === 'admin' || u.profile?.is_admin === true
  })

  const isResearcher = computed(() => {
    const u = user.value
    return !!u && !isAdmin.value && u.profile?.role === 'researcher'
  })

  const canViewResearchDiagnostics = computed(() => {
    const profile = user.value?.profile
    return isAdmin.value || (!!profile && (
      profile.can_view_research_diagnostics === true
      || profile.role === 'researcher'
    ))
  })

  const canConfigureScreeningPrompt = computed(() => {
    const profile = user.value?.profile
    return isAdmin.value || (!!profile && (
      profile.can_configure_screening_prompt === true
      || profile.role === 'researcher'
    ))
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

  async function resendVerificationEmail(email) {
    return await authApi.resendVerificationEmail(email)
  }

  async function logout() {
    await authApi.logout()
    user.value = null
  }

  return {
    user, initialized, isAdmin, isResearcher,
    canViewResearchDiagnostics, canConfigureScreeningPrompt,
    fetchCurrentUser, login, register,
    resendVerificationEmail, logout,
  }
})
