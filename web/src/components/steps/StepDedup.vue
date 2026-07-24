<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#8b5cf6,#a78bfa)">
        <i class="fas fa-clone"></i>
      </div>
      <div>
        <h3 class="step-title">文献自动去重</h3>
        <p class="step-subtitle">检测并合并重复文献，保留最优记录</p>
      </div>
    </div>

    <!-- 文件数量与状态 -->
    <div class="step-list-box mb-6 max-w-2xl mx-auto" style="padding:20px 24px">
      <div class="flex justify-between items-center text-sm text-gray-600 mb-3">
        <span class="text-gray-500"><i class="fas fa-file-alt mr-1.5 text-purple-400"></i>当前 Reference 文件:</span>
        <span class="font-bold text-base text-gray-800">{{ s.referenceFiles.length }} 个</span>
      </div>
      <div class="flex justify-between items-center text-sm text-gray-600">
        <span class="text-gray-500"><i class="fas fa-check-circle mr-1.5 text-purple-400"></i>去重状态:</span>
        <span :class="s.dedupCompleted ? 'badge badge-green' : 'badge badge-gray'">{{ s.dedupCompleted ? '已完成' : '待处理' }}</span>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="text-center">
      <button
        @click="handleDeduplication"
        :disabled="s.isDeduplicating"
        :class="s.dedupCompleted ? 'bg-amber-600 hover:bg-amber-700' : 'bg-purple-600 hover:bg-purple-700'"
        class="text-white px-8 py-3 rounded-lg font-medium shadow-lg disabled:opacity-50 transition"
      >
        <i v-if="s.isDeduplicating" class="fas fa-spinner fa-spin mr-2"></i>
        <i v-else :class="s.dedupCompleted ? 'fas fa-redo' : 'fas fa-magic'" class="mr-2"></i>
        {{ s.isDeduplicating ? '正在去重…' : s.dedupCompleted ? '重新去重' : '开始去重' }}
      </button>
    </div>

    <!-- 去重统计信息 -->
    <div
      v-if="s.dedupStats"
      class="mt-8 rounded-xl p-6" style="background:linear-gradient(135deg,#faf5ff,#eef2ff);border:1px solid #ddd6fe"
    >
      <h4 class="text-lg font-bold text-purple-800 mb-4 flex items-center">
        <i class="fas fa-chart-pie mr-2"></i>
        去重统计报告
      </h4>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div class="step-stat-card">
          <div class="text-3xl font-bold text-gray-800">{{ s.dedupStats.total_files }}</div>
          <div class="text-sm text-gray-500 mt-1">原始文献</div>
        </div>
        <div class="step-stat-card">
          <div class="text-3xl font-bold text-green-600">{{ s.dedupStats.kept_files }}</div>
          <div class="text-sm text-gray-500 mt-1">保留文献</div>
        </div>
        <div class="step-stat-card">
          <div class="text-3xl font-bold text-red-500">{{ s.dedupStats.duplicates }}</div>
          <div class="text-sm text-gray-500 mt-1">重复文献</div>
        </div>
        <div class="step-stat-card">
          <div class="text-3xl font-bold text-purple-600">{{ s.dedupStats.duplicate_rate }}</div>
          <div class="text-sm text-gray-500 mt-1">重复率</div>
        </div>
      </div>
      <div v-if="s.dedupStats.completion_time" class="text-xs text-gray-400 mt-2">
        <i class="fas fa-clock mr-1"></i>
        完成时间: {{ new Date(s.dedupStats.completion_time).toLocaleString() }}
      </div>

      <!-- 重复文献详细列表 -->
      <div
        v-if="s.dedupStats.duplicate_details?.length > 0"
        class="mt-6"
      >
        <div class="flex items-center justify-between mb-3">
          <h5 class="font-bold text-purple-700">
            <i class="fas fa-list-alt mr-2"></i>
            重复文献列表 (共{{ s.dedupStats.duplicate_groups || 0 }}组)
          </h5>
          <button
            @click="s.showDuplicateDetails = !s.showDuplicateDetails"
            class="text-sm text-purple-600 hover:text-purple-800 underline"
          >
            {{ s.showDuplicateDetails ? '收起详情' : '展开详情' }}
          </button>
        </div>

        <div v-show="s.showDuplicateDetails" class="step-list-box" style="max-height:24rem;padding:8px">
          <div
            v-for="(dup, idx) in s.dedupStats.duplicate_details"
            :key="idx"
            class="p-3 rounded-lg hover:bg-white mb-1 transition"
            style="border-bottom:1px solid #f8fafc"
          >
            <div class="font-medium text-gray-800 mb-2">{{ idx + 1 }}. {{ dup.title || '(无标题)' }}</div>

            <!-- 保留的文章 -->
            <div class="text-sm text-gray-600 mb-2">
              <div class="flex items-start">
                <span class="text-green-600 font-medium mr-2 whitespace-nowrap">✓ 保留:</span>
                <span class="flex-1">
                  <span class="font-medium">{{ dup.kept.source_file || dup.kept.filename }}</span>
                  <span v-if="dup.kept.source_position" class="text-blue-600 ml-1">#{{ dup.kept.source_position }}</span>
                  <span v-if="dup.kept.year" class="text-gray-400 ml-2">({{ dup.kept.year }})</span>
                </span>
              </div>
              <div v-if="dup.kept.journal" class="ml-8 text-gray-500">期刊: {{ dup.kept.journal }}</div>
              <div v-if="dup.kept.doi" class="ml-8">
                DOI:
                <a :href="'https://doi.org/' + dup.kept.doi" target="_blank" class="text-blue-600 hover:underline">
                  {{ dup.kept.doi }}
                </a>
              </div>
            </div>

            <!-- 重复的文章 -->
            <div
              v-for="(dup_item, di) in dup.duplicates"
              :key="di"
              class="text-sm text-gray-600 mt-2 pl-4" style="border-left:2px solid #fca5a5"
            >
              <div class="flex items-start">
                <span class="text-red-500 font-medium mr-2 whitespace-nowrap">✗ 重复:</span>
                <span class="flex-1">
                  <span class="font-medium">{{ dup_item.source_file || dup_item.filename }}</span>
                  <span v-if="dup_item.source_position" class="text-blue-600 ml-1">#{{ dup_item.source_position }}</span>
                  <span v-if="dup_item.year" class="text-gray-400 ml-2">({{ dup_item.year }})</span>
                </span>
              </div>
              <div v-if="dup_item.journal" class="ml-8 text-gray-500">期刊: {{ dup_item.journal }}</div>
              <div v-if="dup_item.doi" class="ml-8">
                DOI:
                <a :href="'https://doi.org/' + dup_item.doi" target="_blank" class="text-blue-600 hover:underline">
                  {{ dup_item.doi }}
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useScreeningStore } from '@/stores/screening'
import { useProjectStore } from '@/stores/project'
import { useTaskStore } from '@/stores/task'
import http, { httpNoTimeout } from '@/api/http'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

