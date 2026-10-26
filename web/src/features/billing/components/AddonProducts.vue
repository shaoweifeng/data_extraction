<template>
  <div>
    <p class="addon-note">{{ kind === 'credits' ? '订阅用户可兑换优惠积分包；无需套餐也可追加体验积分。所有积分补充均在兑换后 12 个月内有效。' : '升级至目标并发，不叠加。需有有效套餐；同档可续期，有效期内暂不支持跨档更换。' }}</p>
    <div v-if="kind === 'concurrency' && Number(current.ai_call_slots) >= 16" class="addon-note status">当前已达到最高公开并发档位。已有同档升级包仍可按资格续期。</div>
    <div class="addon-grid">
      <article v-for="item in visibleProducts" :key="item.version" class="addon-card" :class="{ unavailable: !item.eligible }">
        <span class="addon-badge">{{ item.kind === 'TRIAL' ? '无需订阅' : '订阅用户专享' }}</span>
        <h3>{{ item.name }}</h3>
        <div class="addon-amount">{{ item.kind === 'CONCURRENCY' ? `提升至 ${item.target_slots} 并发` : `${number(item.credits)} 积分` }}</div>
        <div class="addon-price">¥{{ Number(item.reference_price_cny) }}<small>{{ item.kind === 'CONCURRENCY' ? '/ 自然月' : '/ 份' }}</small></div>
        <small class="reference-label">正式服务参考价 · 暂不公开售卖</small>
        <p>{{ item.kind === 'CONCURRENCY' ? `有效 ${item.valid_months} 个自然月；不附送积分，不增加项目或存储额度。` : `兑换后有效 ${item.valid_months} 个月；不改变套餐及并发权益。` }}</p>
        <p v-if="!item.eligible" class="eligibility">{{ item.ineligible_reason }}</p>
        <button v-if="!item.eligible && item.ineligible_reason?.includes('先开通')" class="secondary" type="button" @click="$emit('show-plans')">查看个人套餐</button>
        <button v-else-if="item.eligible && contactEnabled" type="button" @click="$emit('consult', item)">申请使用</button>
      </article>
    </div>
    <p v-if="!visibleProducts.length" class="addon-note">暂无已上架商品。</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { selectAddonProducts } from '../products'
const props = defineProps({ products: { type: Array, default: () => [] }, kind: { type: String, default: 'credits' }, current: { type: Object, default: () => ({}) }, contactEnabled: Boolean })
defineEmits(['consult', 'show-plans'])
const visibleProducts = computed(() => selectAddonProducts(props.products, props.kind, props.current))
const number = value => Number(value || 0).toLocaleString('zh-CN')
</script>

<style scoped>
.addon-note{color:#64748b;font-size:.84rem;line-height:1.7;margin:0 0 20px}.status{padding:12px 15px;background:#eef2ff;border-radius:10px;color:#4f46e5}.addon-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr));gap:16px}.addon-card{min-width:0;border:1px solid #e2e8f0;border-radius:14px;padding:22px;display:flex;flex-direction:column;align-items:flex-start}.addon-card h3{font-size:1.1rem;margin:16px 0 8px}.addon-badge{font-size:.7rem;color:#4f46e5;background:#eef2ff;border-radius:20px;padding:4px 9px}.addon-amount{font-size:.88rem;color:#475569}.addon-price{font-size:1.8rem;font-weight:800;margin:18px 0 4px}.addon-price small{font-size:.76rem;color:#64748b;font-weight:400;margin-left:5px}.reference-label{font-size:.68rem;color:#a16207}.addon-card p{font-size:.78rem;line-height:1.7;color:#64748b;margin:16px 0 24px}.addon-card p.eligibility{margin:0 0 16px;color:#a16207}.addon-card button{width:100%;margin-top:auto;padding:11px;border:0;border-radius:9px;background:#4f46e5;color:white;font-weight:700;cursor:pointer}.addon-card button.secondary{background:#eef2ff;color:#4f46e5}.unavailable{background:#fafbfc}
</style>
