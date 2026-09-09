import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as operationsApi from './api'

export const useOperationsStore = defineStore('operations', () => {
  const system = ref({ mode: 'normal', message: '', scheduled_at: null })
  const snapshot = ref(null)
  const loading = ref(false)
  const error = ref('')

  const isDraining = computed(() => system.value.mode === 'draining')
  const isMaintenance = computed(() => system.value.mode === 'maintenance')

  function applySystemState(value) {
    if (!value?.mode) return
    system.value = { ...system.value, ...value }
    window.__SYSTEM_MAINTENANCE__ = value.mode === 'maintenance'
  }

  async function refreshSystem() {
    const result = await operationsApi.fetchSystemStatus()
    applySystemState(result)
    return result
  }

  async function heartbeat(payload) {
    const result = await operationsApi.sendHeartbeat(payload)
    if (result.state) applySystemState(result.state)
  }

  async function refreshSnapshot(inspectCelery = true) {
    loading.value = true
    error.value = ''
    try {
      const result = await operationsApi.fetchOperationsStatus(inspectCelery)
      snapshot.value = result
      applySystemState(result.state)
      return result
    } catch (err) {
      error.value = err.response?.data?.error || err.message || '读取运维状态失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function changeState(payload) {
    const result = await operationsApi.changeSystemState(payload)
    applySystemState(result)
    await refreshSnapshot(false)
    return result
  }

  return {
    system, snapshot, loading, error, isDraining, isMaintenance,
    applySystemState, refreshSystem, heartbeat, refreshSnapshot, changeState,
  }
})
