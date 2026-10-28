<template>
  <div class="rs-stack">
    <header class="rs-section-heading">
      <div>
        <h2>排除标准</h2>
        <p>每行一条排除标准。保存到服务器后，刷新或切换步骤不会丢失。</p>
      </div>
      <span class="rs-badge">{{ criteriaLines(text).length }} 条</span>
    </header>
    <section class="rs-card">
      <label class="rs-field-label" for="rescreen-criteria">全文复筛排除标准</label><textarea
        id="rescreen-criteria"
        v-model="text"
        rows="12"
        maxlength="12049"
        placeholder="例如：排除非人类研究。&#10;排除不符合目标人群年龄范围的研究。"
        :disabled="ws.state.info.busy"
      />
      <div class="rs-toolbar">
        <small>最多 50 条，每条 2000 字符，总长 12000
          字符。更改标准后已有审核需要重新确认。</small><button
          class="primary"
          :disabled="
            ws.state.working ||
              ws.state.info.busy ||
              !dirty ||
              !criteriaLines(text).length
          "
          @click="save"
        >
          {{ dirty ? '保存排除标准' : '已保存' }}
        </button>
      </div>
      <p v-if="dirty" class="rs-warning">
        有未保存的修改，离开此步骤前请保存。
      </p>
    </section>
  </div>
</template>
<script setup>
import { computed, inject, ref, watch, onBeforeUnmount } from 'vue'
import { criteriaLines } from '../state'
const ws = inject('rescreen')
const text = ref(
  ws.state.info.configuration.criteria.map((row) => row.text).join('\n'),
)
const saved = ref(text.value)
const baseVersion = ref(ws.state.info.configuration.version)
const dirty = computed(() => text.value !== saved.value)
watch(
  () => ws.state.info.configuration.version,
  () => {
    if (!dirty.value) {
      text.value = ws.state.info.configuration.criteria
        .map((row) => row.text)
        .join('\n')
      saved.value = text.value
      baseVersion.value = ws.state.info.configuration.version
    }
  },
)
watch(
  dirty,
  (value) => {
    ws.state.dirty = value
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  ws.state.dirty = false
})
async function save() {
  const result = await ws.action(
    () =>
      ws.api.configuration(ws.state.projectId, {
        expected_version: baseVersion.value,
        criteria: criteriaLines(text.value),
        model_ids: ws.state.info.configuration.model_ids,
      }),
    '排除标准已保存。',
  )
  if (result) {
    saved.value = text.value
    baseVersion.value = result.version
    ws.state.dirty = false
  }
}
</script>
