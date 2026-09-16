<template>
  <div class="legal-page">
    <article class="legal-card">
      <RouterLink class="back-link" to="/login?mode=register">← 返回注册</RouterLink>
      <div v-if="loading" class="legal-state">正在加载…</div>
      <div v-else-if="error" class="legal-state error">{{ error }}</div>
      <template v-else>
        <header>
          <h1>{{ document.title }}</h1>
          <p>版本 {{ document.version }} · 生效日期 {{ document.effective_date }}</p>
        </header>
        <pre>{{ document.content }}</pre>
      </template>
    </article>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fetchLegalDocument } from '@/features/account/api'

const route = useRoute()
const document = ref({})
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    document.value = await fetchLegalDocument(route.meta.legalType)
  } catch (e) {
    error.value = e?.response?.data?.error || '协议加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => route.meta.legalType, load)
</script>

<style scoped>
.legal-page { min-height: 100vh; padding: 2rem 1rem; background: #f5f3ff; }
.legal-card { max-width: 900px; margin: 0 auto; padding: 2.25rem; border-radius: 16px; background: #fff; box-shadow: 0 10px 35px rgba(49,46,129,.1); }
.back-link { color: #6366f1; text-decoration: none; }
header { margin: 1.5rem 0; padding-bottom: 1rem; border-bottom: 1px solid #e2e8f0; }
h1 { margin: 0 0 .5rem; color: #1e1b4b; }
header p { margin: 0; color: #64748b; }
pre { margin: 0; color: #334155; font: 15px/1.85 system-ui, sans-serif; white-space: pre-wrap; overflow-wrap: anywhere; }
.legal-state { padding: 4rem; text-align: center; color: #64748b; }
.legal-state.error { color: #be123c; }
@media (max-width: 640px) { .legal-card { padding: 1.25rem; } }
</style>
