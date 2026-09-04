<template>
  <div class="qa-chart">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#06b6d4,#3b82f6)">
        <i class="fas fa-chart-bar"></i>
      </div>
      <div>
        <h3 class="step-title">结果可视化</h3>
        <p class="step-subtitle">交互式预览评估图表，编辑文献名后点击「生成图片」导出 PNG</p>
      </div>
    </div>

    <!-- 配置控制区 -->
    <div class="gen-control">
      <div class="ctrl-row">
        <div class="ctrl-item">
          <span class="ctrl-label">评价方法</span>
          <select v-model="chartMethod" class="qa-select" @change="doPreview">
            <option v-for="m in qa.methods.filter(m => m.ai_supported)" :key="m.key" :value="m.key">
              {{ m.name }}
            </option>
          </select>
        </div>
        <div class="ctrl-item">
          <span class="ctrl-label">包含文献</span>
          <select v-model="refScope" class="qa-select" @change="doPreview">
            <option value="confirmed">仅已确认</option>
            <option value="all">全部已评价</option>
          </select>
        </div>
        <div class="ctrl-item">
          <span class="ctrl-label">交通灯方向</span>
          <select v-model="orientation" class="qa-select">
            <option value="horizontal">横向（研究=列）</option>
            <option value="vertical">纵向（研究=行）</option>
          </select>
        </div>
        <!-- 生成图片（调 matplotlib 生成 PNG 并自动下载） -->
        <button
          class="btn-generate"
          @click="doGenerateAndDownload"
          :disabled="qa.chartLoading || !qa.chartData"
          title="调用后端渲染高清 PNG 并自动下载"
        >
          <i class="fas fa-spinner fa-spin" v-if="qa.chartLoading"></i>
          <i class="fas fa-image" v-else></i>
          {{ qa.chartLoading ? '生成中...' : '生成图片' }}
        </button>
      </div>
    </div>

    <!-- 加载预览中 -->
    <div v-if="qa.chartPreviewLoading" class="preview-loading">
      <i class="fas fa-spinner fa-spin"></i>
      <span>加载预览中...</span>
    </div>

    <!-- 图表预览区（前端渲染） -->
    <template v-else-if="qa.chartData">

      <!-- 图表信息栏 -->
      <div class="chart-toolbar">
        <span class="chart-meta">
          共 {{ refCount }} 篇文献 · {{ qa.chartData.quality_method }}
          <template v-if="qa.chartData.unconfirmed_count">
            · <span class="warn-text">{{ qa.chartData.unconfirmed_count }} 篇未确认</span>
          </template>
        </span>
        <div class="chart-toolbar-actions">
          <button class="tb-btn" @click="doPreview" :disabled="qa.chartPreviewLoading">
            <i class="fas fa-sync-alt"></i> 刷新预览
          </button>
        </div>
      </div>

      <!-- 文献名编辑提示 -->
      <div class="label-edit-tip">
        <i class="fas fa-pencil-alt"></i>
        点击下方交通灯图中的文献名可直接编辑，编辑完成后点击「生成图片」导出带自定义名称的 PNG
      </div>

      <!-- 图表标签切换 -->
      <div class="chart-tabs">
        <button
          v-for="tab in chartTabs"
          :key="tab.key"
          :class="['chart-tab', { active: activeChartTab === tab.key }]"
          @click="activeChartTab = tab.key"
        >
          <i :class="tab.icon"></i>
          {{ tab.label }}
        </button>
      </div>

      <!-- 交通灯图 -->
      <div v-show="activeChartTab === 'traffic'">
        <QATrafficLight
          v-if="trafficLightData"
          :data="trafficLightData"
          title="偏倚风险评估图（Risk of Bias Summary）"
          :editable="true"
          v-model:studyLabels="studyLabels"
        />
        <div v-else class="chart-empty">暂无交通灯图数据</div>
      </div>

      <!-- 比例图 -->
      <div v-show="activeChartTab === 'proportion'">
        <QAProportionChart
          v-if="proportionData"
          :data="proportionData"
          title="偏倚风险比例图（Risk of Bias Graph）"
        />
        <div v-else class="chart-empty">暂无比例图数据</div>
      </div>

      <!-- 明细表格 -->
      <div v-show="activeChartTab === 'table'">
        <QADetailTable
          v-if="tableData"
          :data="tableData"
          title="评价结果明细"
        />
        <div v-else class="chart-empty">暂无表格数据</div>
      </div>

    </template>

    <!-- 未加载时占位 -->
    <div v-else class="chart-placeholder">
      <i class="fas fa-chart-bar" style="font-size:2.5rem;color:#e2e8f0"></i>
      <p>暂无数据，请确保已完成结果审核</p>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useQAStore } from '@/stores/qa'
