<template>
  <div class="operations-page">
    <AppHeader />
    <main class="operations-main">
      <div class="title-row">
        <div><h1>系统运维</h1><p>查看在线用户和后台任务，并切换平台运行状态；此页不会停止服务进程。</p></div>
        <button class="btn-secondary" :disabled="operations.loading" @click="refresh(true)">刷新</button>
      </div>

      <div v-if="operations.error" class="error-box">{{ operations.error }}</div>

      <section class="state-card card">
        <div>
          <span :class="['state-pill', operations.system.mode]">{{ modeLabel }}</span>
          <strong>{{ operations.system.message || '暂无维护通知' }}</strong>
        </div>
        <div class="state-form">
          <input v-model="message" class="input-base" placeholder="维护通知，例如：20:30 开始升级" />
          <input v-model="scheduledAt" type="datetime-local" class="input-base date-input" />
          <button class="btn-warning" @click="setMode('draining')">进入排空</button>
          <button class="btn-danger" @click="setMode('maintenance')">进入维护</button>
          <button class="btn-success" @click="setMode('normal')">恢复开放</button>
        </div>
      </section>

      <section class="metric-grid" v-if="snapshot">
        <div class="metric card"><span>当前在线用户</span><strong>{{ snapshot.presence.online_users }}</strong></div>
        <div class="metric card"><span>活跃标签页</span><strong>{{ snapshot.presence.active_tabs }}</strong></div>
        <div class="metric card"><span>最近活跃用户</span><strong>{{ snapshot.presence.recent_users }}</strong></div>
        <div class="metric card"><span>未过期会话</span><strong>{{ snapshot.sessions.unexpired }}</strong></div>
        <div class="metric card"><span>活动任务</span><strong>{{ snapshot.active_task_count }}</strong></div>
        <div class="metric card"><span>Celery Active</span><strong>{{ snapshot.celery.active ?? '-' }}</strong></div>
      </section>

      <section v-if="snapshot" :class="['safety card', safetyClass]">
        <strong>{{ safetyLabel }}</strong>
        <span>{{ safetyHint }}</span>
        <div class="task-actions">
          <button class="btn-warning" :disabled="operations.system.mode === 'normal'" @click="pauseTasks">暂停长任务</button>
          <button class="btn-secondary" @click="resumeTasks">恢复维护任务</button>
        </div>
      </section>

      <section class="table-card card" v-if="snapshot">
        <h2>在线用户</h2>
        <table><thead><tr><th>用户</th><th>页面</th><th>项目</th><th>标签页</th><th>最后心跳</th></tr></thead>
          <tbody><tr v-for="user in snapshot.presence.users" :key="user.user_id">
            <td>{{ user.username }}</td><td>{{ user.page || '-' }}</td><td>{{ user.project_id || '-' }}</td>
            <td>{{ user.tabs }}</td><td>{{ formatTime(user.last_seen) }}</td>
          </tr><tr v-if="!snapshot.presence.users.length"><td colspan="5">暂无在线用户</td></tr></tbody>
        </table>
      </section>

      <section class="table-card card" v-if="snapshot">
        <h2>活动任务 <small v-if="snapshot.tasks_truncated">仅展示最早 {{ snapshot.task_list_limit }} 条</small></h2>
        <table><thead><tr><th>ID</th><th>用户</th><th>项目</th><th>类型</th><th>状态</th><th>进度</th></tr></thead>
          <tbody><tr v-for="task in snapshot.tasks" :key="task.id">
            <td>{{ task.id }}</td><td>{{ task.username || '-' }}</td><td>{{ task.project }}</td>
            <td>{{ task.type }}</td><td>{{ task.status }}</td><td>{{ task.progress }}%</td>
          </tr><tr v-if="!snapshot.tasks.length"><td colspan="6">暂无活动任务</td></tr></tbody>
        </table>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useOperationsStore } from '@/features/operations/store'
import * as operationsApi from '@/features/operations/api'
import AppHeader from '@/shared/components/AppHeader.vue'

const operations = useOperationsStore()
const snapshot = computed(() => operations.snapshot)
const message = ref('')
const scheduledAt = ref('')
let timer = null
const modeLabel = computed(() => ({ normal: '正常运行', draining: '正在排空', maintenance: '维护中' }[operations.system.mode]))
const safetyClass = computed(() => snapshot.value?.safe_to_stop == null
  ? 'pending'
  : (snapshot.value.safe_to_stop ? 'safe' : 'busy'))
