<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#8b5cf6,#a78bfa)">
        <i class="fas fa-clone"></i>
      </div>
      <div>
        <h3 class="step-title">文献自动去重</h3>
        <p class="step-subtitle">检测并合并重复文献，保留最优记录</p>
      </div>
    </div>

    <!-- 去重进度条 -->
    <div v-if="s.isDeduplicating" class="dedup-progress-banner mb-5">
      <div class="flex items-center gap-2 mb-2">
        <i class="fas fa-spinner fa-spin text-purple-500"></i>
        <span class="font-medium text-sm text-purple-700">
          {{ s.dedupProgressMsg || '正在启动去重...' }}
        </span>
      </div>
      <div class="progress-bar-track" style="height:5px">
        <div
          v-if="s.dedupProgressCurrent > 0 && s.dedupProgressCurrent < 100"
          class="progress-bar-fill"
          :style="{ width: s.dedupProgressCurrent + '%', background: '#8b5cf6' }"
        ></div>
        <div
          v-else-if="s.dedupProgressCurrent >= 100"
          class="progress-bar-fill"
          style="width:100%;background:#8b5cf6"
        ></div>
        <div v-else class="progress-bar-fill animate-pulse" style="width:30%;background:#8b5cf6"></div>
      </div>
      <div class="text-xs mt-1 text-purple-400">
        <span v-if="s.dedupProgressCurrent > 0 && s.dedupProgressCurrent < 100">{{ s.dedupProgressCurrent }}%</span>
        <span v-else-if="s.dedupProgressCurrent >= 100">100% · 收尾中...</span>
        <span v-else>处理中...</span>
      </div>
    </div>

    <!-- 状态卡片 + 操作区 -->
    <div class="dedup-action-card">
      <!-- 左：状态信息 -->
      <div class="dedup-status-grid">
        <div class="dedup-status-item">
          <div class="dedup-status-icon" style="background:#eff6ff;color:#3b82f6">
            <i class="fas fa-file-alt"></i>
          </div>
          <div class="dedup-status-body">
            <div class="dedup-status-value">{{ s.referenceFiles.length }}</div>
            <div class="dedup-status-label">已导入索引文件</div>
          </div>
        </div>
        <div class="dedup-status-item">
          <div
            class="dedup-status-icon"
            :style="s.dedupCompleted
              ? 'background:#dcfce7;color:#16a34a'
              : 'background:#faf5ff;color:#8b5cf6'"
          >
            <i :class="s.dedupCompleted ? 'fas fa-check-circle' : 'fas fa-hourglass-half'"></i>
          </div>
          <div class="dedup-status-body">
            <div
              class="dedup-status-value"
              :style="s.dedupCompleted ? 'color:#16a34a' : 'color:#8b5cf6'"
            >
              {{ s.dedupCompleted ? '已完成' : '待处理' }}
            </div>
            <div class="dedup-status-label">去重状态</div>
          </div>
        </div>
        <template v-if="s.dedupStats">
          <div class="dedup-status-item">
            <div class="dedup-status-icon" style="background:#fee2e2;color:#dc2626">
              <i class="fas fa-copy"></i>
            </div>
            <div class="dedup-status-body">
              <div class="dedup-status-value" style="color:#dc2626">{{ s.dedupStats.duplicates }}</div>
              <div class="dedup-status-label">发现重复</div>
            </div>
          </div>
          <div class="dedup-status-item">
            <div class="dedup-status-icon" style="background:#dcfce7;color:#16a34a">
              <i class="fas fa-bookmark"></i>
            </div>
            <div class="dedup-status-body">
              <div class="dedup-status-value" style="color:#16a34a">{{ s.dedupStats.kept_files }}</div>
              <div class="dedup-status-label">保留文献</div>
            </div>
          </div>
        </template>
      </div>

      <!-- 右：操作按钮 -->
      <div class="dedup-action-btn-wrap">
        <button
          :disabled="s.isDeduplicating"
          class="dedup-btn"
          :class="s.dedupCompleted ? 'dedup-btn--redo' : 'dedup-btn--start'"
          @click="handleDeduplication"
        >
          <i v-if="s.isDeduplicating" class="fas fa-spinner fa-spin"></i>
          <i v-else :class="s.dedupCompleted ? 'fas fa-redo' : 'fas fa-magic'"></i>
          {{ s.isDeduplicating ? '正在去重…' : s.dedupCompleted ? '重新去重' : '开始去重' }}
        </button>
        <p v-if="!s.dedupCompleted && !s.isDeduplicating" class="dedup-btn-hint">
          将自动检测重复文献并合并
        </p>
        <p v-if="s.dedupStats?.completion_time" class="dedup-btn-hint">
          <i class="fas fa-clock mr-1"></i>
          {{ new Date(s.dedupStats.completion_time).toLocaleString() }}
        </p>
      </div>
    </div>

    <!-- 去重结果统计 -->
    <div v-if="s.dedupStats" class="dedup-result-section">
      <!-- 摘要柱图 -->
      <div class="dedup-bar-summary">
        <div class="dedup-bar-row">
          <span class="dedup-bar-label">原始文献</span>
          <div class="dedup-bar-track">
            <div class="dedup-bar-fill" style="width:100%;background:#c7d2fe"></div>
          </div>
          <span class="dedup-bar-num">{{ s.dedupStats.total_files }}</span>
        </div>
        <div class="dedup-bar-row">
          <span class="dedup-bar-label">保留</span>
          <div class="dedup-bar-track">
            <div
              class="dedup-bar-fill"
              :style="{ width: keptPct + '%', background: '#86efac' }"
            ></div>
          </div>
          <span class="dedup-bar-num" style="color:#16a34a">{{ s.dedupStats.kept_files }}</span>
        </div>
        <div class="dedup-bar-row">
          <span class="dedup-bar-label">重复去除</span>
          <div class="dedup-bar-track">
            <div
              class="dedup-bar-fill"
              :style="{ width: dupPct + '%', background: '#fca5a5' }"
            ></div>
          </div>
          <span class="dedup-bar-num" style="color:#dc2626">{{ s.dedupStats.duplicates }}</span>
        </div>
      </div>

      <!-- 重复率徽章 -->
      <div class="dedup-rate-badge">
        重复率 <strong>{{ s.dedupStats.duplicate_rate }}</strong>
      </div>

      <!-- 重复文献详细列表：服务端分页，成员按需加载 -->
      <div v-if="s.dedupStats.duplicate_groups > 0" class="mt-4">
        <div class="dedup-detail-header">
          <span class="font-semibold text-gray-700 text-sm">
            <i class="fas fa-list-ul mr-1.5 text-purple-400"></i>
            重复文献详情（共 {{ s.dedupStats.duplicate_groups || 0 }} 组）
          </span>
          <button
            class="dedup-detail-toggle"
            @click="toggleDuplicateDetails"
          >
            <i :class="s.showDuplicateDetails ? 'fas fa-chevron-up' : 'fas fa-chevron-down'"></i>
            {{ s.showDuplicateDetails ? '收起' : '展开' }}
          </button>
        </div>

        <div v-if="s.showDuplicateDetails" class="dedup-detail-panel">
          <div v-if="detailLoading" class="dedup-detail-state">
            <i class="fas fa-spinner fa-spin"></i> 正在加载重复组…
          </div>
          <div v-else-if="detailError" class="dedup-detail-state dedup-detail-error">
            <span>{{ detailError }}</span>
            <button @click="loadDuplicateGroups(groupPage)">重新加载</button>
          </div>
          <div v-else-if="duplicateGroups.length === 0" class="dedup-detail-state">
            当前页没有重复组
          </div>
          <div
            v-for="group in duplicateGroups"
            v-else
            :key="group.id"
            class="dedup-detail-item"
          >
            <button class="dedup-group-head" @click="toggleGroupMembers(group)">
              <span class="dedup-detail-title">
                {{ group.sequence }}. {{ group.title || '(无标题)' }}
              </span>
              <span class="dedup-group-count">
                {{ group.member_count }} 条
                <i :class="group.expanded ? 'fas fa-chevron-up' : 'fas fa-chevron-down'"></i>
              </span>
            </button>

            <div v-if="group.expanded" class="dedup-members">
              <div v-if="group.membersLoading" class="dedup-member-state">
                <i class="fas fa-spinner fa-spin"></i> 正在加载组内文献…
              </div>
              <div v-else-if="group.membersError" class="dedup-member-state dedup-detail-error">
                {{ group.membersError }}
                <button @click.stop="loadGroupMembers(group, group.memberPage)">重试</button>
              </div>
              <template v-else>
                <div
                  v-for="member in group.members"
                  :key="member.id"
                  class="dedup-ref"
                >
                  <span
                    class="dedup-ref-badge"
                    :class="member.role === 'kept' ? 'kept-badge' : 'dup-badge'"
                  >{{ member.role === 'kept' ? '保留' : '重复' }}</span>
                  <div class="dedup-ref-info">
                    <span class="font-medium text-gray-700">{{ member.reference.source_file }}</span>
                    <span class="text-blue-500 ml-1">#{{ member.reference.source_position }}</span>
                    <span v-if="member.reference.year" class="text-gray-400 ml-2">{{ member.reference.year }}</span>
                    <span v-if="member.reference.journal" class="text-gray-400 ml-2">· {{ member.reference.journal }}</span>
                    <a
                      v-if="member.reference.doi"
                      :href="'https://doi.org/' + member.reference.doi"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="dedup-doi-link ml-2"
                    >DOI</a>
                  </div>
                </div>
                <div v-if="group.memberTotalPages > 1" class="dedup-pagination dedup-pagination--members">
                  <button
                    :disabled="group.memberPage <= 1"
                    @click="loadGroupMembers(group, group.memberPage - 1)"
                  >
                    上一页
                  </button>
                  <span>{{ group.memberPage }} / {{ group.memberTotalPages }}</span>
                  <button
                    :disabled="group.memberPage >= group.memberTotalPages"
                    @click="loadGroupMembers(group, group.memberPage + 1)"
                  >
                    下一页
                  </button>
                </div>
              </template>
            </div>
          </div>

          <div v-if="groupTotalPages > 1 && !detailLoading" class="dedup-pagination">
            <button :disabled="groupPage <= 1" @click="loadDuplicateGroups(groupPage - 1)">
              <i class="fas fa-chevron-left"></i> 上一页
            </button>
            <span>第 {{ groupPage }} / {{ groupTotalPages }} 页</span>
            <button
              :disabled="groupPage >= groupTotalPages"
              @click="loadDuplicateGroups(groupPage + 1)"
            >
              下一页 <i class="fas fa-chevron-right"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'
