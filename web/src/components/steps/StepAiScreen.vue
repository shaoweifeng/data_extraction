<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">
        <i class="fas fa-robot"></i>
      </div>
      <div>
        <h3 class="step-title">AI 智能初筛</h3>
        <p class="step-subtitle">基于纳排标准，大模型自动判断文献是否纳入</p>
      </div>
    </div>

    <!-- 模型选择 -->
    <div class="mb-6">
      <div v-if="s.aiModelsLoading" class="text-center py-4 text-gray-400 text-sm">
        <i class="fas fa-spinner fa-spin mr-1"></i>加载模型列表...
      </div>
      <div v-else class="grid grid-cols-3 gap-3">
        <div
          v-for="m in s.aiModelsList"
          :key="m.id"
          @click="!s.isProcessing && selectModel(m)"
          :class="[
            'relative border-2 rounded-xl p-4 cursor-pointer transition select-none',
            s.selectedAiModel === m.id
              ? 'border-indigo-500 bg-indigo-50'
              : m.configured
              ? 'border-gray-200 hover:border-indigo-300 bg-white'
              : 'border-dashed border-gray-200 bg-gray-50 opacity-60 cursor-not-allowed',
            s.isProcessing ? 'pointer-events-none' : '',
          ]"
        >
          <span
            v-if="s.selectedAiModel === m.id"
            class="absolute top-2 right-2 w-5 h-5 bg-indigo-500 rounded-full flex items-center justify-center"
          >
            <i class="fas fa-check text-white text-[10px]"></i>
          </span>
          <div class="flex items-center gap-2 mb-2">
            <span class="text-2xl">
              <span v-if="m.logo === 'deepseek'">🤖</span>
              <span v-else-if="m.logo === 'doubao'">🫘</span>
              <span v-else-if="m.logo === 'qwen'">🌙</span>
              <span v-else>🧠</span>
            </span>
            <div>
              <p class="text-sm font-bold text-gray-800">{{ m.name }}</p>
              <p class="text-[10px] text-gray-400 font-mono">{{ m.model }}</p>
            </div>
          </div>
          <p class="text-xs text-gray-500">{{ m.description }}</p>
          <div class="mt-2">
            <span v-if="m.configured" class="text-[10px] px-1.5 py-0.5 bg-green-100 text-green-600 rounded">已配置</span>
            <span v-else class="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-400 rounded">未配置 API Key</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Prompt 设置（折叠面板） -->
    <div class="step-collapse mb-6">
      <button
        @click="promptPanelOpen = !promptPanelOpen"
        class="step-collapse-header"
      >
        <span><i class="fas fa-sliders-h mr-2 text-gray-400"></i>Prompt 设置（可选）</span>
        <span class="flex items-center gap-2">
          <span v-if="s.useCustomPrompt" class="badge badge-purple">已自定义</span>
          <i :class="promptPanelOpen ? 'fa-chevron-up' : 'fa-chevron-down'" class="fas text-gray-400 text-xs"></i>
        </span>
      </button>
      <div v-show="promptPanelOpen" class="step-collapse-body space-y-3">
        <div class="flex gap-6 text-sm">
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" :value="false" v-model="s.useCustomPrompt" class="accent-indigo-600" />
            <span :class="!s.useCustomPrompt ? 'text-indigo-700 font-semibold' : 'text-gray-600'">使用默认 Prompt</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" :value="true" v-model="s.useCustomPrompt" class="accent-indigo-600" />
            <span :class="s.useCustomPrompt ? 'text-indigo-700 font-semibold' : 'text-gray-600'">自定义 Prompt</span>
          </label>
        </div>
        <div v-if="s.useCustomPrompt" class="space-y-2">
          <div class="flex items-center gap-2 text-xs text-amber-600 rounded-lg px-3 py-2" style="background:#fffbeb;border:1px solid #fde68a">
            <i class="fas fa-exclamation-triangle"></i>
            <span>
              必须包含 <code class="bg-amber-100 px-1 rounded font-mono">{screening_criteria}</code> 占位符，纳排标准会被自动注入到此处
            </span>
          </div>
          <textarea
            v-model="s.customPromptText"
            rows="10"
            placeholder="在此输入自定义 Prompt，必须包含 {screening_criteria} 占位符..."
            class="w-full text-xs font-mono input-base resize-y"
            style="font-family:'JetBrains Mono',monospace;min-height:120px"
            :class="
              s.customPromptText && !s.customPromptText.includes('{screening_criteria}')
                ? 'border-red-400 bg-red-50'
                : ''
            "
          ></textarea>
          <div
            v-if="s.customPromptText && !s.customPromptText.includes('{screening_criteria}')"
            class="text-xs text-red-500 flex items-center gap-1"
          >
            <i class="fas fa-times-circle"></i> 缺少 {screening_criteria} 占位符，无法保存
          </div>
        </div>
        <div v-else class="step-prompt-preview">
          {{ defaultPromptPreview }}
        </div>
        <div class="flex gap-2 pt-1">
          <button
            @click="savePrompt"
            :disabled="s.useCustomPrompt && (!s.customPromptText || !s.customPromptText.includes('{screening_criteria}'))"
            class="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            <i class="fas fa-save mr-1"></i>保存
          </button>
          <button
            v-if="s.useCustomPrompt"
            @click="resetPrompt"
            class="px-4 py-1.5 text-sm btn-secondary"
          >
            <i class="fas fa-undo mr-1"></i>重置为默认
          </button>
          <span v-if="promptSaveStatus" class="text-xs self-center" :class="promptSaveStatus === 'ok' ? 'text-green-600' : 'text-red-500'">
            {{ promptSaveStatus === 'ok' ? '✓ 已保存' : '✗ 保存失败' }}
          </span>
        </div>
      </div>
    </div>

    <!-- 文献列表 + 日志 -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
      <!-- 左侧：待/已筛选列表 -->
      <div class="step-ref-panel">
        <div class="step-ref-panel-tabs">
          <button
            @click="screeningTab = 'pending'; loadPending(0)"
            :class="screeningTab === 'pending' ? 'active-pending' : ''"
            class="step-ref-panel-tab"
          >
            待筛选 ({{ Math.max(0, s.pendingTotal - s.screenedTotal) }})
          </button>
          <button
            @click="screeningTab = 'screened'; loadScreened(0)"
            :class="screeningTab === 'screened' ? 'active-screened' : ''"
            class="step-ref-panel-tab"
          >
            已筛选 ({{ s.screenedTotal || s.processedCount }})
          </button>
        </div>

        <!-- 待筛选 -->
        <div v-show="screeningTab === 'pending'" class="flex-1 flex flex-col min-h-0">
          <div class="step-ref-list">
            <div v-if="s.pendingFiles.length === 0" class="h-full flex items-center justify-center text-gray-400 text-xs py-4">暂无待筛选文献</div>
            <div v-else>
              <div
                v-for="file in s.pendingFiles"
                :key="file.id"
                class="step-ref-row"
              >
                <div class="flex items-center overflow-hidden">
                  <i class="fas fa-file-code text-blue-400 mr-2 flex-shrink-0"></i>
                  <span class="truncate" :title="file.filename">{{ file.filename }}</span>
                </div>
                <span class="badge badge-gray ml-2">待筛选</span>
              </div>
            </div>
          </div>
          <div v-if="(s.pendingTotal - s.screenedTotal) > PAGE_SIZE" class="flex items-center justify-center gap-2 mt-2 flex-shrink-0">
            <button @click="loadPending(Math.max(0, s.pendingPage - 1))" :disabled="s.pendingPage === 0" class="step-page-btn">上一页</button>
            <span class="text-xs text-gray-400">{{ s.pendingPage + 1 }}/{{ Math.ceil(Math.max(1, s.pendingTotal - s.screenedTotal) / PAGE_SIZE) }}</span>
            <button @click="loadPending(s.pendingPage + 1)" :disabled="s.pendingPage >= Math.ceil(Math.max(1, s.pendingTotal - s.screenedTotal) / PAGE_SIZE) - 1" class="step-page-btn">下一页</button>
          </div>
        </div>

        <!-- 已筛选 -->
        <div v-show="screeningTab === 'screened'" class="flex-1 flex flex-col min-h-0">
          <div class="step-ref-list">
            <div v-if="s.screenedFiles.length === 0" class="h-full flex items-center justify-center text-gray-400 text-xs py-4">暂无已筛选文献</div>
            <div v-else>
              <div
                v-for="file in s.screenedFiles"
                :key="file.id"
                class="step-ref-row"
              >
                <div class="flex items-center overflow-hidden">
                  <i
                    class="fas fa-file-code mr-2 flex-shrink-0"
                    :class="file.metadata?.decision === 'included' ? 'text-green-500' : 'text-red-400'"
                  ></i>
                  <span class="truncate" :title="file.filename">{{ file.filename }}</span>
                </div>
                <span
                  class="badge ml-2"
                  :class="file.metadata?.decision === 'included' ? 'badge-green' : 'badge-red'"
                >
                  {{ file.metadata?.decision === 'included' ? '已纳入' : '已排除' }}
                </span>
              </div>
            </div>
          </div>
          <div v-if="s.screenedTotal > PAGE_SIZE" class="flex items-center justify-center gap-2 mt-2 flex-shrink-0">
            <button @click="loadScreened(Math.max(0, s.screenedPage - 1))" :disabled="s.screenedPage === 0" class="step-page-btn">上一页</button>
            <span class="text-xs text-gray-400">{{ s.screenedPage + 1 }}/{{ Math.ceil(s.screenedTotal / PAGE_SIZE) }}</span>
            <button @click="loadScreened(s.screenedPage + 1)" :disabled="s.screenedPage >= Math.ceil(s.screenedTotal / PAGE_SIZE) - 1" class="step-page-btn">下一页</button>
          </div>
        </div>
      </div>

      <!-- 右侧：日志控制台 -->
      <div class="log-console h-96 flex flex-col" style="border:1px solid #1e293b">
        <div class="flex-1 overflow-y-auto">
          <div v-if="s.latestAiScreenTask?.status === 'stopped' && !s.aiScreenLogContent" class="text-yellow-700 whitespace-pre-wrap">
            任务已暂停。
