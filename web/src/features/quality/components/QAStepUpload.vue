<template>
  <div class="qa-upload">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#10b981,#059669)">
        <i class="fas fa-upload"></i>
      </div>
      <div>
        <h3 class="step-title">上传文献</h3>
        <p class="step-subtitle">创建待评价文献列表，支持从初筛/复筛导入或直接上传全文文件</p>
      </div>
    </div>

    <!-- 导入方式 Tab -->
    <div class="upload-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="['upload-tab', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key"
      >
        <i :class="tab.icon"></i>
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab 内容 -->
    <div class="upload-panel">
      <!-- 从初筛/复筛导入 -->
      <template v-if="activeTab === 'screening'">
        <div
          class="dropzone dropzone--import"
          @click.stop
        >
          <i class="fas fa-database" style="font-size:2rem;color:#6366f1;margin-bottom:8px"></i>
          <p>将自动导入初筛/复筛阶段中已标记为「纳入」的文献</p>
          <p style="font-size:0.72rem;color:#94a3b8">快速进入质量评价流程，无需手动上传</p>
          <div class="import-inline-actions" @click.stop>
            <select v-model="importStage" class="qa-select">
              <option value="SCREEN_1">从文献初筛导入</option>
              <option value="SCREEN_2">从文献复筛导入</option>
            </select>
            <button class="btn-primary" @click="confirmImport" :disabled="importing">
              <i class="fas fa-download" v-if="!importing"></i>
              <i class="fas fa-spinner fa-spin" v-else></i>
              {{ importing ? '导入中...' : '开始导入' }}
            </button>
          </div>
          <p style="font-size:0.72rem;color:#f59e0b;margin-top:10px" @click.stop>
            <i class="fas fa-exclamation-triangle"></i>
            导入将重置文献列表及所有已有评价记录
          </p>
          <div v-if="importResult" class="import-result" @click.stop>
            <span class="result-ok" v-if="importResult.imported !== undefined">✓ 成功导入 {{ importResult.imported }} 篇最终纳入文献</span>
            <span class="result-err" v-if="importResult.error">✗ {{ importResult.error }}</span>
          </div>
        </div>
      </template>

      <!-- 上传全文文件 -->
      <template v-else-if="activeTab === 'fulltext'">
        <div
          class="dropzone"
          :class="{ 'dropzone--drag': isDragging, 'dropzone--uploading': uploading }"
          @dragover.prevent="isDragging = true"
          @dragleave="isDragging = false"
          @drop.prevent="onDrop"
          @click="!uploading && $refs.fileInput.click()"
        >
          <template v-if="uploading">
            <i class="fas fa-spinner fa-spin" style="font-size:2rem;color:#6366f1;margin-bottom:8px"></i>
            <p style="font-weight:500;color:#6366f1">正在上传 {{ uploadTotal }} 个文件…</p>
            <p style="font-size:0.72rem;color:#94a3b8">请稍候，上传完成后将自动刷新文献列表</p>
          </template>
          <template v-else>
            <i class="fas fa-file-pdf" style="font-size:2rem;color:#e74c3c;margin-bottom:8px"></i>
            <p>拖拽 PDF 文件到此处，或<span class="link-text">点击选择文件</span></p>
            <p style="font-size:0.72rem;color:#94a3b8">单次最多 20 个 PDF；上传后会进行安全校验和文本提取</p>
          </template>
          <input ref="fileInput" type="file" multiple accept=".pdf" style="display:none" @change="onFileSelect" />
        </div>
        <!-- 上传结果提示 -->
        <div v-if="uploadResult" class="upload-result-bar" :class="uploadResult.error ? 'result-err-bar' : 'result-ok-bar'">
          <i :class="uploadResult.error ? 'fas fa-times-circle' : 'fas fa-check-circle'"></i>
          {{ uploadResult.error || `成功上传 ${uploadResult.count} 个文件` }}
        </div>
      </template>

      <!-- 上传题录 -->
      <template v-else-if="activeTab === 'bibliography'">
        <div
          class="dropzone"
          :class="{ 'dropzone--drag': isBibDragging }"
          @dragover.prevent="isBibDragging = true"
          @dragleave="isBibDragging = false"
          @drop.prevent="onBibDrop"
          @click="$refs.bibInput.click()"
        >
          <i class="fas fa-file-alt" style="font-size:2rem;color:#6366f1;margin-bottom:8px"></i>
          <p>拖拽题录文件到此处，或<span class="link-text">点击选择文件</span></p>
          <p style="font-size:0.72rem;color:#94a3b8">支持 .ris / .bib / .txt 格式，系统将解析文献标题、作者、年份等信息</p>
          <input ref="bibInput" type="file" accept=".ris,.bib,.txt,.enw" style="display:none" @change="onBibSelect" />
          <p v-if="bibMessage" class="bib-msg" @click.stop>{{ bibMessage }}</p>
        </div>
      </template>
    </div>

    <!-- 已导入文献列表 -->
    <div v-if="pageData.summary.total" class="ref-list-section">
      <div class="ref-list-header">
        <h4>已导入文献（{{ pageData.summary.total.toLocaleString() }} 篇）</h4>
        <span class="ref-stats">
          全文已有 {{ pageData.summary.fulltext_available }} 篇 ·
          待获取 {{ pageData.summary.fulltext_pending }} 篇
        </span>
      </div>
      <div class="ref-table-wrap">
        <table class="ref-table">
          <thead>
            <tr>
              <th style="width:40px">#</th>
              <th>文献标题</th>
              <th style="min-width:90px">来源</th>
              <th style="min-width:88px">全文状态</th>
              <th style="min-width:90px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(ref, idx) in pageData.results" :key="ref.id">
              <td class="center">{{ (pageData.page - 1) * pageData.page_size + idx + 1 }}</td>
              <td>
                <span class="ref-title-text" :title="ref.title">{{ ref.title }}</span>
              </td>
              <td><span :class="['tag', sourceTagClass(ref.source_type)]">{{ sourceLabel(ref.source_type) }}</span></td>
              <td>
                <span :class="['tag', fulltextTagClass(ref.fulltext_status)]">
                  {{ fulltextLabel(ref) }}
                </span>
                <div v-if="ref.fulltext_asset?.error_message" class="asset-error" :title="ref.fulltext_asset.error_message">
                  {{ ref.fulltext_asset.error_message }}
                </div>
              </td>
              <td>
                <button v-if="ref.fulltext_asset?.status === 'failed'" class="btn-link" @click="retryAsset(ref)">
                  重试处理
                </button>
                <button v-else-if="ref.fulltext_status !== 'available'" class="btn-link" @click="bindFulltext(ref)">
                  绑定全文
                </button>
                <span v-else class="text-success"><i class="fas fa-check"></i> 已有全文</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <QAPagination
        :page="pageData.page"
        :total-pages="pageData.total_pages"
        :total="pageData.count"
        :loading="pageLoading"
        @change="loadPage"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useQAStore } from '@/features/quality/store'
