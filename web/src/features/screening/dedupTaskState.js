const ACTIVE_STATUSES = new Set(['pending', 'queuing', 'running'])

export function findLatestDedupTask(tasks = []) {
  return tasks.find(task => task.task_type === 'dedup') || null
}

export function getDedupTaskUiState(task) {
  if (!task) return { active: false, completed: false, progress: 0, message: '' }

  const progress = Math.max(0, Math.min(100, Math.round(task.progress_percentage || 0)))
  let message = '正在启动去重任务...'
  if (progress >= 100) message = '正在完成收尾...'
  else if (progress >= 70) message = `正在保存结果 ${progress}%`
  else if (progress >= 55) message = `正在生成去重文件 ${progress}%`
  else if (progress >= 15) message = `正在扫描文献 ${progress}%`
  else if (progress > 0) message = `正在准备文件 ${progress}%`

  return {
    active: ACTIVE_STATUSES.has(task.status),
    completed: task.status === 'completed',
    progress,
    message: task.status === 'completed' ? '去重完成' : message,
  }
}