已处理: {{ s.screeningProgress.processed }} / {{ s.screeningProgress.total }} 篇 ({{ s.screeningProgress.percent }}%)
点击「继续筛选」从断点处继续，已筛选结果已保留。
          </div>
          <div v-else-if="!s.latestAiScreenTask && !s.aiScreenLogContent" class="text-gray-400">等待任务启动...</div>
          <div v-else class="whitespace-pre-wrap">{{ s.aiScreenLogContent || '正在初始化...' }}</div>
        </div>
      </div>
    </div>

    <!-- 进度条 -->
    <div
      v-if="s.isProcessing || (s.latestAiScreenTask && ['completed', 'stopped'].includes(s.latestAiScreenTask.status))"
      class="mb-4 w-full max-w-2xl mx-auto"
    >
      <div class="flex justify-between text-sm mb-1 text-gray-600">
        <span>筛选进度</span>
        <span class="font-bold">
          {{ s.screeningProgress.processed }} / {{ s.screeningProgress.total }} ({{ s.screeningProgress.percent }}%)
        </span>
      </div>
      <div class="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
        <div
          class="bg-indigo-600 h-4 rounded-full transition-all duration-500 ease-out"
          :style="{ width: s.screeningProgress.percent + '%' }"
        ></div>
      </div>
      <div v-if="s.latestAiScreenTask?.status === 'completed'" class="mt-2 text-green-600 font-bold animate-bounce">
        <i class="fas fa-check-circle"></i> 筛选完成！结果已生成
      </div>
    </div>

    <!-- 按钮区域 -->
    <div class="text-center space-y-4">
      <template v-if="!s.latestAiScreenTask || ['completed', 'failed'].includes(s.latestAiScreenTask.status)">
        <button
          @click="startScreening"
          :disabled="s.isProcessing"
          :class="s.latestAiScreenTask?.status === 'completed' ? 'bg-amber-600 hover:bg-amber-700' : 'bg-indigo-600 hover:bg-indigo-700'"
          class="text-white px-8 py-4 rounded-xl font-bold text-lg shadow-lg disabled:opacity-50 transition"
        >
          <i v-if="s.isProcessing" class="fas fa-spinner fa-spin mr-2"></i>
          {{ s.isProcessing ? 'AI 正在筛选中...' : s.latestAiScreenTask?.status === 'completed' ? '重新筛选' : '启动 AI 筛选任务' }}
        </button>
      </template>
      <template v-else-if="s.latestAiScreenTask.status === 'pending'">
        <button disabled class="bg-gray-400 text-white px-8 py-3 rounded-xl font-bold text-base shadow cursor-wait">
          <i class="fas fa-hourglass-half fa-spin mr-2"></i>等待队列中，即将启动...
        </button>
      </template>
      <template v-else-if="s.latestAiScreenTask.status === 'running'">
        <button @click="stopTask" class="bg-red-600 text-white px-8 py-3 rounded-xl font-bold text-base shadow hover:bg-red-700 transition">
          <i class="fas fa-stop mr-2"></i>暂停筛选
        </button>
      </template>
      <template v-else-if="s.latestAiScreenTask.status === 'stopping'">
        <button disabled class="bg-yellow-500 text-white px-8 py-3 rounded-xl font-bold text-base shadow cursor-wait">
          <i class="fas fa-spinner fa-spin mr-2"></i>正在停止...
        </button>
      </template>
      <template v-else-if="s.latestAiScreenTask.status === 'stopped'">
        <button @click="resumeTask" class="bg-green-600 text-white px-8 py-3 rounded-xl font-bold text-base shadow hover:bg-green-700 transition mr-4">
          <i class="fas fa-play mr-2"></i>继续筛选
        </button>
        <button @click="abandonTask" class="bg-gray-400 text-white px-8 py-3 rounded-xl font-bold text-base shadow hover:bg-gray-500 transition">
          <i class="fas fa-trash mr-2"></i>放弃任务
        </button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useScreeningStore } from '@/stores/screening'
