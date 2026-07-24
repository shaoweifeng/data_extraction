<template>
  <div class="flex items-center justify-between pt-4 border-t border-gray-200">
    <button
      v-if="screening.currentStep > 1"
      @click="screening.currentStep--"
      class="flex items-center gap-2 px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
    >
      ← 上一步
    </button>
    <div v-else />

    <button
      v-if="screening.currentStep < 6"
      @click="screening.currentStep++"
      class="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
    >
      下一步 →
    </button>
  </div>
</template>

<script setup>
import { useScreeningStore } from '@/stores/screening'
const screening = useScreeningStore()
</script>
