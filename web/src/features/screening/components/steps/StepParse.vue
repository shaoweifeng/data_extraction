<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#3b82f6,#6366f1)">
        <i class="fas fa-file-import"></i>
      </div>
      <div>
        <h3 class="step-title">导入文献索引</h3>
        <p class="step-subtitle">支持主流数据库导出格式，自动解析文献元数据</p>
      </div>
    </div>

    <!-- 上传/解析进度区域 -->
    <div
      v-if="s.uploadPhase !== 'idle'"
      class="progress-banner mb-4"
      :class="s.uploadPhase === 'uploading' ? 'upload-banner' : 'parse-banner'"
    >
      <div class="flex items-center gap-2 mb-2">
        <i class="fas fa-spinner fa-spin"></i>
        <span class="font-medium text-sm">
          <template v-if="s.uploadPhase === 'uploading'">
            正在上传文件 ({{ s.uploadFileIndex }}/{{ s.uploadTotalFiles }})：{{ s.uploadCurrentFile }}
          </template>
          <template v-else>
            {{ s.parseProgressMsg || '正在启动解析...' }}
          </template>
        </span>
      </div>
      <div class="progress-bar-track" style="height:5px">
        <div
          v-if="s.uploadPhase === 'uploading'"
          class="progress-bar-fill"
          :style="{ width: s.uploadProgress + '%', background: '#3b82f6' }"
        ></div>
        <div
          v-else-if="s.parseProgressTotal > 0"
          class="progress-bar-fill"
          :style="{ width: s.parseProgressCurrent + '%' }"
        ></div>
        <div v-else class="progress-bar-fill animate-pulse" style="width:40%"></div>
      </div>
      <div class="flex text-xs mt-1 opacity-70">
        <span v-if="s.uploadPhase === 'uploading'">{{ s.uploadProgress }}%</span>
        <span v-else-if="s.parseProgressTotal > 0">{{ s.parseProgressCurrent }}%</span>
        <span v-else>解析中...</span>
      </div>
    </div>

    <!-- 上传区域 -->
    <div
      class="upload-zone"
      :class="{
        'upload-zone--disabled': s.isParsing || s.uploadPhase !== 'idle',
        'upload-zone--dragover': isDragOver,
      }"
      @click="s.isParsing || s.uploadPhase !== 'idle' ? null : fileInput?.click()"
      @dragover.prevent="onDragOver"
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInput"
        type="file"
        class="hidden"
        multiple
        accept=".ris,.bib,.nbib,.xml,.ciw,.enw,.txt,.doc,.docx"
        @change="handleUpload"
      />

      <!-- 上传图标 + 按钮 -->
      <div class="upload-zone__top">
        <div class="upload-zone__icon">
          <i class="fas fa-cloud-upload-alt"></i>
        </div>
        <button
          :disabled="s.isParsing || s.uploadPhase !== 'idle'"
          class="btn-primary upload-btn"
        >
          <i v-if="s.isParsing || s.uploadPhase !== 'idle'" class="fas fa-spinner fa-spin"></i>
          <i v-else class="fas fa-upload"></i>
          {{ s.uploadPhase === 'uploading' ? '上传中...' : s.isParsing ? '正在解析...' : '上传 Reference 文件' }}
        </button>
        <p class="upload-hint">点击选择或将文件拖拽到此处</p>
        <!-- 紧凑格式行 -->
        <div class="fmt-inline">
          <span class="fmt-inline-label">支持格式：</span>
          <code>.ris</code><code>.bib</code><code>.nbib</code><code>.xml</code>
          <code>.ciw</code><code>.enw</code><code>.docx</code><code>.txt</code>
          <button class="fmt-help-btn" :title="showFmtDetail ? '收起' : '查看格式说明'" @click.stop="showFmtDetail = !showFmtDetail">
            <i class="fas" :class="showFmtDetail ? 'fa-times' : 'fa-question-circle'"></i>
          </button>
        </div>

        <!-- 展开的格式详情 -->
        <transition name="fmt-slide">
          <div v-if="showFmtDetail" class="fmt-detail-panel" @click.stop>
            <table class="fmt-table">
              <thead><tr><th>扩展名</th><th>格式</th><th>常见来源</th></tr></thead>
              <tbody>
                <tr><td><code>.ris</code></td><td>RIS</td><td>EndNote · Zotero · 万方</td></tr>
                <tr><td><code>.bib</code> <code>.bibtex</code></td><td>BibTeX</td><td>LaTeX 工具链</td></tr>
                <tr><td><code>.nbib</code> <code>.medline</code></td><td>NBIB / Medline</td><td>PubMed</td></tr>
                <tr><td><code>.xml</code></td><td>XML</td><td>Web of Science · Cochrane</td></tr>
                <tr><td><code>.ciw</code></td><td>CIW</td><td>Web of Science（早期）</td></tr>
                <tr><td><code>.enw</code></td><td>ENW</td><td>EndNote Web</td></tr>
                <tr><td><code>.docx</code> <code>.doc</code></td><td>Word 文档</td><td>手动整理</td></tr>
                <tr><td><code>.txt</code></td><td>纯文本</td><td>CNKI · 维普</td></tr>
              </tbody>
            </table>
          </div>
        </transition>
      </div>
    </div>

    <!-- 已导入文件列表 -->
    <div class="mt-6">
      <div v-if="parseOverview.totalFiles > 0" class="parse-overview mb-4">
        <div class="parse-overview__head">
          <div>
            <h4>解析结果</h4>
            <p>以下统计按当前已导入的索引文件汇总</p>
          </div>
          <span class="parse-health" :class="`parse-health--${parseOverview.status}`">
            {{ overviewStatusText }}
          </span>
        </div>
        <div class="parse-overview__grid">
          <div class="parse-metric"><strong>{{ parseOverview.totalFiles }}</strong><span>索引文件</span></div>
          <div class="parse-metric"><strong>{{ parseOverview.detected }}</strong><span>检测条目</span></div>
          <div class="parse-metric parse-metric--success"><strong>{{ parseOverview.parsed }}</strong><span>成功解析</span></div>
          <div class="parse-metric parse-metric--error"><strong>{{ parseOverview.skipped }}</strong><span>异常跳过</span></div>
          <div class="parse-metric parse-metric--warning"><strong>{{ parseOverview.missingAbstract }}</strong><span>摘要缺失</span></div>
        </div>
      </div>
      <div class="flex items-center justify-between mb-3">
        <h4 class="font-semibold text-gray-700 text-sm">
          <i class="fas fa-layer-group mr-1.5 text-blue-400"></i>
          已导入的索引
        </h4>
        <span v-if="s.parsedCount > 0 && !s.isParsing" class="badge badge-green">
          已解析 {{ s.parsedCount }} 条文献
        </span>
      </div>
      <div class="step-list-box" style="max-height:16rem">
        <div v-if="s.referenceFiles.length === 0" class="text-gray-400 text-sm text-center py-6">
          <i class="fas fa-inbox text-2xl mb-2 opacity-40 block"></i>
          暂无已导入的索引
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="file in s.referenceFiles"
            :key="file.id"
            class="parse-file-card"
          >
            <div class="step-list-item parse-file-row">
              <button class="parse-file-main" @click="toggleParseReport(file)">
                <i class="fas fa-bookmark text-blue-400 flex-shrink-0"></i>
                <span class="truncate text-sm text-gray-700">{{ file.filename }}</span>
              </button>
              <div class="parse-file-actions">
                <template v-if="file.metadata?.parse_summary">
                  <span v-if="file.metadata.parse_summary.status === 'failed'" class="parse-badge parse-badge--error">
                    解析失败
                  </span>
                  <span v-else class="parse-badge parse-badge--success">
                    成功 {{ file.metadata.parse_summary.parsed_entries }}/{{ file.metadata.parse_summary.detected_entries }}
                  </span>
                  <span v-if="file.metadata.parse_summary.skipped_entries" class="parse-badge parse-badge--error">
                    异常 {{ file.metadata.parse_summary.skipped_entries }}
                  </span>
                  <span v-if="file.metadata.parse_summary.missing_abstract_entries" class="parse-badge parse-badge--warning">
                    缺摘要 {{ file.metadata.parse_summary.missing_abstract_entries }}
                  </span>
                  <button class="parse-expand-btn" title="查看解析详情" @click="toggleParseReport(file)">
                    <i class="fas" :class="expandedFileId === file.id ? 'fa-chevron-up' : 'fa-chevron-down'"></i>
                  </button>
                </template>
                <span v-else-if="s.isParsing" class="parse-badge parse-badge--pending">等待统计</span>
                <a
                  :href="`/api/files/${file.id}/download/`"
                  :download="file.filename"
                  class="text-blue-400 hover:text-blue-600 transition"
                  title="下载原始文件"
                >
                  <i class="fas fa-download text-sm"></i>
                </a>
                <button class="text-gray-300 hover:text-red-400 transition" @click="handleDeleteFile(file.id)">
                  <i class="fas fa-trash text-sm"></i>
                </button>
              </div>
            </div>

            <div v-if="expandedFileId === file.id" class="parse-detail">
              <div v-if="reportLoading[file.id]" class="parse-detail__empty">
                <i class="fas fa-spinner fa-spin"></i> 正在加载解析报告...
              </div>
              <template v-else-if="reportByFile[file.id]">
                <div class="parse-detail__summary">
                  <span>格式 <strong>{{ reportByFile[file.id].format?.toUpperCase() }}</strong></span>
                  <span>检测 <strong>{{ reportByFile[file.id].detected_entries }}</strong></span>
                  <span>成功 <strong>{{ reportByFile[file.id].parsed_entries }}</strong></span>
                  <span>跳过 <strong>{{ reportByFile[file.id].skipped_entries }}</strong></span>
                  <span>摘要缺失 <strong>{{ reportByFile[file.id].missing_abstract_entries }}</strong></span>
                </div>
                <div v-if="reportByFile[file.id].issues?.length" class="parse-issues">
                  <div v-for="(issue, index) in reportByFile[file.id].issues" :key="`${issue.code}-${index}`" class="parse-issue">
                    <span class="parse-issue__level" :class="`parse-issue__level--${issue.severity}`">
                      {{ issue.severity === 'error' ? '错误' : '警告' }}
                    </span>
                    <div class="parse-issue__body">
                      <div class="parse-issue__location">
                        {{ issueLocation(issue) }}
                        <span v-if="issue.identifier"> · {{ issue.identifier }}</span>
                      </div>
                      <div class="parse-issue__message">{{ issue.message }}</div>
                      <div v-if="issue.title" class="parse-issue__title">{{ issue.title }}</div>
                      <div v-if="issue.suggestion" class="parse-issue__suggestion">建议：{{ issue.suggestion }}</div>
                    </div>
                  </div>
                </div>
                <div v-else class="parse-detail__empty parse-detail__empty--success">
                  <i class="fas fa-check-circle"></i> 未发现解析异常或字段缺失
                </div>
              </template>
              <div v-else class="parse-detail__empty">暂无可用的解析报告</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted, onUnmounted } from 'vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'
