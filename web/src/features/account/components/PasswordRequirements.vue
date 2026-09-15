<template>
  <div class="password-requirements" aria-live="polite">
    <span :class="{ met: lengthValid }">
      <i :class="lengthValid ? 'fas fa-check-circle' : 'far fa-circle'"></i>
      8～128 个字符
    </span>
    <span v-if="confirmPassword" :class="{ met: passwordsMatch }">
      <i :class="passwordsMatch ? 'fas fa-check-circle' : 'far fa-circle'"></i>
      两次密码一致
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  password: { type: String, default: '' },
  confirmPassword: { type: String, default: '' },
})

const lengthValid = computed(() => props.password.length >= 8 && props.password.length <= 128)
const passwordsMatch = computed(
  () => Boolean(props.confirmPassword) && props.password === props.confirmPassword,
)
</script>

<style scoped>
.password-requirements {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 0.8rem;
  color: #94a3b8;
  font-size: 0.72rem;
  margin-top: -0.35rem;
}
.password-requirements span { display: inline-flex; align-items: center; gap: 0.25rem; }
.password-requirements .met { color: #059669; }
</style>
