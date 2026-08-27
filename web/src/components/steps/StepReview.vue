<template>
  <div class="step-review">
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
                <span v-else-if="item.consensus === 'conflict'" class="badge conflict">
                  <i class="fas fa-exclamation-triangle"></i> 分歧
                </span>
                <span v-else-if="item.ai_decision" class="badge ai" :class="item.ai_decision">
                  AI · {{ decisionLabel(item.ai_decision) }}
                </span>
                <span v-else class="badge pending">待审</span>
                <!-- 备注图标 -->
                <span
                  v-if="item.has_notes"
                  class="ref-note-icon"
                  title="查看备注历史"
                  @click.stop="openNotesPanel(item)"
                >
                  <i class="fas fa-sticky-note"></i>
                </span>
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
            <div class="detail-title-row">
              <h3 class="detail-title">{{ selected.title }}</h3>
              <div class="detail-title-actions">
                <button @click="criteriaPopup = true" class="icon-action-btn" title="查看纳排标准">
                  <i class="fas fa-clipboard-list"></i>
                  <span>纳排标准</span>
                </button>
                <button v-if="extractionFields.length" @click="fieldsPopup = true" class="icon-action-btn" title="查看提取字段">
                  <i class="fas fa-tags"></i>
                  <span>提取字段</span>
                </button>
              </div>
            </div>
            <div class="detail-url">
              <i class="fas fa-external-link-alt"></i>
              <a v-if="selected.doi" :href="'https://doi.org/' + selected.doi" target="_blank">https://doi.org/{{ selected.doi }}</a>
              <a v-else-if="selected.url" :href="selected.url" target="_blank">{{ selected.url }}</a>
              <span v-else class="url-none">无法获取 URL</span>
            </div>
            <div class="detail-info-row">
              <span v-if="selected.authors" class="info-chip info-chip-authors" :title="selected.authors"><i class="fas fa-users"></i> {{ selected.authors }}</span>
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

          <!-- AI 判断 -->
          <div class="detail-ai" v-if="selected.ai_decision">
            <div v-if="selected.consensus === 'conflict'" class="conflict-alert">
              <i class="fas fa-exclamation-triangle mr-1"></i>
              <span><b>模型结论分歧</b> — 各模型判断不一致，请人工裁定</span>
            </div>
            <div v-if="selected.multi_model_results && selected.multi_model_results.length > 1" class="multi-model-results">
              <button class="multi-model-toggle" @click="multiModelOpen = !multiModelOpen">
                <i class="fas fa-layer-group mr-1"></i>
                多模型判断明细
                <span class="toggle-count">（{{ selected.multi_model_results.length }} 个模型）</span>
                <i :class="multiModelOpen ? 'fas fa-chevron-up' : 'fas fa-chevron-down'" class="ml-auto"></i>
              </button>
              <template v-if="multiModelOpen">
                <div v-for="(mr, mi) in selected.multi_model_results" :key="mi" class="model-result-row">
                  <div class="model-result-header">
                    <span class="model-result-name">
                      <span v-if="mr.model_name?.includes('Doubao')">🫘</span>
                      <span v-else-if="mr.model_name?.includes('DeepSeek')">🤖</span>
                      <span v-else-if="mr.model_name?.includes('Qwen')">🌙</span>
                      <span v-else>🧠</span>
                      {{ mr.model_name || mr.model_id }}
                    </span>
                    <span class="badge ai" :class="mr.decision">{{ decisionLabel(mr.decision) }}</span>
                  </div>
                  <div v-if="mr.reason" class="model-result-reason">{{ mr.reason }}</div>
                </div>
              </template>
            </div>
            <div v-else class="ai-result-row">
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

            <!-- 备注区（所有决定通用，独立于排除理由） -->
            <div class="note-wrap">
              <div class="reason-wrap-label">
                <i class="fas fa-sticky-note mr-1 text-gray-400"></i>备注
                <span class="text-xs text-gray-400 ml-1">（可选，按回车保存）</span>
              </div>
              <div class="note-input-row">
                <textarea v-model="localNote" placeholder="添加备注…" rows="1"
                  @keydown.enter.exact.prevent="localNote.trim() && saveNote()" />
                <button class="note-save-btn" @click="saveNote" :disabled="saving || !localNote.trim()">
                  <i class="fas fa-save"></i>
                </button>
              </div>
            </div>
          </div>

          <!-- ── 排除理由侧边栏（从排除按钮弹出，浮于右侧）── -->
          <transition name="reason-panel-slide">
            <div v-if="reasonPanelOpen" class="reason-side-panel" @keydown.esc="closeReasonPanel">
              <div class="reason-panel-header">
                <span><i class="fas fa-ban mr-1.5 text-red-400"></i>排除理由</span>
                <button class="reason-panel-close" @click="closeReasonPanel" title="取消排除">
                  <i class="fas fa-times"></i>
                </button>
              </div>
              <div class="reason-panel-body">
                <!-- 快捷标准 -->
                <div v-if="criteriaList.length" class="reason-criteria-list">
                  <div class="reason-criteria-label">快速选择排除标准：</div>
                  <button
                    v-for="(c, i) in criteriaList" :key="i"
                    class="reason-criteria-item"
                    :class="{ active: localReason === c }"
                    @click="pickCriteria(c)"
                    :title="c"
                  >
                    <span class="rci-num">{{ i + 1 }}</span>
                    <span class="rci-text">{{ c }}</span>
                  </button>
                </div>
                <!-- 分隔线 -->
                <div v-if="criteriaList.length" class="reason-panel-divider">
                  <span>或自定义理由</span>
                </div>
                <!-- 自定义输入 -->
                <textarea
                  ref="reasonTextarea"
                  v-model="localReason"
                  class="reason-panel-input"
                  placeholder="输入自定义排除理由，按 Enter 确认…"
                  rows="3"
                  @keydown.enter.exact.prevent="confirmExclude"
                />
              </div>
              <div class="reason-panel-footer">
                <button class="reason-cancel-btn" @click="closeReasonPanel">取消</button>
                <button class="reason-confirm-btn" @click="confirmExclude" :disabled="saving">
                  <i class="fas fa-check mr-1"></i>确认排除 → 下一篇
                </button>
              </div>
            </div>
          </transition>
        </template>

        <div v-else class="detail-empty">
          <i class="fas fa-hand-pointer"></i>
          <p>从左侧列表选择一篇文献开始审阅</p>
        </div>
      </div>
    </div>

    <!-- ── 纳排标准弹窗 ── -->
    <div v-if="criteriaPopup" class="popup-overlay" @click.self="criteriaPopup = false">
      <div class="popup-box">
        <div class="popup-header">
          <span><i class="fas fa-clipboard-list mr-2 text-indigo-500"></i>纳排标准</span>
          <button @click="criteriaPopup = false" class="popup-close"><i class="fas fa-times"></i></button>
        </div>
        <div class="popup-body">
          <ol v-if="criteriaList.length" class="criteria-popup-list">
            <li v-for="(c, i) in criteriaList" :key="i">{{ c }}</li>
          </ol>
          <div v-else class="popup-empty">尚未设置纳排标准</div>
        </div>
      </div>
    </div>

    <!-- ── 备注历史弹窗 ── -->
    <div v-if="notesPanelOpen" class="popup-overlay" @click.self="notesPanelOpen = false">
      <div class="popup-box notes-popup-box">
        <div class="popup-header">
          <span><i class="fas fa-sticky-note mr-2 text-amber-500"></i>备注历史</span>
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-400 font-normal">{{ notesPanelTitle }}</span>
            <button @click="notesPanelOpen = false" class="popup-close"><i class="fas fa-times"></i></button>
          </div>
        </div>
        <div class="popup-body notes-popup-body">
          <div v-if="notesLoading" class="notes-loading">
            <i class="fas fa-spinner fa-spin mr-1"></i>加载中…
          </div>
          <div v-else-if="notesList.length === 0" class="notes-empty">
            <i class="fas fa-comment-slash"></i>
            <span>暂无备注记录</span>
          </div>
          <div v-else class="notes-list">
            <div v-for="(note, i) in notesList" :key="i" class="note-history-item">
              <div class="note-history-meta">
                <span class="note-history-user"><i class="fas fa-user-circle mr-1"></i>{{ note.user }}</span>
                <span class="note-history-time">{{ formatNoteTime(note.created_at) }}</span>
              </div>
              <div class="note-history-content">{{ note.content }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 提取字段弹窗 ── -->
    <div v-if="fieldsPopup" class="popup-overlay" @click.self="fieldsPopup = false">
      <div class="popup-box">
        <div class="popup-header">
          <span><i class="fas fa-tags mr-2 text-indigo-500"></i>自定义提取字段</span>
          <button @click="fieldsPopup = false" class="popup-close"><i class="fas fa-times"></i></button>
        </div>
        <div class="popup-body">
          <div v-for="f in extractionFields" :key="f.name" class="field-popup-item">
            <span class="field-name">{{ f.name }}</span>
            <span class="field-def">{{ f.definition }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
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
const localReason   = ref('')   // 排除理由（仅排除时使用）
const localNote     = ref('')   // 备注（所有决定通用）
const saving        = ref(false)
const saveStatus    = ref('')
const saveStatusType = ref('')

// 弹窗状态
const criteriaPopup   = ref(false)
const fieldsPopup     = ref(false)
const multiModelOpen  = ref(false)   // 多模型明细折叠开关（默认收起）
const reasonPanelOpen = ref(false)   // 排除理由侧边栏
const reasonTextarea  = ref(null)    // 侧边栏 textarea ref

// 备注历史面板
const notesPanelOpen  = ref(false)
const notesPanelTitle = ref('')
const notesLoading    = ref(false)
const notesList       = ref([])
const notesPanelXml   = ref('')

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
  { key: 'conflict',   label: '⚠️ 分歧', tip: '模型结论不一致，需人工裁定' },
  { key: 'included',   label: '纳入' },
  { key: 'excluded',   label: '排除' },
  { key: 'pending',    label: '待定' },
]

function tabCount(key) {
  const s = stats.value
  if (key === '')           return s.total || ''
  if (key === 'unreviewed') return Math.max(0, (s.total - s.reviewed)) || ''
  // 最终决定口径（人工有则用人工，否则用AI，不重不漏）：加起来 = total
  if (key === 'included')   return s.tab_included ?? ''
  if (key === 'excluded')   return s.tab_excluded ?? ''
  if (key === 'pending')    return s.tab_pending  ?? ''
  if (key === 'conflict')   return s.tab_conflict ?? ''
  return ''
}

const decisionOpts = [
  { value: 'included', label: '纳入', icon: 'fas fa-check' },
  { value: 'pending',  label: '待定', icon: 'fas fa-question' },
  { value: 'excluded', label: '排除', icon: 'fas fa-times'  },
]

function decisionLabel(v) {
  return { included: '纳入', excluded: '排除', pending: '待定', conflict: '分歧', error: '错误' }[v] || v || '—'
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

async function saveDecision(decision, reason, autoNext = false) {
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
    // 更新本地列表显示
    const item = displayItems.value.find(i => i.source_xml === selected.value.source_xml)
    const prevDecision = item?.human_decision ?? null   // 保存前的人工决定（null = 未审阅）
    // 保存前该文献的「最终决定」（用于从 tab_* 中扣减）
    const prevFinalDec = prevDecision !== null
      ? prevDecision
      : (item?.consensus === 'conflict' ? 'conflict' : (item?.ai_decision || 'pending'))

    if (item) { item.human_decision = decision; item.human_reason = reason; item.is_override = item.ai_decision !== decision }
    selected.value.human_decision = decision
    selected.value.human_reason   = reason
    selected.value.is_override    = selected.value.ai_decision !== decision

    // ── 立即本地更新 Tab 计数（最终决定口径）──────────────────────
    const s = stats.value
    if (prevDecision === null) {
      s.reviewed = (s.reviewed ?? 0) + 1  // 首次审阅
    }
    // 从之前的最终分类扣减
    if (prevFinalDec === 'included')  s.tab_included = Math.max(0, (s.tab_included ?? 0) - 1)
    else if (prevFinalDec === 'excluded') s.tab_excluded = Math.max(0, (s.tab_excluded ?? 0) - 1)
    else if (prevFinalDec === 'pending')  s.tab_pending  = Math.max(0, (s.tab_pending  ?? 0) - 1)
    else if (prevFinalDec === 'conflict') s.tab_conflict = Math.max(0, (s.tab_conflict ?? 0) - 1)
    // 加入新的人工决定分类
    if (decision === 'included')      s.tab_included = (s.tab_included ?? 0) + 1
    else if (decision === 'excluded') s.tab_excluded = (s.tab_excluded ?? 0) + 1
    else if (decision === 'pending')  s.tab_pending  = (s.tab_pending  ?? 0) + 1

    saveStatus.value     = '已保存 ✓'
    saveStatusType.value = 'success'
    // 后台静默刷新，确保最终数据精准（不阻塞 UI）
    loadStats()
    setTimeout(() => { saveStatus.value = '' }, 2000)

    // 保存后自动跳转下一篇（仅主决策按钮触发时）
    if (autoNext) {
      goNextItem()
    }
  } catch (e) {
    saveStatus.value     = '保存失败，请重试'
    saveStatusType.value = 'error'
  } finally { saving.value = false }
}

/** 根据当前过滤 Tab，跳转到列表中的下一篇文献 */
function goNextItem() {
  if (!selected.value || !displayItems.value.length) return
  const curIdx = displayItems.value.findIndex(i => i.source_xml === selected.value.source_xml)
  const nextIdx = curIdx + 1
  if (nextIdx < displayItems.value.length) {
    selectItem(displayItems.value[nextIdx])
  } else if (page.value < totalPages.value) {
    // 当前页末尾，加载下一页后选第一篇
    loadItems(page.value + 1).then(() => {
      if (displayItems.value.length) selectItem(displayItems.value[0])
    })
  }
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
  reasonPanelOpen.value = false   // 切换文献时关闭侧边栏
  // 若之前是排除，reason 是排除理由；否则是备注
  if (item.human_decision === 'excluded') {
    localReason.value = item.human_reason || ''
    localNote.value   = ''
  } else {
    localReason.value = ''
    localNote.value   = item.human_reason || ''
  }
  saveStatus.value    = ''
  // 多模型明细默认收起（分歧文献也不自动展开，用户按需查看）
  multiModelOpen.value = false
}

function setDecision(value) {
  if (value === 'excluded') {
    // 排除：弹出侧边栏，不立即保存
    localDecision.value = value
    reasonPanelOpen.value = true
    nextTick(() => {
      // 若已有快捷标准则不自动聚焦 textarea，让用户先看标准
      if (!criteriaList.value.length) {
        reasonTextarea.value?.focus()
      }
    })
    return
  }
  // 纳入/待定：立即保存并跳转下一篇
  reasonPanelOpen.value = false
  localDecision.value = value
  saveDecision(value, localNote.value, true)
}

function closeReasonPanel() {
  reasonPanelOpen.value = false
  // 如果尚未保存过排除决定，还原 localDecision
  if (selected.value && selected.value.human_decision !== 'excluded') {
    localDecision.value = selected.value.human_decision || ''
  }
}

/** 确认排除：选好理由后点击，保存并跳转 */
function confirmExclude() {
  reasonPanelOpen.value = false
  saveDecision('excluded', localReason.value, true)
}

/** 保存备注（不跳转，追加到 notes 字段） */
async function saveNote() {
  if (!selected.value || !localNote.value.trim()) return
  saving.value = true
  saveStatus.value = '保存中…'
  saveStatusType.value = ''
  try {
    const xmlEncoded = encodeURIComponent(selected.value.source_xml)
    await http.post(`/review/note/${xmlEncoded}/`, {
      project: project.currentProject?.id,
      step:    reviewStepId.value,
      content: localNote.value.trim(),
    })
    // 标记该文献已有备注
    const item = displayItems.value.find(i => i.source_xml === selected.value.source_xml)
    if (item) item.has_notes = true
    selected.value.has_notes = true
    localNote.value = ''
    saveStatus.value = '备注已保存 ✓'
    saveStatusType.value = 'success'
    setTimeout(() => { saveStatus.value = '' }, 2000)
  } catch (e) {
    saveStatus.value = '备注保存失败，请重试'
    saveStatusType.value = 'error'
  } finally {
    saving.value = false
  }
}

/** 打开备注历史面板 */
async function openNotesPanel(item) {
  notesPanelXml.value   = item.source_xml
  notesPanelTitle.value = item.title || item.source_xml
  notesPanelOpen.value  = true
  notesLoading.value    = true
  notesList.value       = []
  try {
    const xmlEncoded = encodeURIComponent(item.source_xml)
    const res = await http.get(`/review/notes/${xmlEncoded}/`, {
      params: { project: project.currentProject?.id }
    })
    notesList.value = res.data.notes || []
  } catch (e) {
    console.error('[review] load notes error', e)
  } finally {
    notesLoading.value = false
  }
}

/** 格式化备注时间 */
function formatNoteTime(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch { return isoStr }
}

// 快捷标准：点击即选中理由，不自动跳转（需用户点确认排除按钮）
function pickCriteria(criteriaText) {
  localReason.value = criteriaText
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
.badge.ai.included { background: #dcfce7; color: #16a34a; }
.badge.ai.excluded { background: #fee2e2; color: #dc2626; }
.badge.pending  { background: #fef9c3; color: #ca8a04; }
.badge.conflict { background: #fff7ed; color: #c2410c; border: 1px solid #fed7aa; }

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
/* .detail-title is now defined below in the title-row section */
.detail-info-row { display: flex; flex-wrap: wrap; gap: .35rem; }
.info-chip {
  display: inline-flex; align-items: center; gap: .28rem;
  font-size: .73rem; color: #64748b; background: #f8fafc; border-radius: 5px; padding: .15rem .4rem;
}
.info-chip a { color: #6366f1; text-decoration: none; }
/* 作者 chip：限制宽度，超出截断，hover 显示完整内容 */
.info-chip-authors {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

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
.abstract-body { font-size: .9rem; color: #334155; line-height: 1.75; word-break: break-word; white-space: pre-wrap; }
.abstract-empty { color: #cbd5e1; font-size: .8rem; font-style: italic; }

/* 弹窗内字段样式（复用旧 field-item） */
.field-name { font-weight: 600; color: #334155; min-width: 80px; flex-shrink: 0; }
.field-def  { color: #64748b; font-size: .83rem; }

/* AI 判断（固定，但内部可滚动以防理由超长）*/
.detail-ai {
  flex-shrink: 0;
  max-height: 240px;
  overflow-y: auto;
  padding: 0 1.1rem .5rem;
}
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

.save-status { font-size: .73rem; white-space: nowrap; }
.save-status.success { color: #16a34a; }
.save-status.error   { color: #dc2626; }

/* 排除理由区 + 备注区标题 */
.reason-wrap-label {
  font-size: .74rem; color: #64748b; font-weight: 600; margin-bottom: 5px;
  display: flex; align-items: center;
}

/* 备注区独立样式（始终显示） */
.note-wrap {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
}
.note-input-row {
  display: flex; align-items: flex-start; gap: 6px;
}
.note-input-row textarea {
  flex: 1;
  border: 1px solid #e2e8f0; border-radius: 6px; padding: .4rem .5rem;
  font-size: .81rem; color: #334155; resize: none; outline: none; box-sizing: border-box;
  background: #fafafa;
}
.note-input-row textarea:focus { border-color: #6366f1; background: #fff; }
.note-save-btn {
  flex-shrink: 0;
  width: 32px; height: 32px;
  border-radius: 6px; border: 1px solid #6366f1;
  background: #eef2ff; color: #6366f1; font-size: .82rem; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all .15s; margin-top: 1px;
}
.note-save-btn:hover:not(:disabled) { background: #6366f1; color: #fff; }
.note-save-btn:disabled { opacity: .5; cursor: not-allowed; }

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

/* ── 分歧标识条 ── */
.conflict-alert {
  display: flex; align-items: center; gap: 8px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: .8rem;
  color: #c2410c;
  margin-bottom: 8px;
}
.conflict-alert i { flex-shrink: 0; }

/* ── 多模型判断明细 ── */
.multi-model-results {
  margin-top: 6px;
}
.multi-model-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 6px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  font-size: .78rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: background .12s;
  text-align: left;
}
.multi-model-toggle:hover { background: #eef2ff; color: #4338ca; border-color: #c7d2fe; }
.toggle-count { font-weight: 400; color: #94a3b8; }
.model-result-row {
  background: #fafafa;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 6px;
}
.model-result-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 4px;
}
.model-result-name {
  font-size: .82rem; font-weight: 600; color: #334155;
  display: flex; align-items: center; gap: 4px;
}
.model-result-reason {
  font-size: .76rem; color: #64748b; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
}

/* ── 标题行（标题 + 图标操作按钮）── */
.detail-title-row {
  display: flex; align-items: flex-start; justify-content: space-between; gap: .6rem;
  margin-bottom: .3rem;
}
.detail-title { flex: 1; margin: 0; font-size: .95rem; font-weight: 700; color: #1e293b; line-height: 1.4; }
.detail-title-actions {
  display: flex; gap: .4rem; flex-shrink: 0; margin-top: 2px;
}
.icon-action-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 8px; border-radius: 6px; border: 1px solid #e2e8f0;
  background: #f8fafc; color: #6366f1; font-size: .72rem; cursor: pointer;
  transition: all .15s; white-space: nowrap;
}
.icon-action-btn:hover { background: #eef2ff; border-color: #6366f1; }
.icon-action-btn i { font-size: .7rem; }

/* ── 弹窗 ── */
.popup-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,.45);
  display: flex; align-items: center; justify-content: center;
}
.popup-box {
  background: #fff; border-radius: 12px;
  width: min(520px, 90vw); max-height: 75vh;
  display: flex; flex-direction: column;
  box-shadow: 0 20px 60px rgba(0,0,0,.18);
  overflow: hidden;
}
.popup-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: .75rem 1.1rem; border-bottom: 1px solid #e2e8f0;
  font-size: .88rem; font-weight: 700; color: #1e293b;
}
.popup-close {
  background: none; border: none; cursor: pointer;
  color: #94a3b8; font-size: .85rem; padding: 2px 6px;
  border-radius: 4px; transition: background .12s;
}
.popup-close:hover { background: #f1f5f9; color: #475569; }
.popup-body {
  flex: 1; overflow-y: auto; padding: .9rem 1.1rem;
}
.popup-empty { color: #94a3b8; font-style: italic; font-size: .82rem; }
.criteria-popup-list {
  margin: 0; padding-left: 1.4rem;
}
.criteria-popup-list li {
  font-size: .85rem; color: #334155; margin-bottom: .6rem; line-height: 1.6;
}
.field-popup-item {
  display: flex; gap: .6rem; padding: .4rem 0;
  border-bottom: 1px solid #f1f5f9;
}
.field-popup-item:last-child { border-bottom: none; }

/* ── 排除理由侧边栏 ── */
.reason-side-panel {
  position: absolute;
  /* 从底部 action 栏上方弹出，紧贴右侧 */
  right: 0;
  bottom: 0;
  width: 320px;
  max-height: calc(100% - 48px);  /* 不超出 detail-panel */
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #fca5a5;
  border-bottom: none;
  border-radius: 12px 12px 0 0;
  box-shadow: -4px -4px 20px rgba(220,38,38,.12), -2px 0 12px rgba(0,0,0,.06);
  z-index: 100;
  overflow: hidden;
}
/* 让 detail-panel 成为定位容器 */
.detail-panel { position: relative; }

.reason-panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: .7rem 1rem .6rem;
  background: #fef2f2;
  border-bottom: 1px solid #fecaca;
  font-size: .85rem; font-weight: 700; color: #dc2626;
  flex-shrink: 0;
}
.reason-panel-close {
  width: 24px; height: 24px; border-radius: 50%;
  border: none; background: transparent;
  color: #ef4444; cursor: pointer; font-size: .8rem;
  display: flex; align-items: center; justify-content: center;
  transition: background .12s;
}
.reason-panel-close:hover { background: #fee2e2; }

.reason-panel-body {
  flex: 1; overflow-y: auto;
  padding: .75rem .9rem .5rem;
}

.reason-criteria-label {
  font-size: .73rem; color: #94a3b8; font-weight: 600;
  margin-bottom: 6px; text-transform: uppercase; letter-spacing: .04em;
}
.reason-criteria-list { margin-bottom: 4px; }
.reason-criteria-item {
  display: flex; align-items: flex-start; gap: 8px;
  width: 100%; text-align: left;
  padding: 7px 10px; margin-bottom: 5px;
  background: #fafafa; border: 1.5px solid #e2e8f0;
  border-radius: 8px; cursor: pointer;
  transition: all .15s;
}
.reason-criteria-item:hover {
  background: #fff7ed; border-color: #f97316;
}
.reason-criteria-item.active {
  background: #fee2e2; border-color: #ef4444;
}
.rci-num {
  flex-shrink: 0;
  width: 20px; height: 20px; border-radius: 50%;
  background: #fee2e2; color: #dc2626;
  font-size: .68rem; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  margin-top: 1px;
}
.reason-criteria-item.active .rci-num { background: #dc2626; color: #fff; }
.rci-text {
  font-size: .78rem; color: #475569; line-height: 1.45; flex: 1;
}

.reason-panel-divider {
  display: flex; align-items: center; gap: 6px;
  margin: 8px 0 10px; color: #cbd5e1; font-size: .72rem;
}
.reason-panel-divider::before,
.reason-panel-divider::after {
  content: ''; flex: 1; height: 1px; background: #e2e8f0;
}

.reason-panel-input {
  width: 100%; border: 1.5px solid #e2e8f0; border-radius: 8px;
  padding: .45rem .6rem; font-size: .82rem; color: #334155;
  resize: none; outline: none; box-sizing: border-box;
  background: #fafafa; line-height: 1.5;
  transition: border-color .15s, background .15s;
}
.reason-panel-input:focus { border-color: #ef4444; background: #fff; }

.reason-panel-footer {
  display: flex; gap: .5rem; justify-content: flex-end;
  padding: .6rem .9rem;
  border-top: 1px solid #fecaca;
  background: #fef2f2;
  flex-shrink: 0;
}
.reason-cancel-btn {
  padding: .38rem .85rem; border-radius: 7px;
  border: 1px solid #e2e8f0; background: #fff;
  color: #64748b; font-size: .8rem; cursor: pointer;
  transition: all .15s;
}
.reason-cancel-btn:hover { background: #f1f5f9; }
.reason-confirm-btn {
  padding: .38rem 1rem; border-radius: 7px;
  border: none; background: #dc2626;
  color: #fff; font-size: .8rem; font-weight: 600;
  cursor: pointer; display: flex; align-items: center;
  transition: background .15s;
}
.reason-confirm-btn:hover:not(:disabled) { background: #b91c1c; }
.reason-confirm-btn:disabled { opacity: .55; cursor: not-allowed; }

/* 侧边栏出入动画 */
.reason-panel-slide-enter-active,
.reason-panel-slide-leave-active {
  transition: transform .22s cubic-bezier(.4,0,.2,1), opacity .18s;
}
.reason-panel-slide-enter-from,
.reason-panel-slide-leave-to {
  transform: translateY(16px);
  opacity: 0;
}

/* ── 备注图标（列表项右下角）── */
.ref-status {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.ref-note-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px; height: 18px;
  border-radius: 4px;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  color: #d97706;
  font-size: .62rem;
  cursor: pointer;
  transition: all .12s;
  flex-shrink: 0;
}
.ref-note-icon:hover { background: #fef3c7; border-color: #f59e0b; color: #b45309; }

/* ── 备注历史弹窗 ── */
.notes-popup-box {
  width: min(480px, 92vw);
  max-height: 70vh;
}
.notes-popup-body {
  padding: .7rem 1rem;
  overflow-y: auto;
}
.notes-loading {
  text-align: center; padding: 1.5rem;
  color: #94a3b8; font-size: .82rem;
}
.notes-empty {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: .5rem;
  padding: 2rem; color: #cbd5e1; font-size: .82rem;
}
.notes-empty i { font-size: 1.6rem; }
.notes-list { display: flex; flex-direction: column; gap: 8px; }
.note-history-item {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 10px 12px;
}
.note-history-meta {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 6px;
}
.note-history-user {
  font-size: .72rem; color: #92400e; font-weight: 600;
}
.note-history-time {
  font-size: .7rem; color: #a16207;
}
.note-history-content {
  font-size: .82rem; color: #334155; line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
}

</style>
