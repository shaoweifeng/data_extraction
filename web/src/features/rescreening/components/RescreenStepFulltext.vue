<template>
  <div class="fulltext-step">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">
        <i class="fas fa-link"></i>
      </div>
      <div>
        <h3 class="step-title">全文查找绑定</h3>
        <p class="step-subtitle">自动查找后直接绑定全文；用户只在未绑定、绑定失败或需要更改时介入</p>
      </div>
    </div>

    <input ref="uploadInput" type="file" accept=".pdf" style="display:none" @change="onUploadSelected" />
    <div class="action-panel">
      <div class="auto-search-copy">
        <strong>一键在线查找全文</strong>
        <span>系统将对未绑定文献自动查找、下载并绑定 PDF，不再进入候选全文人工确认流程。</span>
      </div>
      <button class="btn-primary" :disabled="!canAutoSearch" @click="runAutoSearch">
        <i v-if="!rescreen.fulltextSearching" class="fas fa-magnifying-glass"></i>
        <i v-else class="fas fa-spinner fa-spin"></i>
        {{ rescreen.fulltextSearching ? '自动查找中...' : '自动查找全文' }}
      </button>
    </div>

    <div class="status-cards">
      <div class="status-card status-card--bound">
        <span class="status-num">{{ rescreen.boundRefs.length }}</span>
        <span class="status-label">已绑定</span>
      </div>
      <div class="status-card status-card--unbound">
        <span class="status-num">{{ rescreen.unboundRefs.length }}</span>
        <span class="status-label">未绑定</span>
      </div>
      <div class="status-card status-card--failed">
        <span class="status-num">{{ rescreen.bindFailedRefs.length }}</span>
        <span class="status-label">绑定失败</span>
      </div>
    </div>

    <div class="ref-list-section">
      <div class="ref-list-header">
        <h4>全文绑定列表</h4>
        <span class="ref-stats">{{ rescreen.totalRefs ? '只展示三列：文献 / 全文状态 / 操作' : '上传/导入文献后生成列表' }}</span>
      </div>
      <div v-if="rescreen.totalRefs === 0" class="empty-ref-list">
        <i class="fas fa-inbox"></i>
        <p>暂无复筛文献</p>
        <span>请先回到“上传/导入文献”步骤，从三种入口中选择一种生成复筛文献列表。</span>
      </div>
      <div v-else class="ref-table-wrap">
        <table class="ref-table">
          <thead>
            <tr>
              <th>文献</th>
              <th class="center" style="width:140px">全文状态</th>
              <th class="center" style="width:150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="paper in rescreen.refs" :key="paper.id" :class="{ selected: rescreen.activeRefId === paper.id }">
              <td>
                <div class="ref-title-text">{{ paper.title }}</div>
                <div class="ref-meta">{{ paper.first_author }} · {{ paper.year }} · {{ paper.journal }} · {{ paper.doi || paper.pmid }}</div>
                <div v-if="paper.fulltext_source || paper.fulltext_license" class="source-meta">
                  <i class="fas fa-shield-halved"></i>
                  来源：{{ sourceLabel(paper.fulltext_source || paper.fulltext_resolver) }}
                  <span v-if="paper.fulltext_license"> · 许可：{{ paper.fulltext_license }}</span>
                </div>
                <a
                  v-if="paper.fulltext_status !== 'bound' && paper.fulltext_lookup_url"
                  class="lookup-link"
                  :href="paper.fulltext_lookup_url"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <i class="fas fa-arrow-up-right-from-square"></i> 在线查找全文
                </a>
                <div v-if="paper.fulltext_error" class="error-text"><i class="fas fa-circle-info"></i> {{ paper.fulltext_error }}</div>
              </td>
              <td class="center"><span :class="['tag', fulltextTagClass(paper.fulltext_status)]">{{ fulltextLabel(paper.fulltext_status) }}</span></td>
              <td class="center op-cell">
                <template v-if="paper.fulltext_status === 'bound'">
                  <button class="btn-link" @click="selectPaper(paper)">查看</button>
                  <button class="btn-link" @click="triggerUpload(paper.id)">更改</button>
                </template>
                <button v-else class="btn-link" @click="triggerUpload(paper.id)">上传</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="rescreen.activeRef" class="preview-drawer">
      <div class="drawer-head">
        <div>
          <h4>全文查看 / 更改</h4>
          <p>{{ rescreen.activeRef.title }}</p>
        </div>
        <span :class="['tag', fulltextTagClass(rescreen.activeRef.fulltext_status)]">{{ fulltextLabel(rescreen.activeRef.fulltext_status) }}</span>
      </div>
      <div class="drawer-body">
        <template v-if="rescreen.activeRef.fulltext_status === 'bound'">
          <div class="pdf-toolbar">
            <span><i class="fas fa-file-pdf"></i> {{ rescreen.activeRef.fulltext_filename }}</span>
            <button @click="triggerUpload(rescreen.activeRef.id)">更改全文</button>
          </div>
          <div class="pdf-preview-real">
            <QAPdfViewer
              :pdf-url="rescreen.activeRef.fulltext_url"
              :filename="rescreen.activeRef.fulltext_filename || 'document.pdf'"
            />
          </div>
        </template>
        <div v-else class="manual-upload-box">
          <i class="fas fa-cloud-arrow-up"></i>
          <strong>{{ rescreen.activeRef.fulltext_status === 'bind_failed' ? '当前全文绑定失败' : '当前文献未绑定全文' }}</strong>
          <p>请手动上传正确 PDF，上传成功后状态变为「已绑定」。</p>
          <div class="manual-actions">
            <button class="btn-primary" @click="triggerUpload(rescreen.activeRef.id)">上传 PDF</button>
            <a
              v-if="rescreen.activeRef.fulltext_lookup_url"
              class="btn-secondary"
              :href="rescreen.activeRef.fulltext_lookup_url"
              target="_blank"
              rel="noopener noreferrer"
            >在线查找全文</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import QAPdfViewer from '@/features/quality/components/QAPdfViewer.vue'