import * as screeningApi from '@/features/screening/api'
import * as workflowApi from '@/shared/api/workflow'
import { findLatestDedupTask, getDedupTaskUiState } from '@/features/screening/dedupTaskState'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()
let dedupPollGeneration = 0
let dedupPollTimer = null
let componentActive = true
let groupRequestController = null
let groupRequestGeneration = 0
const memberRequestControllers = new Map()
const duplicateGroups = ref([])
const detailLoading = ref(false)
const detailError = ref('')
const groupPage = ref(1)
const groupTotalPages = ref(0)

function isCurrentProject(projectId) {
  return componentActive && Number(project.currentProject?.id) === Number(projectId)
}

function applyTaskState(task) {
  const state = getDedupTaskUiState(task)
  s.isDeduplicating = state.active
  s.dedupCompleted = state.completed
  s.dedupProgressCurrent = state.progress
  s.dedupProgressMsg = state.message
  return state
}

const keptPct = computed(() => {
  if (!s.dedupStats?.total_files) return 0
  return Math.round((s.dedupStats.kept_files / s.dedupStats.total_files) * 100)
})
const dupPct = computed(() => {
  if (!s.dedupStats?.total_files) return 0
  return Math.round((s.dedupStats.duplicates / s.dedupStats.total_files) * 100)
})

