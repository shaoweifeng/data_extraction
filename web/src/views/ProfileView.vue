<template>
  <div class="profile-page">
    <!-- 顶部导航栏 -->
    <AppHeader ref="headerRef" />

    <div class="profile-body">
      <!-- ── 左侧：用户信息卡片 ────────────────────── -->
      <aside class="profile-sidebar">
        <div class="user-card">
          <div class="user-avatar-lg">
            {{ auth.user?.username?.charAt(0)?.toUpperCase() || 'U' }}
          </div>
          <div class="user-card-info">
            <div class="user-card-name">{{ auth.user?.username }}</div>
            <div class="user-card-role" :class="roleClass">{{ roleLabel }}</div>
          </div>
        </div>

        <!-- 余额概览 -->
        <div class="balance-card" v-if="billing">
          <div class="balance-main">
            <span class="balance-num">{{ billing.is_unlimited ? '∞' : billing.balance }}</span>
            <span class="balance-unit">credits</span>
          </div>
          <div class="balance-sub-row" v-if="!billing.is_unlimited">
            <span class="balance-sub-item"><i class="fas fa-gift"></i> 累计赠送 {{ billing.total_granted }}</span>
            <span class="balance-sub-item"><i class="fas fa-fire"></i> 累计消耗 {{ billing.total_consumed }}</span>
          </div>
          <div class="balance-sub-row" v-else>
            <span class="balance-sub-item"><i class="fas fa-crown"></i> 管理员无限额度</span>
          </div>
          <div class="balance-ratio-tip">1 credit ≈ {{ billing.credit_token_ratio }} tokens</div>
        </div>
        <div class="balance-card balance-loading" v-else-if="billingLoading">
          <i class="fas fa-spinner fa-spin"></i> 加载中…
        </div>

        <!-- 并发档位 -->
        <div class="concurrency-card" v-if="auth.user?.profile">
          <div class="cc-label"><i class="fas fa-tachometer-alt"></i> 并发档位</div>
          <div class="cc-val">{{ auth.user.profile.concurrency_limit || 2 }} 线程</div>
          <div class="cc-hint">AI 筛选时最多同时使用的线程数</div>
        </div>

        <button class="back-btn" @click="router.push('/')">
          <i class="fas fa-arrow-left"></i> 返回项目列表
        </button>
      </aside>

      <!-- ── 右侧：内容区 ─────────────────────────── -->
      <main class="profile-main">

        <!-- 兑换码充值 -->
        <section class="profile-section">
          <h2 class="section-title"><i class="fas fa-ticket-alt"></i> 兑换码充值</h2>
          <div class="redeem-box">
            <input
              v-model="redeemCode"
              class="redeem-input"
              placeholder="请输入兑换码，如 FREE-XXXX-XXXX"
              maxlength="32"
              :disabled="redeemLoading"
              @keyup.enter="submitRedeem"
            />
            <button
              class="redeem-btn"
              :disabled="!redeemCode.trim() || redeemLoading"
              @click="submitRedeem"
            >
              <i class="fas fa-spinner fa-spin" v-if="redeemLoading"></i>
              <i class="fas fa-check" v-else></i>
              {{ redeemLoading ? '处理中…' : '立即兑换' }}
            </button>
          </div>
          <div class="redeem-result redeem-ok" v-if="redeemSuccess">
            <i class="fas fa-check-circle"></i>
            兑换成功！获得 <b>{{ redeemSuccess.credits_added }}</b> credits，
            当前余额 <b>{{ redeemSuccess.new_balance }}</b> credits
          </div>
          <div class="redeem-result redeem-err" v-if="redeemError">
            <i class="fas fa-exclamation-circle"></i> {{ redeemError }}
          </div>
        </section>

        <!-- 交易流水 -->
        <section class="profile-section">
          <h2 class="section-title"><i class="fas fa-list-alt"></i> 交易流水</h2>

          <div class="txn-loading" v-if="txnLoading">
            <i class="fas fa-spinner fa-spin"></i> 加载中…
          </div>

          <template v-else>
            <div class="txn-empty" v-if="!txnData || txnData.results.length === 0">
              <i class="fas fa-inbox"></i> 暂无交易记录
            </div>

            <table class="txn-table" v-else>
              <thead>
                <tr>
                  <th>类型</th>
                  <th>金额</th>
                  <th>余额</th>
                  <th>备注</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in txnData.results" :key="t.id">
                  <td>
                    <span class="txn-type-badge" :class="`txn-${t.txn_type}`">
                      {{ t.txn_type_display }}
                    </span>
                  </td>
                  <td :class="t.amount === 0 ? 'txn-amount-zero' : t.amount > 0 ? 'txn-amount-pos' : 'txn-amount-neg'">
                    {{ t.amount === 0 ? '—' : (t.amount > 0 ? '+' : '') + t.amount }}
                  </td>
                  <td class="txn-balance-after">{{ t.balance_after }}</td>
                  <td class="txn-note">{{ t.note || '—' }}</td>
                  <td class="txn-time">{{ formatTime(t.created_at) }}</td>
                </tr>
              </tbody>
            </table>

            <!-- 分页 -->
            <div class="txn-pagination" v-if="txnData && txnData.total_pages > 1">
              <button
                class="page-btn"
                :disabled="txnPage <= 1"
                @click="loadTransactions(txnPage - 1)"
              >
                <i class="fas fa-chevron-left"></i>
              </button>
              <span class="page-info">
                第 {{ txnPage }} / {{ txnData.total_pages }} 页
                （共 {{ txnData.count }} 条）
              </span>
              <button
                class="page-btn"
                :disabled="txnPage >= txnData.total_pages"
                @click="loadTransactions(txnPage + 1)"
              >
                <i class="fas fa-chevron-right"></i>
              </button>
            </div>
          </template>
        </section>

      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppHeader from '@/components/layout/AppHeader.vue'