import * as screeningApi from '@/features/screening/api'
import * as workflowApi from '@/shared/api/workflow'
import { extractListData } from '@/utils/format'
const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()
const fileInput = ref(null)
const showFmtDetail = ref(false)
const isDragOver = ref(false)
const expandedFileId = ref(null)
const reportByFile = reactive({})
const reportLoading = reactive({})
let parsePollGeneration = 0
let parsePollTimer = null

const parseOverview = computed(() => {
  const summaries = s.referenceFiles
    .map(file => file.metadata?.parse_summary)
    .filter(Boolean)
  const overview = {
    totalFiles: summaries.length,
    detected: 0,
    parsed: 0,
    skipped: 0,
    missingAbstract: 0,
    status: 'success',
  }
  for (const summary of summaries) {
    overview.detected += Number(summary.detected_entries || 0)
    overview.parsed += Number(summary.parsed_entries || 0)
    overview.skipped += Number(summary.skipped_entries || 0)
    overview.missingAbstract += Number(summary.missing_abstract_entries || 0)
  }
  if (summaries.length && summaries.every(summary => summary.status === 'failed')) overview.status = 'failed'
  else if (summaries.some(summary => summary.status === 'failed' || summary.status === 'partial')) overview.status = 'partial'
  else if (summaries.some(summary => summary.status === 'warning')) overview.status = 'warning'
  return overview
})

