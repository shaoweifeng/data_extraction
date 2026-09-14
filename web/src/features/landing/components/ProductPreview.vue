<template>
  <div class="preview-shell" role="img" aria-label="AI 文献初筛界面示意">
    <div class="preview-topbar">
      <div class="preview-brand"><i class="fas fa-flask"></i></div>
      <div>
        <strong>干预措施与结局研究</strong>
        <span>文献初筛 · AI 辅助判断</span>
      </div>
      <div class="preview-status"><i class="fas fa-circle-check"></i> 已保存</div>
    </div>

    <div class="preview-steps" aria-hidden="true">
      <span v-for="(step, index) in steps" :key="step" :class="{ active: index === 4, done: index < 4 }">
        <i v-if="index < 4" class="fas fa-check"></i>
        <template v-else>{{ index + 1 }}</template>
        <small>{{ step }}</small>
      </span>
    </div>

    <div class="preview-workspace">
      <aside class="preview-criteria">
        <div class="preview-pane-title"><i class="fas fa-list-check"></i> 纳排标准</div>
        <article>
          <span class="criteria-index include">I</span>
          <p><strong>目标人群</strong>符合预设疾病诊断标准</p>
        </article>
        <article>
          <span class="criteria-index exclude">E</span>
          <p><strong>研究类型</strong>排除综述、会议摘要及动物实验</p>
        </article>
        <div class="criteria-count"><strong>6</strong> 条标准已参与判断</div>
      </aside>

      <section class="preview-document">
        <div class="document-meta">
          <span>2024 · Randomized controlled trial</span>
          <span class="document-id">#0284</span>
        </div>
        <h3>Effect of an early intervention on patient-reported outcomes</h3>
        <p>
          This randomized study evaluated the intervention in adults meeting the predefined diagnostic criteria...
        </p>
        <div class="keyword-row">
          <span>randomized</span><span>adult</span><span>controlled trial</span>
        </div>
        <div class="document-footer">
          <span><i class="fas fa-file-lines"></i> 摘要信息完整</span>
          <span><i class="fas fa-language"></i> English</span>
        </div>
      </section>

      <aside class="preview-decision">
        <div class="preview-pane-title"><i class="fas fa-wand-magic-sparkles"></i> 模型判断</div>
        <div class="model-result included">
          <span class="model-dot">A</span>
          <div><small>模型 A</small><strong><i class="fas fa-check"></i> 纳入</strong></div>
        </div>
        <div class="model-result included">
          <span class="model-dot">B</span>
          <div><small>模型 B</small><strong><i class="fas fa-check"></i> 纳入</strong></div>
        </div>
        <div class="consensus-result">
          <small>交叉验证结论</small>
          <strong>一致纳入</strong>
          <p>研究人群与研究设计符合当前纳排标准。</p>
        </div>
        <div class="preview-action"><i class="fas fa-user-check"></i> 进入人工复核</div>
      </aside>
    </div>
  </div>
</template>

<script setup>
const steps = ['解析', '去重', '标准', '字段', 'AI 初筛', '审阅', '导出']
</script>

