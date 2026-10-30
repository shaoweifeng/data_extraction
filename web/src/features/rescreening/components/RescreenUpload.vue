<template>
  <div class="qa-upload rescreen-upload">
    <div class="step-header">
      <div
        class="step-icon-wrap"
        style="background: linear-gradient(135deg, #8b5cf6, #6366f1)"
      >
        <i class="fas fa-upload"></i>
      </div>
      <div>
        <h3 class="step-title">上传/导入文献</h3>
        <p class="step-subtitle">
          从初筛导入、上传 PDF 全文或上传题录，建立复筛文献列表
        </p>
      </div>
    </div>
    <div class="upload-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="upload-tab"
        :class="{ active: activeTab === tab.key }"
        :disabled="blocked"
        @click="activeTab = tab.key"
      >
        <i :class="tab.icon"></i>{{ tab.label }}
      </button>
    </div>
    <div class="upload-panel">
      <template v-if="activeTab === 'screening'">
        <div class="dropzone dropzone--import">
          <i
            class="fas fa-database"
            style="font-size: 2rem; color: #6366f1; margin-bottom: 8px"
          ></i>
          <p>导入文献初筛阶段中最终标记为「纳入」的文献</p>
          <p class="upload-hint">
            保留完整题录和来源，重复导入不会重复创建；来源变化须先核对。
          </p>
          <div class="import-inline-actions">
            <select class="qa-select" aria-label="初筛导入范围">
              <option>从文献初筛导入最终纳入文献</option>
            </select><button class="btn-primary" :disabled="blocked" @click="preview">
              <i class="fas fa-download"></i>预览导入
            </button>
          </div>
          <div v-if="ws.state.source" class="import-result">
            <p>
              新增 {{ ws.state.source.new_count }} 篇 · 已导入
              {{ ws.state.source.existing_count }} 篇 · 来源变化
              {{ ws.state.source.changed_count }} 篇
            </p>
            <p v-if="ws.state.source.changed_count" class="rs-warning">
              存在来源变化，当前不会自动覆盖，请核对来源后再导入。
            </p>
            <button
              class="btn-primary"
              :disabled="
                blocked ||
                  !ws.state.source.new_count ||
                  !!ws.state.source.changed_count
              "
              @click="importSource"
            >
              确认导入
            </button>
          </div>
        </div>
      </template>
      <template v-else>
        <div
          class="dropzone"
          :class="{
            'dropzone--drag': dragging,
            'dropzone--uploading': ws.state.working,
          }"
          role="button"
          tabindex="0"
          :aria-label="activeTab === 'pdf' ? '选择 PDF 全文' : '选择题录文件'"
          :aria-disabled="blocked"
          @click="!blocked && fileInput?.click()"
          @keydown.enter.prevent="!blocked && fileInput?.click()"
          @keydown.space.prevent="!blocked && fileInput?.click()"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="drop"
        >
          <i
            :class="activeTab === 'pdf' ? 'fas fa-file-pdf' : 'fas fa-file-alt'"
            style="font-size: 2rem; color: #6366f1; margin-bottom: 8px"
          ></i>
          <p>
            拖拽{{
              activeTab === 'pdf' ? ' PDF 全文' : '题录文件'
            }}到此处，或<span class="link-text">点击选择文件</span>
          </p>
          <p class="upload-hint">
            {{
              activeTab === 'pdf'
                ? '支持批量上传 PDF；处理完成后创建复筛文献，进入全文绑定步骤核对。'
                : '支持 XML、RIS、NBIB、BibTeX 等现有解析格式，大小与数量由服务器校验。'
            }}
          </p>
          <input
            ref="fileInput"
            :key="activeTab"
            type="file"
            multiple
            :accept="
              activeTab === 'pdf'
                ? '.pdf'
                : '.xml,.ris,.nbib,.bib,.txt,.ciw,.enw,.doc'
            "
            hidden
            :disabled="blocked"
            @change="upload"
          />
        </div>
        <p v-if="ws.state.uploadProgress !== null" class="upload-hint">
          上传进度 {{ ws.state.uploadProgress }}% · 接收后由后台处理
        </p>
      </template>
    </div>
    <div class="ref-list-section">
      <div class="ref-list-header">
        <h4>复筛文献列表</h4>
        <span class="ref-stats">共 {{ ws.state.info.counts.total }} 篇</span>
      </div>
      <div v-if="ws.state.selected.length" class="rs-toolbar selection-toolbar">
        <span>已选择 {{ ws.state.selected.length }} 篇</span><button :disabled="blocked" @click="removeSelected">
          移除所选文献
        </button>
      </div>
      <RescreenReferenceList
        variant="upload"
        selectable
        action-label="移除"
        @open="remove"
      />
    </div>
    <details class="import-history">
      <summary>导入记录与文件处理详情</summary>
      <section class="rs-card">
        <div class="rs-toolbar">
          <h3>导入记录</h3>
          <button
            :disabled="ws.state.working"
            @click="ws.read(() => ws.loadImports())"
          >
            刷新
          </button>
        </div>
        <div class="rs-table-scroll">
          <table class="rs-table">
            <thead>
              <tr>
                <th>批次</th>
                <th>来源</th>
                <th>状态</th>
                <th>成功条目</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="batch in ws.state.imports.items" :key="batch.id">
                <td>#{{ batch.id }}</td>
                <td>{{ sources[batch.source_type] || batch.source_type }}</td>
                <td>
                  {{ label(batch.status)
                  }}<small v-if="batch.error" class="rs-warning">{{
                    batch.error
                  }}</small>
                </td>
                <td>{{ batch.accepted_count }}</td>
                <td class="rs-actions">
                  <button @click="details(batch.id)">详情</button><button
                    v-if="batch.retryable"
                    :disabled="blocked"
                    @click="batchAction(batch.id, 'retry')"
                  >
                    重试
                  </button><button
                    v-if="['uploaded', 'importing'].includes(batch.status)"
                    :disabled="ws.state.working"
                    @click="batchAction(batch.id, 'cancel')"
                  >
                    停止
                  </button>
                </td>
              </tr>
              <tr v-if="!ws.state.imports.items.length">
                <td colspan="5" class="rs-empty">暂无导入记录</td>
              </tr>
            </tbody>
          </table>
        </div>
        <RescreenPagination
          :page="ws.state.imports"
          @change="(p, s) => ws.read(() => ws.loadImports(p, s))"
        />
        <div v-if="batchDetail" class="rs-inset">
          <div class="rs-toolbar">
            <strong>批次 #{{ batchDetail.id }}</strong><button @click="batchDetail = null">关闭详情</button>
          </div>
          <div v-for="file in batchDetail.files" :key="file.id">
            <p>
              {{ file.filename }}
              <a
                :href="`/api/rescreening/imports/files/${file.id}/download/`"
                target="_blank"
                rel="noopener"
              >下载原始题录</a>
            </p>
            <pre v-if="ws.state.info.capabilities.diagnostics && file.report">{{
              JSON.stringify(file.report, null, 2)
            }}</pre>
          </div>
          <p v-if="batchDetail.error">{{ batchDetail.error }}</p>
        </div>
      </section>
    </details>
  </div>
