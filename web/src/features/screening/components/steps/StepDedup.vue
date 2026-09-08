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
          @click="handleDeduplication"
          :disabled="s.isDeduplicating"
          class="dedup-btn"
          :class="s.dedupCompleted ? 'dedup-btn--redo' : 'dedup-btn--start'"
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

      <!-- 重复文献详细列表 -->
      <div v-if="s.dedupStats.duplicate_details?.length > 0" class="mt-4">
        <div class="dedup-detail-header">
          <span class="font-semibold text-gray-700 text-sm">
            <i class="fas fa-list-ul mr-1.5 text-purple-400"></i>
            重复文献详情（共 {{ s.dedupStats.duplicate_groups || 0 }} 组）
          </span>
          <button
            @click="s.showDuplicateDetails = !s.showDuplicateDetails"
            class="dedup-detail-toggle"
          >
            <i :class="s.showDuplicateDetails ? 'fas fa-chevron-up' : 'fas fa-chevron-down'"></i>
            {{ s.showDuplicateDetails ? '收起' : '展开' }}
          </button>
        </div>

        <div v-show="s.showDuplicateDetails" class="dedup-detail-list">
          <div
            v-for="(dup, idx) in s.dedupStats.duplicate_details"
            :key="idx"
            class="dedup-detail-item"
          >
            <div class="dedup-detail-title">{{ idx + 1 }}. {{ dup.title || '(无标题)' }}</div>

            <!-- 保留的 -->
            <div class="dedup-ref kept">
              <span class="dedup-ref-badge kept-badge">保留</span>
              <div class="dedup-ref-info">
                <span class="font-medium text-gray-700">{{ dup.kept.source_file || dup.kept.filename }}</span>
                <span v-if="dup.kept.source_position" class="text-blue-500 ml-1">#{{ dup.kept.source_position }}</span>
                <span v-if="dup.kept.year" class="text-gray-400 ml-2">{{ dup.kept.year }}</span>
                <span v-if="dup.kept.journal" class="text-gray-400 ml-2">· {{ dup.kept.journal }}</span>
                <a v-if="dup.kept.doi" :href="'https://doi.org/' + dup.kept.doi" target="_blank" class="dedup-doi-link ml-2">
                  DOI
                </a>
              </div>
            </div>

            <!-- 重复的 -->
            <div
              v-for="(dup_item, di) in dup.duplicates"
              :key="di"
              class="dedup-ref dup"
            >
              <span class="dedup-ref-badge dup-badge">重复</span>
              <div class="dedup-ref-info">
                <span class="font-medium text-gray-600">{{ dup_item.source_file || dup_item.filename }}</span>
                <span v-if="dup_item.source_position" class="text-blue-500 ml-1">#{{ dup_item.source_position }}</span>
                <span v-if="dup_item.year" class="text-gray-400 ml-2">{{ dup_item.year }}</span>
                <span v-if="dup_item.journal" class="text-gray-400 ml-2">· {{ dup_item.journal }}</span>
                <a v-if="dup_item.doi" :href="'https://doi.org/' + dup_item.doi" target="_blank" class="dedup-doi-link ml-2">
                  DOI
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'
import * as workflowApi from '@/shared/api/workflow'
import { findLatestDedupTask, getDedupTaskUiState } from '@/features/screening/dedupTaskState'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()
let dedupPollGeneration = 0
let dedupPollTimer = null
let componentActive = true

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
  s.dedupStats = (dedupStep.metadata?.total_files !== undefined) ? dedupStep.metadata : null
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

.dedup-detail-list {
  background: #fff;
  border: 1px solid #ede9fe;
  border-radius: 10px;
  max-height: 24rem;
  overflow-y: auto;
  padding: 4px 0;
}
.dedup-detail-item {
  padding: 10px 14px;
  border-bottom: 1px solid #f8fafc;
}
.dedup-detail-item:last-child { border-bottom: none; }
.dedup-detail-title {
  font-size: .82rem;
  font-weight: 600;
  color: #334155;
  margin-bottom: 6px;
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
</style>
