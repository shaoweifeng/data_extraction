<template>
  <div class="qa-export">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#10b981,#06b6d4)">
        <i class="fas fa-file-export"></i>
      </div>
      <div>
        <h3 class="step-title">导出报告</h3>
        <p class="step-subtitle">导出质量评价图表与 Excel 明细，用于论文写作</p>
      </div>
    </div>

    <!-- 导出配置 -->
    <div class="export-config">
      <div class="config-row">
        <div class="config-item">
          <span class="config-label">评价方法</span>
          <select v-model="exportMethod" class="qa-select">
            <option v-for="m in qa.methods.filter(m => m.ai_supported)" :key="m.key" :value="m.key">
              {{ m.name }}
            </option>
          </select>
        </div>
        <div class="config-item">
          <span class="config-label">交通灯方向</span>
          <select v-model="qa.chartOrientation" class="qa-select">
            <option value="horizontal">横向（研究=列）</option>
            <option value="vertical">纵向（研究=行）</option>
          </select>
        </div>
        <div class="config-item">
          <span class="config-label">图例语言</span>
          <select v-model="qa.chartLang" class="qa-select">
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
        <div class="config-item">
          <label class="checkbox-label">
            <input type="checkbox" v-model="includeUnconfirmed" />
            <span>包含未完全确认的文献</span>
          </label>
        </div>
      </div>
    </div>

    <!-- 导出卡片 -->
    <div class="export-cards">
      <!-- 图片导出卡 -->
      <div class="export-card">
        <div class="card-icon" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">
          <i class="fas fa-image"></i>
        </div>
        <div class="card-body">
          <h4 class="card-title">偏倚风险图（图片）</h4>
          <p class="card-desc">导出 PNG 格式的交通灯图和比例图，按上方配置的方向和图例语言实时生成，可直接插入论文</p>
          <ul class="card-features">
            <li><i class="fas fa-check" style="color:#10b981"></i> Risk of Bias Summary（交通灯图）</li>
            <li><i class="fas fa-check" style="color:#10b981"></i> Risk of Bias Graph（比例条形图）</li>
            <li><i class="fas fa-check" style="color:#10b981"></i> 高分辨率 PNG（300dpi）</li>
          </ul>
        </div>
        <div class="card-actions">
          <div class="card-stat">
            {{ qa.confirmedRefs.length }} 篇已确认
          </div>
          <button
            class="btn-export"
            style="background:linear-gradient(135deg,#6366f1,#8b5cf6)"
            @click="doExportImage"
            :disabled="exportingImage || !qa.confirmedRefs.length"
          >
            <i class="fas fa-spinner fa-spin" v-if="exportingImage"></i>
            <i class="fas fa-download" v-else></i>
            {{ exportingImage ? '导出中...' : '下载图片' }}
          </button>
        </div>
      </div>

      <!-- Excel 导出卡 -->
      <div class="export-card">
        <div class="card-icon" style="background:linear-gradient(135deg,#10b981,#059669)">
          <i class="fas fa-file-excel"></i>
        </div>
        <div class="card-body">
          <h4 class="card-title">评价明细（Excel）</h4>
          <p class="card-desc">导出包含所有信号问题评价结果的 Excel 文件，便于数据核查</p>
          <ul class="card-features">
            <li><i class="fas fa-check" style="color:#10b981"></i> Sheet 1：文献概览与领域评估</li>
            <li><i class="fas fa-check" style="color:#10b981"></i> Sheet 2：信号问题逐条明细</li>
            <li><i class="fas fa-check" style="color:#10b981"></i> Sheet 3：AI 评价 vs 人工确认对比</li>
            <li><i class="fas fa-check" style="color:#10b981"></i> Sheet 4：方法说明</li>
          </ul>
        </div>
        <div class="card-actions">
          <div class="card-stat">
            {{ totalCount }} 篇文献 · {{ confirmedSignalCount }} 条已确认
          </div>
          <button
            class="btn-export"
            style="background:linear-gradient(135deg,#10b981,#059669)"
            @click="doExportExcel"
            :disabled="exportingExcel || !qa.refs.length"
          >
            <i class="fas fa-spinner fa-spin" v-if="exportingExcel"></i>
            <i class="fas fa-download" v-else></i>
            {{ exportingExcel ? '导出中...' : '下载 Excel' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 导出历史 -->
    <div v-if="exportHistory.length" class="export-history">
      <h4 class="history-title">最近导出记录</h4>
      <div class="history-list">
        <div v-for="(h, i) in exportHistory" :key="i" class="history-item">
          <i :class="['history-icon', h.type === 'image' ? 'fas fa-image' : 'fas fa-file-excel']"
             :style="{ color: h.type === 'image' ? '#6366f1' : '#10b981' }"></i>
          <span class="history-name">{{ h.name }}</span>
          <span class="history-time">{{ h.time }}</span>
          <a :href="h.url" download class="history-dl" v-if="h.url">
            <i class="fas fa-download"></i>
          </a>
        </div>
      </div>
    </div>

    <!-- 完成提示 -->
    <div class="complete-banner">
      <i class="fas fa-party-horn" style="color:#f59e0b;font-size:1.4rem"></i>
      <div>
        <p class="banner-title">质量评价流程已完成！</p>
        <p class="banner-desc">您已完成文献质量评价的全部步骤，可以在此导出结果用于研究报告。</p>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useQAStore } from '@/features/quality/store'
import { useProjectStore } from '@/features/projects/store'

const qa      = useQAStore()
const project = useProjectStore()

const exportMethod       = ref('QUADAS2')
const includeUnconfirmed = ref(false)
const exportingImage     = ref(false)
const exportingExcel     = ref(false)
const exportHistory      = ref([])

const totalCount = computed(() => qa.refs.length)
const confirmedSignalCount = computed(() => {
  // 粗略估计：已确认文献 × 平均信号问题数
  return qa.confirmedRefs.length * 11
})

onMounted(async () => {
  if (qa.methods.length === 0) await qa.fetchMethods()
  if (qa.methods.length) exportMethod.value = qa.methods.find(m => m.ai_supported)?.key || 'QUADAS2'
})
onUnmounted(() => qa.cancelChartGeneration())

async function doExportImage() {
  if (!project.currentProject) return
  exportingImage.value = true
  try {
    const refIds = includeUnconfirmed.value
      ? qa.refs.map(r => r.id)
      : qa.confirmedRefs.map(r => r.id)
    if (!refIds.length) {
      alert(includeUnconfirmed.value ? '暂无已评价的文献' : '暂无已确认的文献，请先完成结果审核')
      return
    }

    // 从数据库读取用户自定义文献名（与 Step5 保持一致）
    const studyLabels = await qa.fetchChartSettings(project.currentProject.id, exportMethod.value)

    // 始终重新生成，确保 orientation / lang / studyLabels 都是最新值
    await qa.generateChart(
      project.currentProject.id,
      exportMethod.value,
      refIds,
      studyLabels,
      qa.chartOrientation,
      qa.chartLang,
    )

    const method = qa.chartData?.quality_method || exportMethod.value
    if (qa.chartData?.traffic_light_image) {
      _dl(qa.chartData.traffic_light_image, `qa_traffic_light_${method}.png`)
      addHistory('image', `qa_traffic_light_${method}.png`, null)
    }
    if (qa.chartData?.proportion_image) {
      setTimeout(() => _dl(qa.chartData.proportion_image, `qa_proportion_${method}.png`), 200)
      addHistory('image', `qa_proportion_${method}.png`, null)
    }
    if (!qa.chartData?.traffic_light_image && !qa.chartData?.proportion_image) {
      alert('图片生成失败，请重试')
    }
  } catch (e) {
    if (e?.name === 'AbortError') return
    alert('导出失败：' + (e?.response?.data?.error || e?.message || e))
  } finally {
    exportingImage.value = false
  }
}

function _dl(dataUrl, filename) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  a.click()
}