import { useProjectStore } from '@/stores/project'
import { useTaskStore } from '@/stores/task'
import http, { httpNoTimeout } from '@/api/http'
import { extractListData } from '@/utils/format'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const screeningTab = ref('pending')
const promptPanelOpen = ref(false)
const promptSaveStatus = ref('')
const defaultPromptPreview = ref('（加载中...）')

const PAGE_SIZE = 50

// ── 初始化 ──────────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([loadAiModels(), loadPrompt()])
  await Promise.all([loadPending(), loadScreened()])
  loadAiScreenStats()
  syncLatestAiTask()
})

// ── 模型选择 ──────────────────────────────────────────────────
async function loadAiModels() {
  s.aiModelsLoading = true
  try {
    const res = await http.get('/ai-models/')
    s.aiModelsList = res.data
    const def = s.aiModelsList.find((m) => m.is_default && m.configured) || s.aiModelsList.find((m) => m.configured)
    if (def) s.selectedAiModel = def.id
    // 从日志恢复上次选择
    if (project.currentProject) {
      const logRes = await http.get(`/activity-logs/?project=${project.currentProject.id}&operation_type=model_select&limit=1`)
      const logs = extractListData(logRes.data)
      if (logs.length > 0) {
        const lastModel = logs[0].operation_detail?.model_id
        if (lastModel && s.aiModelsList.find((m) => m.id === lastModel)) {
          s.selectedAiModel = lastModel
        }
      }
    }
  } catch (e) {
    console.error('加载模型列表失败', e)
  } finally {
    s.aiModelsLoading = false
  }
}

