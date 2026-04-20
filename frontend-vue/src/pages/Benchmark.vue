<template>
  <main class="mx-auto w-full max-w-[1160px] px-6 pb-20 pt-12">

    <!-- Header -->
    <div class="mb-12 text-center">
      <p class="text-xs uppercase tracking-[0.3em] mb-3" style="color: var(--danger)">Évaluation H1</p>
      <h1 class="text-3xl font-semibold tracking-tight sm:text-4xl" style="color: var(--text)">Benchmark comparatif</h1>
      <p class="mt-3 text-sm" style="color: var(--text-dim)">
        LLM brut vs pipeline structuré vs pipeline+mémoire · ERRANT F0.5 · span F0.5 · type accuracy
      </p>
    </div>

    <!-- Actions -->
    <div class="flex flex-wrap gap-3 mb-8">
      <button @click="runBenchmark" :disabled="runningBenchmark"
        class="rounded-lg px-4 py-2 text-sm font-medium transition"
        style="background: var(--accent); color: var(--bg)"
        :class="runningBenchmark ? 'opacity-40 cursor-not-allowed' : 'hover:opacity-90'"
      >
        {{ runningBenchmark ? '⟳ exécution...' : 'Lancer benchmark' }}
      </button>
    </div>

    <div v-if="loading" class="space-y-4">
      <div v-for="i in 3" :key="i" class="h-40 rounded-3xl animate-pulse" style="background: rgba(255,255,255,0.04)"></div>
    </div>

    <div v-else-if="stats" class="grid gap-6 lg:grid-cols-[1fr_320px]">

      <!-- Left: config cards -->
      <div class="space-y-4">

        <!-- One card per config -->
        <div v-for="cfg in orderedConfigs" :key="cfg.model_name"
          class="glass-card rounded-3xl overflow-hidden"
        >
          <!-- Config header -->
          <div class="px-5 py-4 border-b flex items-center gap-3" style="border-color: var(--border)">
            <span class="h-2.5 w-2.5 rounded-full shrink-0" :style="`background: ${configColor(cfg.model_name)}`"></span>
            <span class="text-sm font-medium" style="color: var(--text)">{{ cfg.model_name }}</span>
            <span class="text-[10px] ml-auto" style="color: var(--text-dim)">n = {{ cfg.n.toLocaleString() }}</span>
          </div>

          <div class="px-5 py-4 space-y-4">

            <!-- ERRANT block -->
            <div>
              <p class="text-[9px] uppercase tracking-widest mb-2" style="color: var(--text-dim)">
                ERRANT · édit-level · BEA-2019 standard
                <span v-if="cfg.errant_n_runs" style="color: var(--text-dim2)"> · {{ cfg.errant_n_runs }} runs</span>
              </p>
              <div class="grid grid-cols-3 gap-2 mb-2">
                <Cell label="F0.5" :value="pct(cfg.errant_f05)" :sub="cfg.errant_f05_std ? `±${pct(cfg.errant_f05_std)}` : null" accent />
                <Cell label="Précision" :value="pct(cfg.errant_p)" />
                <Cell label="Rappel" :value="pct(cfg.errant_r)" />
              </div>
              <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--border)">
                <div class="h-full rounded-full transition-all duration-700"
                  :style="`width: ${(cfg.errant_f05 || 0) * 100}%; background: ${configColor(cfg.model_name)}`"
                ></div>
              </div>
            </div>

            <!-- Secondary metrics -->
            <div>
              <p class="text-[9px] uppercase tracking-widest mb-2" style="color: var(--text-dim)">Métriques complémentaires</p>
              <div class="grid grid-cols-5 gap-2">
                <Cell label="TSF0.5" :value="pct(cfg.avg_f05)" dim />
                <Cell label="Exact match" :value="pct(cfg.exact_match)" />
                <Cell label="Type acc." :value="pct(cfg.type_acc)" />
                <Cell label="Span F0.5" :value="pct(cfg.avg_span_f05)" />
                <Cell label="Feedback" :value="pct(cfg.feedback_present)" />
              </div>
            </div>

          </div>
        </div>

        <!-- Delta table vs baseline -->
        <div v-if="baseline && orderedConfigs.length > 1" class="glass-card rounded-3xl overflow-hidden">
          <div class="px-5 py-4 border-b" style="border-color: var(--border)">
            <span class="text-xs font-medium" style="color: var(--text)">Δ vs llm_brut (baseline)</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-[11px]">
              <thead>
                <tr style="border-bottom: 1px solid var(--border)">
                  <th class="px-5 py-2 text-left font-medium" style="color: var(--text-dim)">Métrique</th>
                  <th v-for="cfg in nonBaseline" :key="cfg.model_name"
                    class="px-4 py-2 text-right font-medium"
                    :style="`color: ${configColor(cfg.model_name)}`"
                  >{{ cfg.model_name }}</th>
                </tr>
              </thead>
              <tbody class="divide-y" style="border-color: var(--border)">
                <tr v-for="row in deltaRows" :key="row.label" class="hover:bg-white/[0.02]">
                  <td class="px-5 py-2" style="color: var(--text-dim)">{{ row.label }}</td>
                  <td v-for="cfg in nonBaseline" :key="cfg.model_name"
                    class="px-4 py-2 text-right font-mono"
                    :style="deltaColor(row.getValue(cfg) - row.getValue(baseline))"
                  >{{ deltaFmt(row.getValue(cfg) - row.getValue(baseline)) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </div>

      <!-- Right column -->
      <div class="space-y-4">

        <!-- Type alignment -->
        <div class="glass-card rounded-3xl overflow-hidden">
          <div class="px-5 py-4 border-b" style="border-color: var(--border)">
            <span class="text-xs font-medium" style="color: var(--text)">Alignement par type</span>
            <span class="text-[10px] ml-2" style="color: var(--text-dim)">pipeline_structuré</span>
          </div>
          <div class="divide-y" style="border-color: var(--border)">
            <div v-for="row in stats.type_alignment" :key="row.error_type" class="px-5 py-2.5 flex items-center gap-3">
              <span class="text-[11px] w-24 shrink-0" style="color: var(--text)">{{ row.error_type }}</span>
              <div class="flex-1 h-1 rounded-full overflow-hidden" style="background: var(--border)">
                <div class="h-full rounded-full" :style="`width: ${row.alignment_rate * 100}%; background: var(--accent)`"></div>
              </div>
              <span class="text-[10px] w-10 text-right font-mono shrink-0" style="color: var(--text-dim)">{{ pct(row.alignment_rate) }}</span>
              <span class="text-[9px] w-12 text-right shrink-0" style="color: var(--text-dim2)">n={{ row.n }}</span>
            </div>
          </div>
        </div>

        <!-- Predicted distribution -->
        <div class="glass-card rounded-3xl overflow-hidden">
          <div class="px-5 py-4 border-b" style="border-color: var(--border)">
            <span class="text-xs font-medium" style="color: var(--text)">Distribution prédite</span>
            <span class="text-[10px] ml-2" style="color: var(--text-dim)">pipeline_structuré</span>
          </div>
          <div class="divide-y" style="border-color: var(--border)">
            <div v-for="row in stats.predicted_distribution" :key="row.error_type" class="px-5 py-2.5 flex items-center gap-3">
              <span class="text-[11px] w-24 shrink-0" style="color: var(--text)">{{ row.error_type || 'none' }}</span>
              <div class="flex-1 h-1 rounded-full overflow-hidden" style="background: var(--border)">
                <div class="h-full rounded-full" :style="`width: ${row.pct}%; background: var(--pipeline)`"></div>
              </div>
              <span class="text-[10px] w-12 text-right font-mono shrink-0" style="color: var(--text-dim)">{{ row.pct.toFixed(1) }}%</span>
            </div>
          </div>
        </div>

        <!-- Legend -->
        <div class="glass-card rounded-3xl p-4 text-[11px] space-y-2" style="color: var(--text-dim)">
          <p class="text-[9px] uppercase tracking-widest mb-3">Métriques</p>
          <div><span style="color: var(--success)">ERRANT F0.5</span> — édition, BEA-2019. β=0.5 favorise la précision.</div>
          <div><span style="color: var(--text-dim)">TSF0.5</span> — token-sequence, non-standard. Pour référence.</div>
          <div><span style="color: var(--text)">Span F0.5</span> — localisation des spans d'erreur vs gold.</div>
          <div><span style="color: var(--text)">Type acc.</span> — type d'erreur prédit = gold.</div>
          <div><span style="color: var(--pipeline)">pipeline+mémoire</span> — pgvector activé, k=3 erreurs similaires.</div>
        </div>

      </div>
    </div>

    <div v-else class="text-center py-20 text-sm" style="color: var(--text-dim)">
      Aucune donnée. Lancez un benchmark ou importez des résultats.
    </div>

  </main>
</template>

<script setup>
import { ref, computed, inject, onMounted, defineComponent, h } from 'vue'
import { apiConfig, apiFetch } from '../config/api.js'

defineProps({ apiStatusLabel: String, apiStatusClass: String })
const setApiStatus = inject('setApiStatus', () => {})

// ── helpers ──────────────────────────────────────────────────────────────────

function pct(v) {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function deltaFmt(v) {
  if (v == null || isNaN(v)) return '—'
  const s = (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%'
  return s
}

function deltaColor(v) {
  if (v == null || isNaN(v)) return 'color: var(--text-dim)'
  if (Math.abs(v) < 0.001) return 'color: var(--text-dim)'
  return v > 0 ? 'color: var(--success)' : 'color: var(--danger)'
}

function configColor(name) {
  if (!name) return 'var(--text-dim)'
  if (name.includes('mémoire') || name.includes('memoire')) return 'var(--pipeline)'
  if (name.includes('pipeline') || name.includes('structur')) return 'var(--accent)'
  return 'var(--danger)'
}

// ── Cell component ────────────────────────────────────────────────────────────

const Cell = defineComponent({
  props: { label: String, value: String, sub: String, accent: Boolean, dim: Boolean },
  setup(props) {
    return () => h('div', {
      style: 'border-radius:6px; padding:8px; background:rgba(255,255,255,0.025); border:1px solid rgba(255,255,255,0.06); text-align:center'
    }, [
      h('p', { style: 'font-size:9px; color:var(--text-dim); margin-bottom:3px; text-transform:uppercase; letter-spacing:.05em' }, props.label),
      h('p', {
        style: `font-size:13px; font-weight:500; ${props.accent ? 'color:var(--success)' : props.dim ? 'color:var(--text-dim)' : 'color:var(--text)'}`
      }, props.value),
      props.sub ? h('p', { style: 'font-size:9px; color:var(--text-dim2); margin-top:1px' }, props.sub) : null,
    ])
  }
})

// ── state ─────────────────────────────────────────────────────────────────────

const loading = ref(true)
const runningBenchmark = ref(false)
const stats = ref(null)

const CONFIG_ORDER = ['llm_brut', 'pipeline_structuré', 'pipeline+mémoire']

const orderedConfigs = computed(() => {
  if (!stats.value) return []
  return CONFIG_ORDER
    .map(name => stats.value.configurations.find(c => c.model_name === name))
    .filter(Boolean)
})

const baseline = computed(() => orderedConfigs.value.find(c => c.model_name === 'llm_brut'))
const nonBaseline = computed(() => orderedConfigs.value.filter(c => c.model_name !== 'llm_brut'))

const deltaRows = [
  { label: 'ERRANT F0.5',   getValue: c => c.errant_f05 || 0 },
  { label: 'ERRANT Prec.',  getValue: c => c.errant_p || 0 },
  { label: 'ERRANT Rappel', getValue: c => c.errant_r || 0 },
  { label: 'TSF0.5',        getValue: c => c.avg_f05 || 0 },
  { label: 'Exact match',   getValue: c => c.exact_match || 0 },
  { label: 'Type accuracy', getValue: c => c.type_acc || 0 },
  { label: 'Span F0.5',     getValue: c => c.avg_span_f05 || 0 },
  { label: 'Feedback',      getValue: c => c.feedback_present || 0 },
]

// ── data loading ──────────────────────────────────────────────────────────────

const loadStats = async () => {
  try {
    const r = await apiFetch('/api/benchmark/stats')
    const data = await r.json()
    if (r.ok && data.status === 'success') {
      stats.value = data
      setApiStatus('ok')
    }
  } catch {}
  finally { loading.value = false }
}

const runBenchmark = async () => {
  runningBenchmark.value = true
  try {
    const r = await apiFetch(apiConfig.endpoints.benchmarks.run, { method: 'POST' })
    const data = await r.json()
    if (r.ok && data.status === 'success') {
      await loadStats()
      setApiStatus('ok')
    } else {
      throw new Error(data.detail || 'Échec benchmark')
    }
  } catch (e) {
    setApiStatus('fail')
    alert('Erreur benchmark: ' + e.message)
  } finally {
    runningBenchmark.value = false
  }
}

onMounted(loadStats)
</script>
