<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#0d9488,#14b8a6)">
        <i class="fas fa-chart-pie"></i>
      </div>
      <div>
        <h3 class="step-title">结果归纳与导出</h3>
        <p class="step-subtitle">汇总筛选结果，导出 Excel 和 RIS 文件</p>
      </div>
    </div>

    <!-- 统计数据 -->
    <div v-if="displayStats" class="stat-section">

      <!-- AI 初筛结果（仅管理员可见） -->
      <div v-if="auth.isAdmin" class="stat-block">
        <div class="stat-block-title">
          <i class="fas fa-robot"></i> AI 初筛结果
        </div>
        <div class="stat-row">
          <div class="stat-card green">
            <div class="stat-num">{{ displayStats.ai_included ?? displayStats.included }}</div>
            <div class="stat-lbl">AI 纳入</div>
          </div>
          <div class="stat-card red">
            <div class="stat-num">{{ displayStats.ai_excluded ?? displayStats.excluded }}</div>
            <div class="stat-lbl">AI 排除</div>
          </div>
          <div v-if="(displayStats.ai_conflict ?? 0) > 0" class="stat-card yellow">
            <div class="stat-num">{{ displayStats.ai_conflict }}</div>
            <div class="stat-lbl">模型歧义</div>
          </div>
          <div class="stat-card gray">
            <div class="stat-num">{{ displayStats.total }}</div>
            <div class="stat-lbl">总计</div>
          </div>
        </div>
      </div>

      <!-- 人工审阅修正（只有参与了人工审阅才显示；仅管理员可见） -->
      <template v-if="auth.isAdmin && displayStats.reviewed > 0">
        <div class="stat-block">
          <div class="stat-block-title">
            <i class="fas fa-user-edit"></i> 人工审阅情况
            <span class="stat-block-sub">（已审阅 {{ displayStats.reviewed }} / {{ displayStats.total }} 篇，其中 {{ displayStats.overridden }} 篇覆写了 AI 判断）</span>
          </div>
          <div class="stat-row">
            <div class="stat-card green">
              <div class="stat-num">{{ displayStats.included }}</div>
              <div class="stat-lbl">人工纳入</div>
            </div>
            <div class="stat-card red">
              <div class="stat-num">{{ displayStats.excluded }}</div>
              <div class="stat-lbl">人工排除</div>
            </div>
            <div class="stat-card yellow">
              <div class="stat-num">{{ displayStats.pending ?? 0 }}</div>
              <div class="stat-lbl">待定</div>
            </div>
            <div class="stat-card gray">
              <div class="stat-num">{{ displayStats.unreviewed }}</div>
              <div class="stat-lbl">未审阅</div>
            </div>
          </div>
        </div>
      </template>

      <!-- 最终筛选结果：管理员 → 人工审阅后才显示；普通用户 → 始终显示 -->
      <template v-if="auth.isAdmin ? displayStats.reviewed > 0 : true">
        <div class="stat-block stat-block-final">
          <div class="stat-block-title">
            <i class="fas fa-check-double text-teal-600"></i> 最终筛选结果
            <span class="stat-block-sub">（已审阅文献取人工结论，未审阅文献取 AI 结论）</span>
            <span v-if="auth.isAdmin && displayStats.ai_accuracy !== null && displayStats.ai_accuracy !== undefined"
                  class="ml-auto text-xs font-semibold"
                  :class="displayStats.ai_accuracy >= 80 ? 'text-green-600' : displayStats.ai_accuracy >= 60 ? 'text-amber-600' : 'text-red-600'">
              AI 准确率 {{ displayStats.ai_accuracy }}%
            </span>
          </div>
          <div class="stat-row">
            <div class="stat-card green">
              <div class="stat-num">{{ displayStats.final_included ?? displayStats.included }}</div>
              <div class="stat-lbl">最终纳入</div>
            </div>
            <div class="stat-card red">
              <div class="stat-num">{{ displayStats.final_excluded ?? displayStats.excluded }}</div>
              <div class="stat-lbl">最终排除</div>
            </div>
            <div class="stat-card yellow">
              <div class="stat-num">{{ displayStats.final_conflict_pending ?? displayStats.pending ?? 0 }}</div>
              <div class="stat-lbl">分歧+待定</div>
            </div>
            <div class="stat-card gray">
              <div class="stat-num">{{ displayStats.total }}</div>
              <div class="stat-lbl">总计</div>
            </div>
          </div>
        </div>
      </template>

      <!-- AI 准确率模块已移除，准确率数字展示在"最终筛选结果"标题行右侧 -->
    </div>

    <!-- 导出按钮区域 -->
    <div class="space-y-3">

      <!-- 待定文献始终阻止导出 -->
      <div v-if="hasPending" class="export-block-tip">
        <i class="fas fa-exclamation-triangle mr-1.5"></i>
        当前仍有 <b>{{ pendingCount }} 篇</b>待定文献，无法导出。请先在【人工审阅】步骤处理。
      </div>

      <!-- AI 分歧默认阻止导出，但允许用户明确豁免 -->
      <div v-if="hasConflict" class="conflict-waiver-box">
        <div class="conflict-waiver-copy">
          <i class="fas fa-code-branch mr-1.5"></i>
          当前有 <b>{{ conflictCount }} 篇</b> AI 分歧文献。建议先人工裁定；如需保留分歧状态直接导出，可启用豁免。
        </div>
        <label class="conflict-waiver-toggle">
          <input v-model="allowConflictExport" type="checkbox">
          <span>允许豁免分歧文献并导出</span>
        </label>
        <p v-if="allowConflictExport" class="conflict-waiver-note">
          Excel 的 include_or_not 将标记为 conflict，exclusion_reason 将记录各模型决定和详细理由。
        </p>
        <label v-if="allowConflictExport" class="conflict-waiver-toggle conflict-ris-toggle">
          <input v-model="includeConflictsInRis" type="checkbox">
          <span>同时将分歧文献加入“仅纳入”RIS（导出所有/纳入时）</span>
        </label>
        <p v-if="allowConflictExport && includeConflictsInRis" class="conflict-waiver-note">
          RIS 将使用 N1 备注保留“未经人工裁定”标记和各模型理由。
        </p>
      </div>

      <!-- 生成按钮行 -->
      <div class="flex gap-3 justify-center flex-wrap">
        <button
          @click="exportResults('all')"
          :disabled="s.isExporting || exportBlocked"
          class="bg-teal-600 text-white px-5 py-2.5 rounded-lg font-medium shadow hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <i v-if="s.exportingType === 'all'" class="fas fa-spinner fa-spin mr-1.5"></i>
          <i v-else class="fas fa-layer-group mr-1.5"></i>导出所有文献
        </button>
        <button
          @click="exportResults('included')"
          :disabled="s.isExporting || exportBlocked"
          class="bg-green-600 text-white px-5 py-2.5 rounded-lg font-medium shadow hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <i v-if="s.exportingType === 'included'" class="fas fa-spinner fa-spin mr-1.5"></i>
          <i v-else class="fas fa-check-circle mr-1.5"></i>导出纳入文献
        </button>
        <button
          @click="exportResults('excluded')"
          :disabled="s.isExporting || exportBlocked"
          class="bg-red-500 text-white px-5 py-2.5 rounded-lg font-medium shadow hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <i v-if="s.exportingType === 'excluded'" class="fas fa-spinner fa-spin mr-1.5"></i>
          <i v-else class="fas fa-times-circle mr-1.5"></i>导出排除文献
        </button>
      </div>

      <div v-if="s.isExporting && activeExportTask" class="export-progress-box">
        <div class="export-progress-head">
          <span>
            <i class="fas fa-file-export mr-1.5"></i>
            {{ exportStatusLabel }}
          </span>
          <span class="font-semibold">{{ exportProgressPercent }}%</span>
        </div>
        <div class="export-progress-track">
          <div class="export-progress-fill" :style="{ width: `${exportProgressPercent}%` }"></div>
        </div>
        <div class="export-progress-foot">
          <span v-if="exportTotal > 0">已处理约 {{ exportProcessed.toLocaleString() }} / {{ exportTotal.toLocaleString() }} 篇</span>
          <span v-else>正在等待任务进度…</span>
          <button
            v-if="['pending', 'queuing', 'running'].includes(activeExportTask.status)"
            class="export-stop-btn"
            type="button"
            @click="stopExport"
          >
            <i class="fas fa-stop mr-1"></i>停止导出
          </button>
        </div>
      </div>

      <!-- 下载区 -->
      <div class="step-list-box" style="padding:14px 16px">
        <p class="text-xs text-gray-400 mb-2">下载历史版本（点击导出后自动更新）</p>

        <!-- 所有文献 Excel -->
        <div class="flex items-center gap-2 mb-2">
          <span class="text-xs text-gray-500 w-28 text-right flex-shrink-0">所有文献</span>
          <button
            @click="downloadFile(s.exportXlsxAllFiles[selectedAllVer])"
            :disabled="!s.exportXlsxAllFiles || s.exportXlsxAllFiles.length === 0"
            class="bg-teal-600 hover:bg-teal-700 text-white py-1.5 rounded-lg font-medium shadow disabled:bg-gray-300 disabled:cursor-not-allowed transition w-[130px] text-sm flex-shrink-0"
          >
            <i class="fas fa-file-download mr-1"></i>下载Excel
          </button>
          <select
            v-if="s.exportXlsxAllFiles && s.exportXlsxAllFiles.length > 0"
            v-model="selectedAllVer"
            class="border rounded-lg px-2 py-1.5 text-sm bg-white min-w-0 flex-1 input-base"
          >
            <option v-for="(f, i) in s.exportXlsxAllFiles" :key="f.id" :value="i">{{ exportFileLabel(f) }}</option>
          </select>
          <span v-else class="text-xs text-gray-400 flex-1">暂无记录</span>
        </div>

        <!-- 纳入文献 Excel -->
        <div class="flex items-center gap-2 mb-2">
          <span class="text-xs text-gray-500 w-28 text-right flex-shrink-0">纳入文献</span>
          <button
            @click="downloadFile(s.exportXlsxIncludedFiles[selectedIncluVer])"
            :disabled="!s.exportXlsxIncludedFiles || s.exportXlsxIncludedFiles.length === 0"
            class="bg-green-600 hover:bg-green-700 text-white py-1.5 rounded-lg font-medium shadow disabled:bg-gray-300 disabled:cursor-not-allowed transition w-[130px] text-sm flex-shrink-0"
          >
            <i class="fas fa-file-download mr-1"></i>下载Excel
          </button>
          <select
            v-if="s.exportXlsxIncludedFiles && s.exportXlsxIncludedFiles.length > 0"
            v-model="selectedIncluVer"
            class="border rounded-lg px-2 py-1.5 text-sm bg-white min-w-0 flex-1 input-base"
          >
            <option v-for="(f, i) in s.exportXlsxIncludedFiles" :key="f.id" :value="i">{{ exportFileLabel(f) }}</option>
          </select>
          <span v-else class="text-xs text-gray-400 flex-1">暂无记录</span>
        </div>

        <!-- 排除文献 Excel -->
        <div class="flex items-center gap-2 mb-2">
          <span class="text-xs text-gray-500 w-28 text-right flex-shrink-0">排除文献</span>
          <button
            @click="downloadFile(s.exportXlsxExcludedFiles[selectedExcluVer])"
            :disabled="!s.exportXlsxExcludedFiles || s.exportXlsxExcludedFiles.length === 0"
            class="bg-red-500 hover:bg-red-600 text-white py-1.5 rounded-lg font-medium shadow disabled:bg-gray-300 disabled:cursor-not-allowed transition w-[130px] text-sm flex-shrink-0"
          >
            <i class="fas fa-file-download mr-1"></i>下载Excel
          </button>
          <select
            v-if="s.exportXlsxExcludedFiles && s.exportXlsxExcludedFiles.length > 0"
            v-model="selectedExcluVer"
            class="border rounded-lg px-2 py-1.5 text-sm bg-white min-w-0 flex-1 input-base"
          >
            <option v-for="(f, i) in s.exportXlsxExcludedFiles" :key="f.id" :value="i">{{ exportFileLabel(f) }}</option>
          </select>
          <span v-else class="text-xs text-gray-400 flex-1">暂无记录</span>
        </div>

        <!-- EndNote RIS -->
        <div class="flex items-center gap-2">
          <span class="text-xs text-gray-500 w-28 text-right flex-shrink-0">EndNote<br/><span class="text-gray-400">（仅纳入）</span></span>
          <button
            @click="downloadFile(s.exportRisFiles[selectedRisVer])"
            :disabled="!s.exportRisFiles || s.exportRisFiles.length === 0"
            class="bg-blue-600 hover:bg-blue-700 text-white py-1.5 rounded-lg font-medium shadow disabled:bg-gray-300 disabled:cursor-not-allowed transition w-[130px] text-sm flex-shrink-0"
          >
            <i class="fas fa-file-download mr-1"></i>下载EndNote
          </button>
          <select
            v-if="s.exportRisFiles && s.exportRisFiles.length > 0"
            v-model="selectedRisVer"
            class="border rounded-lg px-2 py-1.5 text-sm bg-white min-w-0 flex-1 input-base"
          >
            <option v-for="(f, i) in s.exportRisFiles" :key="f.id" :value="i">{{ exportFileLabel(f) }}</option>
          </select>
          <span v-else class="text-xs text-gray-400 flex-1">暂无记录</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'