async function selectModel(m) {
  if (s.isProcessing) return
  s.selectedAiModel = m.id
  if (!project.currentProject) return
  try {
    await http.post(`/projects/${project.currentProject.id}/log_model_select/`, {
      model_id: m.id,
      model_name: m.name,
    })
    await taskStore.fetchActivityLogs(project.currentProject.id)
  } catch {}
}

// ── Prompt ──────────────────────────────────────────────────
async function loadPrompt() {
  if (!project.currentProject) return
  try {
    const res = await http.get(`/projects/${project.currentProject.id}/get_prompt/`)
    s.useCustomPrompt = res.data.use_custom_prompt || false
    s.customPromptText = res.data.custom_prompt || ''
    if (res.data.default_prompt) defaultPromptPreview.value = res.data.default_prompt
  } catch {}
}

async function savePrompt() {
  if (!project.currentProject) return
  if (s.useCustomPrompt && !s.customPromptText.includes('{screening_criteria}')) return
  promptSaveStatus.value = ''
  try {
    await http.post(`/projects/${project.currentProject.id}/save_prompt/`, {
      custom_prompt: s.customPromptText,
      use_custom_prompt: s.useCustomPrompt,
    })
    promptSaveStatus.value = 'ok'
    await taskStore.fetchActivityLogs(project.currentProject.id)
  } catch {
    promptSaveStatus.value = 'error'
  }
  setTimeout(() => { promptSaveStatus.value = '' }, 3000)
}

