<template>
  <div class="account-action-page">
    <div class="account-action-card">
      <h1>设置新密码</h1>
      <p class="lead">新密码设置成功后，其他设备上的旧登录状态将失效。</p>
      <form v-if="!success" class="account-action-form" @submit.prevent="submit">
        <PasswordField
          id="reset-password"
          v-model="form.password"
          label="新密码"
          autocomplete="new-password"
          :minlength="PASSWORD_MIN_LENGTH"
          :maxlength="PASSWORD_MAX_LENGTH"
        />
        <PasswordField
          id="reset-password-confirm"
          v-model="form.password_confirm"
          label="确认新密码"
          autocomplete="new-password"
          :minlength="PASSWORD_MIN_LENGTH"
          :maxlength="PASSWORD_MAX_LENGTH"
        />
        <PasswordRequirements :password="form.password" :confirm-password="form.password_confirm" />
        <p v-if="error" class="account-action-message error">{{ error }}</p>
        <button class="account-action-button" type="submit" :disabled="loading || !token">
          {{ loading ? '正在重置…' : '重置密码' }}
        </button>
      </form>
      <div v-else class="account-action-status">
        <div class="status-icon success"><i class="fas fa-check"></i></div>
        <p class="account-action-message success">{{ success }}</p>
      </div>
      <div class="account-action-links">
        <RouterLink :to="success ? '/login' : '/forgot-password'">
          {{ success ? '使用新密码登录' : '重新申请重置链接' }}
        </RouterLink>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { resetPassword } from '@/features/account/api'
import PasswordField from '@/features/account/components/PasswordField.vue'
import PasswordRequirements from '@/features/account/components/PasswordRequirements.vue'
import { firstAccountError, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from '@/features/account/validation'

const route = useRoute()
const token = ref('')
const form = reactive({ password: '', password_confirm: '' })
const loading = ref(false)
const error = ref('')
const success = ref('')

onMounted(() => {
  const fragment = new window.URLSearchParams(route.hash.replace(/^#/, ''))
  token.value = fragment.get('token') || ''
  if (!token.value) error.value = '密码重置链接缺少必要信息，请重新申请。'
})

async function submit() {
  error.value = ''
  if (form.password !== form.password_confirm) {
    error.value = '两次输入的密码不一致'
    return
  }
  loading.value = true
  try {
    const data = await resetPassword({ token: token.value, ...form })
    success.value = data.message
    window.history.replaceState(null, '', route.path)
  } catch (err) {
    error.value = firstAccountError(err, '密码重置失败')
  } finally {
    loading.value = false
  }
}
</script>

<style src="../account-actions.css"></style>
