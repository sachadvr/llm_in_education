<template>
  <main class="mx-auto w-full max-w-[1160px] px-6 pb-20 pt-12">

    <!-- Header -->
    <div class="mb-12 text-center">
      <p class="text-xs uppercase tracking-[0.3em] mb-3" style="color: var(--accent)">H2 — Adaptativité</p>
      <h1 class="text-3xl font-semibold tracking-tight sm:text-4xl" style="color: var(--text)">Vecteur de compétences</h1>
      <p class="mt-3 text-sm" style="color: var(--text-dim)">
        Niveau = f(Taux de succès, Erreurs récurrentes, Historique) · λ=0.1 · intervalles 1/3/7/14/30 jours
      </p>
    </div>

    <div v-if="loading" class="flex items-center gap-3 py-16 justify-center" style="color: var(--text-dim)">
      <span class="animate-spin text-lg">◌</span>
      <span class="text-sm">Chargement du profil apprenant...</span>
    </div>

    <div v-else class="grid gap-6 lg:grid-cols-[1fr_340px]">

      <!-- Left: error competency matrix -->
      <div class="space-y-4">

        <!-- Due for review — priority section -->
        <div v-if="dueErrors.length" class="glass-card rounded-3xl p-4" style="border-color: rgba(251,146,60,0.35)">
          <div class="flex items-center gap-2 mb-4">
            <span class="text-[10px] uppercase tracking-widest font-medium" style="color: var(--warm)">● Révisions dues</span>
            <span class="rounded px-2 py-0.5 text-[10px]" style="background: var(--warm-dim); color: var(--warm)">{{ dueErrors.length }}</span>
          </div>
          <div class="grid gap-2">
            <div v-for="err in dueErrors" :key="err.error_type"
              class="flex items-center justify-between rounded-lg px-4 py-3 cursor-pointer transition-all hover:opacity-80"
              style="background: rgba(251,146,60,0.08); border: 1px solid rgba(251,146,60,0.2)"
              @click="$router.push('/quiz')"
            >
              <div class="flex items-center gap-3">
                <MasteryPips :level="err.mastery_level" />
                <span class="text-sm font-medium" style="color: var(--text)">{{ err.error_type }}</span>
              </div>
              <div class="flex items-center gap-3">
                <span class="text-[11px]" style="color: var(--warm)">révision due</span>
                <span class="text-xs rounded px-2 py-0.5" style="background: var(--warm-dim); color: var(--warm)">→ QCM</span>
              </div>
            </div>
          </div>
        </div>

        <!-- All error types -->
        <div class="glass-card rounded-3xl overflow-hidden">
          <div class="px-5 py-4 border-b flex items-center justify-between" style="border-color: var(--border)">
            <span class="text-xs font-medium tracking-wide" style="color: var(--text)">Erreurs fréquentes — pondération exponentielle</span>
            <span class="text-[11px]" style="color: var(--text-dim)">poids = n × e<sup>-λt</sup></span>
          </div>

          <div v-if="!errorHistory.length" class="px-5 py-10 text-center text-sm" style="color: var(--text-dim)">
            Aucune erreur enregistrée. Commencez un exercice ou un QCM.
          </div>

          <div v-else class="divide-y" style="border-color: var(--border)">
            <div v-for="err in errorHistory" :key="err.error_type"
              class="flex items-center gap-4 px-5 py-4 transition-all hover:opacity-90"
              :style="err.is_due_for_review ? 'background: rgba(251,146,60,0.04)' : 'background: transparent'"
            >
              <!-- Error type label -->
              <div class="w-28 shrink-0">
                <span class="text-xs font-medium" style="color: var(--text)">{{ err.error_type }}</span>
              </div>

              <!-- Mastery pips -->
              <div class="shrink-0">
                <MasteryPips :level="err.mastery_level" />
              </div>

              <!-- Weight bar -->
              <div class="flex-1 min-w-0">
                <div class="h-1 rounded-full overflow-hidden" style="background: var(--border)">
                  <div class="h-full rounded-full transition-all duration-700"
                    :style="`width: ${Math.min(100, err.weight * 10)}%; background: ${weightColor(err.weight)}`"
                  ></div>
                </div>
              </div>

              <!-- Stats -->
              <div class="flex items-center gap-4 text-[11px] shrink-0" style="color: var(--text-dim)">
                <span>×{{ err.count }}</span>
                <span class="w-16 text-right" :style="err.is_due_for_review ? 'color: var(--warm)' : ''">
                  {{ reviewLabel(err) }}
                </span>
                <span class="w-12 text-right font-medium tabular-nums" style="color: var(--text)">{{ err.weight.toFixed(2) }}</span>
              </div>
            </div>
          </div>
        </div>

      </div>

      <!-- Right: stats + overview -->
      <div class="space-y-4">

        <!-- CECRL level card -->
        <div class="glass-card rounded-3xl p-5">
          <p class="text-[10px] uppercase tracking-widest mb-4" style="color: var(--text-dim)">Niveau CECRL estimé</p>
          <div class="flex items-baseline gap-2 mb-1">
            <span class="font-serif italic text-5xl" style="color: var(--accent)">{{ difficultyAssessment.level || 'A2' }}</span>
            <span class="text-sm" style="color: var(--text-dim)">{{ difficultyAssessment.reasoning ? '· ' + difficultyAssessment.reasoning.replace(/_/g,' ') : '' }}</span>
          </div>
          <div class="mt-3 h-1.5 rounded-full overflow-hidden" style="background: var(--border)">
            <div class="h-full rounded-full transition-all duration-1000"
              :style="`width: ${levelPercent}%; background: linear-gradient(90deg, var(--pipeline), var(--accent))`"
            ></div>
          </div>
          <div class="mt-1 flex justify-between text-[10px]" style="color: var(--text-dim2)">
            <span>A1</span><span>A2</span><span>B1</span><span>B2</span>
          </div>
        </div>

        <!-- Stats grid -->
        <div class="glass-card rounded-3xl p-5 space-y-3">
          <p class="text-[10px] uppercase tracking-widest mb-4" style="color: var(--text-dim)">Statistiques session</p>
          <StatRow label="Tentatives" :value="stats.total_attempts || 0" />
          <StatRow label="Taux de réussite" :value="`${Math.round((stats.success_rate || 0) * 100)}%`" :accent="true" />
          <StatRow label="Types d'erreurs" :value="stats.unique_error_types || errorHistory.length" />
          <StatRow label="Score pondéré" :value="(stats.total_weighted_score || 0).toFixed(2)" />
          <StatRow label="Tendance" :value="stats.learning_trend || '—'" />
        </div>

        <!-- Spaced rep schedule -->
        <div class="glass-card rounded-3xl p-5">
          <p class="text-[10px] uppercase tracking-widest mb-4" style="color: var(--text-dim)">Calendrier SRS · Ebbinghaus</p>
          <div class="flex items-center justify-between mb-3">
            <div v-for="(d, i) in [1,3,7,14,30]" :key="d"
              class="flex flex-col items-center gap-1"
            >
              <div class="h-6 w-6 rounded-full grid place-items-center text-[10px] transition-all"
                :style="i < maxMastery
                  ? 'background: var(--accent); color: var(--bg)'
                  : 'border: 1px solid var(--border); color: var(--text-dim2)'"
              >{{ i+1 }}</div>
              <span class="text-[9px]" style="color: var(--text-dim2)">{{ d }}j</span>
            </div>
          </div>
          <p class="text-[11px] leading-relaxed" style="color: var(--text-dim)">
            Maîtrise max atteinte : niveau <span style="color: var(--accent)">{{ maxMastery }}/4</span>.
            Les révisions dues passent en priorité dans le QCM.
          </p>
        </div>

        <!-- Recommendations -->
        <div v-if="recommendations.focus_areas?.length" class="rounded-xl p-5" style="border: 1px solid var(--border); background: var(--bg-card)">
          <p class="text-[10px] uppercase tracking-widest mb-4" style="color: var(--text-dim)">Recommandations</p>
          <div class="space-y-2">
            <div v-for="(rec, i) in recommendations.focus_areas" :key="i"
              class="flex items-center gap-2 text-xs rounded px-3 py-2"
              style="background: var(--pipeline-dim); color: var(--pipeline)"
            >
              <span>→</span>
              <span>{{ rec }}</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted, defineComponent, h } from 'vue'
