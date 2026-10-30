<template>
  <div class="rs-page">
    <section class="rs-head">
      <div class="rs-head-icon"><i class="fas fa-file-export"></i></div>
      <div>
        <h3>结果导出</h3>
        <p>导出复筛结果、纳入全文或缺失清单，保留人工判断及完整题录。</p>
      </div>
      <span
        v-if="ws.state.info.export_completed_id"
        class="rs-badge rs-badge--success"
      >{{
        ws.state.info.export_completion_kind === 'skipped'
          ? '当前版本已明确跳过导出'
          : '当前版本已完成导出'
      }}</span>
    </section>
    <div class="summary-grid">
      <div>
        <b>{{ counts.total }}</b><span>全部文献</span>
      </div>
      <div>
        <b>{{ counts.included }}</b><span>人工纳入</span>
      </div>
      <div>
        <b>{{ counts.excluded }}</b><span>人工排除</span>
      </div>
      <div>
        <b>{{ counts.missing ?? counts.not_retrieved }}</b><span>未绑定 PDF</span>
      </div>
    </div>
    <section v-if="counts.remaining" class="block-card">
      <h4><i class="fas fa-exclamation-circle"></i>导出前需要处理</h4>
      <p>还有 {{ counts.remaining }} 篇待审核或重新确认，当前仅可导出草稿。</p>
    </section>
    <div class="export-controls">
      <label>文件格式<select v-model="format" aria-label="导出文件格式">
        <option value="xlsx">Excel（含完整元数据）</option>
        <option value="xml">结构化 XML</option>
        <option value="ris">EndNote / RIS</option>
        <option value="metadata">完整原始元数据 JSONL</option>
      </select></label>
      <label>结果类型<select v-model="mode" aria-label="导出结果类型">
        <option value="draft">草稿（不标记完成）</option>
        <option value="final" :disabled="!!counts.remaining">最终结果</option>
      </select></label>
      <span>最终文件生成成功才标记完成；草稿与 PDF 附件不标记完成。</span>
    </div>
    <div class="export-grid">
      <article
        v-for="item in exportCards"
        :key="item.format || item.key"
        class="export-card"
      >
        <div class="export-icon"><i :class="item.icon"></i></div>
        <h4>{{ item.title }}</h4>
        <p>{{ item.desc }}</p>
        <button
          :disabled="
            blocked ||
              ws.state.info.export_busy ||
              (mode === 'final' && !!counts.remaining)
          "
          @click="generateCard(item)"
        >
          生成{{ item.format === 'pdf' ? ' PDF 包' : '文件' }}
        </button>
      </article>
    </div>
    <details class="export-options">
      <summary>更多导出选项 / 分批导出</summary>
      <div class="rs-toolbar">
        <label>导出范围<select v-model="scope">
          <option value="all">所有文献</option>
          <option value="included">纳入文献</option>
          <option value="excluded">排除文献</option>
          <option value="not_retrieved">全文未获取文献</option>
          <option value="pending">待定 / 未审阅草稿</option>
        </select></label><button
          class="primary"
          :disabled="
            blocked ||
              ws.state.info.export_busy ||
              (mode === 'final' && !!counts.remaining)
          "
          @click="generate()"
        >
          生成所选范围
        </button>
      </div>
      <label class="rs-checkbox"><input
        v-model="batched"
        type="checkbox"
      />仅导出所选范围内的一段文献</label>
      <div v-if="batched" class="rs-toolbar">
        <label>起始序号<input v-model.number="first" type="number" min="1" /></label><label>文献条数<input
          v-model.number="size"
          type="number"
          min="1"
          max="100000"
        /></label>
      </div>
      <p class="rs-muted">
        默认不分批，导出此范围的全部文献。文件保留期到期不会撤销完成凭据；修改输入或审核结果后，旧文件标记为历史版本。
      </p>
      <p class="rs-muted">
        PDF 包只打包可用全文，清单列出缺失文件；元数据附件与 PDF
        包本身不标记完成。草稿不会将未确认 AI 建议当作最终纳入。
      </p>
      <div class="rs-toolbar">
        <button
          :disabled="blocked || !!counts.remaining || ws.state.info.export_busy"
          @click="skip"
        >
          明确跳过本版本导出
        </button><span class="rs-muted">全部文献最终确认后可跳过，保留操作记录。</span>
      </div>
    </details>
    <section class="history-card rs-stack">
      <div class="rs-section-title">
        <h3>生成记录</h3>
        <button
          class="rs-btn"
          :disabled="ws.state.working"
          @click="ws.read(() => ws.loadExports())"
        >
          刷新
        </button>
      </div>
      <div
        v-for="row in exportPage.items"
        :key="row.id"
        class="rs-inset rs-stack"
      >
        <div class="rs-section-title">
          <strong>{{
            row.format === 'skip'
              ? '明确跳过导出'
              : `${scopeLabels[row.scope]} · ${row.format.toUpperCase()} · ${row.mode === 'final' ? '最终结果' : '草稿'}`
          }}</strong><span class="rs-badge">{{
            row.current ? '当前版本' : '历史版本'
          }}</span>
        </div>
        <p v-if="row.format === 'skip'">已明确跳过本版本导出，未生成文件。</p>
        <p v-else>
          {{ statusLabels[row.status] || row.status }} ·
          {{ row.processed_count }} / {{ row.total_count }} 篇<span
            v-if="row.selection?.limit"
          >
            · 范围内第 {{ row.selection.offset + 1 }}～{{
              row.selection.offset + row.total_count
            }}
            篇</span>
        </p>
        <progress
          v-if="['pending', 'running', 'cancelling'].includes(row.status)"
          class="rs-progress"
          :value="row.processed_count"
          :max="row.total_count || 1"
        ></progress>
        <div class="rs-toolbar">
          <a
            v-if="downloadUrl(row)"
            class="rs-btn rs-btn--primary"
            :href="downloadUrl(row)"
          >下载 {{ row.download_name }}</a>
          <span v-if="row.expired" class="rs-muted">文件已清理或超过保留期，请重新生成。</span>
          <button
            v-if="
              row.retained_bytes &&
                ['completed', 'failed', 'cancelled'].includes(row.status)
            "
            class="rs-btn"
            :disabled="ws.state.working"
            @click="purge(row)"
          >
            清理生成文件
          </button>
          <button
            v-if="['pending', 'running'].includes(row.status)"
            class="rs-btn"
            :disabled="ws.state.working"
            @click="
              ws.action(() => ws.api.cancelExport(row.id), '已请求停止导出。')
            "
          >
            停止导出
          </button>
          <span v-if="row.error_code" class="rs-warning">{{
            errorLabels[row.error_code] ||
              '文件未生成，请重试；持续失败请联系管理员。'
          }}</span>
        </div>
      </div>
      <p v-if="!exportPage.total" class="rs-muted">尚未生成导出文件。</p>
      <RescreenPagination
        :page="exportPage"
        :disabled="ws.state.working"
        @change="(page, size) => ws.read(() => ws.loadExports(page, size))"
      />
    </section>
    <section class="rs-card rs-stack">
      <h3>导入质量评价</h3>
      <p class="rs-muted">
        仅追加当前人工确认纳入的文献，共享已有
        PDF，不重复上传或收取模型积分。已存在的 QA 文献、AI
        评价和人工成果均保留，不自动更新或删除。
      </p>
      <div class="rs-toolbar">
        <button class="rs-btn" :disabled="blocked" @click="previewQA">
          预览待导入内容
        </button><a
          class="rs-btn"
          :href="`/workspace/${ws.state.projectId}?stage=QUALITY`"
        >前往质量评价</a>
      </div>
      <div v-if="handoffPreview" class="rs-inset rs-stack">
        <p>
          当前纳入 {{ handoffPreview.counts.included }} 篇 · 新增
          {{ handoffPreview.counts.new }} 篇 · 已有
          {{ handoffPreview.counts.existing }} 篇
        </p>
        <p v-if="differences" class="rs-warning">
          {{ differences }} 篇来源已变化或不再纳入，原 QA
          快照和评价将原样保留，不会同步覆盖。
        </p>
        <ul v-if="handoffPreview.differences.length" class="rs-differences">
          <li
            v-for="row in handoffPreview.differences"
            :key="row.qa_reference_id"
            :title="row.title"
          >
            {{ row.title }} ·
            {{ row.kind === 'changed' ? '来源版本已变化' : '来源不再纳入' }}
          </li>
        </ul>
        <p v-if="handoffPreview.differences_truncated" class="rs-muted">
          仅展示前 100 条差异。
        </p>
        <label v-if="differences" class="rs-checkbox"><input
          v-model="acknowledged"
          type="checkbox"
        />我已了解差异，保留已有 QA 及其成果，仅追加新文献</label>
        <button
          class="rs-btn rs-btn--primary"
          :disabled="
            blocked ||
              !handoffPreview.counts.new ||
              (!!differences && !acknowledged)
          "
          @click="importQA"
        >
          确认增量导入
        </button>
      </div>
      <p v-if="handoffResult" class="rs-success">
        新增 {{ handoffResult.imported }} 篇，保留已有
        {{ handoffResult.preserved }} 篇。{{
          handoffResult.no_fulltext
            ? `其中 ${handoffResult.no_fulltext} 篇仍需获取全文。`
            : ''
        }}
      </p>
    </section>
  </div>
