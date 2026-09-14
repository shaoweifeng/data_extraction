<template>
  <header class="landing-header">
    <div class="landing-header-inner">
      <RouterLink class="landing-brand" to="/" aria-label="科研 Meta 平台首页">
        <span class="landing-brand-mark"><i class="fas fa-flask"></i></span>
        <span class="landing-brand-copy">
          <strong>科研 Meta 平台</strong>
          <small>循证研究工作流</small>
        </span>
      </RouterLink>

      <button
        class="landing-menu-button"
        type="button"
        :aria-expanded="menuOpen"
        aria-controls="landing-navigation"
        aria-label="打开首页导航"
        @click="menuOpen = !menuOpen"
      >
        <i :class="menuOpen ? 'fas fa-times' : 'fas fa-bars'"></i>
      </button>

      <div id="landing-navigation" class="landing-navigation" :class="{ open: menuOpen }">
        <nav aria-label="首页导航">
          <a href="#capabilities" @click="closeMenu">核心能力</a>
          <a href="#workflow" @click="closeMenu">工作流程</a>
          <a href="#reliability" @click="closeMenu">可靠性</a>
        </nav>
        <div class="landing-actions">
          <RouterLink v-if="!user" class="landing-login" to="/login" @click="closeMenu">
            登录
          </RouterLink>
          <RouterLink class="landing-start" :to="primaryTarget" @click="closeMenu">
            {{ user ? '进入工作台' : '免费开始' }}
            <i class="fas fa-arrow-right"></i>
          </RouterLink>
          <div v-if="user" ref="accountMenu" class="landing-account">
            <button
              class="landing-account-trigger"
              type="button"
              :aria-expanded="accountOpen"
              aria-haspopup="menu"
              aria-label="打开个人账户菜单"
              @click="accountOpen = !accountOpen"
            >
              <span class="landing-avatar">{{ userInitial }}</span>
              <span class="landing-username">{{ user.username }}</span>
              <i class="fas fa-chevron-down"></i>
            </button>
            <div v-if="accountOpen" class="landing-account-menu" role="menu">
              <div class="account-summary">
                <span class="landing-avatar large">{{ userInitial }}</span>
                <div><small>当前账户</small><strong>{{ user.username }}</strong></div>
              </div>
              <RouterLink :to="{ name: 'Profile' }" role="menuitem" @click="closeAllMenus">
                <i class="fas fa-user-gear"></i>个人中心
              </RouterLink>
              <RouterLink :to="{ name: 'Home' }" role="menuitem" @click="closeAllMenus">
                <i class="fas fa-folder-open"></i>我的项目
              </RouterLink>
              <button type="button" role="menuitem" @click="logout">
                <i class="fas fa-arrow-right-from-bracket"></i>退出登录
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({
  user: { type: Object, default: null },
})
const emit = defineEmits(['logout'])

const menuOpen = ref(false)
const accountOpen = ref(false)
const accountMenu = ref(null)
const userInitial = computed(() => props.user?.username?.charAt(0)?.toUpperCase() || 'U')
const primaryTarget = computed(() => (
  props.user ? { name: 'Home' } : { name: 'Login', query: { mode: 'register' } }
))

function closeMenu() {
  menuOpen.value = false
}

function closeAllMenus() {
  menuOpen.value = false
  accountOpen.value = false
}

function handleDocumentClick(event) {
  if (accountOpen.value && !accountMenu.value?.contains(event.target)) accountOpen.value = false
}

function handleEscape(event) {
  if (event.key === 'Escape') closeAllMenus()
}

function logout() {
  closeAllMenus()
  emit('logout')
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleEscape)
})
onUnmounted(() => {
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleEscape)
})
</script>

