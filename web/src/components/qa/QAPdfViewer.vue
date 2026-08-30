<template>
  <div class="pdf-viewer">
    <div class="viewer-toolbar">
      <span class="viewer-title">
        <i class="fas fa-file-pdf" style="color:#e74c3c"></i>
        {{ filename }}
      </span>
      <div class="toolbar-actions">
        <a :href="pdfUrl" target="_blank" class="tb-btn" title="新窗口打开">
          <i class="fas fa-external-link-alt"></i> 新窗口打开
        </a>
        <a :href="pdfUrl" download class="tb-btn" title="下载 PDF">
          <i class="fas fa-download"></i> 下载
        </a>
      </div>
    </div>
    <div class="viewer-body">
      <!-- 加载中 -->
      <div v-if="loading" class="empty-state">
        <i class="fas fa-spinner fa-spin" style="font-size:2rem;color:#6366f1"></i>
        <p>加载 PDF 中…</p>
      </div>
      <!-- 加载失败 -->
      <div v-else-if="error" class="empty-state">
        <i class="fas fa-exclamation-circle" style="font-size:2rem;color:#dc2626"></i>
        <p>{{ error }}</p>
        <a :href="pdfUrl" target="_blank" class="tb-btn" style="margin-top:8px">
          <i class="fas fa-external-link-alt"></i> 在新窗口打开
        </a>
      </div>
      <!-- Blob URL iframe，避免 Electron 里 Chrome PDF 插件的内部请求被拒 -->
      <iframe
        v-else-if="blobUrl"
        :src="blobUrl"
        class="pdf-iframe"
        frameborder="0"
      ></iframe>
      <!-- 无文件 -->
      <div v-else class="empty-state">
        <i class="fas fa-file-pdf"></i>
        <p>暂无全文文件</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'

const props = defineProps({
  pdfUrl:   { type: String, default: '' },
  filename: { type: String, default: 'document.pdf' },
})

const blobUrl = ref('')
const loading = ref(false)
const error   = ref('')

let currentBlobUrl = ''

function revokeCurrent() {
  if (currentBlobUrl) {
    URL.revokeObjectURL(currentBlobUrl)
    currentBlobUrl = ''
  }
}

async function loadPdf(url) {
  if (!url) {
    revokeCurrent()
    blobUrl.value = ''
    return
  }
  loading.value = true
  error.value   = ''
  revokeCurrent()
  blobUrl.value = ''

  try {
    const resp = await fetch(url, { credentials: 'include' })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const objectUrl = URL.createObjectURL(blob)
    currentBlobUrl = objectUrl
    blobUrl.value  = objectUrl
  } catch (e) {
    error.value = `PDF 加载失败：${e.message}，请尝试「新窗口打开」`
  } finally {
    loading.value = false
  }
}

watch(() => props.pdfUrl, (url) => loadPdf(url), { immediate: true })

onUnmounted(() => revokeCurrent())
</script>

<style scoped>
.pdf-viewer { display: flex; flex-direction: column; height: 100%; background: #1e1e2e; border-radius: 12px; overflow: hidden; }
.viewer-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 8px 14px; background: #2d2d44; border-bottom: 1px solid #3d3d5c; flex-shrink: 0; }
.viewer-title { font-size: 0.78rem; color: #c4c4d4; display: flex; align-items: center; gap: 6px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toolbar-actions { display: flex; align-items: center; gap: 6px; }
.tb-btn { padding: 5px 10px; background: #3d3d5c; border: none; color: #c4c4d4; border-radius: 5px; cursor: pointer; font-size: 0.75rem; transition: background 0.12s; text-decoration: none; display: flex; align-items: center; gap: 4px; }
.tb-btn:hover { background: #5353a0; color: #fff; }
.viewer-body { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
.pdf-iframe { width: 100%; height: 100%; border: none; background: #fff; flex: 1; }
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; height: 100%; color: #94a3b8; font-size: 0.85rem; text-align: center; padding: 20px; }
.empty-state i { font-size: 2.5rem; color: #475569; }
</style>
