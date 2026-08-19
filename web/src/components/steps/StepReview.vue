<template>
  <div class="step-review">
    <!-- 顶部进度条 -->
    <div class="review-header">
      <div class="review-progress">
        <span class="progress-text">
          已审 <strong>{{ stats.reviewed }}</strong> / 共 <strong>{{ stats.total }}</strong> 篇
          <span v-if="stats.overridden" class="override-badge">
            · {{ stats.overridden }} 篇覆写了 AI 判断
          </span>
        </span>
        <div class="progress-bar-wrap">
          <div class="progress-bar-fill" :style="{ width: progressPct + '%' }"></div>
        </div>
      </div>
    </div>

    <div class="review-body">
      <!-- ── 左栏：文献列表 ── -->
      <div class="list-panel">
        <!-- 搜索框 -->
        <div class="search-box">
          <i class="fas fa-search"></i>
          <input v-model="searchQ" placeholder="搜索标题…" @input="onSearch" />
        </div>

        <!-- Tab 过滤（纵向，宽度固定） -->
        <div class="tab-bar">
          <button
            v-for="tab in tabs" :key="tab.key"
            class="tab-btn" :class="{ active: activeTab === tab.key }"
            @click="switchTab(tab.key)"
          >
            <div class="tab-label">{{ tab.label }}</div>
            <div class="tab-count-num">{{ tabCount(tab.key) || 0 }}</div>
          </button>
        </div>

        <!-- 文献列表 -->
        <div class="ref-list">
          <div v-if="loading" class="list-loading">
            <i class="fas fa-spinner fa-spin"></i> 加载中…
          </div>
          <template v-else>
          <div
              v-for="(item, idx) in displayItems" :key="item.source_xml"
              class="ref-item"
              :class="{
                selected: selected?.source_xml === item.source_xml,
                override: item.is_override,
              }"
              @click="selectItem(item)"
            >
              <div class="ref-num">{{ (page - 1) * pageSize + idx + 1 }}</div>
              <div class="ref-main">
                <div class="ref-title">{{ item.title || item.source_xml }}</div>
                <div class="ref-sub">
                  <span v-if="item.year">{{ item.year }}</span>
                  <span v-if="item.journal" class="ref-journal">{{ item.journal }}</span>
                </div>
              </div>
              <div class="ref-status">
                <span v-if="item.human_decision" class="badge human" :class="[item.human_decision, item.is_override ? 'is-override' : '']">
                  <i v-if="item.is_override" class="fas fa-pen" title="覆写了AI判断"></i>
                  <i v-else class="fas fa-check" title="已人工确认"></i>
                  {{ decisionLabel(item.human_decision) }}
                </span>
                <span v-else-if="item.ai_decision" class="badge ai" :class="item.ai_decision">
                  AI · {{ decisionLabel(item.ai_decision) }}
                </span>
                <span v-else class="badge pending">待审</span>
              </div>
            </div>
            <div v-if="!loading && displayItems.length === 0" class="list-empty">暂无文献</div>
          </template>
        </div>

        <!-- 分页控件 -->
        <div class="pagination" v-if="totalPages > 1">
          <button class="pg-btn" :disabled="page <= 1" @click="goPage(page - 1)">
            <i class="fas fa-chevron-left"></i>
          </button>
          <span class="pg-info">{{ page }} / {{ totalPages }}</span>
          <button class="pg-btn" :disabled="page >= totalPages" @click="goPage(page + 1)">
            <i class="fas fa-chevron-right"></i>
          </button>
        </div>
      </div>

      <!-- ── 右栏：文献详情 ── -->
      <div class="detail-panel">
        <template v-if="selected">
          <!-- 文献基本信息（固定，不滚动）-->
          <div class="detail-meta">
            <h3 class="detail-title">{{ selected.title }}</h3>
            <!-- URL 行 -->
            <div class="detail-url">
              <i class="fas fa-external-link-alt"></i>
              <a v-if="selected.doi" :href="'https://doi.org/' + selected.doi" target="_blank">https://doi.org/{{ selected.doi }}</a>
              <a v-else-if="selected.url" :href="selected.url" target="_blank">{{ selected.url }}</a>
              <span v-else class="url-none">无法获取 URL</span>
            </div>
            <div class="detail-info-row">
              <span v-if="selected.authors" class="info-chip"><i class="fas fa-users"></i> {{ selected.authors }}</span>
              <span v-if="selected.year"    class="info-chip"><i class="fas fa-calendar"></i> {{ selected.year }}</span>
              <span v-if="selected.journal" class="info-chip"><i class="fas fa-book"></i> {{ selected.journal }}</span>
            </div>
          </div>

          <!-- Abstract 独立滚动框（flex:1 自适应剩余高度） -->
          <div class="abstract-box">
            <div class="abstract-box-header">
              <span class="section-label" style="margin:0">摘要</span>
            </div>
            <div class="abstract-box-body">
              <div class="abstract-body" v-if="selected.abstract">{{ selected.abstract }}</div>
              <div v-else class="abstract-empty">（暂无摘要）</div>
            </div>
          </div>

          <!-- 纳排标准 + 自定义字段（折叠面板，固定高度） -->
          <div class="ref-panels">
            <div class="ref-panel">
              <div class="ref-panel-header" @click="showCriteria = !showCriteria">
                <i class="fas fa-clipboard-list"></i> 纳排标准
                <i class="fas" :class="showCriteria ? 'fa-chevron-up' : 'fa-chevron-down'" style="margin-left:auto"></i>
              </div>
              <div class="ref-panel-body" v-if="showCriteria">
                <ul v-if="criteriaList.length" class="criteria-list">
                  <li v-for="(c, i) in criteriaList" :key="i">{{ c }}</li>
                </ul>
                <div v-else class="ref-panel-empty">尚未设置纳排标准</div>
              </div>
            </div>
            <div class="ref-panel" v-if="extractionFields.length">
              <div class="ref-panel-header" @click="showFields = !showFields">
                <i class="fas fa-tags"></i> 自定义提取字段
                <i class="fas" :class="showFields ? 'fa-chevron-up' : 'fa-chevron-down'" style="margin-left:auto"></i>
              </div>
              <div class="ref-panel-body" v-if="showFields">
                <div v-for="f in extractionFields" :key="f.name" class="field-item">
                  <span class="field-name">{{ f.name }}</span>
                  <span class="field-def">{{ f.definition }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- AI 判断 -->
          <div class="detail-ai" v-if="selected.ai_decision">
            <div class="section-label">AI 判断</div>
            <div class="ai-result-row">
              <span class="badge ai" :class="selected.ai_decision">
                AI: {{ decisionLabel(selected.ai_decision) }}
              </span>
              <span v-if="selected.ai_reason" class="ai-reason">{{ selected.ai_reason }}</span>
            </div>
          </div>

          <!-- 固定底部操作区 -->
          <div class="detail-action">
            <div class="action-row">
              <div class="action-btns">
                <button
                  v-for="opt in decisionOpts" :key="opt.value"
                  class="action-btn" :class="[opt.value, { active: localDecision === opt.value }]"
                  @click="setDecision(opt.value)" :disabled="saving"
                >
                  <i :class="opt.icon"></i> {{ opt.label }}
                </button>
              </div>
              <div v-if="saveStatus" class="save-status" :class="saveStatusType">{{ saveStatus }}</div>
            </div>
            <!-- 排除模式：快捷理由 + 自定义输入 -->
            <div class="reason-wrap" v-if="localDecision === 'excluded'">
              <!-- 快捷标准选项 -->
              <div v-if="criteriaList.length" class="quick-criteria">
                <div class="quick-criteria-label">快捷选择排除标准：</div>
                <div class="quick-criteria-tags">
                  <button
                    v-for="(c, i) in criteriaList" :key="i"
                    class="criteria-tag"
                    :class="{ active: localReason === c }"
                    @click="pickCriteria(c)"
                    :title="c"
                  >
                    <span class="criteria-tag-num">标准 {{ i + 1 }}</span>
                    <span class="criteria-tag-text">{{ c }}</span>
                  </button>
                </div>
              </div>
              <textarea
                v-model="localReason"
                placeholder="输入排除理由（可选，失焦自动保存）…"
                rows="2"
                @blur="autoSave"
              />
            </div>
            <!-- 其他操作（纳入/待定）的自定义理由 -->
            <div class="reason-wrap" v-else-if="localDecision">
              <textarea v-model="localReason" placeholder="输入理由（可选，失焦自动保存）…" rows="2" @blur="autoSave" />
            </div>
          </div>
        </template>

        <div v-else class="detail-empty">
          <i class="fas fa-hand-pointer"></i>
          <p>从左侧列表选择一篇文献开始审阅</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useScreeningStore } from '@/stores/screening'
