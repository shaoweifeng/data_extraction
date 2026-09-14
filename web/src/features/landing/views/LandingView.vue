<template>
  <div class="landing-page">
    <LandingHeader :user="auth.user" @logout="handleLogout" />

    <main>
      <section class="landing-hero">
        <div class="hero-glow hero-glow-one"></div>
        <div class="hero-glow hero-glow-two"></div>
        <div class="landing-container hero-grid">
          <div class="hero-copy">
            <div class="hero-badge">
              <i class="fas fa-sparkles"></i>
              AI 辅助的循证研究工作流
            </div>
            <h1>让文献筛选更快，<br><span>也让每个判断有迹可循</span></h1>
            <p class="hero-lead">
              从文献导入、去重、纳排标准到 AI 初筛、人工复核与质量评价，
              把重复工作交给系统，把最终判断留给研究者。
            </p>
            <div class="hero-actions">
              <RouterLink class="hero-primary" :to="primaryTarget">
                {{ auth.user ? '进入我的项目' : '免费开始使用' }}
                <i class="fas fa-arrow-right"></i>
              </RouterLink>
              <a class="hero-secondary" href="#workflow">
                查看工作流程
                <i class="fas fa-arrow-down"></i>
              </a>
            </div>
            <p class="hero-note">
              <i class="fas fa-circle-check"></i>
              项目化管理
              <span></span>
              <i class="fas fa-circle-check"></i>
              人工可随时复核
            </p>
          </div>

          <div class="hero-preview-wrap">
            <div class="preview-float preview-float-top">
              <i class="fas fa-code-compare"></i>
              <span><strong>多模型共识</strong>自动识别判断分歧</span>
            </div>
            <ProductPreview />
            <div class="preview-float preview-float-bottom">
              <i class="fas fa-clock-rotate-left"></i>
              <span><strong>过程留痕</strong>关键操作持续记录</span>
            </div>
          </div>
        </div>
      </section>

      <section class="value-strip" aria-label="平台价值">
        <div class="landing-container value-strip-inner">
          <div v-for="pillar in valuePillars" :key="pillar.label" class="value-item">
            <i :class="pillar.icon"></i>
            <span>{{ pillar.label }}</span>
          </div>
        </div>
      </section>

      <section id="capabilities" class="landing-section capabilities-section">
        <div class="landing-container">
          <div class="section-heading centered">
            <span class="section-kicker">核心能力</span>
            <h2>围绕真实研究过程组织，而不是堆叠零散工具</h2>
            <p>每一项能力都连接到同一个项目上下文，输入、判断、任务与结果保持连续。</p>
          </div>
          <div class="feature-grid">
            <article v-for="card in featureCards" :key="card.title" class="feature-card">
              <div class="feature-icon" :class="card.tone"><i :class="card.icon"></i></div>
              <span class="feature-eyebrow">{{ card.eyebrow }}</span>
              <h3>{{ card.title }}</h3>
              <p>{{ card.description }}</p>
            </article>
          </div>
        </div>
      </section>

      <section id="workflow" class="landing-section workflow-section">
        <div class="landing-container">
          <div class="section-heading workflow-heading">
            <div>
              <span class="section-kicker">工作流程</span>
              <h2>从待筛选文献到可复核结果，一步一步向前</h2>
            </div>
            <p>清晰的阶段和任务状态帮助研究者知道当前做到了哪里、下一步需要处理什么。</p>
          </div>

          <div class="workflow-panel screening-panel">
            <div class="workflow-intro">
              <div class="workflow-label"><i class="fas fa-filter"></i> 文献初筛</div>
              <h3>七个连续步骤，连接规则、模型和人工判断</h3>
              <p>从原始文献到最终导出，过程数据始终归属于当前项目。</p>
              <div class="workflow-outcome">
                <i class="fas fa-file-circle-check"></i>
                <span><strong>最终产出</strong>纳入、排除、待定与分歧均有明确去向</span>
              </div>
            </div>
            <ol class="screening-steps">
              <li v-for="step in screeningSteps" :key="step.number">
                <span class="step-number">{{ step.number }}</span>
                <div><strong>{{ step.title }}</strong><p>{{ step.text }}</p></div>
              </li>
            </ol>
          </div>

          <div class="workflow-panel quality-panel">
            <div class="quality-topline">
              <div>
                <div class="workflow-label green"><i class="fas fa-shield-virus"></i> 质量评价</div>
                <h3>将初筛结果继续带入评价与复核</h3>
              </div>
              <p>全文、方法、AI 结果与人工判断集中在一个评价流程中。</p>
            </div>
            <div class="quality-steps">
              <article v-for="(step, index) in qualitySteps" :key="step.title">
                <span class="quality-index">{{ String(index + 1).padStart(2, '0') }}</span>
                <i :class="step.icon"></i>
                <strong>{{ step.title }}</strong>
                <p>{{ step.text }}</p>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section id="reliability" class="landing-section reliability-section">
        <div class="landing-container reliability-grid">
          <div class="reliability-copy">
            <span class="section-kicker light">可靠性设计</span>
            <h2>AI 加快处理速度，研究者保留最终决定权</h2>
            <p>
              平台不会把模型输出包装成不可修改的答案。AI 原始结论、模型分歧、人工覆写和任务过程被分别记录，让结果能够回看、解释和修正。
            </p>
            <div class="reliability-quote">
              <i class="fas fa-quote-left"></i>
              <span>遇到信息不足或模型分歧时，系统将问题明确交还给人工，而不是隐藏不确定性。</span>
            </div>
          </div>
          <div class="trust-grid">
            <article v-for="card in trustCards" :key="card.title">
              <i :class="card.icon"></i>
              <h3>{{ card.title }}</h3>
              <p>{{ card.description }}</p>
            </article>
          </div>
        </div>
      </section>

      <section class="landing-cta-section">
        <div class="landing-container landing-cta">
          <div class="cta-orbit cta-orbit-one"></div>
          <div class="cta-orbit cta-orbit-two"></div>
          <div>
            <span>开始你的研究项目</span>
            <h2>{{ auth.user ? '继续处理你的文献与评价任务' : '让复杂流程清晰起来' }}</h2>
            <p>{{ auth.user ? '进入项目列表，继续上一次工作。' : '创建账号，从第一个文献筛选项目开始。' }}</p>
          </div>
          <RouterLink class="cta-button" :to="primaryTarget">
            {{ auth.user ? '进入工作台' : '免费开始' }}
            <i class="fas fa-arrow-right"></i>
          </RouterLink>
        </div>
      </section>
    </main>

    <footer class="landing-footer">
      <div class="landing-container footer-main">
        <div class="footer-brand">
          <span class="landing-brand-mark"><i class="fas fa-flask"></i></span>
          <div><strong>科研 Meta 平台</strong><p>系统化文献筛选与质量评价</p></div>
        </div>
        <nav aria-label="页脚导航">
          <a href="#capabilities">核心能力</a>
          <a href="#workflow">工作流程</a>
          <a href="#reliability">可靠性</a>
          <RouterLink :to="auth.user ? { name: 'Home' } : { name: 'Login' }">
            {{ auth.user ? '工作台' : '登录' }}
          </RouterLink>
        </nav>
      </div>
      <div class="landing-container footer-bottom">
        <span>© {{ currentYear }} 科研 Meta 平台</span>
        <span>让研究过程更高效、更清晰、更可复核</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/features/account/store'