const overviewStatusText = computed(() => {
  if (parseOverview.value.status === 'failed') return '解析失败'
  if (parseOverview.value.status === 'partial') return '解析完成，存在异常'
  if (parseOverview.value.status === 'warning') return '解析完成，存在字段缺失'
  return '解析完成'
})

function issueLocation(issue) {
  const parts = []
  if (issue.position) parts.push(`第 ${issue.position} 条`)
  if (issue.line) parts.push(`第 ${issue.line} 行`)
  return parts.join(' / ') || '文件级问题'
}

async function toggleParseReport(file) {
  if (!file.metadata?.parse_summary) return
  if (expandedFileId.value === file.id) {
    expandedFileId.value = null
    return
  }
  expandedFileId.value = file.id
  if (reportByFile[file.id] || reportLoading[file.id]) return
  reportLoading[file.id] = true
  try {
    const res = await workflowApi.fetchParseReport(file.id)
    reportByFile[file.id] = res.data
  } catch (err) {
    console.error('加载解析报告失败', err)
    reportByFile[file.id] = null
  } finally {
    reportLoading[file.id] = false
  }
}

function onDragOver() {
  if (s.isParsing || s.uploadPhase !== 'idle') return
  isDragOver.value = true
}
function onDragLeave() {
  isDragOver.value = false
}
function onDrop(event) {
  isDragOver.value = false
  if (s.isParsing || s.uploadPhase !== 'idle') return
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  handleFiles(files)
}
function uploadFileXHR(file, index) {
  s.uploadCurrentFile = file.name
  s.uploadFileIndex = index
  s.uploadProgress = 0
  return screeningApi.uploadReferenceFile(file, project.currentProject.id, ratio => {
    s.uploadProgress = Math.round(ratio * 100)
  })
}
async function handleUpload(event) {
  const files = Array.from(event.target.files)
  if (!files.length) return
  event.target.value = ''
  handleFiles(files)
}

