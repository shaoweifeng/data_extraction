<template>
  <Teleport to="body">
    <Transition name="feedback-fade">
      <div v-if="open" class="feedback-mask" role="presentation" @click.self="requestClose">
        <section
          ref="dialogRef"
          class="feedback-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="feedback-title"
          @keydown.esc="requestClose"
          @keydown.tab="trapFocus"
        >
          <header class="feedback-head">
            <div>
              <h2 id="feedback-title">使用反馈</h2>
              <p>遇到问题或有改进建议，都可以告诉我们</p>
            </div>
            <button class="feedback-close" type="button" aria-label="关闭" @click="requestClose">
              <i class="fas fa-times"></i>
            </button>
          </header>

          <div v-if="successCode" class="feedback-success" role="status">
            <i class="fas fa-circle-check"></i>
            <h3>反馈已收到</h3>
            <p>反馈编号：{{ successCode }}</p>
            <button type="button" class="feedback-primary" @click="closeAfterSuccess">完成</button>
          </div>

          <form v-else class="feedback-form" @submit.prevent="handleSubmit">
            <fieldset class="feedback-types">
              <legend>反馈类型</legend>
              <label :class="{ active: category === 'problem' }">
                <input v-model="category" type="radio" value="problem" @change="markChanged">
                <i class="fas fa-bug"></i> 遇到问题
              </label>
              <label :class="{ active: category === 'suggestion' }">
                <input v-model="category" type="radio" value="suggestion" @change="markChanged">
                <i class="fas fa-lightbulb"></i> 改进建议
              </label>
            </fieldset>

            <label class="feedback-field">
              <span>详细描述 <em>必填</em></span>
              <textarea
                ref="textareaRef"
                v-model="content"
                rows="6"
                maxlength="2000"
                placeholder="请描述你遇到的情况、期望的结果，或希望我们改进的地方…"
                @input="markChanged"
              ></textarea>
              <small :class="{ limit: content.length >= 1900 }">{{ content.length }} / 2000</small>
            </label>

            <div class="feedback-field">
              <span>相关图片 <b>选填，最多 3 张</b></span>
              <input
                ref="fileInputRef"
                class="feedback-file-input"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                @change="onFileInput"
              >
              <button
                v-if="images.length < 3"
                class="feedback-upload"
                type="button"
                @click="fileInputRef?.click()"
                @dragover.prevent
                @drop.prevent="onDrop"
              >
                <i class="fas fa-image"></i>
                <span>选择或拖入图片</span>
                <small>JPEG、PNG、WebP，单张不超过 5 MiB</small>
              </button>
              <div v-if="images.length" class="feedback-previews">
                <figure v-for="item in images" :key="item.id">
                  <img :src="item.preview" :alt="item.file.name">
                  <button type="button" :aria-label="`删除 ${item.file.name}`" @click="removeImage(item.id)">
                    <i class="fas fa-times"></i>
                  </button>
                </figure>
              </div>
            </div>

            <p v-if="errorMessage" class="feedback-error" role="alert">{{ errorMessage }}</p>

            <footer class="feedback-actions">
              <span>将自动附带当前页面和浏览器信息</span>
              <button class="feedback-secondary" type="button" :disabled="submitting" @click="requestClose">取消</button>
              <button class="feedback-primary" type="submit" :disabled="submitting">
                <i v-if="submitting" class="fas fa-spinner fa-spin"></i>
                {{ submitting ? '提交中…' : '提交反馈' }}
              </button>
            </footer>
          </form>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/features/account/store'
import { submitFeedback } from './api'
import { validateFeedbackContent, validateFeedbackFiles } from './validation'

const auth = useAuthStore()
const route = useRoute()
const visible = computed(() => !!auth.user && !auth.isAdmin && route.name !== 'Login')
const open = ref(false)
const category = ref('problem')
const content = ref('')
const images = ref([])
const submitting = ref(false)
const errorMessage = ref('')
const successCode = ref('')
const requestId = ref('')
const dialogRef = ref(null)
const textareaRef = ref(null)
const fileInputRef = ref(null)