import { useAuthStore } from '@/features/account/store'
import * as screeningApi from '@/features/screening/api'
import * as workflowApi from '@/shared/api/workflow'
import { downloadUrl } from '@/shared/composables/useDownload'
import { pollUntil } from '@/shared/composables/usePolling'
import { extractListData, exportFileLabel } from '@/utils/format'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()
const auth = useAuthStore()

const selectedAllVer = ref(0)
const selectedIncluVer = ref(0)
const selectedExcluVer = ref(0)
const selectedRisVer = ref(0)
let exportAbortController = null
const activeExportTask = ref(null)
const allowConflictExport = ref(false)
const includeConflictsInRis = ref(false)

// 本地统计（脱离 screening store，直接从 review/stats 接口读）
const exportStats = ref(null)

// 优先展示 exportStats（含人工审阅结果），降级展示 screening store 里的 AI 结果
const displayStats = computed(() => {
  if (exportStats.value) return exportStats.value
  return s.screeningResults
})

const pendingCount = computed(() => Number(displayStats.value?.tab_pending ?? displayStats.value?.pending ?? 0))
const conflictCount = computed(() => Number(displayStats.value?.tab_conflict ?? displayStats.value?.ai_conflict ?? 0))
const hasPending = computed(() => pendingCount.value > 0)
const hasConflict = computed(() => conflictCount.value > 0)
const exportBlocked = computed(() => hasPending.value || (hasConflict.value && !allowConflictExport.value))
const exportProgressPercent = computed(() => {
  const progress = Number(activeExportTask.value?.progress_percentage || 0)
  return Math.max(0, Math.min(100, Math.round(progress)))
})
const exportTotal = computed(() => Number(displayStats.value?.total || 0))
const exportProcessed = computed(() => Math.round(exportTotal.value * exportProgressPercent.value / 100))
const exportStatusLabel = computed(() => ({
  pending: '导出任务等待 Worker 接收',
  queuing: '导出任务排队中',
  running: `正在生成${s.exportingType === 'included' ? '纳入' : s.exportingType === 'excluded' ? '排除' : '全部'}文献`,
  stopping: '正在停止导出',
}[activeExportTask.value?.status] || '正在导出'))