</template>
<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import RescreenPagination from './RescreenPagination.vue'
import { emptyPage } from '../state'
const ws = inject('rescreen')
const counts = computed(() => ws.state.info.counts)
const blocked = computed(() => ws.state.working || ws.state.info.busy)
const exportPage = computed(() => ws.state.exports || emptyPage())
const scope = ref('all'),
  format = ref('xlsx'),
  mode = ref(counts.value.remaining ? 'draft' : 'final')
const batched = ref(false),
  first = ref(1),
  size = ref(100)
const handoffPreview = ref(null),
  handoffResult = ref(null),
  acknowledged = ref(false)
const differences = computed(() =>
  handoffPreview.value
    ? handoffPreview.value.counts.changed +
      handoffPreview.value.counts.no_longer_included
    : 0,
)
const scopeLabels = {
  all: '所有文献',
  included: '纳入文献',
  excluded: '排除文献',
  not_retrieved: '全文未获取文献',
  pending: '待定 / 未审阅草稿',
}
const statusLabels = {
  pending: '等待后台处理',
  running: '生成中',
  cancelling: '正在停止',
  cancelled: '已停止',
  failed: '生成失败',
  completed: '已生成',
}
const errorLabels = {
  export_too_large: '文件超过导出上限，请缩小范围。',
  storage_quota_exceeded: '账户存储空间不足，请清理后重试。',
  asset_checksum_mismatch: 'PDF 完整性校验失败，请联系管理员。',
  dispatch_failed: '后台任务未成功派发，请重试。',
}
watch(
  () => counts.value.remaining,
  (value) => {
    if (value) mode.value = 'draft'
  },
)
onMounted(() => ws.read(() => ws.loadExports(1)))
function downloadUrl(row) {
  return row.download_url === `/api/rescreening/exports/${row.id}/download/`
    ? row.download_url
    : null
}
async function generate(overrides = {}) {
  const payload = {
    format: format.value,
    scope: scope.value,
    mode: mode.value,
    fingerprint: ws.state.info.fingerprint,
    ...overrides,
    ...(batched.value ? { offset: first.value - 1, limit: size.value } : {}),
  }
  await ws.action(
    () =>
      ws.keyed('export', payload, (key) =>
        ws.api.startExport(ws.state.projectId, payload, key),
      ),
    '导出任务已创建，完成后可在生成记录中下载。',
  )
}
async function previewQA() {
  acknowledged.value = false
  handoffResult.value = null
  handoffPreview.value = await ws.read(() =>
    ws.api.qaPreview(ws.state.projectId),
  )
}
async function importQA() {
  const result = await ws.action(
    () =>
      ws.api.qaHandoff(ws.state.projectId, {
        confirmation_token: handoffPreview.value.confirmation_token,
        acknowledge_differences: acknowledged.value,
      }),
    '已增量导入质量评价，已有成果保持不变。',
  )
  if (result) {
    handoffResult.value = result
    handoffPreview.value = null
  }
}
async function purge(row) {
  if (
    !window.confirm(
      '将删除此记录的生成文件及导出快照，释放配额；完成凭据和原始文献不受影响。确认清理？',
    )
  )
    return
  await ws.action(
    () => ws.api.purgeExport(row.id),
    '生成文件已清理，需要时可重新生成。',
  )
}
async function skip() {
  if (
    !window.confirm(
      '确认明确跳过本版本导出？将记录完成凭据但不生成文件；文献或审核变化后仍需重新确认。',
    )
  )
    return
  const payload = { fingerprint: ws.state.info.fingerprint }
  await ws.action(
    () =>
      ws.keyed('skip-export', payload, (key) =>
        ws.api.skipExport(ws.state.projectId, payload, key),
      ),
    '已记录本版本跳过导出。',
  )
}