import LandingHeader from '@/features/landing/components/LandingHeader.vue'
import ProductPreview from '@/features/landing/components/ProductPreview.vue'
import {
  featureCards,
  qualitySteps,
  screeningSteps,
  trustCards,
  valuePillars,
} from '@/features/landing/content'

const auth = useAuthStore()
const currentYear = new Date().getFullYear()
const primaryTarget = computed(() => (
  auth.user ? { name: 'Home' } : { name: 'Login', query: { mode: 'register' } }
))

async function handleLogout() {
  await auth.logout()
}
</script>

<style scoped>
.landing-page {
  min-height: 100%;
  /* clip 不会创建新的滚动容器，因此顶部 sticky 导航可相对视口持续固定。 */
  overflow-x: clip;
  color: #1e293b;
  background: #fff;
}
.landing-page :where(a, button):focus-visible {
  outline: 3px solid rgba(99, 102, 241, 0.32);
  outline-offset: 3px;
}
.landing-container { width: min(1180px, calc(100% - 40px)); margin: 0 auto; }
.landing-hero {
  position: relative;
  overflow: hidden;
  padding: 94px 0 105px;
  background:
    linear-gradient(180deg, rgba(238, 242, 255, 0.78), rgba(255, 255, 255, 0) 58%),
    radial-gradient(circle at 85% 10%, rgba(221, 214, 254, 0.78), transparent 32%),
    #fff;
}
.hero-grid { position: relative; z-index: 2; display: grid; grid-template-columns: 0.95fr 1.05fr; align-items: center; gap: 44px; }
.hero-glow { position: absolute; border-radius: 50%; filter: blur(4px); pointer-events: none; }
.hero-glow-one { width: 280px; height: 280px; top: -150px; left: 12%; background: rgba(165, 180, 252, 0.2); }
.hero-glow-two { width: 190px; height: 190px; right: 2%; bottom: -80px; background: rgba(196, 181, 253, 0.22); }
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 22px;
  padding: 7px 11px;
  border: 1px solid #c7d2fe;
  border-radius: 999px;
  color: #4f46e5;
  background: rgba(238, 242, 255, 0.8);
  font-size: 0.76rem;
  font-weight: 700;
}
.hero-copy h1 { margin: 0; color: #172033; font-size: clamp(2.7rem, 4.1vw, 3.55rem); line-height: 1.12; letter-spacing: -0.052em; }
.hero-copy h1 span { color: transparent; background: linear-gradient(120deg, #4f46e5, #7c3aed 58%, #a855f7); background-clip: text; -webkit-background-clip: text; }
.hero-lead { max-width: 580px; margin: 25px 0 0; color: #64748b; font-size: 1.01rem; line-height: 1.9; }
.hero-actions { display: flex; align-items: center; gap: 13px; margin-top: 31px; }
.hero-primary,
.cta-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: 11px;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #7c3aed);
  box-shadow: 0 12px 25px rgba(99, 102, 241, 0.27);
  font-weight: 700;
  text-decoration: none;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.hero-primary { padding: 13px 20px; font-size: 0.9rem; }
.hero-primary:hover,
.cta-button:hover { transform: translateY(-2px); box-shadow: 0 16px 30px rgba(99, 102, 241, 0.36); }
.hero-secondary { display: inline-flex; align-items: center; gap: 8px; padding: 12px 15px; color: #475569; font-size: 0.86rem; font-weight: 700; text-decoration: none; }
.hero-secondary:hover { color: #4f46e5; }
.hero-note { display: flex; align-items: center; gap: 7px; margin: 20px 0 0; color: #94a3b8; font-size: 0.7rem; }
.hero-note i { color: #22c55e; }
.hero-note span { width: 1px; height: 12px; margin: 0 4px; background: #e2e8f0; }
.hero-preview-wrap { position: relative; min-width: 0; animation: preview-enter 0.8s ease both; }
.preview-float { position: absolute; z-index: 3; display: flex; align-items: center; gap: 9px; padding: 10px 13px; border: 1px solid rgba(226, 232, 240, 0.9); border-radius: 11px; color: #64748b; background: rgba(255, 255, 255, 0.94); box-shadow: 0 12px 30px rgba(30, 41, 59, 0.12); font-size: 0.62rem; backdrop-filter: blur(10px); }
.preview-float i { width: 25px; height: 25px; display: grid; place-items: center; border-radius: 7px; color: #4f46e5; background: #eef2ff; }
.preview-float strong { display: block; color: #334155; font-size: 0.66rem; }
.preview-float-top { top: -30px; right: 34px; }
.preview-float-bottom { bottom: -28px; left: 32px; }
@keyframes preview-enter { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
.value-strip { border-top: 1px solid #eef2ff; border-bottom: 1px solid #eef2ff; background: #fafbff; }
.value-strip-inner { min-height: 78px; display: grid; grid-template-columns: repeat(4, 1fr); align-items: center; }
.value-item { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 34px; color: #475569; font-size: 0.78rem; font-weight: 700; }
.value-item + .value-item { border-left: 1px solid #e2e8f0; }
.value-item i { color: #6366f1; font-size: 0.9rem; }
.landing-section { padding: 104px 0; scroll-margin-top: 68px; }
.section-heading { margin-bottom: 45px; }
.section-heading.centered { max-width: 900px; margin-right: auto; margin-left: auto; text-align: center; }
.section-kicker { display: block; margin-bottom: 12px; color: #6366f1; font-size: 0.72rem; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
.section-heading h2,
.reliability-copy h2,
.landing-cta h2 { margin: 0; color: #1e293b; font-size: clamp(2rem, 3vw, 2.75rem); line-height: 1.25; letter-spacing: -0.035em; }
.section-heading p { margin: 16px auto 0; color: #64748b; line-height: 1.8; }
.capabilities-section { background: #fff; }
.feature-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 17px; }
.feature-card { position: relative; min-height: 230px; padding: 24px; overflow: hidden; border: 1px solid #e7eaf2; border-radius: 16px; background: linear-gradient(145deg, #fff, #fbfcff); transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease; }
.feature-card::after { content: ''; position: absolute; width: 110px; height: 110px; right: -65px; bottom: -65px; border-radius: 50%; background: #eef2ff; opacity: 0.7; }
.feature-card:hover { transform: translateY(-4px); border-color: #c7d2fe; box-shadow: 0 18px 38px rgba(71, 85, 105, 0.09); }
.feature-icon { width: 42px; height: 42px; display: grid; place-items: center; margin-bottom: 19px; border-radius: 11px; font-size: 1rem; }
.feature-icon.blue { color: #2563eb; background: #dbeafe; }
.feature-icon.violet { color: #7c3aed; background: #ede9fe; }
.feature-icon.indigo { color: #4f46e5; background: #e0e7ff; }
.feature-icon.amber { color: #d97706; background: #fef3c7; }
.feature-icon.emerald { color: #059669; background: #d1fae5; }
.feature-icon.rose { color: #e11d48; background: #ffe4e6; }
.feature-eyebrow { color: #94a3b8; font-size: 0.65rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
.feature-card h3 { margin: 7px 0 9px; color: #273449; font-size: 1rem; }
.feature-card p { margin: 0; color: #64748b; font-size: 0.79rem; line-height: 1.78; }
.workflow-section { background: linear-gradient(180deg, #f8fafc, #fff); }
.workflow-heading { display: grid; grid-template-columns: 1.5fr 0.72fr; align-items: end; gap: 60px; }
.workflow-heading p { margin: 0 0 4px; }
.workflow-panel { border: 1px solid #e2e8f0; border-radius: 22px; background: #fff; box-shadow: 0 18px 48px rgba(71, 85, 105, 0.07); }
.screening-panel { display: grid; grid-template-columns: 0.72fr 1.28fr; overflow: hidden; }
.workflow-intro { padding: 36px; color: #e0e7ff; background: linear-gradient(155deg, #312e81, #4338ca 58%, #6d28d9); }
.workflow-label { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border: 1px solid rgba(199, 210, 254, 0.24); border-radius: 999px; color: #c7d2fe; background: rgba(255, 255, 255, 0.08); font-size: 0.68rem; font-weight: 800; }
.workflow-label.green { color: #047857; border-color: #a7f3d0; background: #ecfdf5; }
.workflow-intro h3 { margin: 21px 0 12px; color: #fff; font-size: 1.48rem; line-height: 1.4; }
.workflow-intro > p { margin: 0; color: #c7d2fe; font-size: 0.8rem; line-height: 1.75; }
.workflow-outcome { display: flex; align-items: center; gap: 11px; margin-top: 36px; padding-top: 20px; border-top: 1px solid rgba(255, 255, 255, 0.14); }
.workflow-outcome > i { width: 34px; height: 34px; display: grid; place-items: center; flex-shrink: 0; border-radius: 9px; color: #312e81; background: #c7d2fe; }
.workflow-outcome span { color: #c7d2fe; font-size: 0.68rem; line-height: 1.45; }
.workflow-outcome strong { display: block; color: #fff; font-size: 0.72rem; }
.screening-steps { margin: 0; padding: 24px 30px; list-style: none; display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px 22px; }
.screening-steps li { display: flex; align-items: flex-start; gap: 12px; padding: 13px 9px; border-bottom: 1px solid #f1f5f9; }
.screening-steps li:last-child { grid-column: span 2; border-bottom: 0; }
.step-number { width: 29px; height: 29px; display: grid; place-items: center; flex-shrink: 0; border-radius: 8px; color: #4f46e5; background: #eef2ff; font-size: 0.61rem; font-weight: 800; }
.screening-steps strong { color: #334155; font-size: 0.78rem; }
.screening-steps p { margin: 4px 0 0; color: #94a3b8; font-size: 0.68rem; line-height: 1.45; }
.quality-panel { margin-top: 24px; padding: 32px; }
.quality-topline { display: flex; justify-content: space-between; align-items: end; gap: 40px; margin-bottom: 28px; }
.quality-topline h3 { margin: 14px 0 0; color: #1e293b; font-size: 1.35rem; }
.quality-topline > p { max-width: 390px; margin: 0; color: #64748b; font-size: 0.78rem; line-height: 1.7; }
.quality-steps { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
.quality-steps article { position: relative; min-width: 0; padding: 18px 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #fbfefd; }
.quality-steps article:not(:last-child)::after { content: '→'; position: absolute; z-index: 2; top: 50%; right: -9px; color: #a7f3d0; font-size: 0.7rem; font-weight: 800; }
.quality-index { position: absolute; top: 9px; right: 10px; color: #cbd5e1; font-size: 0.55rem; font-weight: 800; }
.quality-steps article > i { display: block; margin-bottom: 14px; color: #10b981; font-size: 0.88rem; }
.quality-steps strong { display: block; color: #334155; font-size: 0.7rem; }
.quality-steps p { margin: 6px 0 0; color: #94a3b8; font-size: 0.59rem; line-height: 1.5; }
.reliability-section { color: #cbd5e1; background: radial-gradient(circle at 15% 10%, rgba(99, 102, 241, 0.24), transparent 30%), linear-gradient(145deg, #111827, #1e1b4b 65%, #312e81); }
.reliability-grid { display: grid; grid-template-columns: 0.82fr 1.18fr; align-items: center; gap: 75px; }
.section-kicker.light { color: #a5b4fc; }
.reliability-copy h2 { color: #fff; }
.reliability-copy > p { margin: 20px 0 0; color: #aebbd0; font-size: 0.89rem; line-height: 1.9; }
.reliability-quote { display: flex; align-items: flex-start; gap: 12px; margin-top: 27px; padding: 16px; border: 1px solid rgba(165, 180, 252, 0.2); border-radius: 12px; background: rgba(99, 102, 241, 0.1); color: #c7d2fe; font-size: 0.74rem; line-height: 1.65; }
.reliability-quote i { margin-top: 2px; color: #818cf8; }
.trust-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 13px; }
.trust-grid article { padding: 22px; border: 1px solid rgba(199, 210, 254, 0.14); border-radius: 14px; background: rgba(255, 255, 255, 0.055); }
.trust-grid article > i { width: 35px; height: 35px; display: grid; place-items: center; border-radius: 9px; color: #c7d2fe; background: rgba(129, 140, 248, 0.17); }
.trust-grid h3 { margin: 15px 0 8px; color: #f8fafc; font-size: 0.86rem; }
.trust-grid p { margin: 0; color: #94a3b8; font-size: 0.7rem; line-height: 1.65; }
.landing-cta-section { padding: 72px 0; background: #f8fafc; }
.landing-cta { position: relative; overflow: hidden; min-height: 230px; display: flex; align-items: center; justify-content: space-between; gap: 40px; padding: 48px 56px; border-radius: 24px; color: #c7d2fe; background: linear-gradient(135deg, #312e81, #4f46e5 58%, #7c3aed); box-shadow: 0 22px 55px rgba(49, 46, 129, 0.2); }
.landing-cta > div:not(.cta-orbit) { position: relative; z-index: 2; }
.landing-cta span { font-size: 0.7rem; font-weight: 800; letter-spacing: 0.14em; }
.landing-cta h2 { margin-top: 10px; color: #fff; }
.landing-cta p { margin: 10px 0 0; color: #c7d2fe; }
.cta-button { position: relative; z-index: 2; flex-shrink: 0; padding: 13px 20px; color: #4338ca; background: #fff; box-shadow: 0 12px 25px rgba(30, 27, 75, 0.22); font-size: 0.86rem; }
.cta-orbit { position: absolute; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 50%; }
.cta-orbit-one { width: 260px; height: 260px; right: -70px; top: -150px; }
.cta-orbit-two { width: 170px; height: 170px; left: 46%; bottom: -130px; }
.landing-footer { padding: 46px 0 24px; background: #fff; }
.footer-main { display: flex; align-items: center; justify-content: space-between; padding-bottom: 30px; border-bottom: 1px solid #e2e8f0; }
.footer-brand { display: flex; align-items: center; gap: 11px; }
.footer-brand .landing-brand-mark { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 10px; color: #fff; background: linear-gradient(135deg, #6366f1, #8b5cf6); }
.footer-brand strong { color: #1e293b; font-size: 0.86rem; }
.footer-brand p { margin: 3px 0 0; color: #94a3b8; font-size: 0.64rem; }
.footer-main nav { display: flex; gap: 25px; }
.footer-main nav a { color: #64748b; font-size: 0.72rem; font-weight: 600; text-decoration: none; }
.footer-main nav a:hover { color: #4f46e5; }
.footer-bottom { display: flex; justify-content: space-between; padding-top: 22px; color: #94a3b8; font-size: 0.63rem; }
@media (max-width: 1020px) {
  .landing-hero { padding-top: 75px; }
  .hero-grid { grid-template-columns: 1fr; gap: 75px; }
  .hero-copy { max-width: 720px; text-align: center; margin: 0 auto; }
  .hero-lead { margin-right: auto; margin-left: auto; }
  .hero-actions, .hero-note { justify-content: center; }
  .hero-preview-wrap { max-width: 760px; margin: 0 auto; }
  .feature-grid { grid-template-columns: repeat(2, 1fr); }
  .quality-steps { grid-template-columns: repeat(3, 1fr); }
  .quality-steps article:nth-child(3)::after { display: none; }
  .reliability-grid { grid-template-columns: 1fr; gap: 42px; }
  .reliability-copy { max-width: 690px; }
}
@media (max-width: 760px) {
  .landing-container { width: min(100% - 28px, 1180px); }
  .landing-hero { padding: 62px 0 78px; }
  .hero-copy h1 { font-size: clamp(2.35rem, 11vw, 3.3rem); }
  .hero-lead { font-size: 0.91rem; }
  .preview-float { display: none; }
  .value-strip-inner { grid-template-columns: repeat(2, 1fr); padding: 12px 0; }
  .value-item { justify-content: flex-start; padding-left: 12%; }
  .value-item + .value-item { border-left: 0; }
  .value-item:nth-child(even) { border-left: 1px solid #e2e8f0; }
  .landing-section { padding: 78px 0; }
  .feature-grid { grid-template-columns: 1fr; }
  .feature-card { min-height: 0; }
  .workflow-heading { grid-template-columns: 1fr; gap: 16px; }
  .workflow-heading p { margin-top: 0; }
  .screening-panel { grid-template-columns: 1fr; }
  .screening-steps { grid-template-columns: 1fr; }
  .screening-steps li:last-child { grid-column: auto; }
  .quality-topline { flex-direction: column; align-items: flex-start; gap: 16px; }
  .quality-steps { grid-template-columns: repeat(2, 1fr); }
  .quality-steps article:nth-child(3)::after { display: block; }
  .quality-steps article:nth-child(even)::after { display: none; }
  .trust-grid { grid-template-columns: 1fr; }
  .landing-cta { flex-direction: column; align-items: flex-start; padding: 38px 30px; }
  .footer-main { flex-direction: column; align-items: flex-start; gap: 24px; }
  .footer-main nav { flex-wrap: wrap; gap: 15px 22px; }
}
@media (max-width: 480px) {
  .hero-copy h1 { font-size: 2.2rem; }
  .hero-actions { flex-direction: column; align-items: stretch; }
  .hero-secondary { justify-content: center; }
  .hero-note { flex-wrap: wrap; }
  .value-item { padding-left: 3%; font-size: 0.7rem; }
  .section-heading h2, .reliability-copy h2, .landing-cta h2 { font-size: 1.8rem; }
  .workflow-intro, .quality-panel { padding: 25px 20px; }
  .screening-steps { padding: 16px; }
  .quality-steps { grid-template-columns: 1fr; }
  .quality-steps article::after { display: none !important; }
  .footer-bottom { flex-direction: column; gap: 6px; }
}
@media (prefers-reduced-motion: reduce) {
  .hero-preview-wrap { animation: none; }
  .feature-card, .hero-primary, .cta-button { transition: none; }
}
</style>