async function handleDeduplication() {
  if (s.referenceFiles.length === 0) {
    alert('请先上传文献文件')
    return
  }
  s.isDeduplicating = true
  resetDedupDetails()
  s.dedupProgressCurrent = 0
  s.dedupProgressMsg = '正在启动去重任务...'
  try {
    const res = await workflowApi.createTask({
      project: project.currentProject.id,
      task_type: 'dedup',
    })
    const task = res.data
    await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
    pollDedupStatus(task.id)
  } catch (err) {
    alert(`去重启动失败: ${err.response?.data?.error || err.message}`)
    s.isDeduplicating = false
  }
}

function resetDedupDetails() {
  groupRequestGeneration += 1
  groupRequestController?.abort()
  groupRequestController = null
  memberRequestControllers.forEach(controller => controller.abort())
  memberRequestControllers.clear()
  duplicateGroups.value = []
  detailLoading.value = false
  detailError.value = ''
  groupPage.value = 1
  groupTotalPages.value = 0
  s.showDuplicateDetails = false
}

async function toggleDuplicateDetails() {
  s.showDuplicateDetails = !s.showDuplicateDetails
  if (s.showDuplicateDetails && duplicateGroups.value.length === 0) {
    await loadDuplicateGroups(1)
  }
}

async function loadDuplicateGroups(page = 1) {
  const projectId = project.currentProject?.id
  const runId = s.dedupStats?.dedup_run_id
  if (!projectId || !runId) return

  groupRequestController?.abort()
  memberRequestControllers.forEach(controller => controller.abort())
  memberRequestControllers.clear()
  const controller = new AbortController()
  groupRequestController = controller
  const generation = ++groupRequestGeneration
  detailLoading.value = true
  detailError.value = ''
  try {
    const response = await screeningApi.fetchDedupGroups(
      projectId,
      runId,
      { page, page_size: 20 },
      { signal: controller.signal },
    )
    if (generation !== groupRequestGeneration || !isCurrentProject(projectId)) return
    duplicateGroups.value = response.data.results.map(group => ({
      ...group,
      expanded: false,
      members: [],
      membersLoading: false,
      membersError: '',
      memberPage: 1,
      memberTotalPages: 0,
    }))
    groupPage.value = response.data.page
    groupTotalPages.value = response.data.total_pages
  } catch (error) {
    if (error.code !== 'ERR_CANCELED' && generation === groupRequestGeneration) {
      detailError.value = error.response?.data?.detail || '重复组加载失败，请稍后重试'
    }
  } finally {
    if (generation === groupRequestGeneration) detailLoading.value = false
  }
}

