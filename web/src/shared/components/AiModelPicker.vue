<template>
  <div class="ai-provider-list">
    <div
      v-for="provider in providers"
      :key="provider.id"
      class="ai-provider-group"
    >
      <!-- 厂家标题行 -->
      <div class="ai-provider-header">
        <span class="ai-provider-logo">
          <span v-if="provider.logo === 'deepseek'">🤖</span>
          <span v-else-if="provider.logo === 'doubao'">🫘</span>
          <span v-else-if="provider.logo === 'qwen'">🌙</span>
          <span v-else>🧠</span>
        </span>
        <span class="ai-provider-name">{{ provider.name }}</span>
        <span v-if="!provider.configured" class="ai-provider-unconfigured"
          >未配置</span
        >
      </div>
      <!-- 子模型列表 -->
      <div class="ai-submodel-list">
        <button
          v-for="sm in provider.sub_models"
          :key="sm.id"
          :disabled="disabled || !sm.configured"
          :aria-pressed="isSelected(sm.id)"
          type="button"
          @click="$emit('toggle', sm)"
          :class="[
            'ai-submodel-btn',
            isSelected(sm.id) ? 'ai-submodel-btn-active' : '',
          ]"
          :title="sm.description"
        >
          <span class="ai-submodel-name">{{ sm.name }}</span>
          <span class="ai-submodel-desc">{{ sm.description }}</span>
          <span
            v-if="multiplierFor(sm.id) != null"
            class="ai-submodel-multiplier"
          >
            约 {{ multiplierFor(sm.id) }}×
          </span>
          <i
            v-if="isSelected(sm.id)"
            class="fas fa-check ai-submodel-check"
          ></i>
        </button>
      </div>
    </div>
  </div>
</template>
<script setup>
defineProps({
  providers: { type: Array, required: true },
  isSelected: { type: Function, required: true },
  multiplierFor: { type: Function, required: true },
  disabled: Boolean,
})
defineEmits(['toggle'])
</script>
<style scoped>
.ai-provider-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ai-provider-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.ai-provider-logo {
  font-size: 1rem;
  line-height: 1;
}
.ai-provider-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
}
.ai-provider-unconfigured {
  font-size: 0.68rem;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 2px;
}
.ai-submodel-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-left: 20px;
}
.ai-submodel-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1.5px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 0.78rem;
  position: relative;
  max-width: 100%;
  flex-wrap: wrap;
  overflow-wrap: anywhere;
}
.ai-submodel-btn:hover:not(:disabled) {
  border-color: #a5b4fc;
  background: #f5f3ff;
}
.ai-submodel-btn-active {
  border-color: #6366f1;
  background: #eef2ff;
}
.ai-submodel-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ai-submodel-name {
  font-weight: 500;
  color: #334155;
}
.ai-submodel-desc {
  font-size: 0.68rem;
  color: #94a3b8;
}
.ai-submodel-multiplier {
  flex-shrink: 0;
  color: #7c3aed;
  background: #f3e8ff;
  border: 1px solid #e9d5ff;
  border-radius: 999px;
  padding: 0.08rem 0.4rem;
  font-size: 0.65rem;
  font-weight: 700;
}
.ai-submodel-btn-active .ai-submodel-name {
  color: #4338ca;
}
.ai-submodel-btn-active .ai-submodel-desc {
  color: #818cf8;
}
.ai-submodel-check {
  font-size: 0.62rem;
  color: #6366f1;
  margin-left: 2px;
}
</style>
