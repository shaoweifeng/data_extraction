<template>
  <div class="page-layout">
    <AppSidebar />
    <main class="main-content">
      <!-- 顶部 Header -->
      <div class="top-bar">
        <div>
          <h1 class="top-bar-title">欢迎回来，{{ auth.user?.username }} 👋</h1>
          <p class="top-bar-sub">从左侧选择项目继续工作，或新建项目开始</p>
        </div>
      </div>

      <!-- 欢迎卡片 -->
      <div class="home-welcome-card">
        <!-- 顶部图标+说明 -->
        <div class="welcome-hero">
          <div class="welcome-icon-wrap">
            <i class="fas fa-microscope"></i>
          </div>
          <div>
            <h2 class="welcome-heading">科研文献筛选与数据提取</h2>
            <p class="welcome-desc">
              支持从 RIS、BibTeX、NBIB 等格式导入文献，自动去重，基于自定义纳排标准完成 AI 初筛，最终导出结构化数据。
            </p>
          </div>
        </div>

        <!-- 特性卡片 -->
        <div class="feature-grid">
          <div class="feature-card" v-for="f in features" :key="f.title">
            <div class="feature-icon" :style="{ background: f.bg }">
              <i :class="f.icon" :style="{ color: f.color }"></i>
            </div>
            <div>
              <p class="feature-title">{{ f.title }}</p>
              <p class="feature-desc">{{ f.desc }}</p>
            </div>
          </div>
        </div>

        <!-- 项目统计 -->
        <div v-if="project.projects.length > 0" class="project-stats">
          <div class="stat-item">
            <span class="stat-num">{{ project.projects.length }}</span>
            <span class="stat-label">个项目</span>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const auth = useAuthStore()
const project = useProjectStore()

const features = [
  {
    icon: 'fas fa-file-import',
    title: '文献解析',
    desc: '支持 RIS / BibTeX / NBIB / TXT 多种格式批量导入',
    bg: '#eff6ff', color: '#3b82f6',
  },
  {
    icon: 'fas fa-copy',
    title: '智能去重',
    desc: '自动识别并合并重复文献，保留最优记录',
    bg: '#faf5ff', color: '#8b5cf6',
  },
  {
    icon: 'fas fa-robot',
    title: 'AI 初筛',
    desc: '基于纳排标准，大模型自动判断文献是否纳入',
    bg: '#ecfdf5', color: '#10b981',
  },
  {
    icon: 'fas fa-file-excel',
    title: '结果导出',
    desc: '纳入/排除文献分类导出，Excel 与 RIS 双格式',
    bg: '#fff7ed', color: '#f59e0b',
  },
]

onMounted(async () => {
  await project.fetchProjects()
})
</script>

<style scoped>
.page-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: #f8fafc;
}
.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-width: 0;
}

/* 顶部 Header */
.top-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 24px 32px 0;
}
.top-bar-title { font-size: 1.375rem; font-weight: 700; color: #1e293b; margin: 0; }
.top-bar-sub { font-size: 0.85rem; color: #94a3b8; margin: 4px 0 0; }

/* 欢迎卡 */
.home-welcome-card {
  margin: 20px 32px;
  background: #fff;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
  overflow: hidden;
}

.welcome-hero {
  display: flex; align-items: flex-start; gap: 16px;
  padding: 24px 24px 20px;
  border-bottom: 1px solid #f1f5f9;
}
.welcome-icon-wrap {
  width: 52px; height: 52px; flex-shrink: 0;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 8px 20px rgba(99,102,241,.3);
}
.welcome-icon-wrap i { font-size: 1.4rem; color: #fff; }
.welcome-heading { font-size: 1.1rem; font-weight: 700; color: #1e293b; margin: 0 0 6px; }
.welcome-desc { font-size: 0.83rem; color: #64748b; line-height: 1.6; margin: 0; max-width: 560px; }

/* 特性网格 */
.feature-grid {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 1px; background: #f1f5f9;
}
.feature-card {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 18px 20px; background: #fff;
}
.feature-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.feature-icon i { font-size: 0.9rem; }
.feature-title { font-size: 0.82rem; font-weight: 600; color: #1e293b; margin: 0 0 3px; }
.feature-desc { font-size: 0.75rem; color: #94a3b8; margin: 0; line-height: 1.45; }

/* 项目统计 */
.project-stats {
  padding: 14px 24px;
  border-top: 1px solid #f1f5f9;
  display: flex; gap: 24px;
}
.stat-item { display: flex; align-items: baseline; gap: 4px; }
.stat-num { font-size: 1.5rem; font-weight: 700; color: #6366f1; }
.stat-label { font-size: 0.8rem; color: #94a3b8; }

@media (max-width: 900px) {
  .feature-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
