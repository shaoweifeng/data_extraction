<template>
  <div class="ai-layout">
    <section class="ai-left">
      <div class="rs-head">
        <div>
          <h3>AI 全文复筛</h3>
          <p>复用初筛 AI 任务页心智：模型、Prompt、进度、待处理/已完成列表；输入改为 PDF 全文。</p>
        </div>
        <button class="primary-btn" :disabled="rescreen.aiRunning || rescreen.boundRefs.length === 0" @click="runAiRescreen">
          <i :class="rescreen.aiRunning ? 'fas fa-spinner fa-spin' : 'fas fa-play'"></i>
          {{ rescreen.aiRunning ? '复筛中…' : '开始 AI 复筛' }}
        </button>
      </div>

      <div class="panel">
        <div class="panel-title"><h4>任务输入</h4><span>仅处理已绑定全文</span></div>
        <div class="task-grid">
          <div><b>{{ rescreen.boundRefs.length }}</b><span>可进入 AI</span></div>
          <div><b>{{ rescreen.totalRefs - rescreen.boundRefs.length }}</b><span>跳过无全文</span></div>
          <div><b>{{ rescreen.criteriaList.length }}</b><span>复筛标准</span></div>
        </div>
        <div class="progress"><div :style="{ width: `${rescreen.aiProgress}%` }"></div></div>
      </div>

      <div class="panel">
        <div class="panel-title"><h4>Prompt 摘要</h4><span>来自纳排标准</span></div>
        <ul class="criteria-mini">
          <li v-for="item in rescreen.criteriaList" :key="item">{{ item }}</li>
        </ul>
      </div>
    </section>

    <section class="ai-right panel">
      <div class="panel-title"><h4>AI 结果预览</h4><span>最终仍需人工确认</span></div>
      <div v-for="ref in rescreen.refs" :key="ref.id" class="result-item">
        <div>
          <strong>{{ ref.title }}</strong>
          <p>{{ ref.ai_reason || (ref.fulltext_status === 'bound' ? '待 AI 复筛' : '无可用全文，跳过 AI') }}</p>
        </div>
        <span :class="['decision', ref.ai_decision || ref.ai_status]">{{ decisionLabel(ref) }}</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { useProjectStore } from '@/features/projects/store'
import { useRescreenStore } from '@/features/rescreening/store'
const project = useProjectStore()
const rescreen = useRescreenStore()
function decisionLabel(ref) {
  if (ref.ai_status === 'skipped_unbound') return '跳过'
  return { included: '建议纳入', excluded: '建议排除', pending: '待定' }[ref.ai_decision] || '未开始'
}
function runAiRescreen() {
  rescreen.runAiRescreen(project.currentProject?.id)
}
</script>

<style scoped>
.ai-layout{display:grid;grid-template-columns:420px minmax(0,1fr);gap:16px;min-height:0}.ai-left{display:flex;flex-direction:column;gap:16px}.rs-head,.panel{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px;box-shadow:0 8px 20px rgba(15,23,42,.04)}.rs-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}h3,h4,p{margin:0}h3{font-size:1.05rem;color:#1e293b}.rs-head p,.panel-title span,.result-item p{font-size:.78rem;color:#64748b;margin-top:4px;line-height:1.5}.primary-btn{display:inline-flex;align-items:center;gap:7px;border:0;border-radius:10px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;padding:10px 14px;font-weight:700;cursor:pointer;white-space:nowrap}.primary-btn:disabled{opacity:.55;cursor:not-allowed}.panel-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.task-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.task-grid div{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:12px}.task-grid b{font-size:1.3rem;color:#1e293b;margin-right:6px}.task-grid span{font-size:.76rem;color:#64748b}.progress{height:8px;background:#eef2ff;border-radius:999px;overflow:hidden;margin-top:14px}.progress div{height:100%;background:linear-gradient(90deg,#6366f1,#8b5cf6);transition:width .3s}.criteria-mini{margin:0;padding-left:18px;color:#475569;font-size:.82rem}.criteria-mini li{margin:7px 0}.ai-right{overflow:auto}.result-item{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:13px 0;border-bottom:1px solid #f1f5f9}.result-item strong{font-size:.86rem;color:#1e293b}.decision{flex-shrink:0;border-radius:999px;padding:4px 9px;font-size:.74rem;font-weight:700;background:#f8fafc;color:#64748b}.decision.included{background:#ecfdf5;color:#047857}.decision.pending{background:#fffbeb;color:#b45309}.decision.skipped_unbound{background:#f1f5f9;color:#64748b}@media(max-width:1100px){.ai-layout{grid-template-columns:1fr}}
</style>
