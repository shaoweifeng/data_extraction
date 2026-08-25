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
          <button class="fmt-help-btn" @click.stop="showFmtDetail = !showFmtDetail" :title="showFmtDetail ? '收起' : '查看格式说明'">
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
            class="step-list-item"
          >
            <div class="flex items-center overflow-hidden gap-2">
              <i class="fas fa-bookmark text-blue-400 flex-shrink-0"></i>
              <span class="truncate text-sm text-gray-700">{{ file.filename }}</span>
            </div>
            <div class="flex items-center gap-3 flex-shrink-0">
              <a :href="file.file" class="text-blue-400 hover:text-blue-600 transition">
                <i class="fas fa-download text-sm"></i>
              </a>
              <button @click="handleDeleteFile(file.id)" class="text-gray-300 hover:text-red-400 transition">
                <i class="fas fa-trash text-sm"></i>
              </button>
            </div>
          </div>
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
const fileInput = ref(null)
const showFmtDetail = ref(false)
const isDragOver = ref(false)

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
function getCsrf() {
  return document.cookie.split('; ').find((r) => r.startsWith('csrftoken='))?.split('=')[1]
}
function uploadFileXHR(file, index) {
  return new Promise((resolve, reject) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('filename', file.name)
    formData.append('project', project.currentProject.id)
    formData.append('data_category', 'input')
    s.uploadCurrentFile = file.name
    s.uploadFileIndex = index
    s.uploadProgress = 0
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/files/')
    xhr.setRequestHeader('X-CSRFToken', getCsrf() || '')
    xhr.withCredentials = true
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        s.uploadProgress = Math.round((e.loaded / e.total) * 100)
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) }
        catch { reject(new Error('响应解析失败')) }
      } else {
        try {
          const d = JSON.parse(xhr.responseText)
          reject(new Error(d.error || `上传失败 (${xhr.status})`))
        } catch { reject(new Error(`上传失败 (${xhr.status})`)) }
      }
    }
    xhr.onerror = () => reject(new Error('网络错误'))
    xhr.send(formData)
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
    const res = await http.get(`/files/?project=${project.currentProject.id}&data_category=input`)
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
    const res = await httpNoTimeout.post('/tasks/', {
      project: project.currentProject.id,
      task_type: 'parse',
      config: { file_ids: fileIds },
    })
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
  let pollCount = 0
  let errorCount = 0
  const poll = async () => {
    pollCount++
    try {
      const res = await http.get(`/tasks/${taskId}/`)
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
        setTimeout(poll, 500)
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
    } catch (err) {
      errorCount++
      s.parseProgressMsg = `轮询中... [${pollCount}] (错误${errorCount})`
      if (errorCount < 5) {
        setTimeout(poll, 1000)
      } else {
        s.isParsing = false
        s.uploadPhase = 'idle'
      }
    }
  }
  await poll()
}
onMounted(loadScreen1Files)

async function handleDeleteFile(fileId) {
  if (!confirm('确定删除该文件？')) return
  try {
    await http.delete(`/files/${fileId}/`)
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
</style>