async function resetPrompt() {
  if (!project.currentProject) return
  try {
    await http.post(`/projects/${project.currentProject.id}/reset_prompt/`)
    s.useCustomPrompt = false
    s.customPromptText = ''
    promptSaveStatus.value = 'ok'
    await taskStore.fetchActivityLogs(project.currentProject.id)
    setTimeout(() => { promptSaveStatus.value = '' }, 2000)
  } catch {
    promptSaveStatus.value = 'error'
  }
}

// ── 文件列表 ──────────────────────────────────────────────────
async function loadPending(page) {
  if (!project.currentProject) return
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const pageNum = page ?? s.pendingPage
  const offset = pageNum * PAGE_SIZE

  for (const key of ['dedup', 'parse']) {
    const step = stage.steps.find((st) => st.step_key === key)
    if (!step) continue
    try {
      const res = await http.get(`/files/?project=${project.currentProject.id}&step=${step.id}&data_category=intermediate&limit=${PAGE_SIZE}&offset=${offset}`)
      const data = res.data
      const files = extractListData(data)
      if (data.total > 0 || files.length > 0) {
        s.pendingFiles = files
        s.pendingTotal = data.total ?? files.length
        if (page !== undefined) s.pendingPage = page
        return
      }
    } catch {}
  }
  s.pendingFiles = []
  s.pendingTotal = 0
}

async function loadScreened(page) {
  if (!project.currentProject) return
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'ai_screen')
  if (!step) return
  const pageNum = page ?? s.screenedPage
  const offset = pageNum * PAGE_SIZE
  try {
    const res = await http.get(`/files/?project=${project.currentProject.id}&step=${step.id}&data_category=output&limit=${PAGE_SIZE}&offset=${offset}`)
    const data = res.data
    s.screenedFiles = extractListData(data)
    s.screenedTotal = data.total ?? s.screenedFiles.length
    if (page !== undefined) s.screenedPage = page
  } catch {}
}

async function loadAiScreenStats() {
  if (!project.currentProject) return
  try {
    const res = await http.get(`/projects/${project.currentProject.id}/ai_screen_stats/`)
    s.aiScreenStats = res.data
  } catch {}
}

// 同步最新 ai_screen 任务
function syncLatestAiTask() {
  const aiTask = taskStore.recentTasks.find((t) => t.task_type === 'ai_screen')
  if (aiTask) s.latestAiScreenTask = aiTask
}

