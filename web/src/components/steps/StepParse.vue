<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#3b82f6,#6366f1)">
        <i class="fas fa-file-import"></i>
      </div>
      <div>
        <h3 class="step-title">导入文献索引</h3>
        <p class="step-subtitle">上传 RIS / BibTeX / NBIB / TXT 格式的文献文件</p>
      </div>
    </div>

    <!-- 上传/解析进度区域 -->
    <div
      v-if="s.uploadPhase !== 'idle'"
      class="mb-4"
      :style="s.uploadPhase === 'uploading'
        ? 'background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:12px 16px'
        : 'background:#f5f3ff;border:1px solid #ddd6fe;border-radius:12px;padding:12px 16px'"
    >
      <div class="flex items-center gap-2 mb-2">
        <i
          class="fas fa-spinner fa-spin"
          :class="s.uploadPhase === 'uploading' ? 'text-blue-500' : 'text-indigo-500'"
        ></i>
        <span
          class="font-medium text-sm"
          :class="s.uploadPhase === 'uploading' ? 'text-blue-700' : 'text-indigo-700'"
        >
          <template v-if="s.uploadPhase === 'uploading'">
            正在上传文件 ({{ s.uploadFileIndex }}/{{ s.uploadTotalFiles }})：{{ s.uploadCurrentFile }}
          </template>
          <template v-else>
            {{ s.parseProgressMsg || '正在启动解析...' }}
          </template>
        </span>
      </div>
      <!-- 进度条 -->
      <div class="progress-bar-track" style="height:6px">
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
      <div
        class="flex justify-between text-xs mt-1"
        :class="s.uploadPhase === 'uploading' ? 'text-blue-500' : 'text-indigo-500'"
      >
        <span v-if="s.uploadPhase === 'uploading'">{{ s.uploadProgress }}%</span>
        <span v-else-if="s.parseProgressTotal > 0">{{ s.parseProgressCurrent }}%</span>
        <span v-else>解析中...</span>
      </div>
    </div>

    <!-- 上传区域 -->
    <div
      class="step-upload-zone"
      @click="s.isParsing || s.uploadPhase !== 'idle' ? null : fileInput?.click()"
    >
      <input
        ref="fileInput"
        type="file"
        class="hidden"
        multiple
        accept=".ris,.bib,.nbib,.xml,.ciw,.enw,.txt,.doc,.docx"
        @change="handleUpload"
      />
      <div class="mb-3 text-blue-400" style="font-size:2rem">
        <i class="fas fa-cloud-upload-alt"></i>
      </div>
      <button
        :disabled="s.isParsing || s.uploadPhase !== 'idle'"
        class="btn-primary"
        style="background:linear-gradient(135deg,#3b82f6,#6366f1)"
      >
        <i v-if="s.isParsing || s.uploadPhase !== 'idle'" class="fas fa-spinner fa-spin"></i>
        <i v-else class="fas fa-upload"></i>
        {{ s.uploadPhase === 'uploading' ? '上传中...' : s.isParsing ? '正在解析...' : '上传 Reference 文件' }}
      </button>
      <p class="mt-3 text-sm text-gray-400">点击或拖拽文件到此处（支持 .ris .bib .nbib .txt 等）</p>
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
  event.target.value = ''
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
