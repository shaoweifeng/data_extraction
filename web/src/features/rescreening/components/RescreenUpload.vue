<template>
  <div class="rs-stack">
    <header class="rs-section-heading">
      <div>
        <h2>导入复筛文献</h2>
        <p>
          从初筛纳入结果继续，也可以独立上传题录或 PDF。导入不消耗模型积分。
        </p>
      </div>
      <span class="rs-badge">{{ ws.state.info.counts.total }} 篇文献</span>
    </header>
    <div class="rs-upload-grid">
      <section class="rs-card">
        <h3><i class="fas fa-filter"></i> 从初筛导入</h3>
        <p>读取人工决定优先的纳入文献，保留完整题录和来源。</p>
        <button :disabled="blocked" @click="preview">预览初筛来源</button>
        <div v-if="ws.state.source" class="rs-inset">
          <p>
            新增 {{ ws.state.source.new_count }} 篇 · 已导入
            {{ ws.state.source.existing_count }} 篇 · 来源变化
            {{ ws.state.source.changed_count }} 篇
          </p>
          <p v-if="ws.state.source.changed_count" class="rs-warning">
            存在来源变化，当前不会自动覆盖，请核对来源后再导入。
          </p>
          <button
            class="primary"
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
      </section>
      <section class="rs-card">
        <h3><i class="fas fa-file-upload"></i> 上传题录或全文</h3>
        <p>
          题录支持 XML、RIS、NBIB、BibTeX 等现有解析格式；PDF
          可独立创建复筛文献。
        </p>
        <div class="rs-toolbar">
          <label><input v-model="kind" type="radio" value="index" /> 题录索引</label><label><input v-model="kind" type="radio" value="pdf" /> PDF 全文</label>
        </div>
        <label class="rs-dropzone"><i class="fas fa-cloud-upload-alt"></i><span>选择{{ kind === 'pdf' ? ' PDF' : '题录' }}文件</span><small>支持多文件，大小与数量由服务器校验</small><input
          :key="kind"
          type="file"
          multiple
          :accept="
            kind === 'pdf'
              ? '.pdf'
              : '.xml,.ris,.nbib,.bib,.txt,.ciw,.enw,.doc'
          "
          :disabled="blocked"
          @change="upload"
        /></label>
        <p v-if="ws.state.uploadProgress !== null" class="rs-muted">
          上传进度 {{ ws.state.uploadProgress }}% · 接收后由后台处理
        </p>
      </section>
    </div>
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
    <div v-if="ws.state.selected.length" class="rs-toolbar"><span>已选择 {{ ws.state.selected.length }} 篇</span><button :disabled="blocked" @click="removeSelected">移除所选文献</button></div>
    <RescreenReferenceList selectable action-label="移除" @open="remove" />
  </div>
</template>
<script setup>
import { computed, inject, ref, onMounted } from 'vue'
import RescreenPagination from './RescreenPagination.vue'
import RescreenReferenceList from './RescreenReferenceList.vue'
import { label } from '../state'
const ws = inject('rescreen')
const kind = ref('index')
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
  if (files.length) ws.upload(files, kind.value === 'pdf', true)
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
  if (!window.confirm(`移除所选 ${ws.state.selected.length} 篇文献？原始题录及历史记录会保留，不会自动恢复到当前列表。`)) return
  const result = await ws.action(() => ws.api.remove(ws.state.projectId, [...ws.state.selected], ws.state.info.revision), '已移除所选文献。')
  if (result) ws.state.selected = []
}
</script>
