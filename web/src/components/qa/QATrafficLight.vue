<template>
  <div class="traffic-light-chart">
    <div class="chart-title" v-if="title">{{ title }}</div>

    <!-- 编辑提示 -->
    <div class="edit-hint" v-if="editable">
      <i class="fas fa-pencil-alt"></i>
      点击左侧文献名可修改，修改后点击「生成图表」将使用新名称生成 PNG
    </div>

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

      <!-- 第二行：领域名（旋转文字） -->
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
          <!-- 文献名：可编辑 -->
          <div class="tl-label-col">
            <template v-if="editable">
              <input
                v-if="editingId === ref.id"
                class="label-input"
                :value="localLabels[ref.id] ?? ref.title"
                @blur="e => commitEdit(ref.id, e.target.value)"
                @keyup.enter="e => commitEdit(ref.id, e.target.value)"
                @keyup.escape="editingId = null"
                ref="inputRef"
                :title="localLabels[ref.id] ?? ref.title"
              />
              <span
                v-else
                class="label-editable"
                :title="(localLabels[ref.id] ?? ref.title) + '\n点击修改'"
                @click="startEdit(ref.id)"
              >
                <span class="label-text">{{ truncate(localLabels[ref.id] ?? ref.title, 28) }}</span>
                <i class="fas fa-pencil-alt label-edit-icon"></i>
              </span>
            </template>
            <template v-else>
              <span :title="ref.title">{{ truncate(ref.title, 30) }}</span>
            </template>
          </div>

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
import { computed, ref, reactive, nextTick, watch } from 'vue'

const props = defineProps({
  data:     { type: Object, required: true },
  title:    { type: String, default: '' },
  editable: { type: Boolean, default: false },
  // 外部传入的当前标签（从父组件 v-model:studyLabels 同步）
  studyLabels: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update:studyLabels'])

const CELL_W = 56

const nBias   = computed(() => props.data.n_bias   ?? props.data.domain_names?.length ?? 0)
const nApplic = computed(() => props.data.n_applic ?? 0)

// 本地编辑状态
const localLabels = reactive({ ...props.studyLabels })
const editingId   = ref(null)
const inputRef    = ref(null)

// 外部 studyLabels 变化时同步
watch(() => props.studyLabels, (val) => {
  Object.assign(localLabels, val)
}, { deep: true })

function startEdit(id) {
  editingId.value = id
  nextTick(() => {
    const el = document.querySelector('.label-input')
    if (el) { el.focus(); el.select() }
  })
}

function commitEdit(id, val) {
  const trimmed = val?.trim()
  if (trimmed) {
    localLabels[id] = trimmed
    emit('update:studyLabels', { ...localLabels })
  }
  editingId.value = null
}

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
  margin-bottom: 6px;
  text-align: center;
}
.edit-hint {
  font-size: 0.72rem;
  color: #6366f1;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  border-radius: 6px;
  padding: 5px 10px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tl-wrap { overflow-x: auto; }

.tl-row { display: flex; align-items: center; }

/* 左侧文献标签列 */
.tl-label-col {
  width: 210px;
  min-width: 160px;
  flex-shrink: 0;
  font-size: 0.75rem;
  color: #475569;
  padding-right: 10px;
}

/* 右侧列区域 */
.tl-cols { display: flex; flex-shrink: 0; }

/* ── 可编辑文献名 ─────────────────────────────────────── */
.label-editable {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  border-radius: 4px;
  padding: 2px 4px;
  transition: background 0.12s;
  overflow: hidden;
}
.label-editable:hover { background: #f1f5f9; }
.label-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.label-edit-icon {
  font-size: 0.6rem;
  color: #94a3b8;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.12s;
}
.label-editable:hover .label-edit-icon { opacity: 1; }

.label-input {
  width: 100%;
  font-size: 0.75rem;
  color: #1e293b;
  border: 1px solid #6366f1;
  border-radius: 4px;
  padding: 2px 6px;
  outline: none;
  background: #fff;
  box-sizing: border-box;
}

/* ── 分组标题行 ───────────────────────────────────────── */
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
.bias-label   { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
.applic-label { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }

/* ── 领域名行 ─────────────────────────────────────────── */
.tl-domain-row { align-items: flex-end; margin-bottom: 4px; }
.tl-domain-cell {
  width: 56px;
  height: 76px;
  position: relative;
  flex-shrink: 0;
  overflow: visible;
}
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
.sep-left  { border-left: 2px solid #cbd5e1; margin-left: 1px; }

/* ── 数据行 ───────────────────────────────────────────── */
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

/* ── 图例 ────────────────────────────────────────────── */
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
