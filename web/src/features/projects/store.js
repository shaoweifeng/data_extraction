/**
 * features/projects/store.js
 * 项目 / 阶段 / 步骤状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as projectApi from '@/features/projects/api'

export const useProjectStore = defineStore('project', () => {
  const projects = ref([])
  const currentProject = ref(null)
  const stagesData = ref([])

  // 当前阶段（固定 SCREEN_1，后续扩展时修改）
  const currentStage = ref('SCREEN_1')
  let stageRequestGeneration = 0

  // computed: 当前阶段的步骤列表
  const currentStageSteps = computed(() => {
    const stage = stagesData.value.find((s) => s.stage_key === currentStage.value)
    return stage?.steps || []
  })

  async function fetchProjects() {
    projects.value = await projectApi.fetchProjects()
  }

  async function createProject(data) {
    const project = await projectApi.createProject(data)
    projects.value.push(project)
    return project
  }

  async function deleteProject(projectId) {
    await projectApi.deleteProject(projectId)
    projects.value = projects.value.filter((p) => p.id !== projectId)
    if (currentProject.value?.id === projectId) {
      currentProject.value = null
      stagesData.value = []
    }
  }

  async function selectProject(project) {
    const generation = ++stageRequestGeneration
    currentProject.value = project
    const stages = await projectApi.fetchStages(project.id)
    if (
      generation === stageRequestGeneration
      && Number(currentProject.value?.id) === Number(project.id)
    ) {
      stagesData.value = stages
    }
  }

  async function fetchStages(projectId) {
    const generation = ++stageRequestGeneration
    const stages = await projectApi.fetchStages(projectId)
    if (
      generation === stageRequestGeneration
      && Number(currentProject.value?.id) === Number(projectId)
    ) {
      stagesData.value = stages
    }
  }

  async function skipStep(stepId) {
    return await projectApi.skipStep(stepId)
  }

  function reset() {
    stageRequestGeneration++
    currentProject.value = null
    stagesData.value = []
  }

  return {
    projects,
    currentProject,
    stagesData,
    currentStage,
    currentStageSteps,
    fetchProjects,
    createProject,
    deleteProject,
    selectProject,
    fetchStages,
    skipStep,
    reset,
  }
})
