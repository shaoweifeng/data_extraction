<template>
  <aside class="sidebar">
    <!-- Logo -->
    <div class="sidebar-logo">
      <div class="sidebar-logo-icon">
        <i class="fas fa-flask"></i>
      </div>
      <div class="sidebar-logo-text">
        <span class="sidebar-logo-name">科研 Meta 平台</span>
        <span class="sidebar-logo-user">
          <i class="fas fa-circle" style="font-size:5px;color:#4ade80;vertical-align:middle;margin-right:3px;"></i>
          {{ auth.user?.username }}
        </span>
      </div>
    </div>

    <!-- 项目名称（进入项目后显示） -->
    <div v-if="project.currentProject" class="sidebar-project-header">
      <div class="sidebar-project-icon">
        {{ project.currentProject.name.charAt(0).toUpperCase() }}
      </div>
      <div class="sidebar-project-info">
        <p class="sidebar-project-name">{{ project.currentProject.name }}</p>
        <p class="sidebar-project-sub">当前项目</p>
      </div>
    </div>

    <!-- 导航 -->
    <nav class="sidebar-nav">
      <template v-if="project.currentProject">
        <!-- 6大阶段 -->
        <p class="sidebar-section-label">项目工作流</p>
        <a
          v-for="stage in stages"
          :key="stage.key"
          href="#"
          @click.prevent="handleStageClick(stage.key)"
          :class="['sidebar-nav-item', project.currentStage === stage.key ? 'sidebar-nav-active' : '']"
        >
          <div class="sidebar-nav-icon-wrap">
            <i :class="stage.icon"></i>
          </div>
          <span class="sidebar-nav-label">{{ stage.name }}</span>
          <span
            v-if="getStageStatus(stage.key)"
            class="sidebar-nav-status"
            :class="getStageStatusClass(stage.key)"
          ></span>
        </a>

        <div class="sidebar-divider"></div>
        <a href="#" @click.prevent="handleBackToList" class="sidebar-nav-item sidebar-back-btn">
          <div class="sidebar-nav-icon-wrap">
            <i class="fas fa-arrow-left"></i>
          </div>
          <span class="sidebar-nav-label">返回项目列表</span>
        </a>
      </template>

      <template v-else>
        <p class="sidebar-section-label">系统概览</p>
        <a href="#" class="sidebar-nav-item sidebar-nav-active">
          <div class="sidebar-nav-icon-wrap"><i class="fas fa-th-large"></i></div>
          <span class="sidebar-nav-label">项目列表</span>
        </a>
      </template>
    </nav>

    <!-- 底部退出 -->
    <div class="sidebar-footer">
      <button @click="handleLogout" class="sidebar-logout-btn">
        <i class="fas fa-sign-out-alt"></i>
        <span>退出登录</span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useScreeningStore } from '@/stores/screening'
import { useTaskStore } from '@/stores/task'

const router = useRouter()
const auth = useAuthStore()
const project = useProjectStore()
const screening = useScreeningStore()
const taskStore = useTaskStore()

const stages = [
  { key: 'SEARCH',   name: '文献检索',   icon: 'fas fa-search' },
  { key: 'SCREEN_1', name: '文献初筛',   icon: 'fas fa-filter' },
  { key: 'SCREEN_2', name: '文献复筛',   icon: 'fas fa-tasks' },
  { key: 'QUALITY',  name: '文献质量评价', icon: 'fas fa-shield-virus' },
  { key: 'EXTRACT',  name: '数据提取',   icon: 'fas fa-file-export' },
  { key: 'META',     name: 'Meta 分析',  icon: 'fas fa-chart-line' },
]

function getStageStatus(key) {
  const s = project.stagesData.find((s) => s.stage_key === key)
  return s?.status || null
}

function getStageStatusClass(key) {
  const status = getStageStatus(key)
  if (status === 'completed') return 'status-done'
  if (status === 'running') return 'status-running'
  return ''
}

