<template>
  <div v-if="operations.system.mode !== 'normal'" :class="['system-banner', operations.system.mode]">
    <i class="fas fa-triangle-exclamation"></i>
    <strong>{{ operations.system.mode === 'maintenance' ? '平台维护中' : '平台即将维护' }}</strong>
    <span>{{ operations.system.message || defaultMessage }}</span>
    <span v-if="operations.system.scheduled_at" class="system-banner-time">
      计划时间：{{ formatTime(operations.system.scheduled_at) }}
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useOperationsStore } from '@/features/operations/store'

const operations = useOperationsStore()
const defaultMessage = computed(() => operations.system.mode === 'maintenance'
  ? '升级期间暂时无法操作，请稍后再试。'
  : '已停止接收新任务，请保存当前操作。')

function formatTime(value) {
  return new Date(value).toLocaleString('zh-CN')
}
</script>

<style scoped>
.system-banner {
  min-height: 38px; padding: 8px 18px; display: flex; align-items: center;
  justify-content: center; gap: 8px; font-size: .82rem; z-index: 1000;
}
.system-banner.draining { background: #fff7ed; color: #9a3412; border-bottom: 1px solid #fed7aa; }
.system-banner.maintenance { background: #fef2f2; color: #991b1b; border-bottom: 1px solid #fecaca; }
.system-banner-time { opacity: .8; margin-left: 6px; }
</style>
