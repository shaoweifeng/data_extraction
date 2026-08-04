<template>
  <div class="ai-screen-layout">
    <!-- ── 顶部：标题 + 模型选择 ── -->
    <div class="ai-screen-top">
      <!-- 步骤标题（紧凑） -->
      <div class="ai-top-title">
        <div class="step-head-icon" style="background:linear-gradient(135deg,#6366f1,#8b5cf6);width:32px;height:32px;border-radius:9px">
          <i class="fas fa-robot" style="font-size:0.85rem"></i>
        </div>
        <div>
          <h3 class="step-title" style="font-size:1rem;margin:0">AI 智能初筛</h3>
          <p class="step-subtitle" style="font-size:0.72rem;margin:0">基于纳排标准，大模型自动判断文献是否纳入</p>
        </div>
      </div>

      <!-- 模型选择（横向芯片） -->
      <div class="ai-model-chips">
        <span class="text-xs text-gray-500 font-medium mr-2 whitespace-nowrap">选择模型：</span>
        <div v-if="s.aiModelsLoading" class="text-xs text-gray-400"><i class="fas fa-spinner fa-spin mr-1"></i>加载中...</div>
        <div v-else class="flex flex-wrap gap-1.5">
          <button
            v-for="m in s.aiModelsList"
            :key="m.id"
            @click="!s.isProcessing && m.configured && selectModel(m)"
            :class="[
              'model-chip',
              s.selectedAiModel === m.id ? 'model-chip-active' : '',
              !m.configured ? 'model-chip-disabled' : '',
            ]"
          >
            <span>
              <span v-if="m.logo === 'deepseek'">🤖</span>
              <span v-else-if="m.logo === 'doubao'">🫘</span>
              <span v-else-if="m.logo === 'qwen'">🌙</span>
              <span v-else>🧠</span>
            </span>
            {{ m.name }}
            <i v-if="s.selectedAiModel === m.id" class="fas fa-check ml-1 text-indigo-500" style="font-size:0.65rem"></i>
            <span v-if="!m.configured" class="text-[10px] text-gray-400 ml-1">（未配置）</span>
          </button>
        </div>
      </div>

      <!-- Prompt 设置（折叠，内嵌右侧） -->
      <div class="ai-prompt-toggle">
        <button @click="promptPanelOpen = !promptPanelOpen" class="prompt-toggle-btn">
          <i class="fas fa-sliders-h mr-1"></i>Prompt
          <span v-if="s.useCustomPrompt" class="badge badge-purple ml-1" style="font-size:0.65rem;padding:1px 6px">自定义</span>
          <i :class="promptPanelOpen ? 'fa-chevron-up' : 'fa-chevron-down'" class="fas ml-1 text-xs text-gray-400"></i>
        </button>
      </div>
    </div>

    <!-- Prompt 展开区（可折叠，绝对定位覆盖） -->
    <div v-show="promptPanelOpen" class="ai-prompt-panel step-collapse-body space-y-2">
      <div class="flex gap-4 text-sm">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" :value="false" v-model="s.useCustomPrompt" class="accent-indigo-600" />
          <span :class="!s.useCustomPrompt ? 'text-indigo-700 font-semibold' : 'text-gray-600'">默认 Prompt</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="radio" :value="true" v-model="s.useCustomPrompt" class="accent-indigo-600" />
          <span :class="s.useCustomPrompt ? 'text-indigo-700 font-semibold' : 'text-gray-600'">自定义 Prompt</span>
        </label>
        <button @click="savePrompt" :disabled="s.useCustomPrompt && (!s.customPromptText || !s.customPromptText.includes('{screening_criteria}'))" class="ml-auto px-3 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-40 transition">
          <i class="fas fa-save mr-1"></i>保存
        </button>
        <button v-if="s.useCustomPrompt" @click="resetPrompt" class="px-3 py-1 text-xs btn-secondary">
          <i class="fas fa-undo mr-1"></i>重置
        </button>
        <span v-if="promptSaveStatus" class="text-xs self-center" :class="promptSaveStatus === 'ok' ? 'text-green-600' : 'text-red-500'">
          {{ promptSaveStatus === 'ok' ? '✓ 已保存' : '✗ 失败' }}
        </span>
      </div>
      <div v-if="s.useCustomPrompt" class="space-y-1">
        <div class="flex items-center gap-1 text-xs text-amber-600" style="background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:4px 8px">
          <i class="fas fa-exclamation-triangle"></i>
          必须含 <code class="bg-amber-100 px-1 rounded font-mono">{screening_criteria}</code> 占位符
        </div>
        <textarea v-model="s.customPromptText" rows="6" placeholder="自定义 Prompt，含 {screening_criteria}..." class="w-full text-xs font-mono input-base resize-y" style="font-family:monospace;min-height:80px" :class="s.customPromptText && !s.customPromptText.includes('{screening_criteria}') ? 'border-red-400 bg-red-50' : ''"></textarea>
      </div>
      <div v-else class="step-prompt-preview" style="max-height:80px;overflow-y:auto">{{ defaultPromptPreview }}</div>
    </div>

    <!-- ── 主体：文献列表（左） + 日志+进度+操作（右） ── -->
    <div class="ai-screen-body">
      <!-- 左：文献 Tab 列表 -->
      <div class="step-ref-panel ai-ref-panel">
        <div class="step-ref-panel-tabs">
          <button @click="screeningTab = 'pending'; loadPending(0)" :class="screeningTab === 'pending' ? 'active-pending' : ''" class="step-ref-panel-tab">
            待筛选 ({{ s.pendingTotal }})
          </button>
          <button @click="screeningTab = 'screened'; loadScreened(0)" :class="screeningTab === 'screened' ? 'active-screened' : ''" class="step-ref-panel-tab">
            已筛选 ({{ s.screenedTotal || s.processedCount }})
          </button>
        </div>
        <div v-show="screeningTab === 'pending'" class="flex-1 flex flex-col min-h-0">
          <div class="step-ref-list">
            <div v-if="s.pendingFiles.length === 0" class="h-full flex items-center justify-center text-gray-400 text-xs py-4">暂无待筛选文献</div>
            <div v-else>
              <div v-for="file in s.pendingFiles" :key="file.id" class="step-ref-row">
                <div class="flex items-center overflow-hidden flex-1 min-w-0">
                  <i class="fas fa-file-code text-blue-400 mr-2 flex-shrink-0"></i>
                  <span class="truncate" :title="file.filename">{{ file.filename }}</span>
                </div>
                <span class="badge badge-gray ml-2">待筛</span>
              </div>
            </div>
          </div>
          <div v-if="s.pendingTotal > PAGE_SIZE" class="flex items-center justify-center gap-1 mt-1 flex-shrink-0">
            <button @click="loadPending(Math.max(0, s.pendingPage - 1))" :disabled="s.pendingPage === 0" class="step-page-btn">上一页</button>
            <span class="text-xs text-gray-400">{{ s.pendingPage + 1 }}/{{ Math.ceil(Math.max(1, s.pendingTotal) / PAGE_SIZE) }}</span>
            <button @click="loadPending(s.pendingPage + 1)" :disabled="s.pendingPage >= Math.ceil(Math.max(1, s.pendingTotal) / PAGE_SIZE) - 1" class="step-page-btn">下一页</button>
          </div>
        </div>
        <div v-show="screeningTab === 'screened'" class="flex-1 flex flex-col min-h-0">
          <div class="step-ref-list">
            <div v-if="s.screenedFiles.length === 0" class="h-full flex items-center justify-center text-gray-400 text-xs py-4">暂无已筛选文献</div>
            <div v-else>
              <div v-for="file in s.screenedFiles" :key="file.id" class="step-ref-row">
                <div class="flex items-center overflow-hidden flex-1 min-w-0">
                  <i class="fas fa-file-code mr-2 flex-shrink-0" :class="file.metadata?.decision === 'included' ? 'text-green-500' : 'text-red-400'"></i>
                  <span class="truncate" :title="file.filename">{{ file.filename }}</span>
                </div>
                <span class="badge ml-2" :class="file.metadata?.decision === 'included' ? 'badge-green' : 'badge-red'">
                  {{ file.metadata?.decision === 'included' ? '纳入' : '排除' }}
                </span>
              </div>
            </div>
          </div>
          <div v-if="s.screenedTotal > PAGE_SIZE" class="flex items-center justify-center gap-1 mt-1 flex-shrink-0">
            <button @click="loadScreened(Math.max(0, s.screenedPage - 1))" :disabled="s.screenedPage === 0" class="step-page-btn">上一页</button>
            <span class="text-xs text-gray-400">{{ s.screenedPage + 1 }}/{{ Math.ceil(s.screenedTotal / PAGE_SIZE) }}</span>
            <button @click="loadScreened(s.screenedPage + 1)" :disabled="s.screenedPage >= Math.ceil(s.screenedTotal / PAGE_SIZE) - 1" class="step-page-btn">下一页</button>
          </div>
        </div>
      </div>

      <!-- 右：日志 + 进度 + 操作按钮 -->
      <div class="ai-right-panel">
        <!-- 日志控制台 -->
        <div class="log-console ai-log-console" style="border:1px solid #1e293b">
          <div class="flex-1 overflow-y-auto">
            <div v-if="s.latestAiScreenTask?.status === 'stopped' && !s.aiScreenLogContent" class="text-yellow-700 whitespace-pre-wrap">任务已暂停。