import http from '@/api/http'

const router    = useRouter()
const auth      = useAuthStore()
const headerRef = ref(null)

// ── 角色展示 ─────────────────────────────────────────────
const roleLabel = computed(() => {
  const p = auth.user?.profile
  if (auth.user?.is_superuser) return '超级管理员'
  if (p?.role === 'admin') return '管理员'
  return '普通用户'
})
const roleClass = computed(() => {
  if (auth.user?.is_superuser || auth.user?.profile?.role === 'admin') return 'role-admin'
  return 'role-user'
})

// ── 余额 ─────────────────────────────────────────────────
const billing        = ref(null)
const billingLoading = ref(false)

async function loadBilling() {
  billingLoading.value = true
  try {
    const res  = await http.get('/billing/balance/')
    billing.value = res.data
  } catch (e) {
    console.warn('balance load failed', e)
  } finally {
    billingLoading.value = false
  }
}

// ── 兑换码 ───────────────────────────────────────────────
const redeemCode    = ref('')
const redeemLoading = ref(false)
const redeemSuccess = ref(null)
const redeemError   = ref('')

async function submitRedeem() {
  const code = redeemCode.value.trim()
  if (!code || redeemLoading.value) return

  redeemLoading.value = true
  redeemSuccess.value = null
  redeemError.value   = ''

  try {
    const res = await http.post('/billing/redeem/', { code })
    redeemSuccess.value = res.data
    redeemCode.value    = ''
    // 刷新余额和流水（同时更新 Header 里的余额展示）
    await loadBilling()
    await loadTransactions(1)
    headerRef.value?.refreshBalance()
  } catch (err) {
    const msg = err.response?.data?.error || '兑换失败，请检查兑换码是否正确'
    redeemError.value = msg
  } finally {
    redeemLoading.value = false
  }
}

// ── 交易流水 ─────────────────────────────────────────────
const txnData    = ref(null)
const txnLoading = ref(false)
const txnPage    = ref(1)
const PAGE_SIZE  = 10

async function loadTransactions(page = 1) {
  txnLoading.value = true
  txnPage.value    = page
  try {
    const res = await http.get('/billing/transactions/', {
      params: { page, page_size: PAGE_SIZE },
    })
    txnData.value = res.data
  } catch (e) {
    console.warn('transactions load failed', e)
  } finally {
    txnLoading.value = false
  }
}

// ── 工具函数 ─────────────────────────────────────────────
function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ── 初始化 ───────────────────────────────────────────────
onMounted(async () => {
  await loadBilling()
  await loadTransactions(1)
})
</script>

