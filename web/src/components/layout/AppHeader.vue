<template>
  <header class="app-header">
    <!-- 左侧：Logo（点击返回主页） -->
    <div class="header-brand" @click="goHome" title="返回项目列表">
      <div class="header-brand-icon">
        <i class="fas fa-flask"></i>
      </div>
      <div class="header-brand-text">
        <span class="header-brand-name">科研 Meta 平台</span>
        <span class="header-brand-sub">系统化文献筛选与数据提取</span>
      </div>
    </div>

    <!-- 中间：面包屑（工作区时显示项目名和当前阶段） -->
    <div class="header-breadcrumb" v-if="project.currentProject">
      <span class="bc-sep"><i class="fas fa-chevron-right"></i></span>
      <span class="bc-item">{{ project.currentProject.name }}</span>
      <span class="bc-sep"><i class="fas fa-chevron-right"></i></span>
      <span class="bc-stage">{{ currentStageName }}</span>
    </div>

    <!-- 右侧：余额 + 用户信息 + 退出 -->
    <div class="header-right">
      <!-- 主页时显示新建项目按钮 -->
      <slot name="actions" />

      <!-- 余额展示（点击进个人中心充值） -->
      <div class="header-balance" @click="onUserClick" title="查看个人中心 / 充值">
        <i class="fas fa-coins header-balance-icon"></i>
        <span class="header-balance-val">
          <template v-if="balance !== null">{{ balance }}</template>
          <i class="fas fa-spinner fa-spin" v-else style="font-size:0.65rem;"></i>
        </span>
        <span class="header-balance-unit">credits</span>
      </div>

      <!-- 用户信息（点击进个人中心） -->
      <div class="header-user" @click="onUserClick" title="查看个人中心">
        <div class="header-avatar">
          {{ auth.user?.username?.charAt(0)?.toUpperCase() || 'U' }}
        </div>
        <span class="header-username">{{ auth.user?.username }}</span>
        <i class="fas fa-chevron-down header-user-caret"></i>
      </div>

      <!-- 退出登录 -->
      <button @click="handleLogout" class="header-logout" title="退出登录">
        <i class="fas fa-sign-out-alt"></i>
        <span>退出</span>
      </button>
    </div>
  </header>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useScreeningStore } from '@/stores/screening'
import { useTaskStore } from '@/stores/task'
import http from '@/api/http'

const router = useRouter()
const auth = useAuthStore()
const project = useProjectStore()
const screening = useScreeningStore()
const taskStore = useTaskStore()

// ── 余额 ────────────────────────────────────────────────────
const balance = ref(null)

async function fetchBalance() {
  if (!auth.user) return
  try {
    const res = await http.get('/billing/balance/')
    const data = res.data
    balance.value = data.is_unlimited ? '\u221e' : data.balance
  } catch (e) {
    // 静默失败，不影响导航栏渲染
    balance.value = 0  // 请求失败时显示 0，而不是一直 spinner
  }
}

onMounted(fetchBalance)

// 监听任务完成事件，自动刷新余额（如 AI 筛选扣费后同步显示）
window.addEventListener('app:balance-changed', fetchBalance)
onUnmounted(() => window.removeEventListener('app:balance-changed', fetchBalance))

// 暴露刷新方法，供其他组件（如 AI 筛选完成后）调用
defineExpose({ refreshBalance: fetchBalance })

// ── 面包屑 ──────────────────────────────────────────────────
const stageNames = {
  SEARCH:   '文献检索',
  SCREEN_1: '文献初筛',
  SCREEN_2: '文献复筛',
  QUALITY:  '文献质量评价',
  EXTRACT:  '数据提取',
  META:     'Meta 分析',
}
const currentStageName = computed(() => stageNames[project.currentStage] || project.currentStage)

// ── 事件 ────────────────────────────────────────────────────
function goHome() {
  project.currentProject = null
  project.currentStage = 'SCREEN_1'
  screening.reset()
  taskStore.reset()
  router.push('/')
}

function onUserClick() {
  router.push('/profile')
}

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-header {
  height: 54px;
  display: flex; align-items: center;
  padding: 0 20px 0 16px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
  gap: 0;
  z-index: 20;
  position: relative;
}

/* ── Logo ── */
.header-brand {
  display: flex; align-items: center; gap: 9px;
  cursor: pointer; padding: 6px 10px;
  border-radius: 8px; transition: background 0.15s;
  flex-shrink: 0;
}
.header-brand:hover { background: #f1f5f9; }
.header-brand-icon {
  width: 30px; height: 30px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 8px rgba(99,102,241,.3);
  flex-shrink: 0;
}
.header-brand-icon i { color: #fff; font-size: 0.8rem; }
.header-brand-text { display: flex; flex-direction: column; gap: 1px; }
.header-brand-name { font-size: 0.875rem; font-weight: 700; color: #1e293b; line-height: 1; }
.header-brand-sub { font-size: 0.65rem; color: #94a3b8; line-height: 1; }

/* ── 面包屑 ── */
.header-breadcrumb {
  display: flex; align-items: center; gap: 6px;
  flex: 1; margin-left: 6px;
  overflow: hidden;
}
.bc-sep { color: #d1d5db; font-size: 0.65rem; }
.bc-item {
  font-size: 0.8rem; color: #64748b;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 180px;
}
.bc-stage {
  font-size: 0.8rem; font-weight: 600; color: #6366f1;
  white-space: nowrap;
}

/* ── 右侧 ── */
.header-right {
  display: flex; align-items: center; gap: 8px;
  margin-left: auto; flex-shrink: 0;
}

/* 余额胶囊 */
.header-balance {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 10px;
  border-radius: 999px;
  background: #faf5ff; border: 1px solid #e9d5ff;
  cursor: pointer; transition: all 0.15s;
  white-space: nowrap;
}
.header-balance:hover { background: #f3e8ff; border-color: #c4b5fd; }
.header-balance-icon { color: #7c3aed; font-size: 0.72rem; }
.header-balance-val  { font-size: 0.82rem; font-weight: 700; color: #5b21b6; }
.header-balance-unit { font-size: 0.7rem; color: #7c3aed; }

/* 用户信息 */
.header-user {
  display: flex; align-items: center; gap: 7px;
  padding: 5px 10px;
  border-radius: 999px;
  background: #f8fafc; border: 1px solid #e2e8f0;
  cursor: pointer; transition: all 0.15s;
}
.header-user:hover { background: #f1f5f9; border-color: #c7d2fe; }
.header-avatar {
  width: 24px; height: 24px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.65rem; font-weight: 700; color: #fff;
  flex-shrink: 0;
}
.header-username { font-size: 0.8rem; font-weight: 500; color: #374151; }
.header-user-caret { font-size: 0.6rem; color: #94a3b8; }

/* 退出按钮 */
.header-logout {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 12px;
  border: 1px solid #fee2e2; border-radius: 999px;
  background: #fff; color: #ef4444;
  font-size: 0.78rem; font-weight: 500; cursor: pointer;
  transition: all 0.15s;
}
.header-logout:hover { background: #fee2e2; border-color: #fca5a5; }
</style>
