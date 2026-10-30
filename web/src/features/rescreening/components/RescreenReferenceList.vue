<template>
  <section class="reference-list" :class="'reference-list--' + variant">
    <form class="list-tools" @submit.prevent="search">
      <div class="search-box">
        <i class="fas fa-search"></i><input
          v-model="query"
          type="search"
          maxlength="200"
          placeholder="搜索文献标题或 DOI"
          aria-label="搜索复筛文献"
        />
      </div>
      <select v-model="status" aria-label="筛选文献状态" @change="search">
        <option value="">全部文献</option>
        <option value="ready">全文可用于 AI</option>
        <option value="missing">未绑定全文</option>
        <option value="unreviewed">待审核 / 待定</option>
        <option value="reconfirm">需要重新确认</option>
        <option value="included">已纳入</option>
        <option value="excluded">已排除</option>
        <option value="not_retrieved">全文未获取</option>
      </select>
      <button :disabled="ws.state.working">搜索</button>
    </form>
    <div v-if="selectable" class="list-tools selection-tools">
      <button :disabled="ws.state.working" @click="ws.selectPage(readyOnly)">
        选择本页{{ readyOnly ? '可筛选文献' : '' }}
      </button>
      <span>已选 {{ ws.state.selected.length }} 篇（跨页保留）</span><button @click="clearSelection">清空选择</button>
    </div>
    <div class="ref-table-wrap">
      <table class="ref-table">
        <thead>
          <tr>
            <th>文献</th>
            <th v-if="variant === 'upload'" class="center">来源</th>
            <th v-else class="center">全文状态</th>
            <th class="center">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in ws.state.refs.items"
            :key="row.id"
            :class="{ selected: ws.state.detail?.id === row.id }"
          >
            <td>
              <div class="ref-title-row">
                <input
                  v-if="selectable"
                  type="checkbox"
                  :checked="ws.state.selected.includes(row.id)"
                  :disabled="
                    ws.state.working ||
                      (readyOnly &&
                        !row.ai_ready &&
                        !ws.state.selected.includes(row.id))
                  "
                  :aria-label="`选择 ${row.title}`"
                  @change="ws.toggle(row.id)"
                />
                <div class="ref-title-text" :title="row.title">
                  {{ row.title }}
                </div>
              </div>
              <div class="ref-meta">
                {{ row.authors?.slice(0, 2).join('，') || '作者未提供' }} ·
                {{ row.publication_year || '年份未提供' }} ·
                {{ row.journal || '期刊未提供'
                }}<template v-if="row.doi"> · {{ row.doi }}</template>
              </div>
              <small v-if="row.needs_reconfirmation" class="rs-warning">审核需要重新确认</small>
            </td>
            <td class="center">
              <span
                class="tag"
                :class="
                  row.fulltext_status === 'ready'
                    ? 'tag-green'
                    : ['failed', 'rejected'].includes(row.fulltext_status)
                      ? 'tag-red'
                      : 'tag-gray'
                "
              >{{
                variant === 'upload'
                  ? sourceLabels[row.source_type] || '文献导入'
                  : fulltextLabel(row.fulltext_status)
              }}</span>
            </td>
            <td class="center op-cell">
              <template v-if="variant === 'fulltext'">
                <button
                  v-if="row.asset_id"
                  class="btn-link"
                  @click="$emit('open', row)"
                >
                  查看
                </button><button
                  class="btn-link"
                  :disabled="ws.state.working || ws.state.info.busy"
                  @click="$emit('replace', row)"
                >
                  {{ row.asset_id ? '更改' : '上传' }}
                </button><button
                  v-if="!row.asset_id"
                  class="btn-link"
                  @click="$emit('open', row)"
                >
                  绑定已有全文
                </button>
              </template>
              <button
                v-else
                class="btn-link"
                :disabled="
                  variant === 'upload' &&
                    (ws.state.working || ws.state.info.busy)
                "
                @click="$emit('open', row)"
              >
                {{ actionLabel }}
              </button>
            </td>
          </tr>
          <tr v-if="!ws.state.refs.items.length">
            <td colspan="3" class="rs-empty">没有符合条件的文献</td>
          </tr>
        </tbody>
      </table>
    </div>
    <RescreenPagination
      :page="ws.state.refs"
      :disabled="ws.state.working"
      @change="(p, s) => ws.read(() => ws.loadReferences(p, s))"
    />
  </section>
</template>
<script setup>
import { inject, ref } from 'vue'
import { fulltextLabel } from '../state'
import RescreenPagination from './RescreenPagination.vue'
defineProps({
  variant: { type: String, default: 'default' },
  selectable: Boolean,
  readyOnly: Boolean,
  actionLabel: { type: String, default: '查看' },
})
defineEmits(['open', 'replace'])
const ws = inject('rescreen')
const sourceLabels = {
  screening: '初筛导入',
  bibliography: '题录上传',
  pdf: 'PDF 上传',
}
const query = ref(ws.state.filters.q)
const status = ref(ws.state.filters.status)
function clearSelection() {
  ws.state.selected = []
  ws.state.estimate = null
}
function search() {
  ws.state.filters = { q: query.value, status: status.value }
  ws.read(() => ws.loadReferences(1))
}
</script>
<style scoped>
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
.btn-link {
  background: none;
  border: none;
  color: #6366f1;
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0 4px;
  text-decoration: underline;
}

.reference-list {
  min-width: 0;
}
.list-tools {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 16px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.75rem;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  min-width: 180px;
  color: #94a3b8;
}
.search-box input {
  width: 100%;
  min-width: 0;
}
.ref-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ref-meta {
  overflow-wrap: anywhere;
}
.ref-table {
  table-layout: fixed;
}
.ref-table th:first-child {
  width: 65%;
}
.ref-title-text {
  overflow-wrap: anywhere;
}
.ref-table-wrap {
  max-height: 420px;
}
.reference-list :deep(.rs-pagination) {
  padding: 12px 16px;
}
.selection-tools {
  color: #64748b;
}
.reference-list--ai .ref-table th:first-child {
  width: 60%;
}
@media (max-width: 700px) {
  .ref-table th:first-child {
    width: 55%;
  }
  .op-cell {
    white-space: normal;
  }
  .op-cell button {
    margin: 4px 0;
  }
}
</style>
