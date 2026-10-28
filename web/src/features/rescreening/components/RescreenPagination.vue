<template>
  <div class="rs-pagination">
    <span>共 {{ page.total.toLocaleString() }} 条</span>
    <label>每页
      <select
        :value="page.page_size"
        :disabled="disabled"
        @change="$emit('change', 1, Number($event.target.value))"
      >
        <option v-for="size in [20, 50, 100]" :key="size" :value="size">
          {{ size }}
        </option>
      </select></label>
    <button
      :disabled="disabled || page.page <= 1"
      aria-label="上一页"
      @click="$emit('change', page.page - 1, page.page_size)"
    >
      ‹
    </button>
    <label>第
      <input
        :value="page.page"
        type="number"
        min="1"
        :max="page.pages"
        :disabled="disabled"
        aria-label="跳转页码"
        @focus="$event.target.select()"
        @keyup.enter="jump"
        @blur="jump"
      />
      / {{ page.pages || 1 }} 页</label>
    <button
      :disabled="disabled || page.page >= page.pages"
      aria-label="下一页"
      @click="$emit('change', page.page + 1, page.page_size)"
    >
      ›
    </button>
  </div>
</template>
<script setup>
import { pageNumber } from '../state'
const props = defineProps({
  page: { type: Object, required: true },
  disabled: Boolean,
})
const emit = defineEmits(['change'])
function jump(event) {
  const target = pageNumber(event.target.value, props.page.pages)
  event.target.value = target
  if (target !== props.page.page) emit('change', target, props.page.page_size)
}
</script>
