<template>
  <main class="mx-auto flex min-h-screen w-full max-w-[420px] flex-col items-center justify-center px-6">
    <div class="w-full glass-card rounded-3xl p-8">
      <div class="traffic-lights"><span style="background:#ff5f57"></span><span style="background:#febc2e"></span><span style="background:#28c840"></span></div>
      <div class="mb-8 text-center">
        <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-white text-slate-900 text-lg font-semibold">
          λ
        </div>
        <h1 class="text-2xl font-semibold text-white/90">Inscription</h1>
        <p class="mt-2 text-sm text-white/50">Creez un compte pour suivre votre progression</p>
      </div>

      <form @submit.prevent="handleRegister" class="space-y-4">
        <div>
          <label class="mb-1.5 block text-xs font-medium text-white/60">Nom d'utilisateur</label>
          <input
            v-model="username"
            type="text"
            required
            minlength="3"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/80 placeholder:text-white/30 focus:border-white/30 focus:outline-none"
            placeholder="votre_nom"
          />
        </div>

        <div>
          <label class="mb-1.5 block text-xs font-medium text-white/60">Nom d'affichage (optionnel)</label>
          <input
            v-model="displayName"
            type="text"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/80 placeholder:text-white/30 focus:border-white/30 focus:outline-none"
            placeholder="Votre nom"
          />
        </div>

        <div>
          <label class="mb-1.5 block text-xs font-medium text-white/60">Mot de passe</label>
          <input
            v-model="password"
            type="password"
            required
            minlength="4"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/80 placeholder:text-white/30 focus:border-white/30 focus:outline-none"
            placeholder="••••••••"
          />
          <p class="mt-1 text-xs text-white/30">Minimum 4 caracteres</p>
        </div>

        <div v-if="error" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {{ error }}
        </div>

        <div v-if="success" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
          {{ success }}
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full rounded-xl border border-white/80 bg-white py-3 text-sm font-medium text-black transition hover:bg-white/90 disabled:opacity-50"
        >
          <span v-if="loading">Inscription...</span>
          <span v-else>S'inscrire</span>
        </button>
      </form>

      <p class="mt-6 text-center text-sm text-white/50">
        Deja un compte?
        <router-link to="/login" class="text-white/80 underline hover:text-white">Se connecter</router-link>
      </p>

      <router-link to="/" class="mt-4 block text-center text-xs text-white/30 hover:text-white/50">
        Retour a l'accueil
      </router-link>
    </div>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const router = useRouter()
const { register, login } = useAuth()

const username = ref('')
const displayName = ref('')
const password = ref('')
const error = ref('')
const success = ref('')
const loading = ref(false)

const handleRegister = async () => {
  error.value = ''
  success.value = ''
  loading.value = true

  try {
    await register(username.value, password.value, displayName.value)
    success.value = 'Compte cree! Connexion en cours...'

    // Auto-login after registration
    setTimeout(async () => {
      try {
        await login(username.value, password.value)
        router.push('/')
      } catch (e) {
        error.value = 'Inscription reussie mais connexion automatique echouee. Veuillez vous connecter manuellement.'
      }
    }, 1000)
  } catch (e) {
    error.value = e.message
    loading.value = false
  }
}
</script>
