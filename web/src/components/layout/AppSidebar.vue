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
        @click="$emit('new-project')"
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
          class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 ml-2 text-xs transition-all"
        >删除</button>
      </div>
    </div>

    <!-- 底部退出按钮 -->
    <div class="p-3 border-t border-gray-200">
      <button
        @click="handleLogout"
        class="w-full px-3 py-2 text-sm text-gray-600 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
      >退出登录</button>
    </div>
  </aside>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useScreeningStore } from '@/stores/screening'
import { useTaskStore } from '@/stores/task'

defineEmits(['new-project'])

const router = useRouter()
const auth = useAuthStore()
const project = useProjectStore()
const screening = useScreeningStore()
const taskStore = useTaskStore()

async function handleSelectProject(p) {
  // 重置所有相关状态
  screening.reset()
  taskStore.reset()
  await project.selectProject(p)
  router.push(`/workspace/${p.id}`)
}

async function handleDeleteProject(projectId) {
  if (!confirm('确定要删除该项目吗？此操作不可恢复！')) return
  try {
    await project.deleteProject(projectId)
    if (router.currentRoute.value.name === 'Workspace') {
      router.push('/')
    }
  } catch (e) {
    alert(e.response?.data?.error || '删除失败')
  }
}

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>
