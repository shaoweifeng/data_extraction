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
    <div v-if="s.screeningResults" class="step-list-box mb-6 max-w-md mx-auto" style="padding:20px 24px">
      <div class="grid grid-cols-3 gap-4">
        <div class="step-stat-card text-center">
          <div class="text-3xl font-bold text-green-600">{{ s.screeningResults.included }}</div>
          <div class="text-sm text-gray-500 mt-1">已纳入</div>
        </div>
        <div class="step-stat-card text-center">
          <div class="text-3xl font-bold text-red-500">{{ s.screeningResults.excluded }}</div>
          <div class="text-sm text-gray-500 mt-1">已排除</div>
        </div>
        <div class="step-stat-card text-center">
          <div class="text-3xl font-bold text-gray-700">{{ s.screeningResults.total }}</div>
          <div class="text-sm text-gray-500 mt-1">总计</div>
        </div>
      </div>
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
        <p class="text-xs text-gray-400 mb-1">下载历史版本（点击导出后自动更新）</p>

        <!-- 所有文献 Excel -->
        <ExportRow label="所有文献" :files="s.exportXlsxAllFiles" v-model:selected="selectedAllVer" color="teal" />
        <!-- 纳入文献 Excel -->
        <ExportRow label="纳入文献" :files="s.exportXlsxIncludedFiles" v-model:selected="selectedIncluVer" color="green" />
        <!-- 排除文献 Excel -->
        <ExportRow label="排除文献" :files="s.exportXlsxExcludedFiles" v-model:selected="selectedExcluVer" color="red" />
        <!-- EndNote RIS -->
        <ExportRow label="EndNote（仅纳入）" :files="s.exportRisFiles" v-model:selected="selectedRisVer" color="blue" ris />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
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

// ── 内联子组件（简单导出行）──
const ExportRow = {
  props: ['label', 'files', 'selected', 'color', 'ris'],
  emits: ['update:selected'],
  template: `
    <div class="flex items-center gap-2">
      <span class="text-xs text-gray-500 w-28 text-right flex-shrink-0" v-html="label.replace('（', '<br/><span class=&quot;text-gray-400&quot;>（').replace('）', '）</span>')"></span>
      <button
        @click="files[selected] && downloadFile(files[selected])"
        :disabled="!files || files.length === 0"
        :class="'bg-' + color + '-600 hover:bg-' + color + '-700'"
        class="text-white py-1.5 rounded-lg font-medium shadow disabled:bg-gray-300 disabled:cursor-not-allowed transition w-[130px] text-sm flex-shrink-0"
      >
        <i class="fas fa-file-download mr-1"></i>{{ ris ? '下载EndNote' : '下载Excel' }}
      </button>
      <select
        v-if="files && files.length > 0"
        :value="selected"
        @change="$emit('update:selected', Number($event.target.value))"
        class="border rounded-lg px-2 py-1.5 text-sm bg-white min-w-0 flex-1 input-base" style="padding-top:5px;padding-bottom:5px"
      >
        <option v-for="(f, i) in files" :key="f.id" :value="i">{{ fileLabel(f) }}</option>
      </select>
      <span v-else class="text-xs text-gray-400 flex-1">暂无记录</span>
    </div>
  `,
  setup(props) {
    const downloadFile = (f) => {
      const a = document.createElement('a')
      a.href = f.file
      a.download = f.filename
      a.click()
    }
    return { downloadFile, fileLabel: exportFileLabel }
  },
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
    s.exportFiles = extractListData(res.data)
  } catch {}
}

// ── 导出任务 ──
async function exportResults(exportType) {
  s.isExporting = true
  s.exportingType = exportType
  try {
    const res = await httpNoTimeout.post('/tasks/', {
      project: project.currentProject.id,
      task_type: 'result_aggregation',
      config: { ai_model: s.selectedAiModel, export_type: exportType },
    })
    const task = res.data
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

onMounted(loadExportFiles)
</script>