</template>
<script setup>
import { computed, inject, ref, onMounted } from 'vue'
import RescreenPagination from './RescreenPagination.vue'
import RescreenReferenceList from './RescreenReferenceList.vue'
import { label } from '../state'
const ws = inject('rescreen')
const activeTab = ref('screening')
const fileInput = ref(null)
const dragging = ref(false)
const tabs = [
  { key: 'screening', label: '从初筛导入', icon: 'fas fa-database' },
  { key: 'pdf', label: '上传 PDF 全文', icon: 'fas fa-file-pdf' },
  { key: 'index', label: '上传题录', icon: 'fas fa-file-alt' },
]
function drop(event) {
  dragging.value = false
  if (!blocked.value) sendFiles(Array.from(event.dataTransfer?.files || []))
}
function sendFiles(files) {
  if (files.length && !blocked.value)
    ws.upload(files, activeTab.value === 'pdf', true)
}
const batchDetail = ref(null)
const sources = {
  screening: '初筛导入',
  bibliography: '题录上传',
  pdf: 'PDF 上传',
}
const blocked = computed(() => ws.state.working || ws.state.info.busy)
onMounted(() => ws.read(() => ws.loadImports()))
async function preview() {
  const result = await ws.read(() => ws.api.preview(ws.state.projectId))
  if (result) ws.state.source = result
}
function importSource() {
  ws.action(
    () =>
      ws.keyed('import-screening', ws.state.source.fingerprint, (key) =>
        ws.api.importScreening(
          ws.state.projectId,
          ws.state.source.fingerprint,
          key,
        ),
      ),
    '导入任务已创建。',
  )
}
function upload(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  sendFiles(files)
}
function batchAction(id, action) {
  ws.action(() => ws.api.importAction(id, action))
}
async function details(id) {
  batchDetail.value = await ws.read(() => ws.api.importDetail(id))
}
function remove(row) {
  if (window.confirm(`移除“${row.title}”？历史记录会保留。`))
    ws.action(
      () => ws.api.remove(ws.state.projectId, [row.id], ws.state.info.revision),
      '已移除文献。',
    )
}
async function removeSelected() {
  if (
    !window.confirm(
      `移除所选 ${ws.state.selected.length} 篇文献？原始题录及历史记录会保留，不会自动恢复到当前列表。`,
    )
  )
    return
  const result = await ws.action(
    () =>
      ws.api.remove(
        ws.state.projectId,
        [...ws.state.selected],
        ws.state.info.revision,
      ),
    '已移除所选文献。',
  )
  if (result) ws.state.selected = []
}
</script>
<style scoped>
.qa-upload {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.step-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}
.step-icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.step-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}
.step-subtitle {
  font-size: 0.75rem;
  color: #64748b;
  margin: 0;
}
.upload-tabs {
  display: flex;
  gap: 8px;
}
.upload-tab {
  padding: 8px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font-size: 0.82rem;
  color: #64748b;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  gap: 6px;
}
.upload-tab:hover {
  border-color: #6366f1;
  color: #6366f1;
}
.upload-tab.active {
  border-color: #6366f1;
  background: #eef2ff;
  color: #6366f1;
  font-weight: 500;
}
.upload-panel {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
}
.dropzone {
  border: 2px dashed #e2e8f0;
  border-radius: 12px;
  padding: 40px 32px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}
