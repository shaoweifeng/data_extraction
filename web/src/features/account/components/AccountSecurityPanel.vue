<template>
  <section class="security-panel">
    <div class="security-heading">
      <div>
        <h2><i class="fas fa-shield-alt"></i> 账户安全</h2>
        <p>管理登录密码和可信邮箱。</p>
      </div>
      <span :class="['email-status', auth.user?.email_verified ? 'verified' : 'unverified']">
        {{ auth.user?.email_verified ? '邮箱已验证' : '邮箱未验证' }}
      </span>
    </div>

    <div class="security-grid">
      <form class="security-card" @submit.prevent="submitPassword">
        <h3>修改密码</h3>
        <PasswordField
          id="security-current-password"
          v-model="passwordForm.current_password"
          label="当前密码"
          autocomplete="current-password"
        />
        <PasswordField
          id="security-new-password"
          v-model="passwordForm.new_password"
          label="新密码"
          autocomplete="new-password"
          :minlength="PASSWORD_MIN_LENGTH"
          :maxlength="PASSWORD_MAX_LENGTH"
        />
        <PasswordField
          id="security-new-password-confirm"
          v-model="passwordForm.new_password_confirm"
          label="确认新密码"
          autocomplete="new-password"
          :minlength="PASSWORD_MIN_LENGTH"
          :maxlength="PASSWORD_MAX_LENGTH"
        />
        <p v-if="passwordMessage" class="security-message success">{{ passwordMessage }}</p>
        <p v-if="passwordError" class="security-message error">{{ passwordError }}</p>
        <button type="submit" :disabled="passwordLoading">
          {{ passwordLoading ? '正在修改…' : '修改密码' }}
        </button>
      </form>

      <form class="security-card" @submit.prevent="submitEmail">
        <h3>{{ auth.user?.email_verified ? '修改可信邮箱' : '绑定可信邮箱' }}</h3>
        <div class="current-email">
          <span>当前邮箱</span>
          <strong>{{ auth.user?.email || '尚未绑定' }}</strong>
        </div>
        <div class="security-field">
          <label for="security-new-email">新邮箱</label>
          <input
            id="security-new-email"
            v-model="emailForm.new_email"
            type="email"
            maxlength="254"
            autocomplete="email"
            required
          />
        </div>
        <PasswordField
          id="security-email-password"
          v-model="emailForm.current_password"
          label="当前密码"
          autocomplete="current-password"
        />
        <p v-if="emailMessage" class="security-message success">{{ emailMessage }}</p>
        <p v-if="emailError" class="security-message error">{{ emailError }}</p>
        <button type="submit" :disabled="emailLoading || emailCountdown > 0">
          {{ emailLoading ? '正在发送…' : emailCountdown > 0 ? `${emailCountdown} 秒后可重试` : '发送验证邮件' }}
        </button>
      </form>
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref } from 'vue'
import { changePassword, requestEmailChange } from '@/features/account/api'
import { useAuthStore } from '@/features/account/store'
import PasswordField from '@/features/account/components/PasswordField.vue'
import { firstAccountError, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from '@/features/account/validation'

const auth = useAuthStore()
const passwordForm = reactive({
  current_password: '', new_password: '', new_password_confirm: '',
})
const emailForm = reactive({ current_password: '', new_email: '' })
const passwordLoading = ref(false)
const passwordMessage = ref('')
const passwordError = ref('')
const emailLoading = ref(false)
const emailMessage = ref('')
const emailError = ref('')
const emailCountdown = ref(0)
let emailTimer = null

async function submitPassword() {
  passwordMessage.value = ''
  passwordError.value = ''
  if (passwordForm.new_password !== passwordForm.new_password_confirm) {
    passwordError.value = '两次输入的新密码不一致'
    return
  }
  passwordLoading.value = true
  try {
    const data = await changePassword(passwordForm)
    passwordMessage.value = data.message
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    passwordForm.new_password_confirm = ''
  } catch (error) {
    passwordError.value = firstAccountError(error, '密码修改失败')
  } finally {
    passwordLoading.value = false
  }
}

function startEmailCountdown(seconds) {
  emailCountdown.value = Math.max(1, Number(seconds) || 60)
  if (emailTimer) window.clearInterval(emailTimer)
  emailTimer = window.setInterval(() => {
    emailCountdown.value -= 1
    if (emailCountdown.value <= 0) {
      window.clearInterval(emailTimer)
      emailTimer = null
    }
  }, 1000)
}

async function submitEmail() {
  emailMessage.value = ''
  emailError.value = ''
  emailLoading.value = true
  try {
    const data = await requestEmailChange(emailForm)
    emailMessage.value = data.message
    emailForm.current_password = ''
    startEmailCountdown(data.resend_after)
  } catch (error) {
    emailError.value = firstAccountError(error, '邮箱验证邮件发送失败')
  } finally {
    emailLoading.value = false
  }
}

onBeforeUnmount(() => emailTimer && window.clearInterval(emailTimer))
</script>

<style scoped>
.security-panel { margin-bottom: 1.5rem; padding: 1.5rem; border-radius: 14px; background: #fff; box-shadow: 0 2px 12px rgba(15,23,42,.07); }
.security-heading { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; margin-bottom: 1.25rem; }
.security-heading h2 { margin: 0; color: #1e293b; font-size: 1.1rem; }
.security-heading h2 i { color: #6366f1; margin-right: .4rem; }
.security-heading p { margin: .35rem 0 0; color: #94a3b8; font-size: .82rem; }
.email-status { flex: none; padding: .3rem .6rem; border-radius: 999px; font-size: .75rem; font-weight: 600; }
.email-status.verified { color: #047857; background: #d1fae5; }
.email-status.unverified { color: #b45309; background: #fef3c7; }
.security-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.security-card { display: flex; flex-direction: column; gap: .85rem; padding: 1rem; border: 1px solid #e2e8f0; border-radius: 11px; }
.security-card h3 { margin: 0; color: #334155; font-size: .95rem; }
.security-field { display: flex; flex-direction: column; gap: .35rem; }
.security-field label, .current-email span { color: #64748b; font-size: .78rem; font-weight: 600; }
.security-field input { box-sizing: border-box; width: 100%; padding: .65rem .75rem; border: 1px solid #cbd5e1; border-radius: 8px; outline: none; }
.security-field input:focus { border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,.1); }
.current-email { display: flex; flex-direction: column; gap: .2rem; padding: .65rem .75rem; border-radius: 8px; background: #f8fafc; }
.current-email strong { overflow-wrap: anywhere; color: #334155; font-size: .86rem; }
.security-card button { padding: .66rem .85rem; border: 0; border-radius: 8px; color: #fff; background: #6366f1; cursor: pointer; font-weight: 600; }
.security-card button:disabled { opacity: .65; cursor: not-allowed; }
.security-message { margin: 0; padding: .55rem .7rem; border-radius: 7px; font-size: .78rem; line-height: 1.5; }
.security-message.success { color: #166534; background: #f0fdf4; }
.security-message.error { color: #be123c; background: #fff1f2; }
@media (max-width: 860px) { .security-grid { grid-template-columns: 1fr; } }
</style>
