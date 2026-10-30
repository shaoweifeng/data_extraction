<template>
  <div class="fulltext-step">
    <div class="step-header">
      <div
        class="step-icon-wrap"
        style="background: linear-gradient(135deg, #6366f1, #8b5cf6)"
      >
        <i class="fas fa-link"></i>
      </div>
      <div>
        <h3 class="step-title">全文查找绑定</h3>
        <p class="step-subtitle">
          自动查找已有或开放全文，查看、更改或手动上传文献对应的 PDF
        </p>
      </div>
    </div>
    <input
      ref="uploadInput"
      type="file"
      accept=".pdf"
      hidden
      :disabled="blocked"
      @change="uploadForReference"
    />
    <div class="action-panel">
      <div class="auto-search-copy">
        <strong>查找并绑定全文</strong><span>选择文献后查找，明确匹配的全文可自动绑定；标题相近的候选仍需确认，避免绑定错误。</span><small>每次最多
          {{ ws.state.info.capabilities.max_lookup }}
          篇；未开启外部查找时仍可本地匹配和上传。</small>
      </div>
      <div class="rs-actions">
        <button
          class="btn-secondary"
          :disabled="blocked || !canLookup"
          @click="lookup('local')"
        >
          本地匹配
        </button><button
          class="btn-primary"
          :disabled="
            blocked || !canLookup || !ws.state.info.capabilities.online_lookup
          "
          @click="lookup('online')"
        >
          <i class="fas fa-search"></i>自动查找全文
        </button><label class="rs-checkbox"><input
          v-model="downloadOpen"
          type="checkbox"
          :disabled="blocked"
        />下载许可允许的开放全文</label>
      </div>
    </div>
    <div class="status-cards">
      <div class="status-card status-card--bound">
        <span class="status-num">{{
          ws.state.info.counts.bound ?? ws.state.info.counts.ready
        }}</span><span class="status-label">已绑定</span>
      </div>
      <div class="status-card status-card--unbound">
        <span class="status-num">{{ ws.state.info.counts.missing ?? '—' }}</span><span class="status-label">未绑定</span>
      </div>
      <div class="status-card status-card--failed">
        <span class="status-num">{{
          ws.state.info.counts.fulltext_failed ?? '—'
        }}</span><span class="status-label">处理失败</span>
      </div>
    </div>
    <div class="ref-list-section">
      <div class="ref-list-header">
        <h4>全文绑定列表</h4>
        <span class="ref-stats">共 {{ ws.state.info.counts.total }} 篇 · 文献 / 全文状态 / 操作</span>
      </div>
      <RescreenReferenceList
        variant="fulltext"
        selectable
        @open="open"
        @replace="replace"
      />
    </div>
    <div v-if="ws.state.detail" class="preview-drawer">
      <div class="drawer-head">
        <div>
          <h4>全文查看 / 更改</h4>
          <p>{{ ws.state.detail.title }}</p>
        </div>
        <div class="rs-actions">
          <span
            class="tag"
            :class="ws.state.detail.pdf_url ? 'tag-green' : 'tag-gray'"
          >{{ fulltextLabel(ws.state.detail.fulltext_status) }}</span><button class="btn-link" @click="ws.clearReference()">
            关闭
          </button>
        </div>
      </div>
      <div class="drawer-body">
        <template v-if="safePdfUrl(ws.state.detail.pdf_url)">
          <div class="pdf-toolbar">
            <span><i class="fas fa-file-pdf"></i>已绑定全文</span><button :disabled="blocked" @click="replace(ws.state.detail)">
              更改全文
            </button>
          </div>
          <div class="pdf-preview-real">
            <RescreenPdf :url="ws.state.detail.pdf_url" />
          </div>
        </template>
        <div v-else class="manual-upload-box">
          <i class="fas fa-cloud-upload-alt"></i><strong>当前文献尚无可读全文</strong>
          <p>上传正确 PDF，校验与提取完成后确认绑定。</p>
          <button
            class="btn-primary"
            :disabled="blocked"
            @click="replace(ws.state.detail)"
          >
            上传 PDF
          </button>
        </div>
        <div v-if="assetId" class="rs-inset rs-toolbar">
          <span>待绑定全文：{{ selectedAsset?.original_filename || '所选 PDF' }} ·
            {{ label(selectedAsset?.status || 'pending') }}</span><button
            class="primary"
            :disabled="blocked || selectedAsset?.status !== 'ready'"
            @click="bind"
          >
            确认绑定
          </button>
        </div>
        <div class="rs-toolbar binding-tools">
          <button
            :disabled="blocked || !ws.state.detail.asset_id"
            @click="unbind"
          >
            解除当前绑定
          </button><button @click="advancedOpen = true">选择项目已有全文</button>
        </div>
        <form class="rs-toolbar rs-inset" @submit.prevent="manual">
          <input
            v-model="manualUrl"
            type="url"
            maxlength="2000"
            placeholder="记录全文页面链接（不会自动访问）"
            required
          /><button :disabled="blocked">记录外链</button>
        </form>
      </div>
    </div>
    <details
      :open="advancedOpen"
      class="fulltext-management"
      @toggle="advancedOpen = $event.target.open"
    >
      <summary>项目全文与查找记录 / 候选确认</summary>
      <section class="rs-card">
        <div class="rs-toolbar">
          <h3>项目全文资产</h3>
          <button @click="ws.read(() => ws.loadAssets())">刷新</button>
        </div>
        <div class="rs-table-scroll">
          <table class="rs-table">
            <thead>
              <tr>
                <th>ID / 文件</th>
                <th>处理状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="asset in ws.state.assets.items" :key="asset.id">
                <td class="rs-title-cell">
                  <strong :title="asset.original_filename">#{{ asset.id }} · {{ asset.original_filename }}</strong><small>{{ asset.page_count || '—' }} 页 ·
                    {{ (asset.size_bytes / 1048576).toFixed(1) }} MB</small>
                </td>
                <td>
                  <span
                    class="rs-badge"
                    :class="asset.ai_ready ? 'success' : 'warning'"
                  >{{
                    asset.ai_ready ? 'AI 就绪' : label(asset.status)
                  }}</span><small v-if="asset.extraction_truncated">提取覆盖不完整，不能用于完整全文 AI 复筛</small><small v-if="asset.error_message">{{
                    asset.error_message
                  }}</small>
                </td>
                <td class="rs-actions">
                  <a
                    v-if="asset.download_url"
                    :href="asset.download_url"
                    target="_blank"
                    rel="noopener"
                  >查看 PDF</a><button
                    v-if="asset.status === 'ready'"
                    :disabled="blocked || !ws.state.detail"
                    @click="assetId = asset.id"
                  >
                    选择绑定
                  </button><button
                    v-if="asset.status === 'failed'"
                    :disabled="blocked"
                    @click="
                      ws.action(() => ws.api.assetAction(asset.id, 'retry'))
                    "
                  >
                    重新处理
                  </button>
                </td>
              </tr>
              <tr v-if="!ws.state.assets.items.length">
                <td colspan="3" class="rs-empty">
                  暂无全文资产，上传 PDF 后会在这里显示
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <RescreenPagination
          :page="ws.state.assets"
          @change="(p, s) => ws.read(() => ws.loadAssets(p, s))"
        />
      </section>
      <section class="rs-card">
        <h3>查找任务</h3>
        <div
          v-for="job in ws.state.lookups.items"
          :key="job.id"
          class="rs-task-row"
        >
          <span>#{{ job.id }} · {{ label(job.status) }} · {{ job.processed }} /
            {{ job.total }} 篇</span>
          <div class="rs-actions">
            <button @click="ws.read(() => ws.loadLookup(job.id))">
              查看候选
            </button><button
              v-if="['pending', 'running'].includes(job.status)"
              :disabled="ws.state.working"
              @click="ws.action(() => ws.api.lookupAction(job.id, 'cancel'))"
            >
              停止
            </button><button
              v-if="
                ['failed', 'cancelled', 'completed'].includes(job.status) &&
                  job.mode !== 'manual'
              "
              :disabled="blocked"
              @click="ws.action(() => ws.api.lookupAction(job.id, 'retry'))"
            >
              重试未完成项
            </button>
          </div>
        </div>
        <p v-if="!ws.state.lookups.items.length" class="rs-empty">
          暂无查找任务
        </p>
        <RescreenPagination
          :page="ws.state.lookups"
          @change="(p, s) => ws.read(() => ws.loadLookups(p, s))"
        />
        <template v-if="ws.state.lookupId">
          <h4>任务 #{{ ws.state.lookupId }} 的候选</h4>
          <div
            v-for="item in ws.state.lookupItems.items"
            :key="item.id"
            class="rs-inset"
          >
            <p>文献 #{{ item.reference_id }} · {{ label(item.status) }}</p>
            <p v-if="!item.candidates.length" class="rs-muted">
              暂无候选，可手工上传全文
            </p>
            <div
              v-for="candidate in item.candidates"
              :key="candidate.id"
              class="rs-candidate"
            >
              <div>
                <strong>{{ candidate.title || candidate.source }}</strong><small>{{ candidate.source }} ·
                  {{ candidate.license || '未标注许可' }} ·
                  {{ label(candidate.status) }}</small><a
                  v-if="candidate.url"
                  :href="safeLink(candidate.url)"
                  target="_blank"
                  rel="noopener noreferrer"
                >查看来源页面</a>
              </div>
              <div class="rs-actions">
                <button
                  v-if="candidate.asset_id && candidate.status !== 'bound'"
                  :disabled="blocked"
                  @click="confirm(candidate, item)"
                >
                  确认绑定
                </button><button
                  v-if="
                    !candidate.asset_id &&
                      candidate.license &&
                      ws.state.info.capabilities.online_lookup
                  "
                  :disabled="blocked"
                  @click="download(candidate, item)"
                >
                  尝试合规下载
                </button>
              </div>
            </div>
          </div>
          <RescreenPagination
            :page="ws.state.lookupItems"
            @change="
              (p, s) => ws.read(() => ws.loadLookup(ws.state.lookupId, p, s))
            "
          />
        </template>
      </section>
    </details>
  </div>
