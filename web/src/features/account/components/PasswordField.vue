<template>
  <div class="form-group">
    <label class="form-label" :for="id">
      <i class="fas fa-lock form-icon"></i> {{ label }}
    </label>
    <div class="password-wrap">
      <input
        :id="id"
        :value="modelValue"
        :type="visible ? 'text' : 'password'"
        :required="required"
        :minlength="minlength"
        :maxlength="maxlength"
        :autocomplete="autocomplete"
        class="input-base password-input"
        :placeholder="placeholder"
        @input="$emit('update:modelValue', $event.target.value)"
      />
      <button
        type="button"
        class="visibility-button"
        :aria-label="visible ? '隐藏密码' : '显示密码'"
        @click="visible = !visible"
      >
        <i :class="visible ? 'fas fa-eye-slash' : 'fas fa-eye'"></i>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  id: { type: String, required: true },
  modelValue: { type: String, default: '' },
  label: { type: String, default: '密码' },
  placeholder: { type: String, default: '请输入密码' },
  autocomplete: { type: String, default: 'new-password' },
  minlength: { type: Number, default: undefined },
  maxlength: { type: Number, default: 128 },
  required: { type: Boolean, default: true },
})

defineEmits(['update:modelValue'])

const visible = ref(false)
</script>

<style scoped>
.form-group { display: flex; flex-direction: column; gap: 0.375rem; }
.form-label { font-size: 0.8rem; font-weight: 600; color: #475569; }
.form-icon { color: #a5b4fc; margin-right: 2px; width: 14px; }
.password-wrap { position: relative; }
.input-base {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #dbe3ef;
  border-radius: 9px;
  background: #fff;
  color: #1e293b;
  font-size: 0.875rem;
  padding: 0.65rem 0.75rem;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-base:focus {
  border-color: #818cf8;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}
.password-input { padding-right: 2.5rem; }
.visibility-button {
  position: absolute;
  top: 50%;
  right: 0.7rem;
  transform: translateY(-50%);
  border: 0;
  padding: 0.2rem;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
}
.visibility-button:hover { color: #6366f1; }
</style>
