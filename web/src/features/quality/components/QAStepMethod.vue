<template>
  <div class="qa-method">
    <div class="step-header">
      <div class="step-icon-wrap" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">
        <i class="fas fa-list-check"></i>
      </div>
      <div>
        <h3 class="step-title">方法选择</h3>
        <p class="step-subtitle">为每篇文献选择合适的质量评价方法，可批量操作</p>
      </div>
    </div>

    <!-- 批量操作栏 -->
    <div class="batch-bar">
      <label class="checkbox-label">
        <input type="checkbox" :checked="allChecked" @change="toggleAll" />
        <span>全选（{{ checkedIds.length }}/{{ qa.refs.length }}）</span>
      </label>
      <div v-if="checkedIds.length" class="batch-actions">
        <span class="batch-hint">已选 {{ checkedIds.length }} 篇：</span>
        <select v-model="batchMethod" class="qa-select">
          <option value="">批量设置方法...</option>
          <option v-for="m in qa.methods" :key="m.key" :value="m.key">
            {{ m.name }}{{ !m.ai_supported ? ' (AI评价暂不支持)' : '' }}
          </option>
        </select>
        <button class="btn-sm-primary" @click="doBatchMethod" :disabled="!batchMethod || batchLoading">
          <i class="fas fa-check" v-if="!batchLoading"></i>
          <i class="fas fa-spinner fa-spin" v-else></i>
          应用
        </button>
      </div>
      <div class="search-wrap">
        <i class="fas fa-search" style="color:#94a3b8"></i>
        <input v-model="searchText" placeholder="搜索文献标题..." class="search-input" />
      </div>
    </div>

    <!-- 文献列表 -->
    <div class="ref-table-wrap">
      <table class="ref-table">
        <thead>
          <tr>
            <th style="width:40px"></th>
            <th style="width:40px">#</th>
            <th>文献标题</th>
            <th style="width:100px">全文</th>
            <th style="width:160px">质量评价方法</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(ref, idx) in filteredRefs" :key="ref.id" :class="{ 'row-checked': checkedIds.includes(ref.id) }">
            <td class="center">
              <input type="checkbox" :checked="checkedIds.includes(ref.id)" @change="toggleCheck(ref.id)" />
            </td>
            <td class="center text-muted">{{ idx + 1 }}</td>
            <td>
              <p class="ref-title-text" :title="ref.title">{{ ref.title }}</p>
              <span v-if="ref.first_author" class="ref-meta">{{ ref.first_author }}{{ ref.year ? ` · ${ref.year}` : '' }}</span>
            </td>
            <td>
              <span :class="['tag', fulltextTagClass(ref.fulltext_status)]">
                {{ fulltextLabel(ref.fulltext_status) }}
              </span>
            </td>
            <td>
              <select
                :value="ref.quality_method"
                @change="setRefMethod(ref, $event.target.value)"
                class="qa-select method-select"
                :class="{ 'no-method': !ref.quality_method }"
              >
                <option value="">请选择...</option>
                <option v-for="m in qa.methods" :key="m.key" :value="m.key">{{ m.name }}</option>
              </select>
            </td>
          </tr>
          <tr v-if="!filteredRefs.length">
            <td colspan="5" class="empty-row">暂无文献</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 方法说明 -->
    <div class="method-cards">
      <div v-for="m in qa.methods" :key="m.key" class="method-card">
        <div class="method-card-head">
          <span class="method-name">{{ m.name }}</span>
          <span v-if="m.ai_supported" class="tag tag-green ai-badge">AI 支持</span>
          <span v-else class="tag tag-gray ai-badge">AI 暂不支持</span>
        </div>
        <p class="method-desc">{{ m.description }}</p>
        <p class="method-stat">信号问题：{{ m.signal_count }} 条</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQAStore } from '@/features/quality/store'
import { useProjectStore } from '@/features/projects/store'

const qa = useQAStore()
const project = useProjectStore()

const checkedIds  = ref([])
const batchMethod = ref('')
const batchLoading = ref(false)
const searchText  = ref('')

const filteredRefs = computed(() => {
  if (!searchText.value.trim()) return qa.refs
  const q = searchText.value.toLowerCase()
  return qa.refs.filter(r => r.title.toLowerCase().includes(q))
})

const allChecked  = computed(() => checkedIds.value.length === qa.refs.length && qa.refs.length > 0)
const readyCount  = computed(() => qa.refs.filter(r => r.quality_method).length)
const noMethodCount = computed(() => qa.refs.filter(r => !r.quality_method).length)