已处理: {{ s.screeningProgress.processed }} / {{ s.screeningProgress.total }} 篇 ({{ s.screeningProgress.percent }}%)
点击「继续筛选」从断点处继续。</div>
            <div v-else-if="!s.latestAiScreenTask && !s.aiScreenLogContent" class="text-gray-400">等待任务启动...</div>
            <div v-else class="whitespace-pre-wrap">{{ s.aiScreenLogContent || '正在初始化...' }}</div>
          </div>
        </div>

        <!-- 进度条（有任务时显示） -->
        <div v-if="s.isProcessing || (s.latestAiScreenTask && ['completed','stopped'].includes(s.latestAiScreenTask.status))" class="ai-progress-bar">
          <div class="flex justify-between text-xs mb-1 text-gray-600">
            <span>筛选进度</span>
            <span class="font-bold">{{ s.screeningProgress.processed }}/{{ s.screeningProgress.total }} ({{ s.screeningProgress.percent }}%)</span>
          </div>
          <div class="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden">
            <div class="bg-indigo-500 h-2.5 rounded-full transition-all duration-500" :style="{ width: s.screeningProgress.percent + '%' }"></div>
          </div>
          <div v-if="s.latestAiScreenTask?.status === 'completed'" class="mt-1.5 text-xs text-green-600 font-semibold">
            <i class="fas fa-check-circle mr-1"></i>筛选完成！结果已生成
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="ai-action-area">
          <!-- 余额信息 -->
          <div class="billing-bar" :class="billing.sufficient === false ? 'billing-bar-danger' : 'billing-bar-ok'">
            <span class="billing-item">
              <i class="fas fa-coins mr-1"></i>余额：<b>{{ billing.balance ?? '...' }}</b> credits
            </span>
            <span class="billing-item" v-if="s.pendingTotal > 0">
              预估：<b>{{ billing.estimated ?? '...' }}</b> credits（{{ s.pendingTotal }} 篇）
            </span>
            <span v-if="billing.sufficient === false" class="billing-warn">
              <i class="fas fa-exclamation-triangle mr-0.5"></i>余额不足
            </span>
          </div>

          <template v-if="!s.latestAiScreenTask || ['completed','failed'].includes(s.latestAiScreenTask.status)">
            <button @click="startScreening" :disabled="s.isProcessing || billing.sufficient === false" :class="s.latestAiScreenTask?.status === 'completed' ? 'bg-amber-600 hover:bg-amber-700' : 'bg-indigo-600 hover:bg-indigo-700'" class="ai-action-btn text-white">
              <i v-if="s.isProcessing" class="fas fa-spinner fa-spin mr-2"></i>
              {{ s.isProcessing ? 'AI 正在筛选...' : s.latestAiScreenTask?.status === 'completed' ? '重新筛选' : '启动 AI 筛选' }}
            </button>
            <p v-if="billing.sufficient === false" class="text-xs text-red-500 text-center">余额不足，请联系管理员充值</p>
          </template>
          <template v-else-if="s.latestAiScreenTask.status === 'queuing'">
            <div class="queue-status-bar">
              <div class="flex items-center gap-2 text-amber-700">
                <i class="fas fa-clock fa-spin"></i>
                <span class="font-semibold">排队等待中</span>
                <span v-if="queueInfo.position > 0" class="text-sm">
                  — 第 <b>{{ queueInfo.position }}</b> 位
                </span>
              </div>
              <div class="text-xs text-gray-500 mt-1">
                <span>所需线程：{{ queueInfo.slotsNeeded }}</span>
                <span class="mx-2">·</span>
                <span>当前剩余槽：{{ queueInfo.slotsFree }} / {{ queueInfo.slotsTotal }}</span>
                <span v-if="queueInfo.queueLength > 1" class="mx-2">·</span>
                <span v-if="queueInfo.queueLength > 1">队列共 {{ queueInfo.queueLength }} 个任务</span>
              </div>
              <p class="text-xs text-amber-600 mt-1">系统将自动为您分配资源，无需手动操作</p>
            </div>
          </template>
          <template v-else-if="s.latestAiScreenTask.status === 'pending'">
            <button disabled class="ai-action-btn bg-gray-400 text-white cursor-wait">
              <i class="fas fa-hourglass-half fa-spin mr-2"></i>初始化中...
            </button>
          </template>
          <template v-else-if="s.latestAiScreenTask.status === 'running'">
            <button @click="stopTask" class="ai-action-btn bg-red-600 hover:bg-red-700 text-white">
              <i class="fas fa-stop mr-2"></i>暂停筛选
            </button>
          </template>
          <template v-else-if="s.latestAiScreenTask.status === 'stopping'">
            <button disabled class="ai-action-btn bg-yellow-500 text-white cursor-wait">
              <i class="fas fa-spinner fa-spin mr-2"></i>正在停止...
            </button>
          </template>
          <template v-else-if="s.latestAiScreenTask.status === 'stopped'">
            <button @click="resumeTask" class="ai-action-btn bg-green-600 hover:bg-green-700 text-white">
              <i class="fas fa-play mr-2"></i>继续筛选
            </button>
            <button @click="abandonTask" class="ai-action-btn bg-gray-400 hover:bg-gray-500 text-white mt-2">
              <i class="fas fa-trash mr-2"></i>放弃任务
            </button>
          </template>
        </div>
      </div>
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
const billing = ref({ balance: null, estimated: null, sufficient: null })
const queueInfo = ref({ position: 0, queueLength: 0, slotsNeeded: 0, slotsFree: 0, slotsTotal: 0 })

