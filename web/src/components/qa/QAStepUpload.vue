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
        <div class="import-info">
          <i class="fas fa-info-circle" style="color:#6366f1"></i>
          <span>将自动导入文献初筛阶段中已标记为「纳入」的文献，快速进入质量评价流程。</span>
        </div>
        <div class="import-actions">
          <select v-model="importStage" class="qa-select" style="width:200px">
            <option value="SCREEN_1">从文献初筛导入</option>
            <option value="SCREEN_2">从文献复筛导入</option>
          </select>
          <button class="btn-primary" @click="doImport" :disabled="importing">
            <i class="fas fa-download" v-if="!importing"></i>
            <i class="fas fa-spinner fa-spin" v-else></i>
            {{ importing ? '导入中...' : '开始导入' }}
          </button>
        </div>
        <div v-if="importResult" class="import-result">
          <span class="result-ok">✓ 成功导入 {{ importResult.imported }} 篇</span>
          <span v-if="importResult.skipped" class="result-skip">，跳过重复 {{ importResult.skipped }} 篇</span>
        </div>
      </template>

      <!-- 上传全文文件 -->
      <template v-else-if="activeTab === 'fulltext'">
        <div
          class="dropzone"
          :class="{ 'dropzone--drag': isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave="isDragging = false"
          @drop.prevent="onDrop"
          @click="$refs.fileInput.click()"
        >
          <i class="fas fa-file-pdf" style="font-size:2rem;color:#e74c3c;margin-bottom:8px"></i>
          <p>拖拽 PDF 文件到此处，或<span class="link-text">点击选择文件</span></p>
          <p style="font-size:0.72rem;color:#94a3b8">支持批量上传，每个 PDF 自动识别为一篇文献</p>
          <input ref="fileInput" type="file" multiple accept=".pdf" style="display:none" @change="onFileSelect" />
        </div>

        <!-- 上传队列 -->
        <div v-if="uploadQueue.length" class="upload-queue">
          <div v-for="(f, i) in uploadQueue" :key="i" class="queue-item">
            <i class="fas fa-file-pdf" style="color:#e74c3c"></i>
            <span class="queue-name">{{ f.name }}</span>
            <span class="queue-size">{{ formatSize(f.size) }}</span>
            <button class="queue-remove" @click="uploadQueue.splice(i, 1)">
              <i class="fas fa-times"></i>
            </button>
          </div>
          <button class="btn-primary" @click="doUpload" :disabled="uploading">
            <i class="fas fa-upload" v-if="!uploading"></i>
            <i class="fas fa-spinner fa-spin" v-else></i>
            {{ uploading ? `上传中 (${uploadedCount}/${uploadQueue.length})...` : `上传 ${uploadQueue.length} 个文件` }}
          </button>
        </div>
      </template>

      <!-- 上传题录（简化版：暂仅提示） -->
      <template v-else-if="activeTab === 'bibliography'">
        <div class="import-info">
          <i class="fas fa-info-circle" style="color:#f59e0b"></i>
          <span>支持 RIS / BibTeX / EndNote 格式题录文件，系统将解析文献标题、作者、年份等信息。</span>
        </div>
        <div
          class="dropzone"
          @dragover.prevent @drop.prevent="onBibDrop"
          @click="$refs.bibInput.click()"
        >
          <i class="fas fa-file-alt" style="font-size:2rem;color:#6366f1;margin-bottom:8px"></i>
          <p>拖拽题录文件到此处，或<span class="link-text">点击选择文件</span></p>
          <p style="font-size:0.72rem;color:#94a3b8">支持 .ris / .bib / .txt 格式</p>
          <input ref="bibInput" type="file" accept=".ris,.bib,.txt,.enw" style="display:none" @change="onBibSelect" />
        </div>
        <p v-if="bibMessage" class="bib-msg">{{ bibMessage }}</p>
      </template>
    </div>

    <!-- 已导入文献列表 -->
    <div v-if="qa.refs.length" class="ref-list-section">
      <div class="ref-list-header">
        <h4>已导入文献（{{ qa.refs.length }} 篇）</h4>
        <span class="ref-stats">
          全文已有 {{ fulltextAvailable }} 篇 ·
          待获取 {{ fulltextPending }} 篇
        </span>
      </div>
      <div class="ref-table-wrap">
        <table class="ref-table">
          <thead>
            <tr>
              <th style="width:40px">#</th>
              <th>文献标题</th>
              <th>来源</th>
              <th>全文状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(ref, idx) in qa.refs" :key="ref.id">
              <td class="center">{{ idx + 1 }}</td>
              <td>
                <span class="ref-title-text" :title="ref.title">{{ ref.title }}</span>
              </td>
              <td><span :class="['tag', sourceTagClass(ref.source_type)]">{{ sourceLabel(ref.source_type) }}</span></td>
              <td>
                <span :class="['tag', fulltextTagClass(ref.fulltext_status)]">
                  {{ fulltextLabel(ref.fulltext_status) }}
                </span>
              </td>
              <td>
                <button v-if="ref.fulltext_status !== 'available'" class="btn-link" @click="bindFulltext(ref)">
                  绑定全文
                </button>
                <span v-else class="text-success"><i class="fas fa-check"></i> 已有全文</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 底部操作 -->
    <div class="step-footer-actions">
      <span class="footer-tip" v-if="!qa.refs.length">请先导入文献</span>
      <span class="footer-tip" v-else>已导入 {{ qa.refs.length }} 篇文献，可继续下一步</span>
      <button class="btn-primary" :disabled="!qa.refs.length" @click="qa.currentStep = 2">
        下一步：选择评价方法 <i class="fas fa-arrow-right"></i>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQAStore } from '@/stores/qa'
