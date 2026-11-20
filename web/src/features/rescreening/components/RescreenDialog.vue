<template>
  <dialog ref="dialog" class="rescreen-dialog" :aria-labelledby="titleId" @cancel.prevent="$emit('close')" @click.self="$emit('close')">
    <header>
      <h3 :id="titleId">{{ title }}</h3>
      <button type="button" aria-label="关闭弹窗" @click="$emit('close')">×</button>
    </header>
    <div class="dialog-body"><slot /></div>
    <footer v-if="$slots.footer"><slot name="footer" /></footer>
  </dialog>
</template>
<script setup>
import { onMounted, ref, useId, watch } from 'vue'
const props = defineProps({ open: Boolean, title: { type: String, required: true } })
defineEmits(['close'])
const titleId = useId()
const dialog = ref(null)
onMounted(() => watch(() => props.open, (value) => {
  if (value && !dialog.value.open) dialog.value.showModal()
  else if (!value && dialog.value.open) dialog.value.close()
}, { immediate: true, flush: 'post' }))
</script>
<style scoped>
.rescreen-dialog {
  width: min(520px, calc(100vw - 32px));
  max-height: 80vh;
  padding: 0;
  margin: auto;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  background: #fff;
  color: #334155;
  box-shadow: 0 20px 60px #0f172a33;
}
.rescreen-dialog::backdrop { background: #0f172a66; }
.rescreen-dialog[open] { display: flex; flex-direction: column; }
header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 20px; border-bottom: 1px solid #e2e8f0; }
h3 { margin: 0; font-size: 1rem; }
header button { border: 0; background: #f1f5f9; color: #64748b; font-size: 1.3rem; border-radius: 8px; width: 30px; height: 30px; cursor: pointer; }
.dialog-body { padding: 20px; overflow: auto; line-height: 1.7; font-size: 0.88rem; }
footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid #e2e8f0; }
</style>