onMounted(async () => {
  await qa.fetchMethods()
})

function toggleAll(e) {
  checkedIds.value = e.target.checked ? qa.refs.map(r => r.id) : []
}
function toggleCheck(id) {
  const idx = checkedIds.value.indexOf(id)
  if (idx === -1) checkedIds.value.push(id)
  else checkedIds.value.splice(idx, 1)
}

async function setRefMethod(ref, method) {
  await qa.updateRef(ref.id, { quality_method: method })
}

async function doBatchMethod() {
  if (!batchMethod.value || !checkedIds.value.length) return
  batchLoading.value = true
  try {
    await qa.batchSetMethod(checkedIds.value, batchMethod.value)
    batchMethod.value = ''
    checkedIds.value = []
  } finally {
    batchLoading.value = false
  }
}

function fulltextLabel(s) {
  return { available: '已有全文', pending: '待获取', missing: '无全文', error: '失败' }[s] || s
}
function fulltextTagClass(s) {
  return { available: 'tag-green', pending: 'tag-orange', missing: 'tag-gray', error: 'tag-red' }[s] || ''
}
</script>

<style scoped>
.qa-method { display: flex; flex-direction: column; gap: 16px; }
.step-header { display: flex; align-items: center; gap: 12px; }
.step-icon-wrap { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.step-title { font-size: 1rem; font-weight: 600; color: #1e293b; margin: 0; }
.step-subtitle { font-size: 0.75rem; color: #64748b; margin: 0; }
.batch-bar { display: flex; align-items: center; gap: 12px; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 16px; }
.checkbox-label { display: flex; align-items: center; gap: 6px; font-size: 0.82rem; cursor: pointer; flex-shrink: 0; }
.batch-actions { display: flex; align-items: center; gap: 8px; }
.batch-hint { font-size: 0.78rem; color: #64748b; white-space: nowrap; }
.search-wrap { display: flex; align-items: center; gap: 6px; margin-left: auto; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 7px; padding: 6px 10px; }
.search-input { border: none; background: none; outline: none; font-size: 0.82rem; width: 160px; }
.ref-table-wrap { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; max-height: 380px; overflow-y: auto; }
.ref-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.ref-table th { padding: 8px 12px; background: #f8fafc; color: #64748b; font-weight: 500; text-align: left; border-bottom: 1px solid #e2e8f0; position: sticky; top: 0; z-index: 1; }
.ref-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; color: #334155; vertical-align: middle; }
.ref-table tr:last-child td { border-bottom: none; }
.row-checked { background: #faf5ff; }
.center { text-align: center; }
.text-muted { color: #94a3b8; }
.ref-title-text { margin: 0; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.ref-meta { font-size: 0.72rem; color: #94a3b8; }
.tag { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 500; }
.tag-green { background: #d1fae5; color: #065f46; }
.tag-gray { background: #f1f5f9; color: #64748b; }
.tag-orange { background: #ffedd5; color: #9a3412; }
.tag-red { background: #fee2e2; color: #991b1b; }
.method-select { width: 100%; padding: 5px 8px; border: 1px solid #e2e8f0; border-radius: 7px; font-size: 0.78rem; background: #fff; }
.method-select.no-method { border-color: #fca5a5; background: #fff5f5; }
.empty-row { text-align: center; color: #94a3b8; padding: 20px; }
.method-cards { display: flex; gap: 10px; flex-wrap: wrap; }
.method-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; min-width: 160px; flex: 1; }
.method-card-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.method-name { font-size: 0.85rem; font-weight: 600; color: #1e293b; }
.ai-badge { font-size: 0.68rem; }
.method-desc { font-size: 0.72rem; color: #64748b; margin: 0 0 4px 0; }
.method-stat { font-size: 0.68rem; color: #94a3b8; margin: 0; }
.step-footer-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; }
.footer-tip { font-size: 0.78rem; color: #94a3b8; }
.btn-primary { padding: 8px 18px; background: #6366f1; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-primary:hover:not(:disabled) { background: #4f46e5; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { padding: 8px 16px; background: #fff; color: #6366f1; border: 1px solid #6366f1; border-radius: 8px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
.btn-secondary:hover { background: #f5f3ff; }
.btn-sm-primary { padding: 6px 12px; background: #6366f1; color: #fff; border: none; border-radius: 7px; cursor: pointer; font-size: 0.8rem; display: flex; align-items: center; gap: 4px; }
.btn-sm-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.qa-select { padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.82rem; background: #fff; }
</style>
