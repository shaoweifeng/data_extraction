<!-- 质量评价比例图：仅负责展示。 -->
<template>
  <!--
    比例图（Risk of Bias Graph）：堆叠横向条形图
    props.data 格式：
    {
      domain_names: ['患者选择', ...],
      proportions: [
        { domain_name: '患者选择', low: 0.6, high: 0.2, unclear: 0.2 },
        ...
      ]
    }
  -->
  <div class="proportion-chart">
    <div class="chart-title" v-if="title">{{ title }}</div>
    <div class="bar-list">
      <div v-for="item in data.proportions" :key="item.domain_name" class="bar-row">
        <div class="bar-label">{{ item.domain_name }}</div>
        <div class="bar-track">
          <div
            v-if="item.low > 0"
            class="bar-seg seg-low"
            :style="{ width: pct(item.low) }"
            :title="`低风险 ${pctStr(item.low)}`"
          >
            <span v-if="item.low >= 0.08">{{ pctStr(item.low) }}</span>
          </div>
          <div
            v-if="item.unclear > 0"
            class="bar-seg seg-unclear"
            :style="{ width: pct(item.unclear) }"
            :title="`不清楚 ${pctStr(item.unclear)}`"
          >
            <span v-if="item.unclear >= 0.08">{{ pctStr(item.unclear) }}</span>
          </div>
          <div
            v-if="item.high > 0"
            class="bar-seg seg-high"
            :style="{ width: pct(item.high) }"
            :title="`高风险 ${pctStr(item.high)}`"
          >
            <span v-if="item.high >= 0.08">{{ pctStr(item.high) }}</span>
          </div>
          <div
            v-if="item.na > 0"
            class="bar-seg seg-na"
            :style="{ width: pct(item.na) }"
            :title="`不适用 ${pctStr(item.na)}`"
          >
            <span v-if="item.na >= 0.08">{{ pctStr(item.na) }}</span>
          </div>
        </div>
        <div class="bar-total">n={{ item.total || 0 }}</div>
      </div>
    </div>
    <!-- 图例 -->
    <div class="chart-legend">
      <span class="legend-item"><span class="leg-dot seg-low"></span>低风险</span>
      <span class="legend-item"><span class="leg-dot seg-unclear"></span>不清楚</span>
      <span class="legend-item"><span class="leg-dot seg-high"></span>高风险</span>
      <span class="legend-item"><span class="leg-dot seg-na"></span>不适用</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  data:  { type: Object, required: true },
  title: { type: String, default: '' },
})

function pct(v) { return (v * 100).toFixed(1) + '%' }
function pctStr(v) { return (v * 100).toFixed(0) + '%' }
</script>

<style scoped>
.proportion-chart { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; }
.chart-title { font-size: 0.85rem; font-weight: 600; color: #1e293b; margin-bottom: 12px; }
.bar-list { display: flex; flex-direction: column; gap: 10px; }
.bar-row { display: flex; align-items: center; gap: 10px; }
.bar-label { width: 100px; font-size: 0.75rem; color: #475569; text-align: right; flex-shrink: 0; }
.bar-track { flex: 1; height: 28px; background: #f1f5f9; border-radius: 6px; display: flex; overflow: hidden; }
.bar-seg { height: 100%; display: flex; align-items: center; justify-content: center; font-size: 0.68rem; color: #fff; font-weight: 600; transition: width 0.4s ease; overflow: hidden; min-width: 0; }
.seg-low     { background: #059669; }
.seg-unclear { background: #d97706; }
.seg-high    { background: #dc2626; }
.seg-na      { background: #94a3b8; }
.bar-total { font-size: 0.68rem; color: #94a3b8; width: 40px; flex-shrink: 0; }
.chart-legend { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 12px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.legend-item { font-size: 0.72rem; color: #475569; display: flex; align-items: center; gap: 4px; }
.leg-dot { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
</style>
