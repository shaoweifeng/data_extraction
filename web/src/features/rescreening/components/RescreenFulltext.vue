<template>
  <div class="rs-stack">
    <header class="rs-section-heading">
      <div>
        <h2>获取并绑定全文</h2>
        <p>
          先选择文献，再匹配本地资产或查找开放来源。标题相近的候选需要你确认。
        </p>
      </div>
      <label class="rs-button primary">上传 PDF<input
        type="file"
        accept=".pdf"
        multiple
        hidden
        :disabled="blocked"
        @change="upload"
      /></label>
    </header>
    <section class="rs-card rs-toolbar">
      <span>已选 {{ ws.state.selected.length }} 篇</span>
      <button :disabled="blocked || !canLookup" @click="lookup('local')">
        本地匹配
      </button>
      <button
        :disabled="
          blocked || !canLookup || !ws.state.info.capabilities.online_lookup
        "
        @click="lookup('online')"
      >
        查找开放全文
      </button>
      <span v-if="!ws.state.info.capabilities.online_lookup" class="rs-muted">外部查找未启用，可上传 PDF 或记录链接</span>
      <label><input v-model="downloadOpen" type="checkbox" :disabled="blocked" />
        下载许可允许的开放全文</label>
      <small>每次最多
        {{ ws.state.info.capabilities.max_lookup }}
        篇；候选确认后才绑定文献</small>
    </section>
    <RescreenReferenceList selectable action-label="绑定 / 查看" @open="open" />
    <section v-if="ws.state.detail" class="rs-card">
      <div class="rs-toolbar">
        <h3 class="rs-wrap">{{ ws.state.detail.title }}</h3>
        <button @click="ws.state.detail = null">关闭</button>
      </div>
      <p>
        当前全文：{{ label(ws.state.detail.fulltext_status) }}
        <a
          v-if="ws.state.detail.pdf_url"
          :href="ws.state.detail.pdf_url"
          target="_blank"
          rel="noopener"
        >打开 PDF</a>
      </p>
      <div class="rs-toolbar">
        <label>资产 ID
          <input
            v-model="assetId"
            type="number"
            min="1"
            placeholder="点击下方“选择绑定”"
          /></label><button class="primary" :disabled="blocked || !assetId" @click="bind">
          确认绑定
        </button><button
          :disabled="blocked || !ws.state.detail.asset_id"
          @click="unbind"
        >
          解除绑定
        </button>
      </div>
      <form class="rs-toolbar rs-inset" @submit.prevent="manual">
        <input
          v-model="manualUrl"
          type="url"
          maxlength="2000"
          placeholder="手工记录全文页面链接（不会自动访问）"
          required
        /><button :disabled="blocked">记录外链</button>
      </form>
    </section>
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
                >{{ asset.ai_ready ? 'AI 就绪' : label(asset.status) }}</span><small v-if="asset.extraction_truncated">提取覆盖不完整，不能用于完整全文 AI 复筛</small><small v-if="asset.error_message">{{
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
          <button @click="ws.read(() => ws.loadLookup(job.id))">查看候选</button><button
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
      <p v-if="!ws.state.lookups.items.length" class="rs-empty">暂无查找任务</p>
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
  </div>
</template>
<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { label } from '../state'
import RescreenReferenceList from './RescreenReferenceList.vue'
import RescreenPagination from './RescreenPagination.vue'
const ws = inject('rescreen')
const assetId = ref('')
const manualUrl = ref('')
const downloadOpen = ref(false)
const blocked = computed(() => ws.state.working || ws.state.info.busy)
const canLookup = computed(
  () =>
    ws.state.selected.length > 0 &&
    ws.state.selected.length <= ws.state.info.capabilities.max_lookup,
)
onMounted(() =>
  ws.read(() => Promise.all([ws.loadAssets(), ws.loadLookups()])),
)
function upload(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (files.length) ws.upload(files, true, false)
}
function open(row) {
  assetId.value = row.asset_id || ''
  ws.read(() => ws.selectReference(row.id))
}
function lookup(mode) {
  const payload = {
    ids: [...ws.state.selected],
    mode,
    download: downloadOpen.value,
    auto_bind: false,
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