function newRequestId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
    const random = Math.floor(Math.random() * 16)
    const value = character === 'x' ? random : (random & 0x3) | 0x8
    return value.toString(16)
  })
}

function markChanged() {
  requestId.value = ''
  errorMessage.value = ''
}

function openDialog() {
  if (!visible.value) return
  open.value = true
  errorMessage.value = ''
  void nextTick(() => textareaRef.value?.focus())
}

function revokePreviews() {
  images.value.forEach(item => URL.revokeObjectURL(item.preview))
}

function resetForm() {
  revokePreviews()
  category.value = 'problem'
  content.value = ''
  images.value = []
  requestId.value = ''
  errorMessage.value = ''
  successCode.value = ''
}

function requestClose() {
  if (submitting.value) return
  if (!successCode.value && (content.value.trim() || images.value.length)) {
    if (!window.confirm('尚未提交，确定关闭并清空内容吗？')) return
  }
  open.value = false
  resetForm()
}

function closeAfterSuccess() {
  open.value = false
  resetForm()
}

function trapFocus(event) {
  const focusable = dialogRef.value?.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )
  if (!focusable?.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function addFiles(fileList) {
  const files = Array.from(fileList || [])
  const validationError = validateFeedbackFiles(images.value, files)
  if (validationError) {
    errorMessage.value = validationError
    return
  }
  images.value.push(...files.map(file => ({
    id: newRequestId(),
    file,
    preview: URL.createObjectURL(file),
  })))
  markChanged()
}

function onFileInput(event) {
  addFiles(event.target.files)
  event.target.value = ''
}

function onDrop(event) {
  addFiles(event.dataTransfer?.files)
}

function removeImage(id) {
  const item = images.value.find(image => image.id === id)
  if (item) URL.revokeObjectURL(item.preview)
  images.value = images.value.filter(image => image.id !== id)
  markChanged()
}

function feedbackError(error) {
  const code = error.response?.data?.code
  if (code === 'FEEDBACK_DAILY_LIMIT') return '今天的反馈次数已用完，请明天再试'
  if (code === 'FEEDBACK_BURST_LIMIT') return '提交得有点频繁，请一分钟后再试'
  return error.response?.data?.error || '提交失败，请检查网络后重试'
}

async function handleSubmit() {
  errorMessage.value = validateFeedbackContent(content.value)
  if (errorMessage.value) return
  if (!requestId.value) requestId.value = newRequestId()
  submitting.value = true
  try {
    const response = await submitFeedback({
      category: category.value,
      content: content.value.trim(),
      projectId: route.params.projectId ? Number(route.params.projectId) : null,
      pagePath: route.path,
      routeName: String(route.name || ''),
      context: {
        viewport: `${window.innerWidth}x${window.innerHeight}`,
        browser: navigator.userAgent,
        platform: navigator.platform || '',
        frontend_version: import.meta.env.VITE_APP_VERSION || '',
      },
    }, images.value, requestId.value)
    successCode.value = response.data.display_code
  } catch (error) {
    errorMessage.value = feedbackError(error)
  } finally {
    submitting.value = false
  }
}

onMounted(() => window.addEventListener('app:feedback-open', openDialog))
onBeforeUnmount(() => {
  window.removeEventListener('app:feedback-open', openDialog)
  revokePreviews()
})
watch(visible, value => {
  if (!value && open.value) {
    open.value = false
    resetForm()
  }
})
</script>

<style scoped>
.feedback-mask { position: fixed; inset: 0; z-index: 2000; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(15,23,42,.45); backdrop-filter: blur(2px); }
.feedback-dialog { width: min(440px, 100%); max-height: calc(100vh - 40px); overflow: auto; background: #fff; border-radius: 16px; box-shadow: 0 24px 70px rgba(15,23,42,.22); }
.feedback-head { display: flex; justify-content: space-between; gap: 20px; padding: 20px 22px 16px; border-bottom: 1px solid #eef2f7; }
.feedback-head h2 { margin: 0; color: #172033; font-size: 18px; }
.feedback-head p { margin: 5px 0 0; color: #7b879b; font-size: 12px; }
.feedback-close { align-self: flex-start; width: 30px; height: 30px; border: 0; border-radius: 8px; color: #94a3b8; background: transparent; cursor: pointer; }
.feedback-close:hover { color: #475569; background: #f1f5f9; }
.feedback-form { display: flex; flex-direction: column; gap: 16px; padding: 18px 22px 20px; }
.feedback-types { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin: 0; padding: 0; border: 0; }
.feedback-types legend, .feedback-field > span { display: block; margin-bottom: 8px; color: #334155; font-size: 13px; font-weight: 600; }
.feedback-types label { padding: 10px 12px; border: 1px solid #dbe3ee; border-radius: 9px; color: #64748b; cursor: pointer; font-size: 13px; text-align: center; }
.feedback-types label.active { border-color: #93b4fd; color: #1d4ed8; background: #eff6ff; }
.feedback-types input { position: absolute; opacity: 0; pointer-events: none; }
.feedback-types i { margin-right: 5px; }
.feedback-field em { color: #ef4444; font-size: 11px; font-style: normal; }
.feedback-field b { color: #94a3b8; font-size: 11px; font-weight: 400; }
.feedback-field textarea { width: 100%; resize: vertical; min-height: 118px; padding: 11px 12px; border: 1px solid #dbe3ee; border-radius: 9px; outline: none; color: #1e293b; font: inherit; font-size: 13px; line-height: 1.55; }
.feedback-field textarea:focus { border-color: #7da2f8; box-shadow: 0 0 0 3px rgba(37,99,235,.09); }
.feedback-field > small { display: block; margin-top: 4px; color: #94a3b8; font-size: 11px; text-align: right; }
.feedback-field > small.limit { color: #ef4444; }
.feedback-file-input { display: none; }
.feedback-upload { width: 100%; padding: 13px; border: 1px dashed #cbd5e1; border-radius: 9px; color: #64748b; background: #f8fafc; cursor: pointer; }
.feedback-upload:hover { border-color: #93b4fd; color: #2563eb; background: #f5f8ff; }
.feedback-upload span { margin-left: 6px; font-size: 12px; }
.feedback-upload small { display: block; margin-top: 4px; color: #94a3b8; font-size: 10px; }
.feedback-previews { display: flex; gap: 9px; margin-top: 9px; }
.feedback-previews figure { position: relative; width: 72px; height: 72px; margin: 0; }
.feedback-previews img { width: 100%; height: 100%; object-fit: cover; border: 1px solid #e2e8f0; border-radius: 8px; }
.feedback-previews button { position: absolute; top: -6px; right: -6px; width: 21px; height: 21px; padding: 0; border: 2px solid #fff; border-radius: 50%; color: #fff; background: #64748b; cursor: pointer; font-size: 9px; }
.feedback-error { margin: 0; padding: 9px 11px; border-radius: 8px; color: #b91c1c; background: #fef2f2; font-size: 12px; }
.feedback-actions { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 8px; padding-top: 2px; }
.feedback-actions > span { color: #94a3b8; font-size: 10px; }
.feedback-primary, .feedback-secondary { padding: 9px 14px; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 600; }
.feedback-primary { border: 1px solid #2563eb; color: #fff; background: #2563eb; }
.feedback-primary:disabled { opacity: .6; cursor: wait; }
.feedback-secondary { border: 1px solid #dbe3ee; color: #64748b; background: #fff; }
.feedback-success { padding: 40px 24px 30px; text-align: center; }
.feedback-success > i { color: #22c55e; font-size: 38px; }
.feedback-success h3 { margin: 14px 0 6px; color: #1e293b; }
.feedback-success p { margin: 0 0 22px; color: #64748b; font-size: 13px; }
.feedback-fade-enter-active, .feedback-fade-leave-active { transition: opacity .18s; }
.feedback-fade-enter-from, .feedback-fade-leave-to { opacity: 0; }
@media (max-width: 560px) {
  .feedback-mask { align-items: flex-end; padding: 0; }
  .feedback-dialog { width: 100%; max-height: 92vh; border-radius: 16px 16px 0 0; }
  .feedback-actions { grid-template-columns: 1fr 1fr; }
  .feedback-actions > span { grid-column: 1 / -1; }
}
</style>
