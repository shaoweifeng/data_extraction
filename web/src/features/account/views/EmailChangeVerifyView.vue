<template>
  <div class="account-action-page">
    <div class="account-action-card account-action-status">
      <div :class="['status-icon', state]">
        <i v-if="state === 'verifying'" class="fas fa-spinner fa-spin"></i>
        <i v-else-if="state === 'success'" class="fas fa-check"></i>
        <i v-else class="fas fa-exclamation"></i>
      </div>
      <h1>{{ title }}</h1>
      <p :class="['account-action-message', state === 'success' ? 'success' : state === 'error' ? 'error' : '']">
        {{ message }}
      </p>
      <div v-if="state !== 'verifying'" class="account-action-links">
        <RouterLink :to="auth.user ? '/profile' : '/login'">{{ auth.user ? '返回个人中心' : '返回登录' }}</RouterLink>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { confirmEmailChange } from '@/features/account/api'
import { useAuthStore } from '@/features/account/store'

const route = useRoute()
const auth = useAuthStore()
const state = ref('verifying')
const message = ref('正在验证您的新邮箱，请稍候…')
const title = computed(() => ({
  verifying: '正在验证新邮箱', success: '邮箱更新成功', error: '无法更新邮箱',
}[state.value]))

onMounted(async () => {
  const fragment = new window.URLSearchParams(route.hash.replace(/^#/, ''))
  const token = fragment.get('token') || ''
  if (!token) {
    state.value = 'error'
    message.value = '邮箱变更链接缺少必要信息，请重新申请。'
    return
  }
  try {
    const data = await confirmEmailChange(token)
    state.value = 'success'
    message.value = data.message
    window.history.replaceState(null, '', route.path)
    if (auth.user) await auth.fetchCurrentUser()
  } catch (error) {
    state.value = 'error'
    message.value = error?.response?.data?.error || '邮箱变更链接无效或已过期。'
  }
})
</script>

<style src="../account-actions.css"></style>
