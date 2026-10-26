export function selectAddonProducts(products, tab, current = {}) {
  const rows = products.filter(item => tab === 'concurrency'
    ? item.kind === 'CONCURRENCY'
    : item.kind === 'CREDIT' || item.kind === 'TRIAL')
  if (tab === 'credits') {
    const subscribed = !['FREE', 'ADMIN', undefined].includes(current.plan_code)
    return [...rows].sort((a, b) => Number(a.kind === (subscribed ? 'TRIAL' : 'CREDIT')) - Number(b.kind === (subscribed ? 'TRIAL' : 'CREDIT')))
  }
  return rows
}

export function addonConsultationDetails(item) {
  if (!item?.kind) return ''
  const benefit = item.kind === 'CONCURRENCY' ? `提升至 ${item.target_slots} 并发` : `${Number(item.credits).toLocaleString('zh-CN')} 积分`
  return `\n申请权益：${benefit}\n有效期：兑换后 ${item.valid_months} 个自然月`
}
