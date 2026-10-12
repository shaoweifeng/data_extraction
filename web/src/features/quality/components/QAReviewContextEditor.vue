<template>
  <div v-if="scopes.length" class="context-card">
    <button class="context-head" type="button" @click="expanded = !expanded">
      <span><i class="fas fa-bullseye"></i> 系统评价研究问题</span>
      <span class="context-head-tip">用于适用性判断</span>
      <i :class="['fas', expanded ? 'fa-chevron-up' : 'fa-chevron-down']"></i>
    </button>
    <div v-if="expanded" class="context-body">
      <label v-if="scopes.length > 1" class="context-scope">
        <span>评价方法</span>
        <select v-model="activeKey">
          <option v-for="scope in scopes" :key="scope.key" :value="scope.key">
            {{ scope.label }}
          </option>
        </select>
      </label>
      <p class="context-note">
        未填写时，适用性问题将安全降级为“不清楚”；这些内容不会替代文献原文。
      </p>
      <div class="context-fields">
        <label v-for="field in fields" :key="field.key">
          <span>{{ field.label }}</span>
          <textarea
            v-model.trim="form[field.key]"
            :placeholder="field.placeholder"
            rows="2"
            maxlength="4000"
          ></textarea>
        </label>
      </div>
      <div class="context-actions">
        <span v-if="message" :class="['context-message', { error: saveError }]">{{ message }}</span>
        <button type="button" :disabled="saving" @click="save">
          <i :class="saving ? 'fas fa-spinner fa-spin' : 'fas fa-save'"></i>
          {{ saving ? '保存中…' : '保存研究问题' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import * as qualityApi from '@/features/quality/api'

const props = defineProps({
  projectId: { type: Number, default: null },
  references: { type: Array, default: () => [] },
})

const fields = [
  { key: 'target_population', label: '目标人群', placeholder: '例如：疑似肺癌的成年患者' },
  { key: 'index_test', label: '待评价试验/干预', placeholder: '例如：低剂量 CT 筛查' },
  { key: 'target_condition', label: '目标疾病/状态', placeholder: '例如：早期肺癌' },
  { key: 'reference_standard', label: '参考标准', placeholder: '例如：病理学诊断' },
  { key: 'intended_use', label: '使用场景', placeholder: '例如：医院门诊初筛' },
  { key: 'review_objective', label: '研究目的', placeholder: '简述本次系统评价的研究问题' },
]
const blank = () => Object.fromEntries(fields.map(field => [field.key, '']))
const contexts = ref({})
const activeKey = ref('')
const expanded = ref(false)
const saving = ref(false)
const message = ref('')
const saveError = ref(false)
const form = reactive(blank())

const scopes = computed(() => {
  const seen = new Set()
  return props.references.reduce((items, reference) => {
    if (!reference.quality_method) return items
    const variant = reference.quality_method_variant || ''
    const key = `${reference.quality_method}|${variant}`
    if (seen.has(key)) return items
    seen.add(key)
    items.push({
      key,
      method: reference.quality_method,
      variant,
      label: variant ? `${reference.quality_method} · ${variant}` : reference.quality_method,
    })
    return items
  }, [])
})

function applyContext() {
  const value = contexts.value[activeKey.value] || blank()
  for (const field of fields) form[field.key] = value[field.key] || ''
  message.value = ''
}

async function load() {
  if (!props.projectId) return
  try {
    const response = await qualityApi.fetchReviewContexts(props.projectId)
    contexts.value = Object.fromEntries((response.data.data || []).map(item => [
      `${item.quality_method}|${item.method_variant || ''}`,
      item,
    ]))
    if (!scopes.value.some(scope => scope.key === activeKey.value)) {
      activeKey.value = scopes.value[0]?.key || ''
    }
    applyContext()
  } catch (error) {
    saveError.value = true
    message.value = error?.response?.data?.error || '研究问题加载失败'
  }
}

async function save() {
  const scope = scopes.value.find(item => item.key === activeKey.value)
  if (!scope || !props.projectId) return
  saving.value = true
  message.value = ''
  saveError.value = false
  try {
    const response = await qualityApi.saveReviewContext({
      project_id: props.projectId,
      quality_method: scope.method,
      method_variant: scope.variant,
      ...Object.fromEntries(fields.map(field => [field.key, form[field.key]])),
    })
    contexts.value[scope.key] = response.data.data
    message.value = '已保存，将用于后续 AI 适用性判断'
  } catch (error) {
    saveError.value = true
    message.value = error?.response?.data?.error || '保存失败'
  } finally {
    saving.value = false
  }
}

watch(() => props.projectId, load, { immediate: true })
watch(scopes, value => {
  if (!value.some(scope => scope.key === activeKey.value)) {
    activeKey.value = value[0]?.key || ''
  }
}, { deep: true })
watch(activeKey, applyContext)
</script>

<style scoped>
.context-card { background:#fff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; }
.context-head { width:100%; border:0; background:#fff; padding:11px 13px; display:flex; align-items:center; gap:7px; color:#475569; cursor:pointer; font-size:.78rem; font-weight:600; text-align:left; }
.context-head > span:first-child { flex:1; }
.context-head i:first-child { color:#6366f1; margin-right:5px; }
.context-head-tip { font-size:.66rem; font-weight:400; color:#94a3b8; }
.context-body { border-top:1px solid #f1f5f9; padding:12px; }
.context-scope { display:flex; align-items:center; gap:8px; font-size:.72rem; color:#64748b; }
.context-scope select { flex:1; border:1px solid #e2e8f0; border-radius:6px; padding:5px 7px; color:#334155; background:#fff; }
.context-note { margin:8px 0; padding:7px 9px; background:#f8fafc; border-radius:7px; color:#64748b; font-size:.68rem; line-height:1.45; }
.context-fields { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.context-fields label { display:flex; flex-direction:column; gap:3px; color:#64748b; font-size:.68rem; }
.context-fields textarea { width:100%; box-sizing:border-box; resize:vertical; min-height:48px; border:1px solid #e2e8f0; border-radius:6px; padding:6px 7px; color:#334155; font:inherit; line-height:1.4; }
.context-fields textarea:focus { outline:none; border-color:#818cf8; box-shadow:0 0 0 2px #eef2ff; }
.context-actions { margin-top:9px; display:flex; align-items:center; justify-content:flex-end; gap:8px; }
.context-message { flex:1; color:#059669; font-size:.68rem; }
.context-message.error { color:#dc2626; }
.context-actions button { border:0; border-radius:7px; padding:6px 10px; background:#6366f1; color:#fff; font-size:.72rem; cursor:pointer; }
.context-actions button:disabled { opacity:.55; cursor:not-allowed; }
</style>
