<template>
  <div class="home-page">
    <!-- 顶部 Header -->
    <header class="home-header">
      <div class="home-header-brand">
        <div class="brand-icon"><i class="fas fa-flask"></i></div>
        <div>
          <h1 class="brand-name">科研 Meta 平台</h1>
          <p class="brand-sub">系统化完成文献筛选与数据提取</p>
        </div>
      </div>
      <div class="home-header-right">
        <button @click="showModal = true" class="btn-primary">
          <i class="fas fa-plus"></i> 新建项目
        </button>
        <div class="user-chip">
          <i class="fas fa-user-circle"></i>
          {{ auth.user?.username }}
        </div>
        <button @click="handleLogout" class="logout-btn">
          <i class="fas fa-sign-out-alt"></i>
        </button>
      </div>
    </header>

    <!-- 主内容 -->
    <div class="home-body">
      <!-- 空状态 -->
      <div v-if="!loading && project.projects.length === 0" class="home-empty">
        <div class="empty-icon"><i class="fas fa-folder-open"></i></div>
        <h3>还没有项目</h3>
        <p>点击「新建项目」开始你的第一个文献研究</p>
        <button @click="showModal = true" class="btn-primary mt-4">
          <i class="fas fa-plus"></i> 新建项目
        </button>
      </div>

      <!-- 项目卡片网格 -->
      <div v-else class="project-grid">
        <div
          v-for="p in project.projects"
          :key="p.id"
          class="project-card"
          @click="handleSelectProject(p)"
        >
          <div class="project-card-top">
            <div class="project-card-icon">
              {{ p.name.charAt(0).toUpperCase() }}
            </div>
            <button
              @click.stop="handleDeleteProject(p.id)"
              class="project-card-del"
              title="删除项目"
            >
              <i class="fas fa-trash"></i>
            </button>
          </div>
          <h3 class="project-card-name">{{ p.name }}</h3>
          <p class="project-card-desc">{{ p.description || '暂无描述' }}</p>
          <div class="project-card-footer">
            <span class="project-card-date">
              <i class="fas fa-calendar-alt mr-1"></i>
              {{ p.created_at ? new Date(p.created_at).toLocaleDateString('zh-CN') : '' }}
            </span>
            <span class="project-card-arrow">
              进入 <i class="fas fa-arrow-right ml-1"></i>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建项目 Modal -->
    <Teleport to="body">
      <Transition name="modal-fade">
        <div v-if="showModal" class="modal-mask" @click.self="showModal = false">
          <div class="modal-box">
            <div class="modal-header">
              <div class="modal-title-icon">
                <i class="fas fa-folder-plus"></i>
              </div>
              <div>
                <h3 class="modal-title">新建项目</h3>
                <p class="modal-subtitle">创建一个新的文献筛选研究项目</p>
              </div>
              <button @click="showModal = false" class="modal-close">
                <i class="fas fa-times"></i>
              </button>
            </div>
            <form @submit.prevent="handleCreate" class="modal-body">
              <div class="form-group">
                <label class="form-label">项目名称 <span class="text-red-500">*</span></label>
                <input
                  v-model="newProject.name"
                  type="text" required autofocus
                  class="input-base"
                  placeholder="例如：糖尿病文献筛查 2024"
                />
              </div>
              <div class="form-group">
                <label class="form-label">项目描述</label>
                <textarea
                  v-model="newProject.description"
                  rows="3" class="input-base"
                  style="resize:none"
                  placeholder="（可选）简述项目研究方向"
                />
              </div>
              <p v-if="createError" class="form-error-msg">
                <i class="fas fa-exclamation-circle mr-1"></i>{{ createError }}
              </p>
              <div class="modal-actions">
                <button type="button" @click="showModal = false" class="btn-secondary">取消</button>
                <button type="submit" :disabled="creating" class="btn-primary">
                  <span v-if="creating"><i class="fas fa-spinner fa-spin mr-1"></i>创建中...</span>
                  <span v-else><i class="fas fa-check mr-1"></i>创建项目</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
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

const loading = ref(true)
const showModal = ref(false)
const newProject = ref({ name: '', description: '' })
const creating = ref(false)
const createError = ref('')

onMounted(async () => {
  await project.fetchProjects()
  loading.value = false
})

async function handleSelectProject(p) {
  screening.reset()
  taskStore.reset()
  await project.selectProject(p)
  router.push(`/workspace/${p.id}`)
}

async function handleDeleteProject(projectId) {
  if (!confirm('确定要删除该项目吗？此操作将删除项目下所有数据，且不可恢复！')) return
  try {
    await project.deleteProject(projectId)
  } catch (e) {
    alert(e.response?.data?.error || '删除失败')
  }
}

