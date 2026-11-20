<template>
  <div class="rs-page">
    <section class="rs-head">
      <div class="rs-head-icon"><i class="fas fa-list-check"></i></div>
      <div>
        <h3>设定复筛排除标准</h3>
        <p>逐条维护全文复筛排除标准。</p>
      </div>
      <button class="initial-criteria-button" :disabled="initialLoading" @click="showInitialCriteria">查看初筛标准</button>
    </section>

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

    <RescreenDialog :open="initialOpen" title="初筛排除标准" @close="initialOpen = false">
      <p v-if="initialLoading">正在读取初筛标准…</p>
      <p v-else-if="initialFailed">读取失败，请关闭后重试。</p>
      <p v-else-if="!initial?.performed">该项目未进行初筛。</p>
      <ol v-else-if="initial.criteria.length" class="initial-criteria-list">
        <li v-for="(item, index) in initial.criteria" :key="index">{{ item }}</li>
      </ol>
      <p v-else>该项目尚未设置初筛排除标准。</p>
    </RescreenDialog>
    <section class="guide-card">
      <h4><i class="fas fa-lightbulb"></i> 撰写提示</h4>
      <div class="guide-grid">
        <div><b>P 人群</b><span>全文是否符合目标研究对象。</span></div>
        <div>
          <b>I/E 暴露或干预</b><span>是否符合本研究关注的干预、检测或暴露。</span>
        </div>
        <div><b>C 对照</b><span>是否存在符合要求的对照或参考标准。</span></div>
        <div><b>O 结局</b><span>是否报告复筛所需核心结局。</span></div>
      </div>
    </section>
  </div>
</template>
<script setup>
import { computed, inject, ref, onBeforeUnmount } from 'vue'
import { criteriaLines } from '../state'
import RescreenDialog from './RescreenDialog.vue'
const ws = inject('rescreen')
const newCriterion = ref('')
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
.initial-criteria-list { margin: 0; padding-left: 22px; }
.initial-criteria-list li { padding: 6px 0; overflow-wrap: anywhere; white-space: pre-wrap; }
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
.criteria-card,
.guide-card {
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
.guide-card h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #1e293b;
  margin-bottom: 12px;
}
.guide-card i {
  color: #f59e0b;
}
.guide-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.guide-grid div {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 12px;
  padding: 12px;
}
.guide-grid b {
  display: block;
  color: #92400e;
  margin-bottom: 4px;
}
.guide-grid span {
  font-size: 0.78rem;
  color: #78350f;
}
@media (max-width: 1100px) {
  .guide-grid {
    grid-template-columns: 1fr 1fr;
  }
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
