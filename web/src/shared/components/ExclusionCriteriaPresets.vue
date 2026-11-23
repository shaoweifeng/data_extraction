<template>
  <!-- 常用排除标准快捷勾选 -->
  <div class="step-list-box mb-4" style="background:#eff6ff;border-color:#bfdbfe;padding:14px 16px">
    <p class="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-3">
      <i class="fas fa-bolt mr-1"></i>常用排除标准（勾选后自动添加）
    </p>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
      <label v-for="preset in presets" :key="preset" class="flex items-start gap-2 cursor-pointer group">
        <input
          type="checkbox"
          :checked="modelValue.includes(preset)"
          :disabled="disabled"
          class="mt-0.5 w-4 h-4 rounded accent-green-600 cursor-pointer flex-shrink-0"
          @change="$emit('toggle', preset)"
        />
        <span class="text-sm text-gray-700 group-hover:text-gray-900 leading-snug">{{ preset }}</span>
      </label>
    </div>
  </div>
</template>
<script setup>
defineProps({ modelValue: { type: Array, default: () => [] }, disabled: Boolean })
defineEmits(['toggle'])
const presets = [
  '无法获取摘要的文献',
  '非中、英文发表的文献',
  '会议摘要、图书章节及学位论文',
  '研究类型为非原始研究（如综述研究等）',
  '未以人类为研究对象（如动物实验、细胞实验）',
]
</script>
