<template>
  <section class="rs-card">
    <form class="rs-toolbar" @submit.prevent="search">
      <input
        v-model="query"
        type="search"
        maxlength="200"
        placeholder="搜索文献标题或 DOI"
        aria-label="搜索复筛文献"
      />
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
    <div v-if="selectable" class="rs-toolbar rs-subtoolbar">
      <button :disabled="ws.state.working" @click="ws.selectPage(readyOnly)">
        选择本页{{ readyOnly ? '可筛选文献' : '' }}
      </button><span>已选 {{ ws.state.selected.length }} 篇（跨页保留）</span><button
        @click="clearSelection"
      >
        清空选择
      </button>
    </div>
    <div class="rs-table-scroll">
      <table class="rs-table">
        <thead>
          <tr>
            <th v-if="selectable" class="rs-check-col">选择</th>
            <th>文献</th>
            <th>全文</th>
            <th>人工决定</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in ws.state.refs.items"
            :key="row.id"
            :class="{ 'is-selected': ws.state.detail?.id === row.id }"
          >
            <td v-if="selectable">
              <input
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
            </td>
            <td class="rs-title-cell">
              <strong :title="row.title">{{ row.title }}</strong><small>{{ row.authors?.slice(0, 2).join('，') || '作者未提供' }} ·
                {{ row.publication_year || '年份未提供'
                }}<template v-if="row.doi"> · {{ row.doi }}</template></small>
            </td>
            <td>
              <span class="rs-badge" :class="row.ai_ready ? 'success' : ''">{{
                row.ai_ready ? '全文就绪' : label(row.fulltext_status)
              }}</span>
            </td>
            <td>
              <span
                class="rs-badge"
                :class="
                  row.needs_reconfirmation
                    ? 'warning'
                    : row.decision === 'included'
                      ? 'success'
                      : ''
                "
              >{{
                row.needs_reconfirmation ? '需要重确认' : label(row.decision)
              }}</span>
            </td>
            <td>
              <button class="rs-link" @click="$emit('open', row)">
                {{ actionLabel }}
              </button>
            </td>
          </tr>
          <tr v-if="!ws.state.refs.items.length">
            <td :colspan="selectable ? 5 : 4" class="rs-empty">
              没有符合条件的文献
            </td>
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
import { label } from '../state'
import RescreenPagination from './RescreenPagination.vue'
defineProps({
  selectable: Boolean,
  readyOnly: Boolean,
  actionLabel: { type: String, default: '查看' },
})
defineEmits(['open'])
const ws = inject('rescreen')
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
