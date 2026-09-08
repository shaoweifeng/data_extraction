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

    <!-- 撰写指南抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="showGuide" class="fixed right-0 top-0 bottom-0 z-50">
          <div class="w-full max-w-md bg-white h-full shadow-2xl border-l border-gray-200 flex flex-col overflow-hidden rounded-l-xl">
            <!-- 头部 -->
            <div class="flex items-center justify-between px-6 py-4 border-b bg-gradient-to-r from-blue-50 to-white flex-shrink-0">
              <div class="flex items-center gap-2">
                <i class="fas fa-lightbulb text-blue-500 text-lg"></i>
                <h2 class="text-base font-bold text-gray-800">排除标准撰写指南</h2>
              </div>
              <button @click="showGuide = false" class="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
            </div>
            <!-- 内容 -->
            <div class="flex-1 overflow-y-auto px-6 py-5 space-y-6">
              <!-- 板块一 -->
              <div>
                <div class="flex items-center gap-2 mb-3">
                  <span class="w-1 h-5 bg-blue-500 rounded-full inline-block"></span>
                  <h3 class="text-sm font-bold text-gray-700">板块一：排除标准撰写的角度（PICOs / PEO 原则）</h3>
                </div>
                <p class="text-xs text-gray-500 mb-3 leading-relaxed">撰写排除标准时，建议从以下四个维度逐一考虑，确保标准完整覆盖文献筛选需求：</p>
                <div class="grid grid-cols-2 gap-2">
                  <div class="flex items-start gap-2 p-3 rounded-lg bg-blue-50 border border-blue-100">
                    <i class="fas fa-users text-blue-400 mt-0.5 text-xs flex-shrink-0"></i>
                    <div>
                      <p class="text-xs font-semibold text-blue-700">研究对象</p>
                      <p class="text-xs text-gray-500 mt-0.5">P / Population</p>
                    </div>
                  </div>
                  <div class="flex items-start gap-2 p-3 rounded-lg bg-purple-50 border border-purple-100">
                    <i class="fas fa-flask text-purple-400 mt-0.5 text-xs flex-shrink-0"></i>
                    <div>
                      <p class="text-xs font-semibold text-purple-700">干预措施 / 暴露因素</p>
                      <p class="text-xs text-gray-500 mt-0.5">I / E · Intervention / Exposure</p>
                    </div>
                  </div>
                  <div class="flex items-start gap-2 p-3 rounded-lg bg-green-50 border border-green-100">
                    <i class="fas fa-chart-bar text-green-400 mt-0.5 text-xs flex-shrink-0"></i>
                    <div>
                      <p class="text-xs font-semibold text-green-700">结局指标</p>
                      <p class="text-xs text-gray-500 mt-0.5">O · Outcome</p>
                    </div>
                  </div>
                  <div class="flex items-start gap-2 p-3 rounded-lg bg-amber-50 border border-amber-100">
                    <i class="fas fa-file-alt text-amber-400 mt-0.5 text-xs flex-shrink-0"></i>
                    <div>
                      <p class="text-xs font-semibold text-amber-700">研究类型</p>
                      <p class="text-xs text-gray-500 mt-0.5">S · Study design</p>
                    </div>
                  </div>
                </div>
              </div>
              <hr class="border-gray-100">
              <!-- 板块二 -->
              <div>
                <div class="flex items-center gap-2 mb-4">
                  <span class="w-1 h-5 bg-green-500 rounded-full inline-block"></span>
                  <h3 class="text-sm font-bold text-gray-700">板块二：参考示例</h3>
                </div>
                <!-- 示例1 -->
                <div class="mb-5">
                  <div class="bg-gray-50 rounded-lg px-4 py-2 mb-3 border-l-4 border-blue-400">
                    <p class="text-xs font-semibold text-gray-700">示例 1</p>
                    <p class="text-xs text-gray-500 mt-0.5">食管癌化疗后骨髓抑制影响因素 meta 分析</p>
                  </div>
                  <ol class="space-y-1.5 pl-1">
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">1.</span><span>无法获取摘要</span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">2.</span><span>会议摘要、评论、社论及学位论文、病例报告、致编辑的信件以及观点类文章</span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">3.</span><span>非中、英文发表的文献</span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">4.</span><span>非人体研究</span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">5.</span><span>研究类型为非原始研究（如综述研究等）<span class="ml-1 px-1.5 py-0.5 bg-amber-100 text-amber-600 rounded text-[10px]">研究类型</span></span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">6.</span><span>患者未患有食道癌且未使用化学治疗<span class="ml-1 px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-[10px]">研究对象</span></span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">7.</span><span>未报告患者血象或未对骨髓抑制情况进行研究<span class="ml-1 px-1.5 py-0.5 bg-green-100 text-green-600 rounded text-[10px]">结局指标</span></span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">8.</span><span>未提到影响食道癌患者化疗后骨髓抑制情况的因素<span class="ml-1 px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded text-[10px]">干预/暴露</span></span></li>
                  </ol>
                </div>
                <!-- 示例2 -->
                <div>
                  <div class="bg-gray-50 rounded-lg px-4 py-2 mb-3 border-l-4 border-green-400">
                    <p class="text-xs font-semibold text-gray-700">示例 2</p>
                    <p class="text-xs text-gray-500 mt-0.5">健康生活方式干预（饮食、运动、心理等）控制体重的研究</p>
                  </div>
                  <ol class="space-y-1.5 pl-1">
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">1.</span><span>无法获取摘要</span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">2.</span><span>会议摘要、评论、社论及学位论文、病例报告、致编辑的信件以及观点类文章</span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">3.</span><span>非英文文献</span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">4.</span><span>非随机对照研究<span class="ml-1 px-1.5 py-0.5 bg-amber-100 text-amber-600 rounded text-[10px]">研究类型</span></span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">5.</span><span>研究对象非青少年（10–19 岁之间）<span class="ml-1 px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-[10px]">研究对象</span></span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">6.</span><span>未进行减重干预<span class="ml-1 px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded text-[10px]">干预/暴露</span></span></li>
                    <li class="flex gap-2 text-xs text-gray-600"><span class="font-bold text-gray-400 flex-shrink-0">7.</span><span>未用体重率、体脂率等指标对减重效果进行评估<span class="ml-1 px-1.5 py-0.5 bg-green-100 text-green-600 rounded text-[10px]">结局指标</span></span></li>
                  </ol>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useScreeningStore } from '@/features/screening/store'
import { useProjectStore } from '@/features/projects/store'
import { useTaskStore } from '@/features/workflow/store'
import * as workflowApi from '@/shared/api/workflow'

const s = useScreeningStore()
const project = useProjectStore()
const taskStore = useTaskStore()

const newCriteria = ref('')
const showGuide = ref(false)

const presets = [
  '无法获取摘要的文献',
  '非中、英文发表的文献',
  '会议摘要、图书章节及学位论文',
  '研究类型为非原始研究（如综述研究等）',
  '未以人类为研究对象（如动物实验、细胞实验）',
]

async function saveCriteria() {
  const stage = project.stagesData.find((st) => st.stage_key === 'SCREEN_1')
  if (!stage) return
  const step = stage.steps.find((st) => st.step_key === 'criteria')
  if (!step) return
  try {
    await workflowApi.updateStepMetadata(step.id, { criteria: s.criteriaList })
    // 有纳排标准时，将步骤标记为 completed
    if (s.criteriaList.length > 0 && step.status !== 'completed') {
      await workflowApi.completeStep(step.id)
      await project.fetchStages(project.currentProject.id)
    }
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

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}
.drawer-enter-from,
.drawer-leave-to {
  transform: translateX(100%);
}
</style>
