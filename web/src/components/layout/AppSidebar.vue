<template>
  <aside class="w-64 bg-white border-r border-gray-200 flex flex-col h-full">
    <!-- Logo / 标题 -->
    <div class="p-4 border-b border-gray-200">
      <h2 class="font-bold text-gray-800 text-sm">科研数据提取平台</h2>
      <p class="text-xs text-gray-500 mt-0.5">{{ auth.user?.username }}</p>
    </div>

    <!-- 新建项目按钮 -->
    <div class="p-3">
      <button
        @click="showModal = true"
        class="w-full flex items-center gap-2 px-3 py-2 text-sm text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 transition-colors"
      >
        <span>+</span> 新建项目
      </button>
    </div>

    <!-- 项目列表 -->
    <div class="flex-1 overflow-auto px-2">
      <p class="text-xs text-gray-400 px-2 py-1 font-medium">项目列表</p>

      <div v-if="project.projects.length === 0" class="px-3 py-4 text-xs text-gray-400 text-center">
        暂无项目
      </div>

      <div
        v-for="p in project.projects"
        :key="p.id"
        @click="handleSelectProject(p)"
        :class="[
          'flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer mb-1 group transition-colors',
          project.currentProject?.id === p.id
            ? 'sidebar-item-active'
            : 'hover:bg-gray-100 text-gray-700',
        ]"
      >
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium truncate">{{ p.name }}</p>
          <p class="text-xs text-gray-400 truncate mt-0.5">{{ p.description || '暂无描述' }}</p>
        </div>
        <button
          @click.stop="handleDeleteProject(p.id)"
          class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 ml-2 text-xs transition-all shrink-0"
          title="删除项目"
        >✕</button>
      </div>
    </div>

    <!-- 底部退出按钮 -->
    <div class="p-3 border-t border-gray-200">
      <button
        @click="handleLogout"
        class="w-full px-3 py-2 text-sm text-gray-600 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors text-left"
      >退出登录</button>
    </div>
  </aside>

  <!-- 新建项目 Modal（放在 aside 外，避免被 overflow:hidden 裁剪）-->
  <Teleport to="body">
    <div
      v-if="showModal"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      @click.self="showModal = false"
    >
      <div class="bg-white rounded-xl p-6 w-96 shadow-xl">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">新建项目</h3>
        <form @submit.prevent="handleCreate" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">项目名称 *</label>
            <input
              v-model="newProject.name"
              type="text"
              required
              autofocus
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="输入项目名称"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">项目描述</label>
            <textarea
              v-model="newProject.description"
              rows="3"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              placeholder="（可选）简短描述项目内容"
            />
          </div>
          <p v-if="createError" class="text-red-500 text-sm">{{ createError }}</p>
          <div class="flex gap-3 pt-2">
            <button
              type="button"
              @click="showModal = false"
              class="flex-1 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
            >取消</button>
            <button
              type="submit"
              :disabled="creating"
              class="flex-1 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >{{ creating ? '创建中...' : '创建' }}</button>
          </div>
        </form>
      </div>
    </div>
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
  // 重置所有相关状态
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
    // 创建后直接进入工作区
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