async function handleFiles(files) {
  s.uploadPhase = 'uploading'
  s.uploadTotalFiles = files.length
  const uploadedFileIds = []
  for (let i = 0; i < files.length; i++) {
    try {
      const uploaded = await uploadFileXHR(files[i], i + 1)
      uploadedFileIds.push(uploaded.id)
    } catch (err) {
      alert(`上传 ${files[i].name} 失败: ${err.message}`)
    }
  }
  if (uploadedFileIds.length > 0) {
    s.uploadPhase = 'parsing'
    s.uploadProgress = 100
    await loadScreen1Files()
    await taskStore.fetchActivityLogs(project.currentProject.id)
    await triggerParsingTask(uploadedFileIds)
  } else {
    s.uploadPhase = 'idle'
  }
}
async function loadScreen1Files() {
  try {
    const res = await workflowApi.fetchFiles({ project: project.currentProject.id, data_category: 'input' })
    const files = extractListData(res.data)
    const exts = ['.ris', '.bib', '.nbib', '.xml', '.ciw', '.enw', '.txt', '.doc', '.docx']
    s.referenceFiles = files.filter((f) => exts.some((ext) => f.filename.endsWith(ext)))
  } catch (err) {
    console.error('加载文件失败', err)
  }
}
async function triggerParsingTask(fileIds) {
  s.isParsing = true
  s.parsedCount = 0
  s.uploadPhase = 'parsing'
  s.parseProgressMsg = '正在启动解析任务...'
  try {
    const res = await workflowApi.createTask({
      project: project.currentProject.id,
      task_type: 'parse',
      config: { file_ids: fileIds },
    }, { noTimeout: true })
    const task = res.data
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    pollParsingStatus(task.id)
  } catch (err) {
    alert(`解析启动失败: ${err.response?.data?.error || err.message}`)
    s.isParsing = false
    s.uploadPhase = 'idle'
  }
}
async function pollParsingStatus(taskId) {
  clearTimeout(parsePollTimer)
  const generation = ++parsePollGeneration
  let pollCount = 0
  let errorCount = 0
  const poll = async () => {
    if (generation !== parsePollGeneration) return
    pollCount++
    try {
      const res = await workflowApi.fetchTask(taskId)
      if (generation !== parsePollGeneration) return
      const task = res.data
      const status = task.status
      const pp = task.config?.parse_progress
      s.parseProgressMsg = pp?.message || `解析中... [${pollCount}]`
      if (pp?.current != null) {
        s.parseProgressCurrent = pp.current
        s.parseProgressTotal = pp.total || 100
      }
      if (status === 'running' || status === 'pending') {
        s.parsedCount = task.config.total_entries || task.config.split_files || 0
        parsePollTimer = setTimeout(poll, 500)
      } else if (status === 'completed') {
        s.isParsing = false
        s.uploadPhase = 'idle'
        s.parsedCount = task.config?.split_files || task.config?.total_entries || 0
        s.parseProgressMsg = '解析完成'
        await project.fetchStages(project.currentProject.id)
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        await loadScreen1Files()
      } else {
        s.isParsing = false
        s.uploadPhase = 'idle'
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        alert(`解析失败: ${task.error_message || '任务执行失败'}`)
      }
    } catch {
      errorCount++
      s.parseProgressMsg = `轮询中... [${pollCount}] (错误${errorCount})`
      if (errorCount < 5) {
        parsePollTimer = setTimeout(poll, 1000)
      } else {
        s.isParsing = false
        s.uploadPhase = 'idle'
      }
    }
  }
  await poll()
}
onMounted(loadScreen1Files)
onUnmounted(() => {
  parsePollGeneration += 1
  clearTimeout(parsePollTimer)
})

