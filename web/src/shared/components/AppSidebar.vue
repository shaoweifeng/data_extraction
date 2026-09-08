<template>
  <aside class="sidebar">
    <!-- 当前项目信息（只在工作区显示） -->
    <div v-if="project.currentProject" class="sidebar-project-section">
      <div class="sidebar-project-card">
        <div class="sidebar-project-icon">
          {{ project.currentProject.name.charAt(0).toUpperCase() }}
        </div>
        <div class="sidebar-project-info">
          <p class="sidebar-project-name">{{ project.currentProject.name }}</p>
          <p class="sidebar-project-sub">当前项目</p>
        </div>
      </div>
    </div>

    <!-- 导航区 -->
    <nav class="sidebar-nav">
      <template v-if="project.currentProject">
        <!-- 6大阶段 -->
        <p class="sidebar-section-label">研究阶段</p>
        <a
          v-for="stage in stages"
          :key="stage.key"
          href="#"
          @click.prevent="handleStageClick(stage.key)"
          :class="['sidebar-nav-item', project.currentStage === stage.key && 'sidebar-nav-active']"
        >
          <div class="sidebar-nav-icon-wrap">
            <i :class="stage.icon"></i>
          </div>
          <span class="sidebar-nav-label">{{ stage.name }}</span>
          <span
            v-if="getStageStatus(stage.key) === 'completed'"
            class="status-dot status-done"
          ></span>
          <span
            v-else-if="getStageStatus(stage.key) === 'running'"
            class="status-dot status-running"
          ></span>
        </a>
      </template>
    </nav>

    <!-- 底部：返回项目列表（醒目） -->
    <div v-if="project.currentProject" class="sidebar-back-section">
      <button @click="handleBackToList" class="sidebar-back-btn">
        <i class="fas fa-arrow-left"></i>
        <span>返回项目列表</span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'

const router = useRouter()
const project = useProjectStore()
const taskStore = useTaskStore()

const stages = [
  { key: 'SEARCH',   name: '文献检索',     icon: 'fas fa-search' },
  { key: 'SCREEN_1', name: '文献初筛',     icon: 'fas fa-filter' },
  { key: 'SCREEN_2', name: '文献复筛',     icon: 'fas fa-tasks' },
  { key: 'QUALITY',  name: '文献质量评价', icon: 'fas fa-shield-virus' },
  { key: 'EXTRACT',  name: '数据提取',     icon: 'fas fa-file-export' },
  { key: 'META',     name: 'Meta 分析',    icon: 'fas fa-chart-line' },
]

function getStageStatus(key) {
  return project.stagesData.find((s) => s.stage_key === key)?.status || null
}

function handleStageClick(key) {
  project.currentStage = key
  window.dispatchEvent(new CustomEvent('app:stage-changed', { detail: { stage: key } }))
}

function handleBackToList() {
  project.currentProject = null
  project.currentStage = 'SCREEN_1'
  taskStore.reset()
  window.dispatchEvent(new CustomEvent('app:project-left'))
  router.push('/')
}
</script>

<style scoped>
.sidebar {
  width: 210px; min-width: 210px;
  height: 100%;
  display: flex; flex-direction: column;
  background: linear-gradient(180deg, #1e1b4b 0%, #312e81 100%);
  color: #e2e8f0;
  overflow: hidden; flex-shrink: 0;
}

/* 当前项目 */
.sidebar-project-section {
  padding: 10px 10px 6px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
}
.sidebar-project-card {
  display: flex; align-items: center; gap: 8px;
  background: rgba(99,102,241,0.18);
  border: 1px solid rgba(99,102,241,0.25);
  border-radius: 10px;
  padding: 8px 10px;
}
.sidebar-project-icon {
  width: 28px; height: 28px;
  background: linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.72rem; font-weight: 700; color: #fff; flex-shrink: 0;
}
.sidebar-project-info { min-width: 0; }
.sidebar-project-name {
  font-size: 0.78rem; font-weight: 600; color: #e0e7ff;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 0;
}
.sidebar-project-sub { font-size: 0.62rem; color: #818cf8; margin: 1px 0 0; }

/* Nav */
.sidebar-nav { flex: 1; overflow-y: auto; padding: 8px 8px 0; }
.sidebar-section-label {
  font-size: 0.6rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.08em; color: #4b5563; padding: 4px 8px 5px; margin: 0;
}

.sidebar-nav-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 9px; border-radius: 9px; margin-bottom: 2px;
  cursor: pointer; transition: all 0.15s;
  text-decoration: none; color: #94a3b8;
  border: 1px solid transparent;
}
.sidebar-nav-item:hover { background: rgba(255,255,255,0.06); color: #cbd5e1; }
.sidebar-nav-active {
  background: rgba(99,102,241,0.22) !important;
  color: #c7d2fe !important;
  border-color: rgba(99,102,241,0.28) !important;
}
.sidebar-nav-icon-wrap {
  width: 24px; height: 24px; border-radius: 6px;
  background: rgba(255,255,255,0.07);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; font-size: 0.7rem;
}
.sidebar-nav-active .sidebar-nav-icon-wrap {
  background: rgba(129,140,248,0.3); color: #a5b4fc;
}
.sidebar-nav-label { font-size: 0.78rem; font-weight: 500; flex: 1; }

/* 阶段状态点 */
.status-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.status-done { background: #4ade80; }
.status-running { background: #60a5fa; animation: pulse 1.2s infinite; }
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(.7)} }

/* 返回按钮（醒目） */
.sidebar-back-section {
  padding: 8px 10px 10px;
  border-top: 1px solid rgba(255,255,255,0.08);
}
.sidebar-back-btn {
  width: 100%;
  display: flex; align-items: center; justify-content: center; gap: 7px;
  padding: 8px 12px; border-radius: 9px;
  border: 1px solid rgba(165,180,252,0.3);
  background: rgba(99,102,241,0.15);
  color: #a5b4fc;
  font-size: 0.8rem; font-weight: 600; cursor: pointer;
  transition: all 0.18s;
}
.sidebar-back-btn:hover {
  background: rgba(99,102,241,0.28);
  border-color: rgba(165,180,252,0.5);
  color: #c7d2fe;
}
.sidebar-back-btn i { font-size: 0.75rem; }
</style>