</template>
<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { label, fulltextLabel, safePdfUrl } from '../state'
import RescreenPdf from './RescreenPdf.vue'
import RescreenReferenceList from './RescreenReferenceList.vue'
import RescreenPagination from './RescreenPagination.vue'
const ws = inject('rescreen')
const assetId = ref('')
const uploadInput = ref(null)
const pendingReference = ref(null)
const advancedOpen = ref(false)
const selectedAsset = computed(() =>
  ws.state.assets.items.find((asset) => asset.id === Number(assetId.value)),
)
async function replace(row) {
  if (blocked.value) return
  if (ws.state.detail?.id !== row.id) {
    const detail = await ws.read(() => ws.selectReference(row.id))
    if (!detail || detail.id !== row.id) return
  }
  pendingReference.value = {
    id: row.id,
    input_version: ws.state.detail.input_version,
  }
  uploadInput.value?.click()
}
async function uploadForReference(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  const reference = pendingReference.value
  pendingReference.value = null
  if (!file || !reference || blocked.value) return
  const result = await ws.upload([file], true, false)
  if (!result || ws.state.detail?.id !== reference.id) return
  assetId.value = result.assets?.[0]?.id || ''
  await ws.read(() => ws.loadAssets(1))
  ws.state.notice =
    'PDF 已上传，校验与提取完成后点击“确认绑定”。原全文在确认前保持不变。'
}
const manualUrl = ref('')
const downloadOpen = ref(false)
const blocked = computed(() => ws.state.working || ws.state.info.busy)
const canLookup = computed(
  () =>
    ws.state.selected.length > 0 &&
    ws.state.selected.length <= ws.state.info.capabilities.max_lookup,
)
onMounted(() => ws.read(() => Promise.all([ws.loadAssets(), ws.loadLookups()])))
function open(row) {
  assetId.value = ''
  ws.read(() => ws.selectReference(row.id))
}
function lookup(mode) {
  const payload = {
    ids: [...ws.state.selected],
    mode,
    download: downloadOpen.value,
    auto_bind: true,
  }
  ws.action(
    () =>
      ws.keyed('lookup', payload, (key) =>
        ws.api.lookupStart(ws.state.projectId, payload, key),
      ),
    '查找任务已创建。',
  )
}
function bind() {
  const detail = ws.state.detail
  ws.action(async () => {
    await ws.api.binding(detail.id, {
      asset_id: Number(assetId.value),
      expected_version: detail.input_version,
      expected_revision: ws.state.info.revision,
    })
    await ws.selectReference(detail.id)
  }, '已绑定全文；旧建议及审核保留为历史。')
}
function unbind() {
  if (!window.confirm('解除当前全文绑定？已有结果将需要重新确认。')) return
  assetId.value = ''
  const detail = ws.state.detail
  ws.action(async () => {
    await ws.api.binding(detail.id, {
      asset_id: null,
      expected_version: detail.input_version,
      expected_revision: ws.state.info.revision,
    })
    await ws.selectReference(detail.id)
  })
}
function manual() {
  const payload = {
    ids: [ws.state.detail.id],
    mode: 'manual',
    manual_url: manualUrl.value,
  }
  ws.action(
    () =>
      ws.keyed('manual', payload, (key) =>
        ws.api.lookupStart(ws.state.projectId, payload, key),
      ),
    '外链已记录，不会自动访问该页面。',
  )
}
function confirm(candidate, item) {
  ws.action(
    () => ws.api.confirmCandidate(candidate.id, item.input_version),
    '候选已绑定。',
  )
}
function download(candidate, item) {
  const payload = {
    ids: [item.reference_id],
    mode: 'download',
    candidate_id: candidate.id,
  }
  ws.action(() =>
    ws.keyed('download', payload, (key) =>
      ws.api.lookupStart(ws.state.projectId, payload, key),
    ),
  )
}
function safeLink(url) {
  return /^https?:\/\//i.test(url) ? url : undefined
}
</script>
<style scoped>
.fulltext-step {
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
.action-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 16px 18px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}
.auto-search-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.auto-search-copy strong {
  font-size: 0.9rem;
  color: #1e293b;
}
.auto-search-copy span {
  font-size: 0.76rem;
  color: #64748b;
}
.status-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.status-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.status-num {
  font-size: 1.35rem;
  font-weight: 800;
  color: #1e293b;
}
.status-label {
  font-size: 0.76rem;
  color: #64748b;
}
.status-card--bound {
  border-color: #bbf7d0;
  background: #f0fdf4;
}
.status-card--failed {
  border-color: #fecaca;
  background: #fff7f7;
}
.ref-list-section,
.preview-drawer {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}
.ref-list-header,
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid #f1f5f9;
  gap: 12px;
}
.empty-ref-list {
  min-height: 132px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #94a3b8;
  border-top: 1px solid #f1f5f9;
}
.empty-ref-list i {
  font-size: 1.8rem;
  color: #cbd5e1;
}
.empty-ref-list p {
  margin: 0;
  color: #64748b;
  font-weight: 600;
}
.empty-ref-list span {
  font-size: 0.76rem;
}
.ref-list-header h4,
.drawer-head h4 {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 600;
  color: #1e293b;
}
.ref-stats,
.drawer-head p {
  font-size: 0.75rem;
  color: #64748b;
  margin: 3px 0 0;
}
.ref-table-wrap {
  overflow-x: auto;
  max-height: 360px;
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
  padding: 9px 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
  vertical-align: middle;
}
.ref-table tr.selected td {
  background: #f8f7ff;
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
.source-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  font-size: 0.72rem;
  color: #64748b;
}
.source-meta i {
  color: #10b981;
}
.lookup-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  font-size: 0.72rem;
  color: #2563eb;
  text-decoration: none;
}
.lookup-link:hover {
  text-decoration: underline;
}
.error-text {
  font-size: 0.72rem;
  color: #dc2626;
  margin-top: 4px;
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
.tag-gray {
  background: #f1f5f9;
  color: #64748b;
}
.tag-red {
  background: #fee2e2;
  color: #991b1b;
}
.op-cell {
  white-space: nowrap;
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
  font-weight: 600;
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
.drawer-body {
  padding: 14px;
}
.pdf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #2d2d44;
  color: #c4c4d4;
  border-radius: 10px 10px 0 0;
  font-size: 0.78rem;
}
.pdf-toolbar i {
  color: #ef4444;
}
.pdf-toolbar button {
  border: 0;
  border-radius: 6px;
  background: #3d3d5c;
  color: #fff;
  padding: 5px 10px;
  cursor: pointer;
}
.pdf-preview-real {
  height: 320px;
  background: #1e1e2e;
  border-radius: 0 0 10px 10px;
  overflow: hidden;
}
.manual-upload-box {
  height: 220px;
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 9px;
  text-align: center;
  color: #64748b;
}
.manual-upload-box i {
  font-size: 2rem;
  color: #94a3b8;
}
.manual-upload-box p {
  margin: 0;
  font-size: 0.8rem;
}
.manual-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: center;
}
.btn-secondary {
  padding: 8px 14px;
  background: #fff;
  color: #4f46e5;
  border: 1px solid #c7d2fe;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  text-decoration: none;
  font-weight: 600;
}
@media (max-width: 1100px) {
  .status-cards {
    grid-template-columns: 1fr;
  }
  .action-panel {
    align-items: flex-start;
    flex-direction: column;
  }
}

.fulltext-management {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 14px 16px;
}
.binding-tools {
  margin-top: 14px;
}
.action-panel .rs-actions {
  justify-content: flex-end;
}
.auto-search-copy {
  min-width: 0;
  flex: 1;
}
.drawer-head p {
  overflow-wrap: anywhere;
}
.pdf-preview-real {
  height: 420px;
}
.pdf-preview-real :deep(.rs-pdf-viewer),
.pdf-preview-real :deep(iframe) {
  height: 100%;
  width: 100%;
  border: 0;
}
.fulltext-management > .rs-card {
  box-shadow: none;
  margin-top: 14px;
}
</style>
