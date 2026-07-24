<template>
  <div class="step-wrap">
    <div class="step-head">
      <div class="step-head-icon" style="background:linear-gradient(135deg,#10b981,#34d399)">
        <i class="fas fa-list-check"></i>
      </div>
      <div>
        <h3 class="step-title">设定纳排标准</h3>
        <p class="step-subtitle">
          定义文献应达到的纳入或排除条件
          <button @click="showGuide = true" class="ml-2 text-xs text-indigo-500 hover:text-indigo-700 underline">
            <i class="fas fa-lightbulb mr-0.5"></i>查看撰写指南
          </button>
        </p>
      </div>
    </div>

    <!-- 常用排除标准快捷勾选 -->
    <div class="step-list-box mb-4" style="background:#eff6ff;border-color:#bfdbfe;padding:14px 16px">
      <p class="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-3">
        <i class="fas fa-bolt mr-1"></i>常用排除标准（勾选后自动添加）
      </p>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
        <label v-for="preset in presets" :key="preset" class="flex items-start gap-2 cursor-pointer group">
          <input
            type="checkbox"
            :checked="s.criteriaList.includes(preset)"
            @change="togglePreset(preset)"
            class="mt-0.5 w-4 h-4 rounded accent-green-600 cursor-pointer flex-shrink-0"
          />
          <span class="text-sm text-gray-700 group-hover:text-gray-900 leading-snug">{{ preset }}</span>
        </label>
      </div>
    </div>

    <!-- 自定义输入 -->
    <div class="flex space-x-2 mb-4">
      <input
        v-model="newCriteria"
        @keyup.enter="addCriteria"
        type="text"
        placeholder="自定义：输入一条标准并回车"
        class="flex-1 px-4 py-2.5 input-base"
      />
      <button @click="addCriteria" class="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700">
        <i class="fas fa-plus"></i> 添加
      </button>
    </div>

    <!-- 标准列表 -->
    <div class="step-list-box" style="min-height:200px;max-height:400px">
      <div v-if="s.criteriaList.length === 0" class="h-full flex flex-col items-center justify-center text-gray-400 py-8">
        <i class="fas fa-clipboard-list text-3xl mb-2 opacity-50"></i>
        <p>暂无标准，请在上方添加</p>
      </div>
      <div v-else class="space-y-2">
        <div
          v-for="(c, idx) in s.criteriaList"
          :key="idx"
          class="step-list-item group"
        >
          <span class="text-gray-700">
            <span class="font-bold text-green-600 mr-2">{{ idx + 1 }}.</span>{{ c }}
          </span>
          <button
            @click="removeCriteria(idx)"
            class="text-gray-300 hover:text-red-500 transition opacity-0 group-hover:opacity-100"
          >
            <i class="fas fa-trash-alt"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- 撰写指南弹窗 -->
    <Teleport to="body">
      <div v-if="showGuide" class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" @click.self="showGuide = false">
        <div class="bg-white rounded-xl p-6 max-w-lg w-full shadow-xl max-h-[80vh] overflow-y-auto">
          <h4 class="text-lg font-bold mb-3">纳排标准撰写指南</h4>
          <p class="text-sm text-gray-600 mb-4">以下为常见排除标准类型参考：</p>
          <ol class="space-y-2 text-sm text-gray-700">
            <li>文献类型限制（如：综述、病例报告、摘要、学位论文等）</li>
            <li>语言限制（如：非中英文文献）</li>
            <li>研究设计限制（如：非随机对照研究）</li>
            <li>研究对象限制（如：非目标人群）</li>
            <li>干预/暴露因素限制（如：不含目标干预）</li>
            <li>结局指标限制（如：未报告目标指标）</li>
            <li>其他（如：重复发表、无法获取摘要等）</li>
          </ol>
          <button @click="showGuide = false" class="mt-4 px-4 py-2 bg-gray-100 rounded-lg hover:bg-gray-200 text-sm">关闭</button>
        </div>
      </div>
    </Teleport>
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

const newCriteria = ref('')
const showGuide = ref(false)

const presets = [
  '无法获取摘要的文献',
  '非中、英文发表的文献',
  '会议摘要、评论、社论、报道及学位论文',
  '研究类型为非原始研究（如综述研究等）',
  '未以人类为研究对象',
]

async function saveCriteria() {
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'criteria')
  if (!step) return
  try {
    await http.patch(`/steps/${step.id}/update_metadata/`, {
      metadata: { criteria: s.criteriaList },
    })
  } catch (err) {
    console.error('保存纳排标准失败', err)
  }
}

async function addCriteria() {
  const val = newCriteria.value.trim()
  if (!val) return
  s.criteriaList.push(val)
  newCriteria.value = ''
  await saveCriteria()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function removeCriteria(idx) {
  s.criteriaList.splice(idx, 1)
  await saveCriteria()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function togglePreset(preset) {
  const idx = s.criteriaList.indexOf(preset)
  if (idx === -1) {
    s.criteriaList.push(preset)
  } else {
    s.criteriaList.splice(idx, 1)
  }
  await saveCriteria()
  await taskStore.fetchActivityLogs(project.currentProject.id)
}

async function loadCriteria() {
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'criteria')
  if (step?.metadata?.criteria) {
    s.criteriaList = step.metadata.criteria
  }
}

onMounted(loadCriteria)
</script>
