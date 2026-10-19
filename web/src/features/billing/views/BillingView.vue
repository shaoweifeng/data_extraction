<template>
  <div class="billing-page">
    <AppHeader ref="headerRef" />

    <main class="billing-shell">
      <header class="page-heading">
        <div>
          <p class="eyebrow">账户权益</p>
          <h1>套餐与积分</h1>
          <p>查看当前权益、积分有效期和每次 AI 任务的实际用量。</p>
        </div>
        <button class="ghost-btn" type="button" @click="router.push('/profile')">
          <i class="fas fa-user-gear"></i> 账户设置
        </button>
      </header>

      <div v-if="loading" class="loading-panel">
        <i class="fas fa-spinner fa-spin"></i> 正在加载账户权益…
      </div>

      <template v-else>
        <section class="summary-grid">
          <article class="summary-card balance-summary">
            <div class="summary-label"><i class="fas fa-coins"></i> 可用积分</div>
            <div class="summary-value">{{ balance?.is_unlimited ? '∞' : number(balance?.balance) }}</div>
            <div v-if="!balance?.is_unlimited" class="summary-foot">
              累计获得 {{ number(balance?.total_granted) }} · 已消耗 {{ number(balance?.total_consumed) }}
            </div>
            <div v-else class="summary-foot">管理员账户不扣除积分，但仍记录模型用量</div>
          </article>

          <article class="summary-card plan-summary">
            <div class="summary-label"><i class="fas fa-gem"></i> 当前套餐</div>
            <div class="summary-value plan-name">{{ currentPlan.plan_name || '免费体验' }}</div>
            <div class="entitlement-tags">
              <span>{{ limitText(currentPlan.project_limit, '个项目') }}</span>
              <span>{{ number(currentPlan.ai_call_slots) }} 个 AI 调用槽位</span>
              <span>{{ storageText(currentPlan.storage_limit_mb) }}</span>
            </div>
            <div v-if="currentPlan.expires_at" class="summary-foot">
              有效至 {{ formatDate(currentPlan.expires_at) }}
            </div>
          </article>

          <article class="summary-card expiry-summary">
            <div class="summary-label"><i class="fas fa-hourglass-half"></i> 最近到期积分</div>
            <template v-if="nearestExpiry">
              <div class="summary-value">{{ number(nearestExpiry.remaining_amount) }}</div>
              <div class="summary-foot">{{ formatDate(nearestExpiry.expires_at) }} 到期</div>
            </template>
            <template v-else>
              <div class="summary-value muted-value">暂无</div>
              <div class="summary-foot">当前积分没有临近到期批次</div>
            </template>
          </article>
        </section>

        <div v-if="plansData?.scheduled?.length" class="scheduled-banner">
          <i class="fas fa-calendar-check"></i>
          <div>
            <strong>已有待生效套餐</strong>
            <span v-for="item in plansData.scheduled" :key="`${item.version}-${item.starts_at}`">
              {{ item.plan_name }} 将于 {{ formatDate(item.starts_at) }} 生效
            </span>
          </div>
        </div>

        <section class="section-card">
          <div class="section-heading">
            <div><p class="eyebrow">个人套餐</p><h2>选择适合你的处理规模</h2></div>
            <span class="section-note">申请使用 · 暂不公开售卖</span>
          </div>
          <div class="internal-test-notice">
            <i class="fas fa-flask"></i>
            <div>
              <strong>当前处于内测阶段，暂不公开售卖</strong>
              <span>下列价格为未来正式服务参考价。如需体验或了解适用方案，请通过“申请咨询”与我们联系。</span>
            </div>
          </div>
          <div class="plan-grid">
            <article
              v-for="plan in plansData?.plans || []"
              :key="plan.version"
              class="plan-card"
              :class="{ current: currentPlan.plan_code === plan.plan_code, featured: plan.plan_code === 'PLUS' }"
            >
              <div class="plan-card-top">
                <div><h3>{{ plan.name }}</h3></div>
                <span v-if="currentPlan.plan_code === plan.plan_code" class="current-badge">当前套餐</span>
                <span v-else-if="plan.plan_code === 'PLUS'" class="recommend-badge">推荐</span>
              </div>
              <p class="plan-description">{{ plan.description || '完整个人研究工作流' }}</p>
              <div class="plan-price"><b>¥{{ money(plan.monthly_price_cny) }}</b><span>/ 月</span><small>正式服务参考价</small></div>
              <ul>
                <li><i class="fas fa-check"></i><strong>{{ number(plan.included_credits) }}</strong> 积分 / 月</li>
                <li><i class="fas fa-check"></i>最多 {{ plan.project_limit }} 个项目</li>
                <li><i class="fas fa-check"></i>{{ plan.ai_call_slots }} 个共享 AI 调用槽位</li>
                <li><i class="fas fa-check"></i>{{ storageText(plan.storage_limit_mb) }}</li>
                <li><i class="fas fa-check"></i>完整初筛、质量评价与导出能力</li>
              </ul>
              <button
                v-if="serviceContact.enabled"
                class="consult-btn"
                type="button"
                @click="openConsult(plan)"
              >
                申请使用
              </button>
            </article>
          </div>

          <div class="redeem-panel">
            <div class="redeem-copy">
              <i class="fas fa-ticket"></i>
              <div><strong>兑换套餐或积分</strong><span>套餐码会开通权益，积分码只增加可用积分。</span></div>
            </div>
            <div class="redeem-form">
              <input v-model="redeemCode" maxlength="32" placeholder="输入兑换码" :disabled="redeeming" @keyup.enter="submitRedeem" />
              <button type="button" :disabled="!redeemCode.trim() || redeeming" @click="submitRedeem">
                <i :class="redeeming ? 'fas fa-spinner fa-spin' : 'fas fa-arrow-right'"></i>
                {{ redeeming ? '兑换中' : '立即兑换' }}
              </button>
            </div>
            <p v-if="redeemMessage" class="form-message success"><i class="fas fa-circle-check"></i>{{ redeemMessage }}</p>
            <p v-if="redeemError" class="form-message error"><i class="fas fa-circle-exclamation"></i>{{ redeemError }}</p>
          </div>
        </section>

        <section class="section-card">
          <div class="section-heading compact">
            <div><p class="eyebrow">积分批次</p><h2>额度与有效期</h2></div>
            <span class="section-note">任务预占会暂时减少可用积分</span>
          </div>
          <div v-if="!batches?.results?.length" class="empty-state">暂无积分批次</div>
          <div v-else class="table-scroll">
            <table class="data-table">
              <thead><tr><th>来源</th><th>发放</th><th>可用</th><th>预占</th><th>到期时间</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="batch in batches.results" :key="batch.id">
                  <td><span class="source-badge">{{ batch.plan_name || batch.batch_type_display }}</span></td>
                  <td>{{ number(batch.granted_amount) }}</td>
                  <td class="strong-cell">{{ number(batch.remaining_amount) }}</td>
                  <td>{{ number(batch.reserved_amount) }}</td>
                  <td>{{ batch.expires_at ? formatDate(batch.expires_at) : '长期有效' }}</td>
                  <td><span :class="['status-pill', batch.is_expired ? 'expired' : 'active']">{{ batch.is_expired ? '已到期' : '有效' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="section-card">
          <div class="section-heading compact">
            <div><p class="eyebrow">积分账单</p><h2>收支与模型用量</h2></div>
            <span class="section-note">最终扣费以任务实际模型使用情况为准</span>
          </div>
          <div v-if="txnLoading" class="empty-state"><i class="fas fa-spinner fa-spin"></i> 加载中…</div>
          <div v-else-if="!transactions?.results?.length" class="empty-state">暂无积分流水</div>
          <div v-else class="ledger-list">
            <article v-for="txn in transactions.results" :key="txn.id" class="ledger-row">
              <button class="ledger-main" type="button" @click="toggleTransaction(txn)">
                <span :class="['ledger-icon', `type-${txn.txn_type}`]"><i :class="transactionIcon(txn.txn_type)"></i></span>
                <span class="ledger-copy"><strong>{{ txn.txn_type_display }}</strong><small>{{ txn.note || '积分账户变动' }} · {{ formatTime(txn.created_at) }}</small></span>
                <span :class="['ledger-amount', txn.amount > 0 ? 'positive' : txn.amount < 0 ? 'negative' : 'zero']">
                  {{ txn.amount > 0 ? '+' : '' }}{{ txn.amount }}
                  <small>余额 {{ txn.balance_after }}</small>
                </span>
                <i v-if="txn.usage?.length" :class="['fas', expandedTxn === txn.id ? 'fa-chevron-up' : 'fa-chevron-down', 'expand-icon']"></i>
              </button>
              <div v-if="expandedTxn === txn.id && txn.usage?.length" class="usage-detail">
                <div v-for="usage in txn.usage" :key="usage.usage_log_id" class="usage-block">
                  <div class="usage-meta">
                    <span>{{ usage.project_name || '已删除项目' }}</span>
                    <span>任务 #{{ usage.task_id || '—' }}</span>
                    <span>{{ usage.pricing_version }}</span>
                    <span>实际扣除 {{ number(usage.credits_consumed) }} 积分</span>
                  </div>
                  <div class="model-usage-grid">
                    <div v-for="model in usage.models" :key="model.model_id" class="model-usage-card">
                      <strong>{{ model.model_name }}</strong>
                      <span>{{ model.calls }} 次调用</span>
                      <b>约 {{ decimal(model.raw_credits) }} 积分</b>
                    </div>
                  </div>
                </div>
              </div>
            </article>
          </div>
          <div v-if="transactions?.total_pages > 1" class="pagination">
            <button :disabled="txnPage <= 1" @click="loadTransactions(txnPage - 1)"><i class="fas fa-chevron-left"></i></button>
            <span>第 {{ txnPage }} / {{ transactions.total_pages }} 页</span>
            <button :disabled="txnPage >= transactions.total_pages" @click="loadTransactions(txnPage + 1)"><i class="fas fa-chevron-right"></i></button>
          </div>
        </section>
      </template>
    </main>

    <div v-if="selectedPlan" class="contact-modal-backdrop" role="presentation" @click.self="closeConsult">
      <section class="contact-modal" role="dialog" aria-modal="true" aria-labelledby="contact-modal-title">
        <button class="modal-close" type="button" aria-label="关闭" @click="closeConsult"><i class="fas fa-xmark"></i></button>
        <div class="modal-heading">
          <span class="modal-icon"><i class="fas fa-comments"></i></span>
          <div>
            <p class="eyebrow">内测申请咨询</p>
            <h2 id="contact-modal-title">联系 {{ serviceContact.display_name || 'MetaFlow 服务助手' }}</h2>
            <p>{{ serviceContact.description || '当前处于内测阶段，暂不公开售卖。' }}</p>
          </div>
        </div>

        <div
          v-if="hasContactMethods"
          class="contact-layout"
          :class="{ 'without-qr': !serviceContact.qr_available }"
        >
          <div v-if="serviceContact.qr_available" class="qr-panel">
            <button
              class="qr-preview-trigger"
              type="button"
              aria-label="点击放大微信二维码"
              @click="qrPreviewOpen = true"
            >
              <img :src="serviceContact.qr_url" alt="服务联系微信二维码" @error="qrLoadFailed = true" />
            </button>
            <span v-if="qrLoadFailed">二维码暂时无法加载，可复制微信号联系</span>
            <small v-else><i class="fas fa-magnifying-glass-plus"></i> 点击放大后使用微信扫一扫</small>
          </div>
          <div class="contact-details">
            <div v-if="serviceContact.wechat_id" class="contact-row">
              <span><i class="fab fa-weixin"></i> 微信号</span>
              <strong>{{ serviceContact.wechat_id }}</strong>
              <button type="button" @click="copyText(serviceContact.wechat_id, 'wechat')">{{ copiedKey === 'wechat' ? '已复制' : '复制' }}</button>
            </div>
            <div v-if="serviceContact.contact_email" class="contact-row">
              <span><i class="fas fa-envelope"></i> 联系邮箱</span>
              <strong>{{ serviceContact.contact_email }}</strong>
              <button type="button" @click="copyText(serviceContact.contact_email, 'email')">{{ copiedKey === 'email' ? '已复制' : '复制' }}</button>
            </div>
            <div v-if="serviceContact.service_hours" class="contact-row no-action">
              <span><i class="fas fa-clock"></i> 服务时间</span>
              <strong>{{ serviceContact.service_hours }}</strong>
            </div>
          </div>
        </div>
        <div v-else class="default-contact-state">
          <i class="fas fa-circle-info"></i>
          <div><strong>当前尚未配置公开联系方式</strong><span>你仍可复制下方内容；联系方式开放后会在这里展示。</span></div>
        </div>

        <div class="consult-copy-box">
          <div><strong>咨询内容</strong><span>复制后通过微信发送即可，无需填写申请表。</span></div>
          <p>{{ consultationText }}</p>
          <button type="button" @click="copyText(consultationText, 'message')"><i class="fas fa-copy"></i>{{ copiedKey === 'message' ? '已复制咨询内容' : '复制咨询内容' }}</button>
        </div>
        <p v-if="serviceContact.security_notice" class="security-notice"><i class="fas fa-shield-halved"></i>{{ serviceContact.security_notice }}</p>
      </section>

      <div v-if="qrPreviewOpen" class="qr-preview-backdrop" role="presentation" @click.self="qrPreviewOpen = false">
        <section class="qr-preview-dialog" role="dialog" aria-modal="true" aria-label="微信二维码放大预览">
          <button class="qr-preview-close" type="button" aria-label="关闭二维码预览" @click="qrPreviewOpen = false">
            <i class="fas fa-xmark"></i>
          </button>
          <img :src="serviceContact.qr_url" alt="放大的服务联系微信二维码" />
          <p>使用微信扫一扫添加 {{ serviceContact.display_name || 'MetaFlow 服务助手' }}</p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppHeader from '@/shared/components/AppHeader.vue'
import * as billingApi from '@/features/billing/api'
import { useAuthStore } from '@/features/account/store'

const router = useRouter()
const auth = useAuthStore()
const headerRef = ref(null)
const loading = ref(true)
const txnLoading = ref(false)
const balance = ref(null)
const plansData = ref(null)
const batches = ref(null)
const transactions = ref(null)
const txnPage = ref(1)
const expandedTxn = ref(null)
const redeemCode = ref('')
const redeeming = ref(false)
const redeemMessage = ref('')
const redeemError = ref('')
const defaultServiceContact = {
  enabled: true,
  configured: false,
  display_name: 'MetaFlow 服务助手',
  wechat_id: '',
  contact_email: '',
  service_hours: '',
  description: '当前处于内测阶段，暂不公开售卖。如需申请使用，请关注平台后续通知。',
  security_notice: '请勿向任何人提供密码、邮箱验证码或其他账户安全信息。',
  qr_available: false,
  qr_url: null,
}
const serviceContact = ref({ ...defaultServiceContact })
const selectedPlan = ref(null)
const copiedKey = ref('')
const qrLoadFailed = ref(false)
const qrPreviewOpen = ref(false)

const currentPlan = computed(() => plansData.value?.current || balance.value?.plan || {})
const nearestExpiry = computed(() => (batches.value?.results || []).find(item => item.expires_at && !item.is_expired && item.remaining_amount > 0))
const hasContactMethods = computed(() => Boolean(
  serviceContact.value.qr_available || serviceContact.value.wechat_id || serviceContact.value.contact_email,
))
const consultationText = computed(() => {
  const planName = selectedPlan.value?.name || selectedPlan.value?.plan_code || '个人套餐'
  const account = auth.user?.email || auth.user?.username || '请填写平台注册账号'
  return `您好，我想咨询 MetaFlow ${planName} 的内测使用。\n平台账号：${account}`
})

function number(value) { return Number(value || 0).toLocaleString('zh-CN') }
function money(value) { return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }) }
function decimal(value) { return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }
function limitText(value, unit) { return Number(value) < 0 ? '项目数量不限' : `最多 ${number(value)} ${unit}` }
function storageText(value) {
  const amount = Number(value)
  if (amount < 0) return '存储空间不限'
  if (amount >= 1024 && amount % 1024 === 0) return `${number(amount / 1024)} GB 存储空间`
  return `${number(amount)} MB 存储空间`
}
function formatDate(value) { return value ? new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value)) : '—' }
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) : '—' }
function transactionIcon(type) {
  return ({ consume: 'fas fa-bolt', recharge: 'fas fa-ticket', grant: 'fas fa-gift', refund: 'fas fa-rotate-left', expire: 'fas fa-hourglass-end', adjust: 'fas fa-sliders', admin_usage: 'fas fa-chart-line' })[type] || 'fas fa-coins'
}
function toggleTransaction(txn) { if (txn.usage?.length) expandedTxn.value = expandedTxn.value === txn.id ? null : txn.id }
function openConsult(plan) {
  selectedPlan.value = plan
  copiedKey.value = ''
  qrLoadFailed.value = false
}
function closeConsult() {
  qrPreviewOpen.value = false
  selectedPlan.value = null
}
function onEscape(event) {
  if (event.key !== 'Escape') return
  if (qrPreviewOpen.value) qrPreviewOpen.value = false
  else closeConsult()
}
async function copyText(value, key) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    const input = document.createElement('textarea')
    input.value = value
    input.style.position = 'fixed'
    input.style.opacity = '0'
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    input.remove()
  }
  copiedKey.value = key
  window.setTimeout(() => { if (copiedKey.value === key) copiedKey.value = '' }, 1800)
}

