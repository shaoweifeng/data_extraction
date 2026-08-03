<template>
  <div class="login-bg">
    <!-- 背景装饰圆 -->
    <div class="deco deco-1"></div>
    <div class="deco deco-2"></div>
    <div class="deco deco-3"></div>

    <div class="login-card">
      <!-- Logo 区域 -->
      <div class="login-header">
        <div class="login-logo">
          <i class="fas fa-flask"></i>
        </div>
        <h1 class="login-title">科研数据提取平台</h1>
        <p class="login-subtitle">高效完成文献筛选与数据提取全流程</p>
      </div>

      <!-- Tab 切换 -->
      <div class="tab-bar">
        <button
          @click="tab = 'login'; error = ''; success = ''; registered = false"
          :class="['tab-btn', tab === 'login' ? 'tab-active' : '']"
        >登录</button>
        <button
          @click="tab = 'register'; error = ''; success = ''; registered = false"
          :class="['tab-btn', tab === 'register' ? 'tab-active' : '']"
        >注册</button>
      </div>

      <!-- 登录表单 -->
      <form v-if="tab === 'login'" @submit.prevent="handleLogin" class="form-body">
        <div class="form-group">
          <label class="form-label">
            <i class="fas fa-user form-icon"></i> 用户名
          </label>
          <input
            v-model="loginForm.username"
            type="text"
            required
            class="input-base"
            placeholder="请输入用户名"
            autocomplete="username"
          />
        </div>
        <div class="form-group">
          <label class="form-label">
            <i class="fas fa-lock form-icon"></i> 密码
          </label>
          <input
            v-model="loginForm.password"
            type="password"
            required
            class="input-base"
            placeholder="请输入密码"
            autocomplete="current-password"
          />
        </div>
        <p v-if="error" class="form-error">
          <i class="fas fa-exclamation-circle mr-1"></i>{{ error }}
        </p>
        <button type="submit" :disabled="loading" class="btn-primary w-full justify-center py-2.5 mt-2">
          <span v-if="loading"><i class="fas fa-spinner fa-spin mr-1"></i>登录中...</span>
          <span v-else><i class="fas fa-sign-in-alt mr-1"></i>登 录</span>
        </button>
      </form>

      <!-- 注册表单 -->
      <form v-else @submit.prevent="handleRegister" class="form-body">
        <div class="form-group">
          <label class="form-label">
            <i class="fas fa-user form-icon"></i> 用户名
          </label>
          <input
            v-model="registerForm.username"
            type="text"
            required
            class="input-base"
            placeholder="设置用户名"
          />
        </div>
        <div class="form-group">
          <label class="form-label">
            <i class="fas fa-envelope form-icon"></i> 邮箱（可选）
          </label>
          <input
            v-model="registerForm.email"
            type="email"
            class="input-base"
            placeholder="your@email.com"
          />
        </div>
        <div class="form-group">
          <label class="form-label">
            <i class="fas fa-lock form-icon"></i> 密码
          </label>
          <input
            v-model="registerForm.password"
            type="password"
            required
            class="input-base"
            placeholder="设置登录密码"
            autocomplete="new-password"
          />
        </div>
        <p v-if="error" class="form-error">
          <i class="fas fa-exclamation-circle mr-1"></i>{{ error }}
        </p>
        <p v-if="success" class="form-success">
          <i class="fas fa-check-circle mr-1"></i>{{ success }}
        </p>
        <!-- 注册成功后按钮变为「前往登录」 -->
        <button
          v-if="registered"
          type="button"
          @click="tab = 'login'; registered = false"
          class="btn-primary w-full justify-center py-2.5 mt-2"
        >
          <i class="fas fa-sign-in-alt mr-1"></i>前往登录
        </button>
        <button
          v-else
          type="submit"
          :disabled="loading"
          class="btn-primary w-full justify-center py-2.5 mt-2"
          style="background: linear-gradient(135deg,#10b981,#059669)"
        >
          <span v-if="loading"><i class="fas fa-spinner fa-spin mr-1"></i>注册中...</span>
          <span v-else><i class="fas fa-user-plus mr-1"></i>创建账号</span>
        </button>
      </form>

      <p class="login-footer">
        科研数据提取平台 &copy; {{ new Date().getFullYear() }}
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const tab = ref('login')
const error = ref('')
const success = ref('')
const loading = ref(false)
const registered = ref(false)  // 注册成功状态，控制按钮切换

const loginForm = ref({ username: '', password: '' })
const registerForm = ref({ username: '', email: '', password: '' })

async function handleLogin() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(loginForm.value)
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  error.value = ''
  success.value = ''
  loading.value = true
  try {
    const data = await auth.register(registerForm.value)
    success.value = data.message || '注册成功，请登录'
    registered.value = true  // 停留在注册页显示成功，不自动切 tab
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '注册失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-bg {
  min-height: 100vh;
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 30%, #4c1d95 60%, #6d28d9 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.deco {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.25;
  pointer-events: none;
}
.deco-1 { width: 500px; height: 500px; background: #a78bfa; top: -100px; left: -100px; }
.deco-2 { width: 400px; height: 400px; background: #60a5fa; bottom: -80px; right: -60px; }
.deco-3 { width: 300px; height: 300px; background: #f472b6; top: 50%; left: 55%; }

.login-card {
  position: relative;
  z-index: 1;
  background: rgba(255,255,255,0.97);
  border-radius: 20px;
  padding: 2.5rem 2.5rem 1.75rem;
  width: 100%;
  max-width: 420px;
  box-shadow: 0 25px 60px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.1);
}

.login-header { text-align: center; margin-bottom: 1.75rem; }

.login-logo {
  width: 56px; height: 56px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 1rem;
  box-shadow: 0 8px 24px rgba(99,102,241,.4);
}
.login-logo i { font-size: 1.5rem; color: #fff; }

.login-title {
  font-size: 1.375rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 0.4rem;
}
.login-subtitle {
  font-size: 0.8rem;
  color: #94a3b8;
  margin: 0;
}

/* Tab */
.tab-bar {
  display: flex;
  background: #f1f5f9;
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 1.5rem;
}
.tab-btn {
  flex: 1;
  padding: 0.45rem 0;
  border: none;
  border-radius: 7px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  background: transparent;
  color: #64748b;
  transition: all 0.2s;
}
.tab-active {
  background: #fff;
  color: #6366f1;
  box-shadow: 0 1px 4px rgba(0,0,0,0.1);
}

/* Form */
.form-body { display: flex; flex-direction: column; gap: 1rem; }
.form-group { display: flex; flex-direction: column; gap: 0.375rem; }
.form-label { font-size: 0.8rem; font-weight: 600; color: #475569; }
.form-icon { color: #a5b4fc; margin-right: 2px; width: 14px; }

.form-error {
  background: #fff1f2;
  border: 1px solid #fecdd3;
  color: #be123c;
  font-size: 0.8rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  margin: 0;
}
.form-success {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  font-size: 0.8rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  margin: 0;
}

.login-footer {
  text-align: center;
  font-size: 0.75rem;
  color: #94a3b8;
  margin: 1.5rem 0 0;
}

.w-full { width: 100%; }
.justify-center { justify-content: center; }
</style>