// ── 加载统计（从 review/stats 读取完整数据）──
async function loadStats() {
  if (!project.currentProject) return
  try {
    const res = await screeningApi.fetchReviewStats(project.currentProject.id)
    const d = res.data
    if (d.total > 0) {
      // 保存完整 stats 对象，模板直接使用 ai_included/ai_excluded/ai_accuracy 等字段
      exportStats.value = d
    }
  } catch (e) {
    console.error('[StepExport] loadStats 失败', e)
  }
}

// ── 下载文件 ──
function downloadFile(f) {
  if (!f) return
  downloadUrl(f.file_url || f.file, f.filename)
}

// ── 加载导出文件列表 ──
async function loadExportFiles() {
  if (!project.currentProject) return
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  const expStep = stage?.steps.find((st) => st.step_key === 'export')
  if (!expStep) return
  s.exportStepId = expStep.id
  try {
    const res = await workflowApi.fetchFiles({ project: project.currentProject.id, step: expStep.id, data_category: 'output', limit: 100 })
    const allFiles = extractListData(res.data)
    s.exportFiles = allFiles
    // 按文件名分类填充各导出列表
    s.exportXlsxAllFiles = allFiles.filter(f => f.filename?.includes('_all_') && f.filename?.endsWith('.xlsx'))
    s.exportXlsxIncludedFiles = allFiles.filter(f => f.filename?.includes('_included_') && f.filename?.endsWith('.xlsx'))
    s.exportXlsxExcludedFiles = allFiles.filter(f => f.filename?.includes('_excluded_') && f.filename?.endsWith('.xlsx'))
    s.exportRisFiles = allFiles.filter(f => f.filename?.endsWith('.ris'))
    // 兼容：若无明确分类文件则全部放入 All
    if (s.exportXlsxAllFiles.length === 0 && s.exportXlsxIncludedFiles.length === 0 && s.exportXlsxExcludedFiles.length === 0) {
      s.exportXlsxAllFiles = allFiles.filter(f => f.filename?.endsWith('.xlsx'))
    }
    // 重置选中项
    selectedAllVer.value = 0
    selectedIncluVer.value = 0
    selectedExcluVer.value = 0
    selectedRisVer.value = 0
  } catch (e) {
    console.error('[StepExport] loadExportFiles 失败', e)
  }
}

