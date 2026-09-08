import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/features/account/store'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/features/account/views/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('@/features/projects/views/HomeView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/workspace/:projectId',
    name: 'Workspace',
    component: () => import('@/features/projects/views/WorkspaceView.vue'),
    meta: { requiresAuth: true },
    props: true,
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('@/features/account/views/ProfileView.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转 /login
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 首次访问时尝试获取当前用户
  if (!auth.initialized) {
    await auth.fetchCurrentUser()
  }

  if (to.meta.requiresAuth && !auth.user) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  // 已登录时访问 /login 跳转首页
  if (to.name === 'Login' && auth.user) {
    return { name: 'Home' }
  }
})

export default router
