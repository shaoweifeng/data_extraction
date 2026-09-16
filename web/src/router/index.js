import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/features/account/store'

const routes = [
  {
    path: '/',
    name: 'Landing',
    component: () => import('@/features/landing/views/LandingView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/features/account/views/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/verify-email',
    name: 'VerifyEmail',
    component: () => import('@/features/account/views/VerifyEmailView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/forgot-password',
    name: 'ForgotPassword',
    component: () => import('@/features/account/views/ForgotPasswordView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('@/features/account/views/ResetPasswordView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/verify-email-change',
    name: 'VerifyEmailChange',
    component: () => import('@/features/account/views/EmailChangeVerifyView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/projects',
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
  {
    path: '/operations',
    name: 'Operations',
    component: () => import('@/features/operations/views/OperationsView.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：公开首页始终可访问，业务页面未登录时跳转 /login
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 首次访问时尝试获取当前用户
  if (!auth.initialized) {
    await auth.fetchCurrentUser()
  }

  if (to.meta.requiresAuth && !auth.user) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { name: 'Home' }
  }

  // 已登录时访问 /login 跳转首页
  if (to.name === 'Login' && auth.user) {
    return { name: 'Home' }
  }
})

export default router
