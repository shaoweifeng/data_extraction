<template>
  <div class="rs-workspace">
    <div v-if="ws.state.loading" class="rs-loading">
      <i class="fas fa-spinner fa-spin"></i> 正在加载复筛工作区…
    </div>
    <template v-else-if="ws.state.info">
      <nav class="rs-stepbar" aria-label="全文复筛步骤">
        <button
          v-for="(name, index) in STEPS"
          :key="name"
          :disabled="!ws.state.info.steps[index].enabled"
          :class="{
            active: ws.state.step === index + 1,
            done: ws.state.info.steps[index].completed,
          }"
          :aria-current="ws.state.step === index + 1 ? 'step' : undefined"
          @click="navigate(index + 1)"
        >
          <span>{{
            ws.state.info.steps[index].completed ? '✓' : index + 1
          }}</span>{{ name }}
        </button>
      </nav>
      <div class="rs-workspace-body">
        <div class="rs-overview">
          <span><b>{{ ws.state.info.counts.total }}</b> 篇文献</span><span><b>{{ ws.state.info.counts.ready }}</b> 篇全文就绪</span><span><b>{{ ws.state.info.counts.finalized }}</b> 篇最终确认</span><span
            v-if="ws.state.info.counts.needs_reconfirmation"
            class="rs-warning"
          >{{ ws.state.info.counts.needs_reconfirmation }} 篇需重新确认</span><span v-if="ws.state.working" role="status"><i class="fas fa-spinner fa-spin"></i> 正在处理…</span><button
            :disabled="ws.state.working"
            @click="ws.read(() => ws.refresh())"
          >
            <i class="fas fa-sync-alt"></i> 刷新
          </button>
        </div>
        <div v-if="ws.state.error" class="rs-alert danger" role="alert">
          {{ ws.state.error
          }}<button aria-label="关闭错误提示" @click="ws.state.error = ''">
            ×
          </button>
        </div>
        <div v-if="ws.state.notice" class="rs-alert success" role="status">
          {{ ws.state.notice
          }}<button aria-label="关闭提示" @click="ws.state.notice = ''">
            ×
          </button>
        </div>
        <div v-if="ws.state.info.busy" class="rs-alert">
          后台有复筛任务正在处理，状态会自动更新。审核和输入变更暂时锁定，但可以查看文献与已有结果。
        </div>
        <component
          :is="components[ws.state.step - 1]"
          :key="ws.state.step"
          v-bind="ws.state.step === 4 ? { canPrompt } : {}"
        />
      </div>
      <footer class="rs-footer">
        <button
          :disabled="ws.state.step === 1"
          @click="navigate(ws.state.step - 1)"
        >
          ‹ 上一步
        </button><span>步骤状态来自服务器 · {{ ws.state.step }} / 6</span><button
          class="primary"
          :disabled="
            ws.state.step !== 6 && !ws.state.info.steps[ws.state.step]?.enabled
          "
          @click="ws.state.step === 6 ? goQuality() : navigate(ws.state.step + 1)"
        >
          {{ ws.state.step === 6 ? '前往质量评价 ›' : '下一步 ›' }}
        </button>
      </footer>
    </template>
    <div v-else class="rs-empty">
      <p>{{ ws.state.error || '无法加载复筛工作区。' }}</p>
      <button @click="ws.initialize(projectId)">重新加载</button>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, provide, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { useAuthStore } from '@/features/account/store'
import { createRescreenWorkspace } from '../useWorkspace'
import { STEPS, stepNumber } from '../state'
import RescreenUpload from './RescreenUpload.vue'
import RescreenFulltext from './RescreenFulltext.vue'
import RescreenCriteria from './RescreenCriteria.vue'
import RescreenAI from './RescreenAI.vue'
import RescreenReview from './RescreenReview.vue'
import RescreenExport from './RescreenExport.vue'
import '../workspace.css'
const props = defineProps({ projectId: { type: Number, required: true } })
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ws = createRescreenWorkspace()
provide('rescreen', ws)
const components = [
  RescreenUpload,
  RescreenFulltext,
  RescreenCriteria,
  RescreenAI,
  RescreenReview,
  RescreenExport,
]
const canPrompt = computed(
  () => auth.canConfigureScreeningPrompt && ws.state.info?.capabilities.prompt,
)
const dirty = () =>
  ws.state.dirty ||
  ws.state.reviewDirty ||
  ws.state.promptDirty ||
  ws.state.modelDirty
function confirmLeave() {
  return !dirty() || window.confirm('当前存在未保存修改，确定离开此步骤？')
}
async function navigate(index) {
  if (!ws.state.info.steps.find((step) => step.index === index)?.enabled) return
  await router.replace({
    query: { ...route.query, stage: 'SCREEN_2', rescreen_step: index },
  })
}
watch(
  () => props.projectId,
  (id) => ws.initialize(id, route.query.rescreen_step),
  { immediate: true },
)
watch(
  () => route.query.rescreen_step,
  async (value) => {
    if (!ws.state.info) return
    const next = stepNumber(value, ws.state.info)
    if (ws.state.step === next) return
    ws.state.step = next
    ws.state.selected = []
    ws.state.detail = null
    ws.state.aiDetail = null
    ws.state.filters = { q: '', status: next === 4 ? 'ready' : '' }
    await ws.read(() => ws.loadReferences(1))
  },
)
onBeforeRouteLeave(() => confirmLeave())
function goQuality() {
  return router.push({ query: { ...route.query, stage: 'QUALITY', rescreen_step: undefined } })
}
onBeforeRouteUpdate((to, from) => (to.query.rescreen_step !== from.query.rescreen_step || to.query.stage !== from.query.stage) ? confirmLeave() : true)
function beforeUnload(event) { if (dirty()) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => { window.removeEventListener('beforeunload', beforeUnload); ws.dispose() })
</script>