import { useProjectStore } from '@/stores/project'
import QATrafficLight    from './QATrafficLight.vue'
import QAProportionChart from './QAProportionChart.vue'
import QADetailTable     from './QADetailTable.vue'

const qa      = useQAStore()
const project = useProjectStore()

const chartMethod    = ref('QUADAS2')
const refScope       = ref('confirmed')
const orientation    = ref('horizontal')
const activeChartTab = ref('traffic')

// 文献名自定义标签：{ ref_id_str: label }
const studyLabels = reactive({})

// 当 chartData 刷新时，用默认值初始化（不覆盖用户已修改的）
watch(() => qa.chartData, (d) => {
  if (!d || !Array.isArray(d.traffic_light)) return
  d.traffic_light.forEach(row => {
    const id = String(row.ref_id)
    if (!(id in studyLabels)) {
      studyLabels[id] = row.title || `Ref ${row.ref_id}`
    }
  })
})

const chartTabs = [
  { key: 'traffic',    icon: 'fas fa-traffic-light', label: '交通灯图' },
  { key: 'proportion', icon: 'fas fa-chart-bar',      label: '比例图' },
  { key: 'table',      icon: 'fas fa-table',           label: '明细表格' },
]

// ── 数据适配 ─────────────────────────────────────────────────────────────────

const trafficLightData = computed(() => {
  const d = qa.chartData
  if (!d || !Array.isArray(d.traffic_light)) return null

  const biasDomains   = d.bias_domains  || []
  const applicDomains = d.applic_domains || []
  const allDomains = [
    ...biasDomains.map(x => ({ key: x.key, name: x.name, type: 'bias' })),
    ...applicDomains.map(x => ({ key: x.key, name: x.name, type: 'applic' })),
  ]

  return {
    n_bias:       biasDomains.length,
    n_applic:     applicDomains.length,
    domain_names: allDomains.map(x => x.name),
    refs: d.traffic_light.map(row => ({
      id:    row.ref_id,
      title: row.title || `文献 ${row.ref_id}`,
      bias_results: allDomains.map(x =>
        x.type === 'bias'
          ? (row.bias_risk?.[x.key] || 'pending')
          : (row.applicability?.[x.key] || 'na')
      ),
    })),
  }
})

const proportionData = computed(() => {
  const d = qa.chartData
  if (!d || !d.proportion || typeof d.proportion !== 'object') return null

  const proportions = Object.values(d.proportion).map(item => {
    const counts = item.counts || {}
    const total  = Object.values(counts).reduce((s, v) => s + v, 0) || 1
    return {
      domain_name: item.domain_name,
      low:     (counts.low     || 0) / total,
      high:    (counts.high    || 0) / total,
      unclear: (counts.unclear || 0) / total,
      na:      (counts.pending || 0) / total,
      total:   Object.values(counts).reduce((s, v) => s + v, 0),
    }
  })

  return { proportions }
})

const tableData = computed(() => {
  const d = qa.chartData
  if (!d || !Array.isArray(d.traffic_light) || !d.traffic_light.length) return null

  const biasDomains   = d.bias_domains  || []
  const applicDomains = d.applic_domains || []
  const columns = [
    ...biasDomains.map(x => x.name),
    ...applicDomains.map(x => `${x.name}(适用性)`),
  ]
  const riskLabel = r => ({ low: '低风险', high: '高风险', unclear: '不清楚', pending: '待定', na: '不适用' })[r] || r
  const rows = d.traffic_light.map(row => ({
    title: row.title || `文献 ${row.ref_id}`,
    values: [
      ...biasDomains.map(x  => riskLabel(row.bias_risk?.[x.key]   || 'pending')),
      ...applicDomains.map(x => riskLabel(row.applicability?.[x.key] || 'na')),
    ],
  }))

  return { columns, rows }
})

const refCount = computed(() =>
  Array.isArray(qa.chartData?.traffic_light) ? qa.chartData.traffic_light.length : 0
)

// ── 操作 ─────────────────────────────────────────────────────────────────────

function _getRefIds() {
  return refScope.value === 'confirmed'
    ? qa.confirmedRefs.map(r => r.id)
    : qa.refs.filter(r => r.ai_eval_status !== 'pending').map(r => r.id)
}

