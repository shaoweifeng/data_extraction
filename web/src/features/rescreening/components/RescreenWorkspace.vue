<template>
  <RescreenStepUpload v-if="rescreen.currentStep === 1" />
  <RescreenStepFulltext v-else-if="rescreen.currentStep === 2" />
  <RescreenStepCriteria v-else-if="rescreen.currentStep === 3" />
  <RescreenStepAiScreen v-else-if="rescreen.currentStep === 4" />
  <RescreenStepReview v-else-if="rescreen.currentStep === 5" />
  <RescreenStepExport v-else-if="rescreen.currentStep === 6" />
</template>

<script setup>
import { useRescreenStore } from '@/features/rescreening/store'
import RescreenStepUpload from './RescreenStepUpload.vue'
import RescreenStepFulltext from './RescreenStepFulltext.vue'
import RescreenStepCriteria from './RescreenStepCriteria.vue'
import RescreenStepAiScreen from './RescreenStepAiScreen.vue'
import RescreenStepReview from './RescreenStepReview.vue'
import RescreenStepExport from './RescreenStepExport.vue'

const rescreen = useRescreenStore()
</script>