import http from '@/api/http'

const project   = useProjectStore()
const screening = useScreeningStore()

// ── 状态 ──────────────────────────────────────────────────────────────────────
const stats        = ref({ total: 0, reviewed: 0, included: 0, excluded: 0, pending: 0, overridden: 0 })
const displayItems = ref([])
const loading      = ref(false)

const activeTab    = ref('')
const searchQ      = ref('')
const page         = ref(1)
const pageSize     = 30
const totalCount   = ref(0)

const selected      = ref(null)
const localDecision = ref('')
const localReason   = ref('')
const saving        = ref(false)
const saveStatus    = ref('')
const saveStatusType = ref('')

// 折叠面板
const showCriteria = ref(false)
const showFields   = ref(false)

// 纳排标准 + 提取字段（从 stagesData 读）
const criteriaList = computed(() => {
  const stage = project.stagesData?.find(s => s.stage_key === 'SCREEN_1')
  return stage?.steps?.find(s => s.step_key === 'criteria')?.metadata?.criteria || []
})

const extractionFields = computed(() => {
  const stage = project.stagesData?.find(s => s.stage_key === 'SCREEN_1')
  return stage?.steps?.find(s => s.step_key === 'field_extraction')?.metadata?.fields || []
})

// review 步骤 id
const reviewStepId = computed(() => {
  const stage = project.stagesData?.find(s => s.stage_key === 'SCREEN_1')
  return stage?.steps?.find(s => s.step_key === 'review')?.id ?? null
})

