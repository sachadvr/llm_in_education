<template>
  <main class="mx-auto w-full max-w-[1160px] px-6 pb-20 pt-12">

    <!-- Hero -->
    <header class="mt-6 text-center">
      <p class="text-xs uppercase tracking-[0.3em]" style="color: var(--text-dim2)">Learning loop</p>
      <h1 class="mt-5 text-3xl font-semibold tracking-tight sm:text-5xl" style="color: var(--text)">
        Des exercices ciblés, une correction claire,<br class="hidden sm:block"> un feedback simple.
      </h1>
      <p class="mx-auto mt-4 max-w-2xl text-base leading-7 sm:mt-6 sm:text-lg sm:leading-8" style="color: var(--text-dim)">
        LLM → tokenisation → diff → classification déterministe → feedback template
      </p>
      <div class="mt-8 flex flex-wrap items-center justify-center gap-3">
        <button @click="fetchExercise"
          class="inline-flex items-center justify-center rounded-xl border border-white/80 bg-white px-5 py-2.5 text-sm font-medium text-black transition hover:bg-white/90 glow-button"
        >Nouvel exercice</button>
        <router-link to="/quiz"
          class="inline-flex items-center justify-center rounded-xl px-5 py-2.5 text-sm font-medium transition hover:bg-white/8"
          style="border: 1px solid var(--border); color: var(--text-dim)"
        >Aller au QCM</router-link>
        <span class="rounded-full px-3 py-1 text-xs" style="border: 1px solid var(--border); color: var(--text-dim2)">
          latence LLM: {{ statLatency }}
        </span>
      </div>
    </header>

    <!-- Main grid -->
    <section class="mt-14 grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:items-start">

      <!-- Exercise fill-in-blank -->
      <div class="glass-card rounded-3xl p-6">
        <div class="traffic-lights">
          <span style="background:#ff5f57"></span>
          <span style="background:#febc2e"></span>
          <span style="background:#28c840"></span>
        </div>

        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs uppercase tracking-[0.16em]" style="color: var(--text-dim2)">Exercice à trous</p>
            <h2 class="mt-2 text-xl font-semibold" style="color: var(--text)">
              Complétez la phrase
              <span v-if="level" class="ml-2 text-xs font-normal rounded px-2 py-0.5" style="background: var(--accent-dim); color: var(--accent)">{{ level }}</span>
            </h2>
          </div>
          <span class="rounded-full px-3 py-1 text-xs" style="border: 1px solid var(--border); background: var(--bg-card); color: var(--text-dim2)">#{{ counter }}</span>
        </div>

        <!-- Prompt -->
        <div class="mt-6 flex items-start gap-3">
          <div class="h-9 w-9 rounded-full bg-white text-black grid place-items-center text-xs font-semibold flex-shrink-0">AI</div>
          <div class="rounded-2xl rounded-tl-none p-4 text-sm max-w-md" style="border: 1px solid var(--border); background: var(--bg-card)">
            <div v-if="promptLoading" class="flex gap-2 items-center" style="color: var(--text-dim)">
              <span class="animate-pulse">◌</span>
              <span>génération en cours...</span>
            </div>
            <p v-else class="leading-relaxed" style="color: var(--text-dim)">{{ prompt }}</p>
            <p class="mt-2 text-xs" style="color: var(--text-dim2)">Complétez le mot manquant.</p>
          </div>
        </div>

        <!-- Feedback bubble -->
        <transition name="fade">
          <div v-if="exerciseFeedback" class="mt-4 flex items-start justify-end gap-3">
            <div class="rounded-2xl rounded-tr-none px-4 py-3 text-sm max-w-md"
              :style="exerciseFeedback.correct
                ? 'background: rgba(74,222,128,0.15); color: var(--success)'
                : 'background: rgba(248,113,113,0.12); color: var(--danger)'"
            >
              <p class="font-medium">{{ exerciseFeedback.correct ? '✓ Correct !' : '✗ ' + exerciseFeedback.corrected }}</p>
              <p v-if="exerciseFeedback.feedback" class="mt-1 text-xs leading-relaxed" style="color: var(--text-dim)">{{ exerciseFeedback.feedback }}</p>
              <div v-if="exerciseFeedback.error_type && exerciseFeedback.error_type !== 'none'" class="mt-2">
                <span class="text-xs rounded px-2 py-0.5" style="background: var(--warm-dim); color: var(--warm)">{{ exerciseFeedback.error_type }}</span>
              </div>
              <div class="mt-3 flex items-center gap-2">
                <span class="text-xs" style="color: var(--text-dim2)">Utile ?</span>
                <button v-if="exerciseRating === null" @click="rateFeedback(true, 'exercise')" class="text-sm hover:scale-110 transition-transform">👍</button>
                <button v-if="exerciseRating === null" @click="rateFeedback(false, 'exercise')" class="text-sm hover:scale-110 transition-transform">👎</button>
                <span v-if="exerciseRating !== null" class="text-xs" style="color: var(--success)">{{ exerciseRating ? '👍 Merci !' : '👎 Noté.' }}</span>
              </div>
            </div>
            <div class="h-9 w-9 rounded-full grid place-items-center text-xs flex-shrink-0" style="background: var(--bg-card); border: 1px solid var(--border); color: var(--text-dim)">Vous</div>
          </div>
        </transition>

        <!-- Input -->
        <div class="mt-6 grid gap-3">
          <label class="text-xs uppercase tracking-[0.16em]" style="color: var(--text-dim2)">Votre réponse</label>
          <div class="flex flex-col gap-3 sm:flex-row">
            <input v-model="answerInput" @keydown.enter.prevent="submitAnswer"
              class="w-full rounded-2xl px-4 py-3 text-sm outline-none transition"
              style="border: 1px solid var(--border); background: var(--bg-card); color: var(--text)"
              :style="answerInput ? 'border-color: rgba(255,255,255,0.3)' : ''"
              placeholder="Tapez le mot manquant"
            />
            <button @click="submitAnswer" :disabled="submitting"
              class="rounded-2xl border border-white/80 bg-white px-5 py-3 text-sm font-medium text-black transition hover:bg-white/90 glow-button flex-shrink-0"
              :class="submitting ? 'opacity-40' : ''"
            >{{ submitting ? '...' : 'Valider' }}</button>
          </div>
        </div>

        <!-- Footer row -->
        <div class="mt-6 flex items-center justify-between">
          <span v-if="sessionFocus" class="text-xs rounded px-2 py-0.5" style="background: var(--warm-dim); color: var(--warm)">focus: {{ sessionFocus }}</span>
          <span v-else class="text-xs" style="color: var(--text-dim2)">{{ statExercise }}</span>
          <button @click="fetchExercise" class="rounded-full px-4 py-2 text-sm font-medium transition hover:bg-white/8"
            style="border: 1px solid var(--border); color: var(--text-dim)"
          >Nouvel exercice</button>
        </div>
      </div>

      <!-- Right column -->
      <div class="space-y-6">

        <!-- Free correction -->
        <div class="glass-card rounded-3xl p-6">
          <div class="traffic-lights">
            <span style="background:#ff5f57"></span>
            <span style="background:#febc2e"></span>
            <span style="background:#28c840"></span>
          </div>
          <h3 class="text-lg font-semibold" style="color: var(--text)">Correction rapide</h3>
          <p class="mt-2 text-sm" style="color: var(--text-dim)">Teste ton propre exemple et récupère la correction structurée.</p>
          <div class="mt-4">
            <label class="text-xs uppercase tracking-[0.16em]" style="color: var(--text-dim2)">Phrase</label>
            <textarea v-model="phrase" rows="4"
              class="mt-2 w-full rounded-xl px-3 py-3 text-sm outline-none resize-none transition"
              style="border: 1px solid var(--border); background: var(--bg-card); color: var(--text)"
              :style="phrase ? 'border-color: rgba(255,255,255,0.25)' : ''"
              placeholder="Ex: She go to school yesterday."
            ></textarea>
            <button @click="correct" :disabled="correcting"
              class="mt-3 w-full rounded-xl border border-white/80 bg-white py-2.5 text-sm font-medium text-black transition hover:bg-white/90 glow-button"
              :class="correcting ? 'opacity-40' : ''"
            >{{ correcting ? 'Correction...' : 'Corriger via pipeline' }}</button>
          </div>

          <transition name="fade">
            <div v-if="correctionResult" class="mt-4 space-y-3">
              <div class="rounded-2xl p-4 text-sm whitespace-pre-line"
                style="border: 1px solid var(--border); background: rgba(0,0,0,0.35); color: var(--text-dim)"
              >
                <p v-if="correctionResult.corrected" class="font-medium" style="color: var(--accent)">→ {{ correctionResult.corrected }}</p>
                <p v-if="correctionResult.feedback" class="mt-2 leading-relaxed">{{ correctionResult.feedback }}</p>
                <div class="mt-3 flex flex-wrap gap-2">
                  <span v-if="correctionResult.error_type !== 'none'" class="text-xs rounded px-2 py-0.5" style="background: var(--warm-dim); color: var(--warm)">{{ correctionResult.error_type }}</span>
                  <span v-if="correctionResult.error_spans?.length" class="text-xs rounded px-2 py-0.5" style="background: var(--pipeline-dim); color: var(--pipeline)">{{ correctionResult.error_spans.length }} span(s)</span>
                  <span class="text-xs rounded px-2 py-0.5" style="background: var(--bg-card); color: var(--text-dim2)">{{ correctionResult.source }}</span>
                </div>
              </div>
              <div v-if="correctionResult.error_type !== 'none'" class="flex items-center gap-3">
                <span class="text-xs" style="color: var(--text-dim2)">Ce feedback est-il utile ?</span>
                <button v-if="correctionRating === null" @click="rateFeedback(true, 'correction')" class="text-sm hover:scale-110 transition-transform">👍</button>
                <button v-if="correctionRating === null" @click="rateFeedback(false, 'correction')" class="text-sm hover:scale-110 transition-transform">👎</button>
                <span v-if="correctionRating !== null" class="text-xs" style="color: var(--success)">{{ correctionRating ? '👍 Merci !' : '👎 Noté.' }}</span>
              </div>
            </div>
          </transition>
        </div>

        <!-- Stats -->
        <div class="glass-card rounded-3xl p-6">
          <div class="traffic-lights">
            <span style="background:#ff5f57"></span>
            <span style="background:#febc2e"></span>
            <span style="background:#28c840"></span>
          </div>
          <h3 class="text-base font-semibold" style="color: var(--text)">Métriques session</h3>
          <p class="mt-1 text-sm" style="color: var(--text-dim)">Latence et résultats de la session courante.</p>
          <div class="mt-4 space-y-2 text-sm">
            <div class="flex items-center justify-between rounded-xl px-4 py-3" style="border: 1px solid var(--border); background: rgba(0,0,0,0.3)">
              <span style="color: var(--text-dim)">Latence moy. LLM</span>
              <span class="font-medium" style="color: var(--text)">{{ statLatency }}</span>
            </div>
            <div class="flex items-center justify-between rounded-xl px-4 py-3" style="border: 1px solid var(--border); background: rgba(0,0,0,0.3)">
              <span style="color: var(--text-dim)">Dernier exercice</span>
              <span class="font-medium" style="color: var(--text)">{{ statExercise }}</span>
            </div>
            <div class="flex items-center justify-between rounded-xl px-4 py-3" style="border: 1px solid var(--border); background: rgba(0,0,0,0.3)">
              <span style="color: var(--text-dim)">Dernière correction</span>
              <span class="font-medium" style="color: var(--text)">{{ statGrade }}</span>
            </div>
            <div v-if="successRate !== null" class="flex items-center justify-between rounded-xl px-4 py-3" style="border: 1px solid var(--border); background: rgba(0,0,0,0.3)">
              <span style="color: var(--text-dim)">Taux de réussite</span>
              <span class="font-medium" style="color: var(--success)">{{ successRate }}</span>
            </div>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <a href="/api/pipeline" target="_blank" rel="noopener"
              class="rounded-lg px-3 py-2 text-xs transition hover:bg-white/8"
              style="border: 1px solid var(--border); color: var(--text-dim)"
            >Pipeline NLP</a>
            <a href="/api/comparison" target="_blank" rel="noopener"
              class="rounded-lg px-3 py-2 text-xs transition hover:bg-white/8"
              style="border: 1px solid var(--border); color: var(--text-dim)"
            >Comparaison APIs</a>
          </div>
        </div>

      </div>
    </section>

    <!-- References footer -->
    <footer class="mt-16">
      <div class="glass-card rounded-3xl p-6 text-sm" style="color: var(--text-dim)">
        <div class="traffic-lights">
          <span style="background:#ff5f57"></span>
          <span style="background:#febc2e"></span>
          <span style="background:#28c840"></span>
        </div>
        <p class="text-xs uppercase tracking-[0.2em]" style="color: var(--text-dim2)">État de l'art</p>
        <h2 class="mt-3 text-xl font-semibold" style="color: var(--text)">Références principales</h2>
        <p class="mt-2" style="color: var(--text-dim)">Synthèse des travaux liés aux LLM, GEC et LMS adaptatifs utilisés dans le mémoire.</p>
        <ul class="mt-4 space-y-2">
          <li><span class="ref-item" data-preview="Alerte sur les hallucinations: justification du fallback et des garde-fous dans le pipeline.">Evaluating LLMs' Assessment of Mixed-Context Hallucination Through the Lens of Summarization</span></li>
          <li><span class="ref-item" data-preview="Inspire le moteur d'adaptativité: progression basée sur historiques et profils.">Adaptive Learning Systems: Personalized Curriculum Design Using LLM-Powered Analytics</span></li>
          <li><span class="ref-item" data-preview="Base pour la correction grammaticale automatique (GEC) et les métriques F0.5.">Automated Grammatical Error Correction for Language Learners</span></li>
          <li><span class="ref-item" data-preview="Cadre pour la personnalisation: feedback explicite et exercices adaptés.">LLMs in Personalized Education: Adaptive Learning Models</span></li>
          <li><span class="ref-item" data-preview="Justifie le fine-tuning ciblé et la collecte de données apprenants.">Training a Bespoke GEC Model for Azerbaijani EFL Learners</span></li>
          <li><span class="ref-item" data-preview="Valide l'architecture modulaire LLM + LMS + base de données.">Revolutionizing Learning Management Systems: Architecture of an AI-Based LMS</span></li>
        </ul>
      </div>
    </footer>

  </main>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { apiConfig, apiFetch } from '../config/api.js'

