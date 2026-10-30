<template>
  <div class="rs-pdf-viewer">
    <div v-if="preview.state.loading" class="rs-pdf-empty">
      正在安全加载 PDF…
    </div>
    <div v-else-if="preview.state.error" class="rs-pdf-empty">
      <p>{{ preview.state.error }}</p>
      <button @click="preview.load(url)">重试加载</button><a :href="safePdfUrl(url, page)" target="_blank" rel="noopener">独立打开 PDF</a>
    </div>
    <iframe
      v-else-if="preview.state.url"
      :key="`${preview.state.url}:${page}`"
      :src="`${preview.state.url}#page=${Math.max(1, page)}&view=FitH`"
      title="复筛全文 PDF 阅读器"
    />
  </div>
</template>
<script setup>
import { onMounted, onBeforeUnmount, watch } from 'vue'
import { createPdfPreview } from '../usePdfPreview'
import { safePdfUrl } from '../state'
const props = defineProps({
  url: { type: String, required: true },
  page: { type: Number, default: 1 },
})
const preview = createPdfPreview()
onMounted(() => {
  watch(
    () => props.url,
    (value) => preview.load(safePdfUrl(value).split('#')[0]),
    { immediate: true },
  )
})
onBeforeUnmount(() => preview.dispose())
</script>
<style scoped>
.rs-pdf-viewer {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.rs-pdf-viewer iframe {
  width: 100%;
  height: 100%;
  border: 0;
}
.rs-pdf-viewer .rs-pdf-empty {
  min-height: 140px;
  padding: 20px;
}
</style>