async function loadTransactions(page = 1) {
  txnLoading.value = true
  try {
    const response = await billingApi.fetchTransactions({ page, page_size: 10 })
    transactions.value = response.data
    txnPage.value = page
    expandedTxn.value = null
  } finally { txnLoading.value = false }
}

async function loadPortal() {
  loading.value = true
  try {
    const [balanceResponse, planResponse, batchResponse, contactResponse] = await Promise.all([
      billingApi.fetchBalance(), billingApi.fetchPlans(), billingApi.fetchCreditBatches({ page: 1, page_size: 20 }),
      billingApi.fetchServiceContact().catch(() => ({ data: defaultServiceContact })),
    ])
    balance.value = balanceResponse.data
    plansData.value = planResponse.data
    batches.value = batchResponse.data
    serviceContact.value = { ...defaultServiceContact, ...contactResponse.data }
    await loadTransactions(1)
  } finally { loading.value = false }
}

async function submitRedeem() {
  const code = redeemCode.value.trim()
  if (!code || redeeming.value) return
  redeeming.value = true
  redeemMessage.value = ''
  redeemError.value = ''
  try {
    const response = await billingApi.redeemCode(code)
    redeemMessage.value = response.data.message || '兑换成功'
    redeemCode.value = ''
    await loadPortal()
    headerRef.value?.refreshBalance()
  } catch (error) {
    redeemError.value = error.response?.data?.error || '兑换失败，请检查兑换码'
  } finally { redeeming.value = false }
}

