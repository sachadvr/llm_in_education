<template>
  <main class="mx-auto w-full max-w-[1160px] px-6 pb-20 pt-12">

    <!-- Header -->
    <div class="mb-12 text-center">
      <p class="text-xs uppercase tracking-[0.3em] mb-3" style="color: var(--pipeline)">Observabilité</p>
      <h1 class="text-3xl font-semibold tracking-tight sm:text-4xl" style="color: var(--text)">Analytics temps réel</h1>
      <p class="mt-3 text-sm" style="color: var(--text-dim)">
        Heatmap des erreurs · métriques système · tendances d'apprentissage
      </p>
    </div>

    <div class="grid gap-6 lg:grid-cols-[1fr_320px]">

      <!-- Heatmap -->
      <div class="glass-card rounded-3xl overflow-hidden">
        <div class="px-5 py-4 border-b flex items-center justify-between" style="border-color: var(--border)">
          <span class="text-xs font-medium" style="color: var(--text)">Heatmap des erreurs</span>
          <span class="text-[10px] uppercase tracking-widest" style="color: var(--text-dim)">agrégation par session</span>
        </div>

        <div v-if="loadingHeatmap" class="p-6 space-y-2">
          <div v-for="i in 6" :key="i" class="h-10 rounded animate-pulse" style="background: rgba(255,255,255,0.04)"></div>
        </div>

        <div v-else-if="heatmapData.length" class="divide-y" style="border-color: var(--border)">
          <div v-for="(row, idx) in heatmapData.slice(0, 20)" :key="idx"
            class="flex items-center justify-between px-5 py-3"
          >
            <span class="text-[11px] font-mono" style="color: var(--text-dim)">{{ row.session_id?.slice(0, 14) || '—' }}…</span>
            <span class="text-[11px] rounded px-2 py-0.5" style="background: var(--pipeline-dim); color: var(--pipeline)">{{ row.error_type }}</span>
            <span class="text-sm font-medium tabular-nums" style="color: var(--text)">{{ row.count }}</span>
          </div>
        </div>

        <div v-else class="px-5 py-10 text-center text-sm" style="color: var(--text-dim)">
          Aucune donnée disponible.
        </div>
      </div>

      <!-- Right column -->
      <div class="space-y-4">

        <!-- System metrics -->
        <div class="glass-card rounded-3xl overflow-hidden">
          <div class="px-5 py-4 border-b" style="border-color: var(--border)">
            <span class="text-xs font-medium" style="color: var(--text)">Métriques système</span>
          </div>

          <div v-if="loadingSystem" class="p-4 space-y-2">
            <div v-for="i in 4" :key="i" class="h-8 rounded animate-pulse" style="background: rgba(255,255,255,0.04)"></div>
          </div>

          <div v-else class="p-4 space-y-2">
            <MetricRow label="Corrections totales" :value="systemMetrics.total_corrections || 0" />
            <MetricRow label="Tentatives QCM" :value="systemMetrics.total_quiz_attempts || 0" />
            <MetricRow label="Taux de réussite" :value="`${Math.round((systemMetrics.accuracy_rate || 0) * 100)}%`" accent />
            <MetricRow label="Latence moyenne" :value="systemMetrics.avg_latency_ms ? Math.round(systemMetrics.avg_latency_ms) + ' ms' : '—'" />
            <MetricRow label="Confiance moyenne" :value="systemMetrics.confidence_avg ? (systemMetrics.confidence_avg * 100).toFixed(1) + '%' : '—'" />

            <div v-if="systemMetrics.top_error_types?.length" class="pt-2 mt-2 border-t" style="border-color: var(--border)">
              <p class="text-[10px] uppercase tracking-widest mb-2" style="color: var(--text-dim)">Top erreurs</p>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="(et, i) in systemMetrics.top_error_types" :key="i"
                  class="text-[10px] rounded px-2 py-0.5"
                  style="background: var(--warm-dim); color: var(--warm)"
                >{{ et.error_type }}: {{ et.count }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Trends -->
        <div class="glass-card rounded-3xl overflow-hidden">
          <div class="px-5 py-4 border-b" style="border-color: var(--border)">
            <span class="text-xs font-medium" style="color: var(--text)">Tendances 30 jours</span>
          </div>

          <div v-if="loadingTrends" class="p-4 space-y-2">
            <div v-for="i in 4" :key="i" class="h-8 rounded animate-pulse" style="background: rgba(255,255,255,0.04)"></div>
          </div>

          <div v-else-if="trendsData.length" class="divide-y" style="border-color: var(--border)">
            <div v-for="(day, idx) in trendsData.slice(0, 10)" :key="idx"
              class="flex items-center justify-between px-4 py-2.5"
            >
              <span class="text-[11px]" style="color: var(--text-dim)">{{ day.date }}</span>
              <div class="flex items-center gap-3 text-[11px]">
                <span style="color: var(--success)">{{ day.success_count }}</span>
                <span style="color: var(--danger)">{{ day.error_count }}</span>
                <span style="color: var(--text-dim2)">/{{ day.total_attempts }}</span>
              </div>
            </div>
          </div>

          <div v-else class="px-5 py-6 text-center text-sm" style="color: var(--text-dim)">
            Aucune tendance disponible.
          </div>
        </div>

      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, onMounted, inject, defineComponent, h } from 'vue'
import { apiConfig, apiFetch } from '../config/api.js'

defineProps({ apiStatusLabel: String, apiStatusClass: String })

const setApiStatus = inject('setApiStatus', () => {})

const MetricRow = defineComponent({
  props: { label: String, value: [String, Number], accent: Boolean },
  setup(props) {
    return () => h('div', { class: 'flex items-center justify-between py-1' }, [
      h('span', { style: 'font-size:11px;color:var(--text-dim)' }, props.label),
      h('span', {
        style: `font-size:12px;font-weight:500;${props.accent ? 'color:var(--success)' : 'color:var(--text)'}`
      }, String(props.value))
    ])
  }
})

const loadingHeatmap = ref(true)
const loadingSystem = ref(true)
const loadingTrends = ref(true)
const heatmapData = ref([])
const systemMetrics = ref({})
const trendsData = ref([])

function getSessionId() {
  let sid = sessionStorage.getItem('mvp_session_id')
  if (!sid) { sid = crypto.randomUUID ? crypto.randomUUID() : `s${Date.now()}`; sessionStorage.setItem('mvp_session_id', sid) }
  return sid
}

const loadHeatmap = async () => {
  try {
    const r = await apiFetch(apiConfig.endpoints.analytics.heatmap)
    const data = await r.json()
    if (r.ok) heatmapData.value = data.data || []
  } catch {}
  finally { loadingHeatmap.value = false }
}

const loadSystem = async () => {
  try {
    const r = await apiFetch(apiConfig.endpoints.analytics.systemMetrics)
    const data = await r.json()
    if (r.ok) systemMetrics.value = data
  } catch {}
  finally { loadingSystem.value = false }
}

const loadTrends = async () => {
  try {
    const userId = getSessionId()
    const r = await apiFetch(`${apiConfig.endpoints.analytics.trends}?user_id=${encodeURIComponent(userId)}&days=30`)
    const data = await r.json()
    if (r.ok) trendsData.value = data.trends || []
  } catch {}
  finally { loadingTrends.value = false }
}

onMounted(() => {
  Promise.all([loadHeatmap(), loadSystem(), loadTrends()])
    .then(() => setApiStatus('ok'))
    .catch(() => setApiStatus('fail'))
})
</script>
