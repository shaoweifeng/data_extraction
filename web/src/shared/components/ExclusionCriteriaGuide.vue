<template>
  <!-- 撰写指南抽屉 -->
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="modelValue" class="fixed right-0 top-0 bottom-0 z-50">
        <div class="w-full max-w-md bg-white h-full shadow-2xl border-l border-gray-200 flex flex-col overflow-hidden rounded-l-xl">
          <!-- 头部 -->
          <div class="flex items-center justify-between px-6 py-4 border-b bg-gradient-to-r from-blue-50 to-white flex-shrink-0">
            <div class="flex items-center gap-2">
              <i class="fas fa-lightbulb text-blue-500 text-lg"></i>
              <h2 class="text-base font-bold text-gray-800">排除标准撰写指南</h2>
            </div>
            <button aria-label="关闭撰写指南" class="text-gray-400 hover:text-gray-600 text-xl leading-none" @click="$emit('update:modelValue', false)">&times;</button>
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
</template>
<script setup>
defineProps({ modelValue: Boolean })
defineEmits(['update:modelValue'])
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