<style scoped>
.preview-shell {
  position: relative;
  overflow: hidden;
  width: 100%;
  border: 1px solid rgba(199, 210, 254, 0.85);
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 30px 70px rgba(49, 46, 129, 0.2), 0 0 0 8px rgba(255, 255, 255, 0.48);
  text-align: left;
}
.preview-topbar {
  height: 58px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  border-bottom: 1px solid #eef2ff;
}
.preview-brand {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  font-size: 0.72rem;
}
.preview-topbar strong { display: block; color: #1e293b; font-size: 0.75rem; }
.preview-topbar span { display: block; margin-top: 2px; color: #94a3b8; font-size: 0.57rem; }
.preview-status { margin-left: auto; color: #16a34a; font-size: 0.62rem; font-weight: 700; }
.preview-steps {
  height: 48px;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  padding: 0 12px;
  background: #fafbff;
  border-bottom: 1px solid #eef2ff;
}
.preview-steps > span {
  position: relative;
  width: 19px;
  height: 19px;
  display: grid;
  place-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 50%;
  color: #94a3b8;
  background: #fff;
  font-size: 0.55rem;
  font-weight: 800;
}
.preview-steps > span::after {
  content: '';
  position: absolute;
  left: 24px;
  width: 15px;
  height: 1px;
  background: #e2e8f0;
}
.preview-steps > span:last-child::after { display: none; }
.preview-steps > span.done { border-color: #a5b4fc; color: #fff; background: #818cf8; }
.preview-steps > span.active { border-color: #6366f1; color: #fff; background: #6366f1; box-shadow: 0 0 0 4px #e0e7ff; }
.preview-steps small {
  position: absolute;
  top: 23px;
  left: 50%;
  transform: translateX(-50%);
  width: 48px;
  color: #64748b;
  text-align: center;
  font-size: 0.48rem;
  font-weight: 600;
}
.preview-workspace { display: grid; grid-template-columns: 0.82fr 1.42fr 0.9fr; min-height: 290px; }
.preview-criteria,
.preview-decision { padding: 14px; background: #fbfcff; }
.preview-criteria { border-right: 1px solid #eef2ff; }
.preview-decision { border-left: 1px solid #eef2ff; }
.preview-pane-title { margin-bottom: 12px; color: #475569; font-size: 0.63rem; font-weight: 800; }
.preview-pane-title i { margin-right: 5px; color: #818cf8; }
.preview-criteria article {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  padding: 9px;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #fff;
}
.preview-criteria article p { margin: 0; color: #64748b; font-size: 0.52rem; line-height: 1.5; }
.preview-criteria article strong { display: block; margin-bottom: 2px; color: #334155; font-size: 0.57rem; }
.criteria-index { flex: 0 0 auto; width: 19px; height: 19px; border-radius: 6px; display: grid; place-items: center; font-size: 0.52rem; font-weight: 800; }
.criteria-index.include { color: #047857; background: #d1fae5; }
.criteria-index.exclude { color: #be123c; background: #ffe4e6; }
.criteria-count { margin-top: 12px; padding: 8px; border-radius: 8px; color: #64748b; background: #eef2ff; font-size: 0.53rem; text-align: center; }
.criteria-count strong { color: #4f46e5; }
.preview-document { padding: 23px 20px; min-width: 0; }
.document-meta { display: flex; justify-content: space-between; color: #94a3b8; font-size: 0.5rem; }
.document-id { color: #6366f1; font-weight: 700; }
.preview-document h3 { margin: 14px 0 9px; color: #1e293b; font-family: Georgia, serif; font-size: 0.86rem; line-height: 1.4; }
.preview-document > p { margin: 0; color: #64748b; font-family: Georgia, serif; font-size: 0.59rem; line-height: 1.72; }
.keyword-row { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 16px; }
.keyword-row span { padding: 4px 7px; border-radius: 999px; color: #4f46e5; background: #eef2ff; font-size: 0.48rem; }
.document-footer { display: flex; gap: 13px; margin-top: 27px; padding-top: 11px; border-top: 1px solid #f1f5f9; color: #94a3b8; font-size: 0.49rem; }
.model-result { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; padding: 8px; border: 1px solid #e2e8f0; border-radius: 9px; background: #fff; }
.model-dot { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 7px; color: #4f46e5; background: #eef2ff; font-size: 0.52rem; font-weight: 800; }
.model-result small { display: block; color: #94a3b8; font-size: 0.45rem; }
.model-result strong { display: block; margin-top: 2px; color: #059669; font-size: 0.58rem; }
.model-result strong i { margin-right: 3px; }
.consensus-result { margin-top: 11px; padding: 11px; border: 1px solid #a7f3d0; border-radius: 10px; background: #ecfdf5; }
.consensus-result small { color: #64748b; font-size: 0.46rem; }
.consensus-result strong { display: block; margin: 4px 0; color: #047857; font-size: 0.68rem; }
.consensus-result p { margin: 0; color: #64748b; font-size: 0.48rem; line-height: 1.45; }
.preview-action { width: 100%; box-sizing: border-box; margin-top: 11px; padding: 7px; border-radius: 8px; color: #fff; background: linear-gradient(135deg, #6366f1, #7c3aed); font-size: 0.52rem; font-weight: 700; text-align: center; }
@media (max-width: 600px) {
  .preview-shell { border-radius: 15px; }
  .preview-workspace { grid-template-columns: 0.95fr 1.45fr; min-height: 245px; }
  .preview-criteria { display: none; }
  .preview-steps { gap: 13px; }
  .preview-steps > span::after { left: 22px; width: 8px; }
  .preview-document { padding: 18px 13px; }
  .preview-decision { padding: 11px; }
}
</style>
