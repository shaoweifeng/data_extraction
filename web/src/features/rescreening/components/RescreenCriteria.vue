<template>
  <div class="rs-page">
    <section class="rs-head">
      <div class="rs-head-icon"><i class="fas fa-list-check"></i></div>
      <div>
        <h3>设定复筛排除标准</h3>
        <p>逐条维护全文复筛排除标准。<button class="guide-link" @click="showGuide = true"><i class="fas fa-lightbulb"></i> 查看撰写指南</button></p>
      </div>
      <button class="initial-criteria-button" :disabled="initialLoading" @click="showInitialCriteria">查看初筛标准</button>
    </section>

    <ExclusionCriteriaPresets class="criteria-presets" :model-value="criteriaLines(text)" :disabled="ws.state.working || ws.state.info.busy" @toggle="togglePreset" />
    <section class="criteria-card">
      <div class="input-row">
        <input
          v-model="newCriterion"
          type="text"
          maxlength="2000"
          :disabled="ws.state.working || ws.state.info.busy"
          placeholder="自定义：输入一条复筛标准或排除理由，按 Enter 确认"
          @keyup.enter="addCriteria"
        />
        <button
          :disabled="
            !newCriterion.trim() || ws.state.working || ws.state.info.busy
          "
          @click="addCriteria"
        >
          <i class="fas fa-plus"></i> 添加
        </button>
      </div>
      <div v-if="criteriaLines(text).length" class="criteria-list">
        <div
          v-for="(item, index) in criteriaLines(text)"
          :key="index"
          class="criteria-item"
        >
          <span><b>{{ index + 1 }}.</b> {{ item }}</span>
          <button
            :disabled="ws.state.working || ws.state.info.busy"
            :aria-label="`删除第 ${index + 1} 条标准`"
            @click="removeCriteria(index)"
          >
            <i class="fas fa-trash-alt"></i>
          </button>
        </div>
      </div>
      <div v-else class="empty">
        <i class="fas fa-clipboard-list"></i>
        <p>暂无标准，请在上方添加</p>
      </div>
    </section>

    <RescreenDialog :open="initialOpen" title="初筛排除标准" icon="fas fa-list-check" subtitle="初筛阶段已保存的排除标准，仅供查看参考" @close="initialOpen = false">
      <div v-if="initialLoading" class="initial-empty"><i class="fas fa-spinner fa-spin"></i><p>正在读取初筛标准…</p></div>
      <div v-else-if="initialFailed" class="initial-empty"><i class="fas fa-circle-exclamation"></i><p>读取失败，请关闭后重试。</p></div>
      <div v-else-if="!initial?.performed" class="initial-empty"><i class="fas fa-folder-open"></i><strong>该项目未进行初筛</strong><p>可在当前步骤直接制定全文复筛排除标准。</p></div>
      <ol v-else-if="initial.criteria.length" class="initial-criteria-list">
        <li v-for="(item, index) in initial.criteria" :key="index"><span>{{ index + 1 }}</span><p>{{ item }}</p></li>
      </ol>
      <div v-else class="initial-empty"><i class="fas fa-list-check"></i><strong>尚未设置初筛排除标准</strong></div>
    </RescreenDialog>
    <ExclusionCriteriaGuide v-model="showGuide" />
  </div>