<style scoped>
.landing-header {
  position: sticky;
  top: 0;
  z-index: 50;
  border-bottom: 1px solid rgba(226, 232, 240, 0.82);
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(18px);
}
.landing-header-inner {
  width: min(1180px, calc(100% - 40px));
  height: 68px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 30px;
}
.landing-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #1e293b;
  text-decoration: none;
  flex-shrink: 0;
}
.landing-brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.28);
}
.landing-brand-copy { display: flex; flex-direction: column; line-height: 1.12; }
.landing-brand-copy strong { font-size: 0.95rem; letter-spacing: -0.01em; }
.landing-brand-copy small { margin-top: 3px; color: #94a3b8; font-size: 0.64rem; letter-spacing: 0.08em; }
.landing-navigation { display: flex; align-items: center; flex: 1; }
.landing-navigation nav { display: flex; gap: 28px; margin: 0 auto; }
.landing-navigation nav a,
.landing-login {
  color: #64748b;
  font-size: 0.84rem;
  font-weight: 600;
  text-decoration: none;
  transition: color 0.18s ease;
}
.landing-navigation nav a:hover,
.landing-login:hover { color: #4f46e5; }
.landing-actions { display: flex; align-items: center; gap: 17px; }
.landing-start {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 15px;
  border-radius: 10px;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #7c3aed);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.2);
  font-size: 0.82rem;
  font-weight: 700;
  text-decoration: none;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.landing-start:hover { transform: translateY(-1px); box-shadow: 0 11px 24px rgba(99, 102, 241, 0.3); }
.landing-account { position: relative; }
.landing-account-trigger {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 9px 4px 5px;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  color: #475569;
  background: #fff;
  cursor: pointer;
}
.landing-account-trigger:hover { border-color: #c7d2fe; background: #fafaff; }
.landing-account-trigger > i { color: #94a3b8; font-size: 0.62rem; }
.landing-avatar { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; color: #fff; background: linear-gradient(135deg, #6366f1, #8b5cf6); font-size: 0.72rem; font-weight: 800; }
.landing-avatar.large { width: 34px; height: 34px; flex: 0 0 auto; }
.landing-username { max-width: 92px; overflow: hidden; color: #334155; font-size: 0.76rem; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.landing-account-menu {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  width: 205px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 18px 45px rgba(30, 41, 59, 0.15);
}
.account-summary { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; padding: 9px 8px 12px; border-bottom: 1px solid #f1f5f9; }
.account-summary small { display: block; color: #94a3b8; font-size: 0.61rem; }
.account-summary strong { display: block; max-width: 125px; margin-top: 2px; overflow: hidden; color: #334155; font-size: 0.75rem; text-overflow: ellipsis; white-space: nowrap; }
.landing-account-menu a,
.landing-account-menu button { width: 100%; box-sizing: border-box; display: flex; align-items: center; gap: 10px; padding: 9px 10px; border: 0; border-radius: 8px; color: #475569; background: transparent; font: inherit; font-size: 0.74rem; font-weight: 600; text-align: left; text-decoration: none; cursor: pointer; }
.landing-account-menu a:hover { color: #4f46e5; background: #eef2ff; }
.landing-account-menu button:hover { color: #dc2626; background: #fef2f2; }
.landing-account-menu i { width: 14px; color: #94a3b8; text-align: center; }
.landing-menu-button {
  display: none;
  margin-left: auto;
  width: 38px;
  height: 38px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  color: #475569;
}
@media (max-width: 760px) {
  .landing-header-inner { width: min(100% - 28px, 1180px); height: 62px; }
  .landing-menu-button { display: grid; place-items: center; }
  .landing-navigation {
    display: none;
    position: absolute;
    top: 62px;
    left: 14px;
    right: 14px;
    padding: 18px;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.98);
    box-shadow: 0 18px 45px rgba(30, 41, 59, 0.14);
  }
  .landing-navigation.open { display: block; }
  .landing-navigation nav { flex-direction: column; gap: 4px; }
  .landing-navigation nav a { padding: 10px 8px; }
  .landing-actions { margin-top: 12px; padding-top: 14px; border-top: 1px solid #f1f5f9; }
  .landing-start { margin-left: auto; }
  .landing-account { min-width: 170px; }
  .landing-account-trigger { width: 100%; }
  .landing-account-menu { position: static; width: auto; margin-top: 8px; box-shadow: none; }
}
@media (max-width: 430px) {
  .landing-brand-copy small { display: none; }
}
</style>
