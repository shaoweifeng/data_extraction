<template>
  <aside class="sidebar">
    <!-- Logo 区 -->
    <div class="sidebar-logo">
      <div class="sidebar-logo-icon">
        <i class="fas fa-flask"></i>
      </div>
      <div class="sidebar-logo-text">
        <span class="sidebar-logo-name">科研提取平台</span>
        <span class="sidebar-logo-user">
          <i class="fas fa-circle text-green-400" style="font-size:6px;vertical-align:middle;margin-right:4px;"></i>
          {{ auth.user?.username }}
        </span>
      </div>
    </div>

    <!-- 新建项目按钮 -->
    <div class="sidebar-new-btn-wrap">
      <button @click="showModal = true" class="sidebar-new-btn">
        <i class="fas fa-plus"></i>
        <span>新建项目</span>
      </button>
    </div>

    <!-- 项目列表 -->
    <div class="sidebar-list-wrap">
      <p class="sidebar-section-label">我的项目</p>

      <div v-if="project.projects.length === 0" class="sidebar-empty">
        <i class="fas fa-folder-open mb-2 text-xl opacity-40"></i>
        <span>暂无项目，点击新建</span>
      </div>

      <div
        v-for="p in project.projects"
        :key="p.id"
        @click="handleSelectProject(p)"
        :class="['sidebar-item', project.currentProject?.id === p.id ? 'sidebar-item-active' : '']"
      >
        <div class="sidebar-item-icon">
          {{ p.name.charAt(0).toUpperCase() }}
        </div>
        <div class="sidebar-item-info">
          <p class="sidebar-item-name">{{ p.name }}</p>
          <p class="sidebar-item-desc">{{ p.description || '暂无描述' }}</p>
        </div>
        <button
          @click.stop="handleDeleteProject(p.id)"
          class="sidebar-item-del"
          title="删除项目"
        >
          <i class="fas fa-times"></i>
        </button>
      </div>
    </div>

    <!-- 底部操作 -->
    <div class="sidebar-footer">
      <button @click="handleLogout" class="sidebar-logout-btn">
        <i class="fas fa-sign-out-alt"></i>
        <span>退出登录</span>
      </button>
    </div>
  </aside>

  <!-- 新建项目 Modal -->
  <Teleport to="body">
    <Transition name="modal-fade">
      <div
        v-if="showModal"
        class="modal-mask"
        @click.self="showModal = false"
      >
        <div class="modal-box">
          <div class="modal-header">
            <div class="modal-title-icon">
              <i class="fas fa-folder-plus"></i>
            </div>
            <div>
              <h3 class="modal-title">新建项目</h3>
              <p class="modal-subtitle">创建一个新的文献筛选项目</p>
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
                type="text"
                required
                autofocus
                class="input-base"
                placeholder="例如：糖尿病文献筛查 2024"
              />
            </div>
            <div class="form-group">
              <label class="form-label">项目描述</label>
              <textarea
                v-model="newProject.description"
                rows="3"
                class="input-base"
                style="resize:none"
                placeholder="（可选）简述项目研究方向"
              />
            </div>
            <p v-if="createError" class="form-error-msg">
              <i class="fas fa-exclamation-circle mr-1"></i>{{ createError }}
            </p>
            <div class="modal-actions">
              <button
                type="button"
                @click="showModal = false"
                class="btn-secondary"
              >取消</button>
              <button
                type="submit"
                :disabled="creating"
                class="btn-primary"
              >
                <span v-if="creating"><i class="fas fa-spinner fa-spin mr-1"></i>创建中...</span>
                <span v-else><i class="fas fa-check mr-1"></i>创建项目</span>
              </button>
            </div>
          </form>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
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

const showModal = ref(false)
const newProject = ref({ name: '', description: '' })
const creating = ref(false)
const createError = ref('')

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
    if (router.currentRoute.value.params.projectId === String(projectId)) {
      router.push('/')
    }
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
/* ── 侧边栏容器 ── */
.sidebar {
  width: 240px;
  min-width: 240px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #1e1b4b 0%, #312e81 100%);
  color: #e2e8f0;
  overflow: hidden;
  flex-shrink: 0;
}

