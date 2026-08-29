<template>
  <div class="pdf-viewer">
    <div class="viewer-toolbar">
      <span class="viewer-title">
        <i class="fas fa-file-pdf" style="color:#e74c3c"></i>
        {{ filename }}
      </span>
      <div class="toolbar-actions">
        <button class="tb-btn" @click="zoomOut" :disabled="scale <= 0.5"><i class="fas fa-search-minus"></i></button>
        <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
        <button class="tb-btn" @click="zoomIn" :disabled="scale >= 3"><i class="fas fa-search-plus"></i></button>
        <button class="tb-btn" @click="prevPage" :disabled="currentPage <= 1"><i class="fas fa-chevron-left"></i></button>
        <span class="page-label">{{ currentPage }} / {{ totalPages }}</span>
        <button class="tb-btn" @click="nextPage" :disabled="currentPage >= totalPages"><i class="fas fa-chevron-right"></i></button>
        <a :href="pdfUrl" target="_blank" class="tb-btn" title="新窗口打开">
          <i class="fas fa-external-link-alt"></i>
        </a>
      </div>
    </div>

    <div class="viewer-body" ref="containerRef">
      <div v-if="loading" class="loading-state">
        <i class="fas fa-spinner fa-spin"></i>
        加载中...
      </div>
      <div v-else-if="error" class="error-state">
        <i class="fas fa-exclamation-triangle"></i>
        <p>{{ error }}</p>
        <a :href="pdfUrl" target="_blank" class="fallback-link">点此直接下载 PDF</a>
      </div>
      <div v-else class="canvas-wrap" :style="{ transform: `scale(${scale})`, transformOrigin: 'top center' }">
        <canvas ref="canvasRef"></canvas>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  pdfUrl:   { type: String, required: true },
  filename: { type: String, default: 'document.pdf' },
})

const containerRef = ref(null)
const canvasRef    = ref(null)
const loading      = ref(true)
const error        = ref('')
const currentPage  = ref(1)
const totalPages   = ref(0)
const scale        = ref(1.2)

let pdfDoc   = null
let renderTask = null

watch(() => props.pdfUrl, (url) => {
  if (url) loadPdf(url)
})

onMounted(() => {
  if (props.pdfUrl) loadPdf(props.pdfUrl)
})

onUnmounted(() => {
  if (renderTask) renderTask.cancel()
})

async function loadPdf(url) {
  loading.value = true
  error.value   = ''
  currentPage.value = 1

  try {
    // 动态加载 pdfjs-dist（如未安装则走降级）
    const pdfjsLib = await import('pdfjs-dist/build/pdf').catch(() => null)
    if (!pdfjsLib) {
      throw new Error('pdfjs-dist 未安装，无法在线预览 PDF')
    }
    // 设置 worker
    if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
      pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js'
    }
    pdfDoc = await pdfjsLib.getDocument({ url }).promise
    totalPages.value = pdfDoc.numPages
    loading.value = false
    await nextTick()
    await renderPage(currentPage.value)
  } catch (e) {
    loading.value = false
    error.value = e.message || 'PDF 加载失败'
  }
}

async function renderPage(pageNum) {
  if (!pdfDoc || !canvasRef.value) return
  if (renderTask) renderTask.cancel()

  const page = await pdfDoc.getPage(pageNum)
  const viewport = page.getViewport({ scale: 1.5 })
  const canvas   = canvasRef.value
  const ctx      = canvas.getContext('2d')

  canvas.height = viewport.height
  canvas.width  = viewport.width

  renderTask = page.render({ canvasContext: ctx, viewport })
  await renderTask.promise.catch(() => {}) // 取消时静默
}

function prevPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    renderPage(currentPage.value)
  }
}
function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    renderPage(currentPage.value)
  }
}
function zoomIn()  { scale.value = Math.min(3, +(scale.value + 0.25).toFixed(2)) }
function zoomOut() { scale.value = Math.max(0.5, +(scale.value - 0.25).toFixed(2)) }
</script>

<style scoped>
.pdf-viewer { display: flex; flex-direction: column; height: 100%; background: #1e1e2e; border-radius: 12px; overflow: hidden; }
.viewer-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 8px 14px; background: #2d2d44; border-bottom: 1px solid #3d3d5c; }
.viewer-title { font-size: 0.78rem; color: #c4c4d4; display: flex; align-items: center; gap: 6px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toolbar-actions { display: flex; align-items: center; gap: 4px; }
.tb-btn { padding: 4px 8px; background: #3d3d5c; border: none; color: #c4c4d4; border-radius: 5px; cursor: pointer; font-size: 0.75rem; transition: background 0.12s; text-decoration: none; }
.tb-btn:hover:not(:disabled) { background: #5353a0; color: #fff; }
.tb-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.zoom-label, .page-label { font-size: 0.72rem; color: #94a3b8; padding: 0 4px; min-width: 36px; text-align: center; }
.viewer-body { flex: 1; overflow: auto; display: flex; align-items: flex-start; justify-content: center; padding: 16px; }
.loading-state, .error-state { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #94a3b8; font-size: 0.85rem; padding: 60px; }
.error-state i { font-size: 2rem; color: #f87171; }
.error-state p { margin: 0; }
.fallback-link { color: #818cf8; font-size: 0.8rem; }
.canvas-wrap { transition: transform 0.1s; }
.canvas-wrap canvas { display: block; box-shadow: 0 4px 24px rgba(0,0,0,.5); border-radius: 4px; }
</style>