onMounted(() => {
  document.addEventListener('keydown', onEscape)
  loadPortal()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onEscape))
</script>

<style scoped>
.billing-page{min-height:100vh;background:#f5f7fb;color:#1e293b}.billing-shell{width:min(1180px,calc(100% - 40px));margin:0 auto;padding:34px 0 56px}.page-heading,.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.page-heading{margin-bottom:24px}.page-heading h1,.section-heading h2{margin:2px 0 6px;font-weight:800;letter-spacing:-.02em}.page-heading h1{font-size:1.8rem}.section-heading h2{font-size:1.2rem}.page-heading p,.section-note{margin:0;color:#64748b;font-size:.86rem}.eyebrow{text-transform:uppercase;letter-spacing:.12em!important;color:#6366f1!important;font-size:.7rem!important;font-weight:800;margin:0!important}.ghost-btn{border:1px solid #dbe2ea;background:#fff;color:#475569;border-radius:10px;padding:9px 14px;cursor:pointer}.ghost-btn:hover{border-color:#a5b4fc;color:#4f46e5}.loading-panel,.empty-state{padding:42px;text-align:center;color:#94a3b8;background:#fff;border:1px solid #e2e8f0;border-radius:14px}.summary-grid{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:16px;margin-bottom:20px}.summary-card,.section-card{background:#fff;border:1px solid #e2e8f0;border-radius:16px;box-shadow:0 8px 24px rgba(15,23,42,.04)}.summary-card{padding:20px}.balance-summary{background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;border:0}.summary-label{font-size:.78rem;color:#64748b;display:flex;gap:7px;align-items:center}.balance-summary .summary-label,.balance-summary .summary-foot{color:rgba(255,255,255,.8)}.summary-value{font-size:2rem;font-weight:850;margin:11px 0 7px}.plan-name{font-size:1.45rem}.muted-value{color:#94a3b8}.summary-foot{font-size:.76rem;color:#94a3b8}.entitlement-tags{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0}.entitlement-tags span{background:#eef2ff;color:#4f46e5;border-radius:999px;padding:4px 8px;font-size:.7rem;font-weight:700}.scheduled-banner{display:flex;align-items:center;gap:12px;background:#fffbeb;border:1px solid #fde68a;color:#92400e;border-radius:12px;padding:12px 16px;margin-bottom:20px}.scheduled-banner div{display:flex;flex-direction:column;gap:2px}.scheduled-banner span{font-size:.78rem}.section-card{padding:24px;margin-top:18px}.section-heading{margin-bottom:18px}.section-heading.compact{align-items:center}.internal-test-notice{display:flex;align-items:flex-start;gap:12px;margin:-2px 0 18px;padding:13px 15px;border:1px solid #c7d2fe;border-radius:12px;background:#f5f3ff;color:#4338ca}.internal-test-notice>i{margin-top:2px}.internal-test-notice div{display:flex;flex-direction:column;gap:3px}.internal-test-notice span{font-size:.76rem;color:#6366f1;line-height:1.55}.plan-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.plan-card{border:1px solid #e2e8f0;border-radius:14px;padding:20px;position:relative;display:flex;flex-direction:column}.plan-card.featured{border-color:#a5b4fc;box-shadow:0 10px 28px rgba(99,102,241,.1)}.plan-card.current{border:2px solid #6366f1}.plan-card-top{display:flex;justify-content:space-between;align-items:flex-start}.plan-card h3{margin:3px 0;font-size:1.25rem}.current-badge,.recommend-badge{font-size:.66rem;padding:4px 8px;border-radius:999px;font-weight:700}.current-badge{background:#eef2ff;color:#4f46e5}.recommend-badge{background:#fef3c7;color:#a16207}.plan-description{min-height:34px;color:#64748b;font-size:.78rem}.plan-price{display:flex;align-items:baseline;gap:4px;margin:17px 0;flex-wrap:wrap}.plan-price b{font-size:1.75rem}.plan-price span{font-size:.76rem;color:#94a3b8}.plan-price small{width:100%;color:#a16207;font-size:.66rem}.plan-card ul{list-style:none;margin:0 0 24px;padding:0;display:flex;flex-direction:column;gap:10px;color:#475569;font-size:.8rem}.plan-card li{display:flex;align-items:center;gap:8px}.plan-card li i{color:#22c55e;font-size:.7rem}.consult-btn{width:100%;margin-top:auto;padding:10px 14px;border:0;border-radius:9px;background:#4f46e5;color:#fff;font-weight:750;cursor:pointer}.consult-btn:hover{background:#4338ca}.redeem-panel{margin-top:18px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:13px;padding:16px}.redeem-copy{display:flex;align-items:center;gap:11px}.redeem-copy>i{width:36px;height:36px;display:grid;place-items:center;background:#ede9fe;color:#7c3aed;border-radius:10px}.redeem-copy div{display:flex;flex-direction:column}.redeem-copy span{font-size:.75rem;color:#64748b}.redeem-form{display:flex;gap:9px;margin-top:13px}.redeem-form input{flex:1;border:1px solid #dbe2ea;border-radius:9px;padding:10px 12px;outline:0}.redeem-form input:focus{border-color:#818cf8;box-shadow:0 0 0 3px #eef2ff}.redeem-form button{border:0;border-radius:9px;background:#4f46e5;color:#fff;font-weight:700;padding:0 18px;cursor:pointer}.redeem-form button:disabled{background:#c7d2fe}.form-message{margin:10px 0 0;font-size:.8rem;display:flex;gap:6px}.form-message.success{color:#15803d}.form-message.error{color:#b91c1c}.table-scroll{overflow-x:auto}.data-table{width:100%;border-collapse:collapse;font-size:.8rem}.data-table th{text-align:left;color:#64748b;font-size:.72rem;padding:9px;border-bottom:1px solid #e2e8f0}.data-table td{padding:11px 9px;border-bottom:1px solid #f1f5f9}.strong-cell{font-weight:800;color:#4f46e5}.source-badge,.status-pill{display:inline-flex;border-radius:999px;padding:3px 8px;font-size:.68rem;font-weight:700}.source-badge{background:#f1f5f9;color:#475569}.status-pill.active{background:#dcfce7;color:#15803d}.status-pill.expired{background:#f1f5f9;color:#94a3b8}.ledger-list{border-top:1px solid #f1f5f9}.ledger-row{border-bottom:1px solid #f1f5f9}.ledger-main{width:100%;border:0;background:transparent;display:grid;grid-template-columns:38px 1fr auto 18px;align-items:center;gap:12px;padding:13px 4px;text-align:left;cursor:pointer}.ledger-main:hover{background:#fafbff}.ledger-icon{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:#f1f5f9;color:#64748b}.ledger-icon.type-consume{background:#fff7ed;color:#ea580c}.ledger-icon.type-recharge,.ledger-icon.type-grant{background:#ecfdf5;color:#059669}.ledger-copy{display:flex;flex-direction:column;gap:3px}.ledger-copy strong{font-size:.84rem}.ledger-copy small,.ledger-amount small{font-size:.7rem;color:#94a3b8}.ledger-amount{font-size:.92rem;font-weight:800;text-align:right;display:flex;flex-direction:column}.ledger-amount.positive{color:#16a34a}.ledger-amount.negative{color:#dc2626}.ledger-amount.zero{color:#64748b}.expand-icon{font-size:.68rem;color:#94a3b8}.usage-detail{background:#f8fafc;border-radius:10px;margin:0 4px 12px;padding:13px}.usage-block+.usage-block{margin-top:12px}.usage-meta{display:flex;gap:12px;flex-wrap:wrap;color:#64748b;font-size:.7rem;margin-bottom:9px}.model-usage-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}.model-usage-card{background:#fff;border:1px solid #e2e8f0;border-radius:9px;padding:10px;display:flex;flex-direction:column;gap:3px;font-size:.71rem;color:#64748b}.model-usage-card strong{font-size:.78rem;color:#334155}.model-usage-card b{color:#4f46e5;margin-top:3px}.pagination{display:flex;justify-content:center;align-items:center;gap:12px;margin-top:15px;font-size:.78rem;color:#64748b}.pagination button{width:30px;height:30px;border:1px solid #dbe2ea;background:#fff;border-radius:7px}.pagination button:disabled{opacity:.4}.contact-modal-backdrop{position:fixed;inset:0;z-index:1200;display:grid;place-items:center;padding:20px;background:rgba(15,23,42,.55);backdrop-filter:blur(4px)}.contact-modal{position:relative;width:min(620px,100%);max-height:calc(100vh - 40px);overflow:auto;border-radius:20px;background:#fff;padding:26px;box-shadow:0 24px 70px rgba(15,23,42,.3)}.modal-close{position:absolute;right:16px;top:16px;width:34px;height:34px;border:0;border-radius:9px;background:#f1f5f9;color:#64748b;cursor:pointer}.modal-heading{display:flex;align-items:flex-start;gap:13px;padding-right:35px}.modal-heading h2{margin:4px 0;font-size:1.25rem}.modal-heading p:last-child{margin:0;color:#64748b;font-size:.8rem}.modal-icon{flex:0 0 42px;height:42px;display:grid;place-items:center;border-radius:12px;background:#ede9fe;color:#6d28d9}.contact-layout{display:grid;grid-template-columns:160px 1fr;gap:16px;margin-top:20px}.qr-panel{border:1px solid #e2e8f0;border-radius:12px;padding:10px;text-align:center}.qr-panel img{width:138px;height:138px;object-fit:contain;display:block}.qr-panel span,.qr-panel small{display:block;margin-top:7px;font-size:.68rem;color:#64748b}.contact-details{display:flex;flex-direction:column;gap:9px}.contact-row{display:grid;grid-template-columns:86px 1fr auto;gap:8px;align-items:center;border:1px solid #e2e8f0;border-radius:10px;padding:10px}.contact-row>span{font-size:.7rem;color:#64748b}.contact-row strong{font-size:.78rem;overflow-wrap:anywhere}.contact-row button{border:0;background:#eef2ff;color:#4f46e5;border-radius:7px;padding:5px 8px;font-size:.68rem;cursor:pointer}.contact-row.no-action{grid-template-columns:86px 1fr}.default-contact-state{display:flex;align-items:flex-start;gap:10px;margin-top:18px;padding:13px 14px;border:1px solid #fde68a;border-radius:11px;background:#fffbeb;color:#92400e}.default-contact-state div{display:flex;flex-direction:column;gap:3px}.default-contact-state span{font-size:.72rem;line-height:1.5}.consult-copy-box{margin-top:16px;padding:14px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0}.consult-copy-box>div{display:flex;justify-content:space-between;gap:12px}.consult-copy-box span{font-size:.7rem;color:#64748b}.consult-copy-box p{white-space:pre-line;margin:10px 0;font-size:.8rem;color:#334155;line-height:1.6}.consult-copy-box button{border:0;border-radius:8px;background:#4f46e5;color:#fff;padding:8px 11px;font-size:.74rem;font-weight:700;cursor:pointer}.consult-copy-box button i{margin-right:6px}.security-notice{display:flex;align-items:flex-start;gap:7px;margin:13px 0 0;color:#92400e;font-size:.7rem;line-height:1.5}.security-notice i{margin-top:2px}@media(max-width:850px){.summary-grid,.plan-grid{grid-template-columns:1fr}.billing-shell{width:min(100% - 24px,1180px);padding-top:20px}.page-heading{align-items:flex-start}.section-card{padding:17px}.section-heading{align-items:flex-start;flex-direction:column;gap:5px}}@media(max-width:560px){.page-heading{flex-direction:column}.redeem-form{flex-direction:column}.redeem-form button{padding:10px}.ledger-main{grid-template-columns:36px 1fr auto}.expand-icon{display:none}.summary-value{font-size:1.7rem}.contact-modal{padding:20px}.contact-layout{grid-template-columns:1fr}.qr-panel{width:160px;margin:0 auto}.contact-row{grid-template-columns:80px 1fr auto}.consult-copy-box>div{flex-direction:column;gap:3px}}
.contact-layout.without-qr{grid-template-columns:minmax(0,1fr)}
.contact-layout.without-qr .contact-details{grid-column:1;width:100%}
.contact-row{grid-template-columns:104px minmax(0,1fr) auto;min-width:0;padding:12px 14px}
.contact-row.no-action{grid-template-columns:104px minmax(0,1fr)}
.contact-row strong{min-width:0;line-height:1.45;word-break:break-word}
.qr-preview-trigger{display:block;width:138px;height:138px;padding:0;border:0;border-radius:7px;background:#fff;cursor:zoom-in;overflow:hidden}
.qr-preview-trigger img{width:100%;height:100%;object-fit:contain;display:block}
.qr-panel small i{margin-right:4px}
.qr-preview-backdrop{position:fixed;inset:0;z-index:1300;display:grid;place-items:center;padding:24px;background:rgba(15,23,42,.78);backdrop-filter:blur(7px)}
.qr-preview-dialog{position:relative;width:min(560px,calc(100vw - 48px));padding:28px;border-radius:20px;background:#fff;box-shadow:0 28px 80px rgba(0,0,0,.38);text-align:center}
.qr-preview-dialog img{display:block;width:min(460px,100%);aspect-ratio:1;object-fit:contain;margin:0 auto;border-radius:12px;background:#fff}
.qr-preview-dialog p{margin:16px 36px 0;color:#475569;font-size:.84rem}
.qr-preview-close{position:absolute;top:12px;right:12px;z-index:1;width:38px;height:38px;border:0;border-radius:10px;background:#f1f5f9;color:#64748b;cursor:pointer}
.qr-preview-close:hover{background:#e2e8f0;color:#334155}
@media(max-width:560px){.contact-row,.contact-row.no-action{grid-template-columns:1fr auto}.contact-row>span{grid-column:1}.contact-row strong{grid-column:1/-1;grid-row:2}.contact-row button{grid-column:2;grid-row:1}}
</style>
