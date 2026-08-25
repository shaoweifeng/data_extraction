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

      <!-- AI 初筛结果 -->
      <div class="stat-block">
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

      <!-- 人工审阅修正（只有参与了人工审阅才显示） -->
      <template v-if="displayStats.reviewed > 0">
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

        <!-- 最终筛选结果（人工 + 未审AI的综合） -->
        <div class="stat-block stat-block-final">
          <div class="stat-block-title">
            <i class="fas fa-check-double text-teal-600"></i> 最终筛选结果
            <span class="stat-block-sub">（已审阅文献取人工结论，未审阅文献取 AI 结论）</span>
            <span v-if="displayStats.ai_accuracy !== null && displayStats.ai_accuracy !== undefined"
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

        <!-- AI 准确率模块已移除，准确率数字展示在"最终筛选结果"标题行右侧 -->
      </template>
    </div>

    <!-- 导出按钮区域 -->
    <div class="space-y-3">
      <!-- 生成按钮行 -->
      <div class="flex gap-3 justify-center flex-wrap">
        <button
          @click="exportResults('all')"
          :disabled="s.isExporting"
          class="bg-teal-600 text-white px-5 py-2.5 rounded-lg font-medium shadow hover:bg-teal-700 disabled:opacity-50 transition"
        >
          <i v-if="s.exportingType === 'all'" class="fas fa-spinner fa-spin mr-1.5"></i>
          <i v-else class="fas fa-layer-group mr-1.5"></i>导出所有文献
        </button>
        <button
          @click="exportResults('included')"
          :disabled="s.isExporting"
          class="bg-green-600 text-white px-5 py-2.5 rounded-lg font-medium shadow hover:bg-green-700 disabled:opacity-50 transition"
        >
          <i v-if="s.exportingType === 'included'" class="fas fa-spinner fa-spin mr-1.5"></i>
          <i v-else class="fas fa-check-circle mr-1.5"></i>导出纳入文献
        </button>
        <button
          @click="exportResults('excluded')"
          :disabled="s.isExporting"
          class="bg-red-500 text-white px-5 py-2.5 rounded-lg font-medium shadow hover:bg-red-600 disabled:opacity-50 transition"
        >
          <i v-if="s.exportingType === 'excluded'" class="fas fa-spinner fa-spin mr-1.5"></i>
          <i v-else class="fas fa-times-circle mr-1.5"></i>导出排除文献
        </button>
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
import { ref, computed, onMounted } from 'vue'
import { useScreeningStore } from '@/stores/screening'
import { useProjectStore } from '@/stores/project'
import { useTaskStore } from '@/stores/task'
import http, { httpNoTimeout } from '@/api/http'
import { extractListData, exportFileLabel } from '@/utils/format'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const selectedAllVer = ref(0)
const selectedIncluVer = ref(0)
const selectedExcluVer = ref(0)
const selectedRisVer = ref(0)

// 本地统计（脱离 screening store，直接从 review/stats 接口读）
const exportStats = ref(null)

// 优先展示 exportStats（含人工审阅结果），降级展示 screening store 里的 AI 结果
const displayStats = computed(() => {
  if (exportStats.value) return exportStats.value
  return s.screeningResults
})

// ── 加载统计（从 review/stats 读取完整数据）──
async function loadStats() {
  if (!project.currentProject) return
  try {
    const res = await http.get('/review/stats/', {
      params: { project: project.currentProject.id }
    })
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
  const a = document.createElement('a')
  a.href = f.file_url || f.file
  a.download = f.filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// ── 加载导出文件列表 ──
async function loadExportFiles() {
  if (!project.currentProject) return
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  const expStep = stage?.steps.find((st) => st.step_key === 'export')
  if (!expStep) return
  s.exportStepId = expStep.id
  try {
    const res = await http.get(`/files/?project=${project.currentProject.id}&step=${expStep.id}&data_category=output&limit=100`)
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

// ── 导出任务 ──
async function exportResults(exportType) {
  s.isExporting = true
  s.exportingType = exportType
  try {
    const res = await httpNoTimeout.post('/tasks/', {
      project: project.currentProject.id,
      task_type: 'result_aggregation',
      config: {
        ai_model: s.selectedAiModel,
        // 多模型时一并传入，供后端生成正确的文件名
        ai_models: s.selectedAiModels?.length ? s.selectedAiModels : (s.selectedAiModel ? [s.selectedAiModel] : []),
        export_type: exportType,
      },
    })
    const task = res.data
    // export 是同步步骤，POST 返回时任务已完成；用轮询作兜底
    if (task.status === 'completed') {
      s.isExporting = false
      s.exportingType = ''
      await project.fetchStages(project.currentProject.id)
      await loadExportFiles()
      return
    }
    const pollInterval = setInterval(async () => {
      try {
        const statusRes = await http.get(`/tasks/${task.id}/`)
        const status = statusRes.data.status
        if (status === 'completed') {
          clearInterval(pollInterval)
          s.isExporting = false
          s.exportingType = ''
          await project.fetchStages(project.currentProject.id)
          await loadExportFiles()
        } else if (status === 'failed') {
          clearInterval(pollInterval)
          s.isExporting = false
          s.exportingType = ''
          alert('导出失败，请查看日志')
        }
      } catch {}
    }, 1500)
  } catch (err) {
    alert(`启动失败: ${err.response?.data?.error || err.message}`)
    s.isExporting = false
    s.exportingType = ''
  }
}

onMounted(async () => {
  await Promise.all([loadStats(), loadExportFiles()])
})
</script>

<style scoped>
/* 统计区域 */
.stat-section { margin-bottom: 1.5rem; display: flex; flex-direction: column; gap: .9rem; }
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
