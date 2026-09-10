import http from '@/shared/api/http'


export function submitFeedback(payload, images, idempotencyKey) {
  const form = new FormData()
  form.append('category', payload.category)
  form.append('content', payload.content)
  if (payload.projectId) form.append('project_id', String(payload.projectId))
  form.append('page_path', payload.pagePath || '')
  form.append('route_name', payload.routeName || '')
  form.append('context', JSON.stringify(payload.context || {}))
  images.forEach(item => form.append('images', item.file, item.file.name))

  return http.post('/feedback/', form, {
    headers: {
      'Content-Type': 'multipart/form-data',
      'Idempotency-Key': idempotencyKey,
    },
    timeout: 30000,
  })
}