defineProps({ apiStatusLabel: String, apiStatusClass: String })

const setApiStatus = inject('setApiStatus', () => {})

const phrase = ref('')
const correctionResult = ref(null)
const correcting = ref(false)

const prompt = ref('Cliquez sur "Nouvel exercice" pour commencer.')
const promptLoading = ref(false)
const answerInput = ref('')
const exerciseState = ref(null)
const exerciseFeedback = ref(null)
const level = ref('')
const sessionFocus = ref('')
const counter = ref(0)
const submitting = ref(false)

const latencies = ref([])
const statLatency = ref('—')
const statExercise = ref('—')
const statGrade = ref('—')
const successRate = ref(null)
const correctionRating = ref(null)
const exerciseRating = ref(null)

function getSessionId() {
  let sid = sessionStorage.getItem('mvp_session_id')
  if (!sid) { sid = crypto.randomUUID ? crypto.randomUUID() : `s${Date.now()}`; sessionStorage.setItem('mvp_session_id', sid) }
  return sid
}

function pushLatency(ms) {
  latencies.value.push(ms)
  if (latencies.value.length > 20) latencies.value.shift()
  const avg = latencies.value.reduce((a, b) => a + b, 0) / latencies.value.length
  statLatency.value = `${avg.toFixed(0)} ms`
}

