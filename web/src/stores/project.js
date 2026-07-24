/**
 * stores/project.js
 * 项目 / 阶段 / 步骤状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as projectApi from '@/api/project'

export const useProjectStore = defineStore('project', () => {
  const projects = ref([])
  const currentProject = ref(null)
  const stagesData = ref([])

  // 当前阶段（固定 SCREEN_1，后续扩展时修改）
  const currentStage = ref('SCREEN_1')

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
    currentProject.value = project
    await fetchStages(project.id)
  }

  async function fetchStages(projectId) {
    stagesData.value = await projectApi.fetchStages(projectId)
  }

  async function skipStep(stepId) {
    return await projectApi.skipStep(stepId)
  }

  function reset() {
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
