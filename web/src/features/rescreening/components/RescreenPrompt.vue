<template>
  <details class="rs-card rs-prompt">
    <summary>Prompt 设置 <small>研究者 / 管理员</small></summary>
    <p>补充要求会与固定证据协议共同发送，协议约束与证据校验不会被关闭。</p>
    <textarea
      v-model="text"
      rows="5"
      maxlength="5000"
      placeholder="可选：为当前项目补充关注点或判断要求"
      :disabled="ws.state.info.busy"
    />
    <div class="rs-toolbar">
      <small>{{ text.length }} / 5000 字符</small><button
        :disabled="ws.state.working || ws.state.info.busy || !dirty"
        @click="save"
      >
        保存补充提示
      </button>
    </div>
    <details>
      <summary>查看固定证据协议</summary>
      <pre>{{ ws.state.info.configuration.protocol_prompt }}</pre>
    </details>
  </details>
</template>
<script setup>
import { inject, ref, computed, watch, onBeforeUnmount } from 'vue'
const ws = inject('rescreen')
const text = ref(ws.state.info.configuration.custom_prompt || '')
const original = ref(text.value)
const baseVersion = ref(ws.state.info.configuration.version)
const dirty = computed(() => text.value !== original.value)
watch(
  () => ws.state.info.configuration.version,
  () => {
    if (!dirty.value) {
      text.value = ws.state.info.configuration.custom_prompt || ''
      original.value = text.value
      baseVersion.value = ws.state.info.configuration.version
    }
  },
)
watch(dirty, (value) => {
  ws.state.promptDirty = value
})
onBeforeUnmount(() => {
  ws.state.promptDirty = false
})
async function save() {
  const config = ws.state.info.configuration
  const result = await ws.action(
    () =>
      ws.api.configuration(ws.state.projectId, {
        expected_version: baseVersion.value,
        criteria: config.criteria.map((row) => row.text),
        model_ids: config.model_ids,
        custom_prompt: text.value,
      }),
    '补充提示已保存。',
  )
  if (result) {
    original.value = text.value
    baseVersion.value = result.version
    ws.state.promptDirty = false
  }
}
</script>
