<template>
  <div class="account-action-page">
    <div class="account-action-card">
      <h1>找回密码</h1>
      <p class="lead">输入已经验证的邮箱，我们会向该邮箱发送密码重置链接。</p>
      <form class="account-action-form" @submit.prevent="submit">
        <div class="account-action-field">
          <label for="forgot-email">邮箱</label>
          <input
            id="forgot-email"
            v-model="email"
            class="account-action-input"
            type="email"
            maxlength="254"
            autocomplete="email"
            required
          />
        </div>
        <p v-if="message" class="account-action-message success">{{ message }}</p>
        <p v-if="error" class="account-action-message error">{{ error }}</p>
        <button class="account-action-button" type="submit" :disabled="loading || countdown > 0">
          {{ loading ? '正在发送…' : countdown > 0 ? `${countdown} 秒后可重试` : '发送重置链接' }}
        </button>
      </form>
      <div class="account-action-links"><RouterLink to="/login">返回登录</RouterLink></div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { forgotPassword } from '@/features/account/api'
import { firstAccountError } from '@/features/account/validation'

const email = ref('')
const loading = ref(false)
const message = ref('')
const error = ref('')
const countdown = ref(0)
let timer = null

function startCountdown(seconds) {
  countdown.value = Math.max(1, Number(seconds) || 60)
  if (timer) window.clearInterval(timer)
  timer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      window.clearInterval(timer)
      timer = null
    }
  }, 1000)
}

async function submit() {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const data = await forgotPassword(email.value)
    message.value = data.message
    startCountdown(data.resend_after)
  } catch (err) {
    error.value = firstAccountError(err, '发送失败，请稍后再试')
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => timer && window.clearInterval(timer))
</script>

<style src="../account-actions.css"></style>
