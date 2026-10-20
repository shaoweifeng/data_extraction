<template>
  <div class="rs-page">
    <section class="rs-head">
      <div class="rs-head-icon"><i class="fas fa-file-export"></i></div>
      <div>
        <h3>结果导出</h3>
        <p>复用初筛导出卡片和质量评价导出反馈；新增 PDF 包与缺失清单。</p>
      </div>
    </section>

    <div class="summary-grid">
      <div><b>{{ rescreen.totalRefs }}</b><span>全部文献</span></div>
      <div><b>{{ rescreen.includedRefs.length }}</b><span>人工纳入</span></div>
      <div><b>{{ rescreen.excludedRefs.length }}</b><span>人工排除</span></div>
      <div><b>{{ missingPdfCount }}</b><span>缺失 PDF</span></div>
    </div>

    <section v-if="blockingMessages.length" class="block-card">
      <h4><i class="fas fa-circle-exclamation"></i> 导出前需要处理</h4>
      <ul><li v-for="msg in blockingMessages" :key="msg">{{ msg }}</li></ul>
    </section>

    <div class="export-grid">
      <article v-for="item in exports" :key="item.key" class="export-card">
        <div class="export-icon"><i :class="item.icon"></i></div>
        <h4>{{ item.title }}</h4>
        <p>{{ item.desc }}</p>
        <button :disabled="exportingKey === item.key || (item.final && blockingMessages.length)" @click="doExport(item)">
          {{ exportingKey === item.key ? '导出中…' : '导出' }}
        </button>
      </article>
    </div>

    <section class="history-card">
      <h4>导出历史</h4>
      <div class="history-row"><span>复筛结果汇总.xlsx</span><em>点击导出后由后端实时生成</em></div>
      <div class="history-row"><span>纳入文献PDF包.zip</span><em>待生成</em></div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useProjectStore } from '@/features/projects/store'
import { useDownload } from '@/shared/composables/useDownload'
import { useRescreenStore } from '@/features/rescreening/store'
import * as rescreenApi from '@/features/rescreening/api'
const project = useProjectStore()
const rescreen = useRescreenStore()
const { downloadBlob } = useDownload()
const missingPdfCount = computed(() => rescreen.missingPdfCount)
const blockingMessages = computed(() => rescreen.exportBlockingMessages)
const exportingKey = ref('')
const exports = [
  { key: 'all', scope: 'all', type: 'excel', title: '全部复筛结果 Excel', desc: '包含题录、全文状态、AI 建议、人工最终判断。', icon: 'fas fa-table', final: true },
  { key: 'included', scope: 'included', type: 'excel', title: '最终纳入文献 Excel', desc: '仅导出人工最终纳入文献。', icon: 'fas fa-check-circle', final: true },
  { key: 'excluded', scope: 'excluded', type: 'excel', title: '最终排除文献 Excel', desc: '包含排除理由和审阅人信息。', icon: 'fas fa-ban', final: true },
  { key: 'pdf', scope: 'included', type: 'pdf', title: '纳入文献 PDF 包', desc: '打包导出最终纳入文献对应全文 PDF。', icon: 'fas fa-file-archive', final: false },
  { key: 'missing', scope: 'missing_pdf', type: 'excel', title: '缺失 PDF 清单', desc: '列出未绑定或绑定失败文献，便于人工补全文。', icon: 'fas fa-list-ul', final: false },
]
async function doExport(item) {
  const projectId = project.currentProject?.id
  if (!projectId) {
    window.alert('当前没有可导出的项目')
    return
  }
  exportingKey.value = item.key
  try {
    const payload = { project_id: projectId, scope: item.scope }
    if (item.type === 'pdf') {
      const response = await rescreenApi.exportPdfPackage(payload)
      downloadBlob(response.data, `rescreening_included_pdfs_${new Date().toISOString().slice(0, 10)}.zip`)
    } else {
      const response = await rescreenApi.exportExcel(payload)
      downloadBlob(response.data, `rescreening_${item.scope}_${new Date().toISOString().slice(0, 10)}.xlsx`)
    }
  } catch (error) {
    window.alert(error?.response?.data?.error || `${item.title} 导出失败`)
  } finally {
    exportingKey.value = ''
  }
}
</script>

<style scoped>
.rs-page{display:flex;flex-direction:column;gap:16px}.rs-head{display:flex;align-items:center;gap:14px;background:#fff;border:1px solid #eef2f7;border-radius:14px;padding:18px 20px;box-shadow:0 8px 20px rgba(15,23,42,.04)}.rs-head-icon{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#f59e0b,#fb923c);color:#fff;display:flex;align-items:center;justify-content:center}h3,h4,p{margin:0}h3{font-size:1.05rem;color:#1e293b}.rs-head p{font-size:.8rem;color:#64748b;margin-top:4px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.summary-grid div{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:15px 16px}.summary-grid b{font-size:1.4rem;color:#1e293b;margin-right:8px}.summary-grid span{font-size:.78rem;color:#64748b}.block-card{background:#fff7ed;border:1px solid #fed7aa;border-radius:14px;padding:14px 16px;color:#9a3412}.block-card h4{display:flex;gap:8px;align-items:center}.block-card ul{margin:8px 0 0;padding-left:22px;font-size:.82rem}.export-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.export-card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:10px;min-height:185px;box-shadow:0 8px 20px rgba(15,23,42,.04)}.export-icon{width:42px;height:42px;border-radius:12px;background:#eef2ff;color:#4f46e5;display:flex;align-items:center;justify-content:center}.export-card p{font-size:.8rem;color:#64748b;line-height:1.5}.export-card button{margin-top:auto;border:0;border-radius:9px;background:#4f46e5;color:#fff;padding:9px 12px;font-weight:700;cursor:pointer}.export-card button:disabled{background:#cbd5e1;cursor:not-allowed}.history-card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:16px}.history-row{display:flex;justify-content:space-between;padding:10px 0;border-top:1px solid #f1f5f9;font-size:.84rem}.history-row em{color:#94a3b8;font-style:normal}@media(max-width:1100px){.export-grid,.summary-grid{grid-template-columns:1fr 1fr}}
</style>