const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize)))
const progressPct = computed(() => stats.value.total ? Math.round((stats.value.reviewed / stats.value.total) * 100) : 0)

// ── Tab ───────────────────────────────────────────────────────────────────────
const tabs = [
  { key: '',           label: '全部' },
  { key: 'unreviewed', label: '待审' },
  { key: 'included',   label: '纳入' },
  { key: 'excluded',   label: '排除' },
  { key: 'pending',    label: '待定' },
]

function tabCount(key) {
  const s = stats.value
  if (key === '')           return s.total || ''
  if (key === 'unreviewed') return Math.max(0, (s.total - s.reviewed)) || ''
  if (key === 'included')   return s.included || ''
  if (key === 'excluded')   return s.excluded || ''
  if (key === 'pending')    return s.pending  || ''
  return ''
}

const decisionOpts = [
  { value: 'included', label: '纳入', icon: 'fas fa-check' },
  { value: 'pending',  label: '待定', icon: 'fas fa-question' },
  { value: 'excluded', label: '排除', icon: 'fas fa-times'  },
]

function decisionLabel(v) {
  return { included: '纳入', excluded: '排除', pending: '待定', error: '错误' }[v] || v || '—'
}

// ── API ───────────────────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const res = await http.get('/review/stats/', { params: { project: project.currentProject?.id } })
    stats.value = res.data
  } catch (e) { console.error('[review] loadStats error', e) }
}

async function loadItems(targetPage = 1) {
  if (loading.value) return
  loading.value = true
  try {
    const res = await http.get('/review/list/', {
      params: {
        project:   project.currentProject?.id,
        step:      reviewStepId.value,
        decision:  activeTab.value,
        q:         searchQ.value,
        page:      targetPage,
        page_size: pageSize,
      }
    })
    totalCount.value   = res.data.total
    displayItems.value = res.data.results
    page.value         = targetPage
  } catch (e) { console.error('[review] loadItems error', e) }
  finally { loading.value = false }
}