async function monitorExportTask(task) {
  activeExportTask.value = task
  s.isExporting = true
  s.exportingType = task.config?.export_type || s.exportingType || 'all'
  allowConflictExport.value = Boolean(task.config?.allow_unresolved_conflicts)
  includeConflictsInRis.value = Boolean(task.config?.include_conflicts_in_ris)

  try {
    const completedTask = ['completed', 'failed', 'stopped'].includes(task.status)
      ? task
      : await pollUntil(
        async () => {
          const current = (await workflowApi.fetchTask(task.id)).data
          activeExportTask.value = current
          return current
        },
        current => ['completed', 'failed', 'stopped'].includes(current.status),
        {
          interval: 1500,
          maxAttempts: 2400,
          timeoutMessage: '导出任务运行超过 1 小时，请稍后刷新页面查看结果',
          signal: exportAbortController.signal,
        },
      )

    activeExportTask.value = completedTask
    if (completedTask.status === 'failed') {
      alert(`导出失败：${completedTask.error_message || '请查看任务日志'}`)
      return
    }
    if (completedTask.status === 'stopped') return

    await project.fetchStages(project.currentProject.id)
    await loadExportFiles()
  } catch (err) {
    if (err?.name !== 'AbortError') {
      alert(`导出进度查询失败：${err.response?.data?.error || err.message}`)
    }
  } finally {
    s.isExporting = false
    s.exportingType = ''
    activeExportTask.value = null
  }
}

