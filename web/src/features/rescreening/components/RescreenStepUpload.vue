<template>
  <div class="qa-upload rescreen-upload">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#8b5cf6,#6366f1)">
        <i class="fas fa-upload"></i>
      </div>
      <div>
        <h3 class="step-title">上传/导入文献</h3>
        <p class="step-subtitle">创建复筛文献列表，上传区域与文献质量评价保持一致</p>
      </div>
    </div>

    <div class="upload-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="['upload-tab', { active: activeTab === tab.key, disabled: isTabLocked(tab.key) }]"
        :disabled="isTabLocked(tab.key)"
        :title="isTabLocked(tab.key) ? `当前已选择${selectedUploadModeLabel}，本步骤三种入口只能三选一` : ''"
        @click="activeTab = tab.key"
      >
        <i :class="tab.icon"></i>
        {{ tab.label }}
      </button>
    </div>

    <div class="upload-panel">
      <template v-if="activeTab === 'screening'">
        <div class="dropzone dropzone--import" @click.stop>
          <i class="fas fa-database" style="font-size:2rem;color:#6366f1;margin-bottom:8px"></i>
          <p>将自动导入文献初筛阶段中最终标记为「纳入」的题录文献</p>
          <p style="font-size:0.72rem;color:#94a3b8">导入后保留标题、作者、年份、期刊、DOI/PMID，后续在“全文查找绑定”步骤处理全文</p>
          <div class="import-inline-actions" @click.stop>
            <select v-model="importMode" class="qa-select">
              <option value="included">从文献初筛导入最终纳入文献</option>
            </select>
            <button class="btn-primary" :disabled="importing" @click="confirmImport">
              <i v-if="!importing" class="fas fa-download"></i>
              <i v-else class="fas fa-spinner fa-spin"></i>
              {{ importing ? '导入中...' : '开始导入' }}
            </button>
          </div>
          <p style="font-size:0.72rem;color:#f59e0b;margin-top:10px" @click.stop>
            <i class="fas fa-exclamation-triangle"></i>
            若重复导入，后续接入接口时按 DOI/PMID/标题去重
          </p>
          <div v-if="importResult" class="import-result" @click.stop>
            <span class="result-ok">✓ {{ importResult }}</span>
          </div>
        </div>
      </template>

      <template v-else-if="activeTab === 'fulltext'">
        <div
          :class="['dropzone', { 'dropzone--drag': isDragging, 'dropzone--uploading': uploading }]"
          @click="!uploading && fileInput?.click()"
          @dragover.prevent="isDragging = true"
          @dragleave="isDragging = false"
          @drop.prevent="onPdfDrop"
        >
          <template v-if="uploading">
            <i class="fas fa-spinner fa-spin" style="font-size:2rem;color:#6366f1;margin-bottom:8px"></i>
            <p style="font-weight:500;color:#6366f1">正在上传 PDF 全文包…</p>
            <p style="font-size:0.72rem;color:#94a3b8">上传后系统会尝试解析题名/DOI 并自动绑定到文献记录</p>
          </template>
          <template v-else>
            <i class="fas fa-file-pdf" style="font-size:2rem;color:#e74c3c;margin-bottom:8px"></i>
            <p>拖拽 PDF 文件到此处，或<span class="link-text">点击选择文件</span></p>
            <p style="font-size:0.72rem;color:#94a3b8">支持批量上传；上传后生成复筛文献记录，后续在“全文查找绑定”步骤查看/更改全文</p>
          </template>
          <input ref="fileInput" type="file" multiple accept=".pdf" style="display:none" @change="onPdfSelect" />
        </div>
        <div v-if="uploadResult" :class="['upload-result-bar', uploadResult.type === 'error' ? 'result-err-bar' : 'result-ok-bar']">
          <i :class="uploadResult.type === 'error' ? 'fas fa-times-circle' : 'fas fa-check-circle'"></i>
          {{ uploadResult.text }}
        </div>
      </template>

      <template v-else-if="activeTab === 'bibliography'">
        <div
          :class="['dropzone', { 'dropzone--drag': isBibDragging }]"
          @click="bibInput?.click()"
          @dragover.prevent="isBibDragging = true"
          @dragleave="isBibDragging = false"
          @drop.prevent="onBibDrop"
        >
          <i class="fas fa-file-alt" style="font-size:2rem;color:#6366f1;margin-bottom:8px"></i>
          <p>拖拽题录文件到此处，或<span class="link-text">点击选择文件</span></p>
          <p style="font-size:0.72rem;color:#94a3b8">支持 .ris / .bib / .txt / .enw，解析后后续在“全文查找绑定”步骤处理全文</p>
          <input ref="bibInput" type="file" accept=".ris,.bib,.txt,.enw" style="display:none" @change="onBibSelect" />
          <p v-if="bibMessage" class="bib-msg" @click.stop>{{ bibMessage }}</p>
        </div>
      </template>
    </div>

    <div class="ref-list-section">
      <div class="ref-list-header">
        <h4>复筛文献列表</h4>
        <span class="ref-stats">{{ rescreen.totalRefs ? `共 ${rescreen.totalRefs} 篇` : '上传/导入文献后生成列表' }}</span>
      </div>
      <div v-if="rescreen.totalRefs === 0" class="empty-ref-list">
        <i class="fas fa-inbox"></i>
        <p>暂无复筛文献</p>
        <span>请先从上方三种入口中选择一种：从初筛导入、上传 PDF 全文或上传题录。</span>
      </div>
      <div v-else class="ref-table-wrap">
        <table class="ref-table">
          <thead>
            <tr>
              <th>文献</th>
              <th class="center" style="width:160px">来源</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="paper in rescreen.refs" :key="paper.id">
              <td>
                <div class="ref-title-text">{{ paper.title }}</div>
                <div class="ref-meta">{{ paper.first_author }} · {{ paper.year }} · {{ paper.journal }} · {{ paper.doi || paper.pmid }}</div>
              </td>
              <td class="center"><span class="tag tag-purple">{{ sourceLabel(paper.source_type) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useProjectStore } from '@/features/projects/store'
import { useRescreenStore } from '@/features/rescreening/store'

const project = useProjectStore()
const rescreen = useRescreenStore()
const activeTab = ref('screening')
const importing = ref(false)
const importMode = ref('included')
const importResult = ref('')
const uploading = ref(false)
const uploadResult = ref(null)
const isDragging = ref(false)
const isBibDragging = ref(false)
const bibMessage = ref('')
const fileInput = ref(null)
const bibInput = ref(null)

const tabs = [
  { key: 'screening', label: '从初筛导入', icon: 'fas fa-database' },
  { key: 'fulltext', label: '上传 PDF 全文', icon: 'fas fa-file-pdf' },
  { key: 'bibliography', label: '上传题录', icon: 'fas fa-file-alt' },
]

const sourceToTab = {
  screening_import: 'screening',
  pdf_upload: 'fulltext',
  bibliography_upload: 'bibliography',
}
const selectedUploadMode = computed(() => {
  const firstSource = rescreen.refs[0]?.source_type
  return firstSource ? sourceToTab[firstSource] || '' : ''
})
const selectedUploadModeLabel = computed(() => tabs.find(tab => tab.key === selectedUploadMode.value)?.label || '当前入口')

watch(selectedUploadMode, (mode) => {
  if (mode) activeTab.value = mode
}, { immediate: true })

function isTabLocked(tabKey) {
  return Boolean(selectedUploadMode.value && selectedUploadMode.value !== tabKey)
}

function currentProjectId() {
  return project.currentProject?.id
}
function getErrorText(error, fallback) {
  return error?.response?.data?.error || error?.message || fallback
}
function sourceLabel(value) {
  return { screening_import: '初筛导入', bibliography_upload: '题录上传', pdf_upload: 'PDF 上传' }[value] || value
}
async function confirmImport() {
  importing.value = true
  importResult.value = ''
  try {
    const result = await rescreen.importFromScreening(currentProjectId())
    importResult.value = `成功导入初筛最终纳入文献 ${result.imported || 0} 篇`
  } catch (error) {
    importResult.value = getErrorText(error, '从初筛导入失败')
  } finally {
    importing.value = false
  }
}
async function finishPdfUpload(files) {
  const fileList = Array.from(files || [])
  if (!fileList.length) return
  uploading.value = true
  uploadResult.value = null
  try {
    const result = await rescreen.uploadFulltextFiles(currentProjectId(), fileList)
    uploadResult.value = { type: 'ok', text: `成功上传 ${result.created || fileList.length} 个 PDF，已生成复筛文献记录` }
  } catch (error) {
    uploadResult.value = { type: 'error', text: getErrorText(error, 'PDF 上传失败') }
  } finally {
    uploading.value = false
  }
}
function onPdfSelect(event) {
  finishPdfUpload(event.target.files)
  event.target.value = ''
}
function onPdfDrop(event) {
  isDragging.value = false
  finishPdfUpload(event.dataTransfer.files)
}
async function finishBibUpload(file) {
  if (!file) return
  bibMessage.value = '题录解析中…'
  try {
    const result = await rescreen.uploadBibliographyFile(currentProjectId(), file)
    bibMessage.value = `✓ 题录解析完成，已生成 ${result.created || 0} 条复筛文献记录；后续在“全文查找绑定”步骤处理全文`
  } catch (error) {
    bibMessage.value = getErrorText(error, '题录解析失败')
  }
}
function onBibSelect(event) {
  finishBibUpload(event.target.files?.[0])
  event.target.value = ''
}
function onBibDrop(event) {
  isBibDragging.value = false
  finishBibUpload(event.dataTransfer.files?.[0])
}
</script>

<style scoped>
.qa-upload { display:flex; flex-direction:column; gap:14px; }
.step-header { display:flex; align-items:center; gap:12px; padding:14px 16px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; }
.step-icon-wrap { width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center; color:#fff; flex-shrink:0; }
.step-title { font-size:1rem; font-weight:600; color:#1e293b; margin:0; }
.step-subtitle { font-size:.75rem; color:#64748b; margin:0; }
.upload-tabs { display:flex; gap:8px; }
.upload-tab { padding:8px 16px; border:1px solid #e2e8f0; border-radius:8px; background:#fff; cursor:pointer; font-size:.82rem; color:#64748b; transition:all .15s; display:flex; align-items:center; gap:6px; }
.upload-tab:hover { border-color:#6366f1; color:#6366f1; }
.upload-tab.active { border-color:#6366f1; background:#eef2ff; color:#6366f1; font-weight:500; }
.upload-panel { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:20px; }
.dropzone { border:2px dashed #e2e8f0; border-radius:12px; padding:40px 32px; text-align:center; cursor:pointer; transition:all .2s; }
.dropzone:hover,.dropzone--drag { border-color:#6366f1; background:#f0f4ff; }
.dropzone p { margin:4px 0; font-size:.85rem; color:#64748b; }
.dropzone--import { cursor:default; }
.dropzone--import:hover { border-color:#6366f1; background:#f5f3ff; }
.dropzone--uploading { cursor:default; border-color:#6366f1; background:#f0f4ff; }
.link-text { color:#6366f1; font-weight:600; }
.import-inline-actions { display:flex; gap:10px; align-items:center; justify-content:center; margin-top:16px; flex-wrap:wrap; }
.import-result { margin-top:10px; font-size:.82rem; }
.result-ok { color:#10b981; font-weight:500; }
.upload-result-bar { display:flex; align-items:center; gap:6px; padding:8px 14px; border-radius:8px; font-size:.82rem; font-weight:500; margin-top:10px; }
.result-ok-bar { background:#d1fae5; color:#065f46; }
.result-err-bar { background:#fee2e2; color:#991b1b; }
.ref-list-section { background:#fff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; }
.ref-list-header { display:flex; justify-content:space-between; align-items:center; padding:14px 16px; border-bottom:1px solid #f1f5f9; }
.ref-list-header h4 { margin:0; font-size:.88rem; font-weight:600; color:#1e293b; }
.ref-stats { font-size:.75rem; color:#64748b; }
.ref-table-wrap { overflow-x:auto; max-height:340px; overflow-y:auto; }
.ref-table { width:100%; border-collapse:collapse; font-size:.8rem; }
.ref-table th { padding:8px 12px; background:#f8fafc; color:#64748b; font-weight:500; text-align:left; border-bottom:1px solid #e2e8f0; position:sticky; top:0; }
.ref-table td { padding:8px 12px; border-bottom:1px solid #f1f5f9; color:#334155; vertical-align:middle; }
.center { text-align:center!important; }
.ref-title-text { display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical; overflow:hidden; font-weight:600; color:#334155; }
.ref-meta { font-size:.72rem; color:#94a3b8; margin-top:3px; }
.tag { display:inline-block; padding:2px 8px; border-radius:4px; font-size:.72rem; font-weight:500; }
.tag-green { background:#d1fae5; color:#065f46; }
.tag-purple { background:#ede9fe; color:#5b21b6; }
.tag-gray { background:#f1f5f9; color:#64748b; }
.tag-red { background:#fee2e2; color:#991b1b; }
.btn-primary { padding:8px 18px; background:#6366f1; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:.85rem; display:flex; align-items:center; gap:6px; transition:background .15s; }
.btn-primary:hover:not(:disabled) { background:#4f46e5; }
.btn-primary:disabled { opacity:.5; cursor:not-allowed; }
.btn-link { background:none; border:none; color:#6366f1; cursor:pointer; font-size:.78rem; padding:0 4px; text-decoration:underline; }
.qa-select { padding:7px 10px; border:1px solid #e2e8f0; border-radius:8px; font-size:.82rem; background:#fff; }
.bib-msg { font-size:.82rem!important; color:#10b981!important; margin-top:12px!important; font-weight:500; }
</style>