async function handleCreate() {
  if (!newProject.value.name.trim()) return
  createError.value = ''
  creating.value = true
  try {
    const created = await project.createProject({ ...newProject.value })
    showModal.value = false
    newProject.value = { name: '', description: '' }
    await project.selectProject(created)
    router.push(`/workspace/${created.id}`)
  } catch (e) {
    createError.value = e.response?.data?.error || '创建失败'
  } finally {
    creating.value = false
  }
}

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.home-page {
  min-height: 100vh;
  background: #f8fafc;
  display: flex; flex-direction: column;
}

/* ── Header ── */
.home-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 32px;
  height: 64px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
  position: sticky; top: 0; z-index: 10;
}
.home-header-brand {
  display: flex; align-items: center; gap: 12px;
}
.brand-icon {
  width: 38px; height: 38px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 12px rgba(99,102,241,.3);
}
.brand-icon i { color: #fff; font-size: 1rem; }
.brand-name { font-size: 1rem; font-weight: 700; color: #1e293b; margin: 0; }
.brand-sub { font-size: 0.72rem; color: #94a3b8; margin: 0; }

.home-header-right {
  display: flex; align-items: center; gap: 10px;
}
.user-chip {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  background: #f1f5f9; border-radius: 999px;
  font-size: 0.82rem; color: #374151;
}
.logout-btn {
  width: 34px; height: 34px; border-radius: 8px; border: 1px solid #e2e8f0;
  background: #fff; color: #94a3b8; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.logout-btn:hover { background: #fee2e2; color: #ef4444; border-color: #fecaca; }

/* ── 主体 ── */
.home-body {
  flex: 1; padding: 32px;
  max-width: 1200px; width: 100%; margin: 0 auto;
}

/* 空状态 */
.home-empty {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 6rem 2rem; text-align: center;
}
.empty-icon {
  width: 72px; height: 72px;
  background: linear-gradient(135deg,#e0e7ff,#ede9fe);
  border-radius: 20px;
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 16px;
}
.empty-icon i { font-size: 1.8rem; color: #6366f1; }
.home-empty h3 { font-size: 1.2rem; font-weight: 700; color: #1e293b; margin: 0 0 8px; }
.home-empty p { font-size: 0.875rem; color: #94a3b8; margin: 0; }

/* 项目网格 */
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.project-card {
  background: #fff;
  border-radius: 14px;
  border: 1px solid #e2e8f0;
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex; flex-direction: column;
}
.project-card:hover {
  border-color: #a5b4fc;
  box-shadow: 0 8px 24px rgba(99,102,241,.12);
  transform: translateY(-2px);
}
.project-card-top {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 14px;
}
.project-card-icon {
  width: 46px; height: 46px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.1rem; font-weight: 700; color: #fff;
  box-shadow: 0 4px 12px rgba(99,102,241,.3);
}
.project-card-del {
  opacity: 0; width: 30px; height: 30px;
  border: 1px solid #fee2e2; border-radius: 8px;
  background: #fff; color: #f87171;
  cursor: pointer; transition: all 0.15s;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.75rem;
}
.project-card:hover .project-card-del { opacity: 1; }
.project-card-del:hover { background: #fee2e2; }

.project-card-name {
  font-size: 1rem; font-weight: 700; color: #1e293b;
  margin: 0 0 6px;
}
.project-card-desc {
  font-size: 0.8rem; color: #64748b;
  line-height: 1.5; margin: 0;
  flex: 1;
  display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden;
}
.project-card-footer {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 14px; padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}
.project-card-date { font-size: 0.72rem; color: #94a3b8; }
.project-card-arrow { font-size: 0.75rem; color: #6366f1; font-weight: 500; }

/* Modal */
.modal-mask {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.45);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-box {
  background: #fff; border-radius: 16px;
  width: 100%; max-width: 440px;
  box-shadow: 0 25px 50px rgba(0,0,0,.2);
  overflow: hidden;
}
.modal-header {
  display: flex; align-items: center; gap: 12px;
  padding: 20px 20px 0;
}
.modal-title-icon {
  width: 40px; height: 40px;
  background: linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.modal-title-icon i { color: #fff; font-size: 1rem; }
.modal-title { font-size: 1rem; font-weight: 700; color: #1e293b; margin: 0; }
.modal-subtitle { font-size: 0.75rem; color: #94a3b8; margin: 2px 0 0; }
.modal-close {
  margin-left: auto; width: 28px; height: 28px;
  border: none; border-radius: 8px; background: #f1f5f9;
  color: #64748b; cursor: pointer; transition: all 0.15s;
  display: flex; align-items: center; justify-content: center;
}
.modal-close:hover { background: #fee2e2; color: #ef4444; }
.modal-body { padding: 16px 20px 20px; display: flex; flex-direction: column; gap: 14px; }
.form-group { display: flex; flex-direction: column; gap: 5px; }
.form-label { font-size: 0.8rem; font-weight: 600; color: #374151; }
.form-error-msg {
  background: #fff1f2; border: 1px solid #fecdd3;
  color: #be123c; font-size: 0.8rem;
  padding: 0.5rem 0.75rem; border-radius: 8px;
}
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; }

.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.2s; }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }

.mt-4 { margin-top: 1rem; }
</style>
