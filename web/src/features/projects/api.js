/**
 * features/projects/api.js
 * 项目 / 阶段 / 步骤相关 API
 */
import http from '@/shared/api/http'
import { extractListData } from '@/utils/format'

export async function fetchProjects() {
  const res = await http.get('/projects/')
  return extractListData(res.data)
}

export async function createProject(data) {
  const res = await http.post('/projects/', data)
  return res.data
}

export async function deleteProject(projectId) {
  await http.delete(`/projects/${projectId}/`)
}

export async function fetchStages(projectId) {
  const res = await http.get(`/projects/${projectId}/stages/`)
  return res.data
}

export async function skipStep(stepId) {
  const res = await http.post(`/steps/${stepId}/skip/`)
  return res.data
}
