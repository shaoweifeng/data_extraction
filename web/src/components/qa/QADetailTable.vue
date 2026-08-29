<template>
  <!--
    明细表格
    props.data：由 chart API 返回的 table_data 字段
    {
      columns: ['文献', '患者选择-偏倚', '患者选择-适用', ...],
      rows: [ { title, values: ['低风险', '低风险', ...] } ]
    }
  -->
  <div class="detail-table-wrap">
    <div class="table-title" v-if="title">{{ title }}</div>
    <div class="table-scroll">
      <table class="detail-table">
        <thead>
          <tr>
            <th class="col-title">文献</th>
            <th v-for="(col, ci) in data.columns" :key="ci">{{ col }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in data.rows" :key="ri">
            <td class="col-title-cell" :title="row.title">{{ truncate(row.title, 40) }}</td>
            <td v-for="(val, vi) in row.values" :key="vi">
              <span :class="['risk-chip', riskClass(val)]">{{ val || '—' }}</span>
            </td>
          </tr>
          <tr v-if="!data.rows?.length">
            <td :colspan="(data.columns?.length || 0) + 1" class="empty-row">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
defineProps({
  data:  { type: Object, required: true },
  title: { type: String, default: '' },
})

function riskClass(v) {
  if (!v) return ''
  if (['低风险', '低', '★'].some(k => v.startsWith(k))) return 'chip-low'
  if (['高风险', '高'].some(k => v.startsWith(k))) return 'chip-high'
  if (['不清楚', '不确定'].some(k => v.startsWith(k))) return 'chip-unclear'
  return 'chip-gray'
}
function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n) + '…' : s
}
</script>

<style scoped>
.detail-table-wrap { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; }
.table-title { padding: 12px 16px; font-size: 0.85rem; font-weight: 600; color: #1e293b; border-bottom: 1px solid #f1f5f9; }
.table-scroll { overflow-x: auto; }
.detail-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.detail-table th { padding: 8px 10px; background: #f8fafc; color: #64748b; font-weight: 500; text-align: center; border-bottom: 1px solid #e2e8f0; white-space: nowrap; position: sticky; top: 0; }
.detail-table th.col-title { text-align: left; min-width: 180px; }
.detail-table td { padding: 7px 10px; border-bottom: 1px solid #f1f5f9; text-align: center; vertical-align: middle; color: #475569; }
.col-title-cell { text-align: left; color: #1e293b; font-weight: 500; }
.detail-table tr:last-child td { border-bottom: none; }
.empty-row { text-align: center; color: #94a3b8; padding: 20px; }
.risk-chip { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 500; white-space: nowrap; }
.chip-low     { background: #d1fae5; color: #065f46; }
.chip-high    { background: #fee2e2; color: #991b1b; }
.chip-unclear { background: #ffedd5; color: #9a3412; }
.chip-gray    { background: #f1f5f9; color: #64748b; }
</style>