// ── 筛选任务 ──────────────────────────────────────────────────
async function startScreening() {
  if (s.criteriaList.length === 0) {
    alert('请先设置纳排标准')
    return
  }
  s.isProcessing = true
  s.aiScreenLogContent = '正在启动任务...'

  try {
    await clearAiScreenResults()
    s.screenedFiles = []

    const res = await httpNoTimeout.post('/tasks/', {
      project: project.currentProject.id,
      task_type: 'ai_screening',
      config: { criteria: s.criteriaList, ai_model: s.selectedAiModel },
    })
    s.latestAiScreenTask = res.data
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    pollAiScreening(res.data.id)
  } catch (err) {
    alert(`启动失败: ${err.response?.data?.error || err.message}`)
    s.isProcessing = false
  }
}

async function stopTask() {
  if (!s.latestAiScreenTask) return
  if (!confirm('确定暂停当前筛选任务？')) return
  try {
    await httpNoTimeout.post(`/tasks/${s.latestAiScreenTask.id}/stop/`)
    alert('任务已暂停')
    s.isProcessing = false
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    await project.fetchStages(project.currentProject.id)
    await loadScreened()
  } catch (err) {
    alert(`暂停失败: ${err.response?.data?.error || err.message}`)
  }
}

async function resumeTask() {
  if (!s.latestAiScreenTask) return
  try {
    const res = await httpNoTimeout.post(`/tasks/${s.latestAiScreenTask.id}/resume/`)
    const newTask = res.data.task || res.data
    s.latestAiScreenTask = newTask
    s.screeningProgressValue = newTask.progress_percentage || 0
    s.totalRefs = newTask.metadata?.total_refs || s.totalRefs || s.pendingTotal
    s.isProcessing = true
    s.aiScreenLogContent = '正在恢复任务，即将继续从上次断点处理...'
    pollAiScreening(newTask.id)
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
  } catch (err) {
    alert(`继续失败: ${err.response?.data?.error || err.message}`)
  }
}

async function abandonTask() {
  if (!s.latestAiScreenTask) return
  if (!confirm('确定放弃此任务？已筛选结果将被清除。')) return
  try {
    await clearAiScreenResults()
    await http.delete(`/tasks/${s.latestAiScreenTask.id}/`)
    s.latestAiScreenTask = null
    s.screenedFiles = []
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    alert('任务已放弃，筛选结果已清除')
  } catch (err) {
    alert(`放弃失败: ${err.response?.data?.error || err.message}`)
  }
}

async function clearAiScreenResults() {
  if (!project.currentProject) return
  try {
    await httpNoTimeout.post(`/projects/${project.currentProject.id}/clear_ai_screen_results/`)
  } catch {}
}

async function pollAiScreening(taskId) {
  let pollCount = 0
  const poll = async () => {
    pollCount++
    try {
      const res = await http.get(`/tasks/${taskId}/`)
      const task = res.data
      s.latestAiScreenTask = task
      const status = task.status
      s.screeningProgressValue = task.progress_percentage || 0
      if (task.metadata) {
        s.totalRefs = task.metadata.total_refs || s.totalRefs
        s.processedCount = task.metadata.processed_refs || 0
      }
      // 拉日志
      try {
        const logRes = await http.get(`/tasks/${taskId}/logs/`)
        let logContent = logRes.data.log_content || logRes.data.lines?.join('\n') || ''
        if (!logContent) {
          if (status === 'pending') logContent = '正在启动任务，请稍候...'
          else if (status === 'running') logContent = '任务正在运行中，正在等待日志输出...'
        }
        s.aiScreenLogContent = logContent
      } catch {}

      if (['running', 'pending', 'stopping'].includes(status)) {
        if (pollCount % 5 === 0) {
          loadPending()
          loadScreened()
        }
        setTimeout(poll, 2000)
      } else {
        s.isProcessing = false
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        await project.fetchStages(project.currentProject.id)
        if (status === 'completed') {
          await Promise.all([loadPending(), loadScreened(), loadAiScreenStats()])
          alert('AI初筛完成！')
        } else if (status === 'stopped') {
          await Promise.all([loadScreened(), loadAiScreenStats()])
        } else {
          alert(`AI初筛失败: ${task.error_message || '任务执行失败'}`)
        }
      }
    } catch (err) {
      console.error('轮询AI初筛状态失败', err)
      s.isProcessing = false
    }
  }
  await poll()
}
</script>
