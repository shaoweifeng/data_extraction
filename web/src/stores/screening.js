/**
 * stores/screening.js
 * AI 初筛全流程状态（步骤 1~6 共享）
 * 完整业务逻辑在 E3/E4 批次中填充
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useScreeningStore = defineStore('screening', () => {
  // 步骤导航
  const currentStep = ref(1)

  // 文件上传/解析（步骤1）
  const referenceFiles = ref([])
  const uploadingFiles = ref([])
  const isParsing = ref(false)
  const parsedCount = ref(0)
  const uploadPhase = ref('idle') // idle | uploading | parsing
  const uploadProgress = ref(0)
  const uploadCurrentFile = ref('')
  const uploadFileIndex = ref(0)
  const uploadTotalFiles = ref(0)
  const parseProgressCurrent = ref(0)
  const parseProgressTotal = ref(0)
  const parseProgressMsg = ref('')

  // 去重（步骤2）
  const isDeduplicating = ref(false)
  const dedupCompleted = ref(false)
  const dedupStats = ref(null)
  const showDuplicateDetails = ref(false)
  const showSkipDedupModal = ref(false)

  // 纳排标准（步骤3）
  const newCriteria = ref('')
  const criteriaList = ref([])
  const showCriteriaGuide = ref(false)

  // 提取字段（步骤4）
  const newExtractionFieldName = ref('')
  const newExtractionFieldDef = ref('')
  const extractionFields = ref([])

  // AI 初筛（步骤5）
  const screeningTab = ref('pending')
  const pendingFiles = ref([])
  const screenedFiles = ref([])
  const pendingPage = ref(0)
  const screenedPage = ref(0)
  const pendingTotal = ref(0)
  const screenedTotal = ref(0)
  const PAGE_SIZE = 20
  const latestTask = ref(null)
  const isProcessing = ref(false)
  const aiScreenStats = ref(null)
  const screeningResults = ref([])
  const aiScreenLogContent = ref('')
  const processedCount = ref(0)
  const screeningProgressValue = ref(0)
  const totalRefs = ref(0)

  // AI 模型选择
  const aiModelsList = ref([])
  const aiModelsLoading = ref(false)
  const selectedAiModel = ref(null)

  // Prompt
  const promptPanelOpen = ref(false)
  const useCustomPrompt = ref(false)
  const customPromptText = ref('')
  const promptSaveStatus = ref('')
  const defaultPromptPreview = ref('')

  // 导出（步骤6）
  const exportFiles = ref([])
  const exportStepId = ref(null)
  const isExporting = ref(false)
  const exportingType = ref('')
  const selectedExcelVersion = ref(0)
  const selectedRisVersion = ref(0)
  const selectedExcelAllVersion = ref(0)
  const selectedExcelIncludedVersion = ref(0)
  const selectedExcelExcludedVersion = ref(0)
  const exportXlsxFiles = ref([])
  const exportRisFiles = ref([])
  const exportXlsxAllFiles = ref([])
  const exportXlsxIncludedFiles = ref([])
  const exportXlsxExcludedFiles = ref([])

  function reset() {
    currentStep.value = 1
    referenceFiles.value = []
    uploadingFiles.value = []
    isParsing.value = false
    parsedCount.value = 0
    uploadPhase.value = 'idle'
    uploadProgress.value = 0
    uploadCurrentFile.value = ''
    uploadFileIndex.value = 0
    uploadTotalFiles.value = 0
    parseProgressCurrent.value = 0
    parseProgressTotal.value = 0
    parseProgressMsg.value = ''
    isDeduplicating.value = false
    dedupCompleted.value = false
    dedupStats.value = null
    showDuplicateDetails.value = false
    showSkipDedupModal.value = false
    newCriteria.value = ''
    criteriaList.value = []
    newExtractionFieldName.value = ''
    newExtractionFieldDef.value = ''
    extractionFields.value = []
    screeningTab.value = 'pending'
    pendingFiles.value = []
    screenedFiles.value = []
    pendingPage.value = 0
    screenedPage.value = 0
    pendingTotal.value = 0
    screenedTotal.value = 0
    latestTask.value = null
    isProcessing.value = false
    aiScreenStats.value = null
    screeningResults.value = []
    aiScreenLogContent.value = ''
    processedCount.value = 0
    screeningProgressValue.value = 0
    totalRefs.value = 0
    promptPanelOpen.value = false
    useCustomPrompt.value = false
    customPromptText.value = ''
    promptSaveStatus.value = ''
    exportFiles.value = []
    exportStepId.value = null
    isExporting.value = false
    selectedExcelVersion.value = 0
    selectedRisVersion.value = 0
    selectedExcelAllVersion.value = 0
    selectedExcelIncludedVersion.value = 0
    selectedExcelExcludedVersion.value = 0
    exportXlsxFiles.value = []
    exportRisFiles.value = []
    exportXlsxAllFiles.value = []
    exportXlsxIncludedFiles.value = []
    exportXlsxExcludedFiles.value = []
  }

  return {
    currentStep,
    referenceFiles, uploadingFiles, isParsing, parsedCount,
    uploadPhase, uploadProgress, uploadCurrentFile, uploadFileIndex,
    uploadTotalFiles, parseProgressCurrent, parseProgressTotal, parseProgressMsg,
    isDeduplicating, dedupCompleted, dedupStats, showDuplicateDetails, showSkipDedupModal,
    newCriteria, criteriaList, showCriteriaGuide,
    newExtractionFieldName, newExtractionFieldDef, extractionFields,
    screeningTab, pendingFiles, screenedFiles, pendingPage, screenedPage,
    pendingTotal, screenedTotal, PAGE_SIZE, latestTask, isProcessing,
    aiScreenStats, screeningResults, aiScreenLogContent, processedCount,
    screeningProgressValue, totalRefs,
    aiModelsList, aiModelsLoading, selectedAiModel,
    promptPanelOpen, useCustomPrompt, customPromptText, promptSaveStatus, defaultPromptPreview,
    exportFiles, exportStepId, isExporting, exportingType,
    selectedExcelVersion, selectedRisVersion, selectedExcelAllVersion,
    selectedExcelIncludedVersion, selectedExcelExcludedVersion,
    exportXlsxFiles, exportRisFiles, exportXlsxAllFiles,
    exportXlsxIncludedFiles, exportXlsxExcludedFiles,
    reset,
  }
})
