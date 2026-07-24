<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#0891b2,#22d3ee)">
        <i class="fas fa-tags"></i>
      </div>
      <div>
        <h3 class="step-title">设定提取字段</h3>
        <p class="step-subtitle">定义需要从文献中提取的数据字段及其含义</p>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="flex gap-2 mb-4">
      <input
        v-model="newName"
        @keyup.enter="newDef && addField()"
        type="text"
        placeholder="字段名称（如：年龄）"
        class="w-48 px-4 py-3 border rounded-lg focus:ring-2 focus:ring-cyan-500"
      />
      <input
        v-model="newDef"
        @keyup.enter="newName && addField()"
        type="text"
        placeholder="字段定义（如：研究中纳入患者的年龄情况）"
        class="flex-1 px-4 py-3 border rounded-lg focus:ring-2 focus:ring-cyan-500"
      />
      <button @click="addField" class="px-6 py-3 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700">
        <i class="fas fa-plus"></i> 添加
      </button>
    </div>

    <!-- 字段列表 -->
    <div class="bg-gray-50 rounded-xl border p-4 min-h-[200px] max-h-[400px] overflow-y-auto">
      <div v-if="s.extractionFields.length === 0" class="h-full flex flex-col items-center justify-center text-gray-400 py-8">
        <i class="fas fa-tag text-3xl mb-2 opacity-50"></i>
        <p>暂未添加提取字段，请在上方输入</p>
      </div>
      <div v-else class="space-y-2">
        <div
          v-for="(f, idx) in s.extractionFields"
          :key="idx"
          class="flex justify-between items-center bg-white px-4 py-3 rounded-lg border shadow-sm group"
        >
          <div>
            <span class="font-bold text-cyan-600 mr-2">{{ idx + 1 }}. {{ f.name }}</span>
            <span class="text-gray-500 text-sm">— {{ f.definition }}</span>
          </div>
          <button
            @click="removeField(idx)"
            class="text-gray-300 hover:text-red-500 transition opacity-0 group-hover:opacity-100"
          >
            <i class="fas fa-trash-alt"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useScreeningStore } from '@/stores/screening'
import { useProjectStore } from '@/stores/project'
import { useTaskStore } from '@/stores/task'
import http from '@/api/http'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const newName = ref('')
const newDef = ref('')

async function saveFields() {
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'field_extraction')
  if (!step) return
  try {
    await http.patch(`/steps/${step.id}/update_metadata/`, {
      metadata: { fields: s.extractionFields },
    })
  } catch (err) {
    console.error('保存提取字段失败', err)
  }
}

async function addField() {
  const name = newName.value.trim()
  const def = newDef.value.trim()
  if (!name || !def) return
  s.extractionFields.push({ name, definition: def })
  newName.value = ''
  newDef.value = ''
  await saveFields()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function removeField(idx) {
  s.extractionFields.splice(idx, 1)
  await saveFields()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function loadFields() {
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'field_extraction')
  if (step?.metadata?.fields) {
    s.extractionFields = step.metadata.fields
  }
}

onMounted(loadFields)
</script>
