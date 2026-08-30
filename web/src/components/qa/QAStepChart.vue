<template>
  <div class="qa-chart">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#06b6d4,#3b82f6)">
        <i class="fas fa-chart-bar"></i>
      </div>
      <div>
        <h3 class="step-title">结果可视化</h3>
        <p class="step-subtitle">生成偏倚风险评估图表，支持交通灯图与比例图</p>
      </div>
    </div>

    <!-- 生成控制区 -->
    <div class="gen-control">
      <div class="ctrl-row">
        <div class="ctrl-item">
          <span class="ctrl-label">评价方法</span>
          <select v-model="chartMethod" class="qa-select">
            <option v-for="m in qa.methods.filter(m => m.ai_supported)" :key="m.key" :value="m.key">
              {{ m.name }}
            </option>
          </select>
        </div>
        <div class="ctrl-item">
          <span class="ctrl-label">包含文献</span>
          <select v-model="refScope" class="qa-select">
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
        <button
          class="btn-generate"
          @click="doGenerate"
          :disabled="qa.chartLoading || !chartMethod"
        >
          <i class="fas fa-spinner fa-spin" v-if="qa.chartLoading"></i>
          <i class="fas fa-chart-bar" v-else></i>
          {{ qa.chartLoading ? '生成中...' : '生成图表' }}
        </button>
      </div>
    </div>

    <!-- 图表区 -->
    <template v-if="qa.chartData">
      <!-- 导出工具栏 -->
      <div class="chart-toolbar">
        <span class="chart-meta">
          共 {{ refCount }} 篇文献 · {{ qa.chartData.quality_method }}
          · 生成于 {{ formatTime(qa.chartData.generated_at) }}
        </span>
        <div class="chart-toolbar-actions">
          <button class="tb-btn" @click="downloadImage"
            :disabled="downloadLoading"
            title="下载交通灯图 + 比例图（共两张 PNG）"
          >
            <i class="fas fa-spinner fa-spin" v-if="downloadLoading"></i>
            <i class="fas fa-download" v-else></i>
            {{ downloadLoading ? '下载中...' : '下载图片（2张）' }}
          </button>
        </div>
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

    <!-- 未生成时占位 -->
    <div v-else class="chart-placeholder">
      <i class="fas fa-chart-bar" style="font-size:2.5rem;color:#e2e8f0"></i>
      <p>点击「生成图表」开始可视化</p>
    </div>

    <!-- 底部操作 -->
    <div class="step-footer-actions">
      <button class="btn-secondary" @click="qa.currentStep = 4">
        <i class="fas fa-arrow-left"></i> 上一步
      </button>
      <button class="btn-primary" @click="qa.currentStep = 6">
        下一步：导出报告 <i class="fas fa-arrow-right"></i>
      </button>
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
const downloadLoading = ref(false)

// 文献名自定义标签：{ ref_id: label_str }
// 每次 chartData 刷新时用默认值初始化，用户修改后保留到下次生成
const studyLabels = reactive({})

watch(() => qa.chartData, (d) => {
  // 新数据加载时，把已有默认值填入（不覆盖用户已经改过的）
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

// ── 数据适配：把后端格式转换为子组件期望格式 ─────────────────────────────────

/**
 * 后端 traffic_light 是数组，bias_domains/applic_domains 是领域配置列表
 * 转换为 QATrafficLight 需要的 { domain_names, refs: [{ title, bias_results }] }
 */
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

/**
 * 后端 proportion 是对象 { domain_key: { domain_name, counts, percentages } }
 * 转换为 QAProportionChart 需要的 { proportions: [{ domain_name, low, high, unclear, na, total }] }
 */
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
      na:      (counts.pending || 0) / total,   // pending 展示为灰色
      total:   Object.values(counts).reduce((s, v) => s + v, 0),
    }
  })

  return { proportions }
})

/**
 * 明细表格：从 traffic_light 数组构建
 */
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

