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
      class="mb-4 rounded-xl border overflow-hidden"
      :class="s.uploadPhase === 'uploading' ? 'bg-blue-50 border-blue-200' : 'bg-indigo-50 border-indigo-200'"
    >
      <div class="px-4 pt-3 pb-1 flex items-center gap-2">
        <i
          class="fas fa-spinner fa-spin text-lg"
          :class="s.uploadPhase === 'uploading' ? 'text-blue-600' : 'text-indigo-600'"
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
      <div class="px-4 pb-3">
        <div
          class="w-full bg-white rounded-full h-3 border overflow-hidden"
          :class="s.uploadPhase === 'uploading' ? 'border-blue-200' : 'border-indigo-200'"
        >
          <div
            v-if="s.uploadPhase === 'uploading'"
            class="h-3 rounded-full bg-blue-500 transition-all duration-300"
            :style="{ width: s.uploadProgress + '%' }"
          ></div>
          <div
            v-else-if="s.parseProgressTotal > 0"
            class="h-3 rounded-full bg-indigo-500 transition-all duration-300"
            :style="{ width: s.parseProgressCurrent + '%' }"
          ></div>
          <div v-else class="h-3 rounded-full bg-indigo-400 animate-pulse" style="width: 40%"></div>
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
    </div>

    <!-- 上传区域 -->
    <div
      class="border-2 border-dashed border-blue-200 rounded-xl p-10 hover:bg-blue-50 transition cursor-pointer text-center"
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
      <button
        :disabled="s.isParsing || s.uploadPhase !== 'idle'"
        class="bg-blue-600 text-white px-8 py-3 rounded-lg font-medium shadow-lg hover:bg-blue-700 disabled:opacity-50 transition"
      >
        <i v-if="s.isParsing || s.uploadPhase !== 'idle'" class="fas fa-spinner fa-spin mr-2"></i>
        <i v-else class="fas fa-upload mr-2"></i>
        {{ s.uploadPhase === 'uploading' ? '上传中...' : s.isParsing ? '正在解析...' : '上传 Reference 文件' }}
      </button>
      <p class="mt-4 text-sm text-gray-400">点击或拖拽文件到此处（上传后自动解析）</p>
    </div>

    <!-- 已导入文件列表 -->
    <div class="mt-6 text-left">
      <h4 class="font-semibold text-gray-700 mb-2">
        已导入的索引
        <span v-if="s.parsedCount > 0 && !s.isParsing" class="text-sm text-green-600 ml-2">
          · 已解析 {{ s.parsedCount }} 条文献
        </span>
      </h4>
      <div class="bg-gray-50 rounded-xl border p-4 max-h-64 overflow-y-auto">
        <div v-if="s.referenceFiles.length === 0" class="text-gray-400 text-sm text-center py-4">
          暂无已导入的索引
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="file in s.referenceFiles"
            :key="file.id"
            class="flex items-center justify-between bg-white p-3 rounded border"
          >
            <div class="flex items-center overflow-hidden">
              <i class="fas fa-bookmark text-blue-500 mr-2"></i>
              <span class="truncate">{{ file.filename }}</span>
            </div>
            <div class="space-x-3 flex-shrink-0">
              <a :href="file.file" class="text-blue-600 hover:text-blue-800">
                <i class="fas fa-download"></i>
              </a>
              <button @click="handleDeleteFile(file.id)" class="text-gray-300 hover:text-red-500">
                <i class="fas fa-trash"></i>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useScreeningStore } from '@/stores/screening'
import { useProjectStore } from '@/stores/project'
import { useTaskStore } from '@/stores/task'
import http, { httpNoTimeout } from '@/api/http'
import { extractListData } from '@/utils/format'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const fileInput = ref(null)

// ── 文件上传逻辑（XHR，支持 progress 回调）──────────────────────────────
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

  // 清空 input，支持重复选同一文件
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
  s.parseProgressCurrent = 0
  s.parseProgressTotal = 0
  s.parseProgressMsg = '正在启动解析任务...'
  try {
    const res = await httpNoTimeout.post('/tasks/', {
      project: project.currentProject.id,
      task_type: 'reference_parsing',
      config: { file_ids: fileIds },
    })
    const task = res.data
    s.parseProgressMsg = '解析任务已启动，正在处理文件...'
    pollParsingStatus(task.id)
  } catch (err) {
    alert(`启动解析任务失败: ${err.response?.data?.error || err.message}`)
    s.isParsing = false
    s.uploadPhase = 'idle'
  }
}

async function pollParsingStatus(taskId) {
  let errorCount = 0
  const MAX_ERRORS = 5
  let pollCount = 0

  const poll = async () => {
    pollCount++
    try {
      const res = await http.get(`/tasks/${taskId}/`)
      const task = res.data
      const status = task.status
      errorCount = 0

      if (task.config) {
        s.parsedCount = task.config.total_entries || task.config.split_files || 0
        const pp = task.config.parse_progress
        if (pp) {
          s.parseProgressCurrent = pp.current || 0
          s.parseProgressTotal = pp.total || 0
          s.parseProgressMsg = pp.message || ''
        }
      }

      if (status === 'running' || status === 'pending') {
        setTimeout(poll, 500)
      } else {
        s.isParsing = false
        s.uploadPhase = 'idle'
        await project.fetchStages(project.currentProject.id)
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        await taskStore.fetchActivityLogs(project.currentProject.id)
        if (status === 'completed') {
          s.parsedCount = task.config?.split_files || task.config?.total_entries || 0
        } else {
          alert(`文献解析失败: ${task.error_message || '任务执行失败'}`)
        }
      }
    } catch (err) {
      errorCount++
      s.parseProgressMsg = `轮询中... [${pollCount}] (错误${errorCount})`
      if (errorCount < MAX_ERRORS) {
        setTimeout(poll, 1000)
      } else {
        s.isParsing = false
        s.uploadPhase = 'idle'
      }
    }
  }
  await poll()
}

async function handleDeleteFile(fileId) {
  if (!confirm('确定删除该文件？')) return
  try {
    await http.delete(`/files/${fileId}/`)
    await loadScreen1Files()
    await project.fetchStages(project.currentProject.id)
    await taskStore.fetchActivityLogs(project.currentProject.id)
  } catch (err) {
    alert(`删除失败: ${err.response?.data?.error || err.message}`)
  }
}

// 组件挂载时加载文件列表
import { onMounted } from 'vue'
onMounted(() => loadScreen1Files())
</script>
