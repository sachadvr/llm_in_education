import { ref, computed } from 'vue'
import { apiConfig } from '../config/api.js'

export function useApiStatus() {
  const apiStatus = ref('checking')
  const useOllama = ref(true)
  const toggleLoading = ref(false)

  const apiStatusLabel = computed(() => {
    if (apiStatus.value === 'ok') return 'Ollama pret'
    if (apiStatus.value === 'fail') return 'FAILURE'
    return 'Verification...'
  })

  const apiStatusClass = computed(() => {
    if (apiStatus.value === 'ok') {
      return 'fixed top-5 right-5 z-50 rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/60'
    }
    if (apiStatus.value === 'fail') {
      return 'fixed top-5 right-5 z-50 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200'
    }
    return 'fixed top-5 right-5 z-50 rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/60'
  })

  const toggleLabel = computed(() => {
    if (toggleLoading.value) return '...'
    return useOllama.value ? 'ON' : 'OFF'
  })

  const checkHealth = async () => {
    try {
      const r = await fetch(`${apiConfig.baseUrl}${apiConfig.endpoints.health}`)
      const data = await r.json()
      apiStatus.value = data.ollama_available ? 'ok' : 'fail'
      useOllama.value = !!data.use_ollama
    } catch (e) {
      apiStatus.value = 'fail'
    }
  }

  const toggleOllama = async () => {
    toggleLoading.value = true
    try {
      const r = await fetch(`${apiConfig.baseUrl}${apiConfig.endpoints.ollama}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !useOllama.value })
      })
      const data = await r.json()
      useOllama.value = !!data.use_ollama
      await checkHealth()
    } catch (e) {
      apiStatus.value = 'fail'
    } finally {
      toggleLoading.value = false
    }
  }

  return {
    apiStatus,
    useOllama,
    toggleLoading,
    apiStatusLabel,
    apiStatusClass,
    toggleLabel,
    checkHealth,
    toggleOllama
  }
}
