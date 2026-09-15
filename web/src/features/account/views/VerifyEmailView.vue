<template>
  <div class="verify-page">
    <div class="verify-card">
      <div :class="['verify-icon', state]">
        <i v-if="state === 'verifying'" class="fas fa-spinner fa-spin"></i>
        <i v-else-if="state === 'success'" class="fas fa-check"></i>
        <i v-else class="fas fa-exclamation"></i>
      </div>
      <h1>{{ title }}</h1>
      <p>{{ message }}</p>
      <RouterLink v-if="state !== 'verifying'" to="/login" class="verify-action">
        返回登录
      </RouterLink>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { verifyEmail } from '@/features/account/api'

const route = useRoute()
const state = ref('verifying')
const message = ref('正在验证您的邮箱，请稍候…')

const title = computed(() => ({
  verifying: '正在验证邮箱',
  success: '邮箱验证成功',
  error: '无法验证邮箱',
}[state.value]))

onMounted(async () => {
  const fragment = new window.URLSearchParams(route.hash.replace(/^#/, ''))
  const token = fragment.get('token') || ''
  if (!token) {
    state.value = 'error'
    message.value = '验证链接缺少必要信息，请重新获取验证邮件。'
    return
  }
  try {
    const data = await verifyEmail(token)
    state.value = 'success'
    message.value = data.message || '账号已经激活，现在可以登录。'
  } catch (error) {
    state.value = 'error'
    message.value = error?.response?.data?.error || '验证链接无效或已过期，请重新获取验证邮件。'
  }
})
</script>

<style scoped>
.verify-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: linear-gradient(135deg, #1e1b4b, #4c1d95 60%, #6d28d9);
}
.verify-card {
  width: min(100%, 440px);
  box-sizing: border-box;
  padding: 2.75rem 2.25rem;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.32);
  text-align: center;
}
.verify-icon {
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  margin: 0 auto 1.25rem;
  border-radius: 18px;
  color: #fff;
  font-size: 1.5rem;
  background: #6366f1;
}
.verify-icon.success { background: #059669; }
.verify-icon.error { background: #dc2626; }
h1 { margin: 0 0 0.75rem; color: #1e293b; font-size: 1.45rem; }
p { margin: 0 0 1.75rem; color: #64748b; line-height: 1.7; }
.verify-action {
  display: inline-flex;
  padding: 0.7rem 1.4rem;
  border-radius: 9px;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #7c3aed);
  text-decoration: none;
  font-weight: 600;
}
</style>
