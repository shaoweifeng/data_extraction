import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import { useAuthStore } from './stores/auth'
import './style.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// 监听 http.js 发出的 401/403 事件，清空用户状态并跳转登录页
window.addEventListener('app:unauthorized', () => {
  const auth = useAuthStore()
  auth.user = null
  router.push('/login')
})

app.mount('#app')