const safetyLabel = computed(() => snapshot.value?.safe_to_stop == null
  ? '安全状态待确认'
  : (snapshot.value.safe_to_stop ? '当前可以安全停机' : '当前不建议停机'))
const safetyHint = computed(() => snapshot.value?.safe_to_stop == null
  ? '正在读取安全状态。'
  : '普通在线用户和活动业务任务都清空后即可开始停机；服务进程由 stop.sh 负责关闭。')

async function refresh(inspectCelery = false) {
  try { await operations.refreshSnapshot(inspectCelery) } catch { /* rendered by store */ }
}
async function setMode(mode) {
  if (mode === 'maintenance' && !confirm('确定进入维护模式吗？普通用户的业务请求将被拒绝。')) return
  await operations.changeState({
    mode,
    message: mode === 'normal' ? '' : message.value,
    scheduled_at: scheduledAt.value ? new Date(scheduledAt.value).toISOString() : null,
  })
}
async function pauseTasks() {
  if (!confirm('将协作式暂停正在运行的 AI 初筛和质量评价任务，是否继续？')) return
  const result = await operationsApi.pauseMaintenanceTasks()
  alert(`已请求暂停 ${result.paused.length} 个任务`)
  await refresh(true)
}
async function resumeTasks() {
  const result = await operationsApi.resumeMaintenanceTasks()
  alert(`已恢复 ${result.resumed.length} 个任务`)
  await refresh(true)
}
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN') : '-' }

onMounted(async () => {
  await refresh(true)
  message.value = operations.system.message || ''
  timer = setInterval(() => refresh(false), 15000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.operations-page { min-height: 100vh; background: #f8fafc; }
.operations-main { width: min(1200px, calc(100% - 40px)); margin: 0 auto; padding: 26px 0 50px; }
.title-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.title-row h1 { margin: 0; font-size: 1.3rem; }.title-row p { margin: 5px 0 0; color: #64748b; font-size: .85rem; }
.state-card { padding: 18px; margin-bottom: 16px; }.state-card > div:first-child { display: flex; gap: 10px; align-items: center; }
.state-pill { border-radius: 999px; padding: 4px 10px; font-size: .75rem; }.state-pill.normal { background:#dcfce7;color:#166534; }
.state-pill.draining { background:#ffedd5;color:#9a3412; }.state-pill.maintenance { background:#fee2e2;color:#991b1b; }
.state-form { display: flex; gap: 8px; margin-top: 15px; flex-wrap: wrap; }.state-form > input:first-child { flex: 1; min-width: 260px; }
.date-input { width: 205px; }.metric-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 16px; }
.metric { padding: 15px; display: flex; flex-direction: column; gap: 6px; }.metric span { color:#64748b;font-size:.75rem; }.metric strong { font-size:1.4rem; }
.safety { padding: 16px; display:flex;align-items:center;gap:12px;margin-bottom:16px; }.safety.safe { border-color:#86efac;background:#f0fdf4; }
.safety.busy { border-color:#fdba74;background:#fff7ed; }.safety span { color:#64748b;font-size:.8rem; }.task-actions { margin-left:auto;display:flex;gap:8px; }
.safety.pending { border-color:#cbd5e1;background:#f8fafc; }
.table-card { padding: 18px; margin-bottom: 16px; overflow:auto; }.table-card h2 { margin:0 0 12px;font-size:1rem; }
.table-card h2 small { color:#94a3b8;font-size:.72rem;font-weight:400;margin-left:8px; }
table { width:100%;border-collapse:collapse;font-size:.8rem; }th,td { padding:9px;border-bottom:1px solid #e2e8f0;text-align:left; }th { color:#64748b; }
.btn-warning,.btn-danger,.btn-success { border:0;border-radius:8px;padding:8px 12px;color:white;cursor:pointer;font-weight:600; }
.btn-warning { background:#d97706; }.btn-danger { background:#dc2626; }.btn-success { background:#16a34a; }
.error-box { background:#fef2f2;color:#991b1b;padding:10px;border-radius:8px;margin-bottom:12px; }
@media (max-width: 900px) { .metric-grid { grid-template-columns: repeat(2,1fr); }.safety { align-items:flex-start;flex-direction:column; }.task-actions { margin-left:0; } }
</style>
