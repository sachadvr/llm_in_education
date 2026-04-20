<template>
  <main class="mx-auto flex min-h-screen w-full max-w-[420px] flex-col items-center justify-center px-6">
    <div class="w-full glass-card rounded-3xl p-8">
      <div class="traffic-lights"><span style="background:#ff5f57"></span><span style="background:#febc2e"></span><span style="background:#28c840"></span></div>
      <div class="mb-8 text-center">
        <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-white text-slate-900 text-lg font-semibold">
          λ
        </div>
        <h1 class="text-2xl font-semibold text-white/90">Connexion</h1>
        <p class="mt-2 text-sm text-white/50">Connectez-vous pour acceder a votre progression</p>
      </div>

      <form @submit.prevent="handleLogin" class="space-y-4">
        <div>
          <label class="mb-1.5 block text-xs font-medium text-white/60">Nom d'utilisateur</label>
          <input
            v-model="username"
            type="text"
            required
            class="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/80 placeholder:text-white/30 focus:border-white/30 focus:outline-none"
            placeholder="votre_nom"
          />
        </div>

        <div>
          <label class="mb-1.5 block text-xs font-medium text-white/60">Mot de passe</label>
          <input
            v-model="password"
            type="password"
            required
            class="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/80 placeholder:text-white/30 focus:border-white/30 focus:outline-none"
            placeholder="••••••••"
          />
        </div>

        <div v-if="error" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {{ error }}
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full rounded-xl border border-white/80 bg-white py-3 text-sm font-medium text-black transition hover:bg-white/90 disabled:opacity-50"
        >
          <span v-if="loading">Connexion...</span>
          <span v-else>Se connecter</span>
        </button>
      </form>

      <p class="mt-6 text-center text-sm text-white/50">
        Pas encore de compte?
        <router-link to="/register" class="text-white/80 underline hover:text-white">S'inscrire</router-link>
      </p>

      <router-link to="/" class="mt-4 block text-center text-xs text-white/30 hover:text-white/50">
        Retour a l'accueil
      </router-link>
    </div><!-- end glass-card -->
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const { login } = useAuth()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const handleLogin = async () => {
  error.value = ''
  loading.value = true
  try {
    await login(username.value, password.value)
    router.push('/')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>