async function handleDeduplication() {
  if (s.referenceFiles.length === 0) {
    alert('请先上传文献文件')
    return
  }
  s.isDeduplicating = true
  try {
    const res = await httpNoTimeout.post('/tasks/', {
      project: project.currentProject.id,
      task_type: 'deduplication',
      config: { ai_model: s.selectedAiModel },
    })
    const task = res.data
    pollDedupStatus(task.id)
  } catch (err) {
    alert(`去重启动失败: ${err.response?.data?.error || err.message}`)
    s.isDeduplicating = false
  }
}

async function pollDedupStatus(taskId) {
  const poll = async () => {
    try {
      const res = await http.get(`/tasks/${taskId}/`)
      const task = res.data
      const status = task.status

      if (status === 'running' || status === 'pending') {
        setTimeout(poll, 2000)
      } else if (status === 'completed') {
        s.dedupCompleted = true
        s.isDeduplicating = false
        await project.fetchStages(project.currentProject.id)
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        loadDedupStats()
        alert('去重完成！')
      } else {
        s.isDeduplicating = false
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        alert(`去重失败: ${task.error_message || '任务执行失败'}`)
      }
    } catch (err) {
      console.error('轮询任务状态失败', err)
      s.isDeduplicating = false
    }
  }
  await poll()
}

function loadDedupStats() {
  const screen1Stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!screen1Stage) return
  const dedupStep = screen1Stage.steps.find((st) => st.step_key === 'dedup')
  if (!dedupStep) return

  if (dedupStep.metadata && dedupStep.metadata.total_files !== undefined) {
    s.dedupStats = dedupStep.metadata
  } else {
    s.dedupStats = null
  }
  if (dedupStep.status === 'completed') {
    s.dedupCompleted = true
  }
}

onMounted(loadDedupStats)
</script>
