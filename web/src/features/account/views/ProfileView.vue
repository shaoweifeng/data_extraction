<template>
  <div class="profile-page">
    <AppHeader />
    <div class="profile-body">
      <aside class="profile-sidebar">
        <div class="user-card">
          <div class="user-avatar-lg">{{ auth.user?.username?.charAt(0)?.toUpperCase() || 'U' }}</div>
          <div class="user-card-info">
            <div class="user-card-name">{{ auth.user?.username }}</div>
            <div class="user-email">{{ auth.user?.email || '未设置邮箱' }}</div>
            <div class="user-card-role" :class="roleClass">{{ roleLabel }}</div>
          </div>
        </div>

        <button class="nav-card" type="button" @click="router.push('/billing')">
          <span class="nav-icon"><i class="fas fa-gem"></i></span>
          <span><strong>套餐与积分</strong><small>权益、兑换与账单</small></span>
          <i class="fas fa-chevron-right"></i>
        </button>

        <button class="back-btn" type="button" @click="router.push('/projects')">
          <i class="fas fa-arrow-left"></i> 返回工作台
        </button>
      </aside>

      <main class="profile-main">
        <header class="profile-heading">
          <p>账户设置</p>
          <h1>个人中心</h1>
          <span>管理登录密码、可信邮箱和账户安全信息。</span>
        </header>
        <AccountSecurityPanel />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/features/account/store'
import AppHeader from '@/shared/components/AppHeader.vue'
import AccountSecurityPanel from '@/features/account/components/AccountSecurityPanel.vue'

const router = useRouter()
const auth = useAuthStore()
const roleLabel = computed(() => {
  if (auth.user?.is_superuser) return '超级管理员'
  if (auth.user?.profile?.role === 'admin') return '管理员'
  return '普通用户'
})
const roleClass = computed(() => auth.isAdmin ? 'role-admin' : 'role-user')
</script>

<style scoped>
.profile-page{min-height:100vh;background:#f5f7fb;display:flex;flex-direction:column}.profile-body{width:min(1060px,calc(100% - 40px));margin:0 auto;padding:30px 0 52px;display:grid;grid-template-columns:250px minmax(0,1fr);gap:22px}.profile-sidebar{display:flex;flex-direction:column;gap:13px}.user-card{background:#fff;border:1px solid #e2e8f0;border-radius:15px;padding:24px 18px;text-align:center;box-shadow:0 8px 24px rgba(15,23,42,.04)}.user-avatar-lg{width:62px;height:62px;margin:0 auto 11px;border-radius:18px;background:linear-gradient(135deg,#4f46e5,#8b5cf6);display:grid;place-items:center;color:#fff;font-size:1.55rem;font-weight:800;box-shadow:0 8px 18px rgba(99,102,241,.22)}.user-card-name{font-weight:800;color:#1e293b}.user-email{font-size:.72rem;color:#94a3b8;margin-top:3px;overflow-wrap:anywhere}.user-card-role{display:inline-flex;margin-top:9px;border-radius:999px;padding:3px 9px;font-size:.68rem;font-weight:700}.role-admin{background:#ede9fe;color:#7c3aed}.role-user{background:#ecfdf5;color:#15803d}.nav-card{width:100%;border:1px solid #e2e8f0;background:#fff;border-radius:13px;padding:13px;display:grid;grid-template-columns:38px 1fr auto;align-items:center;gap:10px;text-align:left;cursor:pointer;color:#475569}.nav-card:hover{border-color:#a5b4fc;box-shadow:0 6px 18px rgba(99,102,241,.08)}.nav-icon{width:36px;height:36px;border-radius:10px;background:#eef2ff;color:#4f46e5;display:grid;place-items:center}.nav-card span:nth-child(2){display:flex;flex-direction:column}.nav-card strong{font-size:.8rem;color:#334155}.nav-card small{font-size:.68rem;color:#94a3b8;margin-top:2px}.nav-card>i{font-size:.65rem;color:#cbd5e1}.back-btn{border:1px solid #e2e8f0;background:#fff;color:#64748b;border-radius:10px;padding:9px 12px;cursor:pointer}.back-btn:hover{color:#4f46e5;border-color:#c7d2fe}.profile-main{min-width:0;display:flex;flex-direction:column;gap:18px}.profile-heading{background:#fff;border:1px solid #e2e8f0;border-radius:15px;padding:22px 25px}.profile-heading p{margin:0;color:#6366f1;font-size:.68rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.profile-heading h1{margin:4px 0;font-size:1.55rem;color:#1e293b}.profile-heading span{font-size:.8rem;color:#64748b}@media(max-width:760px){.profile-body{grid-template-columns:1fr;width:min(100% - 24px,1060px);padding-top:20px}.profile-sidebar{display:grid;grid-template-columns:1fr}.back-btn{order:3}}
</style>