function handleStageClick(key) {
  project.currentStage = key
  // 切换阶段时重置步骤到第1步
  if (key === 'SCREEN_1') screening.currentStep = 1
}

function handleBackToList() {
  project.currentProject = null
  project.currentStage = 'SCREEN_1'
  screening.reset()
  taskStore.reset()
  router.push('/')
}

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.sidebar {
  width: 220px; min-width: 220px;
  height: 100%;
  display: flex; flex-direction: column;
  background: linear-gradient(180deg, #1e1b4b 0%, #312e81 100%);
  color: #e2e8f0;
  overflow: hidden; flex-shrink: 0;
}

/* Logo */
.sidebar-logo {
  display: flex; align-items: center; gap: 10px;
  padding: 16px 14px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.sidebar-logo-icon {
  width: 32px; height: 32px;
  background: linear-gradient(135deg, #818cf8, #a78bfa);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  box-shadow: 0 3px 8px rgba(129,140,248,.4);
}
.sidebar-logo-icon i { color: #fff; font-size: 0.82rem; }
.sidebar-logo-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.sidebar-logo-name { font-size: 0.78rem; font-weight: 700; color: #e2e8f0; white-space: nowrap; }
.sidebar-logo-user { font-size: 0.68rem; color: #94a3b8; }

/* 项目 Header */
.sidebar-project-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  background: rgba(99,102,241,0.15);
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.sidebar-project-icon {
  width: 28px; height: 28px;
  background: linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.75rem; font-weight: 700; color: #fff; flex-shrink: 0;
}
.sidebar-project-info { min-width: 0; }
.sidebar-project-name {
  font-size: 0.78rem; font-weight: 600; color: #e0e7ff;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 0;
}
.sidebar-project-sub { font-size: 0.65rem; color: #6366f1; margin: 1px 0 0; }

/* Nav */
.sidebar-nav { flex: 1; overflow-y: auto; padding: 6px 8px 0; }
.sidebar-section-label {
  font-size: 0.62rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.07em; color: #475569; padding: 6px 8px 4px;
}

.sidebar-nav-item {
  display: flex; align-items: center; gap: 9px;
  padding: 8px 10px;
  border-radius: 9px; margin-bottom: 2px;
  cursor: pointer; transition: all 0.18s;
  text-decoration: none; color: #94a3b8;
  border: 1px solid transparent;
  position: relative;
}
.sidebar-nav-item:hover { background: rgba(255,255,255,0.06); color: #cbd5e1; }
.sidebar-nav-active {
  background: rgba(99,102,241,0.22) !important;
  color: #c7d2fe !important;
  border-color: rgba(99,102,241,0.3);
}
.sidebar-nav-icon-wrap {
  width: 26px; height: 26px;
  border-radius: 7px;
  background: rgba(255,255,255,0.07);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; font-size: 0.72rem;
}
.sidebar-nav-active .sidebar-nav-icon-wrap {
  background: rgba(129,140,248,0.3); color: #a5b4fc;
}
.sidebar-nav-label { font-size: 0.8rem; font-weight: 500; flex: 1; }

/* 阶段状态点 */
.sidebar-nav-status {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.status-done { background: #4ade80; }
.status-running { background: #60a5fa; animation: pulse 1.2s infinite; }
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(.7)} }

.sidebar-divider {
  height: 1px; background: rgba(255,255,255,0.07);
  margin: 6px 8px;
}
.sidebar-back-btn { color: #64748b; }
.sidebar-back-btn:hover { color: #94a3b8; }

/* Footer */
.sidebar-footer {
  padding: 8px 10px 12px;
  border-top: 1px solid rgba(255,255,255,0.07);
}
.sidebar-logout-btn {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 9px; border: none;
  background: transparent; color: #64748b;
  font-size: 0.8rem; cursor: pointer; transition: all 0.18s;
}
.sidebar-logout-btn:hover { background: rgba(239,68,68,0.1); color: #f87171; }
</style>