async function restoreActiveExport() {
  const result = await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
  const activeTask = result?.tasks?.find(task => (
    task.task_type === 'export'
    && ['pending', 'queuing', 'running', 'stopping'].includes(task.status)
  ))
  if (!activeTask) return

  exportAbortController?.abort()
  exportAbortController = new AbortController()
  void monitorExportTask(activeTask)
}

async function stopExport() {
  if (!activeExportTask.value) return
  try {
    await workflowApi.stopTask(activeExportTask.value.id)
    activeExportTask.value = { ...activeExportTask.value, status: 'stopped' }
  } catch (err) {
    alert(`停止失败：${err.response?.data?.error || err.message}`)
  }
}

// ── 导出任务 ──
async function exportResults(exportType) {
  exportAbortController?.abort()
  exportAbortController = new AbortController()
  s.isExporting = true
  s.exportingType = exportType
  try {
    const res = await workflowApi.createTask({
      project: project.currentProject.id,
      task_type: 'export',
      config: {
        ai_model: s.selectedAiModel,
        // 多模型时一并传入，供后端生成正确的文件名
        ai_models: s.selectedAiModels?.length ? s.selectedAiModels : (s.selectedAiModel ? [s.selectedAiModel] : []),
        export_type: exportType,
        allow_unresolved_conflicts: allowConflictExport.value,
        include_conflicts_in_ris: allowConflictExport.value && includeConflictsInRis.value,
      },
    })
    const task = res.data
    await monitorExportTask(task)
  } catch (err) {
    if (err?.name === 'AbortError') return
    alert(`启动失败: ${err.response?.data?.error || err.message}`)
    s.isExporting = false
    s.exportingType = ''
  }
}