const exportCards = [
  {
    key: 'all',
    title: '全部复筛结果',
    desc: '包含完整题录、全文状态、AI 建议和人工最终判断。',
    icon: 'fas fa-table',
  },
  {
    key: 'included',
    title: '最终纳入文献',
    desc: '导出人工最终确认纳入的文献，保留完整书目信息。',
    icon: 'fas fa-check-circle',
  },
  {
    key: 'excluded',
    title: '最终排除文献',
    desc: '包含人工排除理由与审阅信息。',
    icon: 'fas fa-ban',
  },
  {
    key: 'included',
    format: 'pdf',
    title: '纳入文献 PDF 包',
    desc: '打包最终纳入文献的可用全文，并附缺失文件清单。',
    icon: 'fas fa-file-archive',
  },
  {
    key: 'not_retrieved',
    title: '全文未获取清单',
    desc: '导出人工标记为全文未获取的文献，便于记录与核对。',
    icon: 'fas fa-list-ul',
  },
]
function generateCard(item) {
  return generate({ scope: item.key, format: item.format || format.value })
}
</script>
<style scoped>
.rs-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rs-head {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}
.rs-head-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, #f59e0b, #fb923c);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
h3,
h4,
p {
  margin: 0;
}
h3 {
  font-size: 1.05rem;
  color: #1e293b;
}
.rs-head p {
  font-size: 0.8rem;
  color: #64748b;
  margin-top: 4px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.summary-grid div {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 15px 16px;
}
.summary-grid b {
  font-size: 1.4rem;
  color: #1e293b;
  margin-right: 8px;
}
.summary-grid span {
  font-size: 0.78rem;
  color: #64748b;
}
.block-card {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 14px;
  padding: 14px 16px;
  color: #9a3412;
}
.block-card h4 {
  display: flex;
  gap: 8px;
  align-items: center;
}
.block-card ul {
  margin: 8px 0 0;
  padding-left: 22px;
  font-size: 0.82rem;
}
.export-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.export-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 185px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}
.export-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: #eef2ff;
  color: #4f46e5;
  display: flex;
  align-items: center;
  justify-content: center;
}
.export-card p {
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.5;
}
.export-card button {
  margin-top: auto;
  border: 0;
  border-radius: 9px;
  background: #4f46e5;
  color: #fff;
  padding: 9px 12px;
  font-weight: 700;
  cursor: pointer;
}
.export-card button:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
.history-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 16px;
}
.history-row {
  display: flex;
  justify-content: space-between;
  padding: 10px 0;
  border-top: 1px solid #f1f5f9;
  font-size: 0.84rem;
}
.history-row em {
  color: #94a3b8;
  font-style: normal;
}
@media (max-width: 1100px) {
  .export-grid,
  .summary-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.export-controls {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 0.8rem;
  color: #64748b;
}
.export-controls label {
  display: flex;
  gap: 8px;
  align-items: center;
}
.export-controls > span {
  font-size: 0.74rem;
}
.export-options {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
}
.export-options > .rs-toolbar,
.export-options > .rs-checkbox {
  margin-top: 14px;
}
.rs-head > span {
  margin-left: auto;
}
.export-card h4 {
  margin: 0;
}
.summary-grid div {
  min-width: 0;
}
.block-card p {
  margin: 8px 0 0;
}
</style>