import { useProjectStore } from '@/features/projects/store'
import { useRescreenStore } from '@/features/rescreening/store'

const project = useProjectStore()
const rescreen = useRescreenStore()
const uploadInput = ref(null)
const pendingRefId = ref(null)
const canAutoSearch = computed(() => (
  !rescreen.fulltextSearching
  && rescreen.totalRefs > 0
  && (rescreen.unboundRefs.length + rescreen.bindFailedRefs.length) > 0
))

function currentProjectId() { return project.currentProject?.id }
function fulltextLabel(value) { return { bound: '已绑定', unbound: '未绑定', bind_failed: '绑定失败' }[value] || value }
function fulltextTagClass(value) { return { bound: 'tag-green', unbound: 'tag-gray', bind_failed: 'tag-red' }[value] || 'tag-gray' }
function sourceLabel(source) {
  return {
    local_upload: '项目内已上传 PDF',
    manual_upload: '人工上传',
    europe_pmc: 'Europe PMC / PMC',
    unpaywall: 'Unpaywall',
    openalex: 'OpenAlex',
  }[source] || source || '—'
}
function selectPaper(paper) { rescreen.activeRefId = paper.id }
function triggerUpload(refId) {
  pendingRefId.value = refId
  uploadInput.value?.click()
}
async function onUploadSelected(event) {
  const file = event.target.files?.[0]
  if (file && pendingRefId.value) {
    await rescreen.replaceFulltextFile(currentProjectId(), pendingRefId.value, file)
  }
  event.target.value = ''
  pendingRefId.value = null
}
async function runAutoSearch() {
  await rescreen.autoSearchFulltext(currentProjectId())
}
</script>