onMounted(async () => {
  await Promise.all([loadStats(), loadExportFiles()])
  await restoreActiveExport()
})
onUnmounted(() => exportAbortController?.abort())
</script>

<style scoped>
/* 统计区域 */
.stat-section { margin-bottom: 1.5rem; display: flex; flex-direction: column; gap: .9rem; }

.export-progress-box { max-width: 680px; margin: 0 auto; padding: 12px 14px; border: 1px solid #99f6e4; border-radius: 10px; background: #f0fdfa; }
.export-progress-head, .export-progress-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #0f766e; font-size: .82rem; }
.export-progress-track { height: 8px; margin: 9px 0 7px; overflow: hidden; border-radius: 999px; background: #ccfbf1; }
.export-progress-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, #0d9488, #14b8a6); transition: width .3s ease; }
.export-stop-btn { padding: 3px 9px; border: 1px solid #fca5a5; border-radius: 6px; color: #b91c1c; background: #fff; cursor: pointer; white-space: nowrap; }
.export-stop-btn:hover { background: #fef2f2; }

/* 导出阻止提示 */
.export-block-tip {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #c2410c;
  border-radius: 8px;
  padding: 9px 14px;
  font-size: .82rem;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.conflict-waiver-box { padding: 11px 14px; border: 1px solid #fde68a; border-radius: 9px; background: #fffbeb; color: #92400e; font-size: .82rem; }
.conflict-waiver-copy { display: flex; align-items: center; flex-wrap: wrap; gap: 3px; }
.conflict-waiver-toggle { display: inline-flex; align-items: center; gap: 7px; margin-top: 9px; font-weight: 600; cursor: pointer; }
.conflict-waiver-toggle input { width: 15px; height: 15px; accent-color: #d97706; }
.conflict-ris-toggle { display: flex; font-weight: 500; }
.conflict-waiver-note { margin-top: 7px; color: #a16207; font-size: .76rem; }
.stat-block {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: .85rem 1rem;
}
/* 最终筛选结果突出显示 */
.stat-block-final {
  background: linear-gradient(135deg, #f0fdf4, #ecfdf5);
  border-color: #6ee7b7;
}
.stat-block-title {
  font-size: .8rem; font-weight: 600; color: #475569;
  display: flex; align-items: center; gap: .4rem; margin-bottom: .7rem;
}
.stat-block-title i { color: #6366f1; }
.stat-block-sub { font-weight: 400; color: #94a3b8; font-size: .75rem; }
.stat-row { display: flex; gap: .65rem; flex-wrap: wrap; }
.stat-card {
  flex: 1; min-width: 70px; text-align: center;
  background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .55rem .4rem;
}
.stat-card.green { border-top: 3px solid #16a34a; }
.stat-card.red   { border-top: 3px solid #dc2626; }
.stat-card.gray  { border-top: 3px solid #94a3b8; }
.stat-card.yellow{ border-top: 3px solid #ca8a04; }
.stat-card.purple{ border-top: 3px solid #7c3aed; }
.stat-num { font-size: 1.5rem; font-weight: 700; color: #1e293b; }
.stat-lbl { font-size: .72rem; color: #94a3b8; margin-top: .1rem; }

/* 准确率 */
.accuracy-row { display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap; }
.accuracy-gauge { position: relative; width: 76px; height: 76px; flex-shrink: 0; }
.gauge-svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.gauge-bg {
  fill: none; stroke: #e2e8f0; stroke-width: 3.5;
  stroke-linecap: round; stroke-dasharray: 100, 100;
}
.gauge-fill { fill: none; stroke-width: 3.5; stroke-linecap: round; transition: stroke-dasharray .6s ease; }
.gauge-val {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: .85rem; font-weight: 700;
}
.gauge-val.good  { color: #16a34a; }
.gauge-val.mid   { color: #ca8a04; }
.gauge-val.bad   { color: #dc2626; }
.accuracy-detail { display: flex; flex-direction: column; gap: .3rem; }
.acc-item { display: flex; align-items: center; gap: .4rem; font-size: .78rem; color: #475569; }
.acc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.acc-dot.correct { background: #16a34a; }
.acc-dot.wrong   { background: #dc2626; }
.acc-dot.default { background: #94a3b8; }
</style>