const PAGE_SIZE = 50

// ── 初始化 ──────────────────────────────────────────────────
onMounted(async () => {
  // 从 stagesData 恢复纳排标准（保证不论先进哪个 tab 都能拿到）
  if (s.criteriaList.length === 0) {
    const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
    const step  = stage?.steps?.find((st) => st.step_key === 'criteria')
    if (step?.metadata?.criteria?.length) {
      s.criteriaList = step.metadata.criteria
    }
  }
  await Promise.all([loadAiModels(), loadPrompt()])
  await Promise.all([loadPending(), loadScreened()])
  loadAiScreenStats()
  syncLatestAiTask()
  loadBilling()
})

// ── 计费 ─────────────────────────────────────────────────────
async function loadBilling() {
  try {
    const balRes = await http.get('/billing/balance/')
    const balData = balRes.data
    if (balData.is_unlimited) {
      billing.value = { balance: '∞', estimated: null, sufficient: true }
      return
    }
    billing.value.balance = balData.balance

    if (s.pendingTotal > 0) {
      const estRes = await http.get(`/billing/estimate/?ref_count=${s.pendingTotal}`)
      billing.value.estimated = estRes.data.estimated_credits
      billing.value.sufficient = estRes.data.sufficient
    } else {
      billing.value.estimated = null
      billing.value.sufficient = true
    }
  } catch (e) {
    console.error('加载余额失败', e)
  }
}

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
  const pid = project.currentProject.id

  // 先确定数据源 step：优先 dedup，其次 parse（与后端 _get_input_files 一致）。
  // 用不带 exclude_screened 的探测判断该 step 是否“本来就有”源文件，
  // 避免筛完后 dedup 返回空、错误 fallback 到 parse 显示全量。
  let sourceStep = null
  for (const key of ['dedup', 'parse']) {
    const step = stage.steps.find((st) => st.step_key === key)
    if (!step) continue
    try {
      const probe = await http.get(`/files/?project=${pid}&step=${step.id}&data_category=intermediate&limit=1&offset=0`)
      if ((probe.data.total ?? 0) > 0) {
        sourceStep = step
        break
      }
    } catch {}
  }

  if (!sourceStep) {
    s.pendingFiles = []
    s.pendingTotal = 0
    return
  }

  try {
    const res = await http.get(`/files/?project=${pid}&step=${sourceStep.id}&data_category=intermediate&exclude_screened=1&limit=${PAGE_SIZE}&offset=${offset}`)
    const data = res.data
    s.pendingFiles = extractListData(data)
    s.pendingTotal = data.total ?? s.pendingFiles.length
    if (page !== undefined) s.pendingPage = page
    // 待筛选数量明确后刷新预估
    if (page === undefined || page === 0) loadBilling()
  } catch {
    s.pendingFiles = []
    s.pendingTotal = 0
  }
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
  if (!aiTask) return
  s.latestAiScreenTask = aiTask
  // 从任务对象恢复筛选进度（刷新页面后进度条不归零）
  s.screeningProgressValue = aiTask.progress_percentage || 0
  const sp = aiTask.config?.screen_progress
  if (sp) {
    s.totalRefs = sp.total_refs || s.totalRefs
    s.processedCount = sp.processed_refs || 0
  }
  // 已实际筛选出的文件数是最可靠的已处理数，用它兜底
  if ((!s.processedCount || s.processedCount === 0) && s.screenedTotal > 0) {
    s.processedCount = s.screenedTotal
  }
  // 若任务处于运行中/等待中，恢复轮询
  if (['running', 'pending', 'stopping', 'queuing'].includes(aiTask.status)) {
    s.isProcessing = aiTask.status === 'running'
    pollAiScreening(aiTask.id)
  }
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
    s.totalRefs = newTask.config?.screen_progress?.total_refs || s.totalRefs || s.pendingTotal
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
      const sp = task.config?.screen_progress
      if (sp) {
        s.totalRefs = sp.total_refs || s.totalRefs
        s.processedCount = sp.processed_refs || 0
      }
      // 拉日志
      try {
        const logRes = await http.get(`/tasks/${taskId}/logs/`)
        let logContent = logRes.data.log_content || logRes.data.lines?.join('\n') || ''
        if (!logContent) {
          if (status === 'pending') logContent = '正在启动任务，请稍候...'
          else if (status === 'queuing') logContent = `排队等待资源中（当前第 ${queueInfo.value.position || '?'} 位），系统将自动为您分配线程...`
          else if (status === 'running') logContent = '任务正在运行中，正在等待日志输出...'
        }
        s.aiScreenLogContent = logContent
      } catch {}

      if (['running', 'pending', 'stopping', 'queuing'].includes(status)) {
        // queuing 状态变化慢，每 5s 轮询一次即可；running 时 2s 轮询
        const interval = status === 'queuing' ? 5000 : 2000
        if (status === 'queuing') {
          // 更新排队信息
          const qi = task.config?.queue_info || {}
          queueInfo.value = {
            position: qi.position || 0,
            queueLength: qi.queue_length || 0,
            slotsNeeded: qi.slots_needed || 0,
            slotsFree: qi.slots_free || 0,
            slotsTotal: qi.slots_total || queueInfo.value.slotsTotal,
          }
        }
        if (pollCount % 5 === 0 && status !== 'queuing') {
          loadPending()
          loadScreened()
        }
        setTimeout(poll, interval)
      } else {
        s.isProcessing = false
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        await project.fetchStages(project.currentProject.id)
        if (status === 'completed') {
          await Promise.all([loadPending(), loadScreened(), loadAiScreenStats()])
          // 任务完成后刷新页面内余额条 + 通知 AppHeader 同步余额胶囊
          loadBilling()
          window.dispatchEvent(new CustomEvent('app:balance-changed'))
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

<style scoped>
/* ── AI初筛专属一页布局 ── */
.ai-screen-layout {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 0;
  padding: 16px;
  overflow: hidden;
}

/* 顶部：标题 + 模型 + Prompt 开关 */
.ai-screen-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.ai-top-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.ai-model-chips {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
  gap: 4px;
}
.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #fff;
  font-size: 0.78rem;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.model-chip:hover { border-color: #a5b4fc; color: #4338ca; }
.model-chip-active {
  border-color: #6366f1;
  background: #eef2ff;
  color: #4338ca;
  font-weight: 600;
}
.model-chip-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ai-prompt-toggle {
  flex-shrink: 0;
}
.prompt-toggle-btn {
  display: flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  font-size: 0.78rem;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}
.prompt-toggle-btn:hover { border-color: #a5b4fc; color: #4338ca; }

/* Prompt 展开面板 */
.ai-prompt-panel {
  margin-bottom: 8px;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  flex-shrink: 0;
}

/* 主体：左文献列表 + 右日志/进度/按钮 */
.ai-screen-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: minmax(0, 1fr);
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.ai-ref-panel {
  height: 100% !important;
  min-height: 0;
  overflow: hidden;
}

/* 右侧面板 */
.ai-right-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  min-height: 0;
}

/* 日志控制台 */
.ai-log-console {
  flex: 1;
  min-height: 0;
  border-radius: 12px;
  padding: 12px;
  overflow-y: auto;
}

/* 进度条 */
.ai-progress-bar {
  flex-shrink: 0;
  padding: 8px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

/* 操作按钮区 */
.ai-action-area {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ai-action-btn {
  width: 100%;
  padding: 10px 16px;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
  disabled: opacity-50;
}
.ai-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 余额信息条 */
.billing-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 0.78rem;
  border: 1px solid #e2e8f0;
}
.billing-bar-ok {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}
.billing-bar-danger {
  background: #fff1f2;
  border-color: #fecdd3;
  color: #be123c;
}
.billing-item { white-space: nowrap; }
.billing-warn { font-weight: 600; margin-left: auto; }

/* 排队状态条 */
.queue-status-bar {
  background: #fffbeb;
  border: 1px solid #fbbf24;
  border-radius: 6px;
  padding: 8px 12px;
  margin: 6px 0;
}
</style>