</template>
<script setup>
import { computed, inject, ref, onBeforeUnmount } from 'vue'
import { criteriaLines } from '../state'
import RescreenDialog from './RescreenDialog.vue'
import ExclusionCriteriaGuide from '@/shared/components/ExclusionCriteriaGuide.vue'
import ExclusionCriteriaPresets from '@/shared/components/ExclusionCriteriaPresets.vue'
const ws = inject('rescreen')
const newCriterion = ref('')
const showGuide = ref(false)
function togglePreset(preset) {
  if (ws.state.working || ws.state.info.busy) return
  const lines = criteriaLines(text.value)
  return save(lines.includes(preset) ? lines.filter(line => line !== preset) : [...lines, preset])
}
async function addCriteria() {
  const value = newCriterion.value.trim()
  if (!value || ws.state.info.busy || ws.state.working) return
  const lines = [...criteriaLines(text.value), value]
  if (lines.length > 50 || lines.join('\n').length > 12000) {
    ws.state.error = '排除标准最多 50 条，总长不能超过 12000 字符。'
    return
  }
  if (await save(lines)) newCriterion.value = ''
}
function removeCriteria(index) {
  if (ws.state.working || ws.state.info.busy) return
  return save(criteriaLines(text.value).filter((_, i) => i !== index))
}
const text = computed(() =>
  ws.state.info.configuration.criteria.map((row) => row.text).join('\n'),
)
let alive = true
const initialOpen = ref(false)
const initialLoading = ref(false)
const initialFailed = ref(false)
const initial = ref(null)
async function showInitialCriteria() {
  initialOpen.value = true
  initialLoading.value = true
  initialFailed.value = false
  const result = await ws.read(() => ws.api.initialCriteria(ws.state.projectId))
  if (!alive) return
  initial.value = result
  initialFailed.value = !result
  initialLoading.value = false
}
onBeforeUnmount(() => {
  alive = false
})
async function save(lines) {
  return ws.action(
    () =>
      ws.api.configuration(ws.state.projectId, {
        expected_version: ws.state.info.configuration.version,
        criteria: lines,
        model_ids: ws.state.info.configuration.model_ids,
      }),
  )
}
</script>
<style scoped>
.rs-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rs-head {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border: 1px solid #eef2f7;
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}
.rs-head-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, #10b981, #34d399);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.initial-criteria-button {
  margin-left: auto;
  border: 1px solid #c7d2fe;
  border-radius: 8px;
  background: #eef2ff;
  color: #4f46e5;
  padding: 8px 12px;
  white-space: nowrap;
  cursor: pointer;
}
.criteria-presets { margin-bottom: 0; }
.guide-link { border: 0; padding: 0 0 0 10px; background: transparent; color: #6366f1; font-size: 0.78rem; cursor: pointer; }
.initial-criteria-list { margin: 0; padding: 0; list-style: none; display: grid; gap: 10px; }
.initial-criteria-list li { display: flex; align-items: flex-start; gap: 12px; padding: 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }
.initial-criteria-list li > span { display: grid; place-items: center; width: 26px; height: 26px; flex: none; background: #e0e7ff; color: #4f46e5; border-radius: 8px; font-weight: 700; }
.initial-criteria-list p { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.initial-empty { display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center; padding: 28px 12px; }
.initial-empty > i { display: grid; place-items: center; width: 60px; height: 60px; border-radius: 18px; background: #eef2ff; color: #818cf8; font-size: 1.5rem; }
.initial-empty p { margin: 0; font-size: 0.82rem; color: #94a3b8; }
h3,
h4,
p {
  margin: 0;
}
h3 {
  font-size: 1.05rem;
  color: #1e293b;
}
.rs-head p {
  font-size: 0.8rem;
  color: #64748b;
  margin-top: 4px;
}
.criteria-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 18px;
}
.input-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.input-row input {
  flex: 1;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 11px 14px;
  font-size: 0.88rem;
  outline: none;
}
.input-row input:focus {
  border-color: #a5b4fc;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}
.input-row button {
  border: 0;
  border-radius: 10px;
  background: #059669;
  color: #fff;
  padding: 0 18px;
  font-weight: 700;
  cursor: pointer;
}
.criteria-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.criteria-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 11px 13px;
  font-size: 0.86rem;
  color: #374151;
}
.criteria-item b {
  color: #059669;
  margin-right: 6px;
}
.criteria-item button {
  border: 0;
  background: transparent;
  color: #cbd5e1;
  cursor: pointer;
}
.criteria-item button:hover {
  color: #dc2626;
}
.empty {
  height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  gap: 8px;
}
.empty i {
  font-size: 2rem;
}
.criteria-item span {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  min-width: 0;
}
.input-row input {
  min-width: 0;
}
</style>