async function doExportExcel() {
  exportingExcel.value = true
  try {
    await qa.exportExcel(project.currentProject.id, exportMethod.value, includeUnconfirmed.value)
    const name = `qa_export_${exportMethod.value}_${new Date().toISOString().slice(0,10)}.xlsx`
    addHistory('excel', name, null)
  } catch (e) {
    alert(e?.response?.data?.error || 'Excel 导出失败')
  } finally {
    exportingExcel.value = false
  }
}

function addHistory(type, name, url) {
  exportHistory.value.unshift({
    type, name, url,
    time: new Date().toLocaleTimeString('zh-CN'),
  })
  if (exportHistory.value.length > 5) exportHistory.value.pop()
}

function confirmReset() {
  if (confirm('确认重置？这将清除当前质量评价的所有状态，但不会删除已导入的文献数据。')) {
    qa.reset()
  }
}
</script>

<style scoped>
.qa-export { display: flex; flex-direction: column; gap: 16px; }
.step-header { display: flex; align-items: center; gap: 12px; }
.step-icon-wrap { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.step-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.step-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }

/* 配置 */
.export-config { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; }
.config-row { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.config-item { display: flex; align-items: center; gap: 8px; }
.config-label { font-size: 0.78rem; color: #64748b; }
.qa-select { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.82rem; background: #fff; }
.checkbox-label { display: flex; align-items: center; gap: 6px; font-size: 0.82rem; cursor: pointer; color: #475569; }

/* 导出卡片 */
.export-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 640px) { .export-cards { grid-template-columns: 1fr; } }
.export-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.card-icon { width: 48px; height: 48px; border-radius: 14px; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 1.3rem; }
.card-title { font-size: 0.95rem; font-weight: 600; color: #1e293b; margin: 0 0 6px; }
.card-desc { font-size: 0.78rem; color: #64748b; margin: 0 0 10px; }
.card-features { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.card-features li { font-size: 0.75rem; color: #475569; display: flex; align-items: center; gap: 6px; }
.card-actions { display: flex; align-items: center; justify-content: space-between; padding-top: 6px; border-top: 1px solid #f1f5f9; }
.card-stat { font-size: 0.72rem; color: #94a3b8; }
.btn-export { padding: 8px 18px; color: #fff; border: none; border-radius: 9px; cursor: pointer; font-size: 0.82rem; display: flex; align-items: center; gap: 6px; }
.btn-export:disabled { opacity: 0.5; cursor: not-allowed; }

/* 历史记录 */
.export-history { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; }
.history-title { font-size: 0.82rem; font-weight: 600; color: #1e293b; margin: 0 0 10px; }
.history-list { display: flex; flex-direction: column; gap: 6px; }
.history-item { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; color: #475569; }
.history-icon { width: 16px; }
.history-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-time { color: #94a3b8; flex-shrink: 0; }
.history-dl { color: #6366f1; text-decoration: none; }

/* 完成提示 */
.complete-banner { background: linear-gradient(135deg, #fef9c3, #fef3c7); border: 1px solid #fde68a; border-radius: 12px; padding: 16px 20px; display: flex; align-items: flex-start; gap: 14px; }
.banner-title { font-size: 0.9rem; font-weight: 600; color: #78350f; margin: 0 0 4px; }
.banner-desc { font-size: 0.78rem; color: #92400e; margin: 0; }

/* 底部 */
.step-footer-actions { display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
.btn-secondary { padding: 8px 16px; background: #fff; color: #6366f1; border: 1px solid #6366f1; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-secondary:hover { background: #f5f3ff; }
.btn-reset { padding: 8px 16px; background: #fff; color: #94a3b8; border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-reset:hover { color: #ef4444; border-color: #fca5a5; }
</style>