<style scoped>
.fulltext-step { display:flex; flex-direction:column; gap:14px; }
.step-header { display:flex; align-items:center; gap:12px; padding:14px 16px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; }
.step-icon-wrap { width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center; color:#fff; flex-shrink:0; }
.step-title { font-size:1rem; font-weight:600; color:#1e293b; margin:0; }
.step-subtitle { font-size:.75rem; color:#64748b; margin:0; }
.action-panel { display:flex; align-items:center; justify-content:space-between; gap:14px; padding:16px 18px; background:#fff; border:1px solid #e2e8f0; border-radius:12px; }
.auto-search-copy { display:flex; flex-direction:column; gap:3px; }
.auto-search-copy strong { font-size:.9rem; color:#1e293b; }
.auto-search-copy span { font-size:.76rem; color:#64748b; }
.status-cards { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.status-card { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:12px 14px; display:flex; align-items:baseline; gap:8px; }
.status-num { font-size:1.35rem; font-weight:800; color:#1e293b; }
.status-label { font-size:.76rem; color:#64748b; }
.status-card--bound { border-color:#bbf7d0; background:#f0fdf4; }
.status-card--failed { border-color:#fecaca; background:#fff7f7; }
.ref-list-section,.preview-drawer { background:#fff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; }
.ref-list-header,.drawer-head { display:flex; justify-content:space-between; align-items:center; padding:14px 16px; border-bottom:1px solid #f1f5f9; gap:12px; }
.empty-ref-list { min-height:132px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; color:#94a3b8; border-top:1px solid #f1f5f9; }
.empty-ref-list i { font-size:1.8rem; color:#cbd5e1; }
.empty-ref-list p { margin:0; color:#64748b; font-weight:600; }
.empty-ref-list span { font-size:.76rem; }
.ref-list-header h4,.drawer-head h4 { margin:0; font-size:.88rem; font-weight:600; color:#1e293b; }
.ref-stats,.drawer-head p { font-size:.75rem; color:#64748b; margin:3px 0 0; }
.ref-table-wrap { overflow-x:auto; max-height:360px; overflow-y:auto; }
.ref-table { width:100%; border-collapse:collapse; font-size:.8rem; }
.ref-table th { padding:8px 12px; background:#f8fafc; color:#64748b; font-weight:500; text-align:left; border-bottom:1px solid #e2e8f0; position:sticky; top:0; }
.ref-table td { padding:9px 12px; border-bottom:1px solid #f1f5f9; color:#334155; vertical-align:middle; }
.ref-table tr.selected td { background:#f8f7ff; }
.center { text-align:center!important; }
.ref-title-text { display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical; overflow:hidden; font-weight:600; color:#334155; }
.ref-meta { font-size:.72rem; color:#94a3b8; margin-top:3px; }
.source-meta { display:flex; align-items:center; gap:4px; margin-top:4px; font-size:.72rem; color:#64748b; }
.source-meta i { color:#10b981; }
.lookup-link { display:inline-flex; align-items:center; gap:4px; margin-top:4px; font-size:.72rem; color:#2563eb; text-decoration:none; }
.lookup-link:hover { text-decoration:underline; }
.error-text { font-size:.72rem; color:#dc2626; margin-top:4px; }
.tag { display:inline-block; padding:2px 8px; border-radius:4px; font-size:.72rem; font-weight:500; }
.tag-green { background:#d1fae5; color:#065f46; }
.tag-gray { background:#f1f5f9; color:#64748b; }
.tag-red { background:#fee2e2; color:#991b1b; }
.op-cell { white-space:nowrap; }
.btn-primary { padding:8px 18px; background:#6366f1; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:.85rem; display:flex; align-items:center; gap:6px; transition:background .15s; font-weight:600; }
.btn-primary:hover:not(:disabled) { background:#4f46e5; }
.btn-primary:disabled { opacity:.5; cursor:not-allowed; }
.btn-link { background:none; border:none; color:#6366f1; cursor:pointer; font-size:.78rem; padding:0 4px; text-decoration:underline; }
.drawer-body { padding:14px; }
.pdf-toolbar { display:flex; align-items:center; justify-content:space-between; padding:8px 12px; background:#2d2d44; color:#c4c4d4; border-radius:10px 10px 0 0; font-size:.78rem; }
.pdf-toolbar i { color:#ef4444; }
.pdf-toolbar button { border:0; border-radius:6px; background:#3d3d5c; color:#fff; padding:5px 10px; cursor:pointer; }
.pdf-preview-real { height:320px; background:#1e1e2e; border-radius:0 0 10px 10px; overflow:hidden; }
.manual-upload-box { height:220px; border:1px dashed #cbd5e1; background:#f8fafc; border-radius:10px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:9px; text-align:center; color:#64748b; }
.manual-upload-box i { font-size:2rem; color:#94a3b8; }
.manual-upload-box p { margin:0; font-size:.8rem; }
.manual-actions { display:flex; gap:10px; align-items:center; justify-content:center; }
.btn-secondary { padding:8px 14px; background:#fff; color:#4f46e5; border:1px solid #c7d2fe; border-radius:8px; cursor:pointer; font-size:.85rem; text-decoration:none; font-weight:600; }
@media(max-width:1100px){.status-cards{grid-template-columns:1fr}.action-panel{align-items:flex-start;flex-direction:column}}
</style>