.dropzone:hover,
.dropzone--drag {
  border-color: #6366f1;
  background: #f0f4ff;
}
.dropzone p {
  margin: 4px 0;
  font-size: 0.85rem;
  color: #64748b;
}
.dropzone--import {
  cursor: default;
}
.dropzone--import:hover {
  border-color: #6366f1;
  background: #f5f3ff;
}
.dropzone--uploading {
  cursor: default;
  border-color: #6366f1;
  background: #f0f4ff;
}
.link-text {
  color: #6366f1;
  font-weight: 600;
}
.import-inline-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: center;
  margin-top: 16px;
  flex-wrap: wrap;
}
.import-result {
  margin-top: 10px;
  font-size: 0.82rem;
}
.result-ok {
  color: #10b981;
  font-weight: 500;
}
.upload-result-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 500;
  margin-top: 10px;
}
.result-ok-bar {
  background: #d1fae5;
  color: #065f46;
}
.result-err-bar {
  background: #fee2e2;
  color: #991b1b;
}
.ref-list-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}
.ref-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid #f1f5f9;
}
.ref-list-header h4 {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 600;
  color: #1e293b;
}
.ref-stats {
  font-size: 0.75rem;
  color: #64748b;
}
.ref-table-wrap {
  overflow-x: auto;
  max-height: 340px;
  overflow-y: auto;
}
.ref-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.ref-table th {
  padding: 8px 12px;
  background: #f8fafc;
  color: #64748b;
  font-weight: 500;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
}
.ref-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
  vertical-align: middle;
}
.center {
  text-align: center !important;
}
.ref-title-text {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-weight: 600;
  color: #334155;
}
.ref-meta {
  font-size: 0.72rem;
  color: #94a3b8;
  margin-top: 3px;
}
.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 500;
}
.tag-green {
  background: #d1fae5;
  color: #065f46;
}
.tag-purple {
  background: #ede9fe;
  color: #5b21b6;
}
.tag-gray {
  background: #f1f5f9;
  color: #64748b;
}
.tag-red {
  background: #fee2e2;
  color: #991b1b;
}
.btn-primary {
  padding: 8px 18px;
  background: #6366f1;
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: background 0.15s;
}
.btn-primary:hover:not(:disabled) {
  background: #4f46e5;
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-link {
  background: none;
  border: none;
  color: #6366f1;
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0 4px;
  text-decoration: underline;
}
.qa-select {
  padding: 7px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.82rem;
  background: #fff;
}
.bib-msg {
  font-size: 0.82rem !important;
  color: #10b981 !important;
  margin-top: 12px !important;
  font-weight: 500;
}

.upload-hint {
  font-size: 0.75rem;
  color: #64748b;
  line-height: 1.6;
}
.selection-toolbar {
  padding: 12px 16px;
}
.import-history {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 16px;
}
.import-result .btn-primary {
  margin: 12px auto 0;
}
.dropzone[aria-disabled='true'] {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