import { useProjectStore } from '@/features/projects/store'
import QAPagination from './QAPagination.vue'

const qa = useQAStore()
const project = useProjectStore()

const activeTab  = ref('screening')
const importStage = ref('SCREEN_1')
const importing  = ref(false)
const importResult = ref(null)
const uploading  = ref(false)
const uploadTotal  = ref(0)
const uploadResult = ref(null)   // { count } | { error }
const isDragging   = ref(false)
const isBibDragging = ref(false)
const bibMessage   = ref('')
let processingPoll = null
const pageLoading = ref(false)
const pageData = ref({
  results: [], count: 0, page: 1, page_size: 30, total_pages: 1,
  summary: { total: 0, fulltext_available: 0, fulltext_pending: 0 },
})

const tabs = [
  { key: 'screening',    label: '从初筛/复筛导入', icon: 'fas fa-database' },
  { key: 'fulltext',     label: '上传全文文件',     icon: 'fas fa-file-pdf' },
  { key: 'bibliography', label: '上传题录',          icon: 'fas fa-file-alt' },
]

async function loadPage(page = pageData.value.page) {
  if (!project.currentProject) return
  pageLoading.value = true
  try {
    pageData.value = await qa.fetchRefPage(project.currentProject.id, { page, page_size: 30 })
  } finally {
    pageLoading.value = false
  }
}