async function toggleGroupMembers(group) {
  group.expanded = !group.expanded
  if (group.expanded && group.members.length === 0) {
    await loadGroupMembers(group, 1)
  }
}

async function loadGroupMembers(group, page = 1) {
  const projectId = project.currentProject?.id
  const runId = s.dedupStats?.dedup_run_id
  if (!projectId || !runId) return

  memberRequestControllers.get(group.id)?.abort()
  const controller = new AbortController()
  memberRequestControllers.set(group.id, controller)
  group.membersLoading = true
  group.membersError = ''
  try {
    const response = await screeningApi.fetchDedupGroupMembers(
      projectId,
      runId,
      group.id,
      { page, page_size: 50 },
      { signal: controller.signal },
    )
    if (!isCurrentProject(projectId) || memberRequestControllers.get(group.id) !== controller) return
    group.members = response.data.results
    group.memberPage = response.data.page
    group.memberTotalPages = response.data.total_pages
  } catch (error) {
    if (error.code !== 'ERR_CANCELED') {
      group.membersError = error.response?.data?.detail || '组内文献加载失败'
    }
  } finally {
    if (memberRequestControllers.get(group.id) === controller) {
      group.membersLoading = false
      memberRequestControllers.delete(group.id)
    }
  }
}

async function pollDedupStatus(taskId) {
  clearTimeout(dedupPollTimer)
  const generation = ++dedupPollGeneration
  const projectId = project.currentProject?.id
  if (!projectId) return
  let errorCount = 0
  const poll = async () => {
    if (generation !== dedupPollGeneration || !isCurrentProject(projectId)) return
    try {
      const res = await workflowApi.fetchTask(taskId)
      if (generation !== dedupPollGeneration || !isCurrentProject(projectId)) return
      const task = res.data
      if (Number(task.project) !== Number(projectId)) return
      const status = task.status
      applyTaskState(task)
      if (['running', 'pending', 'queuing'].includes(status)) {
        dedupPollTimer = setTimeout(poll, 500)
      } else if (status === 'completed') {
        await project.fetchStages(projectId)
        if (!isCurrentProject(projectId)) return
        await taskStore.fetchRecentTasks(projectId, project.stagesData)
        if (!isCurrentProject(projectId)) return
        loadDedupStats()
      } else {
        s.isDeduplicating = false
        await taskStore.fetchRecentTasks(project.currentProject.id, project.stagesData)
        alert(`去重失败: ${task.error_message || '任务执行失败'}`)
      }
    } catch (err) {
      errorCount++
      if (errorCount < 5 && isCurrentProject(projectId)) {
        dedupPollTimer = setTimeout(poll, 1000)
      } else {
        s.isDeduplicating = false
        console.error('轮询任务状态失败', err)
      }
    }
  }
  await poll()
}