/** 快速预览：仅拿数据，不调 matplotlib，进入页面自动触发 */
async function doPreview() {
  if (!project.currentProject) return
  const refIds = _getRefIds()
  if (!refIds.length) return
  try {
    await qa.previewChart(project.currentProject.id, chartMethod.value, refIds)
  } catch (e) {
    console.warn('[QAStepChart] previewChart failed', e)
  }
}

/** 生成图片：调用 matplotlib 生成高清 PNG 并自动触发下载 */
async function doGenerateAndDownload() {
  if (!project.currentProject) return
  const refIds = _getRefIds()
  if (!refIds.length) {
    alert(refScope.value === 'confirmed' ? '暂无已确认的文献，请先完成结果审核' : '暂无已评价的文献')
    return
  }
  try {
    await qa.generateChart(
      project.currentProject.id,
      chartMethod.value,
      refIds,
      { ...studyLabels },
      orientation.value,
    )
    // 自动下载两张图片
    const method = qa.chartData?.quality_method || ''
    const tl  = qa.chartData?.traffic_light_image
    const sum = qa.chartData?.proportion_image
    if (!tl && !sum) { alert('图片生成失败，请重试'); return }
    if (tl)  _dl(tl,  `qa_traffic_light_${method}.png`)
    if (sum) setTimeout(() => _dl(sum, `qa_proportion_${method}.png`), 200)
  } catch (e) {
    alert(e?.response?.data?.error || '图片生成失败')
  }
}

function _dl(dataUrl, filename) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  a.click()
}

// ── 初始化：进入页面自动加载预览 ─────────────────────────────────────────────

onMounted(async () => {
  if (qa.methods.length === 0) await qa.fetchMethods()
  if (qa.methods.length) {
    chartMethod.value = qa.methods.find(m => m.ai_supported)?.key || 'QUADAS2'
  }
  await doPreview()
})
</script>

<style scoped>
.qa-chart { display: flex; flex-direction: column; gap: 14px; }
.step-header { display: flex; align-items: center; gap: 12px; }
.step-icon-wrap { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.step-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.step-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }

/* 控制区 */
.gen-control { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; }
.ctrl-row { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.ctrl-item { display: flex; flex-direction: column; gap: 4px; }
.ctrl-label { font-size: 0.72rem; color: #64748b; }
.qa-select { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.82rem; background: #fff; }

/* 生成图片按钮 */
.btn-generate {
  padding: 8px 18px;
  background: linear-gradient(135deg, #06b6d4, #3b82f6);
  color: #fff; border: none; border-radius: 9px;
  cursor: pointer; font-size: 0.85rem;
  display: flex; align-items: center; gap: 6px;
  align-self: flex-end;
}
.btn-generate:disabled { opacity: 0.5; cursor: not-allowed; }

/* 加载预览中 */
.preview-loading {
  display: flex; align-items: center; gap: 10px;
  justify-content: center; padding: 40px;
  color: #64748b; font-size: 0.85rem;
}

/* 图表工具栏 */
.chart-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 0; }
.chart-meta { font-size: 0.72rem; color: #94a3b8; }
.warn-text { color: #f59e0b; font-weight: 500; }
.chart-toolbar-actions { display: flex; gap: 6px; }
.tb-btn { padding: 6px 12px; background: #fff; border: 1px solid #e2e8f0; border-radius: 7px; cursor: pointer; font-size: 0.78rem; color: #475569; display: flex; align-items: center; gap: 5px; }
.tb-btn:hover:not(:disabled) { border-color: #6366f1; color: #6366f1; }
.tb-btn:disabled { opacity: 0.45; cursor: not-allowed; }

/* 文献名编辑提示 */
.label-edit-tip {
  background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
  padding: 8px 14px; font-size: 0.75rem; color: #92400e;
  display: flex; align-items: center; gap: 8px;
}

/* 图表 tabs */
.chart-tabs { display: flex; gap: 4px; }
.chart-tab { padding: 7px 16px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; font-size: 0.8rem; color: #64748b; display: flex; align-items: center; gap: 6px; }
.chart-tab:hover { border-color: #6366f1; color: #6366f1; }
.chart-tab.active { background: #eef2ff; border-color: #6366f1; color: #4f46e5; font-weight: 500; }

/* 空状态 */
.chart-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 60px; color: #94a3b8; font-size: 0.85rem; border: 2px dashed #e2e8f0; border-radius: 12px; }
.chart-empty { text-align: center; color: #94a3b8; font-size: 0.82rem; padding: 30px; }
</style>