<style scoped>
/* ── 整体布局 ── */
.profile-page {
  min-height: 100vh;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
}
.profile-body {
  flex: 1;
  display: flex;
  gap: 24px;
  padding: 24px;
  max-width: 1100px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* ── 左侧侧栏 ── */
.profile-sidebar {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 用户卡片 */
.user-card {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.user-avatar-lg {
  width: 56px; height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  font-size: 1.5rem; font-weight: 700; color: #fff;
}
.user-card-info { text-align: center; }
.user-card-name { font-size: 1rem; font-weight: 700; color: #1e293b; }
.user-card-role {
  display: inline-block;
  margin-top: 4px;
  font-size: 0.72rem; font-weight: 600;
  padding: 2px 8px; border-radius: 999px;
}
.role-admin { background: #ede9fe; color: #7c3aed; }
.role-user  { background: #f0fdf4; color: #16a34a; }

/* 余额卡片 */
.balance-card {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 12px;
  padding: 16px;
  color: #fff;
}
.balance-loading { display: flex; align-items: center; gap: 8px; font-size: 0.85rem; }
.balance-main { display: flex; align-items: baseline; gap: 4px; margin-bottom: 10px; }
.balance-num { font-size: 2rem; font-weight: 800; }
.balance-unit { font-size: 0.85rem; opacity: 0.85; }
.balance-sub-row { display: flex; gap: 12px; flex-wrap: wrap; }
.balance-sub-item { font-size: 0.75rem; opacity: 0.9; display: flex; align-items: center; gap: 4px; }
.balance-ratio-tip { font-size: 0.7rem; opacity: 0.7; margin-top: 8px; }

/* 并发档位 */
.concurrency-card {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 14px 16px;
}
.cc-label { font-size: 0.78rem; color: #64748b; margin-bottom: 4px; display: flex; align-items: center; gap: 5px; }
.cc-val   { font-size: 1.25rem; font-weight: 700; color: #1e293b; }
.cc-hint  { font-size: 0.7rem; color: #94a3b8; margin-top: 3px; }

/* 返回按钮 */
.back-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px;
  border: 1px solid #e2e8f0; border-radius: 8px;
  background: #fff; color: #64748b;
  font-size: 0.82rem; cursor: pointer;
  transition: all 0.15s;
}
.back-btn:hover { background: #f1f5f9; color: #374151; border-color: #c7d2fe; }

/* ── 右侧主内容 ── */
.profile-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

.profile-section {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  padding: 20px 24px;
}
.section-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 16px 0;
  display: flex; align-items: center; gap: 8px;
}
.section-title i { color: #6366f1; }

/* 兑换码 */
.redeem-box {
  display: flex; gap: 10px;
}
.redeem-input {
  flex: 1;
  padding: 9px 14px;
  border: 1px solid #e2e8f0; border-radius: 8px;
  font-size: 0.9rem; color: #1e293b;
  outline: none; transition: border-color 0.15s;
  font-family: 'Courier New', monospace; letter-spacing: 1px;
}
.redeem-input:focus { border-color: #6366f1; }
.redeem-input:disabled { background: #f8fafc; color: #94a3b8; }
.redeem-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 9px 20px;
  background: #6366f1; color: #fff;
  border: none; border-radius: 8px;
  font-size: 0.88rem; font-weight: 600; cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}
.redeem-btn:hover:not(:disabled) { background: #4f46e5; }
.redeem-btn:disabled { background: #c7d2fe; cursor: not-allowed; }
.redeem-result {
  margin-top: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  display: flex; align-items: center; gap: 6px;
}
.redeem-ok  { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
.redeem-err { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }

/* 流水表格 */
.txn-loading, .txn-empty {
  text-align: center;
  color: #94a3b8;
  font-size: 0.88rem;
  padding: 24px 0;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.txn-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.txn-table th {
  text-align: left;
  padding: 8px 10px;
  color: #64748b;
  border-bottom: 1px solid #e2e8f0;
  font-weight: 600;
  font-size: 0.8rem;
}
.txn-table td {
  padding: 9px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #374151;
}
.txn-table tr:last-child td { border-bottom: none; }
.txn-table tr:hover td { background: #f8fafc; }

.txn-type-badge {
  display: inline-block;
  padding: 2px 8px; border-radius: 999px;
  font-size: 0.72rem; font-weight: 600;
}
.txn-grant       { background: #ecfdf5; color: #065f46; }
.txn-recharge    { background: #eff6ff; color: #1d4ed8; }
.txn-consume     { background: #fff7ed; color: #9a3412; }
.txn-refund      { background: #fdf4ff; color: #6b21a8; }
.txn-adjust      { background: #fafafa; color: #374151; border: 1px solid #e5e7eb; }
.txn-admin_usage { background: #f0f9ff; color: #0369a1; border: 1px dashed #7dd3fc; }

.txn-amount-pos  { color: #16a34a; font-weight: 600; }
.txn-amount-neg  { color: #dc2626; font-weight: 600; }
.txn-amount-zero { color: #94a3b8; font-weight: 500; }
.txn-balance-after { color: #6366f1; font-weight: 600; }
.txn-note { color: #94a3b8; font-size: 0.8rem; max-width: 180px; }
.txn-time { color: #94a3b8; font-size: 0.78rem; white-space: nowrap; }

/* 分页 */
.txn-pagination {
  display: flex; align-items: center; gap: 12px;
  justify-content: center;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}
.page-btn {
  width: 30px; height: 30px;
  border: 1px solid #e2e8f0; border-radius: 6px;
  background: #fff; color: #374151;
  cursor: pointer; font-size: 0.75rem;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.page-btn:hover:not(:disabled) { background: #f1f5f9; border-color: #c7d2fe; }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-info { font-size: 0.82rem; color: #64748b; }
</style>