async function saveDecision(decision, reason) {
  if (!selected.value || !reviewStepId.value) return
  saving.value = true
  saveStatus.value = '保存中…'
  saveStatusType.value = ''
  try {
    const xmlEncoded = encodeURIComponent(selected.value.source_xml)
    await http.patch(`/review/item/${xmlEncoded}/`, {
      project: project.currentProject?.id,
      step:    reviewStepId.value,
      decision,
      reason:  reason || '',
    })
    // 更新本地列表
    const item = displayItems.value.find(i => i.source_xml === selected.value.source_xml)
    if (item) { item.human_decision = decision; item.human_reason = reason; item.is_override = item.ai_decision !== decision }
    selected.value.human_decision = decision
    selected.value.is_override    = selected.value.ai_decision !== decision
    saveStatus.value     = '已保存 ✓'
    saveStatusType.value = 'success'
    await loadStats()
    setTimeout(() => { saveStatus.value = '' }, 2000)
  } catch (e) {
    saveStatus.value     = '保存失败，请重试'
    saveStatusType.value = 'error'
  } finally { saving.value = false }
}

// ── 交互 ──────────────────────────────────────────────────────────────────────
function switchTab(key) { activeTab.value = key; loadItems(1) }

let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadItems(1), 300)
}

function goPage(p) {
  if (p < 1 || p > totalPages.value) return
  loadItems(p)
  selected.value = null
}

function selectItem(item) {
  selected.value      = { ...item }
  localDecision.value = item.human_decision || ''
  localReason.value   = item.human_reason   || ''
  saveStatus.value    = ''
}

function setDecision(value) {
  localDecision.value = value
  saveDecision(value, localReason.value)
}

function autoSave() {
  if (localDecision.value) saveDecision(localDecision.value, localReason.value)
}

// 快捷标准：点击即填入理由并立即保存
function pickCriteria(criteriaText) {
  localReason.value = criteriaText
  saveDecision('excluded', criteriaText)
}

onMounted(async () => {
  await Promise.all([loadStats(), loadItems(1)])
})
</script>

<style scoped>
.step-review {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  font-size: 0.88rem;
  overflow: hidden;
}

/* ── 顶部 ── */
.review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.2rem;
  padding: 0.65rem 1rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.review-progress { flex: 1; }