const correct = async () => {
  if (!phrase.value.trim()) return
  correcting.value = true
  correctionResult.value = null
  correctionRating.value = null
  try {
    const r = await apiFetch(apiConfig.endpoints.correct, {
      method: 'POST',
      headers: { 'X-Session-Id': getSessionId() },
      body: JSON.stringify({ phrase: phrase.value })
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail || r.statusText)
    correctionResult.value = data
    setApiStatus(data.source === 'ollama' ? 'ok' : 'fail')
  } catch (e) {
    correctionResult.value = { corrected: `Erreur: ${e.message}`, feedback: '', error_type: 'none', source: 'error', error_spans: [] }
  }
  correcting.value = false
}

const fetchExercise = async () => {
  promptLoading.value = true
  prompt.value = ''
  exerciseFeedback.value = null
  exerciseRating.value = null
  answerInput.value = ''
  const t0 = performance.now()
  try {
    let data = null
    const adaptiveRes = await apiFetch(apiConfig.endpoints.exerciseAdaptive, {
      method: 'POST',
      headers: { 'X-Session-Id': getSessionId() },
      body: JSON.stringify({ user_id: getSessionId() })
    })
    if (adaptiveRes.ok) {
      data = await adaptiveRes.json()
      level.value = data.difficulty ? `difficulté ${data.difficulty}/5` : ''
      sessionFocus.value = data.target_error_type || ''
    } else {
      const fallbackRes = await apiFetch(apiConfig.endpoints.exercise, {
        headers: { 'X-Session-Id': getSessionId() }
      })
      if (!fallbackRes.ok) throw new Error((await fallbackRes.json()).detail || fallbackRes.statusText)
      data = await fallbackRes.json()
      level.value = data.level || ''
      sessionFocus.value = data.recommended_focus || ''
    }
    exerciseState.value = data
    setApiStatus(data.source === 'ollama' ? 'ok' : 'fail')
    counter.value++
    prompt.value = data.prompt
    const dt = performance.now() - t0
    statExercise.value = `${dt.toFixed(0)} ms (${data.source})`
    if (data.source === 'ollama') pushLatency(dt)
  } catch (e) {
    prompt.value = `Impossible de charger: ${e.message}`
    setApiStatus('fail')
  } finally { promptLoading.value = false }
}

const submitAnswer = async () => {
  if (!exerciseState.value || !answerInput.value.trim()) return
  submitting.value = true
  const t0 = performance.now()
  try {
    const r = await apiFetch(apiConfig.endpoints.exerciseGrade, {
      method: 'POST',
      headers: { 'X-Session-Id': getSessionId() },
      body: JSON.stringify({
        sentence: exerciseState.value.sentence,
        blank: exerciseState.value.blank,
        user_answer: answerInput.value.trim()
      })
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail || r.statusText)
    exerciseFeedback.value = data
    const dt = performance.now() - t0
    statGrade.value = `${dt.toFixed(0)} ms (${data.source})`
    if (data.source === 'ollama') pushLatency(dt)
    setApiStatus(data.source === 'ollama' ? 'ok' : 'fail')
  } catch (e) {
    exerciseFeedback.value = { correct: false, feedback: `Erreur: ${e.message}`, error_type: 'none', corrected: '', source: 'error' }
    setApiStatus('fail')
  }
  submitting.value = false
}

const loadObservability = async () => {
  try {
    const sessionRes = await apiFetch(apiConfig.endpoints.session, {
      headers: { 'X-Session-Id': getSessionId() }
    })
    const sessionData = await sessionRes.json()
    if (sessionRes.ok && typeof sessionData.success_rate === 'number') {
      successRate.value = `${Math.round(sessionData.success_rate * 100)}%`
    }
  } catch {}
}

const rateFeedback = async (rating, context) => {
  const isCorrectionCtx = context === 'correction'
  if (isCorrectionCtx) correctionRating.value = rating
  else exerciseRating.value = rating
  const source = isCorrectionCtx ? correctionResult.value : exerciseFeedback.value
  if (!source) return
  try {
    await apiFetch(apiConfig.endpoints.feedbackRate, {
      method: 'POST',
      body: JSON.stringify({
        input_phrase: isCorrectionCtx ? phrase.value : (exerciseState.value?.sentence || ''),
        feedback_text: source.feedback || '',
        error_type: source.error_type || null,
        rating,
        context,
      })
    })
  } catch {}
}

onMounted(() => {
  fetchExercise()
  loadObservability()
})
</script>