// ── 文献计数（用于工具栏展示）────────────────────────────────────────────────
const refCount = computed(() =>
  Array.isArray(qa.chartData?.traffic_light) ? qa.chartData.traffic_light.length : 0
)

onMounted(async () => {
  if (qa.methods.length === 0) await qa.fetchMethods()
  if (qa.methods.length) chartMethod.value = qa.methods.find(m => m.ai_supported)?.key || 'QUADAS2'
  if (project.currentProject) {
    await qa.fetchChartInfo(project.currentProject.id, chartMethod.value)
  }
})

async function doGenerate() {
  if (!project.currentProject) return
  const refIds = refScope.value === 'confirmed'
    ? qa.confirmedRefs.map(r => r.id)
    : qa.refs.filter(r => r.ai_eval_status !== 'pending').map(r => r.id)

  if (!refIds.length) {
    alert(refScope.value === 'confirmed' ? '暂无已确认的文献，请先完成结果审核' : '暂无已评价的文献')
    return
  }

  try {
    // 把用户自定义的文献名一起传给后端，robvis 用这些名称生成 PNG
    await qa.generateChart(project.currentProject.id, chartMethod.value, refIds, { ...studyLabels }, orientation.value)
  } catch (e) {
    alert(e?.response?.data?.error || '图表生成失败')
  }
}

// 下载图表图片：同时下载交通灯图 + 比例图
async function downloadImage() {
  downloadLoading.value = true
  try {
    const method = qa.chartData?.quality_method || ''
    const tl  = qa.chartData?.traffic_light_image
    const sum = qa.chartData?.proportion_image

    if (!tl && !sum) {
      alert('暂无图表，请先生成图表')
      return
    }
    if (tl)  _dl(tl,  `qa_traffic_light_${method}.png`)
    // 稍微延迟，避免浏览器合并两次下载
    if (sum) setTimeout(() => _dl(sum, `qa_proportion_${method}.png`), 200)
  } finally {
    downloadLoading.value = false
  }
}

function _dl(dataUrl, filename) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  a.click()
}

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}
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
.btn-generate { padding: 8px 18px; background: linear-gradient(135deg, #06b6d4, #3b82f6); color: #fff; border: none; border-radius: 9px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-generate:disabled { opacity: 0.5; cursor: not-allowed; }

/* 图表工具栏 */
.chart-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 0; }
.chart-meta { font-size: 0.72rem; color: #94a3b8; }
.chart-toolbar-actions { display: flex; gap: 6px; }
.tb-btn { padding: 6px 12px; background: #fff; border: 1px solid #e2e8f0; border-radius: 7px; cursor: pointer; font-size: 0.78rem; color: #475569; display: flex; align-items: center; gap: 5px; }
.tb-btn:hover:not(:disabled) { border-color: #6366f1; color: #6366f1; }
.tb-btn:disabled { opacity: 0.45; cursor: not-allowed; }

/* 图表 tabs */
.chart-tabs { display: flex; gap: 4px; }
.chart-tab { padding: 7px 16px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; font-size: 0.8rem; color: #64748b; display: flex; align-items: center; gap: 6px; }
.chart-tab:hover { border-color: #6366f1; color: #6366f1; }
.chart-tab.active { background: #eef2ff; border-color: #6366f1; color: #4f46e5; font-weight: 500; }

/* 空状态 */
.chart-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 60px; color: #94a3b8; font-size: 0.85rem; border: 2px dashed #e2e8f0; border-radius: 12px; }
.chart-empty { text-align: center; color: #94a3b8; font-size: 0.82rem; padding: 30px; }

/* 底部 */
.step-footer-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.btn-primary { padding: 8px 18px; background: #6366f1; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-primary:hover { background: #4f46e5; }
.btn-secondary { padding: 8px 16px; background: #fff; color: #6366f1; border: 1px solid #6366f1; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-secondary:hover { background: #f5f3ff; }
</style>