onMounted(async () => {
  await loadPage(1)
  processingPoll = window.setInterval(async () => {
    if (!project.currentProject || pageLoading.value) return
    const hasProcessing = pageData.value.results.some(item =>
      ['pending', 'validating', 'scanning', 'extracting'].includes(item.fulltext_asset?.status)
    )
    if (hasProcessing) await loadPage()
  }, 3000)
})

onUnmounted(() => {
  if (processingPoll) window.clearInterval(processingPoll)
})

async function doImport() {
  importing.value = true
  importResult.value = null
  try {
    const result = await qa.importFromScreening(project.currentProject.id, importStage.value)
    importResult.value = result
    await qa.fetchRefs(project.currentProject.id)
    await loadPage(1)
  } catch (e) {
    importResult.value = { error: e?.response?.data?.error || '导入失败' }
  } finally {
    importing.value = false
  }
}

function confirmImport() {
  if (pageData.value.summary.total > 0) {
    if (!confirm(`当前已有 ${pageData.value.summary.total} 篇文献及相关评价记录。\n导入将清空所有已有数据并重新导入最终纳入文献，是否继续？`)) return
  }
  doImport()
}

function onFileSelect(e) {
  const files = Array.from(e.target.files || [])
  // 重置 input，允许重复选同一文件
  e.target.value = ''
  if (files.length) doUpload(files)
}
function onDrop(e) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer.files || [])
  if (files.length) doUpload(files)
}

async function doUpload(files) {
  if (!files || !files.length) return
  uploading.value = true
  uploadTotal.value = files.length
  uploadResult.value = null
  try {
    await qa.uploadFulltext(project.currentProject.id, files)
    uploadResult.value = { count: files.length }
    await qa.fetchRefs(project.currentProject.id)
    await loadPage(1)
  } catch (e) {
    const detail = e?.response?.data?.error
    uploadResult.value = { error: detail?.message || detail || '上传失败，请重试' }
  } finally {
    uploading.value = false
  }
}

async function retryAsset(ref) {
  try {
    await qa.retryFulltext(ref.fulltext_asset.id)
    await loadPage()
  } catch (e) {
    const detail = e?.response?.data?.error
    uploadResult.value = { error: detail?.message || detail || '重试失败，请稍后再试' }
  }
}

function onBibDrop(e) {
  isBibDragging.value = false
  bibMessage.value = '题录导入功能即将上线，敬请期待'
}
function onBibSelect() { bibMessage.value = '题录导入功能即将上线，敬请期待' }

function bindFulltext(ref) {
  // TODO: 打开文件选择器绑定全文
  alert('绑定全文功能即将上线')
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB'
  return (bytes / 1024 / 1024).toFixed(1) + 'MB'
}

function sourceLabel(t) {
  return { screening_import: '初筛/复筛', bibliography_upload: '题录', fulltext_upload: '全文上传' }[t] || t
}
function sourceTagClass(t) {
  return { screening_import: 'tag-purple', bibliography_upload: 'tag-blue', fulltext_upload: 'tag-green' }[t] || ''
}
function fulltextLabel(ref) {
  const assetStatus = ref.fulltext_asset?.status
  const processing = {
    pending: '等待处理', validating: '正在校验', scanning: '安全扫描中', extracting: '正在提取',
    rejected: '文件被拒绝', failed: '处理失败', ready: '已有全文',
  }
  return processing[assetStatus] || { available: '已有全文', pending: '待获取', missing: '无全文', error: '获取失败' }[ref.fulltext_status] || ref.fulltext_status
}
function fulltextTagClass(s) {
  return { available: 'tag-green', pending: 'tag-orange', missing: 'tag-gray', error: 'tag-red' }[s] || ''
}
</script>

