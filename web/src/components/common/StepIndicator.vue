<template>
  <div class="step-indicator">
    <template v-for="(step, idx) in steps" :key="step.id">
      <!-- 步骤节点 -->
      <button
        @click="handleStepClick(step, idx)"
        :class="['step-node', getNodeClass(step, idx)]"
      >
        <span class="step-node-num">
          <i v-if="getStepStatus(step) === 'completed' && currentStep !== idx + 1" class="fas fa-check step-check-icon"></i>
          <span v-else>{{ idx + 1 }}</span>
        </span>
        <span class="step-node-label">{{ step.name }}</span>
        <!-- running 脉冲 -->
        <span v-if="getStepStatus(step) === 'running' && currentStep !== idx + 1" class="step-running-dot"></span>
      </button>

      <!-- 连接线 -->
      <div
        v-if="idx < steps.length - 1"
        :class="['step-line', getStepStatus(step) === 'completed' ? 'step-line-done' : '']"
      ></div>
    </template>
  </div>
</template>

<script setup>
import { useScreeningStore } from '@/stores/screening'

const props = defineProps({
  steps: { type: Array, required: true },
  currentStep: { type: Number, required: true },
  stagesData: { type: Array, default: () => [] },
})

const screening = useScreeningStore()

function getStepObj(step) {
  const stage = props.stagesData.find((s) => s.stage_key === 'SCREEN_1')
  return stage?.steps.find((s) => s.step_key === step.stepKey)
}

// 归一化后端步骤状态 → UI 状态
// 后端 StageStep.status 取值：pending / in_progress / completed / failed / skipped
// （历史上执行器还可能写入越界的 stopped，这里一并按“进行中”处理）
function getStepStatus(step) {
  const raw = getStepObj(step)?.status || 'pending'
  if (raw === 'in_progress' || raw === 'stopped' || raw === 'stopping') return 'running'
  return raw
}

function getNodeClass(step, idx) {
  const stepNum = idx + 1
  const status = getStepStatus(step)
  const active = props.currentStep === stepNum

  if (active) return 'step-node-active'
  if (status === 'completed') return 'step-node-done'
  if (status === 'running') return 'step-node-running'
  if (status === 'failed') return 'step-node-failed'
  return 'step-node-idle'
}

function handleStepClick(step, idx) {
  screening.currentStep = idx + 1
}
</script>

<style scoped>
.step-indicator {
  display: flex;
  align-items: center;
  gap: 0;
  overflow-x: auto;
}

/* 步骤节点按钮 */
.step-node {
  display: flex; align-items: center; gap: 7px;
  padding: 6px 12px;
  border-radius: 999px;
  border: none;
  cursor: pointer;
  font-size: 0.8rem; font-weight: 500;
  white-space: nowrap;
  transition: all 0.2s;
  position: relative;
  flex-shrink: 0;
}

.step-node-num {
  width: 20px; height: 20px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; font-weight: 700;
  flex-shrink: 0;
}
.step-check-icon { font-size: 0.65rem; }
.step-node-label { font-size: 0.8rem; }

/* 激活状态 */
.step-node-active {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  box-shadow: 0 4px 12px rgba(99,102,241,.35);
}
.step-node-active .step-node-num {
  background: rgba(255,255,255,0.25);
  color: #fff;
}

/* 已完成 */
.step-node-done {
  background: #ecfdf5;
  color: #059669;
}
.step-node-done:hover { background: #d1fae5; }
.step-node-done .step-node-num {
  background: #10b981; color: #fff;
}

/* 运行中 */
.step-node-running {
  background: #eff6ff;
  color: #3b82f6;
}
.step-node-running .step-node-num {
  background: #3b82f6; color: #fff;
}

/* 失败 */
.step-node-failed {
  background: #fff1f2;
  color: #e11d48;
}
.step-node-failed .step-node-num {
  background: #e11d48; color: #fff;
}

/* 空闲 */
.step-node-idle {
  background: transparent;
  color: #64748b;
}
.step-node-idle:hover { background: #f1f5f9; }
.step-node-idle .step-node-num {
  background: #e2e8f0; color: #64748b;
}

/* running 脉冲点 */
.step-running-dot {
  position: absolute; top: 4px; right: 4px;
  width: 7px; height: 7px;
  background: #3b82f6; border-radius: 50%;
  animation: pulse 1.2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.75); }
}

/* 连接线 */
.step-line {
  flex: 1; min-width: 8px; max-width: 28px; height: 2px;
  background: #e2e8f0; border-radius: 999px; flex-shrink: 0;
}
.step-line-done {
  background: linear-gradient(90deg, #10b981, #6366f1);
}
</style>