import { useProjectStore } from '@/stores/project'

const qa = useQAStore()
const project = useProjectStore()

const activeTab  = ref('screening')
const importStage = ref('SCREEN_1')
const importing  = ref(false)
const importResult = ref(null)
const uploading  = ref(false)
const uploadedCount = ref(0)
const uploadQueue  = ref([])
const isDragging   = ref(false)
const bibMessage   = ref('')

const tabs = [
  { key: 'screening',    label: '从初筛/复筛导入', icon: 'fas fa-database' },
  { key: 'fulltext',     label: '上传全文文件',     icon: 'fas fa-file-pdf' },
  { key: 'bibliography', label: '上传题录',          icon: 'fas fa-file-alt' },
]

const fulltextAvailable = computed(() => qa.refs.filter(r => r.fulltext_status === 'available').length)
const fulltextPending   = computed(() => qa.refs.filter(r => r.fulltext_status !== 'available').length)

onMounted(async () => {
  if (project.currentProject) await qa.fetchRefs(project.currentProject.id)
})

async function doImport() {
  importing.value = true
  importResult.value = null
  try {
    const result = await qa.importFromScreening(project.currentProject.id, importStage.value)
    importResult.value = result
    await qa.fetchRefs(project.currentProject.id)
  } catch (e) {
    importResult.value = { error: e?.response?.data?.error || '导入失败' }
  } finally {
    importing.value = false
  }
}

function onFileSelect(e) {
  const files = Array.from(e.target.files || [])
  uploadQueue.value.push(...files.filter(f => f.name.toLowerCase().endsWith('.pdf')))
}
function onDrop(e) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer.files || [])
  uploadQueue.value.push(...files.filter(f => f.name.toLowerCase().endsWith('.pdf')))
}

async function doUpload() {
  if (!uploadQueue.value.length) return
  uploading.value = true
  uploadedCount.value = 0
  try {
    await qa.uploadFulltext(project.currentProject.id, uploadQueue.value)
    uploadedCount.value = uploadQueue.value.length
    uploadQueue.value = []
    await qa.fetchRefs(project.currentProject.id)
  } catch (e) {
    alert(e?.response?.data?.error || '上传失败')
  } finally {
    uploading.value = false
  }
}

function onBibDrop(e) { bibMessage.value = '题录导入功能即将上线，敬请期待' }
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
function fulltextLabel(s) {
  return { available: '已有全文', pending: '待获取', missing: '无全文', error: '获取失败' }[s] || s
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
.import-result { margin-top: 12px; font-size: 0.82rem; }
.result-ok { color: #10b981; font-weight: 500; }
.result-skip { color: #94a3b8; }
.dropzone { border: 2px dashed #e2e8f0; border-radius: 12px; padding: 40px; text-align: center; cursor: pointer; transition: all 0.2s; }
.dropzone:hover, .dropzone--drag { border-color: #6366f1; background: #f0f4ff; }
.dropzone p { margin: 4px 0; font-size: 0.85rem; color: #64748b; }
.link-text { color: #6366f1; font-weight: 500; }
.upload-queue { margin-top: 16px; display: flex; flex-direction: column; gap: 6px; }
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