<style scoped>
.qa-upload { display: flex; flex-direction: column; gap: 20px; }
.step-header { display: flex; align-items: center; gap: 12px; }
.step-icon-wrap { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.step-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.step-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }
.upload-tabs { display: flex; gap: 8px; }
.upload-tab { padding: 8px 16px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; cursor: pointer; font-size: 0.82rem; color: #64748b; transition: all 0.15s; display: flex; align-items: center; gap: 6px; }
.upload-tab:hover { border-color: #6366f1; color: #6366f1; }
.upload-tab.active { border-color: #6366f1; background: #eef2ff; color: #6366f1; font-weight: 500; }
.upload-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; }
.import-info { display: flex; align-items: flex-start; gap: 8px; padding: 10px 14px; background: #f0f9ff; border-radius: 8px; font-size: 0.82rem; color: #475569; margin-bottom: 16px; }
.import-actions { display: flex; gap: 10px; align-items: center; }
.dropzone { border: 2px dashed #e2e8f0; border-radius: 12px; padding: 40px 32px; text-align: center; cursor: pointer; transition: all 0.2s; }
.dropzone:hover, .dropzone--drag { border-color: #6366f1; background: #f0f4ff; }
.dropzone p { margin: 4px 0; font-size: 0.85rem; color: #64748b; }

/* 导入型 dropzone：不触发文件选择框，只是容器 */
.dropzone--import { cursor: default; }
.dropzone--import:hover { border-color: #6366f1; background: #f5f3ff; }

/* 导入操作内联区 */
.import-inline-actions { display: flex; gap: 10px; align-items: center; justify-content: center; margin-top: 16px; flex-wrap: wrap; }
.import-result { margin-top: 10px; font-size: 0.82rem; }
.result-ok { color: #10b981; font-weight: 500; }
.result-skip { color: #94a3b8; }
.result-err { color: #ef4444; font-weight: 500; }
.dropzone--uploading { cursor: default; border-color: #6366f1; background: #f0f4ff; }
.upload-result-bar {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 8px; font-size: 0.82rem; font-weight: 500;
  margin-top: 10px;
}
.result-ok-bar { background: #d1fae5; color: #065f46; }
.result-err-bar { background: #fee2e2; color: #991b1b; }
.asset-error { max-width: 160px; margin-top: 3px; color: #ef4444; font-size: 0.68rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #f8fafc; border-radius: 8px; font-size: 0.82rem; }
.queue-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-size { color: #94a3b8; flex-shrink: 0; }
.queue-remove { background: none; border: none; color: #94a3b8; cursor: pointer; padding: 2px 4px; }
.queue-remove:hover { color: #ef4444; }
.ref-list-section { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; }
.ref-list-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid #f1f5f9; }
.ref-list-header h4 { margin: 0; font-size: 0.88rem; font-weight: 600; color: #1e293b; }
.ref-stats { font-size: 0.75rem; color: #64748b; }
.ref-table-wrap { overflow-x: auto; max-height: 340px; overflow-y: auto; }
.ref-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.ref-table th { padding: 8px 12px; background: #f8fafc; color: #64748b; font-weight: 500; text-align: left; border-bottom: 1px solid #e2e8f0; position: sticky; top: 0; }
.ref-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: middle; }
.ref-table tr:last-child td { border-bottom: none; }
.center { text-align: center; }
.ref-title-text { display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; font-weight: 500; }
.tag-green { background: #d1fae5; color: #065f46; }
.tag-blue { background: #dbeafe; color: #1e40af; }
.tag-purple { background: #ede9fe; color: #5b21b6; }
.tag-orange { background: #ffedd5; color: #9a3412; }
.tag-gray { background: #f1f5f9; color: #64748b; }
.tag-red { background: #fee2e2; color: #991b1b; }
.step-footer-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; padding-top: 4px; }
.footer-tip { font-size: 0.78rem; color: #94a3b8; }
.btn-primary { padding: 8px 18px; background: #6366f1; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; transition: background 0.15s; }
.btn-primary:hover:not(:disabled) { background: #4f46e5; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-link { background: none; border: none; color: #6366f1; cursor: pointer; font-size: 0.78rem; padding: 0; text-decoration: underline; }
.text-success { color: #10b981; font-size: 0.78rem; }
.qa-select { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.82rem; background: #fff; }
.bib-msg { font-size: 0.82rem; color: #f59e0b; margin-top: 12px; }
</style>
