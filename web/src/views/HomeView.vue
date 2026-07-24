<template>
  <div class="flex h-screen bg-gray-50">
    <!-- 左侧项目列表（含新建项目逻辑） -->
    <AppSidebar />

    <!-- 右侧主内容 -->
    <main class="flex-1 overflow-auto p-8">
      <div class="max-w-4xl mx-auto">
        <!-- 顶部标题 -->
        <div class="flex items-center justify-between mb-8">
          <div>
            <h1 class="text-2xl font-bold text-gray-900">科研数据提取平台</h1>
            <p class="text-gray-500 mt-1">从左侧选择项目，或新建项目开始工作</p>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-sm text-gray-600">{{ auth.user?.username }}</span>
          </div>
        </div>

        <!-- 空状态提示 -->
        <div class="bg-white rounded-xl border border-gray-200 p-16 text-center">
          <div class="text-6xl mb-4">🔬</div>
          <h3 class="text-lg font-medium text-gray-700 mb-2">欢迎使用科研数据提取平台</h3>
          <p class="text-gray-500 text-sm mb-6">每个项目包含文献解析、自动去重、纳排标准制定、AI初筛等完整工作流程</p>
          <div class="grid grid-cols-3 gap-4 max-w-lg mx-auto text-left">
            <div class="bg-blue-50 rounded-lg p-3">
              <div class="text-lg mb-1">📄</div>
              <p class="text-xs font-medium text-blue-700">文献解析</p>
              <p class="text-xs text-blue-500 mt-0.5">支持 RIS / BibTeX / NBIB 等格式</p>
            </div>
            <div class="bg-purple-50 rounded-lg p-3">
              <div class="text-lg mb-1">🤖</div>
              <p class="text-xs font-medium text-purple-700">AI 初筛</p>
              <p class="text-xs text-purple-500 mt-0.5">基于纳排标准自动筛选文献</p>
            </div>
            <div class="bg-green-50 rounded-lg p-3">
              <div class="text-lg mb-1">📊</div>
              <p class="text-xs font-medium text-green-700">结果导出</p>
              <p class="text-xs text-green-500 mt-0.5">Excel / RIS 多格式导出</p>
            </div>
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

onMounted(async () => {
  await project.fetchProjects()
})
</script>