import { apiConfig, apiFetch } from '../config/api.js'

// Mastery pips component — 5 circles, filled based on level
const MasteryPips = defineComponent({
  props: { level: { type: Number, default: 0 } },
  setup(props) {
    const colors = ['#6B7280','#F87171','#FB923C','#FBBF24','#2DD4BF']
    return () => h('div', { class: 'flex gap-1 items-center' },
      Array.from({ length: 5 }, (_, i) =>
        h('span', {
          style: `display:block;width:7px;height:7px;border-radius:50%;transition:all 0.4s;` +
            (i <= props.level
              ? `background:${colors[Math.min(props.level,4)]};box-shadow:0 0 6px ${colors[Math.min(props.level,4)]}55`
              : 'border:1px solid rgba(255,255,255,0.1);background:transparent')
        })
      )
    )
  }
})

const StatRow = defineComponent({
  props: { label: String, value: [String, Number], accent: Boolean },
  setup(props) {
    return () => h('div', { class: 'flex items-center justify-between' }, [
      h('span', { style: 'font-size:11px;color:var(--text-dim)' }, props.label),
      h('span', {
        style: `font-size:12px;font-weight:500;${props.accent ? 'color:var(--success)' : 'color:var(--text)'}`
      }, String(props.value))
    ])
  }
})

defineProps({ apiStatusLabel: String, apiStatusClass: String })

const loading = ref(true)
const errorHistory = ref([])
const difficultyAssessment = ref({})
const recommendations = ref({})
const stats = ref({})

function getSessionId() {
  let sid = sessionStorage.getItem('mvp_session_id')
  if (!sid) {
    sid = crypto.randomUUID ? crypto.randomUUID() : `s${Date.now()}`
    sessionStorage.setItem('mvp_session_id', sid)
  }
  return sid
}

const dueErrors = computed(() => errorHistory.value.filter(e => e.is_due_for_review))
const maxMastery = computed(() => errorHistory.value.length
  ? Math.max(...errorHistory.value.map(e => e.mastery_level || 0))
  : 0)
const levelPercent = computed(() => {
  const map = { A1: 10, A2: 35, B1: 65, B2: 90 }
  return map[difficultyAssessment.value.level] || 35
})

function weightColor(w) {
  if (w > 6) return 'var(--danger)'
  if (w > 3) return 'var(--warm)'
  if (w > 1) return 'var(--accent)'
  return 'var(--pipeline)'
}

function reviewLabel(err) {
  if (err.is_due_for_review) return 'due !'
  if (err.next_review_in_days === 0) return 'demain'
  if (err.next_review_in_days != null) return `dans ${err.next_review_in_days}j`
  return '—'
}

const loadProgress = async () => {
  loading.value = true
  try {
    const userId = getSessionId()
    const r = await apiFetch(apiConfig.endpoints.learnerProgress(userId))
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail)
    errorHistory.value = data.error_history || []
    difficultyAssessment.value = data.difficulty_assessment || {}
    recommendations.value = data.recommendations || {}
    stats.value = data.stats || {}
  } catch {}
  finally { loading.value = false }
}

onMounted(loadProgress)
</script>
