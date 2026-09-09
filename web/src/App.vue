<template>
  <SystemStatusBanner />
  <router-view />
  <div v-if="operations.isMaintenance && !auth.isAdmin" class="maintenance-overlay">
    <div class="maintenance-card">
      <i class="fas fa-screwdriver-wrench"></i>
      <h2>平台正在维护</h2>
      <p>{{ operations.system.message || '系统正在升级，请稍后再试。' }}</p>
      <p class="maintenance-hint">页面会自动检测服务恢复状态，无需反复刷新。</p>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/features/account/store'
import { useOperationsStore } from '@/features/operations/store'
import SystemStatusBanner from '@/shared/components/SystemStatusBanner.vue'

const auth = useAuthStore()
const operations = useOperationsStore()
const route = useRoute()
const tabId = sessionStorage.getItem('presence-tab-id')
  || window.crypto?.randomUUID?.()
  || `${Date.now()}-${Math.random().toString(16).slice(2)}`
sessionStorage.setItem('presence-tab-id', tabId)
let statusTimer = null
let heartbeatTimer = null

function presencePayload() {
  const projectId = route.params.projectId ? Number(route.params.projectId) : null
  return { tab_id: tabId, page: route.fullPath, project_id: projectId }
}

async function sendHeartbeat() {
  if (!auth.user || document.visibilityState !== 'visible') return
  try { await operations.heartbeat(presencePayload()) } catch { /* presence is best effort */ }
}

async function refreshSystem() {
  try { await operations.refreshSystem() } catch { /* keep the last known state */ }
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible') void sendHeartbeat()
}

function onMaintenance(event) {
  operations.applySystemState({
    mode: event.detail?.code === 'SYSTEM_DRAINING' ? 'draining' : 'maintenance',
    message: event.detail?.message || '',
  })
}

onMounted(() => {
  void refreshSystem()
  void sendHeartbeat()
  statusTimer = setInterval(refreshSystem, 30000)
  heartbeatTimer = setInterval(sendHeartbeat, 30000)
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('app:maintenance', onMaintenance)
})

watch(() => [auth.user?.id, route.fullPath], () => void sendHeartbeat())

onBeforeUnmount(() => {
  clearInterval(statusTimer)
  clearInterval(heartbeatTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('app:maintenance', onMaintenance)
})
</script>

<style>
* { box-sizing: border-box; }
.maintenance-overlay {
  position: fixed; inset: 38px 0 0; z-index: 999; background: rgba(248,250,252,.96);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.maintenance-card {
  width: min(460px, 100%); padding: 42px; text-align: center; background: #fff;
  border: 1px solid #fecaca; border-radius: 18px; box-shadow: 0 18px 50px rgba(15,23,42,.12);
}
.maintenance-card > i { font-size: 2.4rem; color: #ef4444; }
.maintenance-card h2 { margin: 18px 0 10px; color: #1e293b; }
.maintenance-card p { color: #64748b; }
.maintenance-card .maintenance-hint { font-size: .8rem; color: #94a3b8; }
</style>
