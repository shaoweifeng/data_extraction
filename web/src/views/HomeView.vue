<template>
  <div class="flex h-screen bg-gray-50">
    <!-- 左侧项目列表 -->
    <AppSidebar />

    <!-- 右侧主内容 -->
    <main class="flex-1 overflow-auto p-8">
      <div class="max-w-4xl mx-auto">
        <!-- 顶部标题 -->
        <div class="flex items-center justify-between mb-8">
          <div>
            <h1 class="text-2xl font-bold text-gray-900">科研数据提取平台</h1>
            <p class="text-gray-500 mt-1">选择左侧项目开始工作</p>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-sm text-gray-600">{{ auth.user?.username }}</span>
            <button
              @click="handleLogout"
              class="px-3 py-1.5 text-sm text-gray-600 hover:text-red-600 border border-gray-300 rounded-lg hover:border-red-300 transition-colors"
            >退出</button>
          </div>
        </div>

        <!-- 空状态提示 -->
        <div class="bg-white rounded-xl border border-gray-200 p-16 text-center">
          <div class="text-5xl mb-4">📂</div>
          <h3 class="text-lg font-medium text-gray-700 mb-2">从左侧选择项目，或创建新项目</h3>
          <p class="text-gray-500 text-sm">每个项目包含文献解析、去重、初筛等完整工作流程</p>
        </div>
      </div>
    </main>

    <!-- 新建项目 Modal -->
    <div
      v-if="showNewProjectModal"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      @click.self="showNewProjectModal = false"
    >
      <div class="bg-white rounded-xl p-6 w-96 shadow-xl">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">新建项目</h3>
        <form @submit.prevent="handleCreateProject" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">项目名称 *</label>
            <input
              v-model="newProject.name"
              type="text"
              required
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
          <div class="flex gap-3 pt-2">
            <button
              type="button"
              @click="showNewProjectModal = false"
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const router = useRouter()
const auth = useAuthStore()
const projectStore = useProjectStore()

const showNewProjectModal = ref(false)
const newProject = ref({ name: '', description: '' })
const creating = ref(false)

onMounted(async () => {
  await projectStore.fetchProjects()
})

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}

async function handleCreateProject() {
  if (!newProject.value.name) return
  creating.value = true
  try {
    await projectStore.createProject(newProject.value)
    showNewProjectModal.value = false
    newProject.value = { name: '', description: '' }
  } catch (e) {
    alert(e.response?.data?.error || '创建失败')
  } finally {
    creating.value = false
  }
}

// 暴露给 AppSidebar 触发新建项目 modal
defineExpose({ showNewProjectModal })
</script>