.progress-text { font-size: 0.83rem; color: #64748b; display: block; margin-bottom: 0.3rem; }
.progress-text strong { color: #334155; }
.override-badge { color: #a855f7; font-size: 0.78rem; }
.progress-bar-wrap { height: 4px; background: #e2e8f0; border-radius: 2px; overflow: hidden; max-width: 260px; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 2px; transition: width .4s; }
.btn-complete {
  padding: 0.42rem 1rem;
  background: #6366f1; color: #fff;
  border: none; border-radius: 6px; cursor: pointer;
  font-size: 0.83rem; display: flex; align-items: center; gap: 0.4rem;
  white-space: nowrap; transition: background .2s;
}
.btn-complete:hover:not(:disabled) { background: #4f46e5; }
.btn-complete:disabled { opacity: .6; cursor: not-allowed; }

/* ── 主体 ── */
.review-body { display: flex; flex: 1; overflow: hidden; }

/* ── 左栏 ── */
.list-panel {
  width: 300px; flex-shrink: 0;
  display: flex; flex-direction: column;
  border-right: 1px solid #e2e8f0;
  background: #fff;
  overflow: hidden;
}
.search-box {
  display: flex; align-items: center; gap: .45rem;
  padding: .55rem .75rem; border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.search-box i { color: #94a3b8; font-size: .8rem; }
.search-box input { flex: 1; border: none; outline: none; font-size: .83rem; color: #334155; background: transparent; }

/* 纵向 Tab */
.tab-bar {
  display: flex;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  flex-shrink: 0;
}
.tab-btn {
  flex: 1;
  padding: .5rem .2rem .4rem;
  border: none; background: transparent;
  cursor: pointer;
  display: flex; flex-direction: column; align-items: center; gap: .05rem;
  border-bottom: 2px solid transparent;
  transition: all .15s;
}
.tab-btn.active { background: #fff; border-bottom-color: #6366f1; }
.tab-label { font-size: .75rem; color: #64748b; white-space: nowrap; }
.tab-btn.active .tab-label { color: #6366f1; font-weight: 600; }
.tab-count-num { font-size: .78rem; font-weight: 700; color: #334155; }
.tab-btn.active .tab-count-num { color: #6366f1; }

.ref-list { flex: 1; overflow-y: auto; }

/* 文献列表项 */
.ref-item {
  display: flex; align-items: flex-start; gap: .5rem;
  padding: .6rem .75rem;
  cursor: pointer;
  border-bottom: 1px solid #f1f5f9;
  transition: background .12s;
  position: relative;
}
.ref-item:hover { background: #f8fafc; }
.ref-item.selected {
  background: #eef2ff;
  border-left: 3px solid #6366f1;
}
.ref-item.override::after {
  content: '';
  position: absolute; top: 0; right: 0;
  width: 0; height: 0;
  border-top: 8px solid #a855f7;
  border-left: 8px solid transparent;
}
.ref-num {
  font-size: .7rem; color: #cbd5e1; min-width: 18px;
  padding-top: 3px; text-align: right; flex-shrink: 0;
}
.ref-main { flex: 1; min-width: 0; }
.ref-title {
  font-size: .82rem; color: #1e293b; line-height: 1.38;
  overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  word-break: break-word; margin-bottom: .18rem;
}
.ref-sub { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
.ref-sub span { font-size: .71rem; color: #94a3b8; }
.ref-journal {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px;
}
.ref-status { flex-shrink: 0; padding-top: 2px; }

/* 分页 */
.pagination {
  display: flex; align-items: center; justify-content: center;
  gap: .5rem; padding: .5rem .75rem;
  border-top: 1px solid #e2e8f0; flex-shrink: 0; background: #fff;
}
.pg-btn {
  width: 26px; height: 26px; border-radius: 5px;
  border: 1px solid #e2e8f0; background: #fff;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; color: #6366f1; transition: all .15s;
}
.pg-btn:disabled { opacity: .35; cursor: not-allowed; }
.pg-btn:hover:not(:disabled) { background: #ede9fe; border-color: #6366f1; }
.pg-info { font-size: .8rem; color: #64748b; }

.list-loading, .list-empty { text-align: center; padding: 1.2rem; color: #94a3b8; font-size: .8rem; }

/* badge */
.badge {
  display: inline-flex; align-items: center; gap: .2rem;
  padding: .13rem .4rem; border-radius: 9px; font-size: .7rem; font-weight: 600;
}
/* 人工已审（与AI一致）：绿/红底色 + 对勾图标 */
.badge.human.included { background: #dcfce7; color: #16a34a; }
.badge.human.excluded { background: #fee2e2; color: #dc2626; }
.badge.human.pending  { background: #fef9c3; color: #ca8a04; }
/* 覆写AI判断：额外加橙色边框以示区别 */
.badge.human.is-override { outline: 1.5px solid #f97316; }
.badge.ai    { background: #f1f5f9; color: #64748b; }
.badge.pending  { background: #fef9c3; color: #ca8a04; }

/* ── 右栏 ── */
.detail-panel {
  flex: 1; display: flex; flex-direction: column;
  overflow: hidden; background: #fff;
  min-width: 0;
}
.detail-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 100%; color: #cbd5e1; gap: .8rem; font-size: .9rem;
}
.detail-empty i { font-size: 2.5rem; }

/* 文献元信息（固定，不参与 flex 伸缩）*/
.detail-meta { flex-shrink: 0; padding: .8rem 1.1rem .5rem; }
.detail-title { font-size: .93rem; font-weight: 600; color: #1e293b; line-height: 1.4; margin-bottom: .45rem; }
.detail-info-row { display: flex; flex-wrap: wrap; gap: .35rem; }
.info-chip {
  display: inline-flex; align-items: center; gap: .28rem;
  font-size: .73rem; color: #64748b; background: #f8fafc; border-radius: 5px; padding: .15rem .4rem;
}
.info-chip a { color: #6366f1; text-decoration: none; }

.section-label { font-size: .73rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; margin-bottom: .35rem; }

/* 摘要框：flex:1 自适应剩余高度，内部可滚动 */
.abstract-box {
  flex: 1; min-height: 0;
  border-top: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
  margin: 0 1.1rem .6rem;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.abstract-box-header {
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: .38rem .65rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.abstract-box-body {
  flex: 1; overflow-y: auto;
  padding: .6rem .65rem;
}
.abstract-body { font-size: .82rem; color: #475569; line-height: 1.68; word-break: break-word; white-space: pre-wrap; }
.abstract-empty { color: #cbd5e1; font-size: .8rem; font-style: italic; }

/* 折叠面板（固定高度，不参与 flex 伸缩）*/
.ref-panels { flex-shrink: 0; padding: 0 1.1rem .5rem; }
.ref-panel { border: 1px solid #e2e8f0; border-radius: 7px; margin-bottom: .45rem; overflow: hidden; }
.ref-panel-header {
  display: flex; align-items: center; gap: .5rem;
  padding: .45rem .7rem; background: #f8fafc; cursor: pointer;
  font-size: .78rem; font-weight: 600; color: #475569;
}
.ref-panel-header:hover { background: #f1f5f9; }
.ref-panel-body { padding: .6rem .7rem; font-size: .78rem; color: #475569; }
.ref-panel-empty { color: #94a3b8; font-style: italic; }
.criteria-list { margin: 0; padding-left: 1.2rem; }
.criteria-list li { margin-bottom: .28rem; line-height: 1.5; }
.field-item { display: flex; gap: .5rem; margin-bottom: .38rem; }
.field-name { font-weight: 600; color: #334155; min-width: 80px; flex-shrink: 0; }
.field-def  { color: #64748b; }

/* AI 判断（固定）*/
.detail-ai { flex-shrink: 0; padding: 0 1.1rem .5rem; }
.ai-result-row { display: flex; align-items: flex-start; gap: .6rem; flex-wrap: wrap; }
.ai-reason { font-size: .78rem; color: #64748b; flex: 1; line-height: 1.5; }

/* 固定底部操作区 */
.detail-action {
  flex-shrink: 0;
  padding: .65rem 1.1rem;
  border-top: 1px solid #e2e8f0;
  background: #fff;
  box-shadow: 0 -2px 8px rgba(0,0,0,.04);
}
.action-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: .6rem; margin-bottom: .4rem;
}
.action-btns { display: flex; gap: .5rem; flex-wrap: wrap; }
.action-btn {
  padding: .4rem .9rem; border-radius: 7px; border: 2px solid #e2e8f0;
  background: #fff; font-size: .82rem; cursor: pointer;
  display: flex; align-items: center; gap: .32rem;
  transition: all .15s; color: #64748b;
}
.action-btn:disabled { opacity: .5; cursor: not-allowed; }
.action-btn.included:hover, .action-btn.included.active { background: #dcfce7; border-color: #16a34a; color: #16a34a; }
.action-btn.excluded:hover, .action-btn.excluded.active { background: #fee2e2; border-color: #dc2626; color: #dc2626; }
.action-btn.pending:hover,  .action-btn.pending.active  { background: #fef9c3; border-color: #ca8a04; color: #ca8a04; }

.reason-wrap textarea {
  width: 100%; border: 1px solid #e2e8f0; border-radius: 6px; padding: .4rem .5rem;
  font-size: .81rem; color: #334155; resize: none; outline: none; box-sizing: border-box;
  background: #fafafa;
}
.reason-wrap textarea:focus { border-color: #6366f1; background: #fff; }
.save-status { font-size: .73rem; white-space: nowrap; }
.save-status.success { color: #16a34a; }
.save-status.error   { color: #dc2626; }

/* 文献 URL 行 */
.detail-url {
  display: flex; align-items: center; gap: 6px;
  font-size: .78rem; margin: 3px 0 6px;
  color: #64748b;
}
.detail-url i { font-size: .72rem; color: #94a3b8; flex-shrink: 0; }
.detail-url a { color: #3b82f6; text-decoration: none; word-break: break-all; }
.detail-url a:hover { text-decoration: underline; }
.url-none { color: #94a3b8; font-style: italic; }

/* 排除快捷标准 */
.quick-criteria {
  margin-bottom: 6px;
}
.quick-criteria-label {
  font-size: .74rem; color: #64748b; margin-bottom: 4px;
}
.quick-criteria-tags {
  display: flex; flex-wrap: wrap; gap: 6px;
}
.criteria-tag {
  display: flex; flex-direction: column; align-items: flex-start;
  max-width: 220px;
  padding: 5px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: all .15s;
}
.criteria-tag:hover {
  background: #fef3c7; border-color: #f59e0b;
}
.criteria-tag.active {
  background: #fee2e2; border-color: #f87171;
}
.criteria-tag-num {
  font-size: .68rem; font-weight: 700; color: #ef4444;
  line-height: 1.2;
}
.criteria-tag-text {
  font-size: .72rem; color: #475569; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
