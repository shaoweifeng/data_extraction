<template>
  <div class="traffic-light-chart">
    <div class="chart-title" v-if="title">{{ title }}</div>
    <div class="tl-wrap">

      <!-- 第一行：分组标题 -->
      <div class="tl-row">
        <div class="tl-label-col"></div>
        <div class="tl-cols">
          <div
            class="tl-group-label bias-label"
            :style="{ width: (nBias * CELL_W) + 'px' }"
            v-if="nBias > 0"
          >偏倚风险&nbsp;Risk of Bias</div>
          <div
            class="tl-group-label applic-label"
            :style="{ width: (nApplic * CELL_W) + 'px' }"
            v-if="nApplic > 0"
          >适用性&nbsp;Applicability</div>
        </div>
      </div>

      <!-- 第二行：领域名（旋转文字，独立高度） -->
      <div class="tl-row tl-domain-row">
        <div class="tl-label-col"></div>
        <div class="tl-cols">
          <div
            v-for="(dn, di) in data.domain_names"
            :key="di"
            class="tl-domain-cell"
            :class="{ 'sep-left': di === nBias && nBias > 0 }"
          >
            <span
              class="tl-domain-text"
              :class="di < nBias ? 'tc-bias' : 'tc-applic'"
            >{{ dn }}</span>
          </div>
        </div>
      </div>

      <!-- 数据行 -->
      <div class="tl-body">
        <div
          v-for="(ref, ri) in data.refs"
          :key="ref.id"
          :class="['tl-row', 'tl-data-row', { even: ri % 2 === 0 }]"
        >
          <div class="tl-label-col" :title="ref.title">{{ truncate(ref.title, 30) }}</div>
          <div class="tl-cols">
            <div
              v-for="(result, di) in ref.bias_results"
              :key="di"
              :class="['tl-cell', riskClass(result), { 'sep-left': di === nBias && nBias > 0, 'cell-applic': di >= nBias }]"
              :title="riskLabel(result)"
            >
              <i :class="riskIcon(result)"></i>
            </div>
          </div>
        </div>
      </div>

      <!-- 图例 -->
      <div class="tl-legend">
        <span v-for="l in legends" :key="l.key" :class="['legend-item', l.cls]">
          <i :class="l.icon"></i> {{ l.label }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data:  { type: Object, required: true },
  title: { type: String, default: '' },
})

const CELL_W = 56

const nBias   = computed(() => props.data.n_bias   ?? props.data.domain_names?.length ?? 0)
const nApplic = computed(() => props.data.n_applic ?? 0)

const legends = [
  { key: 'low',     cls: 'leg-low',     icon: 'fas fa-circle-check',    label: '低风险' },
  { key: 'high',    cls: 'leg-high',    icon: 'fas fa-circle-xmark',    label: '高风险' },
  { key: 'unclear', cls: 'leg-unclear', icon: 'fas fa-circle-question', label: '不清楚' },
  { key: 'na',      cls: 'leg-na',      icon: 'fas fa-circle-minus',    label: '不适用' },
]

function riskClass(r) {
  return { low: 'cell-low', high: 'cell-high', unclear: 'cell-unclear', pending: 'cell-pending', na: 'cell-na' }[r] || 'cell-pending'
}
function riskLabel(r) {
  return { low: '低风险', high: '高风险', unclear: '不清楚', pending: '待定', na: '不适用' }[r] || r
}
function riskIcon(r) {
  return {
    low:     'fas fa-circle-check',
    high:    'fas fa-circle-xmark',
    unclear: 'fas fa-circle-question',
    pending: 'fas fa-circle',
    na:      'fas fa-circle-minus',
  }[r] || 'fas fa-circle'
}
function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n) + '…' : s
}
</script>

<style scoped>
.traffic-light-chart {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 16px 12px;
}
.chart-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 10px;
  text-align: center;
}
.tl-wrap { overflow-x: auto; }

/* 所有行的共同布局 */
.tl-row { display: flex; align-items: center; }

/* 左侧文献标签列（固定宽度） */
.tl-label-col {
  width: 200px;
  min-width: 160px;
  flex-shrink: 0;
  font-size: 0.75rem;
  color: #475569;
  padding-right: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 右侧列区域 */
.tl-cols {
  display: flex;
  flex-shrink: 0;
}

/* ── 分组标题行 ───────────────────────────────────────────── */
.tl-group-label {
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.62rem;
  font-weight: 700;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
  margin-bottom: 3px;
}
.bias-label {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}
.applic-label {
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

/* ── 领域名行 ─────────────────────────────────────────────── */
.tl-domain-row { align-items: flex-end; margin-bottom: 4px; }

.tl-domain-cell {
  width: 56px;
  height: 76px;          /* 给旋转文字充分留高，不会溢出到上方 */
  position: relative;
  flex-shrink: 0;
  overflow: visible;
}

/* 旋转文字：锚点在单元格底部中央，向左上方展开 */
.tl-domain-text {
  position: absolute;
  bottom: 6px;
  left: 50%;
  transform-origin: left bottom;
  transform: rotate(-50deg);
  white-space: nowrap;
  font-size: 0.63rem;
  font-weight: 500;
  line-height: 1;
}
.tc-bias   { color: #1d4ed8; }
.tc-applic { color: #15803d; }

/* 偏倚/适用性分隔线（加在第一个适用性列左侧） */
.sep-left {
  border-left: 2px solid #cbd5e1;
  margin-left: 1px;
}

/* ── 数据行 ───────────────────────────────────────────────── */
.tl-body { display: flex; flex-direction: column; gap: 2px; }
.tl-data-row { padding: 2px 0; border-radius: 4px; }
.tl-data-row.even { background: #f8fafc; }

.tl-cell {
  width: 56px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  border-radius: 4px;
  flex-shrink: 0;
}
.tl-cell.cell-applic { background: rgba(240, 253, 244, 0.5); }

.cell-low     { color: #059669; }
.cell-high    { color: #dc2626; }
.cell-unclear { color: #d97706; }
.cell-pending { color: #cbd5e1; }
.cell-na      { color: #94a3b8; }

/* ── 图例 ────────────────────────────────────────────────── */
.tl-legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}
.legend-item { font-size: 0.72rem; color: #475569; display: flex; align-items: center; gap: 4px; }
.leg-low     { color: #059669; }
.leg-high    { color: #dc2626; }
.leg-unclear { color: #d97706; }
.leg-na      { color: #94a3b8; }
</style>