async function restoreDedupTask() {
  const projectId = project.currentProject?.id
  if (!projectId) return
  const result = await taskStore.fetchRecentTasks(projectId, project.stagesData)
  if (!isCurrentProject(projectId)) return
  const latestTask = findLatestDedupTask(result?.tasks || taskStore.recentTasks)
  if (!latestTask) {
    s.isDeduplicating = false
    return
  }

  const state = applyTaskState(latestTask)
  if (state.active) {
    pollDedupStatus(latestTask.id)
  } else if (state.completed) {
    await project.fetchStages(projectId)
    if (isCurrentProject(projectId)) loadDedupStats()
  }
}

function loadDedupStats() {
  const screen1Stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!screen1Stage) return
  const dedupStep = screen1Stage.steps.find((st) => st.step_key === 'dedup')
  if (!dedupStep) return
  const previousRunId = s.dedupStats?.dedup_run_id
  s.dedupStats = (dedupStep.metadata?.total_files !== undefined) ? dedupStep.metadata : null
  if (previousRunId && previousRunId !== s.dedupStats?.dedup_run_id) resetDedupDetails()
  if (dedupStep.status === 'completed') s.dedupCompleted = true
}

onMounted(() => {
  loadDedupStats()
  restoreDedupTask()
})
onUnmounted(() => {
  componentActive = false
  dedupPollGeneration += 1
  clearTimeout(dedupPollTimer)
  resetDedupDetails()
})
</script>

<style scoped>
/* ── 进度横幅 ── */
.dedup-progress-banner {
  background: #faf5ff;
  border: 1px solid #ddd6fe;
  border-radius: 10px;
  padding: 12px 16px;
}

/* ── 状态卡片 ── */
.dedup-action-card {
  display: flex;
  align-items: center;
  gap: 24px;
  background: #fafbff;
  border: 1px solid #e0e7ff;
  border-radius: 14px;
  padding: 20px 24px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.dedup-status-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  flex: 1;
  min-width: 260px;
}
.dedup-status-item {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dedup-status-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: .9rem;
  flex-shrink: 0;
}
.dedup-status-body {}
.dedup-status-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.2;
}
.dedup-status-label {
  font-size: .72rem;
  color: #94a3b8;
  margin-top: 1px;
}

