<template>
  <div class="relative min-h-screen overflow-x-hidden" style="background: var(--bg); color: var(--text)">

    <!-- Hero glow -->
    <div class="pointer-events-none absolute left-1/2 top-0 h-[500px] w-[800px] -translate-x-1/2 hero-glow" style="z-index:0"></div>

    <!-- API Status pill (fixed top-right) -->
    <div class="fixed top-5 right-5 z-50 rounded-2xl border px-4 py-2 text-sm transition-all"
      :class="apiStatusOk
        ? 'border-green-400/30 bg-green-500/10 text-green-200'
        : 'border-rose-400/30 bg-rose-500/10 text-rose-200'"
    >
      <span style="color: rgba(255,255,255,0.4)">API:</span>
      <span class="ml-1.5 font-medium">{{ apiStatusShort }}</span>
    </div>

    <!-- Header -->
    <header class="relative z-10 mx-auto w-full max-w-[1160px] px-6 pt-10 pb-2">
      <div class="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">

        <!-- Brand -->
        <div class="flex items-center gap-3">
          <div class="h-10 w-10 rounded-xl bg-white text-slate-900 grid place-items-center font-semibold text-sm tracking-tight select-none">λ</div>
          <div>
            <p class="text-sm font-semibold" style="color: var(--text)">ALAO</p>
            <p class="text-xs" style="color: var(--text-dim2)">Prototype mémoire</p>
          </div>
        </div>

        <!-- Nav -->
        <nav class="flex items-center gap-1 flex-wrap">
          <router-link
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-medium transition-all"
            :class="$route.path === item.to ? 'border' : 'hover:bg-white/5'"
            :style="$route.path === item.to
              ? `border-color: ${item.color}30; background: ${item.color}12; color: ${item.color}`
              : `color: var(--text-dim)`"
          >
            <span class="h-1.5 w-1.5 rounded-full flex-shrink-0" :style="`background: ${item.color}`"></span>
            {{ item.label }}
          </router-link>
        </nav>

        <!-- Auth -->
        <div class="flex items-center gap-2">
          <div v-if="isLoggedIn && user"
            class="flex items-center gap-1.5 text-xs rounded-xl px-3 py-1.5"
            style="border: 1px solid var(--border); background: var(--bg-card); color: var(--text-dim)"
          >
            <span class="h-1.5 w-1.5 rounded-full flex-shrink-0" style="background: var(--success)"></span>
            {{ user.display_name || user.username }}
          </div>
          <router-link v-if="!isLoggedIn" to="/login"
            class="text-xs rounded-xl px-3 py-1.5 transition hover:bg-white/5"
            style="border: 1px solid var(--border); color: var(--text-dim)"
          >connexion</router-link>
          <button v-if="isLoggedIn" @click="handleLogout"
            class="text-xs rounded-xl px-3 py-1.5 transition hover:bg-white/5"
            style="border: 1px solid var(--border); color: var(--text-dim)"
          >déconnexion</button>
        </div>

      </div>
    </header>

    <div class="relative z-10">
      <router-view v-slot="{ Component }">
        <component :is="Component" :apiStatusLabel="apiStatusLabel" :apiStatusClass="apiStatusClass" />
      </router-view>
    </div>

  </div>
</template>

<script setup>
import { computed, onMounted, provide } from 'vue'
import { useApiStatus } from './composables/useApiStatus'
import { useAuth } from './composables/useAuth'
import { apiConfig } from './config/api'

const { apiStatus, apiStatusLabel, apiStatusClass, checkHealth } = useApiStatus()
const { user, isLoggedIn, logout, checkSession } = useAuth()

const apiStatusOk = computed(() => apiStatus.value === 'ok')
const apiStatusShort = computed(() => apiStatusOk.value ? 'OK' : 'OFFLINE')

const navItems = [
  { to: '/',            label: 'Exercices',   color: '#4ADE80' },
  { to: '/quiz',        label: 'QCM',         color: '#FB923C' },
  { to: '/progression', label: 'Progression', color: '#2DD4BF' },
  { to: '/analytics',   label: 'Analytics',   color: '#818CF8' },
  { to: '/benchmark',   label: 'Benchmark',   color: '#F87171' },
]

const setApiStatus = (val) => { apiStatus.value = val }
provide('setApiStatus', setApiStatus)

const handleLogout = async () => {
  try {
    await fetch(`${apiConfig.baseUrl}${apiConfig.endpoints.logout}`, { method: 'POST', credentials: 'include' })
  } catch {}
  await logout()
}

onMounted(() => {
  checkHealth()
  checkSession()
})
</script>