async function handleDeleteFile(fileId) {
  if (!confirm('确定删除该文件？')) return
  try {
    await workflowApi.deleteFile(fileId)
    delete reportByFile[fileId]
    if (expandedFileId.value === fileId) expandedFileId.value = null
    await loadScreen1Files()
    await taskStore.fetchActivityLogs(project.currentProject.id)
  } catch (err) {
    alert(err.response?.data?.error || '删除失败')
  }
}
</script>

<style scoped>
/* ── 进度横幅 ── */
.progress-banner {
  border-radius: 10px;
  padding: 12px 16px;
}
.upload-banner {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
}
.parse-banner {
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  color: #6d28d9;
}

/* ── 上传区域 ── */
.upload-zone {
  border: 2px dashed #c7d2fe;
  border-radius: 14px;
  background: #fafbff;
  padding: 24px 20px 16px;
  cursor: pointer;
  transition: border-color .2s, background .2s;
}
.upload-zone:hover:not(.upload-zone--disabled) {
  border-color: #818cf8;
  background: #f5f3ff;
}
.upload-zone--dragover {
  border-color: #6366f1 !important;
  background: #eef2ff !important;
  box-shadow: inset 0 0 0 3px #c7d2fe;
}
.upload-zone--disabled {
  cursor: not-allowed;
  opacity: .75;
}