/* ── Logo 区 ── */
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.sidebar-logo-icon {
  width: 36px; height: 36px;
  background: linear-gradient(135deg, #818cf8, #a78bfa);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(129,140,248,.4);
}
.sidebar-logo-icon i { color: #fff; font-size: 0.9rem; }
.sidebar-logo-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.sidebar-logo-name { font-size: 0.8rem; font-weight: 700; color: #e2e8f0; white-space: nowrap; }
.sidebar-logo-user { font-size: 0.7rem; color: #94a3b8; }

/* ── 新建按钮 ── */
.sidebar-new-btn-wrap { padding: 12px 12px 6px; }
.sidebar-new-btn {
  width: 100%;
  display: flex; align-items: center; gap: 8px;
  padding: 9px 14px;
  background: rgba(129,140,248,0.18);
  border: 1px solid rgba(129,140,248,0.3);
  border-radius: 10px;
  color: #a5b4fc;
  font-size: 0.85rem; font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.sidebar-new-btn:hover {
  background: rgba(129,140,248,0.28);
  color: #c7d2fe;
  border-color: rgba(129,140,248,0.5);
}

/* ── 项目列表 ── */
.sidebar-list-wrap { flex: 1; overflow-y: auto; padding: 6px 8px 0; }
.sidebar-section-label {
  font-size: 0.65rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.07em;
  color: #475569; padding: 4px 8px 6px;
}
.sidebar-empty {
  display: flex; flex-direction: column; align-items: center;
  padding: 2rem 1rem; color: #475569; font-size: 0.75rem;
  text-align: center; gap: 4px;
}

.sidebar-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 10px;
  border-radius: 10px;
  cursor: pointer;
  margin-bottom: 2px;
  transition: all 0.18s;
  border-left: 3px solid transparent;
  position: relative;
}
.sidebar-item:hover { background: rgba(255,255,255,0.06); }
.sidebar-item-active {
  background: rgba(99,102,241,0.2) !important;
  border-left-color: #818cf8;
}
.sidebar-item-icon {
  width: 30px; height: 30px;
  background: rgba(255,255,255,0.1);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.8rem; font-weight: 700; color: #a5b4fc;
  flex-shrink: 0;
}
.sidebar-item-active .sidebar-item-icon {
  background: rgba(129,140,248,0.3); color: #c7d2fe;
}
.sidebar-item-info { flex: 1; min-width: 0; }
.sidebar-item-name {
  font-size: 0.8rem; font-weight: 500; color: #cbd5e1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sidebar-item-active .sidebar-item-name { color: #e0e7ff; }
.sidebar-item-desc {
  font-size: 0.68rem; color: #475569;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  margin-top: 1px;
}

.sidebar-item-del {
  opacity: 0; width: 22px; height: 22px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 6px; border: none;
  background: transparent; color: #64748b;
  cursor: pointer; transition: all 0.15s; flex-shrink: 0;
}
.sidebar-item:hover .sidebar-item-del { opacity: 1; }
.sidebar-item-del:hover { background: rgba(239,68,68,0.15); color: #f87171; }

/* ── 底部 ── */
.sidebar-footer {
  padding: 10px 12px 14px;
  border-top: 1px solid rgba(255,255,255,0.07);
}
.sidebar-logout-btn {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 9px 14px; border-radius: 10px; border: none;
  background: transparent; color: #64748b;
  font-size: 0.82rem; cursor: pointer; transition: all 0.18s;
}
.sidebar-logout-btn:hover { background: rgba(239,68,68,0.1); color: #f87171; }

/* ── Modal ── */
.modal-mask {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.5);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-box {
  background: #fff; border-radius: 16px;
  width: 100%; max-width: 440px;
  box-shadow: 0 25px 50px rgba(0,0,0,0.25);
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
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
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
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; padding-top: 4px; }

/* Modal 动画 */
.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity 0.2s, transform 0.2s; }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
.modal-fade-enter-from .modal-box, .modal-fade-leave-to .modal-box { transform: scale(0.96) translateY(8px); }
</style>
