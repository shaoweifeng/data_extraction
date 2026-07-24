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

    <!-- 输入区域 — 两行布局，避免失衡 -->
    <div class="mb-4 p-4 rounded-xl" style="background:#f0f9ff;border:1px solid #bae6fd">
      <div class="flex gap-2 mb-2">
        <div style="width:160px;flex-shrink:0">
          <label class="text-xs font-semibold text-cyan-700 mb-1 block">字段名称</label>
          <input
            v-model="newName"
            @keyup.enter="newDef && addField()"
            type="text"
            placeholder="如：年龄"
            class="input-base"
          />
        </div>
        <div class="flex-1 min-w-0">
          <label class="text-xs font-semibold text-cyan-700 mb-1 block">字段定义</label>
          <input
            v-model="newDef"
            @keyup.enter="newName && addField()"
            type="text"
            placeholder="如：研究中纳入患者的年龄情况"
            class="input-base"
          />
        </div>
      </div>
      <div class="flex justify-end">
        <button
          @click="addField"
          :disabled="!newName.trim() || !newDef.trim()"
          class="btn-primary"
          style="background:linear-gradient(135deg,#0891b2,#22d3ee);font-size:0.82rem"
        >
          <i class="fas fa-plus"></i> 添加字段
        </button>
      </div>
    </div>

    <!-- 字段列表 -->
    <div class="step-list-box" style="min-height:200px;max-height:400px">
      <div v-if="s.extractionFields.length === 0" class="h-full flex flex-col items-center justify-center text-gray-400 py-8">
        <i class="fas fa-tag text-3xl mb-2 opacity-50"></i>
        <p>暂未添加提取字段，请在上方输入</p>
      </div>
      <div v-else class="space-y-2">
        <div
          v-for="(f, idx) in s.extractionFields"
          :key="idx"
          class="step-list-item group"
          style="align-items:flex-start"
        >
          <div class="flex-1 min-w-0 pr-3">
            <div class="flex items-center gap-1 mb-1">
              <span class="badge badge-blue" style="font-size:0.68rem">{{ idx + 1 }}</span>
              <span class="font-semibold text-gray-800 text-sm">{{ f.name }}</span>
            </div>
            <p class="text-gray-500 text-xs leading-relaxed">{{ f.definition }}</p>
          </div>
          <button
            @click="removeField(idx)"
            class="text-gray-300 hover:text-red-500 transition opacity-0 group-hover:opacity-100 flex-shrink-0 mt-0.5"
          >
            <i class="fas fa-trash-alt text-sm"></i>
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
    // 有提取字段时，标记步骤为 completed（或字段为空时可保持 skipped/completed 不变）
    if (s.extractionFields.length > 0 && step.status !== 'completed') {
      await http.post(`/steps/${step.id}/complete/`)
      await project.fetchStages(project.currentProject.id)
    }
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