.upload-zone__top {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.upload-zone__icon {
  font-size: 2rem;
  color: #818cf8;
  line-height: 1;
}
.upload-btn {
  background: linear-gradient(135deg, #3b82f6, #6366f1) !important;
  pointer-events: none;
}
.upload-hint {
  font-size: .8rem;
  color: #94a3b8;
  margin: 0;
}

/* 紧凑格式行 */
.fmt-inline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  justify-content: center;
  padding: 8px 0 4px;
}
.fmt-inline-label {
  font-size: .72rem;
  color: #94a3b8;
  white-space: nowrap;
}
.fmt-inline code {
  display: inline-block;
  padding: 2px 7px;
  background: #eff6ff;
  color: #3b82f6;
  border-radius: 5px;
  font-family: monospace;
  font-size: .72rem;
  border: 1px solid #dbeafe;
}
.fmt-help-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #e0e7ff;
  color: #6366f1;
  border: none;
  cursor: pointer;
  font-size: .7rem;
  transition: background .15s;
  pointer-events: auto;
  flex-shrink: 0;
}
.fmt-help-btn:hover { background: #c7d2fe; }

/* 展开的格式详情面板 */
.fmt-detail-panel {
  margin-top: 8px;
  border-top: 1px solid #e0e7ff;
  padding-top: 10px;
  overflow: hidden;
}
.fmt-slide-enter-active,
.fmt-slide-leave-active {
  transition: max-height .25s ease, opacity .2s;
  max-height: 300px;
}
.fmt-slide-enter-from,
.fmt-slide-leave-to {
  max-height: 0;
  opacity: 0;
}

/* 格式表格 */
.fmt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: .76rem;
}
.fmt-table thead tr { background: #eef2ff; }
.fmt-table th {
  padding: 5px 10px;
  text-align: left;
  color: #4338ca;
  font-weight: 600;
  white-space: nowrap;
}
.fmt-table td {
  padding: 4px 10px;
  color: #475569;
  border-top: 1px solid #f1f5f9;
}
.fmt-table tr:hover td { background: #f8faff; }
.fmt-table code {
  display: inline-block;
  padding: 1px 5px;
  background: #eff6ff;
  color: #2563eb;
  border-radius: 4px;
  font-family: monospace;
  font-size: .72rem;
  margin-right: 2px;
}

/* ── 解析统计与文件级诊断 ── */
.parse-overview {
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}
.parse-overview__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.parse-overview__head h4 { margin: 0; color: #334155; font-size: .9rem; font-weight: 650; }
.parse-overview__head p { margin: 2px 0 0; color: #94a3b8; font-size: .72rem; }
.parse-overview__grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}
.parse-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 10px;
  border-radius: 9px;
  background: #f8fafc;
}
.parse-metric strong { color: #334155; font-size: 1rem; }
.parse-metric span { color: #94a3b8; font-size: .68rem; }
.parse-metric--success { background: #f0fdf4; }
.parse-metric--success strong { color: #15803d; }
.parse-metric--error { background: #fef2f2; }
.parse-metric--error strong { color: #dc2626; }
.parse-metric--warning { background: #fffbeb; }
.parse-metric--warning strong { color: #d97706; }
.parse-health, .parse-badge {
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
  border-radius: 999px;
  font-size: .68rem;
  font-weight: 600;
}
.parse-health { padding: 4px 9px; }
.parse-health--success, .parse-badge--success { color: #15803d; background: #dcfce7; }
.parse-health--warning, .parse-badge--warning { color: #b45309; background: #fef3c7; }
.parse-health--partial, .parse-badge--error { color: #b91c1c; background: #fee2e2; }
.parse-health--failed { color: #991b1b; background: #fecaca; }
.parse-badge--pending { color: #475569; background: #e2e8f0; }
.parse-file-card {
  border: 1px solid #eef2f7;
  border-radius: 9px;
  overflow: hidden;
  background: #fff;
}
.parse-file-row { border: 0; border-radius: 0; }
.parse-file-main {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
}
.parse-file-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.parse-badge { padding: 3px 7px; }
.parse-expand-btn { color: #94a3b8; width: 22px; }
.parse-expand-btn:hover { color: #475569; }
.parse-detail {
  border-top: 1px solid #eef2f7;
  padding: 12px 14px;
  background: #f8fafc;
}
.parse-detail__summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  padding-bottom: 10px;
  color: #64748b;
  font-size: .72rem;
}
.parse-detail__summary strong { color: #334155; }
.parse-issues { display: flex; flex-direction: column; gap: 7px; }
.parse-issue {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 9px 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #e2e8f0;
}
.parse-issue__level {
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 5px;
  font-size: .64rem;
  font-weight: 700;
}
.parse-issue__level--error { color: #b91c1c; background: #fee2e2; }
.parse-issue__level--warning { color: #b45309; background: #fef3c7; }
.parse-issue__body { min-width: 0; font-size: .72rem; line-height: 1.5; }
.parse-issue__location { color: #64748b; font-weight: 600; }
.parse-issue__message { color: #334155; }
.parse-issue__title { color: #64748b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.parse-issue__suggestion { margin-top: 2px; color: #64748b; }
.parse-detail__empty { padding: 8px 0; color: #94a3b8; text-align: center; font-size: .75rem; }
.parse-detail__empty--success { color: #15803d; }

@media (max-width: 760px) {
  .parse-overview__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .parse-file-row { align-items: flex-start; }
  .parse-file-actions { flex-wrap: wrap; justify-content: flex-end; }
}
</style>