/* ── 操作按钮 ── */
.dedup-action-btn-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.dedup-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 28px;
  border-radius: 10px;
  font-weight: 600;
  font-size: .88rem;
  color: #fff;
  border: none;
  cursor: pointer;
  transition: opacity .2s, transform .1s;
  box-shadow: 0 2px 8px rgba(0,0,0,.12);
}
.dedup-btn:disabled { opacity: .55; cursor: not-allowed; }
.dedup-btn:not(:disabled):hover { opacity: .9; transform: translateY(-1px); }
.dedup-btn--start { background: linear-gradient(135deg, #8b5cf6, #6d28d9); }
.dedup-btn--redo  { background: linear-gradient(135deg, #f59e0b, #d97706); }
.dedup-btn-hint {
  font-size: .72rem;
  color: #94a3b8;
  text-align: center;
  margin: 0;
}

/* ── 结果区域 ── */
.dedup-result-section {
  background: linear-gradient(135deg, #faf5ff, #eef2ff);
  border: 1px solid #ddd6fe;
  border-radius: 14px;
  padding: 20px 24px;
}

/* 柱图 */
.dedup-bar-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}
.dedup-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dedup-bar-label {
  width: 60px;
  font-size: .75rem;
  color: #64748b;
  flex-shrink: 0;
  text-align: right;
}
.dedup-bar-track {
  flex: 1;
  height: 10px;
  background: #f1f5f9;
  border-radius: 99px;
  overflow: hidden;
}
.dedup-bar-fill {
  height: 100%;
  border-radius: 99px;
  transition: width .5s ease;
}
.dedup-bar-num {
  width: 36px;
  text-align: right;
  font-size: .8rem;
  font-weight: 700;
  color: #475569;
  flex-shrink: 0;
}

/* 重复率 */
.dedup-rate-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #ede9fe;
  color: #6d28d9;
  border-radius: 20px;
  padding: 3px 14px;
  font-size: .78rem;
  margin-bottom: 4px;
}
.dedup-rate-badge strong { font-size: .88rem; }

/* 详情 */
.dedup-detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.dedup-detail-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: .75rem;
  color: #8b5cf6;
  background: none;
  border: 1px solid #ddd6fe;
  border-radius: 6px;
  padding: 3px 10px;
  cursor: pointer;
  transition: background .15s;
}
.dedup-detail-toggle:hover { background: #f5f3ff; }

.dedup-detail-panel {
  background: #fff;
  border: 1px solid #ede9fe;
  border-radius: 10px;
  padding: 4px 0;
}
.dedup-detail-item {
  padding: 10px 14px;
  border-bottom: 1px solid #f8fafc;
}
.dedup-detail-item:last-child { border-bottom: none; }
.dedup-group-head {
  width: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.dedup-detail-title {
  font-size: .82rem;
  font-weight: 600;
  color: #334155;
}
.dedup-group-count {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #8b5cf6;
  font-size: .72rem;
}
.dedup-members {
  margin-top: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: #fafafa;
}
.dedup-detail-state,
.dedup-member-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 72px;
  padding: 12px;
  color: #64748b;
  font-size: .78rem;
}
.dedup-member-state { min-height: 48px; }
.dedup-detail-error { color: #b91c1c; }
.dedup-detail-error button {
  color: #7c3aed;
  text-decoration: underline;
}
.dedup-ref {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 0;
  font-size: .78rem;
}
.dedup-ref-badge {
  flex-shrink: 0;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: .68rem;
  font-weight: 700;
  margin-top: 1px;
}
.kept-badge { background: #dcfce7; color: #15803d; }
.dup-badge  { background: #fee2e2; color: #b91c1c; }
.dedup-ref-info { flex: 1; color: #64748b; line-height: 1.5; }
.dedup-doi-link {
  display: inline-block;
  padding: 0 6px;
  background: #eff6ff;
  color: #3b82f6;
  border-radius: 4px;
  font-size: .68rem;
  text-decoration: none;
}
.dedup-doi-link:hover { text-decoration: underline; }
.dedup-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 12px 14px 8px;
  color: #64748b;
  font-size: .75rem;
}
.dedup-pagination--members { padding: 8px 0 0; }
.dedup-pagination button {
  padding: 4px 10px;
  border: 1px solid #ddd6fe;
  border-radius: 6px;
  background: #fff;
  color: #7c3aed;
  cursor: pointer;
}
.dedup-pagination button:disabled {
  color: #cbd5e1;
  cursor: not-allowed;
}
</style>
